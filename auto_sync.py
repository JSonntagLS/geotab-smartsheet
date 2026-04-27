import mygeotab
import smartsheet
import os
from datetime import datetime, timedelta

def get_sync_bot():
    try:
        print("--- STARTING VIN-BASED SYNC ---")
        smart = smartsheet.Smartsheet(os.getenv("SMARTSHEET_TOKEN"))
        sheet_id = int(os.getenv("SMARTSHEET_ID"))
        sheet = smart.Sheets.get_sheet(sheet_id)
        
        col_map = {col.title.strip(): col.id for col in sheet.columns if col.title}
        
        # Identify our core columns
        vin_id = col_map.get("VIN")
        name_id = col_map.get("Vehicle Name")
        last_week_id = col_map.get("Last Week's Odometer")
        current_id = col_map.get("Current Mileage")
        date_id = col_map.get("Last Sync Date")

        if not vin_id:
            print("CRITICAL: Please add a column named 'VIN' to your Smartsheet first.")
            return

        # Map Smartsheet rows BY VIN instead of Name
        ss_vin_lookup = {}
        for r in sheet.rows:
            vin_cell = next((c for c in r.cells if c.column_id == vin_id), None)
            if vin_cell and vin_cell.value:
                # We use the VIN as the key
                clean_vin = str(vin_cell.value).strip().upper()
                ss_vin_lookup[clean_vin] = r.id

        api = mygeotab.API(username=os.getenv("GEOTAB_USER"), 
                           password=os.getenv("GEOTAB_PASSWORD"), 
                           database=os.getenv("GEOTAB_DB"))
        api.authenticate()
        
        monday_target = (datetime.now() - timedelta(days=7)).replace(hour=0, minute=0, second=0)
        devices = api.get('Device')
        updated_rows = []

        for d in devices:
            # Geotab stores the VIN inside the device object
            g_vin = str(d.get('vin', '')).strip().upper()
            g_name = str(d.get('name', '')).strip()
            
            if g_vin in ss_vin_lookup:
                try:
                    # 1. Fetch Current Odometer
                    curr_logs = api.get('StatusData', search={'deviceSearch': {'id': d['id']}, 'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 'resultsLimit': 1})
                    # 2. Fetch Monday Odometer
                    prev_logs = api.get('StatusData', search={'deviceSearch': {'id': d['id']}, 'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 'toDate': monday_target, 'resultsLimit': 1})

                    curr_m = int(round(curr_logs['data'] / 1609.344, 0)) if curr_logs else "CHECK GPS"
                    prev_m = int(round(prev_logs['data'] / 1609.344, 0)) if prev_logs else curr_m
                    
                    # Construct Row Update
                    new_row = smartsheet.models.Row()
                    new_row.id = ss_vin_lookup[g_vin]
                    
                    # Update Name, Mileage, and Date
                    c_name = smartsheet.models.Cell(column_id=name_id, value=g_name)
                    c_last = smartsheet.models.Cell(column_id=last_week_id, value=prev_m)
                    c_curr = smartsheet.models.Cell(column_id=current_id, value=curr_m)
                    c_date = smartsheet.models.Cell(column_id=date_id, value=datetime.now().strftime("%m/%d/%Y"))
                    
                    new_row.cells = [c_name, c_last, c_curr, c_date]
                    updated_rows.append(new_row)
                    print(f"Matched VIN {g_vin[-6:]}: Renaming Smartsheet to '{g_name}'")

                except Exception as e:
                    print(f"Error processing VIN {g_vin}: {e}")

        if updated_rows:
            smart.Sheets.update_rows(sheet_id, updated_rows)
            print("SYNC SUCCESSFUL")
        else:
            print("No VIN matches found. Ensure the VINs in Smartsheet match Geotab exactly.")

    except Exception as e:
        print(f"CRITICAL ERROR: {str(e)}")

if __name__ == "__main__":
    get_sync_bot()

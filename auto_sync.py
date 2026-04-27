import mygeotab
import smartsheet
import os
from datetime import datetime, timedelta

def get_sync_bot():
    try:
        print("--- STARTING VIN-ANCHORED SYNC ---")
        smart = smartsheet.Smartsheet(os.getenv("SMARTSHEET_TOKEN"))
        sheet_id = int(os.getenv("SMARTSHEET_ID"))
        sheet = smart.Sheets.get_sheet(sheet_id)
        
        col_map = {col.title.strip(): col.id for col in sheet.columns if col.title}
        
        # Identification Columns
        vin_id = col_map.get("VIN")
        name_id = col_map.get("Vehicle Name")
        last_week_id = col_map.get("Last Week's Odometer")
        current_id = col_map.get("Current Mileage")
        date_id = col_map.get("Last Sync Date")

        if not vin_id:
            print("ERROR: Could not find 'VIN' column. Check spelling/caps.")
            return

        # Build lookup: Mapping VIN -> Row ID
        ss_vin_lookup = {}
        for r in sheet.rows:
            v_cell = next((c for c in r.cells if c.column_id == vin_id), None)
            if v_cell and v_cell.value:
                ss_vin_lookup[str(v_cell.value).strip().upper()] = r.id

        print(f"Found {len(ss_vin_lookup)} VINs to sync in Smartsheet.")

        api = mygeotab.API(username=os.getenv("GEOTAB_USER"), 
                           password=os.getenv("GEOTAB_PASSWORD"), 
                           database=os.getenv("GEOTAB_DB"))
        api.authenticate()
        
        monday_target = (datetime.now() - timedelta(days=7)).replace(hour=0, minute=0, second=0)
        devices = api.get('Device')
        updated_rows = []

        for d in devices:
            g_vin = str(d.get('vin', '')).strip().upper()
            g_name = str(d.get('name', '')).strip()
            
            # Check if this vehicle's VIN is in our Smartsheet list
            if g_vin in ss_vin_lookup:
                try:
                    # Fetch Mileages
                    curr_logs = api.get('StatusData', search={'deviceSearch': {'id': d['id']}, 'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 'resultsLimit': 1})
                    prev_logs = api.get('StatusData', search={'deviceSearch': {'id': d['id']}, 'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 'toDate': monday_target, 'resultsLimit': 1})

                    curr_m = int(round(curr_logs['data'] / 1609.344, 0)) if curr_logs else "CHECK GPS"
                    prev_m = int(round(prev_logs['data'] / 1609.344, 0)) if prev_logs else curr_m

                    # Update Row
                    new_row = smartsheet.models.Row()
                    new_row.id = ss_vin_lookup[g_vin]
                    
                    # This updates Name, Mileages, and Date in one shot
                    cells = [
                        smartsheet.models.Cell(column_id=name_id, value=g_name),
                        smartsheet.models.Cell(column_id=last_week_id, value=prev_m),
                        smartsheet.models.Cell(column_id=current_id, value=curr_m),
                        smartsheet.models.Cell(column_id=date_id, value=datetime.now().strftime("%Y-%m-%d"))
                    ]
                    new_row.cells = cells
                    updated_rows.append(new_row)
                    print(f"Matched {g_vin[-6:]}: Updated to '{g_name}' with {curr_m} miles.")

                except Exception as e:
                    print(f"Skipping {g_vin}: {e}")

        if updated_rows:
            result = smart.Sheets.update_rows(sheet_id, updated_rows)
            print(f"FINAL STATUS: {result.message}")
        else:
            print("No VIN matches found between Smartsheet and Geotab.")

    except Exception as e:
        print(f"CRITICAL SYSTEM ERROR: {str(e)}")

if __name__ == "__main__":
    get_sync_bot()

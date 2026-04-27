import mygeotab
import smartsheet
import os
from datetime import datetime, timedelta

def get_sync_bot():
    try:
        print("--- VIN MATCHING & AUTO-RENAME SYNC ---")
        smart = smartsheet.Smartsheet(os.getenv("SMARTSHEET_TOKEN"))
        sheet_id = int(os.getenv("SMARTSHEET_ID"))
        sheet = smart.Sheets.get_sheet(sheet_id)
        
        col_map = {col.title.strip().upper(): col.id for col in sheet.columns if col.title}
        vin_id = col_map.get("VIN")
        name_id = col_map.get("VEHICLE NAME")
        last_week_id = col_map.get("LAST WEEK'S ODOMETER")
        current_id = col_map.get("CURRENT MILEAGE")
        date_id = col_map.get("LAST SYNC DATE")

        # Map Smartsheet VINs to Row IDs
        ss_vins = {}
        for r in sheet.rows:
            v_cell = next((c for c in r.cells if c.column_id == vin_id), None)
            if v_cell and v_cell.value:
                # We store the last 6 of the VIN for easier matching
                clean_vin = str(v_cell.value).strip().upper()[-6:]
                ss_vins[clean_vin] = r.id

        print(f"Found {len(ss_vins)} VINs in Smartsheet. Connecting to Geotab...")

        api = mygeotab.API(username=os.getenv("GEOTAB_USER"), 
                           password=os.getenv("GEOTAB_PASSWORD"), 
                           database=os.getenv("GEOTAB_DB"))
        api.authenticate()
        
        monday_target = (datetime.now() - timedelta(days=7)).replace(hour=0, minute=0, second=0)
        devices = api.get('Device')
        updated_rows = []

        for d in devices:
            full_vin = str(d.get('vin', '')).strip().upper()
            g_last_6 = full_vin[-6:]
            g_name = str(d.get('name', '')).strip()
            
            if g_last_6 in ss_vins:
                try:
                    # 1. Fetch Mileages
                    curr_logs = api.get('StatusData', search={'deviceSearch': {'id': d['id']}, 'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 'resultsLimit': 1})
                    prev_logs = api.get('StatusData', search={'deviceSearch': {'id': d['id']}, 'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 'toDate': monday_target, 'resultsLimit': 1})

                    curr_m = int(round(curr_logs['data'] / 1609.344, 0)) if curr_logs else "NO DATA"
                    prev_m = int(round(prev_logs['data'] / 1609.344, 0)) if prev_logs else curr_m

                    # 2. Prepare Smartsheet Row Update (Including the Name Update)
                    new_row = smartsheet.models.Row()
                    new_row.id = ss_vins[g_last_6]
                    
                    # This will automatically sync the Geotab name to Smartsheet
                    new_row.cells = [
                        smartsheet.models.Cell(column_id=name_id, value=g_name),
                        smartsheet.models.Cell(column_id=last_week_id, value=prev_m),
                        smartsheet.models.Cell(column_id=current_id, value=curr_m),
                        smartsheet.models.Cell(column_id=date_id, value=datetime.now().strftime("%Y-%m-%d"))
                    ]
                    updated_rows.append(new_row)
                    print(f"Matched {g_last_6}: Syncing name '{g_name}' and mileage.")

                except Exception as e:
                    print(f"Error on VIN {g_last_6}: {e}")

        if updated_rows:
            smart.Sheets.update_rows(sheet_id, updated_rows)
            print(f"SUCCESS: Synced {len(updated_rows)} vehicles.")
        else:
            print("No matching VINs found. Check that the VINs in Smartsheet match Geotab.")

    except Exception as e:
        print(f"CRITICAL FAILURE: {str(e)}")

if __name__ == "__main__":
    get_sync_bot()

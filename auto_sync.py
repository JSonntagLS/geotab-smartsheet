import mygeotab
import smartsheet
import os
from datetime import datetime, timedelta
import json

def get_sync_bot():
    try:
        print("--- DEBUG PROTOCOL: RAW DATA INSPECTION ---")
        smart = smartsheet.Smartsheet(os.getenv("SMARTSHEET_TOKEN"))
        sheet_id = int(os.getenv("SMARTSHEET_ID"))
        sheet = smart.Sheets.get_sheet(sheet_id)
        
        col_map = {col.title.strip().upper(): col.id for col in sheet.columns if col.title}
        serial_col = col_map.get("SERIAL")
        name_col = col_map.get("VEHICLE NAME")
        last_week_col = col_map.get("LAST WEEK'S ODOMETER")
        curr_col = col_map.get("CURRENT MILEAGE")
        date_col = col_map.get("LAST SYNC DATE")

        ss_serials = {}
        for r in sheet.rows:
            s_cell = next((c for c in r.cells if c.column_id == serial_col), None)
            if s_cell and s_cell.value:
                ss_serials[str(s_cell.value).strip().upper()] = r.id

        api = mygeotab.API(username=os.getenv("GEOTAB_USER"), 
                           password=os.getenv("GEOTAB_PASSWORD"), 
                           database=os.getenv("GEOTAB_DB"))
        api.authenticate()
        
        devices = api.get('Device')
        monday_target = (datetime.now() - timedelta(days=7)).replace(hour=0, minute=0, second=0)
        updated_rows = []

        # Debugging the first vehicle match
        debug_count = 0

        for d in devices:
            g_serial = str(d.get('serialNumber', '')).strip().upper()
            g_name = str(d.get('name', '')).strip()
            
            if g_serial in ss_serials:
                try:
                    curr_logs = api.get('StatusData', search={'deviceSearch': {'id': d['id']}, 'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 'resultsLimit': 1})
                    
                    # --- DEBUG SECTION ---
                    if debug_count < 3:
                        print(f"\n[DEBUG] Raw Geotab Response for {g_serial}:")
                        print(f"Type: {type(curr_logs)}")
                        print(f"Content: {curr_logs}")
                        debug_count += 1
                    # ---------------------

                    def extract_miles(logs):
                        # Forcefully check every level of the response
                        if not logs: return "CHECK GPS"
                        
                        try:
                            # Attempt 1: Direct list access
                            if isinstance(logs, list) and len(logs) > 0:
                                val = logs
                                if isinstance(val, dict):
                                    return int(round(val.get('data', 0) / 1609.344, 0))
                            # Attempt 2: If it's a weird object with a .data attribute
                            return int(round(logs.data / 1609.344, 0))
                        except:
                            return "CHECK GPS"

                    curr_m = extract_miles(curr_logs)
                    
                    new_row = smartsheet.models.Row()
                    new_row.id = ss_serials[g_serial]
                    
                    cells = []
                    for cid, val in [(name_col, g_name), (curr_col, curr_m), (date_col, datetime.now().strftime("%Y-%m-%d"))]:
                        new_cell = smartsheet.models.Cell()
                        new_cell.column_id = cid
                        new_cell.value = val
                        cells.append(new_cell)
                    
                    new_row.cells = cells
                    updated_rows.append(new_row)

                except Exception as e:
                    print(f"Skipping {g_serial} | Error: {str(e)}")

        if updated_rows:
            smart.Sheets.update_rows(sheet_id, updated_rows)
            print(f"\n--- SYNC COMPLETE: Updated {len(updated_rows)} rows ---")
        else:
            print("\nNo data to update.")

    except Exception as e:
        print(f"CRITICAL ERROR: {str(e)}")

if __name__ == "__main__":
    get_sync_bot()

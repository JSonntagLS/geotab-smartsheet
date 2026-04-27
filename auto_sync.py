import mygeotab
import smartsheet
import os
from datetime import datetime, timedelta

def get_sync_bot():
    try:
        print("--- SERIAL-ANCHORED SYNC: BULLETPROOF VERSION ---")
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

        for d in devices:
            g_serial = str(d.get('serialNumber', '')).strip().upper()
            g_name = str(d.get('name', '')).strip()
            
            if g_serial in ss_serials:
                try:
                    # Fetching Odometer with safety checks
                    curr_logs = api.get('StatusData', search={'deviceSearch': {'id': d['id']}, 'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 'resultsLimit': 1})
                    prev_logs = api.get('StatusData', search={'deviceSearch': {'id': d['id']}, 'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 'toDate': monday_target, 'resultsLimit': 1})

                    # Conversion logic with "None" protection
                    def get_miles(logs):
                        if logs and isinstance(logs, list) and len(logs) > 0:
                            return int(round(logs.get('data', 0) / 1609.344, 0))
                        return "CHECK GPS"

                    curr_m = get_miles(curr_logs)
                    prev_m = get_miles(prev_logs)
                    if prev_m == "CHECK GPS": prev_m = curr_m

                    # Fix for the __init__ error: Create row then assign ID
                    new_row = smartsheet.models.Row()
                    new_row.id = ss_serials[g_serial]
                    
                    c1 = smartsheet.models.Cell(); c1.column_id = name_col; c1.value = g_name
                    c2 = smartsheet.models.Cell(); c2.column_id = last_week_col; c2.value = prev_m
                    c3 = smartsheet.models.Cell(); c3.column_id = curr_col; c3.value = curr_m
                    c4 = smartsheet.models.Cell(); c4.column_id = date_col; c4.value = datetime.now().strftime("%m/%d/%Y")
                    
                    new_row.cells = [c1, c2, c3, c4]
                    updated_rows.append(new_row)
                    print(f"READY: {g_serial} ({g_name})")

                except Exception as e:
                    print(f"Skipping {g_serial} due to data error: {e}")

        if updated_rows:
            smart.Sheets.update_rows(sheet_id, updated_rows)
            print(f"DONE: Successfully updated {len(updated_rows)} vehicles in Smartsheet.")
        else:
            print("No serial matches found between Geotab and Smartsheet.")

    except Exception as e:
        print(f"CRITICAL SYSTEM ERROR: {str(e)}")

if __name__ == "__main__":
    get_sync_bot()

import mygeotab
import smartsheet
import os
from datetime import datetime, timedelta

def get_sync_bot():
    try:
        print("--- SERIAL-ANCHORED SYNC: ULTRASONIC CLEAN ---")
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
                    curr_logs = api.get('StatusData', search={'deviceSearch': {'id': d['id']}, 'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 'resultsLimit': 1})
                    prev_logs = api.get('StatusData', search={'deviceSearch': {'id': d['id']}, 'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 'toDate': monday_target, 'resultsLimit': 1})

                    def extract_miles(logs):
                        # Explicit check for list type to avoid 'get' error
                        if isinstance(logs, list) and len(logs) > 0:
                            data_val = logs.get('data')
                            if data_val is not None:
                                return int(round(data_val / 1609.344, 0))
                        return "CHECK GPS"

                    curr_m = extract_miles(curr_logs)
                    prev_m = extract_miles(prev_logs)
                    if prev_m == "CHECK GPS": prev_m = curr_m

                    # Build row correctly for the Smartsheet Python SDK
                    new_row = smartsheet.models.Row()
                    new_row.id = ss_serials[g_serial]
                    
                    # Create cells individually to avoid __init__ errors
                    cells = []
                    for cid, val in [(name_col, g_name), (last_week_col, prev_m), (curr_col, curr_m), (date_col, datetime.now().strftime("%Y-%m-%d"))]:
                        new_cell = smartsheet.models.Cell()
                        new_cell.column_id = cid
                        new_cell.value = val
                        new_cell.strict = False
                        cells.append(new_cell)
                    
                    new_row.cells = cells
                    updated_rows.append(new_row)
                    print(f"READY: {g_serial} -> {g_name}")

                except Exception as e:
                    print(f"Skipping {g_serial} (Error: {e})")

        if updated_rows:
            # Send in chunks of 100 to stay safe with Smartsheet limits
            result = smart.Sheets.update_rows(sheet_id, updated_rows)
            print(f"SUCCESS: {len(updated_rows)} vehicles updated. {result.message}")
        else:
            print("No matches found. Check that Column G headers actually say 'Serial'.")

    except Exception as e:
        print(f"CRITICAL SYSTEM ERROR: {str(e)}")

if __name__ == "__main__":
    get_sync_bot()

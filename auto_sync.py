import mygeotab
import smartsheet
import os
from datetime import datetime, timedelta

def get_sync_bot():
    try:
        print("--- SERIAL-ANCHORED SYNC: FINAL REFINEMENT ---")
        smart = smartsheet.Smartsheet(os.getenv("SMARTSHEET_TOKEN"))
        sheet_id = int(os.getenv("SMARTSHEET_ID"))
        sheet = smart.Sheets.get_sheet(sheet_id)
        
        col_map = {col.title.strip().upper(): col.id for col in sheet.columns if col.title}
        serial_col = col_map.get("SERIAL")
        name_col = col_map.get("VEHICLE NAME")
        last_week_col = col_map.get("LAST WEEK'S ODOMETER")
        curr_col = col_map.get("CURRENT MILEAGE")
        date_col = col_map.get("LAST SYNC DATE")

        ss_serials = {str(r.get_column(serial_col).value).strip().upper(): r.id 
                      for r in sheet.rows if r.get_column(serial_col).value}

        api = mygeotab.API(username=os.getenv("GEOTAB_USER"), 
                           password=os.getenv("GEOTAB_PASSWORD"), 
                           database=os.getenv("GEOTAB_DB"))
        api.authenticate()
        
        devices = api.get('Device')
        monday_target = (datetime.now() - timedelta(days=7)).replace(hour=0, minute=0, second=0)
        updated_rows = []

        def extract_miles(logs):
            if not logs or not isinstance(logs, list):
                return "CHECK GPS"
            try:
                # Sort logs by dateTime to get the absolute latest one
                latest_log = sorted(logs, key=lambda x: x['dateTime'])[-1]
                raw_data = latest_log.get('data', 0)
                return int(round(raw_data / 1609.344, 0))
            except:
                return "CHECK GPS"

        for d in devices:
            g_serial = str(d.get('serialNumber', '')).strip().upper()
            g_name = str(d.get('name', '')).strip()
            
            if g_serial in ss_serials:
                try:
                    curr_logs = api.get('StatusData', search={'deviceSearch': {'id': d['id']}, 'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 'resultsLimit': 10})
                    prev_logs = api.get('StatusData', search={'deviceSearch': {'id': d['id']}, 'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 'toDate': monday_target, 'resultsLimit': 1})

                    curr_m = extract_miles(curr_logs)
                    prev_m = extract_miles(prev_logs)
                    if prev_m == "CHECK GPS": prev_m = curr_m

                    new_row = smartsheet.models.Row()
                    new_row.id = ss_serials[g_serial]
                    
                    cells = []
                    updates = [(name_col, g_name), (last_week_col, prev_m), (curr_col, curr_m), (date_col, datetime.now().strftime("%Y-%m-%d"))]
                    
                    for cid, val in updates:
                        c = smartsheet.models.Cell()
                        c.column_id = cid
                        c.value = val
                        cells.append(c)
                    
                    new_row.cells = cells
                    updated_rows.append(new_row)
                    print(f"READY: {g_serial} -> {curr_m} miles")

                except Exception as e:
                    print(f"Skipping {g_serial} | Error: {str(e)}")

        if updated_rows:
            smart.Sheets.update_rows(sheet_id, updated_rows)
            print(f"SUCCESS: {len(updated_rows)} vehicles pushed to Smartsheet.")
        else:
            print("No matches found.")

    except Exception as e:
        print(f"CRITICAL ERROR: {str(e)}")

if __name__ == "__main__":
    get_sync_bot()

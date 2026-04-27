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
                        # Geotab returns a list of dictionaries; we need to access the first item properly
                        if logs and len(logs) > 0:
                            # logs is the dictionary, .get('data') gets the value
                            data_val = logs.get('data')
                            if data_val is not None:
                                return int(round(data_val / 1609.344, 0))
                        return "CHECK GPS"

                    curr_m = extract_miles(curr_logs)
                    prev_m = extract_miles(prev_logs)
                    if prev_m == "CHECK GPS": prev_m = curr_m

                    new_row = smartsheet.models.Row()
                    new_row.id = ss_serials[g_serial]
                    
                    new_row.cells = [
                        smartsheet.models.Cell(column_id=name_col, value=g_name),
                        smartsheet.models.Cell(column_id=last_week_col, value=prev_m),
                        smartsheet.models.Cell(column_id=curr_col, value=curr_m),
                        smartsheet.models.Cell(column_id=date_col, value=datetime.now().strftime("%Y-%m-%d"))
                    ]
                    updated_rows.append(new_row)
                    print(f"READY: {g_serial} -> {g_name}")

                except Exception as e:
                    print(f"Skipping {g_serial} (Error: {e})")

        if updated_rows:
            smart.Sheets.update_rows(sheet_id, updated_rows)
            print(f"SUCCESS: {len(updated_rows)} vehicles updated.")
        else:
            print("No matches found.")

    except Exception as e:
        print(f"SYSTEM ERROR: {str(e)}")

if __name__ == "__main__":
    get_sync_bot()

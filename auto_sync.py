import mygeotab
import smartsheet
import os
from datetime import datetime, timedelta

def get_sync_bot():
    try:
        print("--- SYNC REPAIR V2: FIXING DATA PARSING ---")
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
        # Target exactly 7 days ago for the baseline
        monday_target = (datetime.now() - timedelta(days=7)).replace(hour=0, minute=0, second=0)
        updated_rows = []

        for d in devices:
            g_serial = str(d.get('serialNumber', '')).strip().upper()
            g_name = str(d.get('name', 'Unknown Device')).strip()
            
            if g_serial in ss_serials:
                try:
                    # 1. Get Live Odometer (using resultsLimit to get only the most recent)
                    curr_logs = api.get('StatusData', search={'deviceSearch': {'id': d['id']}, 'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 'resultsLimit': 1})
                    
                    # 2. Get Odometer from 7 days ago
                    prev_logs = api.get('StatusData', search={'deviceSearch': {'id': d['id']}, 'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 'toDate': monday_target.isoformat(), 'resultsLimit': 1})

                    def parse_val(logs):
                        # Geotab returns a LIST. We need to check if the list has items, then grab the first one.
                        if isinstance(logs, list) and len(logs) > 0:
                            # logs is the dictionary we need to .get('data') from
                            return int(round(logs.get('data', 0) / 1609.344, 0))
                        return None

                    live_odometer = parse_val(curr_logs)
                    past_odometer = parse_val(prev_logs)

                    # Fallbacks to ensure Smartsheet doesn't get a "Null/None" value
                    if live_odometer is None:
                        live_odometer = "CHECK GPS"
                    if past_odometer is None:
                        past_odometer = 0 # Or live_odometer if you prefer 0 miles driven vs 0 total
                    
                    new_row = smartsheet.models.Row()
                    new_row.id = ss_serials[g_serial]
                    
                    updates = [
                        (name_col, g_name), 
                        (last_week_col, past_odometer), 
                        (curr_col, live_odometer), 
                        (date_col, datetime.now().strftime("%Y-%m-%d"))
                    ]
                    
                    cells = []
                    for cid, val in updates:
                        c = smartsheet.models.Cell()
                        c.column_id = cid
                        c.value = val
                        # Force cell to be 'None-safe'
                        if c.value is None: c.value = ""
                        cells.append(c)
                    
                    new_row.cells = cells
                    updated_rows.append(new_row)
                    print(f"READY: {g_serial} | Live: {live_odometer} | Last Week: {past_odometer}")

                except Exception as e:
                    print(f"Skipping {g_serial} | Error: {str(e)}")

        if updated_rows:
            # Batch updates to avoid hitting Smartsheet API limits
            smart.Sheets.update_rows(sheet_id, updated_rows)
            print(f"SUCCESS: {len(updated_rows)} vehicles pushed to Smartsheet.")

    except Exception as e:
        print(f"CRITICAL ERROR: {str(e)}")

if __name__ == "__main__":
    get_sync_bot()

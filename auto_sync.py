import mygeotab
import smartsheet
import os
from datetime import datetime, timedelta

def get_sync_bot():
    try:
        print("--- FINAL DATA EXTRACTION FIX ---")
        smart = smartsheet.Smartsheet(os.getenv("SMARTSHEET_TOKEN"))
        sheet_id = int(os.getenv("SMARTSHEET_ID"))
        
        sheet = smart.Sheets.get_sheet(sheet_id)
        print(f"Connected to: '{sheet.name}'")

        col_map = {col.title.strip(): col.id for col in sheet.columns}
        name_id = col_map.get("Vehicle Name")
        last_week_id = col_map.get("Last Week's Odometer")
        current_id = col_map.get("Current Mileage")
        date_id = col_map.get("Last Sync Date")
        ser_id = col_map.get("Serial")

        ss_rows_lookup = {str(r.cells.value).strip().upper(): r.id for r in sheet.rows if r.cells.value}

        api = mygeotab.API(username=os.getenv("GEOTAB_USER"), 
                           password=os.getenv("GEOTAB_PASSWORD"), 
                           database=os.getenv("GEOTAB_DB"))
        api.authenticate()
        
        today = datetime.now()
        monday_start = (today - timedelta(days=today.weekday() + 7)).replace(hour=0, minute=0, second=0, microsecond=0)
        monday_end = monday_start + timedelta(days=2)

        devices = api.get('Device')
        updated_rows = []

        for d in devices:
            g_name = str(d.get('name', '')).strip().upper()
            if g_name in ss_rows_lookup:
                # 1. Fetch Current Odometer
                live_logs = api.get('StatusData', search={
                    'deviceSearch': {'id': d.get('id')}, 
                    'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 
                    'resultsLimit': 1
                })
                current_miles = round(live_logs['data'] / 1609.344, 0) if live_logs else 0

                # 2. Fetch Historical Monday Odometer
                hist_logs = api.get('StatusData', search={
                    'deviceSearch': {'id': d.get('id')}, 
                    'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 
                    'fromDate': monday_start, 
                    'toDate': monday_end
                })
                
                if hist_logs:
                    earliest_log = min(hist_logs, key=lambda x: x['dateTime'])
                    start_miles = round(earliest_log['data'] / 1609.344, 0)
                else:
                    start_miles = current_miles 

                # 3. Construct Update
                new_row = smartsheet.models.Row()
                new_row.id = ss_rows_lookup[g_name]
                
                # Manual Cell Population to avoid __init__ errors
                c1, c2, c3, c4 = smartsheet.models.Cell(), smartsheet.models.Cell(), smartsheet.models.Cell(), smartsheet.models.Cell()
                c1.column_id, c1.value = last_week_id, int(start_miles)
                c2.column_id, c2.value = current_id, int(current_miles)
                c3.column_id, c3.value = ser_id, str(d.get('serialNumber', ''))
                c4.column_id, c4.value = date_id, today.strftime("%Y-%m-%d")
                
                new_row.cells.extend([c1, c2, c3, c4])
                updated_rows.append(new_row)
                print(f"Prepared: {g_name} | {start_miles} -> {current_miles}")

        if updated_rows:
            result = smart.Sheets.update_rows(sheet_id, updated_rows)
            print(f"SYNC COMPLETE: {result.message}")
        else:
            print("No matches found.")

    except Exception as e:
        print(f"CRITICAL ERROR: {str(e)}")

if __name__ == "__main__":
    get_sync_bot()

import mygeotab
import smartsheet
import os
from datetime import datetime, timedelta
import time

def get_sync_bot():
    try:
        print("--- STARTING DEEP SYNC ---")
        
        # 1. Smartsheet Setup
        smart = smartsheet.Smartsheet(os.getenv("SMARTSHEET_TOKEN"))
        sheet_id = int(os.getenv("SMARTSHEET_ID"))
        sheet = smart.Sheets.get_sheet(sheet_id)
        
        # Map columns by TITLE to be index-independent
        col_map = {col.title.strip(): col.id for col in sheet.columns if col.title}
        
        name_col_id = col_map.get("Vehicle Name")
        mil_col_id = col_map.get("Current Mileage")
        last_week_col_id = col_map.get("Last Week's Odometer")
        date_col_id = col_map.get("Last Sync Date")

        # 2. Build Lookup (Finding the 'Vehicle Name' cell specifically)
        ss_rows_lookup = {}
        for r in sheet.rows:
            name_cell = next((c for c in r.cells if c.column_id == name_col_id), None)
            if name_cell and name_cell.value:
                clean_name = str(name_cell.value).strip().upper()
                ss_rows_lookup[clean_name] = r.id

        print(f"Mapped {len(ss_rows_lookup)} vehicles from Smartsheet.")

        # 3. Geotab Setup & Time Windows
        api = mygeotab.API(username=os.getenv("GEOTAB_USER"), 
                           password=os.getenv("GEOTAB_PASSWORD"), 
                           database=os.getenv("GEOTAB_DB"))
        api.authenticate()
        
        today = datetime.now()
        # Monday 4/20/2026 at 12:00 AM
        monday_start = (today - timedelta(days=today.weekday() + 7)).replace(hour=0, minute=0, second=0, microsecond=0)
        monday_end_window = monday_start + timedelta(days=2)

        devices = api.get('Device')
        
        # Get Live Readings
        raw_odo = api.get('StatusData', search={'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 'resultsLimit': len(devices)})
        live_mileage = {item['device']['id']: round(item['data'] / 1609.344, 0) for item in raw_odo}

        updated_rows = []
        for d in devices:
            g_name = str(d['name']).strip().upper()
            
            if g_name in ss_rows_lookup:
                # Get Historical Monday Data
                hist_logs = api.get('StatusData', search={
                    'deviceSearch': {'id': d['id']},
                    'diagnosticSearch': {'id': 'DiagnosticOdometerId'},
                    'fromDate': monday_start,
                    'toDate': monday_end_window
                })

                if hist_logs:
                    earliest_log = min(hist_logs, key=lambda x: x['dateTime'])
                    start_miles = round(earliest_log['data'] / 1609.344, 0)
                else:
                    start_miles = 0
                
                current_miles = live_mileage.get(d['id'], 0)

                # Build the Row Update
                new_row = smartsheet.models.Row(id=ss_rows_lookup[g_name])
                new_row.cells.append(smartsheet.models.Cell(column_id=last_week_col_id, value=int(start_miles)))
                new_row.cells.append(smartsheet.models.Cell(column_id=mil_col_id, value=int(current_miles)))
                new_row.cells.append(smartsheet.models.Cell(column_id=date_col_id, value=today.strftime("%Y-%m-%d")))
                
                updated_rows.append(new_row)
                print(f"Prepared update for: {g_name}")

        # 4. Push Updates
        if updated_rows:
            result = smart.Sheets.update_rows(sheet_id, updated_rows)
            print(f"Smartsheet Sync Complete: {result.message}")
        else:
            print("No matching vehicle names found between Geotab and Smartsheet.")

    except Exception as e:
        print(f"Sync Failed: {e}")

if __name__ == "__main__":
    get_sync_bot()

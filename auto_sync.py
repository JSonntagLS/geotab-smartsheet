import mygeotab
import smartsheet
import pandas as pd
from datetime import datetime, timedelta
import os
import time

def get_sync_bot():
    try:
        print("Robot waking up for Deep Search...")
        
        api = mygeotab.API(username=os.getenv("GEOTAB_USER"), 
                           password=os.getenv("GEOTAB_PASSWORD"), 
                           database=os.getenv("GEOTAB_DB"))
        api.authenticate()

        # 1. SET THE ANCHOR: Last Monday at 12:00 AM
        today = datetime.now()
        monday_start = (today - timedelta(days=today.weekday() + 7)).replace(hour=0, minute=0, second=0, microsecond=0)
        # Extend the window to 48 hours to ensure we catch a log
        monday_end_window = monday_start + timedelta(days=2)

        devices = api.get('Device')
        smart = smartsheet.Smartsheet(os.getenv("SMARTSHEET_TOKEN"))
        sheet_id = int(os.getenv("SMARTSHEET_ID"))
        sheet = smart.Sheets.get_sheet(sheet_id)
        
        col_map = {col.title.strip(): col.id for col in sheet.columns}
        mil_col_id = col_map.get("Current Mileage")
        last_week_col_id = col_map.get("Last Week's Odometer")
        date_col_id = col_map.get("Last Sync Date")
        primary_col_id = next((col.id for col in sheet.columns if col.primary), None)

        ss_rows_lookup = {str(r.cells.value).strip().upper(): r.id for r in sheet.rows if r.cells.value}

        # Get LIVE readings (Current)
        raw_odo = api.get('StatusData', search={'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 'resultsLimit': len(devices)})
        live_mileage = {item['device']['id']: round(item['data'] / 1609.344, 0) for item in raw_odo}

        updated_rows = []
        for d in devices:
            name = str(d['name']).strip().upper()
            if name in ss_rows_lookup:
                # 2. DEEP SEARCH: Get ALL logs for the window and take the first one
                # This is more reliable than 'resultsLimit': 1 for historical data
                hist_logs = api.get('StatusData', search={
                    'deviceSearch': {'id': d['id']},
                    'diagnosticSearch': {'id': 'DiagnosticOdometerId'},
                    'fromDate': monday_start,
                    'toDate': monday_end_window
                })

                # Sort logs by date to get the earliest one in our window
                if hist_logs:
                    earliest_log = min(hist_logs, key=lambda x: x['dateTime'])
                    start_miles = round(earliest_log['data'] / 1609.344, 0)
                else:
                    start_miles = 0
                
                current_miles = live_mileage.get(d['id'], 0)

                new_row = smartsheet.models.Row()
                new_row.id = ss_rows_lookup[name]
                
                c1 = smartsheet.models.Cell(column_id=last_week_col_id, value=int(start_miles))
                c2 = smartsheet.models.Cell(column_id=mil_col_id, value=int(current_miles))
                c3 = smartsheet.models.Cell(column_id=date_col_id, value=today.strftime("%m/%d/%Y %H:%M"))
                
                new_row.cells.extend([c1, c2, c3])
                updated_rows.append(new_row)
                
                # Small pause to be kind to the API
                time.sleep(0.1)

        if updated_rows:
            smart.Sheets.update_rows(sheet_id, updated_rows)
            print(f"Successfully synced {len(updated_rows)} vehicles with Deep Search.")
            
    except Exception as e:
        print(f"Robot Sync Failed: {e}")

if __name__ == "__main__":
    get_sync_bot()

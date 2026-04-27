import mygeotab
import smartsheet
import os
from datetime import datetime, timedelta

def get_sync_bot():
    try:
        print("--- STARTING FINAL DATA RECOVERY ---")
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

        ss_rows_lookup = {}
        for r in sheet.rows:
            name_cell = next((c for c in r.cells if c.column_id == name_id), None)
            if name_cell and name_cell.value:
                ss_rows_lookup[str(name_cell.value).strip().upper()] = r.id

        api = mygeotab.API(username=os.getenv("GEOTAB_USER"), 
                           password=os.getenv("GEOTAB_PASSWORD"), 
                           database=os.getenv("GEOTAB_DB"))
        api.authenticate()
        
        today = datetime.now()
        # Look back to last Monday
        monday_start = (today - timedelta(days=today.weekday() + 7)).replace(hour=0, minute=0, second=0, microsecond=0)
        monday_end = monday_start + timedelta(days=2)

        devices = api.get('Device')
        updated_rows = []

        for d in devices:
            g_name = str(d.get('name', '')).strip().upper()
            if g_name in ss_rows_lookup:
                # 1. Fetch Current Odometer
                live_data = api.get('StatusData', search={
                    'deviceSearch': {'id': d.get('id')}, 
                    'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 
                    'resultsLimit': 1
                })
                current_miles = round(live_data.get('data', 0) / 1609.344, 0) if live_data else 0

                # 2. Fetch Historical Monday Odometer
                hist_logs = api.get('StatusData', search={
                    'deviceSearch': {'id': d.get('id')}, 
                    'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 
                    'fromDate': monday_start, 
                    'toDate': monday_end
                })
                
                # Calculate historical starting point
                if hist_logs:
                    # Find the earliest log in the window
                    earliest_log = min(hist_logs, key=lambda x: x.get('dateTime'))
                    start_miles = round(earliest_log.get('data', 0) / 1609.344, 0)
                else:
                    start_miles = current_miles # Fallback to current if no historical log found

                # 3. Build Row Update
                new_row = smartsheet.models.Row()
                new_row.id = ss_rows_lookup[g_name]
                
                # Add cells one by one to ensure the SDK accepts them
                cells = []
                for col_id, val in [(last_week_id, start_miles), (current_id, current_miles), 
                                    (ser_id, d.get('serialNumber', '')), (date_id, today.strftime("%Y-%m-%d"))]:
                    new_cell = smartsheet.models.Cell()
                    new_cell.column_id = col_id
                    new_cell.value = val
                    cells.append(new_cell)
                
                new_row.cells = cells
                updated_rows.append(new_row)
                print(f"Ready: {g_name} | Start: {start_miles} | Now: {current_miles}")

        if updated_rows:
            # Batch update for efficiency
            result = smart.Sheets.update_rows(sheet_id, updated_rows)
            print(f"SYNC SUCCESS: {result.message}")
        else:
            print("No matching vehicles to update.")

    except Exception as e:
        print(f"CRITICAL ERROR: {str(e)}")

if __name__ == "__main__":
    get_sync_bot()

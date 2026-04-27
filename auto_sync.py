import mygeotab
import smartsheet
import os
from datetime import datetime, timedelta

def get_sync_bot():
    try:
        print("--- FINAL ATTEMPT: MANUAL EXTRACTION ---")
        smart = smartsheet.Smartsheet(os.getenv("SMARTSHEET_TOKEN"))
        sheet_id = int(os.getenv("SMARTSHEET_ID"))
        
        sheet = smart.Sheets.get_sheet(sheet_id)
        print(f"Connected to: '{sheet.name}'")

        # Map Columns by Title
        col_map = {col.title.strip(): col.id for col in sheet.columns if col.title}
        name_id = col_map.get("Vehicle Name")
        last_week_id = col_map.get("Last Week's Odometer")
        current_id = col_map.get("Current Mileage")
        date_id = col_map.get("Last Sync Date")
        ser_id = col_map.get("Serial")

        # Build Row Lookup manually to avoid 'TypedList' errors
        ss_rows_lookup = {}
        for r in sheet.rows:
            # Find the specific cell for 'Vehicle Name' within the row
            target_cell = next((c for c in r.cells if c.column_id == name_id), None)
            if target_cell and target_cell.value:
                clean_name = str(target_cell.value).strip().upper()
                ss_rows_lookup[clean_name] = r.id

        print(f"Mapped {len(ss_rows_lookup)} vehicles from Smartsheet.")

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

                # 3. Construct Update using standard objects
                new_row = smartsheet.models.Row()
                new_row.id = ss_rows_lookup[g_name]
                
                # Use standard Cell objects with explicit attribute assignment
                c1 = smartsheet.models.Cell()
                c1.column_id = last_week_id
                c1.value = int(start_miles)

                c2 = smartsheet.models.Cell()
                c2.column_id = current_id
                c2.value = int(current_miles)

                c3 = smartsheet.models.Cell()
                c3.column_id = ser_id
                c3.value = str(d.get('serialNumber', ''))

                c4 = smartsheet.models.Cell()
                c4.column_id = date_id
                c4.value = today.strftime("%Y-%m-%d")
                
                new_row.cells = [c1, c2, c3, c4]
                updated_rows.append(new_row)
                print(f"Update Prepared: {g_name} ({start_miles} to {current_miles})")

        if updated_rows:
            result = smart.Sheets.update_rows(sheet_id, updated_rows)
            print(f"SYNC STATUS: {result.message}")
        else:
            print("No matching vehicles found.")

    except Exception as e:
        print(f"CRITICAL ERROR: {str(e)}")

if __name__ == "__main__":
    get_sync_bot()

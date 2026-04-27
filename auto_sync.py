import mygeotab
import smartsheet
import os
from datetime import datetime, timedelta

def get_sync_bot():
    try:
        print("--- FINAL ATTEMPT: DIRECT ATTRIBUTE ACCESS ---")
        smart = smartsheet.Smartsheet(os.getenv("SMARTSHEET_TOKEN"))
        sheet_id = int(os.getenv("SMARTSHEET_ID"))
        
        sheet = smart.Sheets.get_sheet(sheet_id)
        print(f"Connected to: '{sheet.name}'")

        # Map Columns
        col_map = {col.title.strip(): col.id for col in sheet.columns if col.title}
        name_id = col_map.get("Vehicle Name")
        last_week_id = col_map.get("Last Week's Odometer")
        current_id = col_map.get("Current Mileage")
        date_id = col_map.get("Last Sync Date")
        ser_id = col_map.get("Serial")

        # Build Row Lookup
        ss_rows_lookup = {}
        for r in sheet.rows:
            target_cell = next((c for c in r.cells if c.column_id == name_id), None)
            if target_cell and target_cell.value:
                ss_rows_lookup[str(target_cell.value).strip().upper()] = r.id

        print(f"Mapped {len(ss_rows_lookup)} vehicles from Smartsheet.")

        api = mygeotab.API(username=os.getenv("GEOTAB_USER"), 
                           password=os.getenv("GEOTAB_PASSWORD"), 
                           database=os.getenv("GEOTAB_DB"))
        api.authenticate()
        
        # Timing
        today = datetime.now()
        monday_start = (today - timedelta(days=today.weekday() + 7)).replace(hour=0, minute=0, second=0, microsecond=0)
        monday_end = monday_start + timedelta(days=2)

        devices = api.get('Device')
        updated_rows = []

        for d in devices:
            # Safely get the name using .get() to avoid KeyErrors
            g_name = str(d.get('name', '')).strip().upper()
            
            if g_name in ss_rows_lookup:
                d_id = d.get('id')
                
                # 1. Get Current Odometer
                live_logs = api.get('StatusData', search={'deviceSearch': {'id': d_id}, 'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 'resultsLimit': 1})
                current_miles = 0
                if live_logs and len(live_logs) > 0:
                    # Access by list index first, THEN key
                    current_miles = round(live_logs.get('data', 0) / 1609.344, 0)

                # 2. Get Historical Odometer
                hist_logs = api.get('StatusData', search={'deviceSearch': {'id': d_id}, 'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 'fromDate': monday_start, 'toDate': monday_end})
                start_miles = current_miles
                if hist_logs and len(hist_logs) > 0:
                    earliest = min(hist_logs, key=lambda x: x.get('dateTime'))
                    start_miles = round(earliest.get('data', 0) / 1609.344, 0)

                # 3. Create Update
                new_row = smartsheet.models.Row()
                new_row.id = ss_rows_lookup[g_name]
                
                # Define cells manually to bypass SDK quirks
                c_start = smartsheet.models.Cell()
                c_start.column_id = last_week_id
                c_start.value = int(start_miles)

                c_now = smartsheet.models.Cell()
                c_now.column_id = current_id
                c_now.value = int(current_miles)

                c_date = smartsheet.models.Cell()
                c_date.column_id = date_id
                c_date.value = today.strftime("%Y-%m-%d")

                new_row.cells = [c_start, c_now, c_date]
                updated_rows.append(new_row)
                print(f"Update Prepared: {g_name} ({start_miles} to {current_miles})")

        if updated_rows:
            # Pushing updates in batches to avoid timeout
            result = smart.Sheets.update_rows(sheet_id, updated_rows)
            print(f"FINAL SYNC STATUS: {result.message}")
        else:
            print("No matches to update.")

    except Exception as e:
        print(f"CRITICAL ERROR: {str(e)}")

if __name__ == "__main__":
    get_sync_bot()

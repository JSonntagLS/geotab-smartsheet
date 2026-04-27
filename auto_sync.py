import mygeotab
import smartsheet
import os
from datetime import datetime, timedelta

def get_sync_bot():
    try:
        print("--- STARTING MANUAL CONSTRUCTION SYNC ---")
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
        monday_start = (today - timedelta(days=today.weekday() + 7)).replace(hour=0, minute=0, second=0, microsecond=0)
        monday_end = monday_start + timedelta(days=2)

        devices = api.get('Device')
        updated_rows = []

        for d in devices:
            g_name = str(d['name']).strip().upper()
            if g_name in ss_rows_lookup:
                # 1. Fetch Data
                live_data = api.get('StatusData', search={'deviceSearch': {'id': d['id']}, 'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 'resultsLimit': 1})
                current_miles = round(live_data['data'] / 1609.344, 0) if live_data else 0

                hist_logs = api.get('StatusData', search={'deviceSearch': {'id': d['id']}, 'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 'fromDate': monday_start, 'toDate': monday_end})
                start_miles = round(min(hist_logs, key=lambda x: x['dateTime'])['data'] / 1609.344, 0) if hist_logs else 0

                # 2. Build Cells Manually (No arguments in __init__)
                c1 = smartsheet.models.Cell()
                c1.column_id = last_week_id
                c1.value = int(start_miles)

                c2 = smartsheet.models.Cell()
                c2.column_id = current_id
                c2.value = int(current_miles)

                c3 = smartsheet.models.Cell()
                c3.column_id = ser_id
                c3.value = str(d['serialNumber'])

                c4 = smartsheet.models.Cell()
                c4.column_id = date_id
                c4.value = today.strftime("%Y-%m-%d")

                # 3. Build Row Manually
                new_row = smartsheet.models.Row()
                new_row.id = ss_rows_lookup[g_name]
                new_row.cells.append(c1)
                new_row.cells.append(c2)
                new_row.cells.append(c3)
                new_row.cells.append(c4)
                
                updated_rows.append(new_row)
                print(f"Matched and Prepared: {g_name}")

        if updated_rows:
            result = smart.Sheets.update_rows(sheet_id, updated_rows)
            print(f"SUCCESS: {result.message}")
        else:
            print("No matching vehicles found.")

    except Exception as e:
        print(f"CRITICAL ERROR: {e}")

if __name__ == "__main__":
    get_sync_bot()

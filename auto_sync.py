import mygeotab
import smartsheet
import os
from datetime import datetime, timedelta

def get_sync_bot():
    try:
        print("--- STARTING CORRECTED SYNC ---")
        smart = smartsheet.Smartsheet(os.getenv("SMARTSHEET_TOKEN"))
        sheet_id = int(os.getenv("SMARTSHEET_ID"))
        
        # Verify Connection
        sheet = smart.Sheets.get_sheet(sheet_id)
        print(f"Connected to: '{sheet.name}'")

        # Map Columns
        col_map = {col.title.strip(): col.id for col in sheet.columns}
        name_id = col_map.get("Vehicle Name")
        last_week_id = col_map.get("Last Week's Odometer")
        current_id = col_map.get("Current Mileage")
        date_id = col_map.get("Last Sync Date")
        ser_id = col_map.get("Serial")

        # Build Row Lookup
        ss_rows_lookup = {}
        for r in sheet.rows:
            name_cell = next((c for c in r.cells if c.column_id == name_id), None)
            if name_cell and name_cell.value:
                ss_rows_lookup[str(name_cell.value).strip().upper()] = r.id

        # Geotab Setup
        api = mygeotab.API(username=os.getenv("GEOTAB_USER"), 
                           password=os.getenv("GEOTAB_PASSWORD"), 
                           database=os.getenv("GEOTAB_DB"))
        api.authenticate()
        
        today = datetime.now()
        # Monday 12:00 AM anchor
        monday_start = (today - timedelta(days=today.weekday() + 7)).replace(hour=0, minute=0, second=0, microsecond=0)
        monday_end = monday_start + timedelta(days=2) # 48-hour window for historical data

        devices = api.get('Device')
        updated_rows = []

        for d in devices:
            g_name = str(d['name']).strip().upper()
            if g_name in ss_rows_lookup:
                # 1. Get Live Current Mileage
                live_data = api.get('StatusData', search={'deviceSearch': {'id': d['id']}, 'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 'resultsLimit': 1})
                current_miles = round(live_data['data'] / 1609.344, 0) if live_data else 0

                # 2. Get Historical Monday Odometer
                hist_logs = api.get('StatusData', search={'deviceSearch': {'id': d['id']}, 'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 'fromDate': monday_start, 'toDate': monday_end})
                start_miles = round(min(hist_logs, key=lambda x: x['dateTime'])['data'] / 1609.344, 0) if hist_logs else 0

                # 3. Corrected Smartsheet Row Construction
                new_row = smartsheet.models.Row()
                new_row.id = ss_rows_lookup[g_name] # Fixed: ID set as attribute, not in __init__
                
                cells = [
                    smartsheet.models.Cell(column_id=last_week_id, value=int(start_miles)),
                    smartsheet.models.Cell(column_id=current_id, value=int(current_miles)),
                    smartsheet.models.Cell(column_id=ser_id, value=str(d['serialNumber'])),
                    smartsheet.models.Cell(column_id=date_id, value=today.strftime("%Y-%m-%d"))
                ]
                new_row.cells.extend(cells)
                updated_rows.append(new_row)
                print(f"Matched: {g_name}")

        if updated_rows:
            result = smart.Sheets.update_rows(sheet_id, updated_rows)
            print(f"SUCCESS: {result.message}")
        else:
            print("No matching vehicles found.")

    except Exception as e:
        print(f"CRITICAL ERROR: {e}")

if __name__ == "__main__":
    get_sync_bot()

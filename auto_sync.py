import mygeotab
import smartsheet
import os
from datetime import datetime, timedelta

def get_sync_bot():
    try:
        print("--- DEBUG MODE START ---")
        smart = smartsheet.Smartsheet(os.getenv("SMARTSHEET_TOKEN"))
        sheet_id = int(os.getenv("SMARTSHEET_ID"))
        
        # Load the sheet with column headers
        sheet = smart.Sheets.get_sheet(sheet_id)
        print(f"Connected to Sheet: '{sheet.name}'")

        # 1. EXACT HEADER MATCHING
        col_map = {col.title: col.id for col in sheet.columns}
        print(f"Available Headers: {list(col_map.keys())}")

        # Check for exact name matches (Watch out for hidden spaces!)
        name_id = col_map.get("Vehicle Name")
        last_week_id = col_map.get("Last Week's Odometer")
        current_id = col_map.get("Current Mileage")
        date_id = col_map.get("Last Sync Date")

        if not all([name_id, last_week_id, current_id]):
            print("ERROR: One or more column headers don't match exactly.")
            return

        # 2. BUILD ROW LOOKUP
        ss_rows_lookup = {}
        print("Rows found in Smartsheet:")
        for r in sheet.rows:
            # Find the cell that belongs to the 'Vehicle Name' column ID
            name_cell = next((c for c in r.cells if c.column_id == name_id), None)
            if name_cell and name_cell.value:
                val = str(name_cell.value).strip().upper()
                ss_rows_lookup[val] = r.id
                print(f" - Found Vehicle: '{val}'")

        # 3. GEOTAB INTEGRATION
        api = mygeotab.API(username=os.getenv("GEOTAB_USER"), 
                           password=os.getenv("GEOTAB_PASSWORD"), 
                           database=os.getenv("GEOTAB_DB"))
        api.authenticate()
        
        today = datetime.now()
        # Set window for last Monday
        monday_start = (today - timedelta(days=today.weekday() + 7)).replace(hour=0, minute=0, second=0)
        monday_end = monday_start + timedelta(days=2)

        devices = api.get('Device')
        updated_rows = []

        for d in devices:
            g_name = str(d['name']).strip().upper()
            
            if g_name in ss_rows_lookup:
                print(f"MATCHED: Updating {g_name}...")
                
                # Get Live Odometer
                live_data = api.get('StatusData', search={'deviceSearch': {'id': d['id']}, 'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 'resultsLimit': 1})
                current_miles = round(live_data['data'] / 1609.344, 0) if live_data else 0

                # Get Historical Odometer
                hist_logs = api.get('StatusData', search={'deviceSearch': {'id': d['id']}, 'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 'fromDate': monday_start, 'toDate': monday_end})
                start_miles = round(min(hist_logs, key=lambda x: x['dateTime'])['data'] / 1609.344, 0) if hist_logs else 0

                # Create Update
                new_row = smartsheet.models.Row(id=ss_rows_lookup[g_name])
                new_row.cells.append(smartsheet.models.Cell(column_id=last_week_id, value=int(start_miles)))
                new_row.cells.append(smartsheet.models.Cell(column_id=current_id, value=int(current_miles)))
                new_row.cells.append(smartsheet.models.Cell(column_id=date_id, value=today.strftime("%Y-%m-%d")))
                updated_rows.append(new_row)

        # 4. THE PUSH
        if updated_rows:
            response = smart.Sheets.update_rows(sheet_id, updated_rows)
            print(f"SUCCESS: {response.message}")
        else:
            print("FAILED: No matches were made. Check if Geotab names match Smartsheet names exactly.")

    except Exception as e:
        print(f"CRITICAL SYSTEM ERROR: {e}")

if __name__ == "__main__":
    get_sync_bot()

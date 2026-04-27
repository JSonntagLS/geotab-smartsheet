import mygeotab
import smartsheet
import os
from datetime import datetime, timedelta

def get_sync_bot():
    try:
        print("--- REBUILDING DATA RETRIEVAL ---")
        smart = smartsheet.Smartsheet(os.getenv("SMARTSHEET_TOKEN"))
        sheet_id = int(os.getenv("SMARTSHEET_ID"))
        
        sheet = smart.Sheets.get_sheet(sheet_id)
        col_map = {col.title.strip(): col.id for col in sheet.columns if col.title}
        
        # Mapping IDs
        name_id = col_map.get("Vehicle Name")
        last_week_id = col_map.get("Last Week's Odometer")
        current_id = col_map.get("Current Mileage")
        date_id = col_map.get("Last Sync Date")

        ss_rows_lookup = {}
        for r in sheet.rows:
            target_cell = next((c for c in r.cells if c.column_id == name_id), None)
            if target_cell and target_cell.value:
                ss_rows_lookup[str(target_cell.value).strip().upper()] = r.id

        api = mygeotab.API(username=os.getenv("GEOTAB_USER"), 
                           password=os.getenv("GEOTAB_PASSWORD"), 
                           database=os.getenv("GEOTAB_DB"))
        api.authenticate()
        
        # Target Monday (7 days ago)
        monday_target = (datetime.now() - timedelta(days=7)).replace(hour=0, minute=0, second=0)

        devices = api.get('Device')
        updated_rows = []

        for d in devices:
            g_name = str(d.get('name', '')).strip().upper()
            if g_name in ss_rows_lookup:
                d_id = d.get('id')
                
                # 1. GET CURRENT ODOMETER (The very last log ever recorded)
                live_logs = api.get('StatusData', search={'deviceSearch': {'id': d_id}, 'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 'resultsLimit': 1})
                
                # 2. GET MONDAY ODOMETER (A 24-hour window around last Monday)
                hist_logs = api.get('StatusData', search={'deviceSearch': {'id': d_id}, 'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 'fromDate': monday_target, 'toDate': monday_target + timedelta(days=1)})

                # Process the data safely
                curr_val = round(live_logs['data'] / 1609.344, 0) if live_logs else 0
                prev_val = round(hist_logs['data'] / 1609.344, 0) if hist_logs else curr_val

                # Build the Smartsheet Row Update
                new_row = smartsheet.models.Row()
                new_row.id = ss_rows_lookup[g_name]
                
                # Manually add cells
                c1, c2, c3 = smartsheet.models.Cell(), smartsheet.models.Cell(), smartsheet.models.Cell()
                c1.column_id, c1.value = last_week_id, int(prev_val)
                c2.column_id, c2.value = current_id, int(curr_val)
                c3.column_id, c3.value = date_id, datetime.now().strftime("%Y-%m-%d")
                
                new_row.cells = [c1, c2, c3]
                updated_rows.append(new_row)
                print(f"Vehicle: {g_name} | Monday: {prev_val} | Now: {curr_val}")

        if updated_rows:
            result = smart.Sheets.update_rows(sheet_id, updated_rows)
            print(f"SUCCESS: {result.message}")
        else:
            print("No matching vehicles found.")

    except Exception as e:
        print(f"ERROR: {str(e)}")

if __name__ == "__main__":
    get_sync_bot()

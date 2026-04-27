import mygeotab
import smartsheet
import os
from datetime import datetime, timedelta

def get_sync_bot():
    try:
        print("--- STARTING DIAGNOSTIC SYNC ---")
        smart = smartsheet.Smartsheet(os.getenv("SMARTSHEET_TOKEN"))
        sheet_id = int(os.getenv("SMARTSHEET_ID"))
        sheet = smart.Sheets.get_sheet(sheet_id)
        
        col_map = {col.title.strip(): col.id for col in sheet.columns if col.title}
        name_id = col_map.get("Vehicle Name")
        last_week_id = col_map.get("Last Week's Odometer")
        current_id = col_map.get("Current Mileage")
        date_id = col_map.get("Last Sync Date")

        # Map Smartsheet rows
        ss_rows = {}
        for r in sheet.rows:
            target_cell = next((c for c in r.cells if c.column_id == name_id), None)
            if target_cell and target_cell.value:
                ss_rows[str(target_cell.value).strip().upper()] = r.id

        api = mygeotab.API(username=os.getenv("GEOTAB_USER"), 
                           password=os.getenv("GEOTAB_PASSWORD"), 
                           database=os.getenv("GEOTAB_DB"))
        api.authenticate()
        
        monday_cutoff = (datetime.now() - timedelta(days=7)).replace(hour=0, minute=0, second=0)
        devices = api.get('Device')
        updated_rows = []

        for d in devices:
            g_name = str(d.get('name', '')).strip().upper()
            if g_name in ss_rows:
                try:
                    # 1. Fetch Current
                    curr_logs = api.get('StatusData', search={'deviceSearch': {'id': d['id']}, 'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 'resultsLimit': 1})
                    
                    # 2. Fetch Monday
                    prev_logs = api.get('StatusData', search={'deviceSearch': {'id': d['id']}, 'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 'toDate': monday_cutoff, 'resultsLimit': 1})

                    # Check if data actually exists before doing math
                    if not curr_logs or not prev_logs:
                        raise ValueError("Missing Data")

                    curr_m = int(round(curr_logs['data'] / 1609.344, 0))
                    prev_m = int(round(prev_logs['data'] / 1609.344, 0))
                    status_msg = datetime.now().strftime("%Y-%m-%d")

                except Exception:
                    # If Geotab fails for THIS vehicle, we set these as strings
                    curr_m = "CHECK GPS"
                    prev_m = "CHECK GPS"
                    status_msg = "GEOTAB ERROR"

                # Construct Row
                new_row = smartsheet.models.Row()
                new_row.id = ss_rows[g_name]
                
                c1, c2, c3 = smartsheet.models.Cell(), smartsheet.models.Cell(), smartsheet.models.Cell()
                c1.column_id, c1.value = last_week_id, prev_m
                c2.column_id, c2.value = current_id, curr_m
                c3.column_id, c3.value = date_id, status_msg
                
                new_row.cells = [c1, c2, c3]
                updated_rows.append(new_row)
                print(f"Processed {g_name}: {curr_m}")

        if updated_rows:
            smart.Sheets.update_rows(sheet_id, updated_rows)
            print("SYNC RUN FINISHED")

    except Exception as e:
        print(f"CRITICAL SYSTEM FAILURE: {str(e)}")

if __name__ == "__main__":
    get_sync_bot()

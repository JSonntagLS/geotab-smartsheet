import mygeotab
import smartsheet
import os
from datetime import datetime, timedelta

def get_sync_bot():
    try:
        print("--- STARTING FINAL STABLE SYNC ---")
        smart = smartsheet.Smartsheet(os.getenv("SMARTSHEET_TOKEN"))
        sheet_id = int(os.getenv("SMARTSHEET_ID"))
        sheet = smart.Sheets.get_sheet(sheet_id)
        
        col_map = {col.title.strip(): col.id for col in sheet.columns if col.title}
        name_id = col_map.get("Vehicle Name")
        last_week_id = col_map.get("Last Week's Odometer")
        current_id = col_map.get("Current Mileage")
        date_id = col_map.get("Last Sync Date")

        # Map Smartsheet rows - Skip duplicates to avoid Smartsheet Error 400
        ss_rows = {}
        for r in sheet.rows:
            target_cell = next((c for c in r.cells if c.column_id == name_id), None)
            if target_cell and target_cell.value:
                name_key = str(target_cell.value).strip().upper()
                if name_key not in ss_rows: # This filter stops the duplicate element error
                    ss_rows[name_key] = r.id

        api = mygeotab.API(username=os.getenv("GEOTAB_USER"), 
                           password=os.getenv("GEOTAB_PASSWORD"), 
                           database=os.getenv("GEOTAB_DB"))
        api.authenticate()
        
        # Look for the last reading before 7 days ago
        monday_target = (datetime.now() - timedelta(days=7)).replace(hour=0, minute=0, second=0)
        
        devices = api.get('Device')
        updated_rows = []

        for d in devices:
            g_name = str(d.get('name', '')).strip().upper()
            if g_name in ss_rows:
                try:
                    # 1. Fetch Current Odometer
                    curr_logs = api.get('StatusData', search={'deviceSearch': {'id': d['id']}, 'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 'resultsLimit': 1})
                    
                    # 2. Fetch Historical (Looking for the single closest log BEFORE Monday)
                    prev_logs = api.get('StatusData', search={'deviceSearch': {'id': d['id']}, 'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 'toDate': monday_target, 'resultsLimit': 1})

                    if not curr_logs:
                        curr_m = "NO DATA"
                    else:
                        curr_m = int(round(curr_logs['data'] / 1609.344, 0))

                    if not prev_logs:
                        prev_m = curr_m # Fallback to current if no history exists
                    else:
                        prev_m = int(round(prev_logs['data'] / 1609.344, 0))
                    
                    status_date = datetime.now().strftime("%m/%d/%Y")

                except Exception:
                    curr_m, prev_m, status_date = "CHECK GPS", "CHECK GPS", "ERROR"

                # Prepare the update
                new_row = smartsheet.models.Row()
                new_row.id = ss_rows[g_name]
                
                c1, c2, c3 = smartsheet.models.Cell(), smartsheet.models.Cell(), smartsheet.models.Cell()
                c1.column_id, c1.value = last_week_id, prev_m
                c2.column_id, c2.value = current_id, curr_m
                c3.column_id, c3.value = date_id, status_date
                
                new_row.cells = [c1, c2, c3]
                updated_rows.append(new_row)
                print(f"Processed {g_name}: {curr_m}")

        if updated_rows:
            # We already filtered duplicates in our ss_rows loop, so this should pass 400 check
            result = smart.Sheets.update_rows(sheet_id, updated_rows)
            print(f"SYNC SUCCESS: {result.message}")
        else:
            print("No matching vehicles found.")

    except Exception as e:
        print(f"CRITICAL FAILURE: {str(e)}")

if __name__ == "__main__":
    get_sync_bot()

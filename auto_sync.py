import mygeotab
import pandas as pd
import os
import smartsheet
from datetime import datetime, timedelta

# --- CONFIGURATION ---
COL_SERIAL = 4402295422095236
COL_MONDAY = 1876872503005060
COL_CURRENT = 8905895049465732
COL_SYNC = 109802027257732

def harvest_data():
    now = datetime.utcnow()
    # Anchor to last Monday
    days_since_monday = now.weekday()
    monday_target = (now - timedelta(days=days_since_monday)).replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Search window: 1 day before Monday to catch the "Start" reading
    search_start_date = (monday_target - timedelta(days=1)).isoformat()
    print(f"--- STARTING SYNC: {now} (Searching from {search_start_date}) ---")
    
    # 1. GEOTAB DATA PULL
    api = mygeotab.API(username=os.getenv("GEOTAB_USER"), password=os.getenv("GEOTAB_PASSWORD"), database=os.getenv("GEOTAB_DB"))
    api.authenticate()

    devices = api.get('Device')
    diagnostics = ['DiagnosticOdometerAdjustmentId', 'DiagnosticOdometerId']
    
    all_devices_logs = {}
    monday_odo = {}
    current_odo = {}

    for diag in diagnostics:
        raw_logs = api.get('StatusData', search={
            'diagnosticSearch': {'id': diag}, 
            'fromDate': search_start_date, 
            'toDate': now.isoformat()
        })
        
        for log in raw_logs:
            d_id = log['device']['id']
            if d_id not in all_devices_logs:
                all_devices_logs[d_id] = []
            all_devices_logs[d_id].append(log)

    # Process logs to find Monday Start and Current
    for dev_id, logs in all_devices_logs.items():
        if not logs:
            continue
            
        logs.sort(key=lambda x: x['dateTime'])
        start_log = logs[0]
        curr_log = logs[-1]
        
        monday_odo[dev_id] = {'val': start_log.get('data', 0), 'ts': start_log.get('dateTime')}
        current_odo[dev_id] = {'val': curr_log.get('data', 0), 'ts': curr_log.get('dateTime')}

    # --- CSV STATE MANAGEMENT (Persistence Logic) ---
    csv_file = 'fleet_live.csv'
    
    if now.weekday() == 0 or not os.path.exists(csv_file):
        # On Monday: Save today's start as the baseline
        pd.DataFrame.from_dict(monday_odo, orient='index').to_csv(csv_file)
        print(f"SNAPSHOT: Saved fresh Monday baseline to {csv_file}")
    else:
        # Not Monday: Overwrite Geotab's 'start' with our frozen CSV baseline
        print(f"PERSISTENCE: Loading Monday baseline from {csv_file}")
        stored_df = pd.read_csv(csv_file, index_col=0)
        stored_data = stored_df.to_dict(orient='index')
        for dev_id, data in stored_data.items():
            # Update monday_odo with stored values so calculations remain consistent
            monday_odo[dev_id] = {'val': data.get('val', 0), 'ts': data.get('ts')}

    # 2. SMARTSHEET INTEGRATION
    smart = smartsheet.Smartsheet(os.getenv("SMARTSHEET_TOKEN"))
    sheet_id = int(os.getenv("SMARTSHEET_ID"))
    sheet = smart.Sheets.get_sheet(sheet_id)
    
    row_map = {}
    for row in sheet.rows:
        serial_cell = next((c.value for c in row.cells if c.column_id == COL_SERIAL), None)
        if serial_cell:
            row_map[str(serial_cell).strip()] = row.id

    rows_to_update = []
    
    for d in devices:
        serial = str(d.get('serialNumber')).strip()
        dev_id = d.get('id')
        
        if serial in row_map:
            curr = current_odo.get(dev_id)
            start = monday_odo.get(dev_id)
            
            if curr and start:
                curr_miles = round(curr['val'] / 1609.344, 0)
                start_miles = round(start['val'] / 1609.344, 0)
                # Handle datetime or string timestamp from CSV
                ts = curr['ts']
                sync_date = ts[:10] if isinstance(ts, str) else ts.strftime('%Y-%m-%d')

                new_row = smartsheet.models.Row()
                new_row.id = row_map[serial]
                new_row.cells.append({'column_id': COL_MONDAY, 'value': start_miles})
                new_row.cells.append({'column_id': COL_CURRENT, 'value': curr_miles})
                new_row.cells.append({'column_id': COL_SYNC, 'value': sync_date})
                rows_to_update.append(new_row)
                print(f"MATCH: {d.get('name')} | Updating Serial {serial}")

    if rows_to_update:
        smart.Sheets.update_rows(sheet_id, rows_to_update)
        print(f"SUCCESS: Updated {len(rows_to_update)} rows in Smartsheet.")
    else:
        print("Done. No updates performed.")

if __name__ == "__main__":
    harvest_data()

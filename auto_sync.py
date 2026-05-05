import mygeotab
import pandas as pd
import os
import smartsheet
from datetime import datetime, timedelta

# --- CONFIGURATION (Column IDs from your Step 1) ---
COL_SERIAL = 4402295422095236
COL_MONDAY = 1876872503005060
COL_CURRENT = 8905895049465732
COL_SYNC = 109802027257732

def harvest_data():
    now = datetime.utcnow()
    # Anchor to last Monday, but create a search buffer starting 2 days prior
    days_since_monday = now.weekday()
    monday_target = (now - timedelta(days=days_since_monday + 7)).replace(hour=0, minute=1, second=0, microsecond=0)
    
    # We search from 2 days before Monday to find the closest "Start" reading
    search_start_date = (monday_target - timedelta(days=2)).isoformat()
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
        # Pulling logs for all devices in the buffer range
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

    # Process logs to find the "best fit" for Monday Start and Current
    for dev_id, logs in all_devices_logs.items():
        if not logs:
            continue
            
        # Sort logs by time to identify the boundaries
        logs.sort(key=lambda x: x['dateTime'])
        
        # 'start' is the first log found in our buffer (closest to Monday morning)
        # 'curr' is the most recent log found
        start_log = logs[0]
        curr_log = logs[-1]
        
        monday_odo[dev_id] = {'val': start_log.get('data', 0), 'ts': start_log.get('dateTime')}
        current_odo[dev_id] = {'val': curr_log.get('data', 0), 'ts': curr_log.get('dateTime')}

    # 2. SMARTSHEET INTEGRATION
    smart = smartsheet.Smartsheet(os.getenv("SMARTSHEET_TOKEN"))
    sheet_id = int(os.getenv("SMARTSHEET_ID"))
    sheet = smart.Sheets.get_sheet(sheet_id)
    
    # Map Serial Number to Row ID for updating
    # This prevents breaking cell links because we aren't deleting rows
    row_map = {}
    for row in sheet.rows:
        serial_cell = next((c.value for c in row.cells if c.column_id == COL_SERIAL), None)
        if serial_cell:
            row_map[str(serial_cell).strip()] = row.id

    rows_to_update = []
    
    for d in devices:
        serial = str(d.get('serialNumber')).strip()
        dev_id = d.get('id')
        
        # Only update if the vehicle exists in your Smartsheet
        if serial in row_map:
            curr = current_odo.get(dev_id)
            start = monday_odo.get(dev_id)
            
            # Logic Integration: Ensure data exists before calculation
            if curr and start:
                curr_miles = round(curr['val'] / 1609.344, 0)
                start_miles = round(start['val'] / 1609.344, 0)
                sync_date = curr['ts'].strftime('%Y-%m-%d')
            else:
                print(f"SKIP: No Geotab data found for {d.get('name')} in this date range.")
                continue

            # Build the update row
            new_row = smartsheet.models.Row()
            new_row.id = row_map[serial]
            new_row.cells.append({'column_id': COL_MONDAY, 'value': start_miles})
            new_row.cells.append({'column_id': COL_CURRENT, 'value': curr_miles})
            new_row.cells.append({'column_id': COL_SYNC, 'value': sync_date})
            
            # Ensure these only appear ONCE:
            rows_to_update.append(new_row)
            print(f"MATCH: {d.get('name')} | Updating Serial {serial}")
        else:
            # If a car is in Geotab but not Smartsheet, we move on.
            pass

    # Perform the bulk update
    if rows_to_update:
        smart.Sheets.update_rows(sheet_id, rows_to_update)
        print(f"SUCCESS: Updated {len(rows_to_update)} rows in Smartsheet.")
    else:
        print("Done. No matching serials found to update.")

if __name__ == "__main__":
    harvest_data()

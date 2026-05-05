import mygeotab
import pandas as pd
import os
import smartsheet
from datetime import datetime, timedelta

# --- CONFIGURATION ---
COL_SERIAL = 4402295422095236
COL_WEEKLY_TOTAL = 1876872503005060  # Replacing COL_MONDAY with 7-day total functionality
COL_CURRENT_ODO = 8905895049465732
COL_SYNC = 109802027257732

def harvest_7day_data():
    now = datetime.utcnow()
    # Looking back 7 days plus a small buffer to ensure we find a starting odometer log
    start_buffer = now - timedelta(days=8) 
    
    # 1. GEOTAB DATA PULL
    api = mygeotab.API(username=os.getenv("GEOTAB_USER"), 
                       password=os.getenv("GEOTAB_PASSWORD"), 
                       database=os.getenv("GEOTAB_DB"))
    api.authenticate()

    # 2. SMARTSHEET SETUP
    smart = smartsheet.Smartsheet(os.getenv("SMARTSHEET_TOKEN"))
    sheet_id = int(os.getenv("SMARTSHEET_ID"))
    sheet = smart.Sheets.get_sheet(sheet_id)
    
    # Map Serial Number to Smartsheet Row ID
    row_map = {str(next((c.value for c in r.cells if c.column_id == COL_SERIAL), "")).strip(): r.id for r in sheet.rows}

    # 3. PULLING AND CALCULATING
    devices = api.get('Device')
    diagnostics = ['DiagnosticOdometerAdjustmentId', 'DiagnosticOdometerId']
    
    history_rows = []
    smartsheet_updates = []

    print(f"--- STARTING 7-DAY SYNC: {now.strftime('%Y-%m-%d %H:%M')} ---")

    for device in devices:
        dev_id = device['id']
        serial = str(device.get('serialNumber')).strip()
        
        logs = []
        for diag in diagnostics:
            logs += api.get('StatusData', search={
                'deviceSearch': {'id': dev_id},
                'diagnosticSearch': {'id': diag},
                'fromDate': start_buffer.isoformat(),
                'toDate': now.isoformat()
            })

        if not logs:
            continue

        # Sort logs to find the boundary of the last 7 days
        logs.sort(key=lambda x: x['dateTime'])
        
        # We find the log closest to exactly 7 days ago
        target_time = now - timedelta(days=7)
        start_log = min(logs, key=lambda x: abs(x['dateTime'] - target_time))
        end_log = logs[-1]
        
        # Calculate Mileage
        miles_start = start_log['data'] / 1609.344
        miles_end = end_log['data'] / 1609.344
        weekly_delta = round(miles_end - miles_start, 0)
        current_odo = round(miles_end, 0)

        # Prep CSV Data (The "Middle Man" History Log)
        history_rows.append({
            'Timestamp': now.strftime('%Y-%m-%d %H:%M'),
            'Serial': serial,
            'Vehicle': device.get('name'),
            'Weekly_Miles': weekly_delta,
            'Current_Odometer': current_odo
        })

        # Prep Smartsheet Update
        if serial in row_map:
            new_row = smartsheet.models.Row()
            new_row.id = row_map[serial]
            new_row.cells.append({'column_id': COL_WEEKLY_TOTAL, 'value': weekly_delta})
            new_row.cells.append({'column_id': COL_CURRENT_ODO, 'value': current_odo})
            new_row.cells.append({'column_id': COL_SYNC, 'value': now.strftime('%Y-%m-%d')})
            smartsheet_updates.append(new_row)

    # 4. EXECUTE UPDATES
    # Save to Master CSV (Fleet History)
    if history_rows:
        df_new = pd.DataFrame(history_rows)
        master_file = 'weekly_fleet_history.csv'
        if os.path.exists(master_file):
            df_master = pd.read_csv(master_file)
            pd.concat([df_master, df_new], ignore_index=True).to_csv(master_file, index=False)
        else:
            df_new.to_csv(master_file, index=False)
        print(f"CSV: Logged {len(history_rows)} entries to {master_file}")

    # Bulk Update Smartsheet
    if smartsheet_updates:
        smart.Sheets.update_rows(sheet_id, smartsheet_updates)
        print(f"SUCCESS: Updated {len(smartsheet_updates)} rows in Smartsheet.")

if __name__ == "__main__":
    harvest_7day_data()

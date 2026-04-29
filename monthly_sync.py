import mygeotab
import pandas as pd
import os
import smartsheet
from datetime import datetime, timedelta

# --- CONFIGURATION ---
COL_SERIAL = 4402295422095236 
COL_MONTHLY_ACTUAL = 5023490920189828 # <-- PASTE YOUR ID HERE

def harvest_monthly_data():
    now = datetime.utcnow()
    start_buffer = now - timedelta(days=35)
    
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

        logs.sort(key=lambda x: x['dateTime'])
        start_log, end_log = logs[0], logs[-1]
        
        # Math: Normalize to a 31-day (744 hour) month
        time_diff = end_log['dateTime'] - start_log['dateTime']
        hours_sampled = time_diff.total_seconds() / 3600
        miles_delta = (end_log['data'] - start_log['data']) / 1609.344

        normalized_monthly = round((miles_delta / hours_sampled) * 744, 0) if hours_sampled > 0 else 0

        # Prep CSV Data
        history_rows.append({
            'Timestamp': now.strftime('%Y-%m-%d %H:%M'),
            'Serial': serial,
            'Monthly_Miles_Actual': normalized_monthly,
            'Trigger': os.getenv('RUN_TRIGGER', 'Manual')
        })

        # Prep Smartsheet Update
        if serial in row_map:
            new_row = smartsheet.models.Row()
            new_row.id = row_map[serial]
            new_row.cells.append({'column_id': COL_MONTHLY_ACTUAL, 'value': normalized_monthly})
            smartsheet_updates.append(new_row)

    # 4. EXECUTE UPDATES
    # Save to Master CSV
    if history_rows:
        df_new = pd.DataFrame(history_rows)
        master_file = 'fleet_history_master.csv'
        if os.path.exists(master_file):
            df_master = pd.read_csv(master_file)
            pd.concat([df_master, df_new], ignore_index=True).to_csv(master_file, index=False)
        else:
            df_new.to_csv(master_file, index=False)

    # Bulk Update Smartsheet
    if smartsheet_updates:
        smart.Sheets.update_rows(sheet_id, smartsheet_updates)
        print(f"SUCCESS: Updated {len(smartsheet_updates)} rows in Smartsheet.")

if __name__ == "__main__":
    harvest_monthly_data()

import mygeotab
import pandas as pd
import os
import smartsheet
from datetime import datetime, timedelta

# --- CONFIGURATION ---
# Replace these with your actual Column IDs from Smartsheet
COL_SERIAL = 4402295422095236 
COL_MONTHLY_ACTUAL = 0000000000000000 # <-- PUT YOUR NEW COLUMN ID HERE

def harvest_monthly_data():
    now = datetime.utcnow()
    # Look back 31 days, but pull a 4-day buffer (35 days) to ensure we find a "start" ping
    start_buffer = now - timedelta(days=35)
    
    print(f"--- STARTING MONTHLY SYNC: {now} ---")
    
    # 1. GEOTAB DATA PULL
    api = mygeotab.API(username=os.getenv("GEOTAB_USER"), 
                       password=os.getenv("GEOTAB_PASSWORD"), 
                       database=os.getenv("GEOTAB_DB"))
    api.authenticate()

    devices = api.get('Device')
    diagnostics = ['DiagnosticOdometerAdjustmentId', 'DiagnosticOdometerId']
    
    # Storage for normalized results and CSV history
    history_rows = []
    smartsheet_updates = []

    for device in devices:
        dev_id = device['id']
        serial = str(device.get('serialNumber')).strip()
        
        # Pull all logs for this device in the last 35 days
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

        # Sort logs by time to find the true Start and End
        logs.sort(key=lambda x: x['dateTime'])
        
        start_log = logs[0]
        end_log = logs[-1]
        
        # Calculate time span in hours
        time_diff = end_log['dateTime'] - start_log['dateTime']
        hours_sampled = time_diff.total_seconds() / 3600
        
        # Calculate raw mile delta
        miles_start = start_log['data'] / 1609.344
        miles_end = end_log['data'] / 1609.344
        miles_delta = miles_end - miles_start

        # NORMALIZATION: Scale the miles to a perfect 31-day month (744 hours)
        if hours_sampled > 0:
            normalized_monthly = round((miles_delta / hours_sampled) * 744, 0)
        else:
            normalized_monthly = 0

        # Log for Master CSV
        history_rows.append({
            'Timestamp': now.strftime('%Y-%m-%d %H:%M'),
            'Serial': serial,
            'Device_Name': device.get('name'),
            'Hours_Sampled': round(hours_sampled, 2),
            'Raw_Delta': round(miles_delta, 0),
            'Monthly_Miles_Actual': normalized_monthly,
            'Trigger': os.getenv('RUN_TRIGGER', 'Manual')
        })

    # 2. SAVE TO MASTER CSV (Local for Action Artifact)
    df_new = pd.DataFrame(history_rows)
    master_file = 'fleet_history_master.csv'
    
    # Append if exists, create if not
    if os.path.exists(master_file):
        df_master = pd.read_csv(master_file)
        df_master = pd.concat([df_master, df_new], ignore_index=True)
        df_master.to_csv(master_file, index=False)
    else:
        df_new.to_csv(master_file, index=False)

# 3. SMARTSHEET INTEGRATION & ID SNIFFER
    smart = smartsheet.Smartsheet(os.getenv("SMARTSHEET_TOKEN"))
    sheet_id = int(os.getenv("SMARTSHEET_ID"))
    sheet = smart.Sheets.get_sheet(sheet_id)
    
    # --- THIS PART PRINTS THE IDs TO YOUR GITHUB LOG ---
    print("--- COLUMN ID LIST ---")
    for column in sheet.columns:
        print(f"COLUMN NAME: {column.title} | ID: {column.id}")
    print("----------------------")

    # Map Serial Number to Row ID
    row_map = {str(next((c.value for c in r.cells if c.column_id == COL_SERIAL), "")).strip(): r.id for r in sheet.rows}

    for item in history_rows:
        if item['Serial'] in row_map:
            new_row = smartsheet.models.Row()
            new_row.id = row_map[item['Serial']]
            # We use a placeholder check here so the script doesn't crash before you have the ID
            if COL_MONTHLY_ACTUAL != 0:
                new_row.cells.append({'column_id': COL_MONTHLY_ACTUAL, 'value': item['Monthly_Miles_Actual']})
                smartsheet_updates.append(new_row)

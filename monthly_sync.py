import mygeotab
import pandas as pd
import os
import smartsheet
from datetime import datetime, timedelta

# --- CONFIGURATION ---
COL_SERIAL = 4402295422095236 
COL_MONTHLY_ACTUAL = 0 # We will fill this in once we get the ID

def harvest_monthly_data():
    print("Checkpoint 1: Starting harvest_monthly_data function...")
    now = datetime.utcnow()
    start_buffer = now - timedelta(days=35)
    
    # 1. GEOTAB DATA PULL
    print("Checkpoint 2: Authenticating with Geotab...")
    try:
        api = mygeotab.API(username=os.getenv("GEOTAB_USER"), 
                           password=os.getenv("GEOTAB_PASSWORD"), 
                           database=os.getenv("GEOTAB_DB"))
        api.authenticate()
        print("Checkpoint 3: Geotab Authentication Successful.")
    except Exception as e:
        print(f"FAILED at Geotab Auth: {e}")
        return

    # 2. SMARTSHEET ID SNIFFER
    print("Checkpoint 4: Connecting to Smartsheet to sniff Column IDs...")
    try:
        smart = smartsheet.Smartsheet(os.getenv("SMARTSHEET_TOKEN"))
        sheet_id = int(os.getenv("SMARTSHEET_ID"))
        sheet = smart.Sheets.get_sheet(sheet_id)
        
        print("\n--- FOUND SMARTSHEET COLUMNS ---")
        for column in sheet.columns:
            print(f"COLUMN NAME: {column.title} | ID: {column.id}")
        print("---------------------------------\n")
    except Exception as e:
        print(f"FAILED at Smartsheet connection: {e}")
        return

    # 3. PULLING VEHICLES
    print("Checkpoint 5: Pulling devices from Geotab...")
    devices = api.get('Device')
    diagnostics = ['DiagnosticOdometerAdjustmentId', 'DiagnosticOdometerId']
    
    history_rows = []

    for device in devices:
        dev_id = device['id']
        serial = str(device.get('serialNumber')).strip()
        
        logs = []
        for diag in diagnostics:
            # Shortening resultsLimit for the ID test run
            logs += api.get('StatusData', search={
                'deviceSearch': {'id': dev_id},
                'diagnosticSearch': {'id': diag},
                'fromDate': start_buffer.isoformat(),
                'toDate': now.isoformat(),
                'resultsLimit': 100 
            })

        if not logs:
            continue

        logs.sort(key=lambda x: x['dateTime'])
        start_log, end_log = logs[0], logs[-1]
        
        time_diff = end_log['dateTime'] - start_log['dateTime']
        hours_sampled = time_diff.total_seconds() / 3600
        miles_delta = (end_log['data'] - start_log['data']) / 1609.344

        normalized_monthly = round((miles_delta / hours_sampled) * 744, 0) if hours_sampled > 0 else 0

        history_rows.append({
            'Timestamp': now.strftime('%Y-%m-%d %H:%M'),
            'Serial': serial,
            'Monthly_Miles_Actual': normalized_monthly,
            'Trigger': os.getenv('RUN_TRIGGER', 'Manual')
        })

    # 4. CSV SAVE
    if history_rows:
        df = pd.DataFrame(history_rows)
        df.to_csv('fleet_history_master.csv', index=False)
        print(f"Checkpoint 6: Processed {len(history_rows)} vehicles into CSV.")
    else:
        print("Checkpoint 6: No vehicle data found to process.")

if __name__ == "__main__":
    harvest_monthly_data()

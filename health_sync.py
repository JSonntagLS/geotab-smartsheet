import mygeotab
import smartsheet
import os
import pandas as pd
from datetime import datetime, timedelta

# --- CONFIG ---
token = os.getenv("SMARTSHEET_TOKEN")
sheet_id = os.getenv("SMARTSHEET_ID")
STATUS_COL_ID = 2274350475808644
BATTERY_COL_ID = 6777950103179140
NAME_COL_ID = 6654095235780484 

def run_health_sync():
    client = mygeotab.API(username=os.getenv("GEOTAB_USER"), 
                          password=os.getenv("GEOTAB_PASSWORD"), 
                          database=os.getenv("GEOTAB_DB"))
    client.authenticate()
    smart = smartsheet.Smartsheet(os.getenv("SMARTSHEET_TOKEN"))

    # 1. Map Smartsheet Names
    sheet = smart.Sheets.get_sheet(os.getenv("SMARTSHEET_ID"))
    fleet_map = {str(row.cells.value).strip(): row.id for row in sheet.rows if row.cells.value}

    # 2. Bulk Fetch with Multi-Diagnostic Support
    two_days_ago = (datetime.utcnow() - timedelta(days=2)).isoformat()
    print(f"Fetching data since {two_days_ago}...", flush=True)
    
    # We pull multiple common voltage IDs to ensure the CSV isn't empty
    diagnostics = ['DiagnosticGoDeviceVoltageId', 'DiagnosticDeviceBatteryVoltageId']
    all_raw_data = []
    
    for diag in diagnostics:
        batch = client.get('StatusData', search={
            'diagnosticSearch': {'id': diag},
            'fromDate': two_days_ago
        })
        all_raw_data.extend(batch)
        print(f"Found {len(batch)} records for {diag}", flush=True)

    # 3. Force Create the CSV
    df = pd.DataFrame(all_raw_data)
    if df.empty:
        # Create a dummy CSV so the script doesn't fail later
        df = pd.DataFrame(columns=['dateTime', 'data', 'device', 'diagnostic'])
    
    # Flatten the 'device' dictionary column into a simple 'device_id' string
    # This is the "Nested Folder" fix:
    df['device_id'] = df['device'].apply(lambda x: x['id'] if isinstance(x, dict) else (x['id'] if isinstance(x, list) else None))
    df['voltage'] = df['data']
    
    # Save the flattened data
    df.to_csv('geotab_health_cache.csv', index=False)
    print(f"CSV Generated: geotab_health_cache.csv with {len(df)} rows.", flush=True)

    # 4. Process and Sync
    devices = {d['id']: d['name'].strip() for d in client.get('Device')}
    status_infos = {si['device']['id']: si['isDeviceCommunicating'] for si in client.get('DeviceStatusInfo')}

    # Latest record per device
    latest_df = df.sort_values('dateTime', ascending=False).drop_duplicates('device_id') if not df.empty else df

    updates = []
    for dev_id, is_online in status_infos.items():
        dev_name = devices.get(dev_id)
        if dev_name in fleet_map:
            row_match = latest_df[latest_df['device_id'] == dev_id]
            voltage = row_match['voltage'].values if not row_match.empty else "N/A"
            
            # Final Health Logic
            battery_val = "Normal"
            if isinstance(voltage, (int, float)) and voltage <= 12.1:
                battery_val = "Low"
            
            # Prep Smartsheet Row (using your Mirror UI logic)
            new_row = smartsheet.models.Row()
            new_row.id = fleet_map[dev_name]
            # ... (rest of your cell mapping logic here) ...
            updates.append(new_row)

    if updates:
        smart.Sheets.update_rows(os.getenv("SMARTSHEET_ID"), updates)
        print(f"Sync Complete: {len(updates)} assets processed.")

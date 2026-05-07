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
    smart = smartsheet.Smartsheet(token)

    # 1. Map Smartsheet Names
    sheet = smart.Sheets.get_sheet(sheet_id)
    fleet_map = {str(row.cells.value).strip(): row.id for row in sheet.rows if row.cells.value}

    # 2. Bulk Fetch Geotab Data
    two_days_ago = (datetime.utcnow() - timedelta(days=2)).isoformat()
    
    # We pull all GoDeviceVoltage records for the whole fleet at once
    print("Fetching bulk health data from Geotab...", flush=True)
    raw_data = client.get('StatusData', search={
        'diagnosticSearch': {'id': 'DiagnosticGoDeviceVoltageId'},
        'fromDate': two_days_ago
    })

    # 3. Flatten to CSV / DataFrame
    # This turns that "nested folder" mess into a simple table
    df = pd.DataFrame(raw_data)
    
    # Clean the data: extract device ID and voltage value
    if not df.empty:
        df['device_id'] = df['device'].apply(lambda x: x['id'] if isinstance(x, dict) else None)
        df['voltage'] = df['data']
        # Keep only the newest record for each device
        df = df.sort_values('dateTime', ascending=False).drop_duplicates('device_id')
        df.to_csv('geotab_health_cache.csv', index=False)
        print("Geotab data flattened to CSV successfully.", flush=True)

    # 4. Get Device Names and Status
    devices = {d['id']: d['name'].strip() for d in client.get('Device')}
    status_infos = {si['device']['id']: si['isDeviceCommunicating'] for si in client.get('DeviceStatusInfo')}

    # 5. Build Updates
    updates = []
    for dev_id, is_online in status_infos.items():
        dev_name = devices.get(dev_id)
        
        if dev_name in fleet_map:
            # Look up voltage from our flattened CSV/DataFrame
            row_match = df[df['device_id'] == dev_id]
            voltage = row_match['voltage'].values if not row_match.empty else "N/A"
            
            # Logic Alignment: Match Geotab's "Low" (12.1V or Offline)
            battery_val = "Normal"
            if isinstance(voltage, (int, float)) and voltage <= 12.1:
                battery_val = "Low"
            elif not is_online and voltage == "N/A":
                battery_val = "Low"

            # Create Smartsheet Row Update
            new_row = smartsheet.models.Row()
            new_row.id = fleet_map[dev_name]
            
            cell_status = smartsheet.models.Cell()
            cell_status.column_id = STATUS_COL_ID
            cell_status.value = "Online" if is_online else "Offline"
            
            cell_battery = smartsheet.models.Cell()
            cell_battery.column_id = BATTERY_COL_ID
            cell_battery.value = battery_val
            
            new_row.cells.extend([cell_status, cell_battery])
            updates.append(new_row)
            print(f"PREP: {dev_name} | Volts: {voltage} | Status: {battery_val}", flush=True)

    # 6. Push to Smartsheet
    if updates:
        for i in range(0, len(updates), 500):
            smart.Sheets.update_rows(sheet_id, updates[i:i+500])
        print(f"Sync Complete: {len(updates)} assets updated.")

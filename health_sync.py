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
    print("--- Starting Health Sync (CSV Method) ---", flush=True)
    
    try:
        client = mygeotab.API(username=os.getenv("GEOTAB_USER"), 
                              password=os.getenv("GEOTAB_PASSWORD"), 
                              database=os.getenv("GEOTAB_DB"))
        client.authenticate()
        smart = smartsheet.Smartsheet(token)
        print("Connected to Geotab and Smartsheet.", flush=True)

        # 1. Map Smartsheet Names
        sheet = smart.Sheets.get_sheet(sheet_id)
        fleet_map = {}
        for row in sheet.rows:
            name_cell = next((c.value for c in row.cells if c.column_id == NAME_COL_ID), None)
            if name_cell:
                fleet_map[str(name_cell).strip()] = row.id
        print(f"Mapped {len(fleet_map)} vehicles from Smartsheet.", flush=True)

        # 2. Bulk Fetch Voltage Data (Updated to include Health Flag)
        two_days_ago = (datetime.utcnow() - timedelta(days=2)).isoformat()
        diags = [
            'DiagnosticGoDeviceVoltageId', 
            'DiagnosticDeviceBatteryVoltageId', 
            'DiagnosticDeviceHealthBatteryVoltageLowId' # The Geotab "Flag"
        ]
        all_raw_data = []

        for diag in diags:
            print(f"Fetching {diag}...", flush=True)
            batch = client.get('StatusData', search={
                'diagnosticSearch': {'id': diag},
                'fromDate': two_days_ago
            })
            if batch:
                all_raw_data.extend(batch)
                print(f"  -> Found {len(batch)} records.", flush=True)

        # 3. The CSV Flattening (Handling Nested Folders)
        print("Flattening data into CSV...", flush=True)
        df = pd.DataFrame(all_raw_data)
        
        if df.empty:
            print("CRITICAL: No voltage data found in Geotab for the last 48 hours.", flush=True)
            # Create empty DF with columns to prevent crash
            df = pd.DataFrame(columns=['dateTime', 'data', 'device', 'diagnostic'])
        else:
            # This lambda handles the list-vs-dict nesting issue automatically
            df['device_id'] = df['device'].apply(lambda x: x['id'] if isinstance(x, dict) else (x['id'] if isinstance(x, list) else None))
            df['voltage'] = df['data']
            # Sort and save
            df = df.sort_values('dateTime', ascending=False).drop_duplicates('device_id')
            df.to_csv('geotab_health_cache.csv', index=False)
            print(f"Saved {len(df)} unique vehicle records to geotab_health_cache.csv", flush=True)

        # 4. Get Current Status
        status_infos = {si['device']['id']: si['isDeviceCommunicating'] for si in client.get('DeviceStatusInfo')}
        devices = {d['id']: d['name'].strip() for d in client.get('Device')}

        # 4.5. Data Audit - Debugging specific assets
        print("--- Target Asset Audit ---", flush=True)
        targets = ["BUS 1", "BUS A", "VAN 2", "40", "47", "88", "CUBE 4"]
        for t_name in targets:
            # Find the ID for the target name
            t_id = next((i for i, n in devices.items() if n == t_name), None)
            if t_id:
                asset_data = df[df['device_id'] == t_id]
                if not asset_data.empty:
                    print(f"\nAUDIT: {t_name} ({t_id})")
                    for _, r in asset_data.iterrows():
                        d_id = r['diagnostic']
                        # Simplify diagnostic display
                        d_short = d_id['id'] if isinstance(d_id, dict) else str(d_id)
                        print(f"  -> {r['dateTime']} | {d_short} | Value: {r['data']}")
                else:
                    print(f"\nAUDIT: {t_name} ({t_id}) -> No data found in CSV.")
        print("\n--- End Audit ---\n", flush=True)
        
        # 5. Build Updates
        updates = []
        for dev_id, is_online in status_infos.items():
            dev_name = devices.get(dev_id)
            if dev_name in fleet_map:
                device_data = df[df['device_id'] == dev_id]
                
                # Precise Flag Detection
                has_health_flag = False
                voltage = "N/A"
                
                if not device_data.empty:
                    for _, row in device_data.iterrows():
                        diag_info = str(row['diagnostic'])
                        if 'HealthBatteryVoltageLow' in diag_info:
                            has_health_flag = True
                        if 'GoDeviceVoltage' in diag_info or 'DeviceBatteryVoltage' in diag_info:
                            if voltage == "N/A": # Grab the most recent one
                                voltage = row['data']

                # Final Health Logic
                battery_val = "Normal"
                if has_health_flag:
                    battery_val = "Low"
                elif isinstance(voltage, (int, float)) and 2.0 <= voltage <= 11.5:
                    battery_val = "Low"

                # Row Prep
                new_row = smartsheet.models.Row()
                new_row.id = fleet_map[dev_name]
                
                c_status = smartsheet.models.Cell()
                c_status.column_id = STATUS_COL_ID
                c_status.value = "Online" if is_online else "Offline"
                
                c_battery = smartsheet.models.Cell()
                c_battery.column_id = BATTERY_COL_ID
                c_battery.value = battery_val
                
                new_row.cells.extend([c_status, c_battery])
                updates.append(new_row)

        # 6. Push Batch
        if updates:
            for i in range(0, len(updates), 500):
                smart.Sheets.update_rows(sheet_id, updates[i:i+500])
            print(f"Sync Complete. Updated {len(updates)} rows in Smartsheet.", flush=True)

    except Exception as e:
        print(f"FATAL ERROR: {str(e)}", flush=True)

if __name__ == "__main__":
    run_health_sync()

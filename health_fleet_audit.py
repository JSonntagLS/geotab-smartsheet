import mygeotab
import os
import pandas as pd
from datetime import datetime, timedelta

def run_fleet_audit():
    print("--- Starting Full Fleet Battery & Connectivity Audit (health_fleet_audit.py) ---", flush=True)
    
    try:
        client = mygeotab.API(username=os.getenv("GEOTAB_USER"), 
                              password=os.getenv("GEOTAB_PASSWORD"), 
                              database=os.getenv("GEOTAB_DB"))
        client.authenticate()
        print("Connected to Geotab API successfully.", flush=True)

        # 1. Fetch All Devices & Communication Status
        devices = {d['id']: d['name'].strip() for d in client.get('Device')}
        status_infos = {si['device']['id']: si.get('isDeviceCommunicating', False) for si in client.get('DeviceStatusInfo')}
        print(f"Retrieved {len(devices)} total devices from Geotab.", flush=True)

        # 2. Setup 7-Day Date Window
        seven_days_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
        
        diags = [
            'DiagnosticGoDeviceVoltageId', 
            'DiagnosticDeviceBatteryVoltageId', 
            'DiagnosticDeviceHealthBatteryVoltageLowId'
        ]
        
        all_raw_data = []

        # 3. Pull 7-Day Telemetry Across Entire Fleet
        for diag in diags:
            print(f"Fetching full fleet logs for {diag}...", flush=True)
            batch = client.get('StatusData', search={
                'diagnosticSearch': {'id': diag},
                'fromDate': seven_days_ago
            })
            if batch:
                all_raw_data.extend(batch)
                print(f"  -> Found {len(batch)} records.", flush=True)

        ## 4. Process Data in Pandas
        df = pd.DataFrame(all_raw_data)
        
        audit_results = []

        for dev_id, dev_name in devices.items():
            is_comm = status_infos.get(dev_id, False)
            comm_status = "Online" if is_comm else "Offline"
            
            # Query last known GPS position timestamp directly
            last_log = client.get('LogRecord', search={'deviceSearch': {'id': dev_id}}, resultsLimit=1)
            last_gps_time = last_log[0]['dateTime'][:16].replace('T', ' ') if last_log else "No GPS Data"
            
            # Filter readings for specific device
            dev_df = df[df['device'].apply(lambda x: x.get('id') if isinstance(x, dict) else None) == dev_id] if not df.empty else pd.DataFrame()
            
            if not dev_df.empty:
                dev_df = dev_df.copy()
                dev_df['voltage'] = pd.to_numeric(dev_df['data'], errors='coerce')
                valid_voltages = dev_df['voltage'].dropna().tolist()
                
                if valid_voltages:
                    min_v = round(min(valid_voltages), 2)
                    avg_v = round(sum(valid_voltages) / len(valid_voltages), 2)
                    max_v = round(max(valid_voltages), 2)
                    total_readings = len(valid_voltages)
                else:
                    min_v, avg_v, max_v, total_readings = "N/A", "N/A", "N/A", 0
            else:
                min_v, avg_v, max_v, total_readings = "N/A", "N/A", "N/A", 0

            audit_results.append({
                'Vehicle Name': dev_name,
                'Geotab Comm Flag': is_comm,
                'GPS Status': comm_status,
                'Last GPS Fixed (UTC)': last_gps_time,
                'Min Volts': min_v,
                '7-Day Avg': avg_v,
                'Max Volts': max_v,
                'Readings Count': total_readings
            })

        # 5. Format and Output Full Fleet Results
        audit_df = pd.DataFrame(audit_results)
        audit_df = audit_df.sort_values(by=['GPS Status', 'Vehicle Name'], ascending=[True, True])

        print("\n" + "="*80, flush=True)
        print(" FULL FLEET TELEMETRY AUDIT REPORT", flush=True)
        print("="*80, flush=True)
        
        pd.set_option('display.max_rows', None)
        pd.set_option('display.max_columns', None)
        pd.set_option('display.width', 1000)
        
        print(audit_df.to_string(index=False), flush=True)
        print("="*80 + "\n", flush=True)

    except Exception as e:
        print(f"FATAL AUDIT ERROR: {str(e)}", flush=True)

if __name__ == "__main__":
    run_fleet_audit()

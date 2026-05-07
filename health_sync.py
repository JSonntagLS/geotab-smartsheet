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

        # 2. Setup Dates
        seven_days_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
        two_days_ago = (datetime.utcnow() - timedelta(days=2)).isoformat()
        
        diags = [
            'DiagnosticGoDeviceVoltageId', 
            'DiagnosticDeviceBatteryVoltageId', 
            'DiagnosticDeviceHealthBatteryVoltageLowId'
        ]
        all_raw_data = []

        for diag in diags:
            print(f"Fetching {diag}...", flush=True)
            search_date = two_days_ago if 'Health' in diag else seven_days_ago
            batch = client.get('StatusData', search={
                'diagnosticSearch': {'id': diag},
                'fromDate': search_date
            })
            if batch:
                all_raw_data.extend(batch)
                print(f"  -> Found {len(batch)} records.", flush=True)

        # 3. Flatten data
        df = pd.DataFrame(all_raw_data)
        if df.empty:
            print("CRITICAL: No voltage data found in Geotab.", flush=True)
            df = pd.DataFrame(columns=['dateTime', 'data', 'device', 'diagnostic'])
        else:
            # Convert 'data' column to actual numbers, ignoring errors
            df['voltage'] = pd.to_numeric(df['data'], errors='coerce')
            df['device_id'] = df['device'].apply(lambda x: x['id'] if isinstance(x, dict) else None)
            
            # SORT: Lowest voltage at the top. 
            # If Van 2 has [14.2, 12.1, 7.1], 7.1 moves to index 0.
            df = df.sort_values(['device_id', 'voltage'], ascending=[True, True])
            
            # KEEP the lowest one per device
            df = df.drop_duplicates('device_id')

        # 4. Get Devices and Status
        status_infos = {si['device']['id']: si['isDeviceCommunicating'] for si in client.get('DeviceStatusInfo')}
        devices = {d['id']: d['name'].strip() for d in client.get('Device')}

        # 5. VAN 2 FORENSIC DEBUGGER
        print("\n--- Van 2 Deep Dive ---", flush=True)
        van_2_id = next((i for i, n in devices.items() if "VAN 2" in n.upper()), None)
        if van_2_id:
            logs = client.get('StatusData', search={'deviceSearch': {'id': van_2_id}, 'diagnosticSearch': {'id': 'DiagnosticGoDeviceVoltageId'}, 'fromDate': seven_days_ago})
            if logs:
                v_list = [float(l['data']) for l in logs]
                print(f"Van 2 Range: {min(v_list)}V - {max(v_list)}V")
                if min(v_list) < 10.5: print(">>> CRANK DIP DETECTED")

        # 6. Build Updates with Pattern Logic
        updates = []
        print("\n--- Processing Fleet Updates ---", flush=True)
        for dev_id, is_comm in status_infos.items():
            dev_name = devices.get(dev_id)
            if dev_name in fleet_map:
                device_data = df[df['device_id'] == dev_id]
                
                # 1. Variables for Logic
                current_v = "N/A"
                avg_v = 0
                if not device_data.empty:
                    current_v = device_data.iloc[0]['voltage']
                
                # 2. Pull 7-day history to check for the "Van 2" pattern
                history = client.get('StatusData', search={'deviceSearch': {'id': dev_id}, 'diagnosticSearch': {'id': 'DiagnosticGoDeviceVoltageId'}, 'fromDate': seven_days_ago})
                if history:
                    v_list = [float(l['data']) for l in history if l['data']]
                    avg_v = sum(v_list) / len(v_list) if v_list else 0

                # 3. SURGICAL LOGIC (The Triple-Lock)
                if not is_comm:
                    status_val = "Offline"
                    battery_val = "N/A"
                else:
                    status_val = "Online"
                    
                    # Lock 1: Is the average truly poor? (Tightened to 12.0 to clear 73A)
                    is_poor_avg = (avg_v < 12.0 and avg_v > 0)
                    
                    # Lock 2: Is the current voltage a total blackout?
                    is_critical_now = (isinstance(current_v, (int, float)) and current_v < 9.0)
                    
                    # Lock 3: The "Van 2" Safety (Deep dip + Low-ish average)
                    v_min = min(v_list) if history and v_list else 15.0
                    is_deep_dip_fail = (v_min < 10.0 and avg_v < 12.3)

                    if is_poor_avg or is_critical_now or is_deep_dip_fail:
                        battery_val = "Low"
                    else:
                        battery_val = "Normal"

                # 4. Debug Output
                if battery_val == "Low" or any(x in dev_name.upper() for x in ["VAN 2", "BUS 1", "BUS A", "CUBE 4", "73A"]):
                    print(f"RESULT: {dev_name[:30]:<30} | Status: {battery_val:<7} | Avg: {round(avg_v, 2):<5} | Now: {current_v}")

                # 5. Prepare Smartsheet Row
                new_row = smartsheet.models.Row()
                new_row.id = fleet_map[dev_name]
                new_row.cells.append(smartsheet.models.Cell({'column_id': STATUS_COL_ID, 'value': status_val}))
                new_row.cells.append(smartsheet.models.Cell({'column_id': BATTERY_COL_ID, 'value': battery_val}))
                updates.append(new_row)

        # 7. Push Batch
        if updates:
            print(f"Pushing {len(updates)} updates to Smartsheet...", flush=True)
            for i in range(0, len(updates), 500):
                smart.Sheets.update_rows(sheet_id, updates[i:i+500])
            print("Sync Complete.", flush=True)

    except Exception as e:
        print(f"FATAL ERROR: {str(e)}", flush=True)

if __name__ == "__main__":
    run_health_sync()

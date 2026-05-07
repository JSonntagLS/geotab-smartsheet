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

        # 6. EXPANDED PATTERN FINDER
        updates = []
        print("\n--- PATTERN ANALYSIS START ---", flush=True)
        print(f"{'VEHICLE':<30} | {'NOW':<6} | {'MIN':<6} | {'AVG':<6} | {'DIP?':<6}", flush=True)
        print("-" * 70)

        for dev_id, _ in status_infos.items():
            if dev_name in fleet_map:
                device_data = df[df['device_id'] == dev_id]
                status_list = client.get('DeviceStatusInfo', search={'deviceSearch': {'id': dev_id}})
                
                # 1. Get Connection Status
                is_actually_comm = False
                if isinstance(status_list, list) and len(status_list) > 0:
                    is_actually_comm = status_list[0].get('isDeviceCommunicating', False)

                # 2. Get Data for Logic (Current and Average)
                current_v = "N/A"
                avg_v = 0
                if not device_data.empty:
                    current_v = device_data.iloc[0]['voltage']
                
                # We pull the 7-day history to get the "Pattern"
                history = client.get('StatusData', search={'deviceSearch': {'id': dev_id}, 'diagnosticSearch': {'id': 'DiagnosticGoDeviceVoltageId'}, 'fromDate': seven_days_ago})
                if history:
                    v_list = [float(l['data']) for l in history if l['data']]
                    avg_v = sum(v_list) / len(v_list) if v_list else 0

                # --- THE NEW SURGICAL LOGIC ---
                # Flag as LOW if the Average is garbage (< 12.2) OR current is critical (< 11.0)
                is_low_by_avg = (avg_v < 12.2 and avg_v > 0)
                is_low_by_now = (isinstance(current_v, (int, float)) and current_v < 11.0)

                if is_low_by_avg or is_low_by_now:
                    battery_val = "Low"
                else:
                    battery_val = "Normal" if is_actually_comm else "N/A"
                
                status_val = "Online" if is_actually_comm else "Offline"
                # --- END LOGIC ---

                # DEBUG PRINT: This tells us if our theory is working
                if battery_val == "Low" or any(x in dev_name.upper() for x in ["VAN 2", "BUS 1", "BUS A", "CUBE 4"]):
                    print(f"VERIFICATION: {dev_name} | Status: {battery_val} | Avg: {round(avg_v, 2)} | Now: {current_v}")

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

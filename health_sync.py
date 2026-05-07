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

        # 2. Bulk Fetch Voltage Data (Expanded to 7 days for Offline assets)
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
            # Use 7 days for voltage, 2 days for the health flag
            search_date = two_days_ago if 'Health' in diag else seven_days_ago
            batch = client.get('StatusData', search={
                'diagnosticSearch': {'id': diag},
                'fromDate': search_date
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

        # INSERT THE VAN 2 DEBUGGER HERE
        # ==========================================
        print("\n--- Investigating Van 2 Battery Health ---", flush=True)
        # Find the specific ID for Van 2 from the devices we just fetched
        van_2_matches = [i for i, n in devices.items() if "VAN 2" in n.upper()]
        
        if van_2_matches:
            van_2_id = van_2_matches
            import datetime
            three_days_ago = datetime.datetime.now() - datetime.timedelta(days=3)
        
            # 1. Get the Voltage Curve
            logs = client.get('StatusData', search={
                'deviceSearch': {'id': van_2_id},
                'diagnosticSearch': {'id': 'DiagnosticGoDeviceVoltageId'},
                'fromDate': three_days_ago
            })
        
            # 2. Get any specific Battery Faults
            faults = client.get('FaultData', search={
                'deviceSearch': {'id': van_2_id},
                'fromDate': three_days_ago
            })
        
            if logs:
                voltages = [float(l['data']) for l in logs]
                print(f"Van 2 Min Voltage (72h): {min(voltages)}V")
                print(f"Van 2 Max Voltage (72h): {max(voltages)}V")
                if min(voltages) < 10.0:
                    print(">>> DETECTED CRANK DIP: Voltage dropped significantly during start.")
        
            if faults:
                for f in faults:
                    # This identifies if Geotab explicitly threw a "Low Battery" flag
                    print(f">>> GEOTAB FAULT: {f['diagnostic']['id']} logged at {f['dateTime']}")
            else:
                print("No specific Geotab Faults found for Van 2 in the last 3 days.")
        else:
            print("Could not find a vehicle named 'Van 2' in Geotab.")
        # ==========================================

        # --- VAN 2 FORENSIC DEBUGGER ---
        print("\n--- Investigating Van 2 Battery Health ---", flush=True)
        van_2_id = next((i for i, n in devices.items() if "VAN 2" in n.upper()), None)
        if van_2_id:
            three_days_ago = (datetime.utcnow() - timedelta(days=3)).isoformat()
            # Get the raw voltage curve to check for Crank Dips
            logs = client.get('StatusData', search={'deviceSearch': {'id': van_2_id}, 'diagnosticSearch': {'id': 'DiagnosticGoDeviceVoltageId'}, 'fromDate': three_days_ago})
            if logs:
                v_list = [float(l['data']) for l in logs]
                print(f"Van 2 Range: {min(v_list)}V to {max(v_list)}V")
                if min(v_list) < 10.5:
                    print(f">>> ALERT: Van 2 dropped to {min(v_list)}V. This confirms a weak battery during startup.")

        # 5. Build Updates
        updates = []
        print("\n--- Processing Fleet Updates ---", flush=True)
        
        for dev_id, _ in status_infos.items():
            dev_name = devices.get(dev_id)
            if dev_name in fleet_map:
                device_data = df[df['device_id'] == dev_id]
                
                # Fetch Status correctly as a list
                status_list = client.get('DeviceStatusInfo', search={'deviceSearch': {'id': dev_id}})
                
                is_actually_comm = False
                if isinstance(status_list, list) and len(status_list) > 0:
                    # FIX: We must access the first item of the list before calling .get()
                    s_info = status_list
                    is_actually_comm = s_info.get('isDeviceCommunicating', False)

                status_val = "Online" if is_actually_comm else "Offline"
        
        # 5. Build Updates
        updates = []
        print("--- Processing Fleet Updates ---", flush=True)
        
        for dev_id, is_online in status_infos.items():
            dev_name = devices.get(dev_id)
            if dev_name in fleet_map:
                device_data = df[df['device_id'] == dev_id]
                
                # REFIX: Safely handle the list return from Geotab
                status_list = client.get('DeviceStatusInfo', search={'deviceSearch': {'id': dev_id}})
                
                # Check if we have a valid list with at least one item
                if isinstance(status_list, list) and len(status_list) > 0:
                    s_info = status_list
                    # Use the API's actual communication status
                    is_actually_comm = s_info.get('isDeviceCommunicating', False)
                else:
                    is_actually_comm = False

                status_val = "Online" if is_actually_comm else "Offline"
                battery_val = "N/A"
                voltage = "N/A"
                has_health_flag = False

                if is_actually_comm:
                    battery_val = "Normal"
                    if not device_data.empty:
                        device_data = device_data.sort_values('dateTime', ascending=False)
                        for _, row in device_data.iterrows():
                            diag_info = str(row['diagnostic'])
                            if 'HealthBatteryVoltageLow' in diag_info:
                                has_health_flag = True
                            if ('GoDeviceVoltage' in diag_info or 'DeviceBatteryVoltage' in diag_info) and voltage == "N/A":
                                voltage = row['data']

                    # VAN 2 SPECIAL CHECK: Look for 'Low Battery' Faults specifically
                    if not has_health_flag and "VAN 2" in dev_name.upper():
                        # Check for the specific Low Battery Fault ID
                        fault_search = client.get('FaultData', search={
                            'deviceSearch': {'id': dev_id},
                            'fromDate': seven_days_ago,
                            'diagnosticSearch': {'id': 'DiagnosticLowBatteryFaultId'}
                        })
                        if fault_search:
                            has_health_flag = True

                    # Final assignment based on flags or raw voltage
                    if has_health_flag:
                        battery_val = "Low"
                    elif isinstance(voltage, (int, float)) and 2.0 <= voltage <= 11.9:
                        battery_val = "Low"

                # Build Smartsheet Row
                new_row = smartsheet.models.Row()
                new_row.id = fleet_map[dev_name]
                
                new_row.cells.append(smartsheet.models.Cell({'column_id': STATUS_COL_ID, 'value': status_val}))
                new_row.cells.append(smartsheet.models.Cell({'column_id': BATTERY_COL_ID, 'value': battery_val}))
                updates.append(new_row)

                # Monitor targets in console
                if any(x in dev_name.upper() for x in ["37", "VAN 2", "BUS 1", "BUS A"]):
                    print(f"DEBUG: {dev_name} | Status: {status_val} | Battery: {battery_val} | V: {voltage}", flush=True)

        # 6. Push to Smartsheet
        if updates:
            print(f"Pushing {len(updates)} updates to Smartsheet...", flush=True)
            # Smartsheet allows 500 rows per request, so we are safe with 73
            ss_client.Sheets.update_rows(SHEET_ID, updates)
            print("Sync Complete.", flush=True)
        # 6. Push Batch
        if updates:
            for i in range(0, len(updates), 500):
                smart.Sheets.update_rows(sheet_id, updates[i:i+500])
            print(f"Sync Complete. Updated {len(updates)} rows in Smartsheet.", flush=True)

    except Exception as e:
        print(f"FATAL ERROR: {str(e)}", flush=True)

if __name__ == "__main__":
    run_health_sync()

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

        # 2. Fetch Native Geotab Device and Status Objects
        print("Fetching native Geotab DeviceStatusInfo...", flush=True)
        raw_devices = client.get('Device')
        devices = {d['id']: d['name'].strip() for d in raw_devices}
        
        status_info_list = client.get('DeviceStatusInfo')
        
        # 3. Fetch Active Faults for Low Battery Detection
        print("Fetching active Geotab ExceptionEvents...", flush=True)
        active_exceptions = client.get('ExceptionEvent', search={'isDismissed': False})
        low_battery_device_ids = set()
        
        for exc in active_exceptions:
            rule_id = exc.get('rule', {}).get('id', '')
            dev_id = exc.get('device', {}).get('id')
            if dev_id and ('Battery' in rule_id or 'Voltage' in rule_id or 'LowPower' in rule_id):
                low_battery_device_ids.add(dev_id)

        # 4. Build Updates Direct from Geotab Status Flags
        updates = []
        print("\n--- Processing Fleet Updates ---", flush=True)
        for si in status_info_list:
            dev_id = si.get('device', {}).get('id')
            dev_name = devices.get(dev_id)
            
            if dev_name and dev_name in fleet_map:
                # Direct Offline Check using Geotab's native state
                is_comm = si.get('isDeviceCommunicating', True)
                status_val = "Online" if is_comm else "Offline"
                
                # Direct Low Battery Check from Geotab's active exception flags
                battery_val = "Low" if dev_id in low_battery_device_ids else "Normal"
                
                print(f"RESULT: {dev_name[:30]:<30} | GPS: {status_val:<7} | Battery: {battery_val}")

                # Prepare Smartsheet Row
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

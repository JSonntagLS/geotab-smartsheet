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

    # 1. Fetch Smartsheet data once and map names to Row IDs
    # This prevents nested loops and "KeyErrors" from missing matches
    sheet = smart.Sheets.get_sheet(sheet_id)
    fleet_map = {} # { "Vehicle Name": row_id }
    for row in sheet.rows:
        name_cell = next((c.value for c in row.cells if c.column_id == NAME_COL_ID), None)
        if name_cell:
            fleet_map[str(name_cell).strip()] = row.id

    # 2. Get Geotab Status & Device Names
    # We pull 'Device' and 'DeviceStatusInfo' to ensure we have names
    devices = client.get('Device')
    status_infos = client.get('DeviceStatusInfo')
    
    # Create a lookup for status by device ID
    status_lookup = {si['device']['id']: si for si in status_infos}
    
    updates = []
    
    # 3. Process the devices
    for dev in devices:
        dev_name = dev.get('name', '').strip()
        dev_id = dev.get('id')
        
        # Only proceed if this vehicle exists in your Smartsheet
        if dev_name in fleet_map:
            status_data = status_lookup.get(dev_id)
            if not status_data:
                continue
                
            is_offline = not status_data.get('isDeviceCommunicating', False)
            
            # Check Battery
            # --- IMPROVED BATTERY CHECK ---
            # --- IMPROVED BATTERY CHECK ---
            battery_val = "Normal"
            two_days_ago = datetime.utcnow() - timedelta(days=2)
            
            # 1. Try the standard IDs first
            batt_logs = client.get('StatusData', search={
                'deviceSearch': {'id': dev_id},
                'diagnosticSearch': {'id': 'DiagnosticDeviceBatteryVoltageId'},
                'fromDate': two_days_ago.isoformat(),
                'resultsLimit': 1
            })
            
            if not batt_logs:
                batt_logs = client.get('StatusData', search={
                    'deviceSearch': {'id': dev_id},
                    'diagnosticSearch': {'id': 'DiagnosticEngineBatteryVoltageId'},
                    'fromDate': two_days_ago.isoformat(),
                    'resultsLimit': 1
                })

            # 2. WILDCARD FALLBACK: If still nothing, search by the 'Voltage' unit/name
            # Some newer Nissans/Hyundais report voltage under custom manufacturer IDs
            if not batt_logs:
                all_logs = client.get('StatusData', search={
                    'deviceSearch': {'id': dev_id},
                    'fromDate': two_days_ago.isoformat(),
                    'resultsLimit': 50
                })
                # Filter through the last 50 logs for anything that looks like voltage
                for log in all_logs:
                    diag = log.get('diagnostic', {})
                    diag_id = diag.get('id', '')
                    if 'Voltage' in diag_id:
                        batt_logs = [log]
                        break

            # 3. Final Evaluation
            if batt_logs:
                log = batt_logs
                voltage = log.get('data', 0)
                # Filter out garbage data (like 0V or 255V)
                if 2.0 <= voltage <= 11.6:
                    battery_val = "Low"
                
                print(f"DEBUG: {dev_name} | Voltage: {voltage} | ID: {log.get('diagnostic', {}).get('id')}", flush=True)
            else:
                # If still no logs, we leave it as "Normal" to avoid false alarms
                print(f"DEBUG: {dev_name} | No Voltage Data found in Geotab for last 48h.", flush=True)
            # --- END BATTERY CHECK ---
            
            status_val = "Offline" if is_offline else "Online"
            
            # BUILD THE UPDATE (Corrected for Smartsheet SDK)
            # BUILD THE UPDATE (Corrected for Smartsheet SDK strictness)
            new_row = smartsheet.models.Row()
            new_row.id = fleet_map[dev_name]
            
            # Create Status Cell
            cell_status = smartsheet.models.Cell()
            cell_status.column_id = STATUS_COL_ID
            cell_status.value = status_val
            
            # Create Battery Cell
            cell_battery = smartsheet.models.Cell()
            cell_battery.column_id = BATTERY_COL_ID
            cell_battery.value = battery_val
            
            new_row.cells.append(cell_status)
            new_row.cells.append(cell_battery)
            updates.append(new_row)

    # 4. Push updates
    if updates:
        # Smartsheet allows 500 rows per update call
        for i in range(0, len(updates), 500):
            batch = updates[i:i+500]
            smart.Sheets.update_rows(sheet_id, batch)
        print(f"Health Sync Complete: Updated {len(updates)} assets.")

if __name__ == "__main__":
    run_health_sync()

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
            battery_val = "Normal"
            two_days_ago = datetime.utcnow() - timedelta(days=2)
            
            # Diagnostic IDs
            diag_id = 'DiagnosticDeviceBatteryVoltageId'
            
            batt_logs = client.get('StatusData', search={
                'deviceSearch': {'id': dev_id},
                'diagnosticSearch': {'id': diag_id},
                'fromDate': two_days_ago.isoformat(),
                'resultsLimit': 1
            })
            
            if not batt_logs:
                # Try Engine Battery ID if Device Battery is empty
                batt_logs = client.get('StatusData', search={
                    'deviceSearch': {'id': dev_id},
                    'diagnosticSearch': {'id': 'DiagnosticEngineBatteryVoltageId'},
                    'fromDate': two_days_ago.isoformat(),
                    'resultsLimit': 1
                })

            if batt_logs:
                log = batt_logs # Get the first record from the list
                voltage = log.get('data', 0)
                print(f"DEBUG: {dev_name} | Voltage: {voltage} | Date: {log.get('dateTime')}", flush=True)
                # Check 1: Is the voltage actually low?
                # Check 2: Is the data older than 48 hours? (Often indicates a dead unit)
                if voltage <= 11.6:
                    battery_val = "Low"
            else:
                # If no logs exist in the last 2 days, and the device is offline, 
                # it's safer to flag as Low/Unknown rather than "Normal"
                if is_offline:
                    battery_val = "Low"
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

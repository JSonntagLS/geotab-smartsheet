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
            
            # --- IMPROVED BATTERY CHECK ---
            battery_val = "Normal"
            two_days_ago = datetime.utcnow() - timedelta(days=2)
            
            # 1. Ask Geotab if IT thinks the battery is low
            health_check = client.get('StatusData', search={
                'deviceSearch': {'id': dev_id},
                'diagnosticSearch': {'id': 'DiagnosticDeviceHealthBatteryVoltageLowId'},
                'fromDate': two_days_ago.isoformat(),
                'resultsLimit': 1
            })

            # 2. Get the actual voltage for our Debug logs
            volt_log_list = client.get('StatusData', search={
                'deviceSearch': {'id': dev_id},
                'diagnosticSearch': {'id': 'DiagnosticGoDeviceVoltageId'},
                'fromDate': two_days_ago.isoformat(),
                'resultsLimit': 1
            })
            
            # SAFE ACCESS: Initialize as "N/A", then extract from the list if it exists
            current_volts = "N/A"
            if isinstance(volt_log_list, list) and len(volt_log_list) > 0:
                first_log = volt_log_list # Get the dictionary from the list
                current_volts = first_log.get('data', 0) # Now call .get() on the dictionary

            # 3. Decision Logic
            if health_check:
                battery_val = "Low"
                v_display = round(current_volts, 2) if isinstance(current_volts, (int, float)) else current_volts
                print(f"DEBUG: {dev_name} | Volts: {v_display} | GEOTAB FLAG: LOW detected", flush=True)
            else:
                # Critical Safety Net (under 11.4V)
                if isinstance(current_volts, (int, float)) and 2.0 <= current_volts <= 11.4:
                    battery_val = "Low"
                    print(f"DEBUG: {dev_name} | Volts: {round(current_volts, 2)} | CRITICAL VOLTAGE detected", flush=True)
                else:
                    v_display = round(current_volts, 2) if isinstance(current_volts, (int, float)) else current_volts
                    print(f"DEBUG: {dev_name} | Volts: {v_display} | Status: Normal", flush=True)
            # --- END BATTERY CHECK ---
            
            status_val = "Offline" if is_offline else "Online"
            
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

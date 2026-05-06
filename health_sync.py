import mygeotab
import smartsheet
import os

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
            battery_val = "Normal"
            batt_logs = client.get('StatusData', search={
                'deviceSearch': {'id': dev_id},
                'diagnosticSearch': {'id': 'DiagnosticDeviceBatteryVoltageId'},
                'resultsLimit': 1
            })
            
            if batt_logs and batt_logs['data'] < 11.57:
                battery_val = "Low"
            
            status_val = "Offline" if is_offline else "Online"
            
            # Build the update
            new_row = smartsheet.models.Row(id=fleet_map[dev_name])
            new_row.cells.append(smartsheet.models.Cell(column_id=STATUS_COL_ID, value=status_val))
            new_row.cells.append(smartsheet.models.Cell(column_id=BATTERY_COL_ID, value=battery_val))
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

import mygeotab
import smartsheet
import os

# --- CONFIG ---
token = os.getenv("SMARTSHEET_TOKEN")
sheet_id = os.getenv("SMARTSHEET_ID")
# Column IDs provided by user
STATUS_COL_ID = 2274350475808644
BATTERY_COL_ID = 6777950103179140

def run_health_sync():
    # 1. Connect to Geotab & Smartsheet
    client = mygeotab.API(username=os.getenv("GEOTAB_USER"), 
                          password=os.getenv("GEOTAB_PASSWORD"), 
                          database=os.getenv("GEOTAB_DB"))
    client.authenticate()
    smart = smartsheet.Smartsheet(token)

    # 2. Get Geotab Status
    # isDeviceCommunicating handles the 'Offline' logic
    # We use diagnostic for battery voltage
    devices = client.get('DeviceStatusInfo')
    
    # 3. Map Geotab Data to Smartsheet Rows
    # We match by Vehicle Name (assuming it's unique in your sheet)
    sheet = smart.Sheets.get_sheet(sheet_id)
    name_col_id = 6654095235780484 # From your previous OIL_COL_IDS

    updates = []
    for dev in devices:
        name = dev['device']['name']
        is_offline = not dev['isDeviceCommunicating']
        
        # Check Battery Voltage (DiagnosticId: DiagnosticDeviceBatteryVoltageId)
        batt_logs = client.get('StatusData', search={
            'deviceSearch': {'id': dev['device']['id']},
            'diagnosticSearch': {'id': 'DiagnosticDeviceBatteryVoltageId'},
            'resultsLimit': 1
        })
        
        status_val = "Offline" if is_offline else "Online"
        battery_val = "Normal"
        if batt_logs and batt_logs['data'] < 11.57:
            battery_val = "Low"

        # Find the row in Smartsheet
        for row in sheet.rows:
            row_name = next((c.value for c in row.cells if c.column_id == name_col_id), None)
            if row_name == name:
                new_row = smartsheet.models.Row(id=row.id)
                new_row.cells.append(smartsheet.models.Cell(column_id=STATUS_COL_ID, value=status_val))
                new_row.cells.append(smartsheet.models.Cell(column_id=BATTERY_COL_ID, value=battery_val))
                updates.append(new_row)
                break

    # 4. Push updates in bulk
    if updates:
        smart.Sheets.update_rows(sheet_id, updates)
        print(f"Health Sync Complete: Updated {len(updates)} assets.")

if __name__ == "__main__":
    run_health_sync()

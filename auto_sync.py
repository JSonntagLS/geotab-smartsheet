import mygeotab
import pandas as pd
import os
import smartsheet
from datetime import datetime, timedelta

# --- CONFIGURATION (Column IDs from your Step 1) ---
COL_SERIAL = 4402295422095236
COL_MONDAY = 1876872503005060
COL_CURRENT = 8905895049465732
COL_SYNC = 109802027257732

def harvest_data():
    now = datetime.utcnow()
    # Anchor to last Monday at 12:01 AM
    days_since_monday = now.weekday()
    monday_start = (now - timedelta(days=days_since_monday + 7)).replace(hour=0, minute=1, second=0, microsecond=0)
    start_date_str = monday_start.isoformat()
    
    print(f"--- STARTING SYNC: {now} ---")
    
    # 1. GEOTAB DATA PULL
    api = mygeotab.API(username=os.getenv("GEOTAB_USER"), password=os.getenv("GEOTAB_PASSWORD"), database=os.getenv("GEOTAB_DB"))
    api.authenticate()

    devices = api.get('Device')
    diagnostics = ['DiagnosticOdometerAdjustmentId', 'DiagnosticOdometerId']
    
    current_odo = {}
    monday_odo = {}

    for diag in diagnostics:
        logs = api.get('StatusData', search={'diagnosticSearch': {'id': diag}, 'fromDate': start_date_str, 'resultsLimit': 2000})
        for log in logs:
            dev_id = log['device']['id']
            val, ts = log.get('data', 0), log.get('dateTime')
            if dev_id not in current_odo or ts > current_odo[dev_id]['ts']:
                current_odo[dev_id] = {'val': val, 'ts': ts}
            if dev_id not in monday_odo or ts < monday_odo[dev_id]['ts']:
                monday_odo[dev_id] = {'val': val, 'ts': ts}

    # 2. SMARTSHEET INTEGRATION
    smart = smartsheet.Smartsheet(os.getenv("SMARTSHEET_TOKEN"))
    sheet_id = int(os.getenv("SMARTSHEET_ID"))
    sheet = smart.Sheets.get_sheet(sheet_id)
    
    # Map Serial Number to Row ID for updating
    # This prevents breaking cell links because we aren't deleting rows
    row_map = {}
    for row in sheet.rows:
        serial_cell = next((c.value for c in row.cells if c.column_id == COL_SERIAL), None)
        if serial_cell:
            row_map[str(serial_cell).strip()] = row.id

    rows_to_update = []
    
    for d in devices:
        serial = str(d.get('serialNumber')).strip()
        dev_id = d.get('id')
        
        # Only update if the vehicle exists in your Smartsheet
        if serial in row_map:
            curr = current_odo.get(dev_id)
            start = monday_odo.get(dev_id)
            
            curr_miles = round(curr['val'] / 1609.344, 0) if curr else 0
            start_miles = round(start['val'] / 1609.344, 0) if start else 0
            sync_date = curr['ts'].strftime('%Y-%m-%d') if curr else "N/A"

            # Build the update row
            new_row = smartsheet.models.Row()
            new_row.id = row_map[serial]
            new_row.cells.append({'column_id': COL_MONDAY, 'value': start_miles})
            new_row.cells.append({'column_id': COL_CURRENT, 'value': curr_miles})
            new_row.cells.append({'column_id': COL_SYNC, 'value': sync_date})
            rows_to_update.append(new_row)
            
            print(f"MATCH: {d.get('name')} | Updating Serial {serial}")
        else:
            # If a car is in Geotab but not Smartsheet, we just log it and move on.
            # No breakage, no errors.
            pass

    # Perform the bulk update
    if rows_to_update:
        smart.Sheets.update_rows(sheet_id, rows_to_update)
        print(f"SUCCESS: Updated {len(rows_to_update)} rows in Smartsheet.")
    else:
        print("Done. No matching serials found to update.")

if __name__ == "__main__":
    harvest_data()

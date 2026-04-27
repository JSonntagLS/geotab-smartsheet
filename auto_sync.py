import mygeotab
import smartsheet
import os
from datetime import datetime

def unified_sync():
    print(f"--- STARTING AUTOMATED SYNC: {datetime.now()} ---")
    
    # 1. Auth
    api = mygeotab.API(username=os.getenv("GEOTAB_USER"), password=os.getenv("GEOTAB_PASSWORD"), database=os.getenv("GEOTAB_DB"))
    api.authenticate()
    smart = smartsheet.Smartsheet(os.getenv("SMARTSHEET_TOKEN"))
    sheet_id = int(os.getenv("SMARTSHEET_ID"))
    
    # 2. Get Geotab Data (The Loop Fix)
    devices = api.get('Device')
    mileage_updates = {}
    for d in devices:
        curr_logs = api.get('StatusData', search={'deviceSearch': {'id': d['id']}, 'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 'resultsLimit': 1})
        if curr_logs:
            mileage_updates[d['serialNumber']] = round(curr_logs['data'] / 1609.344, 0)
        else:
            # If no data, we DON'T send a 0. We send a flag or skip it to preserve Smartsheet's last value.
            mileage_updates[d['serialNumber']] = "CHECK GPS"

    # 3. Push to Smartsheet
    sheet = smart.Sheets.get_sheet(sheet_id)
    col_map = {col.title.strip(): col.id for col in sheet.columns}
    
    rows_to_update = []
    for row in sheet.rows:
        # Match by Serial Number column
        serial_cell = next((c for c in row.cells if c.column_id == col_map.get("Serial")), None)
        if serial_cell and serial_cell.value in mileage_updates:
            new_val = mileage_updates[serial_cell.value]
            
            # Skip update if it's "CHECK GPS" to avoid overwriting with bad data
            if new_val == "CHECK GPS": continue 

            new_row = smartsheet.models.Row(id=row.id)
            new_row.cells.append(smartsheet.models.Cell(column_id=col_map["Current Mileage"], value=new_val))
            new_row.cells.append(smartsheet.models.Cell(column_id=col_map["Last Sync Date"], value=datetime.now().strftime("%Y-%m-%d")))
            rows_to_update.append(new_row)

    if rows_to_update:
        smart.Sheets.update_rows(sheet_id, rows_to_update)
        print(f"SUCCESS: Updated {len(rows_to_update)} vehicles.")

if __name__ == "__main__":
    unified_sync()

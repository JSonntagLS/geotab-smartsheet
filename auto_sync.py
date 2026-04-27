import mygeotab
import smartsheet
import os
from datetime import datetime

def unified_sync():
    print(f"--- STARTING AUTOMATED SYNC: {datetime.now()} ---")
    
    # 1. Auth
    api = mygeotab.API(username=os.getenv("GEOTAB_USER"), 
                       password=os.getenv("GEOTAB_PASSWORD"), 
                       database=os.getenv("GEOTAB_DB"))
    api.authenticate()
    
    smart = smartsheet.Smartsheet(os.getenv("SMARTSHEET_TOKEN"))
    sheet_id = int(os.getenv("SMARTSHEET_ID"))
    
    # 2. Get Geotab Data (Specific Device Loop)
    devices = api.get('Device')
    mileage_updates = {}
    
    for d in devices:
        dev_id = d['id']
        serial = d.get('serialNumber')
        
        # Pull the absolute most recent log for this specific device
        curr_logs = api.get('StatusData', search={
            'deviceSearch': {'id': dev_id},
            'diagnosticSearch': {'id': 'DiagnosticOdometerId'},
            'resultsLimit': 1
        })
        
        # CRITICAL FIX: We check if curr_logs is a list and get the first item
        if isinstance(curr_logs, list) and len(curr_logs) > 0:
            meters = curr_logs.get('data', 0)
            miles = round(meters / 1609.344, 0)
            mileage_updates[serial] = miles
        else:
            # Skip if no data found
            continue

    # 3. Push to Smartsheet
    sheet = smart.Sheets.get_sheet(sheet_id)
    col_map = {col.title.strip(): col.id for col in sheet.columns}
    
    mil_col_id = col_map.get("Current Mileage")
    ser_col_id = col_map.get("Serial")
    date_col_id = col_map.get("Last Sync Date")

    rows_to_update = []
    for row in sheet.rows:
        # Get the serial number from the Smartsheet row to match with Geotab
        ser_cell = next((c for c in row.cells if c.column_id == ser_col_id), None)
        
        if ser_cell and ser_cell.value in mileage_updates:
            new_mileage = mileage_updates[ser_cell.value]
            
            new_row = smartsheet.models.Row(id=row.id)
            
            # Cell for Mileage
            c1 = smartsheet.models.Cell(column_id=mil_col_id, value=new_mileage)
            # Cell for Sync Date
            c2 = smartsheet.models.Cell(column_id=date_col_id, value=datetime.now().strftime("%Y-%m-%d"))
            
            new_row.cells.extend([c1, c2])
            rows_to_update.append(new_row)

    if rows_to_update:
        smart.Sheets.update_rows(sheet_id, rows_to_update)
        print(f"SUCCESS: Updated {len(rows_to_update)} vehicles.")
    else:
        print("No matches found to update.")

if __name__ == "__main__":
    unified_sync()

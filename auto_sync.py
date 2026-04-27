import mygeotab
import smartsheet
import pandas as pd
from datetime import datetime
import os

def get_sync_bot():
    try:
        print("Robot waking up...")
        
        # Geotab Setup
        api = mygeotab.API(username=os.getenv("GEOTAB_USER"), 
                           password=os.getenv("GEOTAB_PASSWORD"), 
                           database=os.getenv("GEOTAB_DB"))
        api.authenticate()
        print("Geotab Authenticated.")

        # Fetch Data
        devices = api.get('Device')
        print(f"Found {len(devices)} devices in Geotab.")
        
        raw_odo = api.get('StatusData', search={'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 'resultsLimit': len(devices)})
        adj_odo = api.get('StatusData', search={'diagnosticSearch': {'id': 'DiagnosticOdometerAdjustmentId'}, 'resultsLimit': len(devices)})

        mileage_dict = {}
        for item in (raw_odo + adj_odo):
            dev_id = item['device']['id']
            miles = round(item['data'] / 1609.344, 0)
            if dev_id not in mileage_dict or miles > mileage_dict[dev_id]:
                mileage_dict[dev_id] = miles

        # Smartsheet Setup
        smart = smartsheet.Smartsheet(os.getenv("SMARTSHEET_TOKEN"))
        sheet_id = int(os.getenv("SMARTSHEET_ID"))
        sheet = smart.Sheets.get_sheet(sheet_id)
        print(f"Connected to Smartsheet: {sheet.name}")
        
        today_date = datetime.now().strftime("%Y-%m-%d")

        # COLUMN MAPPING
        col_map = {col.title.strip(): col.id for col in sheet.columns}
        primary_col_id = next((col.id for col in sheet.columns if col.primary), None)
        
        mil_col_id = col_map.get("Current Mileage")
        last_week_col_id = col_map.get("Last Week's Odometer") # NEW COLUMN
        ser_col_id = col_map.get("Serial")
        date_col_id = col_map.get("Last Sync Date")

        # BUILD LOOKUP AND CAPTURE PREVIOUS DATA
        ss_rows_lookup = {}
        for r in sheet.rows:
            # Find the primary cell (Vehicle Name)
            veh_cell = next((c for c in r.cells if c.column_id == primary_col_id), None)
            
            # Find the existing 'Current Mileage' value to shift it
            current_mil_cell = next((c for c in r.cells if c.column_id == mil_col_id), None)
            existing_value = current_mil_cell.value if current_mil_cell else None

            if veh_cell:
                name_val = veh_cell.value if veh_cell.value is not None else veh_cell.display_value
                name = str(name_val or "").strip().upper()
                if name:
                    # Store both the row ID and the current mileage found in the sheet
                    ss_rows_lookup[name] = {"id": r.id, "old_value": existing_value}
        
        print(f"Indexed {len(ss_rows_lookup)} rows from Smartsheet.")

        updated_rows = []
        seen_ids = set()

        for d in devices:
            name = str(d['name']).strip().upper()
            if name in ss_rows_lookup:
                row_info = ss_rows_lookup[name]
                row_id = row_info["id"]
                
                if row_id not in seen_ids:
                    new_row = smartsheet.models.Row()
                    new_row.id = row_id
                    
                    # 1. SHIFT: Move the old 'Current Mileage' into 'Last Week's Odometer'
                    c_old = smartsheet.models.Cell()
                    c_old.column_id = last_week_col_id
                    c_old.value = row_info["old_value"]
                    
                    # 2. UPDATE: Put the fresh Geotab reading into 'Current Mileage'
                    c_new = smartsheet.models.Cell()
                    c_new.column_id = mil_col_id
                    c_new.value = str(int(mileage_dict.get(d['id'], 0)))
                    
                    # 3. Serial Number
                    c_ser = smartsheet.models.Cell()
                    c_ser.column_id = ser_col_id
                    c_ser.value = str(d['serialNumber'])
                    
                    # 4. Sync Date
                    c_date = smartsheet.models.Cell()
                    c_date.column_id = date_col_id
                    c_date.value = today_date
                    
                    new_row.cells.extend([c_old, c_new, c_ser, c_date])
                    updated_rows.append(new_row)
                    seen_ids.add(row_id)

        print(f"Matched {len(updated_rows)} vehicles to update.")

        if updated_rows:
            result = smart.Sheets.update_rows(sheet_id, updated_rows)
            print(f"Smartsheet Response: {result.message}")
        else:
            print("No matches found to update.")
            
    except Exception as e:
        print(f"Robot Sync Failed: {e}")

if __name__ == "__main__":
    get_sync_bot()

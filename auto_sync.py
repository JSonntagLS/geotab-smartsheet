import mygeotab
import smartsheet
import pandas as pd
from datetime import datetime, timedelta
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

        # 1. CALCULATE START OF LAST WEEK (Last Monday at 12:00 AM)
        today = datetime.now()
        monday_start = (today - timedelta(days=today.weekday() + 7)).replace(hour=0, minute=0, second=0, microsecond=0)
        
        print(f"Fetching Historical Reference from: {monday_start.date()}")

        # Fetch Data
        devices = api.get('Device')
        print(f"Found {len(devices)} devices in Geotab.")

        # Smartsheet Setup
        smart = smartsheet.Smartsheet(os.getenv("SMARTSHEET_TOKEN"))
        sheet_id = int(os.getenv("SMARTSHEET_ID"))
        sheet = smart.Sheets.get_sheet(sheet_id)
        
        # Column Mapping
        col_map = {col.title.strip(): col.id for col in sheet.columns}
        primary_col_id = next((col.id for col in sheet.columns if col.primary), None)
        
        mil_col_id = col_map.get("Current Mileage")
        last_week_col_id = col_map.get("Last Week's Odometer")
        ser_col_id = col_map.get("Serial")
        date_col_id = col_map.get("Last Sync Date")

        # Build Lookup for Smartsheet Rows
        ss_rows_lookup = {}
        for r in sheet.rows:
            veh_cell = next((c for c in r.cells if c.column_id == primary_col_id), None)
            if veh_cell:
                name = str(veh_cell.value or "").strip().upper()
                if name:
                    ss_rows_lookup[name] = r.id

        # 2. GET CURRENT LIVE ODOMETER (All devices at once for speed)
        raw_odo = api.get('StatusData', search={'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 'resultsLimit': len(devices)})
        adj_odo = api.get('StatusData', search={'diagnosticSearch': {'id': 'DiagnosticOdometerAdjustmentId'}, 'resultsLimit': len(devices)})

        live_mileage_dict = {}
        for item in (raw_odo + adj_odo):
            dev_id = item['device']['id']
            miles = round(item['data'] / 1609.344, 0)
            if dev_id not in live_mileage_dict or miles > live_mileage_dict[dev_id]:
                live_mileage_dict[dev_id] = miles

        updated_rows = []
        for d in devices:
            name = str(d['name']).strip().upper()
            if name in ss_rows_lookup:
                # 3. GET HISTORICAL ODOMETER (Last Monday)
                start_data = api.get('StatusData', search={
                    'deviceSearch': {'id': d['id']},
                    'diagnosticSearch': {'id': 'DiagnosticOdometerId'},
                    'fromDate': monday_start,
                    'toDate': monday_start + timedelta(hours=1),
                    'resultsLimit': 1
                })

                start_miles = round(start_data['data'] / 1609.344, 0) if start_data else 0
                current_live_miles = live_mileage_dict.get(d['id'], 0)

                new_row = smartsheet.models.Row()
                new_row.id = ss_rows_lookup[name]
                
                # Update cells
                c1 = smartsheet.models.Cell()
                c1.column_id = last_week_col_id
                c1.value = int(start_miles)
                
                c2 = smartsheet.models.Cell()
                c2.column_id = mil_col_id
                c2.value = int(current_live_miles)
                
                c3 = smartsheet.models.Cell()
                c3.column_id = ser_col_id
                c3.value = str(d['serialNumber'])
                
                c4 = smartsheet.models.Cell()
                c4.column_id = date_col_id
                c4.value = today.strftime("%Y-%m-%d %H:%M") # Added time to see exactly when it ran
                
                new_row.cells.extend([c1, c2, c3, c4])
                updated_rows.append(new_row)

        if updated_rows:
            result = smart.Sheets.update_rows(sheet_id, updated_rows)
            print(f"Success! Updated {len(updated_rows)} vehicles.")
        else:
            print("No matches found.")
            
    except Exception as e:
        print(f"Robot Sync Failed: {e}")

if __name__ == "__main__":
    get_sync_bot()

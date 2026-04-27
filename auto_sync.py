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

        # 1. CALCULATE HISTORICAL WINDOW (Last Monday 12am to Last Sunday 11:59pm)
        today = datetime.now()
        # Last Monday at 00:00:00
        monday_start = (today - timedelta(days=today.weekday() + 7)).replace(hour=0, minute=0, second=0, microsecond=0)
        # Last Sunday at 23:59:59
        sunday_end = (today - timedelta(days=today.weekday() + 1)).replace(hour=23, minute=59, second=59, microsecond=0)
        
        print(f"Fetching Mileage from: {monday_start.date()} to {sunday_end.date()}")

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

        updated_rows = []
        for d in devices:
            name = str(d['name']).strip().upper()
            if name in ss_rows_lookup:
                # 2. GET START OF WEEK ODOMETER (Last Monday)
                start_data = api.get('StatusData', search={
                    'deviceSearch': {'id': d['id']},
                    'diagnosticSearch': {'id': 'DiagnosticOdometerId'},
                    'fromDate': monday_start,
                    'toDate': monday_start + timedelta(hours=1),
                    'resultsLimit': 1
                })
                
                # 3. GET END OF WEEK ODOMETER (Last Sunday)
                end_data = api.get('StatusData', search={
                    'deviceSearch': {'id': d['id']},
                    'diagnosticSearch': {'id': 'DiagnosticOdometerId'},
                    'fromDate': sunday_end - timedelta(hours=1),
                    'toDate': sunday_end,
                    'resultsLimit': 1
                })

                # Convert meters to miles
                start_miles = round(start_data['data'] / 1609.344, 0) if start_data else 0
                end_miles = round(end_data['data'] / 1609.344, 0) if end_data else 0

                if end_miles > 0:
                    new_row = smartsheet.models.Row()
                    new_row.id = ss_rows_lookup[name]
                    
                    # Last Week's Odometer (Monday snapshot)
                    c1 = smartsheet.models.Cell()
                    c1.column_id = last_week_col_id
                    c1.value = int(start_miles)
                    
                    # Current Mileage (Sunday night snapshot)
                    c2 = smartsheet.models.Cell()
                    c2.column_id = mil_col_id
                    c2.value = int(end_miles)
                    
                    # Serial and Date
                    c3 = smartsheet.models.Cell()
                    c3.column_id = ser_col_id
                    c3.value = str(d['serialNumber'])
                    
                    c4 = smartsheet.models.Cell()
                    c4.column_id = date_col_id
                    c4.value = today.strftime("%Y-%m-%d")
                    
                    new_row.cells.extend([c1, c2, c3, c4])
                    updated_rows.append(new_row)

        if updated_rows:
            result = smart.Sheets.update_rows(sheet_id, updated_rows)
            print(f"Updated {len(updated_rows)} vehicles. Smartsheet: {result.message}")
        else:
            print("No matches found to update.")
            
    except Exception as e:
        print(f"Robot Sync Failed: {e}")

if __name__ == "__main__":
    get_sync_bot()

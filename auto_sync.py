import mygeotab
import smartsheet
import os
from datetime import datetime, timedelta

def get_sync_bot():
    try:
        print("--- STARTING VIN-ANCHORED SYNC (FLEXIBLE) ---")
        smart = smartsheet.Smartsheet(os.getenv("SMARTSHEET_TOKEN"))
        sheet_id = int(os.getenv("SMARTSHEET_ID"))
        sheet = smart.Sheets.get_sheet(sheet_id)
        
        # This part is now much more aggressive about finding your columns
        col_map = {col.title.strip().upper(): col.id for col in sheet.columns if col.title}
        
        vin_id = col_map.get("VIN")
        name_id = col_map.get("VEHICLE NAME")
        last_week_id = col_map.get("LAST WEEK'S ODOMETER")
        current_id = col_map.get("CURRENT MILEAGE")
        date_id = col_map.get("LAST SYNC DATE")

        if not vin_id:
            # Fallback: Print all available columns if VIN isn't found
            print(f"ERROR: 'VIN' column not detected. Available headers: {list(col_map.keys())}")
            return

        # Build lookup: Mapping VIN -> Row ID
        ss_vin_lookup = {}
        for r in sheet.rows:
            # Finding the VIN cell by ID
            v_cell = next((c for c in r.cells if c.column_id == vin_id), None)
            if v_cell and v_cell.value:
                # We strip and uppercase the VIN to ensure a perfect match
                ss_vin_lookup[str(v_cell.value).strip().upper()] = r.id

        print(f"Found {len(ss_vin_lookup)} VINs in Smartsheet. Connecting to Geotab...")

        api = mygeotab.API(username=os.getenv("GEOTAB_USER"), 
                           password=os.getenv("GEOTAB_PASSWORD"), 
                           database=os.getenv("GEOTAB_DB"))
        api.authenticate()
        
        monday_target = (datetime.now() - timedelta(days=7)).replace(hour=0, minute=0, second=0)
        devices = api.get('Device')
        updated_rows = []

        for d in devices:
            g_vin = str(d.get('vin', '')).strip().upper()
            g_name = str(d.get('name', '')).strip()
            
            if g_vin in ss_vin_lookup:
                try:
                    # Fetch Mileages safely
                    curr_logs = api.get('StatusData', search={'deviceSearch': {'id': d['id']}, 'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 'resultsLimit': 1})
                    prev_logs = api.get('StatusData', search={'deviceSearch': {'id': d['id']}, 'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 'toDate': monday_target, 'resultsLimit': 1})

                    curr_m = int(round(curr_logs['data'] / 1609.344, 0)) if curr_logs else "NO GPS"
                    prev_m = int(round(prev_logs['data'] / 1609.344, 0)) if prev_logs else curr_m

                    # Create the update row
                    new_row = smartsheet.models.Row()
                    new_row.id = ss_vin_lookup[g_vin]
                    
                    # Manual cell creation to avoid API library version conflicts
                    c1 = smartsheet.models.Cell(); c1.column_id = name_id; c1.value = g_name
                    c2 = smartsheet.models.Cell(); c2.column_id = last_week_id; c2.value = prev_m
                    c3 = smartsheet.models.Cell(); c3.column_id = current_id; c3.value = curr_m
                    c4 = smartsheet.models.Cell(); c4.column_id = date_id; c4.value = datetime.now().strftime("%Y-%m-%d")
                    
                    new_row.cells = [c1, c2, c3, c4]
                    updated_rows.append(new_row)
                    print(f"Matched {g_vin[-6:]}: {g_name}")

                except Exception as e:
                    print(f"Skipping {g_vin}: {e}")

        if updated_rows:
            result = smart.Sheets.update_rows(sheet_id, updated_rows)
            print(f"SUCCESS: {result.message}")
        else:
            print("No matching VINs found. Did you save the Smartsheet after adding the VINs?")

    except Exception as e:
        print(f"SYSTEM FAILURE: {str(e)}")

if __name__ == "__main__":
    get_sync_bot()

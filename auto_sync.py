import mygeotab
import smartsheet
import os
from datetime import datetime, timedelta

def get_sync_bot():
    try:
        print("--- VIN-ANCHORED PERMANENT SYNC ---")
        smart = smartsheet.Smartsheet(os.getenv("SMARTSHEET_TOKEN"))
        sheet_id = int(os.getenv("SMARTSHEET_ID"))
        sheet = smart.Sheets.get_sheet(sheet_id)
        
        # 1. Map Columns (Case-Insensitive)
        col_map = {col.title.strip().upper(): col.id for col in sheet.columns if col.title}
        vin_col = col_map.get("VIN")
        name_col = col_map.get("VEHICLE NAME")
        last_week_col = col_map.get("LAST WEEK'S ODOMETER")
        curr_col = col_map.get("CURRENT MILEAGE")
        date_col = col_map.get("LAST SYNC DATE")

        if not vin_col:
            print("ERROR: Could not find 'VIN' column in Smartsheet.")
            return

        # 2. Build a lookup list of all VINs you've typed in Smartsheet
        ss_rows_to_process = []
        for r in sheet.rows:
            v_cell = next((c for c in r.cells if c.column_id == vin_col), None)
            if v_cell and v_cell.value:
                # We store the Row ID and the VIN string from Smartsheet
                ss_rows_to_process.append({
                    "row_id": r.id,
                    "vin_key": str(v_cell.value).strip().upper()
                })

        print(f"Searching Geotab for {len(ss_rows_to_process)} matching VINs...")

        # 3. Connect to Geotab
        api = mygeotab.API(username=os.getenv("GEOTAB_USER"), 
                           password=os.getenv("GEOTAB_PASSWORD"), 
                           database=os.getenv("GEOTAB_DB"))
        api.authenticate()
        
        devices = api.get('Device')
        monday_target = (datetime.now() - timedelta(days=7)).replace(hour=0, minute=0, second=0)
        updated_rows = []

        # 4. The "Fuzzy Match" Loop
        for item in ss_rows_to_process:
            target_vin = item["vin_key"]
            
            # Find the Geotab device where the VIN contains our Smartsheet VIN
            match = next((d for d in devices if d.get('vin') and target_vin in d.get('vin').upper()), None)
            
            if match:
                try:
                    g_name = match.get('name', 'Unnamed Asset')
                    
                    # Fetch Odometer
                    curr_logs = api.get('StatusData', search={'deviceSearch': {'id': match['id']}, 'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 'resultsLimit': 1})
                    prev_logs = api.get('StatusData', search={'deviceSearch': {'id': match['id']}, 'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 'toDate': monday_target, 'resultsLimit': 1})

                    curr_m = int(round(curr_logs['data'] / 1609.344, 0)) if curr_logs else "NO DATA"
                    prev_m = int(round(prev_logs['data'] / 1609.344, 0)) if prev_logs else curr_m

                    # Build the Update
                    new_row = smartsheet.models.Row(id=item["row_id"])
                    new_row.cells = [
                        smartsheet.models.Cell(column_id=name_col, value=g_name), # UPDATES NAME TO MATCH GEOTAB
                        smartsheet.models.Cell(column_id=last_week_col, value=prev_m),
                        smartsheet.models.Cell(column_id=curr_col, value=curr_m),
                        smartsheet.models.Cell(column_id=date_col, value=datetime.now().strftime("%m/%d/%Y"))
                    ]
                    updated_rows.append(new_row)
                    print(f"FOUND MATCH: Smartsheet VIN '{target_vin}' matches Geotab '{g_name}'")

                except Exception as e:
                    print(f"Odometer error for {target_vin}: {e}")
            else:
                print(f"NO MATCH FOUND for Smartsheet VIN: {target_vin}")

        # 5. Push updates to Smartsheet
        if updated_rows:
            smart.Sheets.update_rows(sheet_id, updated_rows)
            print(f"Successfully updated {len(updated_rows)} rows.")
        else:
            print("Zero matches were found in Geotab. Double-check your VIN column!")

    except Exception as e:
        print(f"SYSTEM ERROR: {str(e)}")

if __name__ == "__main__":
    get_sync_bot()

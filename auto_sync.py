import mygeotab
import smartsheet
import os
from datetime import datetime, timedelta

def get_sync_bot():
    try:
        print("--- SERIAL-ANCHORED PERMANENT SYNC ---")
        smart = smartsheet.Smartsheet(os.getenv("SMARTSHEET_TOKEN"))
        sheet_id = int(os.getenv("SMARTSHEET_ID"))
        sheet = smart.Sheets.get_sheet(sheet_id)
        
        # 1. Map Columns
        col_map = {col.title.strip().upper(): col.id for col in sheet.columns if col.title}
        serial_col = col_map.get("SERIAL") # Looking for your existing 'Serial' column
        name_col = col_map.get("VEHICLE NAME")
        last_week_col = col_map.get("LAST WEEK'S ODOMETER")
        curr_col = col_map.get("CURRENT MILEAGE")
        date_col = col_map.get("LAST SYNC DATE")

        if not serial_col:
            print(f"ERROR: Could not find 'Serial' column. Available: {list(col_map.keys())}")
            return

        # 2. Build Serial Lookup
        ss_serials = {}
        for r in sheet.rows:
            s_cell = next((c for c in r.cells if c.column_id == serial_col), None)
            if s_cell and s_cell.value:
                clean_serial = str(s_cell.value).strip().upper()
                ss_serials[clean_serial] = r.id

        print(f"Found {len(ss_serials)} Serials in Smartsheet. Connecting to Geotab...")

        # 3. Connect to Geotab
        api = mygeotab.API(username=os.getenv("GEOTAB_USER"), 
                           password=os.getenv("GEOTAB_PASSWORD"), 
                           database=os.getenv("GEOTAB_DB"))
        api.authenticate()
        
        devices = api.get('Device')
        monday_target = (datetime.now() - timedelta(days=7)).replace(hour=0, minute=0, second=0)
        updated_rows = []

        # 4. Match by Serial Number (Geotab calls this 'serialNumber')
        for d in devices:
            g_serial = str(d.get('serialNumber', '')).strip().upper()
            g_name = str(d.get('name', '')).strip()
            
            if g_serial in ss_serials:
                try:
                    # Fetch Odometer
                    curr_logs = api.get('StatusData', search={'deviceSearch': {'id': d['id']}, 'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 'resultsLimit': 1})
                    prev_logs = api.get('StatusData', search={'deviceSearch': {'id': d['id']}, 'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 'toDate': monday_target, 'resultsLimit': 1})

                    curr_m = int(round(curr_logs['data'] / 1609.344, 0)) if curr_logs else "NO DATA"
                    prev_m = int(round(prev_logs['data'] / 1609.344, 0)) if prev_logs else curr_m

                    # Build Update
                    new_row = smartsheet.models.Row(id=ss_serials[g_serial])
                    new_row.cells = [
                        smartsheet.models.Cell(column_id=name_col, value=g_name), # Force name to match Geotab
                        smartsheet.models.Cell(column_id=last_week_col, value=prev_m),
                        smartsheet.models.Cell(column_id=curr_col, value=curr_m),
                        smartsheet.models.Cell(column_id=date_col, value=datetime.now().strftime("%m/%d/%Y"))
                    ]
                    updated_rows.append(new_row)
                    print(f"SYNCED: Serial {g_serial} -> {g_name}")

                except Exception as e:
                    print(f"Odometer error for {g_serial}: {e}")

        # 5. Push updates
        if updated_rows:
            smart.Sheets.update_rows(sheet_id, updated_rows)
            print(f"Successfully updated {len(updated_rows)} vehicles.")
        else:
            print("No matching Serial Numbers found. Check for typos in your Serial column!")

    except Exception as e:
        print(f"CRITICAL ERROR: {str(e)}")

if __name__ == "__main__":
    get_sync_bot()

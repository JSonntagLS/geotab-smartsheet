import mygeotab
import smartsheet
import os
from datetime import datetime, timedelta

def get_sync_bot():
    try:
        print("--- DEBUGGING CONNECTION ---")
        smart = smartsheet.Smartsheet(os.getenv("SMARTSHEET_TOKEN"))
        sheet_id = int(os.getenv("SMARTSHEET_ID"))
        
        # 1. VERIFY THE SHEET NAME
        sheet = smart.Sheets.get_sheet(sheet_id)
        print(f"ROBOT IS CONNECTED TO: '{sheet.name}'")
        print(f"IF THE NAME ABOVE IS NOT 'Geotab Vehicle Raw Mileage', YOUR ID IS WRONG.")

        # 2. MAP COLUMNS BY EXACT NAME
        col_map = {col.title.strip(): col.id for col in sheet.columns}
        print(f"Found Columns: {list(col_map.keys())}")
        
        name_id = col_map.get("Vehicle Name")
        last_week_id = col_map.get("Last Week's Odometer")
        current_id = col_map.get("Current Mileage")

        # 3. BUILD LOOKUP
        ss_rows_lookup = {}
        for r in sheet.rows:
            name_cell = next((c for c in r.cells if c.column_id == name_id), None)
            if name_cell and name_cell.value:
                ss_rows_lookup[str(name_cell.value).strip().upper()] = r.id

        # 4. GEOTAB
        api = mygeotab.API(username=os.getenv("GEOTAB_USER"), 
                           password=os.getenv("GEOTAB_PASSWORD"), 
                           database=os.getenv("GEOTAB_DB"))
        api.authenticate()
        
        today = datetime.now()
        monday_start = (today - timedelta(days=today.weekday() + 7)).replace(hour=0, minute=0, second=0)
        
        devices = api.get('Device')
        updated_rows = []

        for d in devices:
            g_name = str(d['name']).strip().upper()
            if g_name in ss_rows_lookup:
                # Get current mileage only for this test to see if it changes
                raw = api.get('StatusData', search={'deviceSearch':{'id':d['id']}, 'diagnosticSearch':{'id':'DiagnosticOdometerId'}, 'resultsLimit':1})
                miles = round(raw['data'] / 1609.344, 0) if raw else 999 # Use 999 to show it's working
                
                new_row = smartsheet.models.Row(id=ss_rows_lookup[g_name])
                # We are pushing 0 to Last Week specifically to clear your '1' and '2'
                new_row.cells.append(smartsheet.models.Cell(column_id=last_week_id, value=0))
                new_row.cells.append(smartsheet.models.Cell(column_id=current_id, value=int(miles)))
                updated_rows.append(new_row)

        if updated_rows:
            # Force the update
            result = smart.Sheets.update_rows(sheet_id, updated_rows)
            print(f"PUSH SUCCESSFUL: {result.message}")
        else:
            print("NO VEHICLES MATCHED.")

    except Exception as e:
        print(f"SYNC FAILED: {e}")

if __name__ == "__main__":
    get_sync_bot()

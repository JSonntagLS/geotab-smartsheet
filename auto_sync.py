import mygeotab
import smartsheet
import pandas as pd
from datetime import datetime
import os

# Use environment variables (GitHub Secrets) instead of st.secrets
def get_sync_bot():
    try:
        # Geotab Setup
        api = mygeotab.API(username=os.getenv("GEOTAB_USER"), 
                           password=os.getenv("GEOTAB_PASSWORD"), 
                           database=os.getenv("GEOTAB_DB"))
        api.authenticate()

        # Fetch Data
        devices = api.get('Device')
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
        today_date = datetime.now().strftime("%Y-%m-%d")

        col_map = {col.title.strip(): col.id for col in sheet.columns}
        primary_col_id = next((col.id for col in sheet.columns if col.primary), None)
        mil_col_id = col_map.get("Current Mileage")
        ser_col_id = col_map.get("Serial")
        date_col_id = col_map.get("Last Sync Date")

        # Matching Logic (Your Battle-Hardened Version)
        ss_rows_lookup = {str(next((c.value or c.display_value or "" for c in r.cells if c.column_id == primary_col_id), "")).strip().upper(): r.id for r in sheet.rows}
        
        updated_rows = []
        seen_ids = set()

        for d in devices:
            name = str(d['name']).strip().upper()
            if name in ss_rows_lookup and ss_rows_lookup[name] not in seen_ids:
                row_id = ss_rows_lookup[name]
                new_row = smartsheet.models.Row(id=row_id)
                
                c1 = smartsheet.models.Cell(column_id=mil_col_id, value=str(int(mileage_dict.get(d['id'], 0))))
                c2 = smartsheet.models.Cell(column_id=ser_col_id, value=str(d['serialNumber']))
                c3 = smartsheet.models.Cell(column_id=date_col_id, value=today_date)
                
                new_row.cells.extend([c1, c2, c3])
                updated_rows.append(new_row)
                seen_ids.add(row_id)

        if updated_rows:
            smart.Sheets.update_rows(sheet_id, updated_rows)
            print(f"Successfully synced {len(updated_rows)} vehicles.")
            
    except Exception as e:
        print(f"Robot Sync Failed: {e}")

if __name__ == "__main__":
    get_sync_bot()

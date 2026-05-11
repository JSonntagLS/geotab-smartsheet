import mygeotab
import os
import smartsheet

# --- CONFIGURATION ---
COL_SERIAL = 4402295422095236 
COL_VIN = 6471696134737796    

def sync_geotab_vins():
    try:
        api = mygeotab.API(username=os.getenv("GEOTAB_USER"), 
                           password=os.getenv("GEOTAB_PASSWORD"), 
                           database=os.getenv("GEOTAB_DB"))
        api.authenticate()

        smart = smartsheet.Smartsheet(os.getenv("SMARTSHEET_TOKEN"))
        sheet_id = int(os.getenv("SMARTSHEET_ID"))
        sheet = smart.Sheets.get_sheet(sheet_id)
    except Exception as e:
        print(f"Authentication Error: {e}")
        return

    # 1. MAP SMARTSHEET ROWS
    row_map = {}
    for row in sheet.rows:
        serial_val = ""
        for cell in row.cells:
            if cell.column_id == COL_SERIAL:
                serial_val = str(cell.value).strip() if cell.value is not None else ""
                break
        if serial_val:
            row_map[serial_val] = row.id
    
    print(f"--- DIAGNOSTICS ---")
    print(f"Smartsheet: Found {len(row_map)} serials.")
    print(f"Smartsheet Samples: {list(row_map.keys())[:5]}")

    # 2. GET GEOTAB DATA
    devices = api.get('Device')
    print(f"Geotab: Found {len(devices)} devices.")
    
    # Print sample Geotab serials for comparison
    geotab_samples = [str(d.get('serialNumber', '')).strip() for d in devices[:5]]
    print(f"Geotab Samples: {geotab_samples}")
    
    smartsheet_updates = []

    # 3. MATCHING LOGIC
    for device in devices:
        # Geotab serials can sometimes have hyphens or different casing
        geotab_serial = str(device.get('serialNumber', '')).strip().upper()
        vin = device.get('vin', '')

        # Check for a match by stripping non-alphanumeric characters if necessary
        # But first, try the direct uppercase match
        match_key = next((s for s in row_map.keys() if s.strip().upper() == geotab_serial), None)

        if match_key and vin:
            new_row = smartsheet.models.Row()
            new_row.id = row_map[match_key]
            new_row.cells.append({'column_id': COL_VIN, 'value': vin})
            smartsheet_updates.append(new_row)

    # 4. EXECUTE
    if smartsheet_updates:
        print(f"SUCCESS: Found {len(smartsheet_updates)} matches. Updating...")
        smart.Sheets.update_rows(sheet_id, smartsheet_updates)
    else:
        print("RESULT: Still no matches. Compare the 'Samples' printed above to see the difference.")

if __name__ == "__main__":
    sync_geotab_vins()

import mygeotab
import os
import smartsheet

# --- CONFIGURATION ---
COL_SERIAL = 6471696134737796
COL_VIN = 4402295422095236

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

    # 1. DEBUG: Show what we are finding in Smartsheet
    row_map = {}
    print(f"--- Checking Smartsheet (Sheet ID: {sheet_id}) ---")
    for row in sheet.rows:
        serial_val = ""
        for cell in row.cells:
            if cell.column_id == COL_SERIAL:
                # Convert to string, strip whitespace, and handle None
                serial_val = str(cell.value).strip() if cell.value is not None else ""
                break
        if serial_val:
            row_map[serial_val] = row.id
    
    print(f"Found {len(row_map)} rows with Serial Numbers in Smartsheet.")
    if len(row_map) > 0:
        print(f"Sample Serial from Smartsheet: '{list(row_map.keys())[0]}'")

    # 2. DEBUG: Show what we are finding in Geotab
    print("\n--- Checking Geotab ---")
    devices = api.get('Device')
    print(f"Retrieved {len(devices)} devices from Geotab.")
    
    smartsheet_updates = []
    match_count = 0

    for device in devices:
        # Geotab serials are often uppercase; we strip just in case
        serial = str(device.get('serialNumber', '')).strip()
        vin = device.get('vin', '')

        # Check for match (Case-Insensitive)
        if serial.upper() in [s.upper() for s in row_map.keys()]:
            # Find the original key to get the correct row ID
            original_key = next(s for s in row_map.keys() if s.upper() == serial.upper())
            
            if vin:
                match_count += 1
                new_row = smartsheet.models.Row()
                new_row.id = row_map[original_key]
                
                new_cell = smartsheet.models.Cell()
                new_cell.column_id = COL_VIN
                new_cell.value = vin
                new_row.cells.append(new_cell)
                smartsheet_updates.append(new_row)

    print(f"Matches found: {match_count}")

    # 3. EXECUTE
    if smartsheet_updates:
        print(f"Updating {len(smartsheet_updates)} rows...")
        smart.Sheets.update_rows(sheet_id, smartsheet_updates)
        print("SUCCESS: VIN numbers updated.")
    else:
        print("Final Status: No updates performed. Check if Serials match exactly.")

if __name__ == "__main__":
    sync_geotab_vins()

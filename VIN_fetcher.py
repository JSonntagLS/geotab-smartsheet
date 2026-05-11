import mygeotab
import os
import smartsheet

# --- UPDATED CONFIGURATION BASED ON YOUR LIST ---
COL_SERIAL = 4402295422095236  # Confirmed: Name: Serial
COL_VIN = 6471696134737796     # Confirmed: Name: VIN

def sync_geotab_vins():
    try:
        # 1. AUTHENTICATION
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

    # 2. MAP SMARTSHEET ROWS
    row_map = {}
    for row in sheet.rows:
        serial_val = ""
        for cell in row.cells:
            if cell.column_id == COL_SERIAL:
                serial_val = str(cell.value).strip() if cell.value is not None else ""
                break
        if serial_val:
            row_map[serial_val] = row.id
    
    print(f"Mapped {len(row_map)} rows from Smartsheet using Serial column.")

    # 3. GET GEOTAB DATA
    print("Fetching device data from Geotab...")
    devices = api.get('Device')
    
    smartsheet_updates = []

    # 4. MATCH AND PREP UPDATES
    for device in devices:
        serial = str(device.get('serialNumber', '')).strip()
        vin = device.get('vin', '')

        # Use case-insensitive matching for the serial number
        match_key = next((s for s in row_map.keys() if s.upper() == serial.upper()), None)

        if match_key and vin:
            new_row = smartsheet.models.Row()
            new_row.id = row_map[match_key]
            
            new_cell = smartsheet.models.Cell()
            new_cell.column_id = COL_VIN
            new_cell.value = vin
            new_row.cells.append(new_cell)
            smartsheet_updates.append(new_row)

    # 5. EXECUTE UPDATES
    if smartsheet_updates:
        print(f"Found {len(smartsheet_updates)} VIN matches. Updating Smartsheet...")
        try:
            smart.Sheets.update_rows(sheet_id, smartsheet_updates)
            print("SUCCESS: Smartsheet has been updated with VIN numbers.")
        except Exception as e:
            print(f"Error during Smartsheet update: {e}")
    else:
        print("No matches found. Ensure Serial numbers in Smartsheet match Geotab precisely.")

if __name__ == "__main__":
    sync_geotab_vins()

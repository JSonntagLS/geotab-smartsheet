import mygeotab
import os
import smartsheet

# --- CONFIGURATION ---
# Using the IDs provided in your request
COL_SERIAL = 6471696134737796
COL_VIN = 4402295422095236

def sync_geotab_vins():
    # 1. AUTHENTICATION (Using your existing environment variable structure)
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

    # 2. MAP SMARTSHEET ROWS
    # Creates a mapping of { 'SerialNumber': row_id }
    row_map = {}
    for row in sheet.rows:
        serial_val = ""
        for cell in row.cells:
            if cell.column_id == COL_SERIAL:
                serial_val = str(cell.value).strip() if cell.value else ""
                break
        if serial_val:
            row_map[serial_val] = row.id

    # 3. GET GEOTAB DEVICES
    print("Fetching device data from Geotab...")
    devices = api.get('Device')
    
    smartsheet_updates = []

    # 4. MATCH AND PREP UPDATES
    for device in devices:
        serial = str(device.get('serialNumber', '')).strip()
        vin = device.get('vin', '')

        # Only proceed if we have a match in Smartsheet and a VIN to provide
        if serial in row_map and vin:
            new_row = smartsheet.models.Row()
            new_row.id = row_map[serial]
            
            # Create the VIN cell
            new_cell = smartsheet.models.Cell()
            new_cell.column_id = COL_VIN
            new_cell.value = vin
            new_cell.strict = False
            
            new_row.cells.append(new_cell)
            smartsheet_updates.append(new_row)

    # 5. EXECUTE SMARTSHEET UPDATE
    if smartsheet_updates:
        print(f"Found {len(smartsheet_updates)} VIN matches. Updating Smartsheet...")
        try:
            # Updating in bulk for efficiency
            smart.Sheets.update_rows(sheet_id, smartsheet_updates)
            print("SUCCESS: VIN numbers have been synchronized.")
        except Exception as e:
            print(f"Error updating Smartsheet: {e}")
    else:
        print("No matching Serial Numbers found or no new VIN data available.")

if __name__ == "__main__":
    sync_geotab_vins()

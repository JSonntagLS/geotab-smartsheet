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
                # Ensure we are capturing the value as a clean string
                serial_val = str(cell.value).strip().upper() if cell.value else ""
                break
        if serial_val:
            row_map[serial_val] = row.id
    
    print(f"Mapped {len(row_map)} serials from Smartsheet.")

    # 2. GET GEOTAB DATA
    devices = api.get('Device')
    print(f"Retrieved {len(devices)} devices from Geotab.")
    
    smartsheet_updates = []

    # 3. MATCHING LOGIC
    for device in devices:
        geotab_serial = str(device.get('serialNumber', '')).strip().upper()
        vin = device.get('vin', '')

        # Check if this Geotab serial exists in our Smartsheet map
        if geotab_serial in row_map and vin:
            # Create a proper Smartsheet Row object
            new_row = smartsheet.models.Row()
            new_row.id = row_map[geotab_serial]
            
            # Create a proper Smartsheet Cell object
            new_cell = smartsheet.models.Cell()
            new_cell.column_id = COL_VIN
            new_cell.value = vin
            new_cell.strict = False  # Allows standard string entry
            
            new_row.cells.append(new_cell)
            smartsheet_updates.append(new_row)

    # 4. EXECUTE
    if smartsheet_updates:
        print(f"Found {len(smartsheet_updates)} matches. Sending updates to Smartsheet...")
        try:
            # Update in chunks of 500 (Smartsheet limit, though you only have ~72)
            smart.Sheets.update_rows(sheet_id, smartsheet_updates)
            print("SUCCESS: Smartsheet updated with VIN numbers.")
        except Exception as e:
            print(f"Smartsheet API Error: {e}")
    else:
        print("RESULT: No matching Serial/VIN pairs found. Check if the VINs are populated in Geotab.")

if __name__ == "__main__":
    sync_geotab_vins()

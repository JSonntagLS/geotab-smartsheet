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
                serial_val = str(cell.value).strip().upper() if cell.value else ""
                break
        if serial_val:
            row_map[serial_val] = row.id
    
    print(f"Mapped {len(row_map)} serials from Smartsheet.")

    # 2. GET GEOTAB DATA
    devices = api.get('Device')
    print(f"Retrieved {len(devices)} devices from Geotab.")
    
    smartsheet_updates = []
    potential_matches = 0

    # 3. MATCHING & DATA VERIFICATION
    for device in devices:
        geotab_serial = str(device.get('serialNumber', '')).strip().upper()
        vin = device.get('vin', '').strip() if device.get('vin') else ""

        if geotab_serial in row_map:
            potential_matches += 1
            # If we have a match but no VIN, print it so we know why it's skipping
            if not vin:
                if potential_matches <= 5:
                    print(f"Match found for {geotab_serial}, but Geotab VIN field is EMPTY.")
                continue

            # If we have both, prepare the update
            new_row = smartsheet.models.Row()
            new_row.id = row_map[geotab_serial]
            
            new_cell = smartsheet.models.Cell()
            new_cell.column_id = COL_VIN
            new_cell.value = vin
            new_cell.strict = False
            
            new_row.cells.append(new_cell)
            smartsheet_updates.append(new_row)

    print(f"Total potential Serial matches: {potential_matches}")
    print(f"Total matches with actual VIN data: {len(smartsheet_updates)}")

    # 4. EXECUTE
    if smartsheet_updates:
        print(f"Sending {len(smartsheet_updates)} updates to Smartsheet...")
        try:
            smart.Sheets.update_rows(sheet_id, smartsheet_updates)
            print("SUCCESS: Smartsheet updated.")
        except Exception as e:
            print(f"Smartsheet API Error: {e}")
    else:
        print("RESULT: No data to update. Either no serials matched, or matched serials have no VIN in Geotab.")

if __name__ == "__main__":
    sync_geotab_vins()

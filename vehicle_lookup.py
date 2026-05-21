import mygeotab
import os
import smartsheet

# --- CONFIGURATION ---
COL_SERIAL = 4402295422095236 
COL_MAKE = 849062013472644
COL_MODEL = 5352661640843140
COL_YEAR = 3100861827157892

def autofill_vehicle_details():
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

    # 1. MAP SMARTSHEET ROWS (Using your exact pattern)
    row_map = {}
    for row in sheet.rows:
        serial_val = ""
        for cell in row.cells:
            if cell.column_id == COL_SERIAL:
                serial_val = str(cell.value).strip().upper() if cell.value else ""
                break
        if serial_val:
            row_map[serial_val] = row
    
    print(f"Mapped {len(row_map)} serials from Smartsheet.")

    # 2. GET GEOTAB DATA
    devices = api.get('Device')
    print(f"Retrieved {len(devices)} devices from Geotab.")
    
    smartsheet_updates = []

    # 3. MATCHING & DATA EXTRACTION
    for device in devices:
        geotab_serial = str(device.get('serialNumber', '')).strip().upper()
        
        if geotab_serial in row_map:
            sheet_row = row_map[geotab_serial]
            
            # Extract current cell values to avoid overwriting existing data
            current_make = next((c.value for c in sheet_row.cells if c.column_id == COL_MAKE), None)
            current_model = next((c.value for c in sheet_row.cells if c.column_id == COL_MODEL), None)
            current_year = next((c.value for c in sheet_row.cells if c.column_id == COL_YEAR), None)

            # Geotab stores engine-decoded data here
            vdi = device.get('vehicleDeviceIdentification', {})
            
            geotab_make = vdi.get('make') if vdi else None
            geotab_model = vdi.get('model') if vdi else None
            geotab_year = vdi.get('year') if vdi else None

            cells_to_update = []

            if geotab_make and not current_make:
                new_cell = smartsheet.models.Cell()
                new_cell.column_id = COL_MAKE
                new_cell.value = str(geotab_make).strip()
                new_cell.strict = False
                cells_to_update.append(new_cell)

            if geotab_model and not current_model:
                new_cell = smartsheet.models.Cell()
                new_cell.column_id = COL_MODEL
                new_cell.value = str(geotab_model).strip()
                new_cell.strict = False
                cells_to_update.append(new_cell)

            if geotab_year and not current_year:
                new_cell = smartsheet.models.Cell()
                new_cell.column_id = COL_YEAR
                new_cell.value = int(geotab_year)
                new_cell.strict = False
                cells_to_update.append(new_cell)

            if cells_to_update:
                print(f"Pending Update -> Serial: {geotab_serial} | Make: {geotab_make} | Model: {geotab_model} | Year: {geotab_year}")
                new_row = smartsheet.models.Row()
                new_row.id = sheet_row.id
                new_row.cells.extend(cells_to_update)
                smartsheet_updates.append(new_row)

    # 4. EXECUTE BULK UPDATE
    if smartsheet_updates:
        print(f"SUCCESS: Found {len(smartsheet_updates)} rows needing info updates. Updating Smartsheet...")
        try:
            smart.Sheets.update_rows(sheet_id, smartsheet_updates)
            print("Smartsheet has been successfully updated.")
        except Exception as e:
            print(f"Smartsheet API Error: {e}")
    else:
        print("RESULT: No missing fields required updates or fields were not provided by Geotab engine nodes.")

if __name__ == "__main__":
    autofill_vehicle_details()

import mygeotab
import os
import smartsheet

# --- CONFIGURATION (COLUMN IDs) ---
COL_SERIAL = 4402295422095236
COL_MAKE = 849062013472644
COL_MODEL = 5352661640843140
COL_YEAR = 3100861827157892

def autofill_vehicle_details():
    # 1. GEOTAB API SETUP
    api = mygeotab.API(username=os.getenv("GEOTAB_USER"), 
                       password=os.getenv("GEOTAB_PASSWORD"), 
                       database=os.getenv("GEOTAB_DB"))
    api.authenticate()

    # 2. SMARTSHEET SETUP
    smart = smartsheet.Smartsheet(os.getenv("SMARTSHEET_TOKEN"))
    sheet_id = int(os.getenv("SMARTSHEET_ID"))
    sheet = smart.Sheets.get_sheet(sheet_id)
    
    # Map out the Smartsheet rows using Serial Number as the key
    row_map = {}
    for r in sheet.rows:
        serial_val = next((c.value for c in r.cells if c.column_id == COL_SERIAL), None)
        if serial_val:
            row_map[str(serial_val).strip()] = r

    # 3. PULL GEOTAB DEVICES
    print("Fetching device list from Geotab...")
    devices = api.get('Device')
    smartsheet_updates = []

    print("Analyzing vehicle data alignments...")
    for device in devices:
        serial = str(device.get('serialNumber', '')).strip()
        
        # Match against our Smartsheet tracking row
        if serial in row_map:
            sheet_row = row_map[serial]
            
            # Extract attributes safely from Geotab metadata properties
            geotab_make = device.get('make')
            geotab_model = device.get('model')
            geotab_year = device.get('year')

            # We will only append an update cell if data is missing or empty on the row
            cells_to_update = []
            
            # Read existing cell states to prevent overwriting correct manual values
            current_make = next((c.value for c in sheet_row.cells if c.column_id == COL_MAKE), None)
            current_model = next((c.value for c in sheet_row.cells if c.column_id == COL_MODEL), None)
            current_year = next((c.value for c in sheet_row.cells if c.column_id == COL_YEAR), None)

            if geotab_make and not current_make:
                cells_to_update.append({'column_id': COL_MAKE, 'value': str(geotab_make).strip()})
            if geotab_model and not current_model:
                cells_to_update.append({'column_id': COL_MODEL, 'value': str(geotab_model).strip()})
            if geotab_year and not current_year:
                cells_to_update.append({'column_id': COL_YEAR, 'value': int(geotab_year)})

            # If there are changes to make, construct the updated row object
            if cells_to_update:
                new_row = smartsheet.models.Row()
                new_row.id = sheet_row.id
                for cell in cells_to_update:
                    new_row.cells.append(cell)
                smartsheet_updates.append(new_row)

    # 4. PUSH BULK UPDATES TO SMARTSHEET
    if smartsheet_updates:
        print(f"Pushing updates for {len(smartsheet_updates)} vehicles to Smartsheet...")
        smart.Sheets.update_rows(sheet_id, smartsheet_updates)
        print("SUCCESS: Make, Model, and Year fields updated where available.")
    else:
        print("Done. No missing fields required updating at this time.")

if __name__ == "__main__":
    autofill_vehicle_details()

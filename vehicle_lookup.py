import mygeotab
import os
import requests
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

    # 3. MATCHING & NHTSA PUBLIC API DECODING
    for device in devices:
        geotab_serial = str(device.get('serialNumber', '')).strip().upper()
        
        if geotab_serial in row_map:
            sheet_row = row_map[geotab_serial]
            
            # Read existing values to prevent blanking or overwriting active data
            current_make = next((c.value for c in sheet_row.cells if c.column_id == COL_MAKE), None)
            current_model = next((c.value for c in sheet_row.cells if c.column_id == COL_MODEL), None)
            current_year = next((c.value for c in sheet_row.cells if c.column_id == COL_YEAR), None)

            # Only look up the VIN if any tracking fields are completely missing
            if not current_make or not current_model or not current_year:
                vin = device.get('vin', '')
                if not vin or vin == "":
                    vin = device.get('engineVehicleIdentificationNumber', '')
                vin = str(vin).strip().upper() if vin else ""

                if len(vin) >= 11:
                    print(f"Pinging NHTSA API database for VIN: {vin}")
                    try:
                        nhtsa_url = f"https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/{vin}?format=json"
                        response = requests.get(nhtsa_url, timeout=10)
                        
                        if response.status_code == 200:
                            data = response.json()
                            results = data.get("Results", [])
                            
                            if results:
                                v_info = results[0]
                                
                                nhtsa_make = v_info.get("Make")
                                nhtsa_model = v_info.get("Model")
                                nhtsa_year = v_info.get("ModelYear")

                                cells_to_update = []

                                if nhtsa_make and not current_make:
                                    new_cell = smartsheet.models.Cell()
                                    new_cell.column_id = COL_MAKE
                                    new_cell.value = str(nhtsa_make).strip()
                                    new_cell.strict = False
                                    cells_to_update.append(new_cell)

                                if nhtsa_model and not current_model:
                                    new_cell = smartsheet.models.Cell()
                                    new_cell.column_id = COL_MODEL
                                    new_cell.value = str(nhtsa_model).strip()
                                    new_cell.strict = False
                                    cells_to_update.append(new_cell)

                                if nhtsa_year and not current_year:
                                    new_cell = smartsheet.models.Cell()
                                    new_cell.column_id = COL_YEAR
                                    new_cell.value = int(nhtsa_year)
                                    new_cell.strict = False
                                    cells_to_update.append(new_cell)

                                if cells_to_update:
                                    print(f"   -> Match Found: {nhtsa_year} {nhtsa_make} {nhtsa_model}")
                                    new_row = smartsheet.models.Row()
                                    new_row.id = sheet_row.id
                                    new_row.cells.extend(cells_to_update)
                                    smartsheet_updates.append(new_row)
                        else:
                            print(f"   -> NHTSA Server responded with error status: {response.status_code}")
                            
                    except Exception as http_err:
                        print(f"   -> Connection issue with NHTSA endpoints for VIN {vin}: {http_err}")

    # 4. EXECUTE SMARTSHEET SYNC
    if smartsheet_updates:
        print(f"SUCCESS: Decoded {len(smartsheet_updates)} assets. Bulk sending to Smartsheet...")
        try:
            smart.Sheets.update_rows(sheet_id, smartsheet_updates)
            print("Smartsheet cell values successfully saved.")
        except Exception as e:
            print(f"Smartsheet API Error: {e}")
    else:
        print("RESULT: No matching rows required updates or missing valid VIN strings to query.")

if __name__ == "__main__":
    autofill_vehicle_details()

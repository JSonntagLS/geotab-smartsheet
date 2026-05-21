import os
import requests
import smartsheet

# --- CONFIGURATION ---
COL_VIN = 6471696134737796
COL_MAKE = 849062013472644
COL_MODEL = 5352661640843140
COL_YEAR = 3100861827157892

def autofill_vehicle_details():
    try:
        smart = smartsheet.Smartsheet(os.getenv("SMARTSHEET_TOKEN"))
        sheet_id = int(os.getenv("SMARTSHEET_ID"))
        sheet = smart.Sheets.get_sheet(sheet_id)
    except Exception as e:
        print(f"Authentication Error: {e}")
        return

    print(f"Successfully loaded sheet. Processing {len(sheet.rows)} rows...")
    smartsheet_updates = []

    # Loop directly through Smartsheet rows using your column IDs
    for row in sheet.rows:
        vin_val = None
        current_make = None
        current_model = None
        current_year = None

        # Extract the relevant cell values for this row
        for cell in row.cells:
            if cell.column_id == COL_VIN:
                vin_val = str(cell.value).strip().upper() if cell.value else ""
            elif cell.column_id == COL_MAKE:
                current_make = cell.value
            elif cell.column_id == COL_MODEL:
                current_model = cell.value
            elif cell.column_id == COL_YEAR:
                current_year = cell.value

        # Only process if we actually have a VIN string and missing vehicle metadata fields
        if vin_val and (not current_make or not current_model or not current_year):
            # Clean up VIN (remove spaces, hyphens just in case)
            clean_vin = "".join(vin_val.split())
            
            # NHTSA requires at least the first 11 characters of a VIN to decode accurately
            if len(clean_vin) >= 11:
                print(f"Pinging NHTSA API database for VIN: {clean_vin}")
                try:
                    nhtsa_url = f"https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/{clean_vin}?format=json"
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
                                new_row.id = row.id
                                new_row.cells.extend(cells_to_update)
                                smartsheet_updates.append(new_row)
                    else:
                        print(f"   -> NHTSA Server responded with error status: {response.status_code}")
                        
                except Exception as http_err:
                    print(f"   -> Connection issue with NHTSA endpoints for VIN {clean_vin}: {http_err}")

    # 3. BULK UPDATE SMARTSHEET
    if smartsheet_updates:
        print(f"SUCCESS: Decoded data for {len(smartsheet_updates)} rows. Bulk sending to Smartsheet...")
        try:
            smart.Sheets.update_rows(sheet_id, smartsheet_updates)
            print("Smartsheet cell values successfully saved.")
        except Exception as e:
            print(f"Smartsheet API Error: {e}")
    else:
        print("RESULT: No rows updated. Either all rows already had data, or no valid VINs were found.")

if __name__ == "__main__":
    autofill_vehicle_details()

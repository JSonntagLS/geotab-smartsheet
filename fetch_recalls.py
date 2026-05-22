import os
import csv
import re
import requests
import urllib.parse
import smartsheet

# --- SMARTSHEET COLUMN CONFIGURATION ---
COL_VEHICLE = 6654095235780484
COL_VIN = 6471696134737796
COL_MAKE = 849062013472644
COL_MODEL = 5352661640843140
COL_YEAR = 3100861827157892

CSV_FILE_PATH = "fixed_recalls.csv"
FIELDNAMES = ["Vehicle Name", "VIN", "CampaignID", "ManufacturerCampaign", "Make", "Model", "Year"]

def fetch_active_recalls(make, model, year):
    """Queries the correct NHTSA database for active safety recalls with URL encoding."""
    if not (make and model and year):
        return []
        
# Standardize parameters and safely handle spaces or slashes in commercial vehicle descriptors
    clean_make = " ".join(str(make).strip().split()).upper()
    clean_model = " ".join(str(model).strip().split()).upper()
    clean_year = " ".join(str(year).strip().split()).upper()

    # Global translation maps to clean up corporate suffixes from sheet cells
    make_normalization = {
        "CHEVROLET CARS": "CHEVROLET",
        "CHEVY": "CHEVROLET",
        "HYUNDAI MOTOR": "HYUNDAI",
        "HYUNDAI MOTOR AMERICA": "HYUNDAI",
        "BLUE BIRD BODY COMPANY": "BLUE BIRD",
        "BLUEBIRD": "BLUE BIRD",
        "CHRYSLER LLC": "CHRYSLER"
    }
    
    if clean_make in make_normalization:
        clean_make = make_normalization[clean_make]
    else:
        for partial_key, replacement in make_normalization.items():
            if partial_key in clean_make:
                clean_make = replacement
                break

    model_normalization = {
        # Typos, Alternate Spellings, and Variations
        "ROUGE": "ROGUE",
        "CHYSLER VOYAGER": "VOYAGER",
        "CHYRSLER VOYAGER": "VOYAGER",
        "PACIFICA HYBRID": "VOYAGER",
        "PACIFICA": "VOYAGER",
        "SAVANNA": "EXPRESS",
        "CHEVY EXPRESS": "EXPRESS",
        "CHEVROLET EXPRESS 3500": "EXPRESS",
        "EXPRESS 3500 CUTAWAY": "EXPRESS",
        "EXPRESS 3500": "EXPRESS",
        
        # Ford Commercial & Passenger Splits
        "TRANSIT E-350": "TRANSIT",
        "E350": "E-350",
        "E-350 SUPER DUTY": "E-350",
        "TRANSIT CARGO VAN": "TRANSIT",
        "TRANSIT CONNECT": "TRANSIT CONNECT",
        "TRAILBLAZER SUV": "TRAILBLAZER",
        "TRAIL BLAZER": "TRAILBLAZER",
        "EQUINOX EV": "EQUINOX",
        
        # Heavy Fleet Commercial Mappings
        "PC205": "CE",
        "CE COMMERCIAL": "CE",
        "INTEGRATED CE COMMERCIAL": "CE",
        "3000": "3000 RE",
        "INTERNATIONAL 3000": "3000 RE",
        "COMMERCIAL SERIES BUS": "COMMERCIAL",
        "SHELL COMMERCIAL SERIES": "COMMERCIAL",
        "COMMERCIAL SERIES": "COMMERCIAL",
        "MC FRONT ENGINE MOTOR HOME CHASSIS": "MC FRONT ENGINE MOTOR HOME CHASSIS"
    }

    if clean_model in model_normalization:
        clean_model = model_normalization[clean_model]
    elif "EXPRESS" in clean_model or "SAVANNA" in clean_model:
        clean_model = "EXPRESS"
    elif "TRANSIT" in clean_model and "CONNECT" not in clean_model:
        clean_model = "TRANSIT"
    elif "PC205" in clean_model or "CE" in clean_model:
        clean_model = "CE"
    elif "COMMERCIAL" in clean_model:
        clean_model = "COMMERCIAL"
        
    encoded_make = urllib.parse.quote(clean_make)
    encoded_model = urllib.parse.quote(clean_model)
    encoded_year = urllib.parse.quote(clean_year)
    
    url = f"https://api.nhtsa.gov/recalls/recallsByVehicle?make={encoded_make}&model={encoded_model}&modelYear={encoded_year}"
    print(f"Pinging NHTSA API for: {clean_year} {clean_make} {clean_model}...")
    
    try:
        response = requests.get(url, timeout=15)
        if response.status_code == 200:
            data = response.json()
            return data.get("results", [])
        elif response.status_code == 400:
            print(f"    -> Info: Model designation '{clean_model}' requires database normalization. Skipping.")
            return []
        else:
            print(f"    -> NHTSA API error status: {response.status_code}")
    except Exception as e:
        print(f"    -> Connection issue with NHTSA endpoint: {e}")
        
    return []

def load_existing_recalls():
    """Reads fixed_recalls.csv to track historical entries and avoid duplicates."""
    existing_records = set()
    if not os.path.exists(CSV_FILE_PATH):
        return existing_records
        
    try:
        with open(CSV_FILE_PATH, mode='r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                vin = row.get("VIN")
                campaign_id = row.get("CampaignID")
                if vin and campaign_id:
                    existing_records.add((vin.strip().upper(), campaign_id.strip()))
    except Exception as e:
        print(f"Error parsing existing CSV file: {e}")
        
    return existing_records

def extract_manufacturer_code(notes_text, vehicle_make=""):
    """Robust pattern matching to isolate shorthand manufacturer campaign codes from NHTSA text blocks."""
    if not notes_text:
        return ""
        
    text_to_search = str(notes_text)
    make_blacklist = {
        str(vehicle_make).strip().upper(), 
        "NISSAN", "CHRYSLER", "FORD", "CHEVROLET", "CHEVY", "HYUNDAI", 
        "FMVSS", "CNG", "LPG", "LNG", "EV", "HEV", "PHEV",
        "VINS", "BEGAN", "DEALERS", "RECALL", "CAMPAIGN", "NUMBER"
    }

    # Inline helper to validate that a code isn't just a manufacturer name or purely text when it shouldn't be
    def is_valid_code(code_str):
        c = code_str.strip().upper()
        if c in make_blacklist or len(c) <= 2:
            return False
        # If it contains only alphabetical characters, make sure it isn't a plain generic English word
        if c.isalpha() and c in ["BEFORE", "AFTER", "OWNER", "UNITS", "THESE", "WHICH", "ABOUT"]:
            return False
        return True

    # Pattern 1: Specific pattern for lists or multi-code phrasing like "numbers for this recall are 06D, 10D..."
    list_match = re.search(r'(?:numbers\s+for\s+this\s+recall\s+are)\s+([A-Z0-9]{2,6})\b', text_to_search, re.IGNORECASE)
    if list_match and is_valid_code(list_match.group(1)):
        return list_match.group(1).strip().upper()

    # Pattern 2: Capture explicit parentheses blocks like (Recall Campaign 246) or (06D)
    paren_match = re.search(r'\((?:Recall\s+)?(?:Campaign|Number)?\s*([A-Z0-9]{3,6})\)', text_to_search, re.IGNORECASE)
    if paren_match and is_valid_code(paren_match.group(1)):
        return paren_match.group(1).strip().upper()
        
    # Pattern 3: Standard manufacturer text callouts targeting specific phrasing variations
    text_match = re.search(r'(?:recall\s+number\s+is|recall\s+is|campaign\s+number\s+is|campaign\s+is|internal\s+number\s+for\s+this\s+recall\s+is)\s+([A-Z0-9]{2,6})(?:\.|\s|$)', text_to_search, re.IGNORECASE)
    if text_match and is_valid_code(text_match.group(1)):
        return text_match.group(1).strip().upper()
    
    # Fallback Pattern 3: Catch casual mentions of numeric/alphanumeric codes near the word recall or campaign
    fallback_match = re.search(r'(?:recall|campaign)\s+(?:code|number)?\s*([A-Z0-9]{2,6})\b', text_to_search, re.IGNORECASE)
    if fallback_match and is_valid_code(fallback_match.group(1)):
        return fallback_match.group(1).strip().upper()

    return ""

def process_recall_sync():
    try:
        smart = smartsheet.Smartsheet(os.getenv("SMARTSHEET_TOKEN"))
        sheet_id = int(os.getenv("SMARTSHEET_ID"))
        sheet = smart.Sheets.get_sheet(sheet_id)
    except Exception as e:
        print(f"Smartsheet Authentication Error: {e}")
        return

    print(f"Loaded sheet. Scanning data records across {len(sheet.rows)} entries...")

    vehicles_to_check = []
    for row in sheet.rows:
        vehicle_val = ""
        vin_val = ""
        make_val = ""
        model_val = ""
        year_val = ""

        for cell in row.cells:
            if cell.column_id == COL_VEHICLE:
                vehicle_val = str(cell.value).strip() if cell.value else ""
            elif cell.column_id == COL_VIN:
                vin_val = str(cell.value).strip().upper() if cell.value else ""
            elif cell.column_id == COL_MAKE:
                make_val = str(cell.value).strip() if cell.value else ""
            elif cell.column_id == COL_MODEL:
                model_val = str(cell.value).strip() if cell.value else ""
            elif cell.column_id == COL_YEAR:
                if cell.value:
                    if isinstance(cell.value, list):
                        raw_item = cell.value if len(cell.value) > 0 else ""
                    else:
                        raw_item = cell.value
                    
                    try:
                        year_val = str(int(float(raw_item))).strip()
                    except (ValueError, TypeError):
                        year_val = str(raw_item).strip()

        if vin_val and make_val and model_val and year_val:
            vehicles_to_check.append({
                "vehicle_name": vehicle_val,
                "vin": "".join(vin_val.split()),
                "make": " ".join(str(make_val).strip().split()).upper(),
                "model": " ".join(str(model_val).strip().split()).upper(),
                "year": " ".join(str(year_val).strip().split()).upper()
            })

    if not vehicles_to_check:
        print("No complete vehicle profiles (VIN, Make, Model, Year) discovered.")
        return

    existing_entries = load_existing_recalls()
    new_rows_to_append = []
    
    debug_counter = 0
    debug_targets = set()
    current_sig = ""
    seen_debug_profiles = set()
    
    for vehicle in vehicles_to_check:
        v_make = str(vehicle["make"]).strip().upper()
        v_model = str(vehicle["model"]).strip().upper()
        v_year = str(vehicle["year"]).strip().upper()
        
        if "SHELL COMMERCIAL SERIES" in v_model or "COMMERCIAL SERIES" in v_model or v_model == "COMMERCIAL":
            v_model = "COMMERCIAL"
        elif "EXPRESS" in v_model or "SAVANNA" in v_model:
            v_model = "EXPRESS"
        elif "PC205" in v_model:
            v_model = "CE"
        elif v_model == "PACIFICA":
            v_model = "VOYAGER"
            
        raw_campaigns = fetch_active_recalls(vehicle["make"], vehicle["model"], vehicle["year"])

        # TARGETED BATCH DEBUGGER: Evaluate the new collection against the updated FMVSS filter
        if raw_campaigns:
            profile_tuple = (v_year, v_make, v_model)
            if profile_tuple not in seen_debug_profiles:
                seen_debug_profiles.add(profile_tuple)
                
                print(f"\n=== DEBUGGER UNIQUE VEHICLE #{debug_counter + 1}: {v_year} {v_make} {v_model} ===")
                first_campaign = raw_campaigns[0]
                sample_text = (first_campaign.get("Notes", "") or "") + " " + (first_campaign.get("Remedy", "") or "")
                extracted = extract_manufacturer_code(sample_text, vehicle["make"])
                print(f"DEBUGGER TEST -> Extracted Code from Payload String: '{extracted}'")
                print("========================================================================\n")
                
                debug_counter += 1

        
        for campaign in raw_campaigns:
            campaign_id = str(campaign.get("NHTSACampaignNumber", "")).strip()
            if not campaign_id:
                continue
                
            # Extract using the API properties if they happen to exist
            raw_mfr_code = campaign.get("mfrCampaignNumber")
            if raw_mfr_code is None:
                raw_mfr_code = campaign.get("MfrCampaignNumber")
                
            final_campaign_display = str(raw_mfr_code).strip() if raw_mfr_code is not None else ""
            
            # If the property is missing, blank, or duplicates the NHTSA ID:
            if (not final_campaign_display or 
                final_campaign_display.upper() == "NONE" or 
                final_campaign_display == campaign_id):
                
                # Check both text fields where manufacturers hide their campaign numbers
                notes_text = campaign.get("Notes", "") or ""
                remedy_text = campaign.get("Remedy", "") or ""
                
                # Combine them or check them sequentially using your pattern matching function
                extracted_code = extract_manufacturer_code(notes_text, vehicle["make"]) or extract_manufacturer_code(remedy_text, vehicle["make"])
                
                if extracted_code:
                    final_campaign_display = extracted_code
                else:
                    final_campaign_display = campaign_id
            
            composite_key = (vehicle["vin"], campaign_id)
            if composite_key not in existing_entries:
                new_rows_to_append.append({
                    "Vehicle Name": vehicle["vehicle_name"],
                    "VIN": vehicle["vin"],
                    "CampaignID": campaign_id,
                    "ManufacturerCampaign": final_campaign_display,
                    "Make": vehicle["make"],
                    "Model": vehicle["model"],
                    "Year": vehicle["year"]
                })
                existing_entries.add(composite_key)

    if new_rows_to_append:
        file_exists = os.path.exists(CSV_FILE_PATH) and os.path.getsize(CSV_FILE_PATH) > 0
        
        with open(CSV_FILE_PATH, mode='a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            
            if not file_exists:
                writer.writeheader()
                
            for new_row in new_rows_to_append:
                writer.writerow(new_row)
                
        print(f"SUCCESS: Exported {len(new_rows_to_append)} fresh individual active campaign elements.")
    else:
        print("RESULT: All CSV entries are perfectly aligned. No new action tracking needed.")

if __name__ == "__main__":
    process_recall_sync()



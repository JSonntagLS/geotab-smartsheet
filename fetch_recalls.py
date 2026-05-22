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
        
    # Safely handle spaces/special characters in commercial make and model names
    encoded_make = urllib.parse.quote(str(make).strip())
    encoded_model = urllib.parse.quote(str(model).strip())
    encoded_year = urllib.parse.quote(str(year).strip())
    
    # Standardize parameters and safely handle spaces or slashes in commercial vehicle descriptors
    clean_make = " ".join(str(make).strip().split()).upper()
    clean_model = " ".join(str(model).strip().split()).upper()
    clean_year = " ".join(str(year).strip().split()).upper()
    
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

def extract_manufacturer_code(notes_text):
    """Robust pattern matching to isolate shorthand manufacturer campaign codes from NHTSA text blocks."""
    if not notes_text:
        return ""
        
    # Pattern 1: Capture explicit parentheses blocks like (Recall Campaign 246) or (06D)
    paren_match = re.search(r'\((?:Recall\s+)?(?:Campaign|Number)?\s*([A-Z0-9]{3,6})\)', notes_text, re.IGNORECASE)
    if paren_match:
        return paren_match.group(1).strip().upper()
        
    # Pattern 2: Standard manufacturer text callouts targeting specific phrasing variations
    text_match = re.search(r'(?:recall\s+number\s+is|recall\s+is|campaign\s+number\s+is|campaign\s+is|internal\s+number\s+for\s+this\s+recall\s+is)\s+([A-Z0-9]{2,6})(?:\.|\s|$)', notes_text, re.IGNORECASE)
    if text_match:
        potential_code = text_match.group(1).strip().upper()
        if any(char.isdigit() for char in potential_code):
            return potential_code

    # Fallback Pattern 3: Catch casual mentions of numeric/alphanumeric codes near the word recall or campaign
    fallback_match = re.search(r'(?:recall|campaign)\s+(?:code|number)?\s*([A-Z0-9]{2,6})\b', notes_text, re.IGNORECASE)
    if fallback_match:
        potential_code = fallback_match.group(1).strip().upper()
        if any(char.isdigit() for char in potential_code):
            return potential_code

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
                "make": make_val,
                "model": model_val,
                "year": year_val
            })

    if not vehicles_to_check:
        print("No complete vehicle profiles (VIN, Make, Model, Year) discovered.")
        return

    existing_entries = load_existing_recalls()
    new_rows_to_append = []

    for vehicle in vehicles_to_check:
        raw_campaigns = fetch_active_recalls(vehicle["make"], vehicle["model"], vehicle["year"])
        
        for campaign in raw_campaigns:
            campaign_id = str(campaign.get("NHTSACampaignNumber", "")).strip()
            if not campaign_id:
                continue
                
            # Shift data source to the text summary block and isolate the true manufacturer campaign string
            notes_payload = campaign.get("Notes", "")
            mfg_campaign = extract_manufacturer_code(notes_payload)
            
            composite_key = (vehicle["vin"], campaign_id)
            if composite_key not in existing_entries:
                new_rows_to_append.append({
                    "Vehicle Name": vehicle["vehicle_name"],
                    "VIN": vehicle["vin"],
                    "CampaignID": campaign_id,
                    "ManufacturerCampaign": mfg_campaign,
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



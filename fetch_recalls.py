import os
import csv
import requests
import smartsheet

# --- SMARTSHEET COLUMN CONFIGURATION ---
COL_VIN = 6471696134737796
COL_MAKE = 849062013472644
COL_MODEL = 5352661640843140
COL_YEAR = 3100861827157892

CSV_FILE_PATH = "fixed_recalls.csv"
FIELDNAMES = ["VIN", "CampaignID", "ManufacturerCampaign", "Make", "Model", "Year"]

def fetch_active_recalls(make, model, year):
    """Queries the correct NHTSA database for active safety recalls."""
    if not (make and model and year):
        return []
        
    # Using the correct api.nhtsa.gov domain for safety campaigns
    url = f"https://api.nhtsa.gov/recalls/recallsByVehicle?make={make}&model={model}&modelYear={year}"
    print(f"Pinging NHTSA API for: {year} {make} {model}...")
    
    try:
        response = requests.get(url, timeout=15)
        if response.status_code == 200:
            data = response.json()
            return data.get("results", [])
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
        vin_val = ""
        make_val = ""
        model_val = ""
        year_val = ""

        for cell in row.cells:
            if cell.column_id == COL_VIN:
                vin_val = str(cell.value).strip().upper() if cell.value else ""
            elif cell.column_id == COL_MAKE:
                make_val = str(cell.value).strip() if cell.value else ""
            elif cell.column_id == COL_MODEL:
                model_val = str(cell.value).strip() if cell.value else ""
            elif cell.column_id == COL_YEAR:
                if cell.value:
                    # Clean the Smartsheet float display (.0) down to a standard integer string
                    raw_year = str(cell.value).split('.')
                    year_val = raw_year.strip()

        if vin_val and make_val and model_val and year_val:
            vehicles_to_check.append({
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
            # The official recall API returns 'NHTSACampaignNumber' inside the results array
            campaign_id = str(campaign.get("NHTSACampaignNumber", "")).strip()
            if not campaign_id:
                continue
                
            # Safely extract the internal factory code if available from the record notes
            mfg_campaign = str(campaign.get("Component", "")).split(":")[-1].strip() if campaign.get("Component") else ""
            
            composite_key = (vehicle["vin"], campaign_id)
            if composite_key not in existing_entries:
                new_rows_to_append.append({
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

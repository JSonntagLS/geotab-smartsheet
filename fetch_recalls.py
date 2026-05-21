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

def fetch_nhtsa_recalls(make, model, year):
    """Queries the NHTSA recall database for a specific make, model, and year."""
    if not (make and model and year):
        return []
        
    url = f"https://vpic.nhtsa.dot.gov/api/vehicles/getrecallsformodelcommonyear?make={make}&model={model}&year={year}&format=json"
    print(f"Pinging NHTSA API for: {year} {make} {model}...")
    
    try:
        response = requests.get(url, timeout=15)
        if response.status_code == 200:
            data = response.json()
            return data.get("Results", [])
        else:
            print(f"   -> NHTSA API returned response status: {response.status_code}")
    except Exception as e:
        print(f"   -> Error reaching NHTSA endpoint: {e}")
        
    return []

def load_existing_recalls():
    """Reads the current CSV data to avoid duplicates."""
    existing_records = set()
    if not os.path.exists(CSV_FILE_PATH):
        return existing_records
        
    try:
        with open(CSV_FILE_PATH, mode='r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Use a unique combination of VIN and CampaignID as our primary key
                if row.get("VIN") and row.get("CampaignID"):
                    existing_records.add((row["VIN"].strip().upper(), row["CampaignID"].strip()))
    except Exception as e:
        print(f"Error parsing existing CSV file: {e}")
        
    return existing_records

def process_recall_sync():
    # 1. Initialize Smartsheet connection
    try:
        smart = smartsheet.Smartsheet(os.getenv("SMARTSHEET_TOKEN"))
        sheet_id = int(os.getenv("SMARTSHEET_ID"))
        sheet = smart.Sheets.get_sheet(sheet_id)
    except Exception as e:
        print(f"Smartsheet Authentication Error: {e}")
        return

    print(f"Loaded sheet. Reading data profiles across {len(sheet.rows)} records...")

    # 2. Extract vehicles from Smartsheet tracking matrix
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
                year_val = str(cell.value).strip() if cell.value else ""

        if vin_val and make_val and model_val and year_val:
            vehicles_to_check.append({
                "vin": "".join(vin_val.split()),
                "make": make_val,
                "model": model_val,
                "year": year_val
            })

    if not vehicles_to_check:
        print("No active vehicles discovered with complete VIN, Make, Model, and Year tracking profiles.")
        return

    # 3. Read existing file state to prevent duplicates
    existing_entries = load_existing_recalls()
    new_rows_to_append = []

    # 4. Fetch recalls and correlate with vehicle context
    for vehicle in vehicles_to_check:
        campaigns = fetch_nhtsa_recalls(vehicle["make"], vehicle["model"], vehicle["year"])
        
        for campaign in campaigns:
            campaign_id = str(campaign.get("NHTSACampaignNumber", "")).strip()
            if not campaign_id:
                continue
                
            # Check if this exact combination of VIN and CampaignID already exists
            if (vehicle["vin"], campaign_id) not in existing_entries:
                new_rows_to_append.append({
                    "VIN": vehicle["vin"],
                    "CampaignID": campaign_id,
                    "Make": vehicle["make"],
                    "Model": vehicle["model"],
                    "Year": vehicle["year"]
                })
                # Add it dynamically to prevent local duplicates within the same run cycle
                existing_entries.add((vehicle["vin"], campaign_id))

    # 5. Output new findings to CSV tracking sheet
    if new_rows_to_append:
        file_exists = os.path.exists(CSV_FILE_PATH) and os.path.getsize(CSV_FILE_PATH) > 0
        
        with open(CSV_FILE_PATH, mode='a', newline='', encoding='utf-8') as f:
            fieldnames = ["VIN", "CampaignID", "Make", "Model", "Year"]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            
            if not file_exists:
                writer.writeheader()
                
            for new_row in new_rows_to_append:
                writer.writerow(new_row)
                
        print(f"SUCCESS: Written {len(new_rows_to_append)} new critical campaign logs to {CSV_FILE_PATH}.")
    else:
        print("RESULT: CSV file tracking is complete. No new recall records detected.")

if __name__ == "__main__":
    process_recall_sync()

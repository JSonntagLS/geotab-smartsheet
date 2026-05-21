import os
import sys
import pandas as pd
import requests
import smartsheet

CSV_PATH = "fixed_recalls.csv"

def decode_vin_details(vin):
    """Queries the NHTSA vPIC database to find Make, Model, and Year from a raw VIN."""
    try:
        url = f"https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/{vin}?format=json"
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            data = res.json().get('Results', [{}])
            make = str(data.get('Make', '')).strip()
            model = str(data.get('Model', '')).strip()
            year = str(data.get('ModelYear', '')).strip()
            if make and model and year:
                return make, model, year
    except Exception:
        pass
    return None, None, None

def fetch_nhtsa_recalls(make, model, year):
    """Queries the NHTSA database for active campaign listings."""
    try:
        url = f"https://api.nhtsa.gov/recalls/recallsByVehicle?make={make}&model={model}&modelYear={year}"
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            return res.json().get('results', [])
    except Exception:
        pass
    return []

def main():
    token = os.environ.get("SMARTSHEET_TOKEN")
    sheet_id = os.environ.get("SHEET_ID")
    
    if not token or not sheet_id:
        print("Error: Missing SMARTSHEET_TOKEN or SHEET_ID environment secrets.")
        sys.exit(1)
        
    print("Connecting to Smartsheet API...")
    smart = smartsheet.Smartsheet(token)
    
    try:
        sheet = smart.Sheets.get_sheet(int(sheet_id))
    except Exception as e:
        print(f"Failed to access Smartsheet: {e}")
        sys.exit(1)

    # Dynamically look for the column named VIN
    col_map = {col.title.lower().strip(): col.index for col in sheet.columns}
    vin_idx = col_map.get('vin')

    if vin_idx == None:
        print(f"Error: Could not find a 'VIN' column in your Smartsheet.")
        print(f"Available columns: {list(col_map.keys())}")
        sys.exit(1)

    print("Parsing unique VINs from Smartsheet...")
    records = []
    
    for row in sheet.rows:
        v_vin = str(row.cells[vin_idx].value or '').strip()
        if not v_vin or len(v_vin) < 10:  # Skip empty or clearly invalid rows
            continue
            
        print(f"Processing VIN: {v_vin}")
        
        # Step 1: Decode the VIN to find the Make, Model, and Year
        make, model, year = decode_vin_details(v_vin)
        
        if not make or not model or not year:
            print(f"Could not decode vehicle metadata for VIN: {v_vin}")
            continue
            
        print(f"Found Identity: {year} {make} {model}")
        
        # Step 2: Grab the matching recall campaigns
        campaigns = fetch_nhtsa_recalls(make, model, year)
        
        for recall in campaigns:
            camp_id = str(recall.get('NHTSACampaignNumber', '')).strip()
            if camp_id:
                records.append({
                    "VIN": v_vin,
                    "CampaignID": camp_id,
                    "Make": make,
                    "Model": model,
                    "Year": year
                })

    # Step 3: Insert everything straight into your fixed_recalls.csv
    df_new = pd.DataFrame(records)
    
    if df_new.empty:
        print("No active recall sequences matched or discovered.")
        if not os.path.exists(CSV_PATH):
            pd.DataFrame(columns=["VIN", "CampaignID", "Make", "Model", "Year"]).to_csv(CSV_PATH, index=False)
    else:
        df_new.to_csv(CSV_PATH, index=False)
        print(f"Success! Captured and inserted {len(df_new)} logs into '{CSV_PATH}'")

if __name__ == "__main__":
    main()

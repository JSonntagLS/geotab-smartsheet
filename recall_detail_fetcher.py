import os
import sys
import pandas as pd
import requests
import smartsheet

CSV_PATH = "fixed_recalls.csv"

def fetch_nhtsa_recalls(make, model, year):
    """Fetches all active federal campaign IDs for a specific vehicle layout."""
    try:
        url = f"https://api.nhtsa.gov/recalls/recallsByVehicle?make={make}&model={model}&modelYear={year}"
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            return res.json().get('results', [])
    except Exception:
        pass
    return []

def main():
    # 1. Gather secure credentials from GitHub environment variables
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

    # 2. Map Smartsheet columns to find index keys dynamically
    col_map = {col.title.lower().strip(): col.index for col in sheet.columns}
    
    # Locate column layouts dynamically, falling back to typical property keys
    vin_idx = col_map.get('vin')
    make_idx = col_map.get('make')
    model_idx = col_map.get('model')
    year_idx = col_map.get('year') or col_map.get('model year') or col_map.get('model_year')

    if None in (vin_idx, make_idx, model_idx, year_idx):
        print(f"Error: Could not map required vehicle columns from your sheet schema.")
        print(f"Detected columns: {list(col_map.keys())}")
        sys.exit(1)

    print("Parsing rows from Smartsheet...")
    records = []
    
    # 3. Iterate through each vehicle in your inventory sheet
    for row in sheet.rows:
        # Prevent errors from empty row values
        v_vin = str(row.cells[vin_idx].value or '').strip()
        v_make = str(row.cells[make_idx].value or '').strip()
        v_model = str(row.cells[model_idx].value or '').strip()
        v_year = str(row.cells[year_idx].value or '').strip()
        
        if not v_vin or not v_make or not v_model or not v_year:
            continue
            
        print(f"Checking updates for: {v_year} {v_make} {v_model} [{v_vin}]")
        
        # 4. Check NHTSA database for real-time campaign identifiers
        campaigns = fetch_nhtsa_recalls(v_make, v_model, v_year)
        
        for recall in campaigns:
            camp_id = str(recall.get('NHTSACampaignNumber', '')).strip()
            if camp_id:
                records.append({
                    "VIN": v_vin,
                    "CampaignID": camp_id,
                    "Make": v_make,
                    "Model": v_model,
                    "Year": v_year
                })

    # 5. Output dataset straight into fixed_recalls.csv
    df_new = pd.DataFrame(records)
    
    if df_new.empty:
        print("No recall entries generated or discovered.")
        # Ensure a clean CSV file header structure still exists
        if not os.path.exists(CSV_PATH):
            pd.DataFrame(columns=["VIN", "CampaignID", "Make", "Model", "Year"]).to_csv(CSV_PATH, index=False)
    else:
        df_new.to_csv(CSV_PATH, index=False)
        print(f"Success! Populated {len(df_new)} total recall listings into '{CSV_PATH}'")

if __name__ == "__main__":
    main()

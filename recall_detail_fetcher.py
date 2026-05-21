import pandas as pd
import requests
import os

CSV_PATH = "fixed_recalls.csv"
OUTPUT_PATH = "detailed_recalls.csv"

def fetch_nhtsa_details(make, model, year, campaign_id):
    """Queries the live NHTSA API for the detailed campaign parameters."""
    try:
        url = f"https://api.nhtsa.gov/recalls/recallsByVehicle?make={make}&model={model}&modelYear={year}"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            results = response.json().get('results', [])
            for recall in results:
                if str(recall.get('NHTSACampaignNumber', '')).strip() == str(campaign_id).strip():
                    return {
                        "Component": recall.get("Component", "N/A"),
                        "Summary": recall.get("Summary", "No Summary Provided"),
                        "Cone": recall.get("Cone", "No Consequence Stated"),
                        "Remedy": recall.get("Remedy", "No Remedy Listed")
                    }
    except Exception:
        pass
    return None

def main():
    if not os.path.exists(CSV_PATH):
        print(f"Error: Could not locate '{CSV_PATH}' in the repository workspace.")
        return

    df_csv = pd.read_csv(CSV_PATH)
    if df_csv.empty:
        print("The fixed_recalls.csv file is empty. Nothing to process.")
        return

    print(f"Processing {len(df_csv)} records from {CSV_PATH}...")
    detailed_records = []
    
    for idx, row in df_csv.iterrows():
        vin = str(row.get('VIN', 'N/A')).strip()
        camp_id = str(row.get('CampaignID', 'N/A')).strip()
        make = str(row.get('Make', '')).strip()
        model = str(row.get('Model', '')).strip()
        year = str(row.get('Year', '')).strip()
        
        print(f"Fetching data for Campaign {camp_id} ({year} {make} {model})...")
        api_data = fetch_nhtsa_details(make, model, year, camp_id)
        
        if api_data:
            detailed_records.append({
                "VIN": vin,
                "CampaignID": camp_id,
                "Make": make,
                "Model": model,
                "Year": year,
                "Component": api_data["Component"],
                "Summary": api_data["Summary"],
                "Consequence": api_data["Cone"],
                "Remedy": api_data["Remedy"]
            })
        else:
            detailed_records.append({
                "VIN": vin,
                "CampaignID": camp_id,
                "Make": make,
                "Model": model,
                "Year": year,
                "Component": "N/A",
                "Summary": "Details could not be fetched from the NHTSA database. Check details manually.",
                "Consequence": "N/A",
                "Remedy": "N/A"
            })

    df_output = pd.DataFrame(detailed_records)
    df_output.to_csv(OUTPUT_PATH, index=False)
    print(f"Success! Detailed report written to '{OUTPUT_PATH}'")

if __name__ == "__main__":
    main()

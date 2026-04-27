import mygeotab
import pandas as pd
import os
from datetime import datetime

def harvest_data():
    print(f"--- STARTING DATA HARVEST: {datetime.now()} ---")
    
    # 1. Connect to Geotab
    api = mygeotab.API(username=os.getenv("GEOTAB_USER"), password=os.getenv("GEOTAB_PASSWORD"), database=os.getenv("GEOTAB_DB"))
    api.authenticate()
    print("Authenticated with Geotab.")

    # 2. Collect Data
    devices = api.get('Device')
    output = []
    print(f"Found {len(devices)} devices. Starting mileage pull...")

    for d in devices:
        logs = api.get('StatusData', search={
            'deviceSearch': {'id': d['id']}, 
            'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 
            'resultsLimit': 1
        })
        
        # Robust check for the list
        miles = 0
        if logs and isinstance(logs, list):
            # Grab the first actual item in the list
            first_entry = logs
            # Now read the data from that item
            meters = first_entry.get('data', 0)
            miles = round(meters / 1609.344, 0)
        
        output.append({
            "Vehicle Name": d['name'],
            "Serial": d['serialNumber'],
            "Live Odometer": miles
        })

    # 3. Save to CSV
    df = pd.DataFrame(output)
    df.to_csv("fleet_live.csv", index=False)
    print("SUCCESS: fleet_live.csv created.")

if __name__ == "__main__":
    harvest_data()

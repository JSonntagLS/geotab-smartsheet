import mygeotab
import pandas as pd
import os
from datetime import datetime

def harvest_data():
    print(f"--- STARTING DATA HARVEST: {datetime.now()} ---")
    
    # 1. Connect to Geotab
    try:
        api = mygeotab.API(
            username=os.getenv("GEOTAB_USER"), 
            password=os.getenv("GEOTAB_PASSWORD"), 
            database=os.getenv("GEOTAB_DB")
        )
        api.authenticate()
        print("Authenticated with Geotab.")
    except Exception as e:
        print(f"Auth Failed: {e}")
        return

    # 2. Collect Data
    devices = api.get('Device')
    output = []
    print(f"Found {len(devices)} devices. Starting mileage pull...")

    for d in devices:
        # Request the single most recent odometer reading for this VIN
        logs = api.get('StatusData', search={
            'deviceSearch': {'id': d['id']}, 
            'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 
            'resultsLimit': 1
        })
        
        # The logic fix that handles the "List" error properly
        miles = 0
        if isinstance(logs, list) and len(logs) > 0:
            # We look inside the first item of the list
            meters = logs.get('data', 0)
            miles = round(meters / 1609.344, 0)
        
        output.append({
            "Vehicle Name": d['name'],
            "Serial": d['serialNumber'],
            "Live Odometer": miles,
            "Last Checked": datetime.now().strftime("%Y-%m-%d %H:%M")
        })

    # 3. Save to CSV
    df = pd.DataFrame(output)
    df.to_csv("fleet_live.csv", index=False)
    print("SUCCESS: fleet_live.csv has been created/updated.")

if __name__ == "__main__":
    harvest_data()

import mygeotab
import pandas as pd
import os
from datetime import datetime

def harvest_data():
    print(f"--- STARTING HARVEST: {datetime.now()} ---")
    
    api = mygeotab.API(username=os.getenv("GEOTAB_USER"), password=os.getenv("GEOTAB_PASSWORD"), database=os.getenv("GEOTAB_DB"))
    api.authenticate()

    # Get Live Snapshot
    status_info = api.get('DeviceStatusInfo')
    live_mileage_map = {info['device']['id']: round(info.get('odometer', 0) / 1609.344, 0) for info in status_info}

    devices = api.get('Device')
    output = []

    for d in devices:
        miles = live_mileage_map.get(d['id'], 0)
        
        # TARGETED DEBUG: This will show up in your GitHub Action log
        if "PACIFICA" in d.get('name', '').upper():
            print(f"DEBUG: Found {d.get('name')} - Current Live Odometer: {miles}")
        
        output.append({
            "Vehicle Name": d.get('name'),
            "Serial": d.get('serialNumber'),
            "Live Odometer": miles
        })

    df = pd.DataFrame(output)
    df.to_csv("fleet_live.csv", index=False)
    print(f"SUCCESS: {len(output)} vehicles processed.")

if __name__ == "__main__":
    harvest_data()

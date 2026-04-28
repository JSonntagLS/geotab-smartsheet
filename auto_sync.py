import mygeotab
import pandas as pd
import os
from datetime import datetime

def harvest_data():
    print(f"--- STARTING FAST BULK HARVEST: {datetime.now()} ---")
    
    api = mygeotab.API(username=os.getenv("GEOTAB_USER"), password=os.getenv("GEOTAB_PASSWORD"), database=os.getenv("GEOTAB_DB"))
    api.authenticate()

    # 1. Get all devices (1 API Call)
    devices = api.get('Device')
    
    # 2. Get the latest Odometer StatusData for EVERYONE in one go (1 API Call)
    # By omitting 'deviceSearch', Geotab returns the most recent records it has
    all_odo_logs = api.get('StatusData', search={
        'diagnosticSearch': {'id': 'DiagnosticOdometerId'},
        'resultsLimit': 76  # Set this to your fleet size or slightly higher
    })

    # Create a lookup dictionary: {device_id: odometer_value}
    odo_lookup = {log['device']['id']: log['data'] for log in all_odo_logs if 'device' in log}

    output = []
    for d in devices:
        device_id = d.get('id')
        # Pull from our local lookup instead of calling the API again
        meters = odo_lookup.get(device_id, 0)
        miles = round(meters / 1609.344, 0)
        
        if "PACIFICA" in d.get('name', '').upper():
            print(f"DEBUG: {d.get('name')} | Result: {miles}")
        
        output.append({
            "Vehicle Name": d.get('name'),
            "Serial": d.get('serialNumber'),
            "Current_Odometer": miles
        })

    df = pd.DataFrame(output)
    df.to_csv("fleet_live.csv", index=False)
    print(f"SUCCESS: {len(output)} vehicles processed in seconds.")

if __name__ == "__main__":
    harvest_data()

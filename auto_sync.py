import mygeotab
import pandas as pd
import os
from datetime import datetime

def harvest_data():
    print(f"--- STARTING LIVE HARVEST: {datetime.now()} ---")
    
    api = mygeotab.API(username=os.getenv("GEOTAB_USER"), password=os.getenv("GEOTAB_PASSWORD"), database=os.getenv("GEOTAB_DB"))
    api.authenticate()

    # Pulling current devices
    devices = api.get('Device')
    output = []

    for d in devices:
        # Simple, direct pull for the absolute latest record for this specific ID
        logs = api.get('StatusData', search={
            'deviceSearch': {'id': d['id']},
            'diagnosticSearch': {'id': 'DiagnosticOdometerId'},
            'resultsLimit': 1
        })

        miles = 0
        # Correctly accessing the first item in the list
        if logs and len(logs) > 0:
            record = logs # This gets the dictionary inside the list
            meters = record.get('data', 0)
            miles = round(meters / 1609.344, 0)
        
        # Keep debug for Pacificas to verify the '0' is gone
        if "PACIFICA" in d.get('name', '').upper():
            print(f"DEBUG: {d.get('name')} | Current Odometer: {miles}")
        
        output.append({
            "Vehicle Name": d.get('name'),
            "Serial": d.get('serialNumber'),
            "Current_Odometer": miles
        })

    df = pd.DataFrame(output)
    df.to_csv("fleet_live.csv", index=False)
    print(f"SUCCESS: {len(output)} vehicles processed.")

if __name__ == "__main__":
    harvest_data()

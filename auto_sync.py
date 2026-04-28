import mygeotab
import pandas as pd
import os
from datetime import datetime

def unwrap_data(obj):
    """
    Russian Nesting Doll logic: 
    If it's a list, look inside. Repeat until we find a dictionary or None.
    """
    while isinstance(obj, list):
        if len(obj) > 0:
            obj = obj
        else:
            return None
    return obj

def harvest_data():
    print(f"--- STARTING ROBUST HARVEST: {datetime.now()} ---")
    
    api = mygeotab.API(username=os.getenv("GEOTAB_USER"), password=os.getenv("GEOTAB_PASSWORD"), database=os.getenv("GEOTAB_DB"))
    api.authenticate()

    devices = api.get('Device')
    output = []

    for d in devices:
        # Get the most recent odometer log
        logs = api.get('StatusData', search={
            'deviceSearch': {'id': d['id']},
            'diagnosticSearch': {'id': 'DiagnosticOdometerId'},
            'resultsLimit': 1
        })

        # Use the Unwrapper to find the record safely
        record = unwrap_data(logs)
        
        miles = 0
        if record and isinstance(record, dict):
            meters = record.get('data', 0)
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
    print(f"SUCCESS: {len(output)} vehicles processed.")

if __name__ == "__main__":
    harvest_data()

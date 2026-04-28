import mygeotab
import pandas as pd
import os
from datetime import datetime, timedelta

def harvest_data():
    today = datetime.now()
    deadline = (today - timedelta(days=1)).replace(hour=23, minute=59, second=59)
    print(f"--- HARVESTING DATA (CEILING: {deadline}) ---")
    
    api = mygeotab.API(username=os.getenv("GEOTAB_USER"), password=os.getenv("GEOTAB_PASSWORD"), database=os.getenv("GEOTAB_DB"))
    api.authenticate()

    devices = api.get('Device')
    output = []

    for d in devices:
        # Step 1: Try to get the Sunday Snapshot
        logs = api.get('StatusData', search={
            'deviceSearch': {'id': d['id']},
            'diagnosticSearch': {'id': 'DiagnosticOdometerId'},
            'toDateTime': deadline.isoformat(),
            'resultsLimit': 1
        })
        
        # Step 2: If Sunday is empty, get the absolute latest record (No Date Limit)
        if not logs or len(logs) == 0:
            logs = api.get('StatusData', search={
                'deviceSearch': {'id': d['id']},
                'diagnosticSearch': {'id': 'DiagnosticOdometerId'},
                'resultsLimit': 1
            })

        miles = 0
        if logs and isinstance(logs, list) and len(logs) > 0:
            record = logs
            if isinstance(record, dict):
                meters = record.get('data', 0)
                miles = round(meters / 1609.344, 0)
        
        if "PACIFICA" in d.get('name', '').upper():
            print(f"DEBUG: {d.get('name')} | Result: {miles}")
        
        output.append({
            "Vehicle Name": d.get('name'),
            "Serial": d.get('serialNumber'),
            "Odometer_Miles": miles
        })

    df = pd.DataFrame(output)
    df.to_csv("fleet_live.csv", index=False)
    print(f"SUCCESS: {len(output)} vehicles processed.")

if __name__ == "__main__":
    harvest_data()

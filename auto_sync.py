import mygeotab
import pandas as pd
import os
from datetime import datetime, timedelta

def harvest_data():
    # Set the deadline to Sunday night
    # We look backwards from this point to find the last known record
    today = datetime.now()
    deadline = (today - timedelta(days=1)).replace(hour=23, minute=59, second=59)
    print(f"--- HARVESTING LAST KNOWN DATA PRIOR TO: {deadline} ---")
    
    api = mygeotab.API(username=os.getenv("GEOTAB_USER"), password=os.getenv("GEOTAB_PASSWORD"), database=os.getenv("GEOTAB_DB"))
    api.authenticate()

    devices = api.get('Device')
    output = []

    for d in devices:
        # 'toDateTime' acts as the ceiling. 
        # Geotab starts there and searches backwards for the 1 most recent result.
        logs = api.get('StatusData', search={
            'deviceSearch': {'id': d['id']},
            'diagnosticSearch': {'id': 'DiagnosticOdometerId'},
            'toDateTime': deadline.isoformat(),
            'resultsLimit': 1
        })
        
        miles = 0
        if logs and isinstance(logs, list) and len(logs) > 0:
            meters = logs.get('data', 0)
            miles = round(meters / 1609.344, 0)
        
        if "PACIFICA" in d.get('name', '').upper():
            print(f"DEBUG: {d.get('name')} | Last Known (as of Sunday): {miles}")
        
        output.append({
            "Vehicle Name": d.get('name'),
            "Serial": d.get('serialNumber'),
            "Sunday_Snapshot_Miles": miles
        })

    df = pd.DataFrame(output)
    df.to_csv("fleet_live.csv", index=False)
    print(f"SUCCESS: {len(output)} vehicles screenshotted.")

if __name__ == "__main__":
    harvest_data()

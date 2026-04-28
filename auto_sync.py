import mygeotab
import pandas as pd
import os
from datetime import datetime, timedelta

def harvest_data():
    # 1. Set our search window: 7 days ago to cover weekends/parking
    lookback_days = 7
    start_date = (datetime.utcnow() - timedelta(days=lookback_days)).isoformat()
    
    print(f"--- STARTING 7-DAY WINDOW HARVEST (Since {start_date}) ---")
    
    api = mygeotab.API(username=os.getenv("GEOTAB_USER"), password=os.getenv("GEOTAB_PASSWORD"), database=os.getenv("GEOTAB_DB"))
    api.authenticate()

    devices = api.get('Device')
    
    # We'll search for both types of Odometer diagnostics within our time window
    diagnostics = ['DiagnosticOdometerAdjustmentId', 'DiagnosticOdometerId']
    
    odo_lookup = {}

    for diag in diagnostics:
        # We increase the resultsLimit because 76 vehicles x 7 days could be many logs
        # but we only care about the latest one per device.
        logs = api.get('StatusData', search={
            'diagnosticSearch': {'id': diag},
            'fromDate': start_date,
            'resultsLimit': 1000 
        })
        
        for log in logs:
            dev_id = log['device']['id']
            val = log.get('data', 0)
            ts = log.get('dateTime')
            
            # Keep the newest log found across both diagnostic types
            if dev_id not in odo_lookup or ts > odo_lookup[dev_id]['ts']:
                odo_lookup[dev_id] = {
                    'val': val, 
                    'ts': ts, 
                    'type': "Adjusted" if "Adjustment" in diag else "Raw"
                }

    output = []
    for d in devices:
        dev_id = d.get('id')
        name = d.get('name', 'Unknown')
        entry = odo_lookup.get(dev_id)
        
        if entry:
            miles = round(entry['val'] / 1609.344, 0)
            timestamp = entry['ts']
            source = entry['type']
        else:
            miles = "NO DATA"
            timestamp = f"None in last {lookback_days} days"
            source = "N/A"

        print(f"[{source.ljust(8)}] {name.ljust(20)} | {str(miles).rjust(8)} mi | {timestamp}")
        
        output.append({
            "Vehicle Name": name,
            "Serial": d.get('serialNumber'),
            "Odometer": miles,
            "Source": source,
            "Last_Sync": timestamp
        })

    df = pd.DataFrame(output)
    df.to_csv("fleet_live.csv", index=False)
    print(f"--- SUCCESS: {len(output)} vehicles processed ---")

if __name__ == "__main__":
    harvest_data()

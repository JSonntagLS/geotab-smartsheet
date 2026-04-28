import mygeotab
import pandas as pd
import os
import json
from datetime import datetime

def harvest_data():
    print(f"--- STARTING MILE-FOCUSED HARVEST: {datetime.now()} ---")
    
    api = mygeotab.API(username=os.getenv("GEOTAB_USER"), password=os.getenv("GEOTAB_PASSWORD"), database=os.getenv("GEOTAB_DB"))
    api.authenticate()

    devices = api.get('Device')
    
    # We pull 500 records to ensure we don't miss the 'quiet' vehicles
    # Pulling both Adjustment (Dashboard) and Raw Odometer
    search_params = [
        {'id': 'DiagnosticOdometerAdjustmentId'},
        {'id': 'DiagnosticOdometerId'}
    ]
    
    all_odo_logs = []
    for diag in search_params:
        logs = api.get('StatusData', search={
            'diagnosticSearch': diag,
            'resultsLimit': 400 
        })
        all_odo_logs.extend(logs)

    # Lookup dictionary to store the best available data per vehicle
    # Priority: Adjustment ID > Raw ID > Nothing
    odo_lookup = {}
    for log in all_odo_logs:
        dev_id = log['device']['id']
        val = log.get('data', 0)
        diag_type = log['diagnostic']['id']
        ts = log.get('dateTime')
        
        # We want the MOST RECENT log. If we already have a log for this car, 
        # only replace it if this new one is newer.
        if dev_id not in odo_lookup or ts > odo_lookup[dev_id]['ts']:
            odo_lookup[dev_id] = {'val': val, 'ts': ts, 'type': diag_type}

    output = []
    for d in devices:
        dev_id = d.get('id')
        name = d.get('name', 'Unknown')
        
        entry = odo_lookup.get(dev_id)
        
        if entry:
            meters = entry['val']
            # CONVERSION: Geotab returns meters. 
            # 1 meter = 0.000621371 miles
            miles = round(meters / 1609.344, 0)
            timestamp = entry['ts']
            source = "Adjusted" if "Adjustment" in entry['type'] else "Raw"
        else:
            miles = "MISSING"
            timestamp = "N/A"
            source = "NONE"

        # BUILD MODE DEBUGGING:
        # Check if the number seems suspiciously low (like KM vs Miles)
        print(f"[{source}] {name.ljust(18)} | {str(miles).rjust(7)} Miles | Last Sync: {timestamp}")
        
        output.append({
            "Vehicle Name": name,
            "Serial": d.get('serialNumber'),
            "Odometer_Miles": miles,
            "Source": source,
            "Last_Sync": timestamp
        })

    df = pd.DataFrame(output)
    df.to_csv("fleet_live.csv", index=False)
    print(f"--- SUCCESS: {len(output)} Vehicles Processed ---")

if __name__ == "__main__":
    harvest_data()

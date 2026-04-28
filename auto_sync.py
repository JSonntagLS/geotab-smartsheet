import mygeotab
import pandas as pd
import os
import json
from datetime import datetime

def harvest_data():
    print(f"--- STARTING DEBUG HARVEST: {datetime.now()} ---")
    
    api = mygeotab.API(username=os.getenv("GEOTAB_USER"), password=os.getenv("GEOTAB_PASSWORD"), database=os.getenv("GEOTAB_DB"))
    api.authenticate()

    devices = api.get('Device')
    
    # INCREASE LIMIT: We want a wider net to ensure every car is caught
    # We'll also print one raw log to see the 'fingerprint' of the data
    all_odo_logs = api.get('StatusData', search={
        'diagnosticSearch': {'id': 'DiagnosticOdometerAdjustmentId'},
        'resultsLimit': 300 
    })

    # DEBUG: Show us exactly what the first log looks like
    if all_odo_logs:
        print("--- RAW SAMPLE LOG (First Record) ---")
        print(json.dumps(all_odo_logs, indent=2))
        print("-------------------------------------")

    # Map with Timestamps: {device_id: (value, timestamp)}
    # We use a loop to ensure we keep the NEWEST timestamp for each ID
    odo_lookup = {}
    for log in all_odo_logs:
        dev_id = log['device']['id']
        val = log.get('data', 0)
        ts = log.get('dateTime')
        
        # Only keep the most recent if we have multiple for the same car
        if dev_id not in odo_lookup:
            odo_lookup[dev_id] = (val, ts)

    output = []
    missing_count = 0

    for d in devices:
        dev_id = d.get('id')
        name = d.get('name', 'Unknown')
        
        data_tuple = odo_lookup.get(dev_id)
        
        if data_tuple:
            meters, timestamp = data_tuple
            miles = round(meters / 1609.344, 0)
        else:
            miles = "NO DATA"
            timestamp = "N/A"
            missing_count += 1

        # Verbose Logging for everything during build mode
        print(f"VEHICLE: {name.ljust(20)} | ODO: {str(miles).ljust(8)} | TS: {timestamp}")
        
        output.append({
            "Vehicle Name": name,
            "Serial": d.get('serialNumber'),
            "Current_Odometer": miles,
            "Log_Timestamp": timestamp
        })

    df = pd.DataFrame(output)
    df.to_csv("fleet_live.csv", index=False)
    
    print(f"--- HARVEST COMPLETE ---")
    print(f"Total Vehicles: {len(output)}")
    print(f"Missing Data: {missing_count}")
    if missing_count > 0:
        print("ALERT: Some vehicles are missing odometer adjustment logs in the last 300 records.")

if __name__ == "__main__":
    harvest_data()

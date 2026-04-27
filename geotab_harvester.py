import mygeotab
import csv
import os
from datetime import datetime, timedelta

def harvest_geotab_to_csv():
    print("--- STARTING HARVESTER: GEOTAB TO CSV ---")
    
    # Auth Geotab
    api = mygeotab.API(username=os.getenv("GEOTAB_USER"), 
                       password=os.getenv("GEOTAB_PASSWORD"), 
                       database=os.getenv("GEOTAB_DB"))
    api.authenticate()

    devices = api.get('Device')
    # Use ISO format for Geotab date searches
    target_date = (datetime.now() - timedelta(days=7)).replace(hour=0, minute=0, second=0).isoformat()
    
    csv_data = []
    
    for d in devices:
        serial = d.get('serialNumber', 'Unknown')
        name = d.get('name', 'Unknown')
        device_id = d.get('id')

        try:
            # 1. Get Live Odometer
            curr_logs = api.get('StatusData', search={'deviceSearch': {'id': device_id}, 'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 'resultsLimit': 1})
            
            # 2. Get Odometer from Last Week
            prev_logs = api.get('StatusData', search={'deviceSearch': {'id': device_id}, 'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 'toDate': target_date, 'resultsLimit': 1})

            # Helper to handle that 'List' error and convert meters to miles
            def extract_miles(logs):
                if isinstance(logs, list) and len(logs) > 0:
                    # Access the first item before calling .get()
                    meters = logs.get('data', 0)
                    return int(round(meters / 1609.344, 0))
                return None

            live_m = extract_miles(curr_logs)
            past_m = extract_miles(prev_logs)

            # Keep "CHECK GPS" if live data is missing
            current_val = live_m if live_m is not None else "CHECK GPS"
            # If past data is missing, we'll leave it blank or use the current value
            past_val = past_m if past_m is not None else ""

            csv_data.append([serial, name, current_val, past_val, datetime.now().strftime("%Y-%m-%d")])
            print(f"Captured: {name} ({serial}) -> {current_val}")

        except Exception as e:
            print(f"Error harvesting {serial}: {str(e)}")

    # Write to CSV
    with open('fleet_data.csv', 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['Serial', 'Name', 'CurrentMileage', 'LastWeekOdometer', 'SyncDate'])
        writer.writerows(csv_data)

    print(f"--- HARVEST COMPLETE: {len(csv_data)} vehicles written to fleet_data.csv ---")

if __name__ == "__main__":
    harvest_geotab_to_csv()

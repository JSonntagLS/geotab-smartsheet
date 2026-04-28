import mygeotab
import pandas as pd
import os
from datetime import datetime, timedelta, time

def harvest_data():
    # --- SETUP TIME WINDOWS ---
    now = datetime.utcnow()
    # Calculate "Last Monday at 12:01 AM"
    days_since_monday = now.weekday()  # Monday is 0
    monday_start = (now - timedelta(days=days_since_monday + 7)).replace(hour=0, minute=1, second=0, microsecond=0)
    
    start_date_str = monday_start.isoformat()
    print(f"--- STARTING DATA HARVEST ---")
    print(f"Anchor Point: {start_date_str}")
    
    api = mygeotab.API(username=os.getenv("GEOTAB_USER"), password=os.getenv("GEOTAB_PASSWORD"), database=os.getenv("GEOTAB_DB"))
    api.authenticate()

    devices = api.get('Device')
    diagnostics = ['DiagnosticOdometerAdjustmentId', 'DiagnosticOdometerId']
    
    # Storage for both points
    current_odo = {}
    monday_odo = {}

    for diag in diagnostics:
        print(f"Pulling logs for {diag}...")
        logs = api.get('StatusData', search={
            'diagnosticSearch': {'id': diag},
            'fromDate': start_date_str,
            'resultsLimit': 2000 # Increased to ensure we get start and end of week
        })
        
        for log in logs:
            dev_id = log['device']['id']
            val = log.get('data', 0)
            ts = log.get('dateTime')
            
            # 1. Update Current (Latest)
            if dev_id not in current_odo or ts > current_odo[dev_id]['ts']:
                current_odo[dev_id] = {'val': val, 'ts': ts}
                
            # 2. Update Monday Start (Earliest)
            if dev_id not in monday_odo or ts < monday_odo[dev_id]['ts']:
                monday_odo[dev_id] = {'val': val, 'ts': ts}

    output = []
    for d in devices:
        dev_id = d.get('id')
        name = d.get('name', 'Unknown')
        
        # Current Stats
        curr = current_odo.get(dev_id)
        curr_miles = round(curr['val'] / 1609.344, 0) if curr else "NO DATA"
        
        # Monday Stats
        start = monday_odo.get(dev_id)
        start_miles = round(start['val'] / 1609.344, 0) if start else "NO DATA"
        
        # Weekly Calculation
        weekly_diff = 0
        if isinstance(curr_miles, float) and isinstance(start_miles, float):
            weekly_diff = curr_miles - start_miles

        print(f"VEHICLE: {name.ljust(20)} | Start: {str(start_miles).rjust(7)} | End: {str(curr_miles).rjust(7)} | Diff: {weekly_diff}")
        
        output.append({
            "Vehicle Name": name,
            "Serial": d.get('serialNumber'),
            "Monday_Start_Odo": start_miles,
            "Current_Odo": curr_miles,
            "Weekly_Miles": weekly_diff,
            "Last_Sync": curr['ts'] if curr else "N/A"
        })

    df = pd.DataFrame(output)
    df.to_csv("fleet_live.csv", index=False)
    print(f"--- SUCCESS: CSV Updated with Weekly Delta ---")

if __name__ == "__main__":
    harvest_data()

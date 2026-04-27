import mygeotab
import os
import pandas as pd
from datetime import datetime

print("--- !!! HEAVY DEBUG MODE STARTING !!! ---")

# 1. Auth with verbose printing
try:
    api = mygeotab.API(username=os.getenv("GEOTAB_USER"), password=os.getenv("GEOTAB_PASSWORD"), database=os.getenv("GEOTAB_DB"))
    api.authenticate()
    print("DEBUG: Auth successful.")
except Exception as e:
    print(f"DEBUG AUTH ERROR: {e}")

# 2. Device Pull
devices = api.get('Device')
print(f"DEBUG: Found {len(devices)} total devices.")

output = []

# Just look at the first 5 to keep the log readable but thorough
for d in devices[:5]:
    print(f"\n>>> PROCESSING VEHICLE: {d.get('name')} | ID: {d.get('id')}")
    
    logs = api.get('StatusData', search={
        'deviceSearch': {'id': d['id']}, 
        'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 
        'resultsLimit': 1
    })
    
    print(f"DEBUG RAW LOGS: {logs}")
    print(f"DEBUG LOGS TYPE: {type(logs)}")

    miles = 0
    
    # This is the "Nuclear" check. It handles lists, nested lists, and dicts.
    if logs:
        if isinstance(logs, list):
            print(f"DEBUG: Logs is a list of length {len(logs)}")
            first_level = logs
            print(f"DEBUG: first_level content: {first_level}")
            print(f"DEBUG: first_level type: {type(first_level)}")
            
            # Check if we have a nested list (list-within-a-list)
            if isinstance(first_level, list):
                print("DEBUG: !!! NESTED LIST DETECTED !!!")
                target = first_level
            else:
                target = first_level
                
            if isinstance(target, dict):
                meters = target.get('data', 0)
                miles = round(meters / 1609.344, 0)
                print(f"DEBUG: Successfully extracted {miles} miles.")
            else:
                print(f"DEBUG ERROR: Target is not a dict, it is {type(target)}")
        else:
            print(f"DEBUG ERROR: Logs is not a list, it is {type(logs)}")
    else:
        print("DEBUG: No logs returned for this vehicle.")

    output.append({"Name": d.get('name'), "Miles": miles})

print("\n--- !!! DEBUG COMPLETE. LOGS END !!! ---")

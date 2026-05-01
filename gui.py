import streamlit as st
import smartsheet
import pandas as pd
from datetime import datetime
import math
import google.generativeai as genai

# --- AI SETUP ---
# Replace with your actual API key
genai.configure(api_key=st.secrets["gemini_api_key"])
model = genai.GenerativeModel('gemini-1.5-flash')

# --- COORDINATE-BASED DISTANCE (Replaces the 136-line table) ---
# This allows any city to talk to any other city accurately.
CITY_COORDS = {
    "Johnston, IA": (41.6730, -93.6977), "Ames, IA": (42.0308, -93.6319),
    "Ankeny, IA": (41.7297, -93.6058), "Cedar Falls, IA": (42.5349, -92.4455),
    "Davenport, IA": (41.5234, -90.5776), "Des Moines, IA": (41.5868, -93.6250),
    "Fort Dodge, IA": (42.4975, -94.1680), "Marshalltown, IA": (42.0494, -92.9080),
    "Mason City, IA": (43.1536, -93.2010), "Pella, IA": (41.4080, -92.9163),
    "Sioux City, IA": (42.4963, -96.4049), "Urbandale, IA": (41.6266, -93.7122),
    "Waterloo, IA": (42.4928, -92.3425), "Aberdeen, SD": (45.4647, -98.4865),
    "Mitchell, SD": (43.7094, -98.0298), "Pierre, SD": (44.3683, -100.3510),
    "Yankton, SD": (42.8711, -97.3973)
}

def get_distance_km(loc1, loc2):
    if loc1 == loc2: return 0
    c1, c2 = CITY_COORDS.get(loc1), CITY_COORDS.get(loc2)
    if not c1 or not c2: return 999 # Penalty for unknown locations
    # Haversine formula for distance
    radius = 3958.8 # Miles
    lat1, lon1 = math.radians(c1[0]), math.radians(c1[1])
    lat2, lon2 = math.radians(c2[0]), math.radians(c2[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

# --- THE SWAP ENGINE ---
if run_analysis:
    st.toast("Calculating Optimal Fleet Rotation...")
    
    # 1. Identify Candidates
    # Recipient: Overused vehicles needing relief
    # Donor: Underused vehicles with capacity
    recipients = df[df['Rotation Priority'].str.contains('URGENT', na=False, case=False)]
    donors = df[df['Utilization Tier'].str.contains('UNDERUSED', na=False, case=False)]

    possible_swaps = []

    for _, rec in recipients.iterrows():
        for _, don in donors.iterrows():
            # RULE 1: Must be same vehicle type
            if rec['Vehicle Description'] != don['Vehicle Description']:
                continue
            
            # RULE 2: Calculate Benefit (Total mileage "error" corrected)
            # We want to match high over-utilization with high under-utilization
            rec_delta = rec['Monthly Projected'] - rec['Monthly Allowance']
            don_delta = don['Monthly Projected'] - don['Monthly Allowance'] # This will be negative
            
            mileage_benefit = rec_delta - don_delta 
            
            # RULE 3: Allowance Similarity (Prefer swapping like-for-like contracts)
            allowance_diff = abs(rec['Monthly Allowance'] - don['Monthly Allowance'])
            similarity_bonus = 1000 / (allowance_diff + 1) # Higher if allowances are close
            
            # RULE 4: Distance Penalty
            dist = get_distance_km(rec['Current Location'], don['Current Location'])
            dist_penalty = (dist ** 1.5) * 0.5 

            # FINAL SCORE
            score = (mileage_benefit * 0.7) + (similarity_bonus * 0.2) - (dist_penalty * 0.1)
            
            possible_swaps.append({
                "score": score,
                "rec_name": rec['Vehicle Name'],
                "don_name": don['Vehicle Name'],
                "rec_loc": rec['Current Location'],
                "don_loc": don['Current Location'],
                "distance": dist,
                "rec_row": rec['row_id'],
                "summary": f"Swap {rec['Vehicle Name']} (+{int(rec_delta)} mi) with {don['Vehicle Name']} ({int(don_delta)} mi)"
            })

    # Sort by highest score and pick unique matches (Greedy algorithm)
    sorted_swaps = sorted(possible_swaps, key=lambda x: x['score'], reverse=True)
    final_recs = []
    used_vehicles = set()

    for s in sorted_swaps:
        if s['rec_name'] not in used_vehicles and s['don_name'] not in used_vehicles:
            
            # --- GEMINI REASONING CALL ---
            prompt = f"""
            Analyze this fleet swap:
            Vehicle A: {s['rec_name']} at {s['rec_loc']} is over-utilizing its lease.
            Vehicle B: {s['don_name']} at {s['don_loc']} is under-utilizing its lease.
            Distance: {s['distance']:.1f} miles.
            Provide a professional 1-sentence rationale for why this swap saves money on lease overages.
            """
            try:
                response = model.generate_content(prompt)
                rationale = response.text
            except:
                rationale = "Optimizes lease mileage distribution based on current utilization trends."

            s['ai_rationale'] = rationale
            final_recs.append(s)
            used_vehicles.add(s['rec_name'])
            used_vehicles.add(s['don_name'])

    # Display final_recs in Streamlit...

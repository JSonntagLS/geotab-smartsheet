import streamlit as st
import smartsheet
import pandas as pd
from datetime import datetime
import math
import google.generativeai as genai

# --- PAGE CONFIG ---
st.set_page_config(layout="wide")

# --- AI SETUP ---
genai.configure(api_key=st.secrets["gemini_api_key"], transport='rest')
model = genai.GenerativeModel('gemini-1.5-flash')

# --- SIDEBAR ---
max_dist = st.sidebar.slider("Max Allowable Swap Distance (Miles)", 20, 500, 200)

# --- COORDINATE-BASED DISTANCE ---
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

def get_distance_miles(loc1, loc2):
    if loc1 == loc2: return 0
    c1, c2 = CITY_COORDS.get(loc1), CITY_COORDS.get(loc2)
    if not c1 or not c2: return 999 
    radius = 3958.8 
    lat1, lon1 = math.radians(c1[0]), math.radians(c1[1])
    lat2, lon2 = math.radians(c2[0]), math.radians(c2[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a)) * 1.2

# --- DATA LOADING ---
try:
    smart = smartsheet.Smartsheet(st.secrets["smartsheet_token"])
    sheet = smart.Sheets.get_sheet(st.secrets["sheet_id"])
    
    columns = [col.title for col in sheet.columns]
    rows = [[cell.value for cell in row.cells] for row in sheet.rows]
    df = pd.DataFrame(rows, columns=columns)
    
    # 1. CLEANING: Strip whitespace from headers
    df.columns = df.columns.str.strip() 

    # 2. EXACT MAPPING: Matches the specific headers from your error report
    col_map = {
        "projected": "Projected Monthly Usage",
        "allowance": "Monthly Allowance",
        "priority": "Rotation Priority",
        "tier": "Utilization Tier",
        "actual": "Monthly Miles Actual",
        "trend": "Weekly Trend",
        "name": "Vehicle Name",
        "loc": "Current Location",
        "desc": "Vehicle Description"
    }

    # Internal ID mapping
    df['row_id_internal'] = [row.id for row in sheet.rows]

    # 3. DISPLAY FILTERING: Strictly ordered
    df_display = df[[
        col_map["name"], 
        col_map["loc"], 
        col_map["allowance"], 
        col_map["projected"], 
        col_map["actual"], 
        col_map["trend"],
        col_map["priority"], 
        col_map["tier"]
    ]]

except Exception as e:
    st.error(f"Error loading Smartsheet: {e}")

# --- ACTION BUTTON STYLE ---
st.markdown("""
    <style>
    div.stButton > button:first-child {
        background-color: #0066cc;
        color: white;
        border-radius: 5px;
        height: 3em;
        width: 100%;
        font-weight: bold;
        border: none;
    }
    </style>""", unsafe_allow_html=True)

run_analysis = st.button("RUN FLEET ROTATION ANALYSIS")

if run_analysis:
    if 'df' not in locals():
        st.error("Data not found.")
    else:
        with st.spinner("Analyzing fleet rotations..."):
            try:
                # Filter based on current priority and tier status
                high_usage_fleet = df[df[col_map["priority"]].str.contains('URGENT', na=False, case=False)]
                low_usage_fleet = df[df[col_map["tier"]].str.contains('UNDERUSED', na=False, case=False)]

                possible_swaps = []
                for _, high_v in high_usage_fleet.iterrows():
                    for _, low_v in low_usage_fleet.iterrows():
                        # Matching by vehicle type/description
                        if high_v[col_map["desc"]] != low_v[col_map["desc"]]:
                            continue

                        dist = get_distance_miles(high_v[col_map["loc"]], low_v[col_map["loc"]])
                        if dist > max_dist:
                            continue
                        
                        # Calculate monthly lease deltas
                        high_delta = float(high_v[col_map["projected"]] or 0) - float(high_v[col_map["allowance"]] or 0)
                        low_delta = float(low_v[col_map["projected"]] or 0) - float(low_v[col_map["allowance"]] or 0)
                        
                        # Scoring logic (Higher impact swaps rise to the top)
                        score = ((high_delta - low_delta) * 0.7) - ((dist ** 1.5) * 0.1)
                        
                        possible_swaps.append({
                            "score": score,
                            "high_name": high_v[col_map["name"]],
                            "high_loc": high_v[col_map["loc"]],
                            "low_name": low_v[col_map["name"]],
                            "low_loc": low_v[col_map["loc"]],
                            "miles_over": int(high_delta),
                            "miles_under": int(abs(low_delta)),
                            "swap_dist_val": f"{dist:.1f} miles"
                        })

                sorted_swaps = sorted(possible_swaps, key=lambda x: x['score'], reverse=True)
                final_recs = []
                used_vehicles = set()

                for s in sorted_swaps:
                    if s['high_name'] not in used_vehicles and s['low_name'] not in used_vehicles:
                        # AI Prompt focusing on Fleet Logistics
                        prompt = (
                            f"Justify a fleet vehicle rotation: Move {s['high_name']} (at {s['high_loc']}) "
                            f"currently trending {s['miles_over']} miles over monthly limit, to the {s['low_loc']} route "
                            f"to replace {s['low_name']} which has {s['miles_under']} miles of monthly capacity. "
                            f"The distance between sites is {s['swap_dist_val']}."
                        )
                        
                        try:
                            response = model.generate_content(prompt)
                            s['Rotation Strategy'] = response.text.strip()
                        except:
                            s['Rotation Strategy'] = f"Reduces overage at {s['high_loc']} by swapping with underutilized asset at {s['low_loc']}."

                        final_recs.append(s)
                        used_vehicles.add(s['high_name'])
                        used_vehicles.add(s['low_name'])

                if final_recs:
                    st.success(f"Analysis Complete: {len(final_recs)} fleet rotations recommended.")
                    
                    # Clean display table
                    ui_df = pd.DataFrame(final_recs).rename(columns={
                        "high_name": "High Mileage Asset",
                        "low_name": "Low Mileage Asset",
                        "miles_over": "Monthly Overage",
                        "miles_under": "Monthly Capacity Available",
                        "swap_dist_val": "Swap Distance"
                    })

                    st.table(ui_df[[
                        "High Mileage Asset", 
                        "Low Mileage Asset", 
                        "Monthly Overage", 
                        "Monthly Capacity Available", 
                        "Swap Distance", 
                        "Rotation Strategy"
                    ]])
                else:
                    st.info("No viable rotations found with current constraints.")
                            
            except Exception as e:
                st.error(f"Analysis Error: {e}")

st.divider()

# --- BOTTOM SECTION: FLEET STATUS ---
st.write("### Current Fleet Status")
if 'df_display' in locals():
    st.dataframe(df_display, use_container_width=True, hide_index=True)

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

    # 2. FUZZY MAPPING: This fixes the "Missing Column" error by finding the best match
    def find_col(target):
        for c in df.columns:
            if target.lower() in c.lower():
                return c
        return None

    # Map your required columns to whatever they are actually named in Smartsheet
    col_map = {
        "projected": find_col("Monthly Projected"),
        "allowance": find_col("Monthly Allowance"),
        "priority": find_col("Rotation Priority"),
        "tier": find_col("Utilization Tier"),
        "actual": find_col("Monthly Miles Actual"),
        "trend": find_col("Weekly Trend"),
        "name": find_col("Vehicle Name"),
        "loc": find_col("Current Location"),
        "desc": find_col("Vehicle Description")
    }

    # Internal ID mapping for potential Smartsheet updates
    df['row_id_internal'] = [row.id for row in sheet.rows]

    # 3. DISPLAY FILTERING
    # Only show the specific columns you requested
    display_list = [col_map["name"], col_map["loc"], col_map["allowance"], 
                    col_map["projected"], col_map["actual"], col_map["trend"],
                    col_map["priority"], col_map["tier"]]
    
    # Filter out any None values if a column truly doesn't exist
    df_display = df[[c for c in display_list if c is not None]]

except Exception as e:
    st.error(f"Error loading Smartsheet: {e}")

# --- ACTION BUTTON ---
# (Keep your CSS block here)
run_analysis = st.button("RUN FLEET ROTATION ANALYSIS")

if run_analysis:
    if 'df' not in locals():
        st.error("Data not found.")
    else:
        with st.spinner("Processing analysis..."):
            # Check if critical math columns were found
            if not col_map["projected"] or not col_map["allowance"]:
                st.error(f"Could not find 'Monthly Projected' or 'Monthly Allowance' in your sheet. Headers found: {list(df.columns)}")
            else:
                try:
                    # Filter using the mapped names
                    recipients = df[df[col_map["priority"]].str.contains('URGENT', na=False, case=False)]
                    donors = df[df[col_map["tier"]].str.contains('UNDERUSED', na=False, case=False)]

                    possible_swaps = []
                    for _, rec in recipients.iterrows():
                        for _, don in donors.iterrows():
                            if rec[col_map["desc"]] != don[col_map["desc"]]:
                                continue

                            dist = get_distance_miles(rec[col_map["loc"]], don[col_map["loc"]])
                            if dist > max_dist:
                                continue
                            
                            # Math using mapped names
                            rec_delta = float(rec[col_map["projected"]] or 0) - float(rec[col_map["allowance"]] or 0)
                            don_delta = float(don[col_map["projected"]] or 0) - float(don[col_map["allowance"]] or 0)
                            
                            score = ((rec_delta - don_delta) * 0.7) - ((dist ** 1.5) * 0.1)
                            
                            possible_swaps.append({
                                "score": score,
                                "rec_name": rec[col_map["name"]],
                                "don_name": don[col_map["name"]],
                                "distance": dist,
                                "summary": f"Swap {rec[col_map['name']]} (+{int(rec_delta)} mi) with {don[col_map['name']]} ({int(don_delta)} mi)"
                            })

                    sorted_swaps = sorted(possible_swaps, key=lambda x: x['score'], reverse=True)
                    # ... rest of your display/AI logic ...
                    final_recs = []
                    used_vehicles = set()

                    for s in sorted_swaps:
                        if s['rec_name'] not in used_vehicles and s['don_name'] not in used_vehicles:
                            prompt = f"Rationale for swap: {s['summary']} over {s['distance']:.1f} miles."
                            try:
                                response = model.generate_content(prompt)
                                s['ai_rationale'] = response.text
                            except:
                                s['ai_rationale'] = "Optimizes lease distribution."

                            final_recs.append(s)
                            used_vehicles.add(s['rec_name'])
                            used_vehicles.add(s['don_name'])

                    if final_recs:
                        st.success(f"Analysis Complete: {len(final_recs)} swaps identified.")
                        st.table(pd.DataFrame(final_recs)[["summary", "distance", "ai_rationale"]])
                    else:
                        st.info("No viable swaps found.")
                    
            except Exception as e:
                st.error(f"An error occurred during analysis: {e}")

st.divider()

# --- BOTTOM SECTION: FLEET STATUS ---
st.write("### Current Fleet Status")
if 'df_display' in locals():
    # use_container_width handles the even spacing across the screen
    st.dataframe(df_display, use_container_width=True, hide_index=True)

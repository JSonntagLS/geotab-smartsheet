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
    df.columns = df.columns.str.strip() 
    
    # Internal mapping for potential Smartsheet updates
    df['row_id_internal'] = [row.id for row in sheet.rows]

    # FETCH RELEVANT COLUMNS
    display_cols = [
        "Vehicle Name", "Current Location", "Monthly Allowance", 
        "Monthly Projected", "Monthly Miles Actual", "Weekly Trend",
        "Rotation Priority", "Utilization Tier"
    ]
    df_display = df[[c for c in display_cols if c in df.columns]]

except Exception as e:
    st.error(f"Error loading Smartsheet: {e}")

# --- TOP SECTION: ACTION BUTTON ---
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
        with st.spinner("Processing analysis..."):
            try:
                # Column check to prevent KeyError
                required = ['Rotation Priority', 'Utilization Tier', 'Monthly Projected', 'Monthly Allowance']
                missing = [r for r in required if r not in df.columns]
                
                if missing:
                    st.error(f"Missing columns in Smartsheet: {', '.join(missing)}")
                else:
                    recipients = df[df['Rotation Priority'].str.contains('URGENT', na=False, case=False)]
                    donors = df[df['Utilization Tier'].str.contains('UNDERUSED', na=False, case=False)]

                    possible_swaps = []
                    for _, rec in recipients.iterrows():
                        for _, don in donors.iterrows():
                            if rec['Vehicle Description'] != don['Vehicle Description']:
                                continue

                            dist = get_distance_miles(rec['Current Location'], don['Current Location'])
                            if dist > max_dist:
                                continue
                            
                            rec_delta = rec['Monthly Projected'] - rec['Monthly Allowance']
                            don_delta = don['Monthly Projected'] - don['Monthly Allowance']
                            
                            score = ((rec_delta - don_delta) * 0.7) - ((dist ** 1.5) * 0.1)
                            
                            possible_swaps.append({
                                "score": score,
                                "rec_name": rec['Vehicle Name'],
                                "don_name": don['Vehicle Name'],
                                "distance": dist,
                                "summary": f"Swap {rec['Vehicle Name']} (+{int(rec_delta)} mi) with {don['Vehicle Name']} ({int(don_delta)} mi)"
                            })

                    sorted_swaps = sorted(possible_swaps, key=lambda x: x['score'], reverse=True)
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

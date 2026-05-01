import streamlit as st
import smartsheet
import pandas as pd
from datetime import datetime
import math
import google.generativeai as genai
import re

# --- PAGE CONFIG ---
st.set_page_config(layout="wide")

# --- AI SETUP ---
genai.configure(api_key=st.secrets["gemini_api_key"])
model = genai.GenerativeModel('models/gemini-1.5-flash')

# --- MAPPINGS ---
col_map = {
    "projected": "Projected Monthly Usage",
    "allowance": "Monthly Allowance",
    "priority": "Rotation Priority",
    "tier": "Utilization Tier",
    "actual": "Monthly Miles Actual",
    "trend": "Weekly Trend",
    "name": "Vehicle Name",
    "loc": "Current Location",
    "desc": "Vehicle Description",
    "start": "Lease Start Date",
    "length": "Lease Length",
    "contract": "Total Contract Miles",
    "odo": "Current Odometer"
}

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

# --- HELPERS ---
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

def force_num(val, fallback=0.0):
    if val is None or str(val).strip().lower() in ["", "nan", "none"]: 
        return fallback
    cleaned = re.sub(r'[^0-9.]', '', str(val))
    try:
        return float(cleaned)
    except:
        return fallback

def calculate_runway(row):
    try:
        total_contract = force_num(row.get(col_map["contract"]), fallback=100000.0)
        current_odo = force_num(row.get(col_map["odo"]), fallback=0.0)
        miles_remaining = total_contract - current_odo
        
        start_date = pd.to_datetime(row.get(col_map["start"]), errors='coerce')
        raw_len = force_num(row.get(col_map["length"]), fallback=36.0)
        months_total = int(raw_len)
        
        if pd.isnat(start_date):
            return int(miles_remaining), 12 
            
        end_date = start_date + pd.offsets.DateOffset(months=months_total)
        today = datetime.now()
        months_remaining = (end_date.year - today.year) * 12 + (end_date.month - today.month)
        
        return int(miles_remaining), max(1, int(months_remaining))
    except:
        return 0, 1

# --- DATA LOADING ---
try:
    smart = smartsheet.Smartsheet(st.secrets["smartsheet_token"])
    sheet = smart.Sheets.get_sheet(st.secrets["sheet_id"])
    columns = [col.title.strip() for col in sheet.columns]
    rows = [[cell.value for cell in row.cells] for row in sheet.rows]
    df = pd.DataFrame(rows, columns=columns)

    df_display = df[[
        col_map["name"], col_map["loc"], col_map["allowance"], 
        col_map["projected"], col_map["actual"], col_map["priority"], col_map["tier"]
    ]]
except Exception as e:
    st.error(f"Error loading Smartsheet: {e}")

# --- SIDEBAR ---
max_dist = st.sidebar.slider("Max Allowable Swap Distance (Miles)", 20, 500, 200)

# --- ACTION ---
run_analysis = st.button("RUN FLEET ROTATION ANALYSIS")

if run_analysis:
    if 'df' not in locals():
        st.error("Data not found.")
    else:
        with st.spinner("Analyzing trajectories..."):
            try:
                high_usage_assets = df[df[col_map["priority"]].astype(str).str.contains('URGENT', na=False, case=False)]
                low_usage_assets = df[df[col_map["tier"]].astype(str).str.contains('UNDERUSED', na=False, case=False)]

                possible_swaps = []
                for _, high_v in high_usage_assets.iterrows():
                    for _, low_v in low_usage_assets.iterrows():
                        if high_v[col_map["desc"]] != low_v[col_map["desc"]]:
                            continue

                        dist = get_distance_miles(high_v[col_map["loc"]], low_v[col_map["loc"]])
                        if dist > max_dist: continue
                        
                        h_proj = force_num(high_v[col_map["projected"]])
                        h_allow = force_num(high_v[col_map["allowance"]])
                        l_proj = force_num(low_v[col_map["projected"]])
                        l_allow = force_num(low_v[col_map["allowance"]])
                        
                        high_delta = h_proj - h_allow
                        low_delta = l_proj - l_allow
                        score = ((high_delta - low_delta) * 0.7) - ((dist ** 1.5) * 0.1)
                        
                        h_miles, h_months = calculate_runway(high_v)
                        l_miles, l_months = calculate_runway(low_v)

                        possible_swaps.append({
                            "score": score,
                            "high_name": high_v[col_map["name"]],
                            "low_name": low_v[col_map["name"]],
                            "over_pacing": int(high_delta),
                            "wasted_miles": int(abs(low_delta)),
                            "swap_dist": f"{dist:.1f} miles",
                            "h_data": {"m": h_miles, "mo": h_months},
                            "l_data": {"m": l_miles, "mo": l_months}
                        })

                sorted_swaps = sorted(possible_swaps, key=lambda x: x['score'], reverse=True)
                final_recs = []
                used_vehicles = set()

                for s in sorted_swaps:
                        # Revised Prompt and Logic for Lease Lifecycle
                        l_miles_left = s['l_data']['m']
                        l_months_left = s['l_data']['mo']
                        h_pacing = s['over_pacing']

                        prompt = (
                            f"Vehicle A is over-pacing by {h_pacing} miles/month. "
                            f"Vehicle B has {l_miles_left} miles remaining and {l_months_left} months left on lease. "
                            f"If we swap them, will Vehicle B likely stay under its contract limit? "
                            f"Answer in 1-2 professional sentences."
                        )
                        
                        try:
                            # Using a more direct call structure to avoid the 404 resource path error
                            response = model.generate_content(
                                prompt,
                                generation_config={"tag_loss_weight": 0.0} # Optional: ensures clean text
                            )
                            s['Lease Lifecycle Projection'] = response.text.strip()
                        except Exception as e:
                            # Fallback to a manual calculation if the API remains unreachable
                            projected_total = h_pacing * l_months_left
                            if projected_total < l_miles_left:
                                s['Lease Lifecycle Projection'] = f"Manual Calc: Swap is viable. Est. use ({projected_total}) is under remaining cap ({l_miles_left})."
                            else:
                                s['Lease Lifecycle Projection'] = f"Manual Calc: Caution. Est. use ({projected_total}) may exceed cap ({l_miles_left})."

                if final_recs:
                    st.success(f"Analysis Complete.")
                    # Rename keys to professional UI headers
                    ui_df = pd.DataFrame(final_recs).rename(columns={
                        "high_name": "Over-Paced Vehicle",
                        "low_name": "Under-Used Vehicle",
                        "over_pacing": "Monthly Miles Over",
                        "wasted_miles": "Monthly Miles Wasted",
                        "swap_dist": "Swap Distance"
                    })
                    
                    # Ensure the list below matches the renamed columns exactly
                    st.table(ui_df[[
                        "Over-Paced Vehicle", 
                        "Under-Used Vehicle", 
                        "Monthly Miles Over", 
                        "Monthly Miles Wasted", 
                        "Swap Distance", 
                        "Lease Lifecycle Projection"
                    ]])
                else:
                    st.info("No viable rotations found.")
            except Exception as e:
                st.error(f"Rotation Logic Error: {e}")

st.divider()
st.write("### Current Fleet Status")
if 'df_display' in locals():
    st.dataframe(df_display, use_container_width=True, hide_index=True)

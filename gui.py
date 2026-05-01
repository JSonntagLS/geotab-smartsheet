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
genai.configure(api_key=st.secrets["gemini_api_key"], transport='rest')
model = genai.GenerativeModel('gemini-1.5-flash')

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

def calculate_runway(row):
    try:
        def force_num(val, fallback=0.0):
            if val is None or str(val).strip().lower() in ["", "nan", "none"]: 
                return fallback
            cleaned = re.sub(r'[^0-9.]', '', str(val))
            return float(cleaned) if cleaned else fallback

        # Use 100k and 25k as "Safe" defaults so the button doesn't break if Smartsheet is glitchy
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
    
    # Extract headers and clean them aggressively
    columns = [col.title.strip() for col in sheet.columns]
    rows = [[cell.value for cell in row.cells] for row in sheet.rows]
    df = pd.DataFrame(rows, columns=columns)

    # Diagnostic check: Are our keys actually in the dataframe?
    missing = [v for v in col_map.values() if v not in df.columns]
    if missing:
        st.error(f"Heads up: These columns aren't being found: {missing}")
        st.write("Available columns in your sheet:", list(df.columns))

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
                # Filtering logic
                high_usage_assets = df[df[col_map["priority"]].astype(str).str.contains('URGENT', na=False, case=False)]
                low_usage_assets = df[df[col_map["tier"]].astype(str).str.contains('UNDERUSED', na=False, case=False)]

                possible_swaps = []
                for _, high_v in high_usage_assets.iterrows():
                    for _, low_v in low_usage_assets.iterrows():
                        if high_v[col_map["desc"]] != low_v[col_map["desc"]]:
                            continue

                        dist = get_distance_miles(high_v[col_map["loc"]], low_v[col_map["loc"]])
                        if dist > max_dist: continue
                        
                        # Use force_num for deltas too
                        def quick_num(v):
                            cleaned = re.sub(r'[^0-9.]', '', str(v)) if v else "0"
                            return float(cleaned) if cleaned else 0.0

                        h_proj = quick_num(high_v[col_map["projected"]])
                        h_allow = quick_num(high_v[col_map["allowance"]])
                        l_proj = quick_num(low_v[col_map["projected"]])
                        l_allow = quick_num(low_v[col_map["allowance"]])
                        
                        high_delta = h_proj - h_allow
                        low_delta = l_proj - l_allow
                        score = ((high_delta - low_delta) * 0.7) - ((dist ** 1.5) * 0.1)
                        
                        h_miles, h_months = calculate_runway(high_v)
                        l_miles, l_months = calculate_runway(low_v)

                        # If the value is 0, we'll still add it to the list but note the data gap
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
                    if s['high_name'] not in used_vehicles and s['low_name'] not in used_vehicles:
                        prompt = (
                            f"Strategic Analysis for LifeServe Blood Center: "
                            f"Vehicle {s['high_name']} has {s['h_data']['m']} miles left for {s['h_data']['mo']} months, but is over-pacing by {s['over_pacing']} mi/month. "
                            f"Vehicle {s['low_name']} has {s['l_data']['m']} miles left for {s['l_data']['mo']} months, but is wasting {s['wasted_miles']} mi/month. "
                            f"Is this swap a permanent fix to hit the contract limit exactly? Explain briefly."
                        )
                        try:
                            response = model.generate_content(prompt)
                            s['Lease Lifecycle Projection'] = response.text.strip()
                        except:
                            s['Lease Lifecycle Projection'] = "Analysis unavailable."

                        final_recs.append(s)
                        used_vehicles.add(s['high_name'])
                        used_vehicles.add(s['low_name'])

                if final_recs:
                    st.success(f"Analysis Complete.")
                    ui_df = pd.DataFrame(final_recs).rename(columns={
                        "high_name": "Over-Paced Vehicle",
                        "low_name": "Under-Used Vehicle",
                        "over_pacing": "Monthly Miles Over Allowance",
                        "swap_dist": "Swap Distance"
                    })
                    st.table(ui_df[["Over-Paced Vehicle", "Under-Used Vehicle", "Monthly Miles Over Allowance", "Swap Distance", "Lease Lifecycle Projection"]])
                else:
                    st.info("No viable rotations found matching the criteria.")
            except Exception as e:
                st.error(f"Rotation Logic Error: {e}")

st.divider()
st.write("### Current Fleet Status")
if 'df_display' in locals():
    st.dataframe(df_display, use_container_width=True, hide_index=True)

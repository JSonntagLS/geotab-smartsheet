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

# --- DATA INSPECTOR (DEBUG ONLY) ---
st.write("### Data Integrity Check")
test_veh = "01 JOHNSTON PM 2026 CHRYSLER PACIFICA"
if test_veh in df[col_map["name"]].values:
    sample_row = df[df[col_map["name"]] == test_veh].iloc[0]
    st.json({
        "Contract Miles Raw": f"'{sample_row[col_map['contract']]}'",
        "Odometer Raw": f"'{sample_row[col_map['odo']]}'",
        "Start Date Raw": f"'{sample_row[col_map['start']]}'",
        "Contract Type": str(type(sample_row[col_map['contract']])),
        "Odo Type": str(type(sample_row[col_map['odo']]))
    })
else:
    st.warning("Could not find the test vehicle for debugging.")
    
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

    df_display = df[[
        col_map["name"], col_map["loc"], col_map["allowance"], 
        col_map["projected"], col_map["actual"], col_map["priority"], col_map["tier"]
    ]]

except Exception as e:
    st.error(f"Error loading Smartsheet: {e}")

# --- HELPER: LEASE RUNWAY ---
def calculate_runway(row):
    try:
        def to_float(val):
            if val is None or str(val).strip() == "": return 0.0
            if isinstance(val, str):
                val = val.replace(',', '').strip()
            try:
                return float(val)
            except:
                return 0.0

        # Extract values using the map
        total_contract = to_float(row.get(col_map["contract"]))
        current_odo = to_float(row.get(col_map["odo"]))
        
        # Calculate miles left
        miles_remaining = total_contract - current_odo
        
        # Date Handling
        raw_start = row.get(col_map["start"])
        start_date = pd.to_datetime(raw_start, errors='coerce')
        
        # Monthly Length
        raw_len = row.get(col_map["length"])
        months_total = int(to_float(raw_len)) if to_float(raw_len) > 0 else 36
        
        if pd.isnat(start_date):
            return int(miles_remaining), 12 # Fallback to 1 year left
            
        end_date = start_date + pd.offsets.DateOffset(months=months_total)
        today = datetime.now()
        
        # Calculate months remaining
        months_remaining = (end_date.year - today.year) * 12 + (end_date.month - today.month)
        
        # Ensure we don't return 0 for months or it breaks division logic in AI
        return int(miles_remaining), max(1, int(months_remaining))
    except Exception as e:
        return 0, 1

# --- ACTION ---
run_analysis = st.button("RUN FLEET ROTATION ANALYSIS")

if run_analysis:
    if 'df' not in locals():
        st.error("Data not found.")
    else:
        with st.spinner("Analyzing trajectories..."):
            try:
                # Use .get() to avoid KeyErrors
                high_usage_assets = df[df[col_map["priority"]].astype(str).str.contains('URGENT', na=False, case=False)]
                low_usage_assets = df[df[col_map["tier"]].astype(str).str.contains('UNDERUSED', na=False, case=False)]

                possible_swaps = []
                for _, high_v in high_usage_assets.iterrows():
                    for _, low_v in low_usage_assets.iterrows():
                        if high_v[col_map["desc"]] != low_v[col_map["desc"]]:
                            continue

                        dist = get_distance_miles(high_v[col_map["loc"]], low_v[col_map["loc"]])
                        if dist > max_dist: continue
                        
                        # Convert to numeric safely
                        h_proj = pd.to_numeric(high_v[col_map["projected"]], errors='coerce') or 0
                        h_allow = pd.to_numeric(high_v[col_map["allowance"]], errors='coerce') or 0
                        l_proj = pd.to_numeric(low_v[col_map["projected"]], errors='coerce') or 0
                        l_allow = pd.to_numeric(low_v[col_map["allowance"]], errors='coerce') or 0
                        
                        high_delta = float(h_proj - h_allow)
                        low_delta = float(l_proj - l_allow)
                        score = ((high_delta - low_delta) * 0.7) - ((dist ** 1.5) * 0.1)
                        
                        # Lifecycle Data
                        h_miles, h_months = calculate_runway(high_v)
                        l_miles, l_months = calculate_runway(low_v)
                        
                        # Only show warning if BOTH miles and months are 0 (true failure)
                        if h_miles <= 0 and h_months <= 1:
                            st.warning(f"Check Smartsheet data for {high_v[col_map['name']]}: Missing Lease Miles/Dates.")

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
                        # Only send to AI if we have real runway data
                        if s['h_data']['m'] > 0:
                            prompt = (
                                f"Analyze this vehicle swap for LifeServe Blood Center: "
                                f"Asset {s['high_name']} has {s['h_data']['m']} miles left on lease with {s['h_data']['mo']} months remaining. "
                                f"It is over-pacing by {s['over_pacing']} miles/month. "
                                f"Asset {s['low_name']} has {s['l_data']['m']} miles left with {s['l_data']['mo']} months remaining. "
                                f"Will this swap allow {s['high_name']} to finish the lease under its 100k limit? "
                                f"Provide a brief, professional projection of the end-of-lease state."
                            )
                            try:
                                response = model.generate_content(prompt)
                                s['Lease Lifecycle Projection'] = response.text.strip()
                            except:
                                s['Lease Lifecycle Projection'] = "AI Analysis failed."
                        else:
                            s['Lease Lifecycle Projection'] = "Insufficient lease data for projection."

                        final_recs.append(s)
                        used_vehicles.add(s['high_name'])
                        used_vehicles.add(s['low_name'])

                if final_recs:
                    st.success(f"Analysis Complete: {len(final_recs)} recommended rotations.")
                    ui_df = pd.DataFrame(final_recs).rename(columns={
                        "high_name": "Over-Paced Vehicle",
                        "low_name": "Under-Used Vehicle",
                        "over_pacing": "Monthly Miles Over Allowance",
                        "wasted_miles": "Monthly Miles Wasted",
                        "swap_dist": "Swap Distance"
                    })

                    st.table(ui_df[[
                        "Over-Paced Vehicle", "Under-Used Vehicle", 
                        "Monthly Miles Over Allowance", "Monthly Miles Wasted", 
                        "Swap Distance", "Lease Lifecycle Projection"
                    ]])
                else:
                    st.info("No viable rotations found.")
            except Exception as e:
                st.error(f"Error in calculation: {e}")

st.divider()
st.write("### Current Fleet Status")
if 'df_display' in locals():
    st.dataframe(df_display, use_container_width=True, hide_index=True)

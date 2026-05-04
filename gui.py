import streamlit as st
import smartsheet
import pandas as pd
from datetime import datetime
import math
import google.generativeai as genai
import re
import os

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
        raw_contract = force_num(row.get(col_map["contract"]))
        total_contract = raw_contract if raw_contract > 1000 else 100000.0
        current_odo = force_num(row.get(col_map["odo"]), fallback=0.0)
        miles_remaining = total_contract - current_odo
        start_date = pd.to_datetime(row.get(col_map["start"]), errors='coerce')
        raw_len = force_num(row.get(col_map["length"]), fallback=36.0)
        
        if pd.isnat(start_date):
            return int(miles_remaining), 12
            
        end_date = start_date + pd.offsets.DateOffset(months=int(raw_len))
        today = datetime.now()
        months_remaining = (end_date.year - today.year) * 12 + (end_date.month - today.month)
        
        return int(miles_remaining), max(1, int(months_remaining))
    except Exception:
        return 50000, 12

# --- DATA LOADING ---
try:
    smart = smartsheet.Smartsheet(st.secrets["smartsheet_token"])
    sheet = smart.Sheets.get_sheet(st.secrets["sheet_id"])
    columns = [col.title.strip() for col in sheet.columns]
    rows = [[cell.value for cell in row.cells] for row in sheet.rows]
    df = pd.DataFrame(rows, columns=columns)

    # DATA CLEANING: Clean all columns first
    for col_key in ["allowance", "projected", "actual", "odo"]:
        col = col_map[col_key]
        if col in df.columns:
            # Clean and convert to float first to handle decimals/errors safely
            df[col] = df[col].apply(lambda x: force_num(x))
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    
    # INDENTATION FIX: Move the display and int-casting OUTSIDE the loop above
    df_display = df[[
        col_map["name"], col_map["loc"], col_map["allowance"], 
        col_map["projected"], col_map["actual"], col_map["priority"], col_map["tier"]
    ]].copy()
    
    for col in [col_map["allowance"], col_map["projected"], col_map["actual"]]:
        # Now that we've used force_num, casting to int will not crash
        df_display[col] = df_display[col].astype(int)

except Exception as e:
    st.error(f"Error loading Smartsheet: {e}")

# --- DASHBOARD METRICS ---
if 'df' in locals():
    with st.container():
        m_cols = st.columns(7)
        labels = ["Highly Overused", "Moderately Overused", "Slightly Overused", "Balanced", "Slightly Underused", "Moderately Underused", "Highly Underused"]
        
        for i, col in enumerate(m_cols):
            label = labels[i]
            count = len(df[df[col_map["tier"]].astype(str).str.strip() == label])
            col.metric(label=label, value=count)

# --- USAGE HISTORY & ANALYSIS SECTION ---
col_btn, col_graph = st.columns([1, 2])

with col_btn:
    st.write("### Actions")
    run_analysis = st.button("RUN FLEET ROTATION ANALYSIS", use_container_width=True, key="fleet_rot_final")

with col_graph:
    if os.path.exists('usage_history.csv'):
        try:
            history_df = pd.read_csv('usage_history.csv')
            history_df['Date'] = pd.to_datetime(history_df['Date'])
            st.write("### Utilization Trends")
            g_col1, g_col2 = st.columns(2)
            with g_col1:
                selected_cat = st.selectbox("Select Category", labels)
            with g_col2:
                time_map = {"1 month": 30, "3 months": 90, "6 months": 180, "1 year": 365, "3 years": 1095}
                selected_time = st.selectbox("Timeframe", list(time_map.keys()))

            cutoff = datetime.now() - pd.Timedelta(days=time_map[selected_time])
            filtered = history_df[history_df['Date'] >= cutoff]
            
            if selected_cat in filtered.columns and not filtered.empty:
                st.bar_chart(filtered.set_index('Date')[selected_cat], height=250)
            else:
                st.info("No trend data for this selection.")
        except Exception:
            st.warning("Trend log busy or unavailable.")
    else:
        st.info("Usage history log will populate after the next automated sync.")

# --- SIDEBAR ---
max_dist = st.sidebar.slider("Max Allowable Swap Distance (Miles)", 20, 500, 200)

# --- ACTION EXECUTION ---
if run_analysis:
    if 'df' not in locals():
        st.error("Data not found.")
    else:
        with st.spinner("Analyzing trajectories..."):
            try:
                high_usage_assets = df[df[col_map["priority"]].astype(str).str.contains('URGENT|HIGH', na=False, case=False)]
                low_usage_assets = df[df[col_map["tier"]].astype(str).str.contains('UNDERUSED', na=False, case=False)]
                
                possible_swaps = []
                for _, high_v in high_usage_assets.iterrows():
                    for _, low_v in low_usage_assets.iterrows():
                        # Match by Description with Name fallback
                        h_desc = str(high_v.get(col_map["desc"], "")).strip().lower()
                        l_desc = str(low_v.get(col_map["desc"], "")).strip().lower()
                        
                        if not h_desc or h_desc == "none":
                            h_desc = "pacifica" if "PACIFICA" in str(high_v[col_map["name"]]).upper() else "rogue" if "ROGUE" in str(high_v[col_map["name"]]).upper() else "voyager"
                        if not l_desc or l_desc == "none":
                            l_desc = "pacifica" if "PACIFICA" in str(low_v[col_map["name"]]).upper() else "rogue" if "ROGUE" in str(low_v[col_map["name"]]).upper() else "voyager"

                        if h_desc != l_desc: continue

                        dist = get_distance_miles(high_v[col_map["loc"]], low_v[col_map["loc"]])
                        if dist > max_dist: continue
                        
                        h_proj, h_allow = force_num(high_v[col_map["projected"]]), force_num(high_v[col_map["allowance"]])
                        l_proj, l_allow = force_num(low_v[col_map["projected"]]), force_num(low_v[col_map["allowance"]])
                        
                        high_delta = h_proj - h_allow
                        low_delta = l_proj - l_allow
                        
                        # If projected is 0 due to a Smartsheet error, we calculate delta based on Actual miles instead
                        if h_proj == 0:
                            high_delta = force_num(high_v[col_map["actual"]]) - h_allow
                        else:
                            high_delta = h_proj - h_allow
                        
                        # Only skip if the vehicle is truly under the allowance
                        if high_delta <= 0: 
                            continue

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
                    if s['high_name'] not in used_vehicles and s['low_name'] not in used_vehicles:
                        l_miles_left, l_months_left = s['l_data']['m'], s['l_data']['mo']
                        h_pacing_monthly = s['over_pacing']
                        projected_total_needed = h_pacing_monthly * l_months_left
                        
                        # Calculate specific dates
                        today = datetime.now()
                        months_until_over = int(l_miles_left / max(1, h_pacing_monthly))
                        runway_end_date = today + pd.offsets.DateOffset(months=months_until_over)
                        
                        date_str = f"{today.strftime('%b %y')} to {runway_end_date.strftime('%b %y')}"
                        est_end_odo = int(force_num(low_v[col_map["odo"]]) + (h_pacing_monthly * l_months_left))

                        # --- CATEGORIZATION LOGIC (Updated for Unique Row Data) ---
                        # Pull data specifically for the current 'high_v' and 'low_v' pair
                        odo_A = force_num(high_v[col_map["odo"]])
                        odo_B = force_num(low_v[col_map["odo"]])
                        
                        # Use Projected if it exists, otherwise use Actual
                        route_A = force_num(high_v[col_map["projected"]]) if force_num(high_v[col_map["projected"]]) > 0 else force_num(high_v[col_map["actual"]])
                        route_B = force_num(low_v[col_map["projected"]]) if force_num(low_v[col_map["projected"]]) > 0 else force_num(low_v[col_map["actual"]])

                        _, months_rem_A = calculate_runway(high_v)
                        _, months_rem_B = calculate_runway(low_v)

                        # Logic: Vehicle B takes Route A | Vehicle A takes Route B
                        proj_end_odo_B = odo_B + (route_A * months_rem_B)
                        proj_end_odo_A = odo_A + (route_B * months_rem_A)

                        def get_status_label(miles):
                            if miles > 105000: return "🔴 OVER"
                            if miles < 85000: return "🔵 UNDER"
                            return "🟢 IDEAL"

                        # Create the two separate status strings
                        s['Over-Paced Post-Swap'] = f"{proj_end_odo_A:,.0f} ({get_status_label(proj_end_odo_A)})"
                        s['Under-Used Post-Swap'] = f"{proj_end_odo_B:,.0f} ({get_status_label(proj_end_odo_B)})"

                        final_recs.append(s)
                        used_vehicles.add(s['high_name'])
                        used_vehicles.add(s['low_name'])

                # --- UPDATED DISPLAY SECTION ---
                if final_recs:
                    st.write("### Recommended Swaps: Lifecycle Projections")
                    rec_df = pd.DataFrame(final_recs)
                    
                    # Select and Rename columns for a clean table layout
                    display_cols = {
                        "high_name": "Over-Paced Vehicle",
                        "low_name": "Under-Used Vehicle",
                        "swap_dist": "Distance",
                        "Over-Paced Post-Swap": "Proj. End (Current High-Use Asset)",
                        "Under-Used Post-Swap": "Proj. End (Current Low-Use Asset)"
                    }
                    
                    st.dataframe(
                        rec_df[list(display_cols.keys())].rename(columns=display_cols),
                        use_container_width=True,
                        hide_index=True
                    )
                else:
                    st.info("No viable swaps found within current constraints.")

            except Exception as e:
                st.error(f"Analysis Error: {e}")

st.divider()
st.write("### Current Fleet Status")
if 'df_display' in locals():
    st.dataframe(df_display, use_container_width=True, hide_index=True)

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
st.title("Fleet Management System")

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
df_display = pd.DataFrame() # Initialize as empty
labels = ["Highly Overused", "Moderately Overused", "Slightly Overused", "Balanced", "Slightly Underused", "Moderately Underused", "Highly Underused"]

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

# --- TAB SETUP ---
tab_rotation, tab_oil, tab_lease = st.tabs([
    "Fleet Rotation Analysis", 
    "Oil Changes", 
    "New Lease Analysis"
])

with tab_rotation:
    st.header("Fleet Rotation Analysis")
    # Everything below this line in your script now belongs inside this 'with' block

    # --- DASHBOARD METRICS ---
    if 'df' in locals():
        with st.container():
            m_cols = st.columns(7)
            labels = ["Highly Overused", "Moderately Overused", "Slightly Overused", "Balanced", "Slightly Underused", "Moderately Underused", "Highly Underused"]
            
            for i, col in enumerate(m_cols):
                label = labels[i]
                if not df.empty and col_map["tier"] in df.columns:
                    count = len(df[df[col_map["tier"]].astype(str).str.strip() == label])
                else:
                    count = 0
                col.metric(label=label, value=count)

    # --- USAGE HISTORY & ANALYSIS SECTION ---
    col_btn, col_graph = st.columns([1, 2])
    
    with col_btn:
        st.write("### Actions")
        run_analysis = st.button("RUN FLEET ROTATION ANALYSIS", use_container_width=True, key="fleet_rot_final")
        # New placement for the slider:
        max_dist = st.slider("Max Allowable Swap Distance (Miles)", 20, 500, 200, step=10)
    
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
                
                if not filtered.empty and selected_cat in filtered.columns:
                    # Check if the column actually has data to show
                    if filtered[selected_cat].sum() > 0:
                        st.bar_chart(filtered.set_index('Date')[selected_cat], height=250)
                    else:
                        st.info("No activity recorded for this category in the selected timeframe.")
                else:
                    st.info("Trend log found, but no data matches the current filters.")
            except Exception:
                st.warning("Trend log busy or unavailable.")
        else:
            st.info("Usage history log will populate after the next automated sync.")
    
    # --- ACTION EXECUTION ---
    if run_analysis:
        if 'df' not in locals():
            st.error("Data not found.")
        else:
            with st.spinner("Analyzing trajectories..."):
                try:
                    # 1. IDENTIFY ASSETS
                    high_usage_assets = df[df[col_map["priority"]].astype(str).str.contains('URGENT|HIGH', na=False, case=False)]
                    low_usage_assets = df[df[col_map["tier"]].astype(str).str.contains('UNDERUSED', na=False, case=False)]
                    
                    possible_swaps = []
                    for h_idx, high_row in high_usage_assets.iterrows():
                        # Calculate "Without-Swap" projection for the high-use asset first
                        # LOGIC INTEGRATION: Establish a 200-mile baseline for stationary vehicles
                        raw_route_A = force_num(high_row[col_map["projected"]]) if force_num(high_row[col_map["projected"]]) > 0 else force_num(high_row[col_map["actual"]])
                        route_A_baseline = max(raw_route_A, 200.0)
                        
                        _, months_rem_A = calculate_runway(high_row)
                        odo_A = force_num(high_row[col_map["odo"]])
                        without_swap_proj_A = odo_A + (route_A_baseline * months_rem_A)
    
                        # GATEKEEPER: If it's already under 103,000 miles, leave it alone!
                        if without_swap_proj_A <= 103000:
                            continue 
    
                        for l_idx, low_row in low_usage_assets.iterrows():
                            h_desc = str(high_row.get(col_map["desc"], "")).strip().lower()
                            l_desc = str(low_row.get(col_map["desc"], "")).strip().lower()
                            if h_desc != l_desc: continue
    
                            dist = get_distance_miles(high_row[col_map["loc"]], low_row[col_map["loc"]])
                            if dist > max_dist: continue
                            
                            # 2. CAPTURE UNIQUE ROW DATA & APPLY BASELINES
                            odo_B = force_num(low_row[col_map["odo"]])
                            
                            raw_route_B = force_num(low_row[col_map["projected"]]) if force_num(low_row[col_map["projected"]]) > 0 else force_num(low_row[col_map["actual"]])
                            route_B_baseline = max(raw_route_B, 200.0)
                            
                            _, months_rem_B = calculate_runway(low_row)
    
                            # 3. CALCULATE SWAP PROJECTIONS
                            # A gets B's route, B gets A's route
                            proj_A = odo_A + (route_B_baseline * months_rem_A)
                            proj_B = odo_B + (route_A_baseline * months_rem_B)
    
                            # 4. SCORING
                            score = ((route_A_baseline - route_B_baseline) * 0.7) - ((dist ** 1.5) * 0.1)
    
                            possible_swaps.append({
                                "score": score,
                                "h_name": high_row[col_map["name"]],
                                "l_name": low_row[col_map["name"]],
                                "dist": f"{dist:.1f} miles",
                                "data_A": {"odo": odo_A, "route": route_B_baseline, "months": months_rem_A, "proj": proj_A},
                                "data_B": {"odo": odo_B, "route": route_A_baseline, "months": months_rem_B, "proj": proj_B}
                            })
    
                    # 5. SORT AND DEDUPLICATE
                    sorted_swaps = sorted(possible_swaps, key=lambda x: x['score'], reverse=True)
                    final_recs = []
                    used_vehicles = set()
    
                    # Define helper function within the analysis block scope
                    def format_projection(proj_val, current_odo, route_val):
                        # Check if we are using the baseline floor
                        is_stationary = route_val <= 200.0
                        
                        if proj_val > 105000:
                            miles_to_go = 105000 - current_odo
                            if route_val > 0:
                                months_until = max(0, miles_to_go / route_val)
                                time_text = f"Hits limit in {months_until:.1f} months"
                            else:
                                time_text = "No usage detected"
                            return f"🔴 OVER: {proj_val:,.0f} mi ({time_text})"
                        
                        elif proj_val < 85000:
                            status_text = "🔵 UNDER"
                            if is_stationary:
                                return f"{status_text}: {proj_val:,.0f} mi (Minimal Usage)"
                            return f"{status_text}: {proj_val:,.0f} mi"
                            
                        return f"🟢 IDEAL: {proj_val:,.0f} mi"
    
                    for s in sorted_swaps:
                        if s['h_name'] not in used_vehicles and s['l_name'] not in used_vehicles:
                            
                            # Calculate "Without Swap" projections using their OWN current routes
                            # High-Use Original Route = route_A (from the logic above)
                            # Low-Use Original Route = route_B (from the logic above)
                            orig_proj_A = s['data_A']['odo'] + (force_num(high_usage_assets.loc[high_usage_assets[col_map["name"]] == s['h_name'], col_map["projected"]].values[0]) * s['data_A']['months'])
                            orig_proj_B = s['data_B']['odo'] + (force_num(low_usage_assets.loc[low_usage_assets[col_map["name"]] == s['l_name'], col_map["projected"]].values[0]) * s['data_B']['months'])
    
                            raw_proj_A = force_num(df.loc[df[col_map['name']]==s['h_name'], col_map['projected']].iloc[0])
                            route_A_final = max(raw_proj_A, 200.0)
                            without_swap_A = s['data_A']['odo'] + (route_A_final * s['data_A']['months'])
    
                            raw_proj_B = force_num(df.loc[df[col_map['name']]==s['l_name'], col_map['projected']].iloc[0])
                            route_B_final = max(raw_proj_B, 200.0)
                            without_swap_B = s['data_B']['odo'] + (route_B_final * s['data_B']['months'])
    
                            final_recs.append({
                                "Over-Paced Vehicle": s['h_name'],
                                "Under-Used Vehicle": s['l_name'],
                                "Distance": s['dist'],
                                "Without-Swap: Current High-Use Asset": format_projection(
                                    without_swap_A, s['data_A']['odo'], route_A_final
                                ),
                                "Post-Swap: Current High-Use Asset": format_projection(
                                    s['data_A']['proj'], s['data_A']['odo'], s['data_A']['route']
                                ),
                                "Without-Swap: Current Low-Use Asset": format_projection(
                                    without_swap_B, s['data_B']['odo'], route_B_final
                                ),
                                "Post-Swap: Current Low-Use Asset": format_projection(
                                    s['data_B']['proj'], s['data_B']['odo'], s['data_B']['route']
                                )
                            })
                            used_vehicles.add(s['h_name'])
                            used_vehicles.add(s['l_name'])
    
                    # 6. DISPLAY RESULTS
                    if final_recs:
                        st.write("### Fleet Rotation Analysis")
                        st.table(pd.DataFrame(final_recs))
                    else:
                        st.info("No matching swaps found within constraints.")
    
                except Exception as e:
                    st.error(f"Rotation Analysis Error: {e}")
    st.divider()
    st.write("### Current Fleet Status")
    if 'df_display' in locals():
        st.dataframe(df_display, use_container_width=True, hide_index=True)

# --- NEW BLANK TABS ---
with tab_oil:
    st.header("Oil Change Management")
    st.info("Tracking logic for oil changes will be placed here.")

with tab_lease:
    st.header("New Lease Analysis")
    st.info("Analysis logic for new leases will be placed here.")

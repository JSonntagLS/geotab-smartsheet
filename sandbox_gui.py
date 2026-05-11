import streamlit as st
import smartsheet
import pandas as pd
from datetime import datetime
import math
import google.generativeai as genai
import re
import os
import requests

@st.cache_data(ttl=3600)  # Caches results for 1 hour to prevent 30-second lag
def check_vehicle_recall(make, model, year):
    try:
        # Using the specific 'recallsByVehicle' endpoint which avoids the Auth Token error
        url = f"https://api.nhtsa.gov/recalls/recallsByVehicle?make={make}&model={model}&modelYear={year}"
        res = requests.get(url, timeout=10).json()
        return res.get('results', [])
    except Exception:
        return []

# --- PAGE CONFIG ---
st.set_page_config(layout="wide")
# Main title removed to shift content up

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
    "odo": "Current Odometer",
    "last_oil": "Mileage of Last Oil Change",
    "next_oil": "Mileage of Next Oil Change",
    "interval": "Miles Between Oil Changes",
    "status": "GPS Status",
    "battery": "Battery Status"
}

# Smartsheet Column IDs for Updates
OIL_COL_IDS = {
    "last_oil": 6747473612935044,
    "next_oil": 4495673799249796,
    "interval": 7596742668488580,
    "odo": 8905895049465732,
    "name": 6654095235780484,
    "last_service_date": 8061461955121028    
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

def force_num(val, fallback=None):
    if val is None:
        return fallback
    # Convert to string and clean
    s_val = str(val).strip().lower()
    if s_val in ["", "nan", "none", "n/a"]: 
        return None  # This is the key change
    cleaned = re.sub(r'[^0-9.]', '', s_val)
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

def seed_fixed_recalls(fleet_df, active_csv_path, fixed_csv_path):
    st.info("Starting Scan... checking NHTSA API.")
    active_keys = set()
    try:
        if os.path.exists(active_csv_path):
            active_df = pd.read_csv(active_csv_path)
            active_keys = set(active_df['VIN'].astype(str).str.strip() + active_df['Campaign'].astype(str).str.strip())
        else:
            st.warning(f"Note: {active_csv_path} not found. Proceeding with full fleet scan.")
            active_keys = set() # Empty set so nothing is skipped
    except Exception as e:
        st.info("Active list check skipped; proceeding with full scan.")
        active_keys = set()

    fixed_history = []
    # Using a subset for the scan to speed up debugging if needed
    for _, row in fleet_df.iterrows():
        vin = str(row.get('VIN', '')).strip()
        if len(vin) == 17:
            try:
                # Basic spec decode
                vpic_url = f"https://vpic.nhtsa.dot.gov/api/vehicles/decodevinvalues/{vin}?format=json"
                res = requests.get(vpic_url, timeout=5).json()
                specs = res['Results'][0]
                
                recalls = check_vehicle_recall(specs.get('Make'), specs.get('Model'), specs.get('ModelYear'))
                for r in recalls:
                    camp_id = str(r.get('NHTSACampaignNumber', '')).strip()
                    if (vin + camp_id) not in active_keys:
                        fixed_history.append({"VIN": vin, "CampaignID": camp_id})
            except:
                continue

    if fixed_history:
        debug_df = pd.DataFrame(fixed_history)
        st.write(f"DEBUG: Attempting to save {len(debug_df)} items to {fixed_csv_path}")
        
        try:
            # 1. Clean data
            debug_df = debug_df.drop_duplicates()
            
            # 2. Force Write
            debug_df.to_csv(fixed_csv_path, index=False)
            
            # 3. VERIFICATION: Immediately try to read it back
            if os.path.exists(fixed_csv_path):
                check_size = os.path.getsize(fixed_csv_path)
                if check_size > 0:
                    st.write(f"DEBUG: File verified on disk ({check_size} bytes)")
                    return len(debug_df)
                else:
                    st.error("FATAL: File exists but is 0 bytes. Check folder permissions.")
            else:
                st.error("FATAL: to_csv command finished but file was not found on disk.")
                
            return 0
        except Exception as e:
            st.error(f"HARD WRITE FAILURE: {e}")
            return 0
    else:
        st.warning("Scan finished, but 0 historical recalls were found.")
        return 0

def sync_master_recall_file(fleet_df, enterprise_path, fixed_path):
    """
    Checks NHTSA for every VIN in the fleet and updates the master CSV.
    """
    new_active_list = []
    
    # Check fixed history
    try:
        fixed_df = pd.read_csv(fixed_path)
        fixed_keys = set(fixed_df['VIN'].astype(str).str.strip() + fixed_df['CampaignID'].astype(str).str.strip())
    except Exception:
        fixed_keys = set()

    for _, row in fleet_df.iterrows():
        vin = str(row.get('VIN', '')).strip()
        v_name = row.get(col_map["name"], "Unknown")
        
        if len(vin) == 17:
            try:
                # Decode VIN to get Make/Model/Year
                vpic_url = f"https://vpic.nhtsa.dot.gov/api/vehicles/decodevinvalues/{vin}?format=json"
                res = requests.get(vpic_url, timeout=5).json()
                specs = res['Results'] if res['Results'] else {}
                
                # Check NHTSA for recalls
                recalls = check_vehicle_recall(specs.get('Make'), specs.get('Model'), specs.get('ModelYear'))
                for r in recalls:
                    camp_id = str(r.get('NHTSACampaignNumber', r.get('NHTSACampaignNumber', ''))).strip()
                    if (vin + camp_id) not in fixed_keys:
                        new_active_list.append({
                            "Vehicle": v_name,
                            "VIN": vin,
                            "Campaign": camp_id,
                            "Campaign Description": r.get('Summary', 'No description available.')
                        })
            except Exception:
                continue

    # Update the master file
    updated_df = pd.DataFrame(new_active_list)
    updated_df.to_csv(enterprise_path, index=False)
    
    return len(new_active_list)

# --- DATA LOADING ---
df_display = pd.DataFrame() # Initialize as empty
labels = ["Highly Overused", "Moderately Overused", "Slightly Overused", "Balanced", "Slightly Underused", "Moderately Underused", "Highly Underused"]

if 'df' not in st.session_state:
    try:
        smart = smartsheet.Smartsheet(st.secrets["smartsheet_token"])
        sheet = smart.Sheets.get_sheet(st.secrets["sheet_id"])
        columns = [col.title.strip() if col.title else f"Unknown_{i}" for i, col in enumerate(sheet.columns)]
        rows = []
        for row in sheet.rows:
            row_data = [cell.value for cell in row.cells]
            row_data.append(row.id)
            rows.append(row_data)
        
        # Save directly to session state
        st.session_state.df = pd.DataFrame(rows, columns=columns + ["row_id"])
    except Exception as e:
        st.error(f"Error loading Smartsheet: {e}")

# Always point 'df' to the session state version
df = st.session_state.get('df', pd.DataFrame())

    date_col_title = next((col.title for col in sheet.columns if col.id == OIL_COL_IDS["last_service_date"]), None)
    # If found, rename it to a friendly key for the rest of the script
    if date_col_title:
        df = df.rename(columns={date_col_title: "Date of Last Oil Change"})
    
    # --- NEW: Map the Date ID to the actual Column Title ---
    date_col_title = next((col.title for col in sheet.columns if col.id == OIL_COL_IDS["last_service_date"]), None)
    # If found, rename it to a friendly key for the rest of the script
    if date_col_title:
        df = df.rename(columns={date_col_title: "Date of Last Oil Change"})
    
    # DATA CLEANING: Clean all columns
    for col_key in ["allowance", "projected", "actual", "odo", "last_oil", "next_oil", "interval"]:
        if col_key in col_map:
            col = col_map[col_key]
            if col in df.columns:
                df[col] = df[col].apply(lambda x: force_num(x))
                # CHANGE: Only fill with 0 for columns that AREN'T the service history
                if col_key != "last_oil":
                    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
                else:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
    
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

# --- SIDEBAR NAVIGATION & CUSTOM UI ---
# Tight two-line title
st.sidebar.markdown("### LifeServe<br>Fleet Management", unsafe_allow_html=True)

# Initialize state
if 'active_page' not in st.session_state:
    st.session_state.active_page = "Fleet Rotation Analysis"

# Using link-style buttons to get the clean text-only look
if st.sidebar.button("Fleet Rotation Analysis", type="secondary", use_container_width=True, key="btn_rot"):
    st.session_state.active_page = "Fleet Rotation Analysis"

if st.sidebar.button("Oil Changes", type="secondary", use_container_width=True, key="btn_oil"):
    st.session_state.active_page = "Oil Changes"

if st.sidebar.button("GPS and Battery Health", type="secondary", use_container_width=True, key="btn_gps"):
    st.session_state.active_page = "GPS and Battery Health"

if st.sidebar.button("Recalls", type="secondary", use_container_width=True, key="btn_recall"):
    st.session_state.active_page = "Recalls"

st.sidebar.divider()

# --- PAGE ROUTING ---
current_page = st.session_state.active_page

if current_page == "Fleet Rotation Analysis":
    st.title("Fleet Rotation Analysis")
    
    # --- DASHBOARD METRICS ---
    if 'df' in locals() and not df.empty:
        m_cols = st.columns(7)
        labels = ["Highly Overused", "Moderately Overused", "Slightly Overused", "Balanced", "Slightly Underused", "Moderately Underused", "Highly Underused"]
        
        for i, col in enumerate(m_cols):
            label = labels[i]
            if col_map["tier"] in df.columns:
                count_val = int(len(df[df[col_map["tier"]].astype(str).str.strip() == label]))
            else:
                count_val = 0
            col.metric(label=label, value=count_val)
        
        st.divider()

        # --- ACTIONS & GRAPH SECTION ---
        col_btn, col_graph = st.columns([1, 2])
        
        with col_btn:
            st.write("### Actions")
            run_analysis = st.button("RUN FLEET ROTATION ANALYSIS", use_container_width=True, key="fleet_rot_final")
            max_dist = st.slider("Max Allowable Swap Distance (Miles)", 20, 500, 200, step=10)
        
        with col_graph:
            if os.path.exists('usage_history.csv'):
                try:
                    history_df = pd.read_csv('usage_history.csv')
                    history_df['Date'] = pd.to_datetime(history_df['Date'])
                    st.write("### Utilization Trends")
                    g_col1, g_col2 = st.columns(2)
                    with g_col1:
                        selected_cat = st.selectbox("Select Category", labels, key="trend_cat")
                    with g_col2:
                        time_map = {"1 month": 30, "3 months": 90, "6 months": 180, "1 year": 365, "3 years": 1095}
                        selected_time = st.selectbox("Timeframe", list(time_map.keys()), key="trend_time")
        
                    cutoff = datetime.now() - pd.Timedelta(days=time_map[selected_time])
                    filtered = history_df[history_df['Date'] >= cutoff]
                    
                    if not filtered.empty and selected_cat in filtered.columns:
                        if filtered[selected_cat].sum() > 0:
                            st.bar_chart(filtered.set_index('Date')[selected_cat], height=250)
                        else:
                            st.info("No activity recorded for this category.")
                except:
                    st.warning("Trend log busy.")
            else:
                st.info("Usage history log will populate after sync.")

        # --- ACTION EXECUTION ---
        if run_analysis:
            with st.spinner("Analyzing trajectories..."):
                try:
                    # 1. IDENTIFY ASSETS
                    high_usage_assets = df[df[col_map["priority"]].astype(str).str.contains('URGENT|HIGH', na=False, case=False)]
                    low_usage_assets = df[df[col_map["tier"]].astype(str).str.contains('UNDERUSED', na=False, case=False)]
                    
                    possible_swaps = []
                    for h_idx, high_row in high_usage_assets.iterrows():
                        raw_route_A = force_num(high_row[col_map["projected"]]) if force_num(high_row[col_map["projected"]]) > 0 else force_num(high_row[col_map["actual"]])
                        route_A_baseline = max(raw_route_A, 200.0)
                        
                        _, months_rem_A = calculate_runway(high_row)
                        odo_A = force_num(high_row[col_map["odo"]])
                        without_swap_proj_A = odo_A + (route_A_baseline * months_rem_A)
    
                        if without_swap_proj_A <= 103000:
                            continue 
    
                        for l_idx, low_row in low_usage_assets.iterrows():
                            h_desc = str(high_row.get(col_map["desc"], "")).strip().lower()
                            l_desc = str(low_row.get(col_map["desc"], "")).strip().lower()
                            if h_desc != l_desc: continue
    
                            dist = get_distance_miles(high_row[col_map["loc"]], low_row[col_map["loc"]])
                            if dist > max_dist: continue
                            
                            odo_B = force_num(low_row[col_map["odo"]])
                            raw_route_B = force_num(low_row[col_map["projected"]]) if force_num(low_row[col_map["projected"]]) > 0 else force_num(low_row[col_map["actual"]])
                            route_B_baseline = max(raw_route_B, 200.0)
                            _, months_rem_B = calculate_runway(low_row)
    
                            proj_A = odo_A + (route_B_baseline * months_rem_A)
                            proj_B = odo_B + (route_A_baseline * months_rem_B)
                            score = ((route_A_baseline - route_B_baseline) * 0.7) - ((dist ** 1.5) * 0.1)
    
                            possible_swaps.append({
                                "score": score,
                                "h_name": high_row[col_map["name"]],
                                "l_name": low_row[col_map["name"]],
                                "dist": f"{dist:.1f} miles",
                                "data_A": {"odo": odo_A, "route_in": route_B_baseline, "route_out": route_A_baseline, "months": months_rem_A, "proj": proj_A, "orig_proj": without_swap_proj_A},
                                "data_B": {"odo": odo_B, "route_in": route_A_baseline, "route_out": route_B_baseline, "months": months_rem_B, "proj": proj_B, "orig_proj": odo_B + (route_B_baseline * months_rem_B)}
                            })
    
                    sorted_swaps = sorted(possible_swaps, key=lambda x: x['score'], reverse=True)
                    final_recs = []
                    used_vehicles = set()
    
                    def format_projection(proj_val, current_odo, route_val):
                        is_stationary = route_val <= 200.0
                        if proj_val > 105000:
                            miles_to_go = 105000 - current_odo
                            time_text = f"Hits limit in {max(0, miles_to_go / route_val):.1f} months" if route_val > 0 else "Hits limit in 0.0 months"
                            return f"🔴 OVER: {proj_val:,.0f} mi ({time_text})"
                        elif proj_val < 85000:
                            status_text = "🔵 UNDER"
                            if is_stationary:
                                return f"{status_text}: {proj_val:,.0f} mi (Minimal Usage)"
                            return f"{status_text}: {proj_val:,.0f} mi"
                        return f"🟢 IDEAL: {proj_val:,.0f} mi"
    
                    for s in sorted_swaps:
                        if s['h_name'] not in used_vehicles and s['l_name'] not in used_vehicles:
                            final_recs.append({
                                "Over-Paced Vehicle": s['h_name'],
                                "Under-Used Vehicle": s['l_name'],
                                "Distance": s['dist'],
                                "Without-Swap: Current High-Use Asset": format_projection(s['data_A']['orig_proj'], s['data_A']['odo'], s['data_A']['route_out']),
                                "Post-Swap: Current High-Use Asset": format_projection(s['data_A']['proj'], s['data_A']['odo'], s['data_A']['route_in']),
                                "Without-Swap: Current Low-Use Asset": format_projection(s['data_B']['orig_proj'], s['data_B']['odo'], s['data_B']['route_out']),
                                "Post-Swap: Current Low-Use Asset": format_projection(s['data_B']['proj'], s['data_B']['odo'], s['data_B']['route_in'])
                            })
                            used_vehicles.add(s['h_name'])
                            used_vehicles.add(s['l_name'])
    
                    if final_recs:
                        st.write("### Fleet Rotation Analysis")
                        st.table(pd.DataFrame(final_recs))
                    else:
                        st.info("No matching swaps found within constraints.")
    
                except Exception as e:
                    st.error(f"Rotation Analysis Error: {e}")

        st.divider()
        st.subheader("Asset Details")
        # Filter for specific columns requested
        rotation_cols = [
            col_map["name"], col_map["loc"], col_map["desc"], 
            col_map["odo"], col_map["actual"], col_map["projected"], 
            col_map["allowance"], col_map["trend"], col_map["priority"], col_map["tier"]
        ]
        # Only display columns that exist in the dataframe
        available_rot_cols = [c for c in rotation_cols if c in df.columns]
        st.dataframe(df[available_rot_cols], use_container_width=True, hide_index=True)
    else:
        st.warning("Smartsheet data not detected. Please ensure the data loading section is above this logic.")

elif current_page == "Oil Changes":
    st.title("Oil Change Management")
    
    if 'df' in locals() and not df.empty:
        # Fixed: Accessing the column we renamed during data loading
        df['Date of Last Oil Change'] = pd.to_datetime(df['Date of Last Oil Change'], errors='coerce')
        six_months_ago = pd.Timestamp.now() - pd.DateOffset(months=6)

        # Updated Filtering Logic:
        # 1. 6000 miles over next_oil (Implied by next_oil logic)
        # 2. Within 1000 of next_oil
        # 3. Over 6 months due (ONLY if date is known/not N/A)
        mask_due = (
            (df[col_map["next_oil"]].notnull() & (df[col_map["odo"]] >= (df[col_map["next_oil"]] - 1000))) | 
            ((df['Date of Last Oil Change'].notnull()) & (df['Date of Last Oil Change'] < six_months_ago))
        )
        
        # FILTER: Exclude rows where Last Date is N/A if they aren't triggered by mileage
        # This ensures 'N/A' dates don't clutter the service due list during initial rollout
        df_due = df[mask_due].copy()
        df_due = df_due[df_due['Date of Last Oil Change'].notnull()]
        
        if df_due.empty:
            st.success("All vehicles are up to date on oil changes!")
        else:
            st.write(f"### Vehicles Due for Service ({len(df_due)})")
            
            # Header Row
            # Header Row - Added Date Columns
            h_col1, h_col2, h_col3, h_col4, h_col5, h_col6, h_col7 = st.columns([2, 1, 1, 1, 1, 1, 1])
            h_col1.write("**Vehicle**")
            h_col2.write("**Current Odo**")
            h_col3.write("**Date of Last Service**")
            h_col4.write("**Next Service Due (Mi)**")
            h_col5.write("**New Odo at Service**")
            h_col6.write("**Date of New Service**")
            h_col7.write("**Action**")
            st.divider()

            for idx, row in df_due.iterrows():
                v_name = row[col_map["name"]]
                curr_odo = int(row[col_map["odo"]]) if pd.notnull(row[col_map["odo"]]) else 0
                next_due = int(row[col_map["next_oil"]]) if pd.notnull(row[col_map["next_oil"]]) else 0
                last_date = row['Date of Last Oil Change']
                # Surgical Fix: Cast row_id to string and handle potential NaNs
                row_id = str(int(row["row_id"])) if pd.notnull(row["row_id"]) else str(idx)
                
                r_col1, r_col2, r_col3, r_col4, r_col5, r_col6, r_col7 = st.columns([2, 1, 1, 1, 1, 1, 1])
                
                r_col1.write(v_name)
                r_col2.write(f"{curr_odo:,}")
                r_col3.write(last_date.strftime('%m/%d/%Y') if pd.notnull(last_date) else "N/A")
                r_col4.write(f"{next_due:,}")
                
                # New Service Odo - using the sanitized string row_id
                new_mileage = r_col5.text_input("Mileage", key=f"odo_{row_id}", label_visibility="collapsed", placeholder="Odo")
                
                # New Service Date - Set to US Format
                new_service_date = r_col6.date_input("Date", value=None, key=f"date_{row_id}", label_visibility="collapsed", format="MM/DD/YYYY")
                
                if r_col7.button("UPDATE", key=f"btn_{row_id}", use_container_width=True):
                    if new_mileage or new_service_date:
                        try:
                            new_row = smartsheet.models.Row()
                            new_row.id = int(row_id)
                            
                            # Logic: Only update fields that are NOT blank
                            if new_mileage:
                                cell_odo = smartsheet.models.Cell()
                                cell_odo.column_id = OIL_COL_IDS["last_oil"]
                                cell_odo.value = force_num(new_mileage)
                                new_row.cells.append(cell_odo)
                            
                            if new_service_date:
                                cell_date = smartsheet.models.Cell()
                                cell_date.column_id = OIL_COL_IDS["last_service_date"]
                                cell_date.value = new_service_date.strftime('%Y-%m-%d')
                                new_row.cells.append(cell_date)
                            
                            smart.Sheets.update_rows(st.secrets["sheet_id"], [new_row])
                            st.toast(f"Updated {v_name} successfully!", icon="✅")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed to update Smartsheet: {e}")
                    else:
                        st.warning("Enter data before updating.")
                st.divider()

        # 3. Full Fleet Oil Service Log Table
        st.subheader("Full Fleet Oil Service Log")
        oil_table_cols = [
            col_map["name"], 
            col_map["loc"], 
            col_map["odo"], 
            "Date of Last Oil Change", 
            col_map["last_oil"], 
            col_map["next_oil"], 
            col_map["interval"]
        ]
        
        # --- SURGICAL EDIT START: Format Date for Display ---
        available_oil_cols = [c for c in oil_table_cols if c in df.columns or c == "Date of Last Oil Change"]
        df_display_oil = df[available_oil_cols].copy()
        
        if "Date of Last Oil Change" in df_display_oil.columns:
            df_display_oil["Date of Last Oil Change"] = df_display_oil["Date of Last Oil Change"].dt.strftime('%m/%d/%Y').fillna("N/A")
            
        st.dataframe(df_display_oil, use_container_width=True, hide_index=True)
        # --- SURGICAL EDIT END ---

elif current_page == "GPS and Battery Health":
    st.title("GPS and Battery Health")

    if 'df' in locals() and not df.empty:
        # 1. Identify Critical Assets with Safety Checks
        status_col = col_map["status"]
        batt_col = col_map["battery"]
        
        offline_gps = df[df[status_col] == "Offline"] if status_col in df.columns else pd.DataFrame()
        low_battery = df[df[batt_col] == "Low"] if batt_col in df.columns else pd.DataFrame()

        # 2. Metric Row (This fixes your st.columns() error by providing a number)
        m_col1, m_col2, m_col3 = st.columns(3)
        m_col1.metric("Offline GPS Units", len(offline_gps), delta=len(offline_gps), delta_color="inverse")
        m_col2.metric("Low Battery Alerts", len(low_battery), delta=len(low_battery), delta_color="inverse")
        m_col3.metric("Total Assets Monitored", len(df))

        st.divider()

        # 3. Critical Attention Lists
        col_gps, col_bat = st.columns(2)
        
        with col_gps:
            st.subheader("📡 Offline GPS Status")
            if not offline_gps.empty:
                st.dataframe(offline_gps[[col_map["name"], col_map["loc"]]], use_container_width=True, hide_index=True)
            else:
                st.success("All GPS units are online.")

        with col_bat:
            st.subheader("🪫 Low Battery Status")
            if not low_battery.empty:
                st.dataframe(low_battery[[col_map["name"], col_map["loc"]]], use_container_width=True, hide_index=True)
            else:
                st.success("All batteries reporting normal levels.")

        st.divider()
        
        # 4. Full Fleet Health Table
        st.subheader("Full Fleet Health Log")
        
        # Build list of columns to display, only if they exist in df
        desired_cols = [col_map["name"], col_map["status"], col_map["battery"], col_map["loc"]]
        available_cols = [c for c in desired_cols if c in df.columns]
        
        if available_cols:
            health_display = df[available_cols].copy()
            
            # Highlight logic for the dataframe
            def color_status(val):
                if val == "Offline" or val == "Low": 
                    return 'color: red'
                return ''
                
            st.dataframe(health_display.style.map(color_status), use_container_width=True, hide_index=True)
        else:
            st.warning("Health columns (Status/Battery) were not found in the sheet.")

elif current_page == "Recalls":
    st.write("DEBUG: RECALL PAGE LOADED") # This should appear immediately
    st.title("Safety Recall Management")
    
    CSV_PATH = 'fixed_recalls.csv'
    SOURCE_FILE = 'Recalls_38991_05112026.csv' 

    # --- ACTION BUTTONS ---
    # Placing these in columns at the top to ensure they are high-level
    btn_col1, btn_col2 = st.columns(2)
    
    with btn_col1:
        if st.button("🔄 Refresh Active List", use_container_width=True):
            st.rerun()

    with btn_col2:
        # We are moving this out of the expander temporarily to ensure it works
        seed_trigger = st.button("RUN HISTORICAL SEED", type="primary", use_container_width=True)

    if seed_trigger:
        if 'df' in locals() and not df.empty:
            with st.status("Syncing with NHTSA Database...") as status:
                count = seed_fixed_recalls(df, SOURCE_FILE, CSV_PATH)
                if count > 0:
                    # Save the result to a "sticky note"
                    st.session_state.sync_message = f"Successfully locked in {count} historical recalls."
                    status.update(label="Sync Complete!", state="complete")
                    st.rerun()
        else:
            st.error("Cannot find fleet data. Refresh the page.")

    # This part shows the message AFTER the rerun
    if 'sync_message' in st.session_state:
        st.success(st.session_state.sync_message)
        if st.button("Dismiss Message"):
            del st.session_state.sync_message
            st.rerun()
        else:
            st.error("Cannot find fleet data. Refresh the page.")

    # --- DATA LOADING & FILTERING ---
    try:
        if not os.path.exists(CSV_PATH):
            pd.DataFrame(columns=['VIN', 'CampaignID']).to_csv(CSV_PATH, index=False)
            
        fixed_df = pd.read_csv(CSV_PATH)
        fixed_keys = set(fixed_df['VIN'].astype(str).str.strip() + fixed_df['CampaignID'].astype(str).str.strip())
        
        if os.path.exists(SOURCE_FILE):
            open_recalls_df = pd.read_csv(SOURCE_FILE)
            # Filter logic
            active_alerts = open_recalls_df[~((open_recalls_df['VIN'].astype(str).str.strip() + 
                                              open_recalls_df['Campaign'].astype(str).str.strip()).isin(fixed_keys))]
            
            st.write(f"### Current Active Recalls ({len(active_alerts)})")
            
            if not active_alerts.empty:
                st.table(active_alerts[['Vehicle', 'VIN', 'Campaign', 'Campaign Description']].head(25))
            else:
                st.success("No active recalls found!")
    except Exception as e:
        st.error(f"Page Error: {e}")

elif current_page == "Recalls":
    st.title("Safety Recall Management")
    
    CSV_PATH = 'fixed_recalls.csv'
    SOURCE_FILE = 'Recalls_389911_05112026.csv' 

    # Ensure files exist
    if not os.path.exists(CSV_PATH):
        pd.DataFrame(columns=['VIN', 'CampaignID']).to_csv(CSV_PATH, index=False)

    # --- REFRESH & SEED ACTIONS ---
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("🔄 Refresh Active List", use_container_width=True):
            st.rerun()
    
    with col_b:
        with st.expander("One-Time Historical Sync"):
            st.write("This compares NHTSA history vs your Enterprise CSV to find completed recalls.")
            if st.button("RUN HISTORICAL SEED"):
                if 'df' in locals() and not df.empty:
                    with st.spinner("Processing historical diff..."):
                        count = seed_fixed_recalls(df, SOURCE_FILE, CSV_PATH)
                        st.success(f"Added {count} historical recalls to Fixed List.")
                        st.rerun()

    # --- MAIN DISPLAY LOGIC ---
    try:
        fixed_df = pd.read_csv(CSV_PATH)
        # Create a lookup set of VIN+ID for fast filtering
        fixed_keys = set(fixed_df['VIN'].astype(str).str.strip() + fixed_df['CampaignID'].astype(str).str.strip())
    except:
        fixed_keys = set()

    if os.path.exists(SOURCE_FILE):
        try:
            open_recalls_df = pd.read_csv(SOURCE_FILE)
            # Filter: Keep rows where VIN+Campaign is NOT in the fixed_keys set
            active_alerts = open_recalls_df[~((open_recalls_df['VIN'].astype(str).str.strip() + 
                                              open_recalls_df['Campaign'].astype(str).str.strip()).isin(fixed_keys))]
            
            if not active_alerts.empty:
                st.warning(f"Pending Recalls: {len(active_alerts)}")
                
                # Table Headers
                h1, h2, h3, h4 = st.columns([1.5, 1.5, 3, 1])
                h1.write("**Vehicle**")
                h2.write("**Campaign ID**")
                h3.write("**Description**")
                h4.write("**Action**")
                st.divider()

                for idx, alert in active_alerts.iterrows():
                    v_vin = str(alert['VIN']).strip()
                    v_camp = str(alert['Campaign']).strip()
                    
                    c1, c2, c3, c4 = st.columns([1.5, 1.5, 3, 1]) 
                    c1.write(f"**{alert.get('Vehicle', 'Unknown')}**")
                    c2.write(f"**ID:** {v_camp}")
                    c3.write(alert.get('Campaign Description', 'No Description'))
                    
                    if c4.button("FIXED", key=f"fix_{v_vin}_{v_camp}"):
                        # Append this specific fix to the CSV
                        new_entry = pd.DataFrame([{"VIN": v_vin, "CampaignID": v_camp}])
                        new_entry.to_csv(CSV_PATH, mode='a', header=False, index=False)
                        st.toast(f"Marked {v_camp} as Fixed!")
                        st.rerun()
            else:
                st.success("All recalls from the Enterprise list have been addressed!")
                
        except Exception as e:
            st.error(f"Error processing recall data: {e}")
    else:
        st.error(f"Source file {SOURCE_FILE} not found. Please ensure it is in the directory.")

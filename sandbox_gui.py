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
    "weekly_actual": "Weekly Miles Actual",
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
    if "harvest_logs" not in st.session_state:
        st.session_state.harvest_logs = []
    
    st.session_state.harvest_logs.clear()
    st.session_state.harvest_logs.append("🛫 **Starting Granular Fleet Harvester Scan (Smartsheet Source)...**")
    
    fixed_history = []
    total_processed = 0
    total_skipped = 0

    if fleet_df is None or fleet_df.empty:
        st.session_state.harvest_logs.append("❌ Critical Error: Master fleet dataframe is empty or unreadable.")
        return 0

    st.session_state.harvest_logs.append(f"📋 Total individual rows detected in fleet dataframe: **{len(fleet_df)}**")

    # Loop through every single individual vehicle record in your main Smartsheet fleet
    for idx, row in fleet_df.iterrows():
        raw_vin = row.get('VIN')
        
        # Clean and validate the string to ensure it's an actual vehicle data row
        if pd.isna(raw_vin) or raw_vin is None:
            total_skipped += 1
            continue
            
        vin = str(raw_vin).strip().upper()
        if len(vin) != 17:
            total_skipped += 1
            continue

        total_processed += 1
        st.session_state.harvest_logs.append(f"⚙️ **[Car #{total_processed}] Initializing Pipeline for VIN:** `{vin}`")
        
        # --- STAGE 1: DECODE VIN VIA NHTSA vPIC ---
        try:
            vpic_url = f"https://vpic.nhtsa.dot.gov/api/vehicles/decodevinvalues/{vin}?format=json"
            st.session_state.harvest_logs.append(f"   📡 Ping vPIC Decoder -> `{vpic_url}`")
            vpic_data = requests.get(vpic_url, timeout=10).json()
            
            # Direct protection against list/dictionary payload nesting variation
            if isinstance(vpic_data, list) and len(vpic_data) > 0:
                vpic_res = vpic_data
            else:
                vpic_res = vpic_data
                
            if not isinstance(vpic_res, dict) or 'Results' not in vpic_res or not vpic_res['Results']:
                st.session_state.harvest_logs.append(f"   ❌ vPIC Failure: Payload missing 'Results' array field.")
                total_skipped += 1
                continue
                
            specs = vpic_res['Results']
            make = str(specs.get('Make', '')).strip()
            model = str(specs.get('Model', '')).strip()
            year = str(specs.get('ModelYear', '')).strip()
            
            st.session_state.harvest_logs.append(f"   📝 vPIC Parsed Specs: Make=`{make}`, Model=`{model}`, Year=`{year}`")
            
            if not make or not model or not year or make.lower() == 'none' or model.lower() == 'none':
                st.session_state.harvest_logs.append(f"   ⚠️ vPIC Reject: Incomplete/Null attributes decoded from VIN sequence.")
                total_skipped += 1
                continue
                
        except Exception as vpic_err:
            st.session_state.harvest_logs.append(f"   💥 Stage 1 Exception (vPIC Decoder Crash): {str(vpic_err)}")
            total_skipped += 1
            continue

        # --- STAGE 2: HARVEST HISTORICAL RECALL CAMPAIGNS ---
        try:
            st.session_state.harvest_logs.append(f"   📡 Ping Recall Engine via Specs -> `{year} {make} {model}`")
            recalls = check_vehicle_recall(make, model, year)
            
            if recalls:
                st.session_state.harvest_logs.append(f"   🟢 Success: Found {len(recalls)} historical campaigns for this vehicle architecture.")
                for r in recalls:
                    campaign_id = str(r.get('NHTSACampaignNumber', '')).strip().upper()
                    if campaign_id:
                        fixed_history.append({
                            "VIN": vin,
                            "CampaignID": campaign_id,
                            "Make": make,
                            "Model": model,
                            "Year": year
                        })
            else:
                st.session_state.harvest_logs.append(f"   ℹ️ Recall Engine: 0 baseline campaigns registered at NHTSA for this asset class.")
                
        except Exception as recall_err:
            st.session_state.harvest_logs.append(f"   💥 Stage 2 Exception (Recall API Crash): {str(recall_err)}")
            continue

    st.session_state.harvest_logs.append(f"📋 **Harvest Run Summary:** Checked {total_processed} cars. Skipped {total_skipped} rows.")

    # Commit itemized data rows directly to your local file storage layer
    if fixed_history:
        try:
            debug_df = pd.DataFrame(fixed_history).drop_duplicates()
            # Enforce exact alignment with your custom csv schema headers
            debug_df = debug_df[['VIN', 'CampaignID', 'Make', 'Model', 'Year']]
            debug_df.to_csv(fixed_csv_path, index=False)
            st.session_state.harvest_logs.append(f"✅ **SUCCESS:** Successfully wrote {len(debug_df)} row entries to `{fixed_csv_path}`!")
            return len(debug_df)
        except Exception as e:
            st.session_state.harvest_logs.append(f"🚨 **HARD WRITE FAILURE:** Could not save csv: {str(e)}")
            return 0
    else:
        st.session_state.harvest_logs.append("⚠️ **Scan Complete:** Zero historical records were generated by the API loop.")
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
                
                if 'Results' in res and len(res['Results']) > 0:
                    specs = res['Results'][0]
                    make = str(specs.get('Make', '')).strip()
                    model = str(specs.get('Model', '')).strip()
                    year = str(specs.get('ModelYear', '')).strip()
                    
                    if make and model and year and make.lower() != 'none' and model.lower() != 'none':
                        # Check NHTSA for recalls
                        recalls = check_vehicle_recall(make, model, year)
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

if not df.empty:
    # Use global sheet if available, otherwise check if smartsheet client needs a quick fallback fetch
    if 'sheet' not in locals() and 'sheet' not in globals():
        try:
            smart = smartsheet.Smartsheet(st.secrets["smartsheet_token"])
            sheet = smart.Sheets.get_sheet(st.secrets["sheet_id"])
        except Exception:
            sheet = None

    date_col_title = next((col.title for col in sheet.columns if col.id == OIL_COL_IDS["last_service_date"]), None) if sheet else None
    # If found, rename it to a friendly key for the rest of the script
    if date_col_title:
        df = df.rename(columns={date_col_title: "Date of Last Oil Change"})
    
    # DATA CLEANING: Clean all columns
    for col_key in ["allowance", "projected", "actual", "weekly_actual", "odo", "last_oil", "next_oil", "interval"]:
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
        df_display[col] = df_display[col].fillna(0).astype(int)

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
                        # Skip processing if the vehicle has a Lock flag active
                        if str(high_row.get("Vehicle Lock", "")).strip().lower() in ["yes", "true", "1", "locked"]:
                            continue

                        odo_val = force_num(high_row[col_map["odo"]], fallback=0.0)
                        proj_m_val = force_num(high_row[col_map["projected"]])
                        act_m_val = force_num(high_row[col_map["actual"]])
                        wk_val = force_num(high_row[col_map["weekly_actual"]])
                        
                        # Catch anomalous odometer data corruption sitting in actuals
                        if act_m_val and odo_val > 0 and act_m_val >= (odo_val * 0.5):
                            act_m_val = 0.0

                        if proj_m_val and proj_m_val > 0:
                            raw_route_A = proj_m_val
                        elif act_m_val and act_m_val > 0:
                            raw_route_A = act_m_val
                        elif wk_val and wk_val > 0:
                            raw_route_A = wk_val * 4.34
                        else:
                            raw_route_A = 0.0

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

                            # Skip processing if the candidate low-use vehicle is locked
                            if str(low_row.get("Vehicle Lock", "")).strip().lower() in ["yes", "true", "1", "locked"]:
                                continue

                            dist = get_distance_miles(high_row[col_map["loc"]], low_row[col_map["loc"]])
                            if dist > max_dist: continue
                            
                            odo_B = force_num(low_row[col_map["odo"]], fallback=0.0)
                            proj_m_val_B = force_num(low_row[col_map["projected"]])
                            act_m_val_B = force_num(low_row[col_map["actual"]])
                            wk_val_B = force_num(low_row[col_map["weekly_actual"]])

                            # Catch anomalous odometer data corruption sitting in actuals
                            if act_m_val_B and odo_B > 0 and act_m_val_B >= (odo_B * 0.5):
                                act_m_val_B = 0.0

                            if proj_m_val_B and proj_m_val_B > 0:
                                raw_route_B = proj_m_val_B
                            elif act_m_val_B and act_m_val_B > 0:
                                raw_route_B = act_m_val_B
                            elif wk_val_B and wk_val_B > 0:
                                raw_route_B = wk_val_B * 4.34
                            else:
                                raw_route_B = 0.0

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
    st.title("Safety Recall Management")
    
    CSV_PATH = 'fixed_recalls.csv'
    FIELDNAMES = ["Vehicle Name", "VIN", "CampaignID", "ManufacturerCampaign", "Make", "Model", "Year"]

    # Ensure fixed file skeleton exists safely with correct layout
    if not os.path.exists(CSV_PATH) or os.path.getsize(CSV_PATH) == 0:
        pd.DataFrame(columns=FIELDNAMES).to_csv(CSV_PATH, index=False)

    # Track fixed composite keys to exclude already completed elements
    try:
        fixed_df = pd.read_csv(CSV_PATH)
        fixed_keys = set(fixed_df['VIN'].astype(str).str.strip().str.upper() + fixed_df['CampaignID'].astype(str).str.strip().str.upper())
    except Exception:
        fixed_keys = set()

    # Dynamic scanner execution button targeting live API calls 
    if st.button("🔍 Scan Fleet for Active Recalls", use_container_width=True, type="primary"):
        if df.empty:
            st.error("Master fleet dataframe cache is unpopulated or missing.")
        else:
            # Persistent session diagnostic dictionary initialized before scan execution
            st.session_state.diagnostic_logs = {
                "total_vehicles_processed": 0,
                "invalid_vins_skipped": 0,
                "api_queries_attempted": [],
                "fixed_keys_snapshot": list(fixed_keys)[:15] if fixed_keys else []
            }
            
            with st.spinner("Pinging NHTSA API endpoints across live fleet configurations..."):
                scanned_results = []
                vin_col = next((c for c in df.columns if 'vin' in c.lower()), None)
                make_col = next((c for c in df.columns if 'make' in c.lower()), None)
                model_col = next((c for c in df.columns if 'model' in c.lower()), None)
                year_col = next((c for c in df.columns if 'year' in c.lower()), None)
                name_col = col_map.get("name") if col_map.get("name") in df.columns else next((c for c in df.columns if 'name' in c.lower()), None)
                
                make_normalization = {
                    "CHEVROLET CARS": "CHEVROLET", "CHEVY": "CHEVROLET",
                    "HYUNDAI MOTOR": "HYUNDAI", "HYUNDAI MOTOR AMERICA": "HYUNDAI",
                    "BLUE BIRD BODY COMPANY": "BLUE BIRD", "BLUEBIRD": "BLUE BIRD",
                    "CHRYSLER LLC": "CHRYSLER"
                }

                for _, row in df.iterrows():
                    raw_vin = str(row.get(vin_col, '')).strip().upper() if vin_col else ""
                    if len(raw_vin) != 17:
                        continue
                    
                    make_val = " ".join(str(row.get(make_col, '')).strip().split()).upper() if make_col else ""
                    model_val = " ".join(str(row.get(model_col, '')).strip().split()).upper() if model_col else ""
                    year_val = " ".join(str(row.get(year_col, '')).strip().split()).upper() if year_col else ""
                    name_val = str(row.get(name_col, 'Unknown Vehicle')).strip() if name_col else "Unknown Vehicle"
                    
                    if make_val in make_normalization:
                        make_val = make_normalization[make_val]

                    if "EXPRESS" in model_val or "SAVANNA" in model_val:
                        model_val = "EXPRESS"
                    elif "TRANSIT" in model_val and "CONNECT" not in model_val:
                        model_val = "TRANSIT"
                    elif "PC205" in model_val or "CE" in model_val:
                        model_val = "CE"
                    elif "COMMERCIAL" in model_val:
                        model_val = "COMMERCIAL"
                    elif model_val == "PACIFICA":
                        model_val = "VOYAGER"

                    st.session_state.diagnostic_logs["total_vehicles_processed"] += 1

                    if make_val and model_val and year_val:
                        recalls = check_vehicle_recall(make_val, model_val, year_val)
                        
                        # Log raw API response numbers per combination tested
                        st.session_state.diagnostic_logs["api_queries_attempted"].append({
                            "vehicle_name": name_val,
                            "vin": raw_vin,
                            "queried_make": make_val,
                            "queried_model": model_val,
                            "queried_year": year_val,
                            "api_raw_results_count": len(recalls) if isinstance(recalls, list) else "ERROR_NOT_LIST"
                        })
                    elif "TRANSIT" in model_val and "CONNECT" not in model_val:
                        model_val = "TRANSIT"
                    elif "PC205" in model_val or "CE" in model_val:
                        model_val = "CE"
                    elif "COMMERCIAL" in model_val:
                        model_val = "COMMERCIAL"
                    elif model_val == "PACIFICA":
                        model_val = "VOYAGER"

                    if make_val and model_val and year_val:
                        recalls = check_vehicle_recall(make_val, model_val, year_val)
                        for r in recalls:
                            camp_id = str(r.get("NHTSACampaignNumber", "")).strip()
                            if not camp_id:
                                continue
                            
                            # Parse manufacturer internal tracking code or fallback to component type
                            raw_mfr = r.get("mfrCampaignNumber") or r.get("MfrCampaignNumber") or ""
                            if not raw_mfr or str(raw_mfr).upper() == "NONE" or str(raw_mfr) == camp_id:
                                notes_text = r.get("Notes", "") or ""
                                remedy_text = r.get("Remedy", "") or ""
                                list_match = re.search(r'(?:numbers\s+for\s+this\s+recall\s+are)\s+([A-Z0-9\-,\s\b(and)]+)', f"{notes_text} {remedy_text}", re.IGNORECASE)
                                if list_match:
                                    codes = re.findall(r'\b([A-Z0-9\-]{2,10})\b', list_match.group(1).upper())
                                    valid_codes = [c for c in codes if c not in ["NISSAN", "FORD", "CHEVY", "CHEVROLET", "RECALL", "AND", "FOR"]]
                                    raw_mfr = " / ".join(sorted(list(set(valid_codes)))) if valid_codes else ""
                            
                            if not raw_mfr:
                                raw_mfr = f"{str(r.get('Component', 'UNKNOWN')).split(':')[0].strip().upper()} RECALL"
                                
                            scanned_results.append({
                                "Vehicle Name": name_val,
                                "VIN": raw_vin,
                                "CampaignID": camp_id,
                                "ManufacturerCampaign": raw_mfr,
                                "Make": make_val,
                                "Model": model_val,
                                "Year": year_val,
                                "Summary": r.get("Summary", "No description available.")
                            })
                st.session_state.scanned_recalls = scanned_results
                st.toast(f"Scan Complete! Located {len(scanned_results)} total active campaigns.", icon="🔍")

    # Render filtered layout from session memory cache
    if "scanned_recalls" in st.session_state:
        # Diagnostic UI Expander Rendered Explicitly for Error Log Verification
        if "diagnostic_logs" in st.session_state:
            with st.expander("🛠️ Live Fleet Scanner Diagnostic Log", expanded=True):
                st.subheader("High-Level Execution Summary")
                st.write(f"**Total Row Records Swept from Smartsheet Cache:** {st.session_state.diagnostic_logs['total_vehicles_processed']}")
                st.write(f"**Invalid Short VINs Discarded:** {st.session_state.diagnostic_logs['invalid_vins_skipped']}")
                st.write(f"**Total Scanned Results Pulled in Memory:** {len(st.session_state.scanned_recalls)}")
                
                st.subheader("Sample of active fixed_keys configuration blocks")
                st.json(st.session_state.diagnostic_logs["fixed_keys_snapshot"])
                
                st.subheader("Raw API Matrix (Endpoints Queried vs Responses Loaded)")
                st.dataframe(pd.DataFrame(st.session_state.diagnostic_logs["api_queries_attempted"]))

        active_alerts = [r for r in st.session_state.scanned_recalls if (r["VIN"] + r["CampaignID"]) not in fixed_keys]
        
        if active_alerts:
            st.warning(f"Unresolved Engine Recalls Active: {len(active_alerts)}")
            
            h1, h2, h3, h4 = st.columns([1.5, 1.5, 3, 1])
            h1.write("**Vehicle Context**")
            h2.write("**Identifiers**")
            h3.write("**Campaign Technical Summary**")
            h4.write("**Action**")
            st.divider()

            for idx, alert in enumerate(active_alerts):
                c1, c2, c3, c4 = st.columns([1.5, 1.5, 3, 1])
                c1.write(f"**{alert['Vehicle Name']}**\n`{alert['VIN']}`")
                c2.write(f"**NHTSA:** {alert['CampaignID']}\n**Mfr:** {alert['ManufacturerCampaign']}")
                c3.write(alert['Summary'])
                
                if c4.button("Completed", key=f"comp_{alert['VIN']}_{alert['CampaignID']}_{idx}", use_container_width=True, type="secondary"):
                    new_row = pd.DataFrame([{
                        "Vehicle Name": alert["Vehicle Name"],
                        "VIN": alert["VIN"],
                        "CampaignID": alert["CampaignID"],
                        "ManufacturerCampaign": alert["ManufacturerCampaign"],
                        "Make": alert["Make"],
                        "Model": alert["Model"],
                        "Year": alert["Year"]
                    }])
                    new_row.to_csv(CSV_PATH, mode='a', header=False, index=False)
                    st.toast(f"Saved campaign {alert['CampaignID']} to fixed records!", icon="✅")
                    st.rerun()
                st.divider()
        else:
            st.success("All clear! Zero active recalls discovered across scanned vehicle parameters.")
# --------------

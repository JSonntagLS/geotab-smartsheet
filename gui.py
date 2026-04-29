import streamlit as st
# 1. THIS MUST BE THE ABSOLUTE FIRST STREAMLIT CALL
st.set_page_config(page_title="Assets | LifeServe", layout="wide")

import smartsheet
import pandas as pd
from datetime import datetime

# --- CONFIGURATION ---
COL_ID_SUGGESTED_SWAP = 3624929309527940
COL_ID_DATE_SWAP = 8128528936898436

access_token = st.secrets["smartsheet_token"]
sheet_id = st.secrets["sheet_id"]
ss_client = smartsheet.Smartsheet(access_token)

DISTANCE_MATRIX = {
    ("Johnston, IA", "Mitchell, SD"): 275,
    ("Johnston, IA", "Sioux City, IA"): 185,
    ("Johnston, IA", "Cedar Falls, IA"): 115,
    ("Johnston, IA", "Mason City, IA"): 120,
    ("Sioux City, IA", "Mitchell, SD"): 135,
    ("Sioux City, IA", "Yankton, SD"): 65,
    ("Cedar Falls, IA", "Mason City, IA"): 75,
}

def get_distance(loc1, loc2):
    dist = DISTANCE_MATRIX.get((loc1, loc2)) or DISTANCE_MATRIX.get((loc2, loc1))
    return f"({dist} miles)" if dist else ""

# --- STYLE SETUP (Geotab Motif) ---
st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    h1 { color: #002f6c; font-family: 'Arial', sans-serif; font-weight: 700; margin-bottom: 0px; }
    h3 { color: #002f6c; font-family: 'Arial', sans-serif; border-bottom: 2px solid #002f6c; padding-bottom: 5px; }
    .stButton>button { 
        background-color: #002f6c; color: white; border-radius: 4px; 
        border: none; padding: 10px 24px; font-weight: bold;
    }
    .stButton>button:hover { background-color: #004a99; color: white; border: none; }
    </style>
    """, unsafe_allow_index=True)

# --- DATA FETCHING ---
@st.cache_data(ttl=60)
def fetch_smartsheet_data():
    sheet = ss_client.Sheets.get_sheet(sheet_id)
    columns = [col.title for col in sheet.columns]
    rows = []
    for row in sheet.rows:
        cells = {columns[i]: cell.value for i, cell in enumerate(row.cells)}
        cells['row_id'] = row.id 
        rows.append(cells)
    return pd.DataFrame(rows)

df = fetch_smartsheet_data()

# --- HEADER & TOP NAVIGATION ---
col_title, col_btn1, col_btn2 = st.columns([3, 1, 1])
with col_title:
    st.title("Assets")
    st.caption("Fleet Rotation Matrix | LifeServe Blood Center")

with col_btn1:
    run_analysis = st.button("🔍 Run Swap Analysis", use_container_width=True)
with col_btn2:
    sync_data = st.button("🚀 Sync to Smartsheet", use_container_width=True)

st.divider()

# --- MAIN DASHBOARD ---
st.subheader("Live Fleet Status")

def color_priority(val):
    if val == "URGENT ROTATION": return 'background-color: #ffcccc'
    if val == "Consider Rotating": return 'background-color: #fff4cc'
    return ''

display_cols = [
    "Vehicle Name", "Current Location", "Vehicle Description", 
    "Monthly Miles Actual", "Projected Monthly Usage", "Monthly Allowance", 
    "Weekly Trend", "Rotation Priority", "Utilization Tier",
    "Suggested Swap", "Date of Suggest Swap"
]
available_cols = [c for c in display_cols if c in df.columns]

if not df.empty:
    styled_df = df[available_cols].style.map(color_priority, subset=['Rotation Priority'])
    st.dataframe(styled_df, use_container_width=True, hide_index=True)

# --- LOGIC ENGINES ---
if run_analysis:
    st.toast("Analyzing Fleet Trends...")
    
    # Clean data
    df['Rotation Priority'] = df['Rotation Priority'].astype(str).str.upper().str.strip()
    df['Utilization Tier'] = df['Utilization Tier'].astype(str).str.upper().str.strip()
    
    urgent = df[(df['Rotation Priority'] == 'URGENT ROTATION') & (df['Vehicle Lock'] != True)].copy()
    underused = df[df['Utilization Tier'].str.contains('UNDERUSED', na=False) & (df['Vehicle Lock'] != True)].copy()
    
    if not urgent.empty:
        st.subheader("💡 AI Recommended Swaps")
        pending_updates = []

        for i in range(min(len(urgent), len(underused))):
            veh_u = urgent.iloc[i]
            veh_low = underused.iloc[i]
            dist_text = get_distance(veh_u['Current Location'], veh_low['Current Location'])
            
            suggestion = f"Swap with {veh_low['Vehicle Name']} {dist_text}"
            st.success(f"**Recommendation {i+1}:** Move **{veh_u['Vehicle Name']}** to **{veh_low['Current Location']}** {dist_text}.")
            
            pending_updates.append({'row_id': veh_u['row_id'], 'suggestion': suggestion})
        
        st.session_state['pending_updates_list'] = pending_updates
    else:
        st.warning("No urgent rotations needed at this time.")

if sync_data:
    if 'pending_updates_list' in st.session_state:
        today = datetime.now().strftime("%Y-%m-%d")
        rows_to_update = []

        for update in st.session_state['pending_updates_list']:
            new_row = ss_client.models.Row()
            new_row.id = int(update['row_id'])
            
            # Add Cells
            res_cell = ss_client.models.Cell(column_id=COL_ID_SUGGESTED_SWAP, value=update['suggestion'])
            date_cell = ss_client.models.Cell(column_id=COL_ID_DATE_SWAP, value=today)
            new_row.cells.extend([res_cell, date_cell])
            rows_to_update.append(new_row)
        
        try:
            ss_client.Sheets.update_rows(sheet_id, rows_to_update)
            st.balloons()
            st.success(f"Successfully synced {len(rows_to_update)} recommendations to Smartsheet!")
            st.cache_data.clear()
        except Exception as e:
            st.error(f"Error: {e}")
    else:
        st.info("Please run the Analysis first to generate recommendations.")

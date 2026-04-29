import streamlit as st
import smartsheet
import pandas as pd
from datetime import datetime

# 1. PAGE CONFIG (MUST BE FIRST AND ONLY CALLED ONCE)
st.set_page_config(page_title="Assets | LifeServe", layout="wide")

# --- CONFIGURATION ---
COL_ID_SUGGESTED_SWAP = 3624929309527940
COL_ID_DATE_SWAP = 8128528936898436

# Access secrets
access_token = st.secrets["smartsheet_token"]
sheet_id = st.secrets["sheet_id"]
ss_client = smartsheet.Smartsheet(access_token)

# Approximate mileage between hubs
DISTANCE_MATRIX = {
    ("Johnston, IA", "Mitchell, SD"): 275,
    ("Johnston, IA", "Sioux City, IA"): 185,
    ("Johnston, IA", "Cedar Falls, IA"): 115,
    ("Johnston, IA", "Mason City, IA"): 120,
    ("Johnston, IA", "Pierre, SD"): 385,     # Added
    ("Johnston, IA", "Pella, IA"): 55,       # Added
    ("Sioux City, IA", "Mitchell, SD"): 135,
    ("Sioux City, IA", "Yankton, SD"): 65,
    ("Sioux City, IA", "Pella, IA"): 240,    # Added
    ("Cedar Falls, IA", "Mason City, IA"): 75,
    ("Davenport, IA", "Pella, IA"): 135,     # Added
}

def get_distance(loc1, loc2):
    # Ensure inputs are strings and stripped
    l1, l2 = str(loc1).strip(), str(loc2).strip()
    dist = DISTANCE_MATRIX.get((l1, l2)) or DISTANCE_MATRIX.get((l2, l1))
    return f"({dist} miles)" if dist else ""

# --- STYLE SETUP (Geotab Motif) ---
st.markdown("""
    <style>
    .main { background-color: #ffffff; }
    h1 { color: #002f6c; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; font-weight: 700; margin-bottom: 0px; }
    h3 { color: #002f6c; font-family: 'Segoe UI', sans-serif; border-bottom: 1px solid #e0e0e0; padding-bottom: 10px; font-size: 1.2rem; }
    
    /* Table Header Styling */
    thead tr th {
        background-color: #ffffff !important;
        color: #666666 !important;
        font-weight: 600 !important;
        text-transform: none !important;
        border-bottom: 2px solid #e0e0e0 !important;
    }

    /* Button Styling */
    .stButton>button { 
        background-color: #002f6c; color: white; border-radius: 4px; 
        border: none; padding: 10px 24px; font-weight: 600;
    }
    .stButton>button:hover { background-color: #004a99; color: white; border: none; }
    </style>
    """, unsafe_allow_html=True)

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
    
    df_raw = pd.DataFrame(rows)
    # CLEANING: Strip spaces from column names to prevent KeyErrors
    df_raw.columns = df_raw.columns.str.strip()
    return df_raw

df = fetch_smartsheet_data()

# --- HEADER & TOP NAVIGATION ---
col_title, col_btn1, col_btn2 = st.columns([3, 1, 1])
with col_title:
    st.title("Assets")
    st.caption("Fleet Rotation Matrix | LifeServe Blood Center")

with col_btn1:
    run_analysis = st.button("Run Swap Analysis", use_container_width=True)
with col_btn2:
    sync_data = st.button("Sync to Smartsheet", use_container_width=True)

st.divider()

# --- MAIN DASHBOARD ---
st.subheader("Live Fleet Status")

def apply_geotab_styles(styler):
    # Set text color to that specific Geotab blue for the primary Asset column
    styler.set_properties(subset=['Vehicle Name'], **{'color': '#0070d2', 'font-weight': '600'})
    # General row styling
    styler.set_properties(**{'background-color': 'white', 'color': '#333333', 'border-bottom': '1px solid #eeeeee'})
    # Priority Highlighting (Geotab-style light red/pink)
    styler.map(lambda val: 'background-color: #feebe2' if str(val).upper().strip() == "URGENT ROTATION" else '', subset=['Rotation Priority'])
    return styler

display_cols = [
    "Vehicle Name", "Current Location", "Vehicle Description", 
    "Monthly Miles Actual", "Projected Monthly Usage", "Monthly Allowance", 
    "Weekly Trend", "Rotation Priority", "Utilization Tier",
    "Suggested Swap", "Date of Suggest Swap"
]
available_cols = [c for c in display_cols if c in df.columns]

if not df.empty:
    # Applying the Geotab look via Pandas Styler
    styled_df = df[available_cols].style.pipe(apply_geotab_styles)
    
    st.dataframe(
        styled_df, 
        use_container_width=True, 
        hide_index=True,
        column_config={
            "Vehicle Name": st.column_config.TextColumn("Asset", width="large"),
            "Monthly Miles Actual": st.column_config.NumberColumn("Odometer (mi)", format="%d"),
        }
    )

# --- ANALYSIS ENGINE ---
if run_analysis:
    st.toast("Analyzing Fleet Trends...")
    
    # Standardize data for matching
    df_analysis = df.copy()
    df_analysis['Rotation Priority'] = df_analysis['Rotation Priority'].astype(str).str.upper().str.strip()
    df_analysis['Utilization Tier'] = df_analysis['Utilization Tier'].astype(str).str.upper().str.strip()
    
    # Check for Vehicle Lock column safely
    lock_col = 'Vehicle Lock' if 'Vehicle Lock' in df_analysis.columns else None
    
    urgent = df_analysis[df_analysis['Rotation Priority'] == 'URGENT ROTATION'].copy()
    if lock_col:
        urgent = urgent[urgent[lock_col] != True]
        
    underused = df_analysis[df_analysis['Utilization Tier'].str.contains('UNDERUSED', na=False)].copy()
    if lock_col:
        underused = underused[underused[lock_col] != True]
    
    if not urgent.empty and not underused.empty:
        st.subheader("AI Recommended Swaps")
        pending_updates = []
        recommendations_for_table = []

        for i in range(min(len(urgent), len(underused))):
            veh_u = urgent.iloc[i]
            veh_low = underused.iloc[i]
            
            loc_u = veh_u.get('Current Location', 'Unknown')
            loc_low = veh_low.get('Current Location', 'Unknown')
            dist_text = get_distance(loc_u, loc_low)
            
            suggestion = f"Swap with {veh_low['Vehicle Name']} {dist_text}"
            
            # Build the table data
            recommendations_for_table.append({
                "Priority Asset": veh_u['Vehicle Name'],
                "Current Site": loc_u,
                "Target Site": loc_low,
                "Distance": dist_text,
                "Suggested Partner": veh_low['Vehicle Name']
            })
            
            pending_updates.append({'row_id': veh_u['row_id'], 'suggestion': suggestion})
        
        # Display as a themed table
        recs_df = pd.DataFrame(recommendations_for_table)
        
        def style_recs(styler):
            styler.set_properties(subset=['Priority Asset'], **{'color': '#0070d2', 'font-weight': '600'})
            styler.set_properties(**{'background-color': '#f0fff4', 'color': '#333333', 'border-bottom': '1px solid #eeeeee'})
            return styler

        st.dataframe(
            recs_df.style.pipe(style_recs),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Priority Asset": st.column_config.TextColumn("Asset Needing Rotation", width="large"),
                "Target Site": st.column_config.TextColumn("Move To"),
                "Suggested Partner": st.column_config.TextColumn("Swap With", width="medium")
            }
        )
        
        st.session_state['pending_updates_list'] = pending_updates
    else:
        st.warning("No matches found. Ensure you have both 'URGENT' and 'UNDERUSED' vehicles available.")

# --- SYNC ENGINE ---
if sync_data:
    if 'pending_updates_list' in st.session_state:
        today = datetime.now().strftime("%Y-%m-%d")
        rows_to_update = []

        for update in st.session_state['pending_updates_list']:
            new_row = ss_client.models.Row()
            new_row.id = int(update['row_id'])
            
            res_cell = ss_client.models.Cell(column_id=COL_ID_SUGGESTED_SWAP, value=update['suggestion'])
            date_cell = ss_client.models.Cell(column_id=COL_ID_DATE_SWAP, value=today)
            new_row.cells.extend([res_cell, date_cell])
            rows_to_update.append(new_row)
        
        try:
            ss_client.Sheets.update_rows(sheet_id, rows_to_update)
            st.balloons()
            st.success(f"Successfully synced {len(rows_to_update)} rows!")
            st.cache_data.clear()
        except Exception as e:
            st.error(f"Smartsheet Error: {e}")
    else:
        st.info("Run Analysis first.")

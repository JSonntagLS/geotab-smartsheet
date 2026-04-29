import streamlit as st
import smartsheet
import pandas as pd
from datetime import datetime

# 1. PAGE CONFIG
st.set_page_config(page_title="Assets | LifeServe", layout="wide")

# --- CONFIGURATION ---
COL_ID_SUGGESTED_SWAP = 3624929309527940
COL_ID_DATE_SWAP = 8128528936898436

access_token = st.secrets["smartsheet_token"]
sheet_id = st.secrets["sheet_id"]
ss_client = smartsheet.Smartsheet(access_token)

# Comprehensive Distance Matrix - Updated with missing routes from latest screenshots
DISTANCE_MATRIX = {
    # Iowa Hubs
    ("Johnston, IA", "Ames, IA"): 30,
    ("Johnston, IA", "Ankeny, IA"): 12,
    ("Johnston, IA", "Cedar Falls, IA"): 115,
    ("Johnston, IA", "Davenport, IA"): 175,
    ("Johnston, IA", "Des Moines, IA"): 10,
    ("Johnston, IA", "Fort Dodge, IA"): 85,
    ("Johnston, IA", "Marshalltown, IA"): 55,
    ("Johnston, IA", "Mason City, IA"): 120,
    ("Johnston, IA", "Pella, IA"): 55,
    ("Johnston, IA", "Sioux City, IA"): 185,
    ("Johnston, IA", "Urbandale, IA"): 5,
    ("Johnston, IA", "Waterloo, IA"): 110,
    
    # South Dakota Hubs
    ("Johnston, IA", "Aberdeen, SD"): 375,
    ("Johnston, IA", "Mitchell, SD"): 275,
    ("Johnston, IA", "Pierre, SD"): 385,
    ("Johnston, IA", "Yankton, SD"): 190,
    
    # Cross-Region Permutations (Added from image_6e0691.png & image_6e0c66.png)
    ("Yankton, SD", "Aberdeen, SD"): 230,
    ("Mason City, IA", "Mitchell, SD"): 265,
    ("Mason City, IA", "Aberdeen, SD"): 305,
    ("Davenport, IA", "Fort Dodge, IA"): 215,
    ("Davenport, IA", "Pella, IA"): 135,
    ("Sioux City, IA", "Aberdeen, SD"): 220,
    ("Sioux City, IA", "Mitchell, SD"): 135,
    ("Sioux City, IA", "Yankton, SD"): 65,
    ("Cedar Falls, IA", "Mason City, IA"): 75,
    ("Cedar Falls, IA", "Fort Dodge, IA"): 100,
}

def get_distance(loc1, loc2):
    """Calculates distance, handles same-city, and ignores 'None' values."""
    try:
        l1, l2 = str(loc1).strip(), str(loc2).strip()
        
        # If Smartsheet has "None" or is blank, return empty string
        if any(x.lower() in ["none", "", "nan"] for x in [l1, l2]):
            return ""
        
        if l1 == l2:
            return "(0 miles)"
            
        dist = DISTANCE_MATRIX.get((l1, l2)) or DISTANCE_MATRIX.get((l2, l1))
        return f"({dist} miles)" if dist is not None else ""
    except:
        return ""

# --- STYLE SETUP ---
st.markdown("""
    <style>
    .main { background-color: #ffffff; }
    h1 { color: #002f6c; font-family: 'Segoe UI', sans-serif; font-weight: 700; }
    thead tr th { background-color: #ffffff !important; color: #666666 !important; border-bottom: 2px solid #e0e0e0 !important; }
    .stButton>button { background-color: #002f6c; color: white; border-radius: 4px; font-weight: 600; }
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
    df_raw.columns = df_raw.columns.str.strip()
    return df_raw

df = fetch_smartsheet_data()

# --- HEADER ---
col_title, col_btn1, col_btn2 = st.columns([3, 1, 1])
with col_title:
    st.title("Assets")
    st.caption("Fleet Rotation Matrix | LifeServe Blood Center")

run_analysis = col_btn1.button("Run Swap Analysis", use_container_width=True)
sync_data = col_btn2.button("Sync to Smartsheet", use_container_width=True)

st.divider()

# --- MAIN DASHBOARD ---
st.subheader("Live Fleet Status")

def apply_geotab_styles(styler):
    styler.set_properties(subset=['Vehicle Name'], **{'color': '#0070d2', 'font-weight': '600'})
    styler.set_properties(**{'background-color': 'white', 'color': '#333333', 'border-bottom': '1px solid #eeeeee'})
    styler.map(lambda val: 'background-color: #feebe2' if str(val).upper().strip() == "URGENT ROTATION" else '', subset=['Rotation Priority'])
    return styler

display_cols = ["Vehicle Name", "Current Location", "Vehicle Description", "Monthly Miles Actual", "Rotation Priority", "Utilization Tier"]
available_cols = [c for c in display_cols if c in df.columns]

if not df.empty:
    st.dataframe(df[available_cols].style.pipe(apply_geotab_styles), use_container_width=True, hide_index=True)

# --- ANALYSIS ENGINE ---
if run_analysis:
    st.toast("Analyzing Fleet Trends...")
    df_analysis = df.copy()
    urgent = df_analysis[df_analysis['Rotation Priority'].astype(str).str.upper().str.strip() == 'URGENT ROTATION']
    underused = df_analysis[df_analysis['Utilization Tier'].astype(str).str.upper().str.contains('UNDERUSED', na=False)]
    
    if not urgent.empty and not underused.empty:
        st.subheader("💡 AI Recommended Swaps")
        recs = []
        updates = []

        for i in range(min(len(urgent), len(underused))):
            v_u, v_l = urgent.iloc[i], underused.iloc[i]
            dist = get_distance(v_u['Current Location'], v_l['Current Location'])
            
            recs.append({
                "Priority Asset": v_u['Vehicle Name'],
                "Current Site": v_u['Current Location'],
                "Target Site": v_l['Current Location'],
                "Distance": dist,
                "Swap With": v_l['Vehicle Name']
            })
            updates.append({'row_id': v_u['row_id'], 'suggestion': f"Swap with {v_l['Vehicle Name']} {dist}"})
        
        st.dataframe(pd.DataFrame(recs), use_container_width=True, hide_index=True)
        st.session_state['pending_updates_list'] = updates
    else:
        st.warning("No matches found.")

# --- SYNC ENGINE ---
if sync_data and 'pending_updates_list' in st.session_state:
    today = datetime.now().strftime("%Y-%m-%d")
    rows_to_update = []
    for update in st.session_state['pending_updates_list']:
        new_row = ss_client.models.Row(id=int(update['row_id']))
        new_row.cells.append(ss_client.models.Cell(column_id=COL_ID_SUGGESTED_SWAP, value=update['suggestion']))
        new_row.cells.append(ss_client.models.Cell(column_id=COL_ID_DATE_SWAP, value=today))
        rows_to_update.append(new_row)
    
    try:
        ss_client.Sheets.update_rows(sheet_id, rows_to_update)
        st.success("Synced successfully!")
    except Exception as e:
        st.error(f"Sync failed: {e}")

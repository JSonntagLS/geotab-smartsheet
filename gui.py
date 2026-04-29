import streamlit as st
import smartsheet
import pandas as pd
from datetime import datetime

# --- CONFIGURATION ---
# Mapping the IDs you found to variables for the write-back function
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
    ("Sioux City, IA", "Mitchell, SD"): 135,
    ("Sioux City, IA", "Yankton, SD"): 65,
    ("Cedar Falls, IA", "Mason City, IA"): 75,
}

def get_distance(loc1, loc2):
    # Check both directions in the matrix
    dist = DISTANCE_MATRIX.get((loc1, loc2)) or DISTANCE_MATRIX.get((loc2, loc1))
    return f"({dist} miles)" if dist else ""

# --- APP UI ---
st.set_page_config(page_title="LifeServe Fleet Matrix", layout="wide")
st.title("🚐 LifeServe Fleet Rotation Command Center")
st.markdown("---")

@st.cache_data(ttl=60)
def fetch_smartsheet_data():
    sheet = ss_client.Sheets.get_sheet(sheet_id)
    columns = [col.title for col in sheet.columns]
    rows = []
    for row in sheet.rows:
        # We store the Row ID so we know exactly which row to update later
        cells = {columns[i]: cell.value for i, cell in enumerate(row.cells)}
        cells['row_id'] = row.id 
        rows.append(cells)
    return pd.DataFrame(rows)

df = fetch_smartsheet_data()

# Update display list to match your actual Smartsheet column names
display_cols = [
    "Vehicle Name", "Current Location", "Vehicle Description", 
    "Monthly Miles Actual", "Projected Monthly Usage", "Monthly Allowance", 
    "Weekly Trend", "Rotation Priority", "Utilization Tier",
    "Suggested Swap", "Date of Suggest Swap"
]

available_cols = [c for c in display_cols if c in df.columns]

# --- MAIN DASHBOARD ---
st.subheader("Live Fleet Status")

def color_priority(val):
    if val == "URGENT ROTATION": return 'background-color: #ffcccc'
    if val == "Consider Rotating": return 'background-color: #fff4cc'
    return ''

if not df.empty:
    # Use .map() instead of .applymap() for compatibility with newer Pandas
    styled_df = df[available_cols].style.map(color_priority, subset=['Rotation Priority'])
    st.dataframe(styled_df, use_container_width=True, hide_index=True)
else:
    st.warning("Data loaded, but requested columns were not found.")

# --- ANALYSIS ENGINE ---
st.sidebar.header("Matrix Actions")

if st.sidebar.button("🔍 Run Swap Analysis"):
    st.sidebar.info("Analyzing Fleet...")
    
    df['Rotation Priority'] = df['Rotation Priority'].astype(str).str.upper().str.strip()
    df['Utilization Tier'] = df['Utilization Tier'].astype(str).str.upper().str.strip()
    
    urgent_vehicles = df[(df['Rotation Priority'] == 'URGENT ROTATION') & (df['Vehicle Lock'] != True)].copy()
    underused_vehicles = df[df['Utilization Tier'].str.contains('UNDERUSED', na=False) & (df['Vehicle Lock'] != True)].copy()
    
    if not urgent_vehicles.empty:
        st.subheader("💡 AI Recommended Swaps")
        pending_updates = []

        for i in range(min(len(urgent_vehicles), len(underused_vehicles))):
            urgent = urgent_vehicles.iloc[i]
            underused = underused_vehicles.iloc[i]
            
            # Get distance between current location and target location
            dist_text = get_distance(urgent['Current Location'], underused['Current Location'])
            
            suggestion = f"Swap with {underused['Vehicle Name']} {dist_text}"
            
            st.success(f"**Recommendation {i+1}:** Move **{urgent['Vehicle Name']}** to **{underused['Current Location']}** {dist_text}.")
            st.write(f"Pairing {urgent['Utilization Tier']} with {underused['Utilization Tier']}.")
            st.divider()

            pending_updates.append({
                'row_id': urgent['row_id'],
                'suggestion': suggestion
            })
        
        st.session_state['pending_updates_list'] = pending_updates
        st.sidebar.success(f"Analysis Complete: {len(pending_updates)} matches found.")
    else:
        st.sidebar.warning("No 'URGENT' vehicles found.")

# --- SYNC ENGINE ---
if st.sidebar.button("🚀 Sync to Smartsheet"):
    if 'pending_updates_list' in st.session_state:
        today = datetime.now().strftime("%Y-%m-%d")
        rows_to_update = []

        for update in st.session_state['pending_updates_list']:
            new_row = ss_client.models.Row()
            # Convert to int to prevent the ValueError
            new_row.id = int(update['row_id']) 
            
            cell_swap = ss_client.models.Cell()
            cell_swap.column_id = COL_ID_SUGGESTED_SWAP
            cell_swap.value = update['suggestion']
            
            cell_date = ss_client.models.Cell()
            cell_date.column_id = COL_ID_DATE_SWAP
            cell_date.value = today
            
            new_row.cells.extend([cell_swap, cell_date])
            rows_to_update.append(new_row)
        
        try:
            # Bulk update to Smartsheet
            ss_client.Sheets.update_rows(sheet_id, rows_to_update)
            st.sidebar.success(f"Synced {len(rows_to_update)} rows to Smartsheet!")
            st.cache_data.clear() 
        except Exception as e:
            st.sidebar.error(f"Smartsheet Sync Error: {e}")
    else:
        st.sidebar.error("Run Analysis first!")

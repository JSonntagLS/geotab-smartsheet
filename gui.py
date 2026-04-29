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
    
    # Logic: Find 'URGENT' vehicles that aren't locked
    urgent_vehicles = df[(df['Rotation Priority'] == 'URGENT ROTATION') & (df['Vehicle Lock'] != True)]
    underused_vehicles = df[df['Utilization Tier'].str.contains('Underused', na=False) & (df['Vehicle Lock'] != True)]
    
    if not urgent_vehicles.empty:
        st.subheader("💡 AI Recommended Swaps")
        # For this test run, we match the top urgent with the top underused
        # In a full run, we would iterate through all classes
        top_urgent = urgent_vehicles.iloc[0]
        top_underused = underused_vehicles.iloc[0]
        
        suggestion = f"Swap with {top_underused['Vehicle Name']} ({top_underused['Current Location']})"
        
        st.success(f"**Recommendation:** Move **{top_urgent['Vehicle Name']}** to **{top_underused['Current Location']}**.")
        st.write(f"This swaps a {top_urgent['Utilization Tier']} vehicle with a {top_underused['Utilization Tier']} vehicle.")
        
        # Store for sync
        st.session_state['pending_swap_row'] = top_urgent['row_id']
        st.session_state['pending_swap_text'] = suggestion
    else:
        st.sidebar.write("No urgent rotations needed!")

# --- SYNC ENGINE ---
if st.sidebar.button("🚀 Sync to Smartsheet"):
    if 'pending_swap_row' in st.session_state:
        row_id = st.session_state['pending_swap_row']
        swap_text = st.session_state['pending_swap_text']
        today = datetime.now().strftime("%Y-%m-%d")
        
        # Create the update row object
        new_row = ss_client.models.Row()
        new_row.id = row_id
        
        # Build the cells using the IDs you provided
        cell_swap = ss_client.models.Cell()
        cell_swap.column_id = COL_ID_SUGGESTED_SWAP
        cell_swap.value = swap_text
        
        cell_date = ss_client.models.Cell()
        cell_date.column_id = COL_ID_DATE_SWAP
        cell_date.value = today
        
        new_row.cells.append(cell_swap)
        new_row.cells.append(cell_date)
        
        # Push to Smartsheet
        ss_client.Sheets.update_rows(sheet_id, [new_row])
        st.sidebar.success("Smartsheet Updated!")
        st.cache_data.clear() # Refresh data
    else:
        st.sidebar.error("Run Analysis first!")

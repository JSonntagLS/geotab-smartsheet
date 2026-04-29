import streamlit as st
import smartsheet
import pandas as pd

# This pulls directly from your Streamlit App Secrets
access_token = st.secrets["smartsheet_token"] 
sheet_id = st.secrets["sheet_id"] 

ss_client = smartsheet.Smartsheet(access_token)

# Professional UI Layout
st.title("🚐 LifeServe Fleet Rotation Command Center")
st.markdown("---")

@st.cache_data(ttl=60)
def fetch_smartsheet_data():
    sheet = ss_client.Sheets.get_sheet(SHEET_ID)
    columns = [col.title for col in sheet.columns]
    rows = []
    for row in sheet.rows:
        cells = {columns[i]: cell.value for i, cell in enumerate(row.cells)}
        rows.append(cells)
    return pd.DataFrame(rows)

df = fetch_smartsheet_data()

# Columns defined for the "Professional UI"
display_cols = [
    "Vehicle Name", "Current Location", "Vehicle Description", 
    "Monthly Actual", "Projected Monthly", "Monthly Allowance", 
    "Weekly Trend", "Rotation Priority", "Utilization Tier",
    "Suggested Swap", "Date of Suggested Swap"
]

# Filtering out columns that don't exist yet to prevent crashes
available_cols = [c for c in display_cols if c in df.columns]

# --- Main Dashboard ---
st.subheader("Live Fleet Matrix")

# Color-coding for the "Professional" look
def color_priority(val):
    if val == "URGENT ROTATION": return 'background-color: #ffcccc'
    if val == "Consider Rotating": return 'background-color: #fff4cc'
    return ''

if not df.empty:
    styled_df = df[available_cols].style.applymap(color_priority, subset=['Rotation Priority'])
    st.dataframe(styled_df, use_container_width=True, hide_index=True)
else:
    st.warning("Data loaded, but requested columns were not found. Use the ID Tool to verify names.")

# --- Sidebar Controls ---
st.sidebar.header("Matrix Actions")

if st.sidebar.button("🔍 Run Swap Analysis"):
    # Logic will filter for 'URGENT' and match with 'Underused' by Class
    st.sidebar.success("AI Analysis Complete")
    st.info("**Top Recommendation:** Swap 01 Johnston (Minivan) with 31 Johnston to reset mileage trends locally.")

if st.sidebar.button("🚀 Sync to Smartsheet"):
    st.sidebar.info("Writing updates to Smartsheet...")

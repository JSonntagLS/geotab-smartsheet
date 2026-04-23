import streamlit as st
import mygeotab
import pandas as pd
import smartsheet

# 1. Setup Page
st.set_page_config(page_title="Lease Rotation Engine", layout="wide")
st.title("🚜 Geotab Mileage Sync")

# 2. Authentication Function
def get_geotab_api():
    try:
        api = mygeotab.API(
            username=st.secrets["GEOTAB_USER"],
            password=st.secrets["GEOTAB_PASSWORD"],
            database=st.secrets["GEOTAB_DB"]
        )
        api.authenticate()
        return api
    except mygeotab.AuthenticationException:
        st.error("Authentication failed. Ensure the user is set to 'Basic Authentication' in Geotab.")
        return None
    except Exception as e:
        st.error(f"Geotab Error: {e}")
        return None

# 3. Smartsheet Sync Function
def sync_to_smartsheet(df):
    try:
        # Initialize client
        smart = smartsheet.Smartsheet(st.secrets["SMARTSHEET_TOKEN"])
        sheet_id = int(st.secrets["SMARTSHEET_ID"])
        sheet = smart.Sheets.get_sheet(sheet_id)
        
        # Build a map of column titles to IDs, cleaning up any accidental spaces
        columns = {col.title.strip(): col.id for col in sheet.columns}
        
        # Identify the Primary Column ID (usually where 'Vehicle Name' lives)
        primary_col_id = next(col.id for col in sheet.columns if col.primary)
        
        # Identify the Mileage Column ID
        mil_col_name = "Current Mileage"
        if mil_col_name not in columns:
            st.error(f"Could not find column '{mil_col_name}'. Found: {list(columns.keys())}")
            return
        
        mil_col_id = columns[mil_col_name]
        updated_rows = []
        
        # Match Geotab data to Smartsheet rows
        for index, row in df.iterrows():
            for s_row in sheet.rows:
                # Find the cell in the Primary Column
                veh_cell = next((c for c in s_row.cells if c.column_id == primary_col_id), None)
                
                # Compare Geotab name to Smartsheet cell value
                if veh_cell and str(veh_cell.value).strip() == str(row["Vehicle Name"]).strip():
                    new_row = smartsheet.models.Row()
                    new_row.id = s_row.id
                    
                    new_cell = smartsheet.models.Cell()
                    new_cell.column_id = mil_col_id
                    new_cell.value = row["Current Mileage"]
                    
                    new_row.cells.append(new_cell)
                    updated_rows.append(new_row)
        
        if updated_rows:
            smart.Sheets.update_rows(sheet_id, updated_rows)
            st.success(f"✅ Successfully updated {len(updated_rows)} vehicles in Smartsheet!")
        else:
            st.warning("Connected to sheet, but no matching Vehicle Names were found. Make sure the names in Geotab match Smartsheet exactly.")
            
    except Exception as e:
        st.error(f"Smartsheet Sync Error: {e}")

# 4. Main Execution
api = get_geotab_api()

if api:
    st.success("Connected to Geotab!")
    
    # Get basic device info
    devices = api.get('Device')
    
    # Pull both odometer types to ensure no 0s
    raw_odo = api.get('StatusData', search={'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 'resultsLimit': len(devices)})
    adj_odo = api.get('StatusData', search={'diagnosticSearch': {'id': 'DiagnosticOdometerAdjustmentId'}, 'resultsLimit': len(devices)})

    # Map the best available mileage to each device
    mileage_dict = {}
    for item in (raw_odo + adj_odo):
        dev_id = item['device']['id']
        miles = round(item['data'] / 1609.344, 0)
        if dev_id not in mileage_dict or miles > mileage_dict[dev_id]:
            mileage_dict[dev_id] = miles

    # Build the final list
    fleet_data = []
    for device in devices:
        fleet_data.append({
            "Vehicle Name": device['name'],
            "Serial": device['serialNumber'],
            "Current Mileage": mileage_dict.get(device['id'], 0)
        })

    # Create DataFrame and Sort
    df = pd.DataFrame(fleet_data).sort_values(by="Current Mileage", ascending=False)

    # 5. Display Dashboard
    st.subheader("📊 Current Fleet Mileage (from Geotab)")
    st.dataframe(df, use_container_width=True, hide_index=True)

    # 6. The Sync Button
    st.divider()
    if st.button("🔄 Sync Geotab Mileage to Smartsheet"):
        with st.spinner("Updating Smartsheet..."):
            sync_to_smartsheet(df)

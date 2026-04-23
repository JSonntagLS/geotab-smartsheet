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
        
        # Map Column Names to IDs from your sheet
        columns = {col.title: col.id for col in sheet.columns}
        
        # CRITICAL: These must match your Smartsheet column names exactly
        veh_col_name = "Vehicle Name"
        mil_col_name = "Current Mileage"
        
        if veh_col_name not in columns or mil_col_name not in columns:
            st.error(f"Could not find columns '{veh_col_name}' or '{mil_col_name}' in Smartsheet.")
            return

        veh_col_id = columns[veh_col_name]
        mil_col_id = columns[mil_col_name]
        
        updated_rows = []
        
        # Match Geotab data to Smartsheet rows
        for index, row in df.iterrows():
            for s_row in sheet.rows:
                # Get the value of the 'Vehicle Name' cell in this Smartsheet row
                veh_cell = next((c for c in s_row.cells if c.column_id == veh_col_id), None)
                
                if veh_cell and veh_cell.value == row["Vehicle Name"]:
                    # Create an update object for this row
                    new_row = smartsheet.models.Row()
                    new_row.id = s_row.id
                    
                    # Add the new mileage cell
                    new_cell = smartsheet.models.Cell()
                    new_cell.column_id = mil_col_id
                    new_cell.value = row["Current Mileage"]
                    new_cell.display_value = str(row["Current Mileage"])
                    
                    new_row.cells.append(new_cell)
                    updated_rows.append(new_row)
        
        if updated_rows:
            # Push the updates in bulk
            smart.Sheets.update_rows(sheet_id, updated_rows)
            st.success(f"✅ Successfully updated {len(updated_rows)} vehicles in Smartsheet!")
        else:
            st.warning("No matching vehicle names found between Geotab and Smartsheet.")
            
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

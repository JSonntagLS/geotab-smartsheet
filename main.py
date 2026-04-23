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
        smart = smartsheet.Smartsheet(st.secrets["SMARTSHEET_TOKEN"])
        sheet_id = int(st.secrets["SMARTSHEET_ID"])
        sheet = smart.Sheets.get_sheet(sheet_id)
        
        # 1. Map Columns
        columns = {col.title.strip(): col.id for col in sheet.columns}
        
        # Fix for the 'TypedList' error: explicitly find the Primary column ID
        primary_col_id = None
        for col in sheet.columns:
            if col.primary:
                primary_col_id = col.id
                break
        
        mil_col_name = "Current Mileage"
        mil_col_id = columns.get(mil_col_name)
        
        if not primary_col_id or not mil_col_id:
            st.error(f"Column mapping failed. Primary: {primary_col_id}, Mileage: {mil_col_id}")
            return

        updated_rows = []
        
        # 2. Match Logic
        for index, row in df.iterrows():
            geotab_name = str(row["Vehicle Name"]).strip().upper()
            
            for s_row in sheet.rows:
                # Find the cell that belongs to the primary column
                veh_cell = next((c for c in s_row.cells if c.column_id == primary_col_id), None)
                
                if veh_cell:
                    # Check both 'value' and 'display_value' for a match
                    ss_val = str(veh_cell.value if veh_cell.value is not None else veh_cell.display_value or "").strip().upper()
                    
                    if ss_val == geotab_name:
                        new_row = smartsheet.models.Row()
                        new_row.id = s_row.id
                        
                        new_cell = smartsheet.models.Cell()
                        new_cell.column_id = mil_col_id
                        new_cell.value = row["Current Mileage"]
                        new_cell.strict = False
                        
                        new_row.cells.append(new_cell)
                        updated_rows.append(new_row)
        
        # 3. Push Updates
        if updated_rows:
            smart.Sheets.update_rows(sheet_id, updated_rows)
            st.success(f"✅ Successfully updated {len(updated_rows)} vehicles in Smartsheet!")
        else:
            st.warning("No matches found. Ensure names in Smartsheet match Geotab exactly.")
            # This helps us debug if it fails again
            if len(sheet.rows) > 0:
                sample_ss = sheet.rows.cells.value or sheet.rows.cells.display_value
                st.info(f"Debug: Looking for '{geotab_name}' but found '{sample_ss}' in first SS row.")
            
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

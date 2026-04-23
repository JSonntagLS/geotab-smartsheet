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
        
        # --- DEBUG SECTION ---
        with st.expander("🔍 Connection Debugger"):
            st.write(f"Found {len(sheet.columns)} columns and {len(sheet.rows)} rows.")
            col_map = {col.title.strip(): col.id for col in sheet.columns}
            
            primary_col_id = next((col.id for col in sheet.columns if col.primary), None)
            mil_col_id = col_map.get("Current Mileage")
            ser_col_id = col_map.get("Serial")

        if not primary_col_id or not mil_col_id:
            st.error("Failed to map columns. Check spelling of 'Current Mileage'.")
            return

        updated_rows = []

        # --- MATCHING LOGIC ---
        for _, g_row in df.iterrows():
            geotab_name = str(g_row["Vehicle Name"]).strip().upper()
            
            for s_row in sheet.rows:
                # Find the primary cell in this row
                veh_cell = next((c for c in s_row.cells if c.column_id == primary_col_id), None)
                
                if veh_cell:
                    ss_val = str(veh_cell.value if veh_cell.value is not None else veh_cell.display_value or "").strip().upper()
                    
                    if ss_val == geotab_name:
                        new_row = smartsheet.models.Row()
                        new_row.id = s_row.id
                        
                        # FORCE MILEAGE: Sending as a string often bypasses "silent" rejection
                        mil_cell = smartsheet.models.Cell()
                        mil_cell.column_id = mil_col_id
                        mil_cell.value = str(int(g_row["Current Mileage"])) # Convert to string
                        mil_cell.strict = False 
                        
                        # FORCE SERIAL
                        ser_cell = smartsheet.models.Cell()
                        ser_cell.column_id = ser_col_id
                        ser_cell.value = str(g_row["Serial"])
                        ser_cell.strict = False
                        
                        new_row.cells.append(mil_cell)
                        new_row.cells.append(ser_cell)
                        updated_rows.append(new_row)

        # --- EXECUTION ---
        if updated_rows:
            # We use 'allow_partial_success' to see if some rows work while others fail
            response = smart.Sheets.update_rows(sheet_id, updated_rows)
            
            if response.message == 'SUCCESS':
                st.success(f"✅ Pushed {len(updated_rows)} updates to Smartsheet! Refresh your sheet now.")
            else:
                st.warning(f"Smartsheet responded with: {response.message}")
        else:
            st.warning("No matches found between Geotab names and Smartsheet names.")
            
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

import streamlit as st
import mygeotab
import pandas as pd
import smartsheet

# 1. Setup Page
st.set_page_config(page_title="Lease Rotation Engine", page_icon="🚜", layout="wide")
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
    except Exception as e:
        st.error(f"Geotab Connection Error: {e}")
        return None

# 3. Smartsheet Sync Function
def sync_to_smartsheet(df):
    try:
        smart = smartsheet.Smartsheet(st.secrets["SMARTSHEET_TOKEN"])
        sheet_id = int(st.secrets["SMARTSHEET_ID"])
        sheet = smart.Sheets.get_sheet(sheet_id)
        
        # Map Columns
        col_map = {col.title.strip(): col.id for col in sheet.columns}
        primary_col_id = next((col.id for col in sheet.columns if col.primary), None)
        mil_col_id = col_map.get("Current Mileage")
        ser_col_id = col_map.get("Serial")

        if not primary_col_id or not mil_col_id:
            st.error("Missing required columns in Smartsheet.")
            return

        updated_rows = []
        seen_row_ids = set()

        for _, g_row in df.iterrows():
            try:
                geotab_name = str(g_row["Vehicle Name"]).strip().upper()
                
                for s_row in sheet.rows:
                    if s_row.id in seen_row_ids:
                        continue

                    # Get Vehicle Name from Smartsheet
                    veh_cell = next((c for c in s_row.cells if c.column_id == primary_col_id), None)
                    if veh_cell:
                        ss_val = str(veh_cell.value or veh_cell.display_value or "").strip().upper()
                        
                        if ss_val == geotab_name:
                            new_row = smartsheet.models.Row()
                            new_row.id = s_row.id
                            
                            # Prepare Mileage Cell
                            mil_cell = smartsheet.models.Cell()
                            mil_cell.column_id = mil_col_id
                            mil_cell.value = int(float(g_row["Current Mileage"]))
                            mil_cell.strict = False
                            
                            # Prepare Serial Cell
                            ser_cell = smartsheet.models.Cell()
                            ser_cell.column_id = ser_col_id
                            ser_cell.value = str(g_row["Serial"])
                            
                            new_row.cells.extend([mil_cell, ser_cell])
                            updated_rows.append(new_row)
                            seen_row_ids.add(s_row.id)
                            break
            except:
                continue

        if updated_rows:
            result = smart.Sheets.update_rows(sheet_id, updated_rows)
            if isinstance(result, list) or (hasattr(result, 'message') and result.message == 'SUCCESS'):
                st.success(f"✅ Successfully updated {len(updated_rows)} vehicles in Smartsheet!")
            else:
                st.error("Update sent but Smartsheet returned an unexpected response.")
        else:
            st.warning("No matching vehicle names found between Geotab and Smartsheet.")
            
    except Exception as e:
        st.error(f"Critical Sync Error: {e}")

# 4. Main Execution
api = get_geotab_api()

if api:
    st.info("Authenticated with Geotab")
    
    # Data Fetching
    devices = api.get('Device')
    raw_odo = api.get('StatusData', search={'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 'resultsLimit': len(devices)})
    adj_odo = api.get('StatusData', search={'diagnosticSearch': {'id': 'DiagnosticOdometerAdjustmentId'}, 'resultsLimit': len(devices)})

    # Processing Mileage
    mileage_dict = {}
    for item in (raw_odo + adj_odo):
        dev_id = item['device']['id']
        miles = round(item['data'] / 1609.344, 0)
        if dev_id not in mileage_dict or miles > mileage_dict[dev_id]:
            mileage_dict[dev_id] = miles

    fleet_data = [{
        "Vehicle Name": d['name'],
        "Serial": d['serialNumber'],
        "Current Mileage": mileage_dict.get(d['id'], 0)
    } for d in devices]

    df = pd.DataFrame(fleet_data).sort_values(by="Current Mileage", ascending=False)

    # 5. UI
    st.subheader("📊 Live Fleet Overview")
    st.dataframe(df, use_container_width=True, hide_index=True)

    if st.button("🔄 Sync Geotab Mileage to Smartsheet", type="primary"):
        with st.spinner("Pushing updates..."):
            sync_to_smartsheet(df)

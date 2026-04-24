import streamlit as st
import mygeotab
import pandas as pd
import smartsheet
from datetime import datetime

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
        today_date = datetime.now().strftime("%Y-%m-%d")
        
        # --- DEBUGGER ---
        with st.expander("🔍 Connection & Column Debugger", expanded=True):
            col_map = {col.title.strip(): col.id for col in sheet.columns}
            st.write("Column IDs Found:", col_map)
            primary_col_id = next((col.id for col in sheet.columns if col.primary), None)
            mil_col_id = col_map.get("Current Mileage")
            ser_col_id = col_map.get("Serial")
            date_col_id = col_map.get("Last Sync Date")

        # 1. BUILD FAST LOOKUP
        ss_rows_lookup = {}
        for s_row in sheet.rows:
            veh_cell = next((c for c in s_row.cells if c.column_id == primary_col_id), None)
            if veh_cell:
                name_val = veh_cell.value if veh_cell.value is not None else veh_cell.display_value
                name = str(name_val or "").strip().upper()
                if name:
                    ss_rows_lookup[name] = s_row.id

        # 2. MATCHING WITH DUPLICATE PROTECTION (FIXES ERROR 1137)
        # We use a dictionary keyed by Row ID to ensure each row is only updated once
        final_updates_dict = {}

        for _, g_row in df.iterrows():
            geotab_name = str(g_row["Vehicle Name"]).strip().upper()
            
            if geotab_name in ss_rows_lookup:
                row_id = ss_rows_lookup[geotab_name]
                
                # If we haven't added this row yet, create the update
                if row_id not in final_updates_dict:
                    new_row = smartsheet.models.Row()
                    new_row.id = row_id
                    
                    c1 = smartsheet.models.Cell()
                    c1.column_id = mil_col_id
                    c1.value = str(int(float(g_row["Current Mileage"])))
                    
                    c2 = smartsheet.models.Cell()
                    c2.column_id = ser_col_id
                    c2.value = str(g_row["Serial"])
                    
                    c3 = smartsheet.models.Cell()
                    c3.column_id = date_col_id
                    c3.value = today_date
                    
                    new_row.cells.extend([c1, c2, c3])
                    final_updates_dict[row_id] = new_row

        # Convert dictionary values back to a list for the API
        updated_rows = list(final_updates_dict.values())

        # 3. EXECUTION
        if updated_rows:
            result = smart.Sheets.update_rows(sheet_id, updated_rows)
            
            # Flexible success check
            success = False
            if hasattr(result, 'message') and result.message == 'SUCCESS':
                success = True
            elif isinstance(result, list) or (hasattr(result, 'data') and isinstance(result.data, list)):
                success = True

            if success:
                st.success(f"✅ Successfully updated {len(updated_rows)} unique vehicles!")
            else:
                st.error("❌ Update failed. Check Raw Response below.")
                with st.expander("View Raw Smartsheet Response"):
                    st.write(result)
        else:
            st.warning("No matches found between Geotab and Smartsheet.")
            
    except Exception as e:
        st.error(f"🚨 Sync Error: {type(e).__name__} - {str(e)}")
        
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

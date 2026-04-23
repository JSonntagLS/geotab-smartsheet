import streamlit as st
import mygeotab
import pandas as pd
import smartsheet # Add this at the top

# ... (Keep your existing Page Setup and get_geotab_api function) ...

# 3. Smartsheet Update Function
def sync_to_smartsheet(df):
    try:
        smart = smartsheet.Smartsheet(st.secrets["SMARTSHEET_TOKEN"])
        sheet_id = int(st.secrets["SMARTSHEET_ID"])
        sheet = smart.Sheets.get_sheet(sheet_id)
        
        # Map Column Names to IDs
        columns = {col.title: col.id for col in sheet.columns}
        veh_col_id = columns.get("Vehicle Name")
        mil_col_id = columns.get("Current Mileage")
        
        updated_rows = []
        for index, row in df.iterrows():
            # Find the row in Smartsheet that matches the Vehicle Name
            for s_row in sheet.rows:
                # Check the cell in the "Vehicle Name" column
                veh_cell = next(c for c in s_row.cells if c.column_id == veh_col_id)
                
                if veh_cell.value == row["Vehicle Name"]:
                    # Create a new row object with the updated mileage
                    new_row = smartsheet.models.Row()
                    new_row.id = s_row.id
                    new_row.cells.append({
                        'column_id': mil_col_id,
                        'value': row["Current Mileage"]
                    })
                    updated_rows.append(new_row)
        
        if updated_rows:
            smart.Sheets.update_rows(sheet_id, updated_rows)
            st.success(f"Successfully updated {len(updated_rows)} vehicles in Smartsheet!")
        else:
            st.warning("No matching vehicles found in Smartsheet.")
            
    except Exception as e:
        st.error(f"Smartsheet Sync Error: {e}")

# ... (Keep your existing Data Pulling Logic) ...

if api:
    # ... (Keep the code that creates your 'df') ...
    
    st.dataframe(df, use_container_width=True, hide_index=True)

    # 5. The Final Sync Button
    if st.button("🔄 Sync Data to Smartsheet"):
        with st.spinner("Pushing data to Smartsheet..."):
            sync_to_smartsheet(df)

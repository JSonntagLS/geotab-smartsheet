import smartsheet
import streamlit as st

# Uses your existing secrets
access_token = st.secrets["smartsheet_token"]
sheet_id = st.secrets["sheet_id"]

def get_column_ids():
    ss_client = smartsheet.Smartsheet(access_token)
    try:
        sheet = ss_client.Sheets.get_sheet(sheet_id)
        st.write(f"### Column IDs for: {sheet.name}")
        
        # Creates a clean table of IDs for easy copying
        column_data = [{"Name": col.title, "ID": col.id} for col in sheet.columns]
        st.table(column_data)
        
    except Exception as e:
        st.error(f"Error accessing Smartsheet: {e}")

if __name__ == "__main__":
    st.title("Smartsheet Column ID Finder")
    get_column_ids()

import smartsheet
import streamlit as st

# Pulls credentials directly from your Streamlit secrets file
access_token = st.secrets["smartsheet_token"]
sheet_id = st.secrets["swaps_sheet_id"]

ss_client = smartsheet.Smartsheet(access_token)

try:
    sheet = ss_client.Sheets.get_sheet(int(sheet_id))
    print(f"\n--- COLUMN IDS FOR: {sheet.name} ---")
    for column in sheet.columns:
        print(f"Name: {column.title:30} | ID: {column.id}")
    print("-" * 50)
except Exception as e:
    print(f"Error accessing Smartsheet: {e}")

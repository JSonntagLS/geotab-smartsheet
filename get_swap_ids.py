import os
import smartsheet

access_token = os.environ.get('SMARTSHEET_TOKEN')
sheet_id = os.environ.get('SWAPS_SHEET_ID')  # Updated to match your new secret name

if not access_token or not sheet_id:
    print("Error: Missing SMARTSHEET_TOKEN or SWAPS_SHEET_ID in GitHub Secrets.")
    exit(1)

ss_client = smartsheet.Smartsheet(access_token)

try:
    sheet = ss_client.Sheets.get_sheet(int(sheet_id))
    print(f"\n--- COLUMN IDS FOR: {sheet.name} ---")
    for column in sheet.columns:
        print(f"Name: {column.title:30} | ID: {column.id}")
    print("-" * 50)
except Exception as e:
    print(f"Error accessing Smartsheet: {e}")

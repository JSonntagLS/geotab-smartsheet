import smartsheet
import os

# GitHub Actions will pass these from your secrets
access_token = os.getenv("SMARTSHEET_TOKEN")
sheet_id = os.getenv("SHEET_ID")

def get_column_ids():
    if not access_token or not sheet_id:
        print("Error: Missing SMARTSHEET_TOKEN or SHEET_ID in GitHub Secrets.")
        return

    ss_client = smartsheet.Smartsheet(access_token)
    
    try:
        sheet = ss_client.Sheets.get_sheet(int(sheet_id))
        print(f"\n--- COLUMN IDS FOR: {sheet.name} ---")
        for column in sheet.columns:
            print(f"Name: {column.title:30} | ID: {column.id}")
        print("-" * 50)
    except Exception as e:
        print(f"Error accessing Smartsheet: {e}")

if __name__ == "__main__":
    get_column_ids()

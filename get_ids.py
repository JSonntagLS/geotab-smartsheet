import smartsheet
import os

# Use os.environ.get to pull from the GitHub Action environment
access_token = os.environ.get('SMARTSHEET_TOKEN')
sheet_id = os.environ.get('SHEET_ID')

if not access_token or not sheet_id:
    print("Error: Missing SMARTSHEET_TOKEN or SHEET_ID in GitHub Secrets.")
    exit(1)

smartsheet_client = smartsheet.Smartsheet(access_token)
# ... rest of your code ...

def get_column_ids():
    if not access_token or not sheet_id:
        print("Error: Missing SMARTSHEET_TOKEN or SMARTSHEET_ID in GitHub Secrets.")
        return

    ss_client = smartsheet.Smartsheet(access_token)
    
    try:
        # The SDK expects a string or int; we'll ensure it's an int
        sheet = ss_client.Sheets.get_sheet(int(sheet_id))
        print(f"\n--- COLUMN IDS FOR: {sheet.name} ---")
        for column in sheet.columns:
            print(f"Name: {column.title:30} | ID: {column.id}")
        print("-" * 50)
    except Exception as e:
        print(f"Error accessing Smartsheet: {e}")

if __name__ == "__main__":
    get_column_ids()

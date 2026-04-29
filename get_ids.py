import smartsheet

# Initialize client
access_token = "YOUR_SMARTSHEET_API_TOKEN"
smartsheet_client = smartsheet.Smartsheet(access_token)
sheet_id = YOUR_SHEET_ID_HERE

def get_column_ids():
    sheet = smartsheet_client.Sheets.get_sheet(sheet_id)
    print(f"--- Column IDs for {sheet.name} ---")
    for column in sheet.columns:
        print(f"Name: {column.title} | ID: {column.id}")

if __name__ == "__main__":
    get_column_ids()

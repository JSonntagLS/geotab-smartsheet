import smartsheet
import os

def get_column_ids():
    smart = smartsheet.Smartsheet(os.getenv("SMARTSHEET_TOKEN"))
    sheet = smart.Sheets.get_sheet(os.getenv("SMARTSHEET_ID"))
    
    print(f"Column Mapping for: {sheet.name}")
    for column in sheet.columns:
        print(f"Column Name: {column.title} | ID: {column.id}")

if __name__ == "__main__":
    get_column_ids()

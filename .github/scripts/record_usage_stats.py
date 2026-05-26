import pandas as pd
import smartsheet
import os
from datetime import datetime

# Match the variable names exactly as they appear in your gui.py
access_token = os.environ.get('SMARTSHEET_TOKEN')
sheet_id = os.environ.get('SHEET_ID')

if not access_token or not sheet_id:
    print("Error: Missing SMARTSHEET_TOKEN or SHEET_ID environment variables.")
    exit(1)

smartsheet_client = smartsheet.Smartsheet(access_token)

try:
    # Converting to int to match gui.py logic
    sheet = smartsheet_client.Sheets.get_sheet(int(sheet_id))
    columns = [col.title for col in sheet.columns]
    rows = [[cell.value for cell in row.cells] for row in sheet.rows]
    df = pd.DataFrame(rows, columns=columns)
except Exception as e:
    print(f"Error accessing Smartsheet: {e}")
    exit(1)

target_col = "Utilization Tier"
lock_col = "Vehicle Lock"
labels = [
    "Highly Overused", "Moderately Overused", "Slightly Overused", 
    "Balanced", 
    "Slightly Underused", "Moderately Underused", "Highly Underused"
]

stats = {"Date": datetime.now().strftime("%Y-%m-%d")}
hist_file = "usage_history.csv" 

if target_col in df.columns:
    # Filter the dataframe to only include vehicles that are NOT locked
    if lock_col in df.columns:
        # Treats True, "True", "checked", or a checked checkbox indicator as locked
        filtered_df = df[~df[lock_col].astype(str).str.strip().str.lower().isin(['true', '1', 'checked'])]
    else:
        filtered_df = df

    raw_values = filtered_df[target_col].fillna("None").astype(str).str.strip().str.lower()
    for label in labels:
        stats[label] = int((raw_values == label.lower().strip()).sum())
    
    new_row = pd.DataFrame([stats])
    if os.path.exists(hist_file):
        history_df = pd.read_csv(hist_file)
        history_df = history_df[history_df['Date'] != stats['Date']]
        history_df = pd.concat([history_df, new_row], ignore_index=True)
    else:
        history_df = new_row
    
    history_df.to_csv(hist_file, index=False)
    print(f"Successfully recorded stats to {hist_file}")
else:
    print(f"ABORTING: Could not find '{target_col}'. Available: {df.columns.tolist()}")
    exit(1)

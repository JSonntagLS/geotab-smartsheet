import pandas as pd
import smartsheet
import os
from datetime import datetime

# Load from GitHub Secrets
token = os.environ["smartsheet_token"]
sid = os.environ["sheet_id"]

smart = smartsheet.Smartsheet(token)
sheet = smart.Sheets.get_sheet(sid)
columns = [col.title.strip() for col in sheet.columns]
rows = [[cell.value for cell in row.cells] for row in sheet.rows]
df = pd.DataFrame(rows, columns=columns)

# The column name must be EXACT
target_col = "Utilization Tier"

labels = [
    "Highly Overused", "Moderately Overused", "Slightly Overused", 
    "Balanced", 
    "Slightly Underused", "Moderately Underused", "Highly Underused"
]

stats = {"Date": datetime.now().strftime("%Y-%m-%d")}

if target_col in df.columns:
    # 1. Clean the Smartsheet data (Remove None, force string, strip, lowercase)
    raw_values = df[target_col].fillna("None").astype(str).str.strip().str.lower()
    
    # DEBUG: This will show up in your GitHub Action logs so we can see the data
    print(f"Unique values found in Smartsheet: {raw_values.unique()}")

    for label in labels:
        # 2. Match against a cleaned version of our labels
        match_count = (raw_values == label.lower().strip()).sum()
        stats[label] = int(match_count)
else:
    print(f"ERROR: Column '{target_col}' not found. Available: {columns}")
    for label in labels: stats[label] = 0

# --- SAVE LOGIC ---
hist_file = "usage_history.csv" 

# Check if we actually found data before saving
if target_col in df.columns and not df.empty:
    raw_values = df[target_col].fillna("None").astype(str).str.strip().str.lower()
    for label in labels:
        match_count = (raw_values == label.lower().strip()).sum()
        stats[label] = int(match_count)
    
    # Save Logic
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
    print(f"ABORTING: No data found in column '{target_col}'. Check your SHEET_ID secret.")

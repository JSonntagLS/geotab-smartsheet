import pandas as pd
import smartsheet
import os
from datetime import datetime

# Load from GitHub Secrets
token = os.environ["smartsheet_token"]
sid = os.environ["sheet_id"]

smart = smartsheet.Smartsheet(token)

# Re-matching the logic that works in your other scripts
try:
    sheet = smart.Sheets.get_sheet(sid)
    columns = [col.title for col in sheet.columns]
    rows = []
    for row in sheet.rows:
        rows.append([cell.value for cell in row.cells])
    df = pd.DataFrame(rows, columns=columns)
except Exception as e:
    print(f"Error loading sheet: {e}")
    df = pd.DataFrame()

# The column name from your Smartsheet
target_col = "Utilization Tier"

labels = [
    "Highly Overused", "Moderately Overused", "Slightly Overused", 
    "Balanced", 
    "Slightly Underused", "Moderately Underused", "Highly Underused"
]

stats = {"Date": datetime.now().strftime("%Y-%m-%d")}

# Define filename
hist_file = "usage_history.csv" 

if not df.empty and target_col in df.columns:
    # Clean data: handle Nones, strip whitespace, lowercase for matching
    raw_values = df[target_col].fillna("None").astype(str).str.strip().str.lower()
    
    for label in labels:
        # Match cleaned labels against cleaned data
        match_count = (raw_values == label.lower().strip()).sum()
        stats[label] = int(match_count)
    
    # Save Logic
    new_row = pd.DataFrame([stats])
    if os.path.exists(hist_file):
        history_df = pd.read_csv(hist_file)
        # Overwrite today's date if re-running manual tests
        history_df = history_df[history_df['Date'] != stats['Date']]
        history_df = pd.concat([history_df, new_row], ignore_index=True)
    else:
        history_df = new_row
    
    history_df.to_csv(hist_file, index=False)
    print(f"Successfully recorded stats to {hist_file}")
else:
    available = df.columns.tolist() if not df.empty else "No columns found"
    print(f"ABORTING: Could not find '{target_col}'. Available columns: {available}")

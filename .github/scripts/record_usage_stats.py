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

# MAPPING: This ensures we find the "Utilization Tier" column accurately
target_col = "Utilization Tier"

labels = [
    "Highly Overused", 
    "Moderately Overused", 
    "Slightly Overused", 
    "Balanced", 
    "Slightly Underused", 
    "Moderately Underused", 
    "Highly Underused"
]

stats = {"Date": datetime.now().strftime("%Y-%m-%d")}

# --- IMPROVED MATCHING LOGIC ---
if target_col in df.columns:
    # We strip spaces and force lowercase on both the data and the labels to ensure a match
    # This prevents zeros caused by trailing spaces like "Balanced "
    current_data = df[target_col].astype(str).str.strip().str.lower()
    
    for label in labels:
        count = len(current_data[current_data == label.lower().strip()])
        stats[label] = count
else:
    # If the script can't find the column, we'll know because all values will be 0
    for label in labels:
        stats[label] = 0

# --- CSV SAVE LOGIC ---
hist_file = "history.csv"
new_row = pd.DataFrame([stats])

if os.path.exists(hist_file):
    try:
        history_df = pd.read_csv(hist_file)
        # Remove any existing row for today if you are running manual tests
        history_df = history_df[history_df['Date'] != stats['Date']]
        history_df = pd.concat([history_df, new_row], ignore_index=True)
    except Exception:
        history_df = new_row
else:
    history_df = new_row

history_df.to_csv(hist_file, index=False)

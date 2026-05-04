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

# MAPPING: Matches the col_map in your Streamlit app
tier_column_name = "Utilization Tier"

# UPDATED CATEGORIES: Matches your new naming convention
labels = [
    "Highly Overused", 
    "Moderately Overused", 
    "Slightly Overused", 
    "Balanced", 
    "Slightly Underused", 
    "Moderately Underused", 
    "Highly Underused"
]

# Create current stats row
stats = {"Date": datetime.now().strftime("%Y-%m-%d")}

for label in labels:
    # Count occurrences in the 'Utilization Tier' column, stripping whitespace for accuracy
    if tier_column_name in df.columns:
        count = len(df[df[tier_column_name].astype(str).str.strip() == label])
    else:
        count = 0
    stats[label] = count

# Append to CSV
hist_file = "history.csv"
new_row = pd.DataFrame([stats])

if os.path.exists(hist_file):
    try:
        history_df = pd.read_csv(hist_file)
        history_df = pd.concat([history_df, new_row], ignore_index=True)
    except Exception:
        # If the CSV is corrupted or empty, start fresh with the new row
        history_df = new_row
else:
    history_df = new_row

# Save back to the root of the repository
history_df.to_csv(hist_file, index=False)

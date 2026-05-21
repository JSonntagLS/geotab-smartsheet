import streamlit as st
import pandas as pd
import requests
import os

st.set_page_config(layout="wide")
st.title("🚨 Detailed Fixed Recalls Registry")
st.markdown("This tool cross-references your logged completions against the live NHTSA database to pull deep data points.")

CSV_PATH = "fixed_recalls.csv"

@st.cache_data(ttl=600)
def fetch_nhtsa_details(make, model, year, campaign_id):
    """Queries the live NHTSA API for the detailed campaign parameters."""
    try:
        url = f"https://api.nhtsa.gov/recalls/recallsByVehicle?make={make}&model={model}&modelYear={year}"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            results = response.json().get('results', [])
            # Isolate the exact matching Campaign ID
            for recall in results:
                if str(recall.get('NHTSACampaignNumber', '')).strip() == str(campaign_id).strip():
                    return {
                        "Component": recall.get("Component", "N/A"),
                        "Summary": recall.get("Summary", "No Summary Provided"),
                        "Cone": recall.get("Cone", "No Consequence Stated"),
                        "Remedy": recall.get("Remedy", "No Remedy Listed")
                    }
    except Exception:
        pass
    return None

if os.path.exists(CSV_PATH):
    try:
        # Load your specific 5-column CSV file
        df_csv = pd.read_csv(CSV_PATH)
        
        if df_csv.empty:
            st.info("The fixed_recalls.csv file is currently empty.")
        else:
            st.metric(label="Total Tracked Resolved Campaigns", value=len(df_csv))
            
            detailed_records = []
            
            # Loop through each line of your CSV and enrich it via the API
            for idx, row in df_csv.iterrows():
                vin = str(row.get('VIN', 'N/A'))
                camp_id = str(row.get('CampaignID', 'N/A'))
                make = str(row.get('Make', ''))
                model = str(row.get('Model', ''))
                year = str(row.get('Year', ''))
                
                api_data = fetch_nhtsa_details(make, model, year, camp_id)
                
                if api_data:
                    detailed_records.append({
                        "VIN": vin,
                        "Campaign ID": camp_id,
                        "Vehicle": f"{year} {make} {model}",
                        "Affected Component": api_data["Component"],
                        "Defect Summary": api_data["Summary"],
                        "Risk / Consequence": api_data["Cone"],
                        "Corrective Remedy": api_data["Remedy"]
                    })
                else:
                    detailed_records.append({
                        "VIN": vin,
                        "Campaign ID": camp_id,
                        "Vehicle": f"{year} {make} {model}",
                        "Affected Component": "Unknown / Clear",
                        "Defect Summary": "Campaign details could not be mapped from public safety endpoints.",
                        "Risk / Consequence": "N/A",
                        "Corrective Remedy": "N/A"
                    })
            
            # Convert enriched data to a presentation dataframe
            df_display = pd.DataFrame(detailed_records)
            
            # Render a high-detail grid layout
            for idx, item in df_display.iterrows():
                with st.container():
                    col1, col2 = st.columns()
                    with col1:
                        st.subheader(f"🚗 {item['Vehicle']}")
                        st.code(f"VIN: {item['VIN']}\nCamp: {item['Campaign ID']}")
                        st.caption(f"**Component:** {item['Affected Component']}")
                    with col2:
                        st.markdown(f"**Defect Summary:**\n{item['Defect Summary']}")
                        st.markdown(f"**Consequences:**\n*{item['Risk / Consequence']}*")
                        st.markdown(f"**Remedy Fix:**\n{item['Corrective Remedy']}")
                    st.divider()
                    
    except Exception as e:
        st.error(f"Error executing retrieval matrix: {e}")
else:
    st.error(f"Could not locate '{CSV_PATH}' in the execution root directory.")

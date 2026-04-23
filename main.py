import streamlit as st
import mygeotab
import pandas as pd

# 1. Setup Page
st.set_page_config(page_title="Lease Rotation Engine", layout="wide")
st.title("🚜 Geotab Mileage Sync")

# 2. Authentication Function
def get_geotab_api():
    try:
        api = mygeotab.API(
            username=st.secrets["GEOTAB_USER"],
            password=st.secrets["GEOTAB_PASSWORD"],
            database=st.secrets["GEOTAB_DB"]
        )
        api.authenticate()
        return api
    except mygeotab.AuthenticationException:
        st.error("Authentication failed. Ensure the user is set to 'Basic Authentication' in Geotab.")
        return None
    except Exception as e:
        st.error(f"Geotab Error: {e}")
        return None

# 3. Execution Logic
api = get_geotab_api()

if api:
    st.success("Connected to Geotab!")
    
    # Get basic device info
    devices = api.get('Device')
    
    # Pull both odometer types to ensure we get data for all vehicles
    raw_odo = api.get('StatusData', search={'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 'resultsLimit': len(devices)})
    adj_odo = api.get('StatusData', search={'diagnosticSearch': {'id': 'DiagnosticOdometerAdjustmentId'}, 'resultsLimit': len(devices)})

    # Map the best available mileage (convert meters to miles)
    mileage_dict = {}
    for item in (raw_odo + adj_odo):
        dev_id = item['device']['id']
        miles = round(item['data'] / 1609.344, 0)
        # Use the highest value found for that vehicle
        if dev_id not in mileage_dict or miles > mileage_dict[dev_id]:
            mileage_dict[dev_id] = miles

    # Build the list for the table
    fleet_data = []
    for device in devices:
        fleet_data.append({
            "Vehicle Name": device['name'],
            "Serial": device['serialNumber'],
            "Current Mileage": mileage_dict.get(device['id'], 0)
        })

    # Create one single DataFrame and sort it
    df = pd.DataFrame(fleet_data).sort_values(by="Current Mileage", ascending=False)

    # 4. Display ONLY ONE clean table
    st.subheader("📊 Fleet Mileage Overview")
    st.dataframe(df, use_container_width=True, hide_index=True)

    # 5. The Sync Button
    if st.button("🔄 Sync Data to Smartsheet"):
        st.info("Geotab data ready. Waiting for Smartsheet Sheet ID and Column Names to finish the push logic.")

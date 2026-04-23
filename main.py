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
    except Exception as e:
        st.error(f"Geotab Authentication Failed: {e}")
        return None

# 3. Data Pulling Logic
api = get_geotab_api()

if api:
    st.success("Connected to Geotab!")
    
    # Get all vehicles and their current status (which includes odometer)
    # Note: 'DeviceStatusInfo' is often faster than searching full logs
    devices = api.get('Device')
    status_info = api.get('DeviceStatusInfo')

    # Create a simple list to hold our data
    fleet_data = []

    for device in devices:
        # Find the matching status info for this specific device ID
        status = next((s for s in status_info if s['device']['id'] == device['id']), None)
        
        odometer = 0
        if status and 'odometer' in status:
            # Geotab returns meters; convert to miles
            odometer = round(status['odometer'] / 1609.344, 0)

        fleet_data.append({
            "Vehicle Name": device['name'],
            "Serial": device['serialNumber'],
            "Current Mileage": odometer
        })

    # 4. Display in Dashboard
    df = pd.DataFrame(fleet_data)
    st.dataframe(df, use_container_width=True)

    if st.button("🔄 Manual Sync to Smartsheet"):
        st.warning("Next step: We need your Smartsheet ID to push this data!")

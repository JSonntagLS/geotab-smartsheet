import streamlit as st
import mygeotab
import pandas as pd

# 1. Setup Page
st.set_page_config(page_title="Lease Rotation Engine", layout="wide")
st.title("🚜 Geotab Mileage Sync")

# 2. Authentication Function
def get_geotab_api():
    try:
        # We start with 'my.geotab.com', and authenticate() 
        # will find the correct server (e.g., my3.geotab.com) for you.
        api = mygeotab.API(
            username=st.secrets["GEOTAB_USER"],
            password=st.secrets["GEOTAB_PASSWORD"],
            database=st.secrets["GEOTAB_DB"]
        )
        api.authenticate()
        return api
    except mygeotab.AuthenticationException:
        st.error("Authentication failed. Ensure the user is set to 'Basic Authentication' in Geotab and not SAML/SSO.")
        return None
    except Exception as e:
        st.error(f"Geotab Error: {e}")
        return None

# 3. Data Pulling Logic
api = get_geotab_api()

if api:
    st.success("Connected to Geotab!")
    
    devices = api.get('Device')
    
    # 1. Pull BOTH types of odometer data to cover all vehicle types
    raw_odo = api.get('StatusData', search={'diagnosticSearch': {'id': 'DiagnosticOdometerId'}, 'resultsLimit': len(devices)})
    adj_odo = api.get('StatusData', search={'diagnosticSearch': {'id': 'DiagnosticOdometerAdjustmentId'}, 'resultsLimit': len(devices)})

    # 2. Create a mapping (Meters to Miles)
    mileage_dict = {}
    for item in (raw_odo + adj_odo):
        dev_id = item['device']['id']
        miles = round(item['data'] / 1609.344, 0)
        # Only update if we don't have a value yet or if this value is higher
        if dev_id not in mileage_dict or miles > mileage_dict[dev_id]:
            mileage_dict[dev_id] = miles

    # 3. Build the Single Fleet Table
    fleet_data = []
    for device in devices:
        fleet_data.append({
            "Vehicle Name": device['name'],
            "Serial": device['serialNumber'],
            "Current Mileage": mileage_dict.get(device['id'], 0)
        })

    df = pd.DataFrame(fleet_data).sort_values(by="Current Mileage", ascending=False)
    
    # Display ONLY ONE table
    st.subheader("📊 Fleet Mileage Overview")
    st.dataframe(df, use_container_width=True, hide_index=True)
    df = pd.DataFrame(fleet_data)
    
    # Let's sort it so the high-mileage ones are at the top
    df = df.sort_values(by="Current Mileage", ascending=False)
    
    st.dataframe(df, use_container_width=True)

    # 4. Display in Dashboard
    df = pd.DataFrame(fleet_data)
    st.dataframe(df, use_container_width=True)

    if st.button("🔄 Manual Sync to Smartsheet"):
        st.warning("Next step: We need your Smartsheet ID to push this data!")

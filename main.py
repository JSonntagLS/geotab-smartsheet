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
    
    # NEW: Let's pull the latest Odometer Status specifically for all vehicles
    # This diagnostic ID is the standard for raw odometer readings
    odometer_data = api.get('StatusData', search={
        'diagnosticSearch': {'id': 'DiagnosticOdometerId'},
        'resultsLimit': len(devices)
    })

    # Create a mapping of Device ID -> Odometer Value
    # Geotab returns this in meters, so we'll convert to miles
    mileage_dict = {
        item['device']['id']: round(item['data'] / 1609.344, 0) 
        for item in odometer_data if 'data' in item
    }

    fleet_data = []
    for device in devices:
        # Get mileage from our new dictionary, default to 0 if not found
        current_mileage = mileage_dict.get(device['id'], 0)

        fleet_data.append({
            "Vehicle Name": device['name'],
            "Serial": device['serialNumber'],
            "Current Mileage": current_mileage
        })

    df = pd.DataFrame(fleet_data)
    
    # Let's sort it so the high-mileage ones are at the top
    df = df.sort_values(by="Current Mileage", ascending=False)
    
    st.dataframe(df, use_container_width=True)

    # 4. Display in Dashboard
    df = pd.DataFrame(fleet_data)
    st.dataframe(df, use_container_width=True)

    if st.button("🔄 Manual Sync to Smartsheet"):
        st.warning("Next step: We need your Smartsheet ID to push this data!")

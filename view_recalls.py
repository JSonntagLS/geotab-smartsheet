import streamlit as st
import pandas as pd
import os

st.set_page_config(layout="wide")
st.title("Fixed Recalls Archive Viewer")

CSV_PATH = "fixed_recalls.csv"

if os.path.exists(CSV_PATH):
    try:
        df = pd.read_csv(CSV_PATH)
        st.metric(label="Total Logged Fixed Records", value=len(df))
        st.dataframe(df, use_container_width=True, hide_index=True)
    except Exception as e:
        st.error(f"Error reading {CSV_PATH}: {e}")
else:
    st.error(f"Could not locate '{CSV_PATH}' in the current working directory.")

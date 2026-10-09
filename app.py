import streamlit as st
import subprocess
import os

st.set_page_config(layout="centered")
st.title("📊 QuickSight Dashboard Migration Tool")

with st.expander("⚠️ Prerequisites", expanded=False):
    st.markdown("""
    - Make sure you have configured the AWS profiles using 
    `aws configure sso --profile dev` & 
    `aws configure sso --profile prod`.
    - Ensure the Dataset exists in the target account!
    """)

# Initialize session states
if "step1_logs" not in st.session_state:
    st.session_state.step1_logs = ""
if "step2_logs" not in st.session_state:
    st.session_state.step2_logs = ""

def run_subprocess(command, log_key):
    st.session_state[log_key] = ""
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in process.stdout:
        st.session_state[log_key] += line
        st.write(line.strip())
    process.wait()
    return process.returncode

# Step 1 – Generate Mapping File
with st.expander("Step 1: Generate Dataset Mapping", expanded=True):
    col1, col2 = st.columns(2)
    with col1:
        source_profile = st.text_input("Source Profile", value="prod")
        source_account = st.text_input("Source Account ID")
    with col2:
        target_profile = st.text_input("Target Profile", value="dev")
        target_account = st.text_input("Target Account ID")

    analysis_name = st.text_input("Analysis Name")
    mapping_file = st.text_input("Output Mapping File", value="prod_to_dev_mapping.json")

    if st.button("🔍 Generate Mapping File"):
        if not (source_account and target_account and analysis_name):
            st.error("Please fill in all required fields.")
        else:
            cmd = [
                "python", "generate_mapping.py",
                "--source-profile", source_profile,
                "--source-account", source_account,
                "--target-profile", target_profile,
                "--target-account", target_account,
                "--analysis-name", analysis_name,
                "--output-file", mapping_file
            ]
            st.write("📄 Running mapping generation...")
            return_code = run_subprocess(cmd, "step1_logs")
            if return_code == 0:
                st.success("✅ Mapping generation complete.")
            else:
                st.error("❌ Failed to generate mapping. Check logs below.")

    if st.session_state.step1_logs:
        st.text_area("Step 1 Logs", st.session_state.step1_logs, height=200)

# Step 2 – Migrate Dashboard
with st.expander("Step 2: Migrate Dashboard", expanded=True):
    st.caption("Migration uses the source and target profiles entered in Step 1.")
    dashboard_name = st.text_input("Target Dashboard Name")

    if st.button("🚀 Migrate Dashboard"):
        if not (dashboard_name and mapping_file and analysis_name):
            st.error("Please provide dashboard name, mapping file, and analysis name.")
        else:
            cmd = [
                "python", "migrate_dashboard.py",
                "--source-profile", source_profile,
                "--target-profile", target_profile,
                "--analysis-name", analysis_name,
                "--dashboard-name", dashboard_name,
                "--mapping-file", mapping_file,
                 "--confirm"
            ]
            st.write("🛠️ Starting dashboard migration...")
            return_code = run_subprocess(cmd, "step2_logs")
            if return_code == 0:
                st.success("✅ Dashboard migration complete.")
            else:
                st.error("❌ Dashboard migration failed. Check logs below.")

    if st.session_state.step2_logs:
        st.text_area("Step 2 Logs", st.session_state.step2_logs, height=300)

import streamlit as st
import os
import logging
from datetime import datetime
from typing import List

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, filename="app.log", filemode="a", format="%(asctime)s - %(levelname)s - %(message)s", encoding="utf-8")

# Custom CSS for modern, colorful styling
st.markdown("""
    <style>
    /* Global styles */
    .stApp {
        background: linear-gradient(135deg, #1e1e2f 0%, #2a2a4a 100%);
        color: #e0e0e0;
        font-family: 'Segoe UI', sans-serif;
    }

    /* Tab styling */
    .stTabs [data-baseweb="tab-list"] {
        background: #2c2c4e;
        border-radius: 10px;
        padding: 5px;
    }
    .stTabs [data-baseweb="tab"] {
        color: #a0a0c0;
        font-weight: 500;
        border-radius: 8px;
        margin: 5px;
        padding: 10px 20px;
        transition: all 0.3s ease;
    }
    .stTabs [data-baseweb="tab"][aria-selected="true"] {
        background: linear-gradient(45deg, #6366f1, #a855f7);
        color: #ffffff;
        font-weight: 600;
        box-shadow: 0 2px 5px rgba(0,0,0,0.2);
    }
    .stTabs [data-baseweb="tab"]:hover {
        background: #3b3b5e;
        color: #ffffff;
    }

    /* Card styling */
    .stContainer {
        background: linear-gradient(145deg, #2a2a4a, #3b3b5e);
        border-radius: 15px;
        padding: 20px;
        margin-bottom: 20px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.3);
        border: 1px solid rgba(99, 102, 241, 0.2);
        transition: transform 0.2s ease;
    }
    .stContainer:hover {
        transform: translateY(-5px);
    }

    /* Buttons */
    .stButton > button {
        background: linear-gradient(45deg, #6366f1, #a855f7);
        color: white;
        border: none;
        border-radius: 8px;
        padding: 10px 20px;
        font-weight: 500;
        transition: all 0.3s ease;
    }
    .stButton > button:hover {
        background: linear-gradient(45deg, #8183ff, #c084fc);
        box-shadow: 0 2px 8px rgba(0,0,0,0.3);
    }

    /* Metrics */
    .stMetric {
        background: rgba(255,255,255,0.05);
        border-radius: 8px;
        padding: 10px;
        margin: 5px 0;
    }
    .stMetric label {
        color: #a0a0c0;
        font-size: 14px;
    }
    .stMetric .stMetricValue {
        color: #ffffff;
        font-weight: 600;
    }

    /* Info and error messages */
    .stAlert {
        border-radius: 8px;
        background: rgba(255,255,255,0.1);
        color: #ffffff;
    }

    /* Selectbox and inputs */
    .stSelectbox, .stNumberInput {
        background: #3b3b5e;
        border-radius: 8px;
        padding: 5px;
    }
    .stSelectbox > div > div, .stNumberInput > div > div {
        color: #ffffff;
    }

    /* Text area */
    .stTextArea textarea {
        background: rgba(255,255,255,0.05);
        color: #ffffff;
        border-radius: 8px;
    }
    </style>
""", unsafe_allow_html=True)

def display_log_stats(log_file: str, container, refresh_key: str):
    """Display log statistics in a reusable way."""
    try:
        if not os.path.exists(log_file) or not os.access(log_file, os.R_OK):
            container.warning("⚠️ No log file found or file is not readable")
            return

        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()

        # Count log levels
        error_count = sum(1 for line in all_lines if "ERROR" in line.upper())
        warning_count = sum(1 for line in all_lines if "WARNING" in line.upper())
        info_count = sum(1 for line in all_lines if "INFO" in line.upper())
        debug_count = sum(1 for line in all_lines if "DEBUG" in line.upper())

        # Display metrics
        col1, col2, col3, col4 = container.columns(4)
        with col1:
            container.metric("Total Lines", len(all_lines))
        with col2:
            container.metric("Errors", error_count, delta=f"{error_count}", delta_color="inverse")
        with col3:
            container.metric("Warnings", warning_count, delta=f"{warning_count}", delta_color="inverse")
        with col4:
            container.metric("Info", info_count)
            container.metric("Debug", debug_count)

        # Recent log entries
        recent_lines = all_lines[-10:]  # Last 10 lines for recent activity
        if recent_lines:
            container.markdown("**Recent Log Entries**")
            log_text = "".join(recent_lines)
            container.text_area("Recent Logs", log_text, height=150, key=f"recent_log_area_{refresh_key}")
        else:
            container.info("🌙 No recent log entries")

        if container.button("🔄 Refresh Statistics", key=refresh_key):
            st.rerun()

    except Exception as e:
        logger.error(f"Error reading log statistics for {log_file}: {e}")
        container.error(f"🚨 Error reading log statistics: {e}")

def show_logs():
    """Display application logs with tabs and card-based layout"""
    st.title("📋 Application Logs")

    # Define tabs
    logs_tab, stats_tab = st.tabs(["📜 Logs", "📊 Statistics"])

    # Logs tab
    with logs_tab:
        with st.container(border=True):
            st.markdown("### Log Filters")
            col1, col2 = st.columns(2)
            with col1:
                log_level = st.selectbox("Log Level", ["ALL", "DEBUG", "INFO", "WARNING", "ERROR"], index=2, key="log_level")
            with col2:
                max_lines = st.number_input("Max Lines", min_value=1, max_value=1000, value=100, step=10, key="max_lines")
            if st.button("🔄 Refresh Logs", key="refresh_logs"):
                st.rerun()

            try:
                log_file = "app.log"
                if os.path.exists(log_file) and os.access(log_file, os.R_OK):
                    with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                        lines = f.readlines()
                    if log_level != "ALL":
                        lines = [line for line in lines if log_level in line.upper()]
                    lines = lines[-max_lines:]  # Limit to max_lines
                    if lines:
                        log_text = "".join(lines)
                        with st.container(border=True):
                            st.markdown("### Logs")
                            st.text_area("Logs", log_text, height=400, key="log_text")
                            st.download_button(
                                label="📥 Download Logs",
                                data=log_text,
                                file_name=f"app_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                                mime="text/plain",
                                key="download_logs"
                            )
                    else:
                        st.info("🌙 No logs found matching the selected criteria")
                else:
                    st.warning("⚠️ Log file not found or not readable. Logs will appear after application activity.")
            except Exception as e:
                logger.error(f"Error displaying logs: {e}")
                st.error(f"🚨 Error displaying logs: {e}")

    # Statistics tab
    with stats_tab:
        with st.container(border=True):
            st.markdown("### 📊 Log Statistics")
            display_log_stats("app.log", st, "refresh_stats")

# Run the app
show_logs()
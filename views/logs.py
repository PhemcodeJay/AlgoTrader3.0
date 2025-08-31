import streamlit as st
import os
import logging
from datetime import datetime
from typing import List
from utils import display_log_stats

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, filename="app.log", filemode="a", format="%(asctime)s - %(levelname)s - %(message)s", encoding="utf-8")

def show_logs():
    st.title("📋 Application Logs")
    st.markdown("""
        <style>
        .stApp {
            background: linear-gradient(135deg, #1e1e2f 0%, #2a2a4a 100%);
            color: #e0e0e0;
            font-family: 'Segoe UI', sans-serif;
        }
        .stTabs [data-baseweb="tab-list"] {
            background: #2c2c4e;
            border-radius: 10px;
            padding: 5px;
        }
        .stTabs [data-baseweb="tab"] {
            color: #a0a0c0;
            font-weight: 400;
            border-radius: 8px;
            margin: 5px;
            padding: 10px 20px;
            transition: all 0.3s ease;
        }
        .stTabs [data-baseweb="tab"][aria-selected="true"] {
            background: linear-gradient(45deg, #6366f1, #a855f7);
            color: #ffffff;
            font-weight: 400;
            box-shadow: 0 2px 5px rgba(0,0,0,0.2);
        }
        .stTabs [data-baseweb="tab"]:hover {
            background: #3b3b5e;
            color: #ffffff;
        }
        .stContainer {
            background: linear-gradient(145deg, #2a2a4a, #3b3b5e);
            border-radius: 15px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.3);
            border: 1px solid rgba(99, 102, 241, 0.2);
        }
        .stTextArea textarea {
            background: rgba(255,255,255,0.05);
            color: #ffffff;
            border-radius: 8px;
        }
        </style>
    """, unsafe_allow_html=True)

    logs_tab, stats_tab = st.tabs(["📜 Logs", "📊 Statistics"])
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
                    lines = lines[-max_lines:]
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
                    st.warning("⚠️ Log file not found or not readable")
            except Exception as e:
                logger.error(f"Error displaying logs: {e}")
                st.error(f"🚨 Error displaying logs: {e}")

    with stats_tab:
        with st.container(border=True):
            st.markdown("### 📊 Log Statistics")
            display_log_stats("app.log", st, "refresh_stats")

# Run the app
show_logs()
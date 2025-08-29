import streamlit as st
import os
import json
import logging
from utils import format_currency_safe
from db import db_manager

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, filename="app.log", filemode="a", format="%(asctime)s - %(levelname)s - %(message)s", encoding="utf-8")

def show_settings(db):
    """Application settings with tabs and card-based layout"""
    st.title("⚙️ Settings")

    # Custom CSS for styling
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
        .stContainer {
            background: linear-gradient(145deg, #2a2a4a, #3b3b5e);
            border-radius: 15px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.3);
            border: 1px solid rgba(99, 102, 241, 0.2);
        }
        .stButton > button {
            background: linear-gradient(45deg, #6366f1, #a855f7);
            color: white;
            border: none;
            border-radius: 8px;
            padding: 10px 20px;
            font-weight: 500;
        }
        .stButton > button:hover {
            background: linear-gradient(45deg, #8183ff, #c084fc);
        }
        .stButton > button[kind="primary"] {
            background: linear-gradient(45deg, #10b981, #34d399);
        }
        .stButton > button[kind="primary"]:hover {
            background: linear-gradient(45deg, #34d399, #6ee7b7);
        }
        .stMetric {
            background: rgba(255,255,255,0.05);
            border-radius: 8px;
            padding: 10px;
            margin: 5px 0;
        }
        .stSelectbox, .stNumberInput {
            background: #3b3b5e;
            border-radius: 8px;
            padding: 5px;
        }
        </style>
    """, unsafe_allow_html=True)

    if not db:
        st.error("Database connection not available")
        return

    try:
        # Define tabs
        params_tab, balance_tab = st.tabs(["Trading Parameters", "Virtual Balance"])

        # Trading Parameters tab
        with params_tab:
            with st.container(border=True):
                st.markdown("### Trading Parameters")
                col1, col2 = st.columns(2)
                with col1:
                    scan_interval = st.number_input("Scan Interval (seconds)", value=3600, min_value=60, max_value=86400, key="scan_interval")
                    max_loss_pct = st.number_input("Max Loss %", value=15.0, min_value=1.0, max_value=100.0, key="max_loss_pct")
                with col2:
                    tp_percent = st.number_input("Default TP %", value=3.0, min_value=0.1, max_value=100.0, key="tp_percent")
                    sl_percent = st.number_input("Default SL %", value=1.5, min_value=0.1, max_value=100.0, key="sl_percent")
                if st.button("💾 Save Settings", type="primary", key="save_settings"):
                    try:
                        st.session_state['trading_params'] = {
                            "scan_interval": scan_interval,
                            "max_loss_pct": max_loss_pct,
                            "tp_percent": tp_percent,
                            "sl_percent": sl_percent
                        }
                        st.success("✅ Settings saved")
                    except Exception as e:
                        logger.error(f"Error saving settings: {e}")
                        st.error(f"Error saving settings: {e}")

        # Virtual Balance tab
        with balance_tab:
            with st.container(border=True):
                st.markdown("### Virtual Balance")
                current_balance = load_virtual_balance()
                new_balance = st.number_input(
                    "Virtual Balance (USDT)",
                    value=current_balance.get('capital', 1000),
                    min_value=100.0,
                    max_value=1_000_000.0,
                    key="virtual_balance"
                )
                if st.button("💰 Update Virtual Balance", type="primary", key="update_balance"):
                    try:
                        if new_balance < 100:
                            st.error("Virtual balance must be at least 100 USDT")
                            return
                        update_virtual_balance(new_balance)
                        st.success(f"✅ Virtual balance updated to ${format_currency_safe(new_balance)}")
                        st.rerun()
                    except Exception as e:
                        logger.error(f"Error updating balance: {e}")
                        st.error(f"Error updating balance: {e}")

    except Exception as e:
        logger.error(f"Error in settings: {e}")
        st.error(f"Settings error: {e}")

def load_virtual_balance():
    """Load virtual balance from file"""
    try:
        if os.path.exists("capital.json") and os.access("capital.json", os.R_OK):
            with open("capital.json", "r") as f:
                data = json.load(f)
                return data.get("virtual", {"capital": 1000, "available": 1000})
        return {"capital": 1000, "available": 1000}
    except Exception as e:
        logger.warning(f"Error loading virtual balance: {e}")
        return {"capital": 1000, "available": 1000}

def update_virtual_balance(new_balance):
    """Update virtual balance in file"""
    try:
        capital_data = load_virtual_balance()
        capital_data.update({
            "capital": new_balance,
            "available": new_balance,
            "start_balance": new_balance
        })
        if os.path.exists("capital.json") and os.access("capital.json", os.R_OK):
            with open("capital.json", "r") as f:
                full_data = json.load(f)
        else:
            full_data = {"real": {}, "virtual": {}}
        full_data["virtual"] = capital_data
        with open("capital.json", "w") as f:
            json.dump(full_data, f, indent=4)
    except Exception as e:
        logger.error(f"Error updating virtual balance: {e}")
        raise

# Run the app
show_settings(db_manager)
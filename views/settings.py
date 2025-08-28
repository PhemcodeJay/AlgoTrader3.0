import streamlit as st
import os
import json
import logging
from utils import format_currency_safe

logger = logging.getLogger(__name__)

def show_settings(db):
    """Application settings with tabs and card-based layout"""
    st.title("⚙️ Settings")

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
                if st.button("💾 Save Settings", key="save_settings"):
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
                if st.button("💰 Update Virtual Balance", key="update_balance"):
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
from typing import Dict, Any
import portalocker
import streamlit as st
import os
import json
import logging
from bybit_client import BybitClient
from utils import format_currency_safe

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, filename="app.log", filemode="a", format="%(asctime)s - %(levelname)s - %(message)s", encoding="utf-8")

SETTINGS_FILE = "settings.json"

def load_settings() -> Dict[str, Any]:
    default_settings = {
        "SCAN_INTERVAL": 3600,
        "TOP_N_SIGNALS": 5,
        "MAX_LOSS_PCT": -15.0,
        "TP_PERCENT": 0.15,
        "SL_PERCENT": 0.05,
        "LEVERAGE": 10,
        "RISK_PCT": 0.01,
        "VIRTUAL_BALANCE": 100.0,
        "ENTRY_BUFFER_PCT": 0.002
    }
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r") as f:
                settings = json.load(f)
            # Merge with defaults
            for key, value in default_settings.items():
                if key not in settings:
                    settings[key] = value
            return settings
        return default_settings
    except Exception as e:
        logger.warning(f"Error loading settings.json: {e}")
        return default_settings

def save_settings(settings: Dict[str, Any]):
    with open(SETTINGS_FILE, "w") as f:
        portalocker.lock(f, portalocker.LOCK_EX)
        json.dump(settings, f, indent=4)
        portalocker.unlock(f)

def show_settings(db, client: BybitClient, trading_mode: str):
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
        </style>
    """, unsafe_allow_html=True)

    try:
        settings = load_settings()
        tabs = ["Account", "Trading Parameters"]
        account_tab, trading_tab = st.tabs(tabs)

        with account_tab:
            with st.container():
                st.markdown("### Account Settings")
                st.write(f"**Trading Mode**: {trading_mode.capitalize()}")
                if trading_mode == "real":
                    if client.is_connected():
                        balance = client.get_wallet_balance()
                        st.write(f"**API Status**: Connected")
                        st.metric("Account Balance", format_currency_safe(balance.get('capital', 0.0)))
                        st.info("Real mode balance is managed by Bybit API and cannot be manually updated.")
                    else:
                        st.error("⚠️ Real mode selected but API credentials are invalid or missing.")
                else:
                    current_balance = client.load_capital("virtual")
                    st.metric("Virtual Balance", format_currency_safe(current_balance.get('capital', 100.0)))
                    new_balance = st.number_input(
                        "Set Virtual Balance (USDT)",
                        value=current_balance.get('capital', 100.0),
                        min_value=100.0,
                        max_value=1_000_000.0,
                        key="virtual_balance"
                    )
                    if st.button("💰 Update Virtual Balance", type="primary", key="update_balance"):
                        try:
                            if new_balance < 100:
                                st.error("Virtual balance must be at least 100 USDT")
                                return
                            client.save_capital("virtual", {
                                "capital": new_balance,
                                "available": new_balance,
                                "used": 0.0,
                                "start_balance": new_balance,
                                "currency": "USDT"
                            })
                            settings["VIRTUAL_BALANCE"] = new_balance
                            save_settings(settings)
                            st.success(f"✅ Virtual balance updated to {format_currency_safe(new_balance)}")
                            st.rerun()
                        except Exception as e:
                            logger.error(f"Error updating balance: {e}")
                            st.error(f"Error updating balance: {e}")

        with trading_tab:
            with st.container():
                st.markdown("### Trading Parameters")
                leverage = st.number_input(
                    "Leverage",
                    min_value=1,
                    max_value=100,
                    value=settings.get("LEVERAGE", 10),
                    step=1,
                    key="leverage"
                )
                risk_pct = st.number_input(
                    "Risk Percentage per Trade",
                    min_value=0.001,
                    max_value=0.1,
                    value=settings.get("RISK_PCT", 0.01),
                    step=0.001,
                    format="%.3f",
                    key="risk_pct"
                )
                tp_percent = st.number_input(
                    "Take Profit Percentage",
                    min_value=0.001,
                    max_value=0.5,
                    value=settings.get("TP_PERCENT", 0.15),
                    step=0.001,
                    format="%.3f",
                    key="tp_percent"
                )
                sl_percent = st.number_input(
                    "Stop Loss Percentage",
                    min_value=0.001,
                    max_value=0.5,
                    value=settings.get("SL_PERCENT", 0.05),
                    step=0.001,
                    format="%.3f",
                    key="sl_percent"
                )
                entry_buffer_pct = st.number_input(
                    "Entry Buffer Percentage",
                    min_value=0.001,
                    max_value=0.1,
                    value=settings.get("ENTRY_BUFFER_PCT", 0.002),
                    step=0.001,
                    format="%.3f",
                    key="entry_buffer_pct"
                )
                scan_interval = st.number_input(
                    "Scan Interval (seconds)",
                    min_value=60,
                    max_value=86400,
                    value=settings.get("SCAN_INTERVAL", 3600),
                    step=60,
                    key="scan_interval"
                )
                top_n_signals = st.number_input(
                    "Top N Signals",
                    min_value=1,
                    max_value=50,
                    value=settings.get("TOP_N_SIGNALS", 5),
                    step=1,
                    key="top_n_signals"
                )
                max_loss_pct = st.number_input(
                    "Max Loss Percentage",
                    min_value=-50.0,
                    max_value=-0.1,
                    value=settings.get("MAX_LOSS_PCT", -15.0),
                    step=0.1,
                    key="max_loss_pct"
                )
                if st.button("💾 Save Trading Parameters", type="primary", key="save_params"):
                    try:
                        settings["LEVERAGE"] = leverage
                        settings["RISK_PCT"] = risk_pct
                        settings["TP_PERCENT"] = tp_percent
                        settings["SL_PERCENT"] = sl_percent
                        settings["ENTRY_BUFFER_PCT"] = entry_buffer_pct
                        settings["SCAN_INTERVAL"] = scan_interval
                        settings["TOP_N_SIGNALS"] = top_n_signals
                        settings["MAX_LOSS_PCT"] = max_loss_pct
                        save_settings(settings)
                        st.success("✅ Trading parameters saved")
                    except Exception as e:
                        logger.error(f"Error saving parameters: {e}")
                        st.error(f"Error saving parameters: {e}")

    except Exception as e:
        logger.error(f"Error in settings: {e}")
        st.error(f"Settings error: {e}")
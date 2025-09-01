from typing import Dict, Any
import portalocker
import streamlit as st
import os
import json
import logging
from bybit_client import BybitClient
from utils import format_currency_safe

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    filename="app.log",
    filemode="a",
    format="%(asctime)s - %(levelname)s - %(message)s",
    encoding="utf-8"
)

SETTINGS_FILE = "settings.json"

DEFAULT_SETTINGS = {
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


def load_settings() -> Dict[str, Any]:
    """Load settings from file, falling back to defaults."""
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r") as f:
                settings = json.load(f)
            # Merge with defaults
            for key, value in DEFAULT_SETTINGS.items():
                settings.setdefault(key, value)
            return settings
        return DEFAULT_SETTINGS.copy()
    except Exception as e:
        logger.warning(f"Error loading settings.json: {e}")
        return DEFAULT_SETTINGS.copy()


def save_settings(settings: Dict[str, Any]):
    """Save settings with file lock for concurrency safety."""
    try:
        with open(SETTINGS_FILE, "w") as f:
            portalocker.lock(f, portalocker.LOCK_EX)
            json.dump(settings, f, indent=4)
            f.flush()
            os.fsync(f.fileno())
            portalocker.unlock(f)
    except Exception as e:
        logger.error(f"Error saving settings: {e}")
        raise


def show_settings(db, client: BybitClient, trading_mode: str):
    """Application settings page with tabs and card layout."""
    st.title("⚙️ Settings")

    # Custom CSS
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
            border-radius: 8px;
            margin: 5px;
            padding: 10px 20px;
            transition: all 0.3s ease;
        }
        .stTabs [data-baseweb="tab"][aria-selected="true"] {
            background: linear-gradient(45deg, #6366f1, #a855f7);
            color: #ffffff;
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
        account_tab, trading_tab = st.tabs(["Account", "Trading Parameters"])

        # --- Account tab ---
        with account_tab, st.container():
            st.markdown("### Account Settings")
            st.write(f"**Trading Mode**: {trading_mode.capitalize()}")

            if trading_mode == "real":
                if client.is_connected():
                    balance = client.get_wallet_balance()
                    st.write("**API Status**: Connected")
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
                    key="virtual_balance_input"
                )
                if st.button("💰 Update Virtual Balance", type="primary", key="update_balance_btn"):
                    try:
                        if new_balance < 100:
                            st.error("Virtual balance must be at least 100 USDT")
                        else:
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

        # --- Trading Parameters tab ---
        with trading_tab, st.container():
            st.markdown("### Trading Parameters")

            leverage = st.number_input(
                "Leverage", 1, 100, settings.get("LEVERAGE", 10), step=1
            )
            risk_pct = st.number_input(
                "Risk Percentage per Trade", 0.001, 0.1,
                settings.get("RISK_PCT", 0.01), step=0.001, format="%.3f"
            )
            tp_percent = st.number_input(
                "Take Profit Percentage", 0.001, 0.5,
                settings.get("TP_PERCENT", 0.15), step=0.001, format="%.3f"
            )
            sl_percent = st.number_input(
                "Stop Loss Percentage", 0.001, 0.5,
                settings.get("SL_PERCENT", 0.05), step=0.001, format="%.3f"
            )
            entry_buffer_pct = st.number_input(
                "Entry Buffer Percentage", 0.001, 0.1,
                settings.get("ENTRY_BUFFER_PCT", 0.002), step=0.001, format="%.3f"
            )
            scan_interval = st.number_input(
                "Scan Interval (seconds)", 60, 86400,
                settings.get("SCAN_INTERVAL", 3600), step=60
            )
            top_n_signals = st.number_input(
                "Top N Signals", 1, 50,
                settings.get("TOP_N_SIGNALS", 5), step=1
            )
            max_loss_pct = st.number_input(
                "Max Loss Percentage", -50.0, -0.1,
                settings.get("MAX_LOSS_PCT", -15.0), step=0.1
            )

            if st.button("💾 Save Trading Parameters", type="primary", key="save_params_btn"):
                try:
                    settings.update({
                        "LEVERAGE": leverage,
                        "RISK_PCT": risk_pct,
                        "TP_PERCENT": tp_percent,
                        "SL_PERCENT": sl_percent,
                        "ENTRY_BUFFER_PCT": entry_buffer_pct,
                        "SCAN_INTERVAL": scan_interval,
                        "TOP_N_SIGNALS": top_n_signals,
                        "MAX_LOSS_PCT": max_loss_pct,
                    })
                    save_settings(settings)
                    st.success("✅ Trading parameters saved")
                except Exception as e:
                    logger.error(f"Error saving parameters: {e}")
                    st.error(f"Error saving parameters: {e}")

    except Exception as e:
        logger.error(f"Error in settings: {e}")
        st.error(f"Settings error: {e}")

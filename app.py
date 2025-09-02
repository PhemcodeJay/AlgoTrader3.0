import streamlit as st
import logging
import os
import sys
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional
import json
from dotenv import load_dotenv

# Pages
from automated_trader import AutomatedTrader
from bybit_client import BybitClient
from engine import TradingEngine
from pages.dashboard import show_dashboard
from pages.positions import show_positions
from pages.orders import show_orders
from pages.signals import show_signals
from pages.portfolio import show_portfolio
from pages.automation import show_automation
from pages.logs import show_logs
from pages.ml import show_ml

# Move set_page_config to the top
st.set_page_config(
    page_title="AlgoTrader Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Import and initialize db_manager before usage
from db import db_manager
client = BybitClient()
engine = TradingEngine()
trader = AutomatedTrader(engine, client)

# Start trading loop in background
import threading
threading.Thread(
    target=trader._trading_loop,
    args=(db_manager, client, None),  # pass container if UI logging
    daemon=True
).start()

# Utility functions
def format_currency_safe(value: Optional[float]) -> str:
    try:
        return f"${float(value):.2f}" if value is not None else "$0.00"
    except (ValueError, TypeError) as e:
        logger.warning(f"Invalid value for currency formatting: {value}, error: {e}")
        return "$0.00"

# Ensure UTF-8 output
try:
    sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1)
except Exception:
    pass  # If running in an environment where fileno is not available, skip

# Custom CSS
CSS = """
    <style>
    .stApp {
        background: linear-gradient(135deg, #1e1e2f 0%, #2a2a4a 100%);
        color: #e0e0e0;
        font-family: 'Segoe UI', sans-serif;
    }
    .css-1d391kg {
        background: #2c2c4e;
        border-right: 1px solid rgba(99, 102, 241, 0.2);
    }
    .stSelectbox, .stNumberInput {
        background: #3b3b5e;
        border-radius: 8px;
        padding: 5px;
    }
    .stSelectbox > div > div, .stNumberInput > div > div {
        color: #ffffff;
    }
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
    .stMetric {
        background: rgba(255,255,255,0.05);
        border-radius: 8px;
        padding: 10px;
        margin: 5px 0;
    }
    .stMetric label {
        color: #a0a0c0;
        font-size: 10px;
    }
    .stMetric .stMetricValue {
        color: #ffffff;
        font-weight: 400;
    }
    .stAlert {
        border-radius: 8px;
        background: rgba(255,255,255,0.05);
    }
    </style>
"""
st.markdown(CSS, unsafe_allow_html=True)

def main():
    try:
        # Initialize session state
        init_session_state()

        # Check for API credentials
        load_dotenv()
        api_key = os.getenv("BYBIT_API_KEY")
        api_secret = os.getenv("BYBIT_API_SECRET")
        has_api_credentials = bool(api_key and api_secret and api_key != "F7aQeUkd3obyUSDeNJ" and api_secret != "A8WNJSiQodExiy2U2GsKTp2Na5ytSwBlK7iD")

        # Sidebar
        st.sidebar.image("logo.png", width=150)
        st.sidebar.title("AlgoTrader")
        
        # Trading mode selection
        mode_options = ["Virtual"]
        if has_api_credentials:
            mode_options.append("Real")
        else:
            st.sidebar.warning("Real mode disabled: Missing or default API credentials in .env")
        
        selected_mode = st.sidebar.selectbox(
            "Trading Mode",
            options=mode_options,
            index=0 if st.session_state.trading_mode == "virtual" else 1 if has_api_credentials else 0,
            key="trading_mode_select"
        )
        st.session_state.trading_mode = "virtual" if selected_mode == "Virtual" else "real"

        # Initialize components with current trading mode
        db, engine, client, automated_trader = init_components(st.session_state.trading_mode)

        if db is None or engine is None or client is None or automated_trader is None:
            st.error("🚨 Failed to initialize application components")
            return

        # Sidebar navigation
        page = st.sidebar.radio(
            "Navigation",
            ["Dashboard", "Positions", "Orders", "Signals", "Portfolio", "Automation", "ML", "Logs"],
            index=0
        )

        # Auto-refresh toggle
        auto_refresh = st.sidebar.checkbox("Auto-refresh (30s)", value=True)
        # Initialize trading_mode if it doesn't exist yet
        if "trading_mode" not in st.session_state:
            st.session_state.trading_mode = "virtual"  # or "real", whichever default you want
        # Display selected page
        try:
            if page == "Dashboard":
                show_dashboard(db, engine, client, st.session_state.trading_mode)
            elif page == "Positions":
                show_positions(db, engine, client, st.session_state.trading_mode)
            elif page == "Orders":
                show_orders(db, engine, client, st.session_state.trading_mode)
            elif page == "Signals":
                show_signals(db, engine, client, st.session_state.trading_mode)
            elif page == "Portfolio":
                show_portfolio(db, engine, client, st.session_state.trading_mode)
            elif page == "Automation":
                show_automation(automated_trader, db, engine, client, st.session_state.trading_mode)
            elif page == "ML":
                show_ml(db, engine, client, st.session_state.trading_mode)
            elif page == "Logs":
                show_logs()
        except Exception as e:
            logger.error(f"Error in page {page}: {e}")
            st.error(f"🚨 Error loading {page}: {str(e)}")

        # Auto-refresh implementation
        if auto_refresh:
            current_time = datetime.now().timestamp()
            if current_time - st.session_state.last_refresh >= 30:
                st.session_state.last_refresh = current_time
                st.rerun()

    except Exception as e:
        logger.error(f"Critical error in main: {e}")
        st.error(f"🚨 Critical application error: {str(e)}")

def init_components(trading_mode: str):
    try:
        from db import db_manager
        from engine import TradingEngine
        from bybit_client import BybitClient
        from automated_trader import AutomatedTrader

        db_manager_instance = db_manager
        engine = TradingEngine()
        # Override .env settings with the selected trading mode
        os.environ["REAL"] = "true" if trading_mode == "real" else "false"
        os.environ["VIRTUAL"] = "true" if trading_mode == "virtual" else "false"
        client = BybitClient()
        automated_trader = AutomatedTrader(engine, client)

        return db_manager_instance, engine, client, automated_trader

    except ImportError as e:
        logger.error(f"Failed to import modules: {e}")
        st.error(f"🚨 Failed to import modules: {e}")
        return None, None, None, None
    except Exception as e:
        logger.error(f"Failed to initialize components: {e}")
        st.error(f"🚨 Failed to initialize components: {e}")
        return None, None, None, None

def init_session_state():
    defaults = {
        'trading_mode': 'virtual',
        'selected_symbol': 'BTCUSDT',
        'position_size': 0.01,
        'leverage': 10,
        'log_level': 'INFO',
        'last_refresh': datetime.now().timestamp()
    }
    for key, default_value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default_value

if __name__ == "__main__":
    main()
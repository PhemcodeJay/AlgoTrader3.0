import streamlit as st
import logging
import os
import sys
from datetime import datetime
from typing import Dict, Any, Optional

# Views
from views.dashboard import show_dashboard
from views.positions import show_positions
from views.orders import show_orders
from views.signals import show_signals
from views.portfolio import show_portfolio
from views.automation import show_automation
from views.logs import show_logs

# Utility functions (from portfolio.py or signals.py)
def format_currency_safe(value: Optional[float]) -> str:
    """Format currency safely"""
    return f"${value:.2f}" if value is not None else "$0.00"

def load_virtual_balance() -> Dict[str, float]:
    """Load virtual balance (placeholder implementation)"""
    try:
        return {"capital": 100.0, "available": 100.0}
    except Exception as e:
        logger.error(f"Error loading virtual balance: {e}")
        return {"capital": 100.0, "available": 100.0}

# Ensure UTF-8 output
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Page configuration
st.set_page_config(
    page_title="AlgoTrader Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for modern, colorful styling
st.markdown("""
    <style>
    /* Global styles */
    .stApp {
        background: linear-gradient(135deg, #1e1e2f 0%, #2a2a4a 100%);
        color: #e0e0e0;
        font-family: 'Segoe UI', sans-serif;
    }

    /* Sidebar styling */
    .css-1d391kg {
        background: #2c2c4e;
        border-right: 1px solid rgba(99, 102, 241, 0.2);
    }

    /* Selectbox */
    .stSelectbox, .stNumberInput {
        background: #3b3b5e;
        border-radius: 8px;
        padding: 5px;
    }
    .stSelectbox > div > div, .stNumberInput > div > div {
        color: #ffffff;
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
        font-size: 10px;
    }
    .stMetric .stMetricValue {
        color: #ffffff;
        font-weight: 400;
    }

    /* Info and error messages */
    .stAlert {
        border-radius: 8px;
        background: rgba(255,255,255,0.1);
        color: #ffffff;
    }

    /* Caption */
    .stCaption {
        color: #a0a0c0;
    }
    </style>
""", unsafe_allow_html=True)

# Initialize components safely
@st.cache_resource
def init_components():
    """Initialize database and trading components with error handling"""
    try:
        # Import modules
        from db import db_manager, init_db
        from engine import TradingEngine
        from bybit_client import BybitClient
        from automated_trader import AutomatedTrader

        # Initialize database
        database_url = os.getenv("DATABASE_URL", "sqlite:///trading.db")
        init_db()
        db_manager_instance = db_manager
        engine = TradingEngine()
        client = BybitClient()
        automated_trader = AutomatedTrader(engine)

        return db_manager_instance, engine, client, automated_trader

    except ImportError as e:
        logger.error(f"Failed to import modules: {e}")
        st.error(f"🚨 Failed to import modules: {e}")
        return None, None, None, None
    except Exception as e:
        logger.error(f"Failed to initialize components: {e}")
        st.error(f"🚨 Failed to initialize components: {e}")
        return None, None, None, None

# Initialize session state
def init_session_state():
    """Initialize session state variables"""
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

def main():
    """Main application function"""
    init_session_state()

    try:
        db, engine, client, automated_trader = init_components()

        if not db or not engine:
            st.error("❌ Failed to initialize core components. Please check logs.")
            st.info("💡 Try refreshing the page or check the application logs.")
            return

        # Sidebar
        with st.sidebar:
            st.title("🎯 AlgoTrader")
            st.markdown("---")

            # Trading Mode Selection
            st.subheader("Trading Mode")
            trading_mode = st.selectbox(
                "Select Mode",
                ["Virtual", "Real"],
                index=0 if st.session_state.trading_mode == 'virtual' else 1,
                help="Virtual mode uses paper trading, Real mode executes actual trades",
                key="trading_mode_select"
            )
            st.session_state.trading_mode = trading_mode.lower()

            # Mode indicator
            if trading_mode == 'Virtual':
                st.success("🟢 Virtual Mode")
            else:
                st.warning("🔴 Real Mode")

            # Live data status
            if client and client.is_connected():
                st.success("📡 Live Data")
            else:
                st.info("🌐 Real-Time Market Data (Public)")

            # Data freshness indicator
            current_time = datetime.now().strftime("%H:%M:%S")
            st.caption(f"Last updated: {current_time}")

            st.markdown("---")

            # Navigation
            page = st.selectbox(
                "Navigate",
                ["Dashboard", "Positions", "Orders", "Signals", "Portfolio", "Automation", "Logs"],
                key="navigation"
            )

            # Wallet Information
            st.markdown("---")
            st.subheader("💰 Wallet Status")

            # Virtual Wallet
            try:
                virtual_balance = load_virtual_balance()
                capital = float(virtual_balance.get("capital", 100.0))
                available = float(virtual_balance.get("available", capital))
                col1, col2 = st.columns(2)
                with col1:
                    st.metric("Virtual Balance", format_currency_safe(capital))
                with col2:
                    st.metric("Virtual Available", format_currency_safe(available))
            except Exception as e:
                logger.error(f"Error loading virtual wallet: {e}")
                st.error("🚨 Error loading virtual wallet")

            # Real Wallet
            try:
                if client and client.is_connected():
                    real_balance = client.get_wallet_balance()
                    col1, col2 = st.columns(2)
                    with col1:
                        st.metric("Real Balance", format_currency_safe(real_balance.get('totalEquity', 0)))
                    with col2:
                        st.metric("Real Available", format_currency_safe(real_balance.get('totalAvailableBalance', 0)))
                else:
                    st.info("⚠️ No API connection")
                    st.metric("Real Balance", "$0.00")
            except Exception as e:
                logger.error(f"Error loading real wallet: {e}")
                st.error("🚨 Error loading real wallet")

            st.markdown("---")

            # Auto-refresh toggle
            auto_refresh = st.checkbox("Auto Refresh (30s)", value=False, key="auto_refresh")
            if st.button("🔄 Refresh Now", key="refresh_now"):
                st.session_state.last_refresh = datetime.now().timestamp()
                st.rerun()

        # Main content routing
        try:
            if page == "Dashboard":
                show_dashboard(db, engine, client)
            elif page == "Positions":
                show_positions(db, engine, client)
            elif page == "Orders":
                show_orders(db, engine, client)
            elif page == "Signals":
                show_signals(db, engine, client)
            elif page == "Portfolio":
                show_portfolio(db, engine, client)
            elif page == "Automation":
                show_automation(automated_trader, db, engine, client)
            elif page == "Logs":
                show_logs()
            # Note: show_settings is removed as it was not provided in the context
        except Exception as e:
            logger.error(f"Error in page {page}: {e}")
            st.error(f"🚨 Error loading {page}: {str(e)}")

        # Auto-refresh implementation (non-blocking)
        if auto_refresh:
            current_time = datetime.now().timestamp()
            if current_time - st.session_state.last_refresh >= 30:
                st.session_state.last_refresh = current_time
                st.rerun()

    except Exception as e:
        logger.error(f"Critical error in main: {e}")
        st.error(f"🚨 Critical application error: {str(e)}")

if __name__ == "__main__":
    main()
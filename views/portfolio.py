import streamlit as st
import logging
from typing import List, Optional
from bybit_client import BybitClient
from engine import TradingEngine
from db import db_manager
import pandas as pd

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Utility functions
def load_virtual_balance() -> dict:
    """Load virtual balance (placeholder implementation)"""
    try:
        # Assuming virtual balance is stored in db or a default value
        return {"capital": 10000.0, "available": 10000.0}
    except Exception as e:
        logger.error(f"Error loading virtual balance: {e}")
        return {"capital": 100.0, "available": 100.0}

def get_open_trades_safe(db) -> List:
    """Safe wrapper for getting open trades"""
    try:
        return db.get_open_trades()
    except Exception as e:
        logger.error(f"Error getting open trades: {e}")
        return []

def get_current_price_safe(symbol: str, client: BybitClient) -> float:
    """Safe wrapper for getting current price"""
    try:
        return client.get_current_price(symbol)
    except Exception as e:
        logger.error(f"Error getting price for {symbol}: {e}")
        return 0.0

def format_price_safe(value: Optional[float]) -> str:
    """Format price safely"""
    return f"{value:.2f}" if value is not None and value > 0 else "N/A"

def format_currency_safe(value: Optional[float]) -> str:
    """Format currency safely"""
    return f"{value:.2f}" if value is not None else "0.00"

def get_trades_safe(db, limit: int = 50) -> List:
    """Safe wrapper for getting trades"""
    try:
        return db.get_trades(limit=limit)
    except Exception as e:
        logger.error(f"Error getting trades: {e}")
        return []

def get_signals_safe(db) -> List:
    """Safe wrapper for getting signals"""
    try:
        return db.get_signals()
    except Exception as e:
        logger.error(f"Error getting signals: {e}")
        return []

def get_portfolio_safe(db) -> List:
    """Safe wrapper for getting portfolio"""
    try:
        return db.get_portfolio()
    except Exception as e:
        logger.error(f"Error getting portfolio: {e}")
        return []

def display_trades_table(trades, container, max_trades=5):
    """Reusable function to display trades table"""
    try:
        if not trades:
            container.info("🌙 No trades to display")
            return

        trades_data = []
        for trade in trades[:max_trades]:
            trades_data.append({
                "Symbol": getattr(trade, 'symbol', 'N/A'),
                "Side": getattr(trade, 'side', 'N/A'),
                "Entry": f"${format_price_safe(getattr(trade, 'entry_price', 0))}",
                "P&L": f"${format_currency_safe(getattr(trade, 'pnl', 0))}",
                "Status": getattr(trade, 'status', 'N/A').title(),
                "Mode": "🟢 Virtual" if getattr(trade, 'virtual', True) else "🔴 Real"
            })

        if trades_data:
            df = pd.DataFrame(trades_data)
            container.dataframe(df, use_container_width=True, height=300)
        else:
            container.info("🌙 No trade data to display")
    except Exception as e:
        logger.error(f"Error displaying trades table: {e}")
        container.error("🚨 Error displaying trades")

def display_signals(signals, container, tab_name, max_signals=5):
    """Reusable function to display signals in card form"""
    container.subheader(f"📡 {tab_name} ({len(signals)})")
    if signals:
        for signal in signals[:max_signals]:
            with container.container(border=True):
                try:
                    symbol = getattr(signal, 'symbol', 'N/A')
                    side = getattr(signal, 'side', 'N/A')
                    confidence = getattr(signal, 'confidence', 0)
                    strategy = getattr(signal, 'strategy', 'N/A')
                    price = getattr(signal, 'price', 0)
                    timestamp = getattr(signal, 'timestamp', None)
                    time_str = timestamp.strftime("%Y-%m-%d %H:%M:%S") if timestamp and hasattr(timestamp, 'strftime') else "N/A"
                    confidence_color = "🔥" if confidence >= 0.9 else "💪" if confidence >= 0.8 else "👍" if confidence >= 0.7 else "⚠️"
                    container.markdown(f"{confidence_color} **{symbol} | {side}** | Confidence: {confidence:.1%} | {strategy}")
                    col1, col2 = st.columns(2)
                    with col1:
                        st.metric("Signal Price", f"${format_price_safe(price)}")
                    with col2:
                        st.metric("Timestamp", time_str)
                except Exception as e:
                    logger.error(f"Error displaying signal: {e}")
                    container.error(f"🚨 Error displaying signal: {e}")
    else:
        container.info(f"🌙 No {tab_name.lower()} found")

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

    /* Dataframe styling */
    .stDataFrame {
        background: rgba(255,255,255,0.05);
        border-radius: 8px;
        padding: 10px;
    }
    </style>
""", unsafe_allow_html=True)

def show_portfolio(db, client, engine):
    """Enhanced portfolio with tabs and card-based layout"""
    st.title("💰 Portfolio Overview")

    if not db or not hasattr(db, 'get_portfolio'):
        st.error("🚨 Database connection not available")
        return

    try:
        # Define tabs
        wallet_tab, holdings_tab, summary_tab = st.tabs(["👛 Wallet", "💼 Holdings", "📊 Trading Summary"])

        # Wallet tab
        with wallet_tab:
            st.subheader("👛 Wallet Overview")
            col1, col2 = st.columns(2)
            with col1:
                with st.container(border=True):
                    st.markdown("### 🟢 Virtual Wallet")
                    try:
                        virtual_balance = load_virtual_balance()
                        col1_1, col1_2 = st.columns(2)
                        with col1_1:
                            st.metric("Total Balance", f"${format_currency_safe(virtual_balance.get('capital', 100))}")
                            st.metric("Available", f"${format_currency_safe(virtual_balance.get('available', 100))}")
                        with col1_2:
                            open_trades = get_open_trades_safe(db)
                            virtual_pnl = 0
                            virtual_positions = 0
                            for trade in open_trades:
                                if getattr(trade, 'virtual', True):
                                    virtual_positions += 1
                                    try:
                                        current_price = get_current_price_safe(getattr(trade, 'symbol', 'BTCUSDT'), client)
                                        entry_price = float(getattr(trade, 'entry_price', 0))
                                        qty = float(getattr(trade, 'qty', 0))
                                        side = getattr(trade, 'side', 'LONG').upper()
                                        if qty > 0:
                                            if side in ['BUY', 'LONG']:
                                                pnl = (current_price - entry_price) * qty
                                            else:
                                                pnl = (entry_price - current_price) * qty
                                            virtual_pnl += pnl
                                    except Exception:
                                        pass
                            st.metric("Unrealized P&L", f"${format_currency_safe(virtual_pnl)}", delta=f"{virtual_pnl:+.2f}", delta_color="normal" if virtual_pnl >= 0 else "inverse")
                            st.metric("Open Positions", virtual_positions)
                    except Exception as e:
                        logger.error(f"Error loading virtual wallet: {e}")
                        st.error(f"🚨 Error loading virtual wallet: {e}")
            with col2:
                with st.container(border=True):
                    st.markdown("### 🔴 Real Wallet")
                    try:
                        if client and hasattr(client, 'is_connected') and client.is_connected():
                            real_balance = client.get_wallet_balance()
                            col2_1, col2_2 = st.columns(2)
                            with col2_1:
                                st.metric("Total Equity", f"${format_currency_safe(real_balance.get('totalEquity', 0))}")
                                st.metric("Available Balance", f"${format_currency_safe(real_balance.get('totalAvailableBalance', 0))}")
                            with col2_2:
                                st.metric("USDT Balance", f"${format_currency_safe(real_balance.get('coin', {}).get('USDT', {}).get('availableBalance', 0))}")
                                open_trades = get_open_trades_safe(db)
                                real_positions = sum(1 for trade in open_trades if not getattr(trade, 'virtual', True))
                                st.metric("Open Positions", real_positions)
                        else:
                            st.info("🌙 Real wallet not connected")
                    except Exception as e:
                        logger.error(f"Error loading real wallet: {e}")
                        st.error(f"🚨 Error loading real wallet: {e}")
            if st.button("🔄 Refresh Wallet", key="refresh_wallet"):
                st.rerun()

        # Holdings tab
        with holdings_tab:
            st.subheader("💼 Portfolio Holdings")
            try:
                portfolio_holdings = get_portfolio_safe(db)
                if portfolio_holdings:
                    for holding in portfolio_holdings:
                        with st.container(border=True):
                            symbol = getattr(holding, 'symbol', 'N/A')
                            is_virtual = getattr(holding, 'virtual', True)  # Use 'virtual' instead of 'is_virtual'
                            st.markdown(f"**{symbol} | {'🟢 Virtual' if is_virtual else '🔴 Real'}**")
                            col1, col2 = st.columns(2)
                            with col1:
                                qty = getattr(holding, 'qty', 0)
                                st.markdown(f"**Quantity**: {qty:.6f}")
                                st.metric("Avg Price", f"${format_price_safe(getattr(holding, 'avg_price', 0))}")
                            with col2:
                                current_price = get_current_price_safe(symbol, client)
                                value = qty * current_price if qty and current_price else 0
                                unrealized_pnl = value - (qty * float(getattr(holding, 'avg_price', 0))) if qty and hasattr(holding, 'avg_price') else 0
                                st.metric("Value", f"${format_currency_safe(value)}")
                                st.metric("Unrealized P&L", f"${format_currency_safe(unrealized_pnl)}", delta=f"{unrealized_pnl:+.2f}", delta_color="normal" if unrealized_pnl >= 0 else "inverse")
                else:
                    st.info("🌙 No portfolio holdings found")
                if st.button("🔄 Refresh Holdings", key="refresh_holdings"):
                    st.rerun()
            except Exception as e:
                logger.error(f"Error loading portfolio holdings: {e}")
                st.error(f"🚨 Error loading portfolio holdings: {e}")

        # Trading Summary tab
        with summary_tab:
            st.subheader("📊 Trading Summary")
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**Recent Trades (Last 5)**")
                recent_trades = get_trades_safe(db, limit=5)
                display_trades_table(recent_trades, st)
            with col2:
                st.markdown("**Recent Signals (Last 5)**")
                recent_signals = get_signals_safe(db)
                display_signals(recent_signals, st, "Recent Signals")
            if st.button("🔄 Refresh Summary", key="refresh_summary"):
                st.rerun()

    except Exception as e:
        logger.error(f"Error in portfolio: {e}")
        st.error(f"🚨 Portfolio error: {e}")

# Initialize components
db = db_manager
engine = TradingEngine()
client = engine.client

# Run the app
show_portfolio(db, client, engine)
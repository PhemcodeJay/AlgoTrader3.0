import streamlit as st
import logging
from typing import List, Optional, Dict
from bybit_client import BybitClient
from engine import TradingEngine
from db import db_manager
import pandas as pd
from datetime import datetime, timezone
import requests

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Constants from utils.py
RISK_PCT = 0.01
ACCOUNT_BALANCE = 100.0
LEVERAGE = 20

# Utility functions
def get_portfolio_balance(db, client: BybitClient, is_virtual: bool = True) -> Dict:
    """Calculate portfolio balance and unrealized P&L"""
    try:
        portfolio_holdings = db.get_portfolio()
        total_capital = ACCOUNT_BALANCE if is_virtual else 0.0
        total_value = 0.0
        unrealized_pnl = 0.0
        used_margin = 0.0

        # Sync with Bybit client for real wallet
        if not is_virtual and client.is_connected():
            wallet_info = client.get_wallet_balance() or {}
            total_capital = float(wallet_info.get('totalEquity', 0.0))

        for holding in portfolio_holdings:
            if holding.is_virtual == is_virtual:
                qty = float(getattr(holding, 'qty', 0) or 0)
                avg_price = float(getattr(holding, 'avg_price', 0) or 0)
                symbol = getattr(holding, 'symbol', 'N/A')
                if symbol in ["1000000BABYDOGEUSDT", "1000000CHEEMSUSDT", "1000000MOGUSDT"]:
                    continue  # Skip invalid symbols
                current_price = get_current_price_safe(symbol, client)
                value = qty * current_price if qty and current_price else 0
                holding_unrealized_pnl = value - (qty * avg_price) if qty and avg_price else 0
                total_value += value
                unrealized_pnl += holding_unrealized_pnl
                used_margin += float(getattr(holding, 'margin_usdt', 0) or 0)

        # Calculate available balance
        available_balance = total_capital - used_margin

        return {
            "capital": total_capital,
            "available": available_balance,
            "value": total_value,
            "unrealized_pnl": unrealized_pnl,
            "open_positions": sum(1 for h in portfolio_holdings if h.is_virtual == is_virtual and h.symbol not in ["1000000BABYDOGEUSDT", "1000000CHEEMSUSDT", "1000000MOGUSDT"])
        }
    except Exception as e:
        logger.error(f"Error calculating portfolio balance (virtual={is_virtual}): {e}")
        return {
            "capital": ACCOUNT_BALANCE if is_virtual else 0.0,
            "available": ACCOUNT_BALANCE if is_virtual else 0.0,
            "value": 0.0,
            "unrealized_pnl": 0.0,
            "open_positions": 0
        }

def get_open_trades_safe(db) -> List:
    """Safe wrapper for getting open trades"""
    try:
        trades = db.get_open_trades() or []
        return [t for t in trades if getattr(t, 'symbol', 'N/A') not in ["1000000BABYDOGEUSDT", "1000000CHEEMSUSDT", "1000000MOGUSDT"]]
    except Exception as e:
        logger.error(f"Error getting open trades: {e}")
        return []

def get_current_price_safe(symbol: str, client: BybitClient) -> float:
    """Safe wrapper for getting current price"""
    try:
        if symbol in ["1000000BABYDOGEUSDT", "1000000CHEEMSUSDT", "1000000MOGUSDT"]:
            return 0.0  # Skip invalid symbols
        price = client.get_current_price(symbol)
        return float(price) if price is not None else 0.0
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
        trades = db.get_trades(limit=limit) or []
        return [t for t in trades if getattr(t, 'symbol', 'N/A') not in ["1000000BABYDOGEUSDT", "1000000CHEEMSUSDT", "1000000MOGUSDT"]]
    except Exception as e:
        logger.error(f"Error getting trades: {e}")
        return []

def get_signals_safe(db) -> List[dict]:
    """Safe wrapper for getting signals"""
    try:
        signals = db.get_signals()
        return [s.to_dict() for s in signals if s.symbol not in ["1000000BABYDOGEUSDT", "1000000CHEEMSUSDT", "1000000MOGUSDT"]] if signals else []
    except Exception as e:
        logger.error(f"Error getting signals: {e}")
        return []

def get_portfolio_safe(db) -> List:
    """Safe wrapper for getting portfolio"""
    try:
        holdings = db.get_portfolio() or []
        return [h for h in holdings if getattr(h, 'symbol', 'N/A') not in ["1000000BABYDOGEUSDT", "1000000CHEEMSUSDT", "1000000MOGUSDT"]]
    except Exception as e:
        logger.error(f"Error getting portfolio: {e}")
        return []

def display_trades_table(trades, container, max_trades=10):
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
                "Mode": "🟢 Virtual" if getattr(trade, 'virtual', True) else "🔴 Real",
                "Strategy": getattr(trade, 'strategy', 'N/A')
            })

        if trades_data:
            df = pd.DataFrame(trades_data)
            container.dataframe(df, use_container_width=True, height=350)
        else:
            container.info("🌙 No trade data to display")
    except Exception as e:
        logger.error(f"Error displaying trades table: {e}")
        container.error("🚨 Error displaying trades")

def display_signals(signals: List[dict], container, title: str, page: int, page_size: int):
    """Display signals in card form with pagination"""
    try:
        if not signals:
            container.info(f"🌙 No {title.lower()} to display")
            return

        # Calculate pagination
        total_signals = len(signals)
        total_pages = (total_signals + page_size - 1) // page_size
        start_idx = (page - 1) * page_size
        end_idx = min(start_idx + page_size, total_signals)
        paginated_signals = signals[start_idx:end_idx]

        container.subheader(f"📡 {title} ({total_signals})")

        # Display paginated signals
        for signal in paginated_signals:
            with container.container(border=True):
                try:
                    symbol = signal.get("symbol", "N/A")
                    side = signal.get("side", "N/A")
                    signal_type = signal.get("signal_type", "N/A")
                    interval = signal.get("interval", "N/A")
                    score = signal.get("score", 0)
                    strategy = signal.get("strategy", "N/A")
                    entry = signal.get("entry", 0)
                    tp = signal.get("tp", 0)
                    sl = signal.get("sl", 0)
                    trail = signal.get("trail", 0)
                    liquidation = signal.get("liquidation", 0)
                    leverage = signal.get("leverage", 0)
                    margin_usdt = signal.get("margin_usdt", 0)
                    created_at = signal.get("created_at", None)
                    indicators = signal.get("indicators", {})
                    time_str = (created_at.strftime("%Y-%m-%d %H:%M:%S") 
                               if isinstance(created_at, datetime) 
                               else created_at if isinstance(created_at, str) 
                               else "N/A")

                    st.markdown(f"**{symbol} | {side} | {interval}**")
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("Entry Price", f"${format_price_safe(entry)}")
                        st.metric("Take Profit", f"${format_price_safe(tp)}")
                        st.metric("Stop Loss", f"${format_price_safe(sl)}")
                    with col2:
                        st.metric("Trail Price", f"${format_price_safe(trail)}")
                        st.metric("Liquidation Price", f"${format_price_safe(liquidation)}")
                        st.metric("Timestamp", time_str)
                    with col3:
                        st.metric("Confidence", f"{score:.2f}%")
                        st.metric("Leverage", f"{leverage}x")
                        st.metric("Margin USDT", f"${format_currency_safe(margin_usdt)}")
                    st.markdown(f"**Strategy**: {strategy}")
                    with st.expander("Indicators"):
                        st.json(indicators)
                except Exception as e:
                    logger.error(f"Error displaying signal: {e}")
                    container.error(f"Error displaying signal: {e}")

        # Pagination controls
        if total_pages > 1:
            col1, col2, col3 = container.columns([1, 2, 1])
            with col2:
                page_key = f"{title.lower().replace(' ', '_')}_page_select"
                page = st.selectbox(
                    "Page",
                    options=list(range(1, total_pages + 1)),
                    index=page - 1,
                    key=page_key
                )
                st.session_state[f"{title.lower().replace(' ', '_')}_page"] = page

    except Exception as e:
        logger.error(f"Error in display_signals: {e}")
        container.error(f"🚨 Error displaying {title.lower()}: {e}")

# Custom CSS for modern, colorful styling
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
        transition: transform 0.2s ease;
    }
    .stContainer:hover {
        transform: translateY(-5px);
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
        font-size: 14px;
    }
    .stMetric .stMetricValue {
        color: #ffffff;
        font-weight: 600;
    }
    .stAlert {
        border-radius: 8px;
        background: rgba(255,255,255,0.1);
        color: #ffffff;
    }
    .stDataFrame {
        background: rgba(255,255,255,0.05);
        border-radius: 8px;
        padding: 10px;
    }
    </style>
""", unsafe_allow_html=True)

def show_portfolio(db, client, engine):
    """Enhanced portfolio with tabs and card-based layout"""
    try:
        if not db or not hasattr(db, 'get_portfolio'):
            st.error("🚨 Database connection not available")
            return

        st.title("💰 Portfolio Overview")

        # Define tabs
        wallet_tab, holdings_tab, summary_tab = st.tabs(["👛 Wallet", "💼 Holdings", "📊 Trading Summary"])

        # Wallet tab
        with wallet_tab:
            st.subheader("👛 Wallet Overview")
            col1, col2 = st.columns(2)
            
            # Virtual Wallet
            with col1:
                with st.container(border=True):
                    st.markdown("### 🟢 Virtual Wallet")
                    virtual_balance = get_portfolio_balance(db, client, is_virtual=True)
                    col1_1, col1_2 = st.columns(2)
                    with col1_1:
                        st.metric("Total Balance", f"${format_currency_safe(virtual_balance.get('capital'))}")
                        st.metric("Available Balance", f"${format_currency_safe(virtual_balance.get('available'))}")
                    with col1_2:
                        st.metric("Portfolio Value", f"${format_currency_safe(virtual_balance.get('value'))}")
                        st.metric("Unrealized P&L", f"${format_currency_safe(virtual_balance.get('unrealized_pnl'))}", 
                                 delta=f"{virtual_balance.get('unrealized_pnl', 0):+.2f}", 
                                 delta_color="normal" if virtual_balance.get('unrealized_pnl', 0) >= 0 else "inverse")
                        st.metric("Open Positions", virtual_balance.get('open_positions', 0))
            
            # Real Wallet
            with col2:
                with st.container(border=True):
                    st.markdown("### 🔴 Real Wallet")

                    if client.is_connected():
                        # Fetch wallet info and portfolio balance with fallbacks
                        try:
                            wallet_info = client.get_wallet_balance() or {}
                        except Exception as e:
                            st.error(f"❌ Failed to fetch wallet: {e}")
                            wallet_info = {}

                        try:
                            real_balance = get_portfolio_balance(db, client, is_virtual=False) or {}
                        except Exception as e:
                            st.error(f"❌ Failed to fetch portfolio: {e}")
                            real_balance = {}

                        # Extract values with fallbacks
                        total_equity = real_balance.get("capital") or wallet_info.get("totalEquity", 0)
                        available_balance = real_balance.get("available") or wallet_info.get("totalAvailableBalance", 0)
                        portfolio_value = real_balance.get("value", 0)
                        unrealized_pnl = real_balance.get("unrealized_pnl", 0)
                        open_positions = real_balance.get("open_positions", 0)

                        # Columns for layout
                        col2_1, col2_2 = st.columns(2)

                        with col2_1:
                            st.metric("Total Equity", f"${format_currency_safe(total_equity)}")
                            st.metric("Available Balance", f"${format_currency_safe(available_balance)}")

                        with col2_2:
                            st.metric("Portfolio Value", f"${format_currency_safe(portfolio_value)}")
                            st.metric(
                                "Unrealized P&L",
                                f"${format_currency_safe(unrealized_pnl)}",
                                delta=f"{unrealized_pnl:+.2f}",
                                delta_color="normal" if unrealized_pnl >= 0 else "inverse"
                            )
                            st.metric("Open Positions", open_positions)

                    else:
                        st.info("🌙 Real wallet not connected")

            # Manual refresh button
            if st.button("🔄 Refresh Wallet", key="portfolio_refresh_wallet"):
                st.rerun()

        # Holdings tab
        with holdings_tab:
            st.subheader("💼 Portfolio Holdings")
            portfolio_holdings = get_portfolio_safe(db)
            if portfolio_holdings:
                for holding in portfolio_holdings:
                    with st.container(border=True):
                        symbol = getattr(holding, 'symbol', 'N/A')
                        is_virtual = getattr(holding, 'is_virtual', True)
                        st.markdown(f"**{symbol} | {'🟢 Virtual' if is_virtual else '🔴 Real'}**")
                        col1, col2 = st.columns(2)
                        with col1:
                            qty = float(getattr(holding, 'qty', 0) or 0)
                            st.markdown(f"**Quantity**: {qty:.6f}")
                            st.metric("Avg Price", f"${format_price_safe(getattr(holding, 'avg_price', 0))}")
                        with col2:
                            current_price = get_current_price_safe(symbol, client)
                            value = qty * current_price if qty and current_price else 0
                            unrealized_pnl = value - (qty * float(getattr(holding, 'avg_price', 0) or 0)) if qty else 0
                            st.metric("Value", f"${format_currency_safe(value)}")
                            st.metric("Unrealized P&L", f"${format_currency_safe(unrealized_pnl)}", 
                                     delta=f"{unrealized_pnl:+.2f}", 
                                     delta_color="normal" if unrealized_pnl >= 0 else "inverse")
            else:
                st.info("🌙 No portfolio holdings found")
            if st.button("🔄 Refresh Holdings", key="portfolio_refresh_holdings"):
                st.rerun()

        # Trading Summary tab
        with summary_tab:
            st.subheader("📊 Trading Summary")
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**Recent Trades (Last 10)**")
                recent_trades = get_trades_safe(db, limit=10)
                display_trades_table(recent_trades, st)
            with col2:
                st.markdown("**Recent Signals**")
                if "recent_signals_page" not in st.session_state:
                    st.session_state.recent_signals_page = 1
                recent_signals = get_signals_safe(db)
                display_signals(recent_signals, st, "Recent Signals", st.session_state.recent_signals_page, page_size=5)
            if st.button("🔄 Refresh Summary", key="portfolio_refresh_summary"):
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
import streamlit as st
import logging
import pandas as pd
from typing import List, Optional, Dict
from bybit_client import BybitClient
from engine import TradingEngine
from db import db_manager
from datetime import datetime, timezone

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, filename="app.log", filemode="a", format="%(asctime)s - %(levelname)s - %(message)s", encoding="utf-8")

# Constants from utils.py
RISK_PCT = 0.01
ACCOUNT_BALANCE = 100.0
LEVERAGE = 20

def get_portfolio_balance(db, client: BybitClient, is_virtual: bool = True) -> Dict:
    """Calculate portfolio balance and unrealized P&L"""
    try:
        portfolio_holdings = db.get_portfolio()
        total_capital = ACCOUNT_BALANCE if is_virtual else 0.0
        total_value = 0.0
        unrealized_pnl = 0.0
        used_margin = 0.0

        if not is_virtual and client.is_connected():
            wallet_info = client.get_wallet_balance() or {}
            total_capital = float(wallet_info.get('totalEquity', 0.0))

        for holding in portfolio_holdings:
            if getattr(holding, 'is_virtual', True) == is_virtual:
                qty = float(getattr(holding, 'qty', 0) or 0)
                avg_price = float(getattr(holding, 'avg_price', 0) or 0)
                symbol = getattr(holding, 'symbol', 'N/A')
                if symbol in ["1000000BABYDOGEUSDT", "1000000CHEEMSUSDT", "1000000MOGUSDT"]:
                    continue
                current_price = get_current_price_safe(symbol, client)
                value = qty * current_price if qty and current_price else 0
                holding_unrealized_pnl = value - (qty * avg_price) if qty and avg_price else 0
                total_value += value
                unrealized_pnl += holding_unrealized_pnl
                used_margin += float(getattr(holding, 'margin_usdt', 0) or 0)

        available_balance = total_capital - used_margin

        return {
            "capital": total_capital,
            "available": available_balance,
            "value": total_value,
            "unrealized_pnl": unrealized_pnl,
            "open_positions": sum(1 for h in portfolio_holdings if getattr(h, 'is_virtual', True) == is_virtual and h.symbol not in ["1000000BABYDOGEUSDT", "1000000CHEEMSUSDT", "1000000MOGUSDT"])
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

def get_portfolio_safe(db) -> List:
    """Safe wrapper for getting portfolio"""
    try:
        return db.get_portfolio()
    except Exception as e:
        logger.error(f"Error getting portfolio: {e}")
        return []

def get_trades_safe(db, limit: int = 50) -> List:
    """Safe wrapper for getting trades"""
    try:
        trades = db.get_trades(limit=limit) or []
        return [t for t in trades if getattr(t, 'symbol', 'N/A') not in ["1000000BABYDOGEUSDT", "1000000CHEEMSUSDT", "1000000MOGUSDT"]]
    except Exception as e:
        logger.error(f"Error getting trades: {e}")
        return []

def get_signals_safe(db) -> List:
    """Safe wrapper for getting signals"""
    try:
        return db.get_signals(limit=50)
    except Exception as e:
        logger.error(f"Error getting signals: {e}")
        return []

def display_trades_table(trades: List, container, client: BybitClient, max_trades=5):
    """Reusable function to display trades table"""
    try:
        if not trades:
            container.info("🌙 No trades to display")
            return

        trades_data = []
        for trade in trades[:max_trades]:
            symbol = getattr(trade, 'symbol', 'N/A')
            current_price = get_current_price_safe(symbol, client)
            qty = float(getattr(trade, 'qty', 0))
            entry_price = float(getattr(trade, 'entry_price', 0))
            unreal_pnl = (current_price - entry_price) * qty if getattr(trade, 'side', 'Buy') == "Buy" else (entry_price - current_price) * qty
            trades_data.append({
                "Symbol": symbol,
                "Side": getattr(trade, 'side', 'N/A'),
                "Entry": f"${format_price_safe(entry_price)}",
                "P&L": f"${format_currency_safe(unreal_pnl if getattr(trade, 'status', '').lower() == 'open' else getattr(trade, 'pnl', 0))}",
                "Status": getattr(trade, 'status', 'N/A').title(),
                "Mode": "Virtual" if getattr(trade, 'virtual', True) else "Real"
            })

        if trades_data:
            df = pd.DataFrame(trades_data)
            container.dataframe(df, use_container_width=True, height=300)
        else:
            container.info("🌙 No trade data to display")
    except Exception as e:
        logger.error(f"Error displaying trades table: {e}")
        container.error("🚨 Error displaying trades")

def display_signals(signals: List, container, title: str, page: int = 1, page_size: int = 5):
    """Reusable function to display signals"""
    try:
        if not signals:
            container.info("🌙 No signals to display")
            return

        signals_data = []
        for signal in signals:
            signals_data.append({
                "Symbol": signal.get("symbol", "N/A"),
                "Side": signal.get("side", "N/A"),
                "Entry": f"${format_price_safe(signal.get('entry_price', 0))}",
                "TP": f"${format_price_safe(signal.get('tp', 0))}",
                "SL": f"${format_price_safe(signal.get('sl', 0))}",
                "Score": f"{signal.get('score', 0):.1f}%",
                "Strategy": signal.get("strategy", "N/A"),
                "Time": signal.get("created_at", "N/A")
            })

        if signals_data:
            start_idx = (page - 1) * page_size
            end_idx = start_idx + page_size
            df = pd.DataFrame(signals_data[start_idx:end_idx])
            container.dataframe(df, use_container_width=True, height=300)
            col1, col2, col3 = container.columns([1, 3, 1])
            if col1.button("◀️ Previous", key=f"{title}_prev"):
                if page > 1:
                    st.session_state[f"{title.lower().replace(' ', '_')}_page"] = page - 1
                    st.rerun()
            if col3.button("Next ▶️", key=f"{title}_next"):
                if end_idx < len(signals_data):
                    st.session_state[f"{title.lower().replace(' ', '_')}_page"] = page + 1
                    st.rerun()
        else:
            container.info("🌙 No signal data to display")
    except Exception as e:
        logger.error(f"Error displaying signals: {e}")
        container.error("🚨 Error displaying signals")

def show_portfolio(db, engine, client, trading_mode: str = "virtual"):
    """Portfolio page with tabs and card-based layout"""
    st.title("💼 Portfolio")

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

    # Define tabs
    wallet_tab, holdings_tab, summary_tab = st.tabs(["💰 Wallet", "📈 Holdings", "📊 Summary"])

    # Wallet tab
    with wallet_tab:
        st.subheader("💰 Wallet Balance")
        is_virtual = trading_mode == "virtual"
        portfolio_balance = get_portfolio_balance(db, client, is_virtual)
        total_balance = portfolio_balance.get("capital", 0.0)
        available_balance = portfolio_balance.get("available", 0.0)
        unrealized_pnl = portfolio_balance.get("unrealized_pnl", 0.0)
        open_positions = portfolio_balance.get("open_positions", 0)
        if is_virtual:
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Virtual Balance", f"${format_currency_safe(total_balance)}")
                st.metric("Available", f"${format_currency_safe(available_balance)}")
            with col2:
                st.metric("Unrealized P&L", f"${format_currency_safe(unrealized_pnl)}", 
                         delta=f"{unrealized_pnl:+.2f}", 
                         delta_color="normal" if unrealized_pnl >= 0 else "inverse")
                st.metric("Open Positions", open_positions)
        else:
            if client.is_connected():
                wallet_info = client.get_wallet_balance() or {}
                col1, col2 = st.columns(2)
                with col1:
                    st.metric("Real Balance", f"${format_currency_safe(float(wallet_info.get('totalEquity', 0.0)))}")
                    st.metric("Available", f"${format_currency_safe(float(wallet_info.get('totalAvailableBalance', 0.0)))}")
                with col2:
                    st.metric("Unrealized P&L", f"${format_currency_safe(unrealized_pnl)}", 
                             delta=f"{unrealized_pnl:+.2f}", 
                             delta_color="normal" if unrealized_pnl >= 0 else "inverse")
                    st.metric("Open Positions", open_positions)
            else:
                st.info("🌙 Real wallet not connected")
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
                    is_virtual_holding = getattr(holding, 'is_virtual', True)
                    if is_virtual_holding != is_virtual:
                        continue
                    st.markdown(f"**{symbol} | {'🟢 Virtual' if is_virtual_holding else '🔴 Real'}**")
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
            display_trades_table(recent_trades, st, client)
        with col2:
            st.markdown("**Recent Signals**")
            if "recent_signals_page" not in st.session_state:
                st.session_state.recent_signals_page = 1
            recent_signals = get_signals_safe(db)
            display_signals(recent_signals, st, "Recent Signals", st.session_state.recent_signals_page, page_size=5)
        if st.button("🔄 Refresh Summary", key="portfolio_refresh_summary"):
            st.rerun()

# Initialize components
db = db_manager
engine = TradingEngine()
client = engine.client

# Run the app
show_portfolio(db, engine, client)
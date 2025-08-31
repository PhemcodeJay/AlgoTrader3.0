import streamlit as st
import logging
import pandas as pd
from typing import List, Optional, Dict
from bybit_client import BybitClient
from engine import TradingEngine
from db import db_manager
from datetime import datetime, timezone
from utils import normalize_signal, format_price_safe, format_currency_safe, display_trades_table, get_trades_safe

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, filename="app.log", filemode="a", format="%(asctime)s - %(levelname)s - %(message)s", encoding="utf-8")

def get_current_price_safe(symbol: str, client: BybitClient) -> float:
    try:
        return client.get_current_price(symbol)
    except Exception as e:
        logger.error(f"Error getting price for {symbol}: {e}")
        return 0.0

def get_portfolio_balance(db, client: BybitClient, trading_mode: str) -> Dict:
    try:
        is_virtual = trading_mode == "virtual"
        portfolio_holdings = db.get_portfolio()
        capital_data = client.load_capital(trading_mode)
        total_capital = capital_data.get("capital", 100.0 if is_virtual else 0.0)
        total_value = 0.0
        unrealized_pnl = 0.0
        used_margin = 0.0
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
        logger.error(f"Error calculating portfolio balance (trading_mode={trading_mode}): {e}")
        return {
            "capital": 100.0 if is_virtual else 0.0,
            "available": 100.0 if is_virtual else 0.0,
            "value": 0.0,
            "unrealized_pnl": 0.0,
            "open_positions": 0
        }

def get_portfolio_safe(db) -> List:
    try:
        return db.get_portfolio()
    except Exception as e:
        logger.error(f"Error getting portfolio: {e}")
        return []

def show_portfolio(db, engine, client, trading_mode: str):
    st.title("💼 Portfolio")
    st.markdown("""
        <style>
        .stApp {
            background: linear-gradient(135deg, #1e1e2f 0%, #2a2a4a 100%);
            color: #e0e0e0;
            font-family: 'Segoe UI', sans-serif;
        }
        </style>
    """, unsafe_allow_html=True)
    overview_tab, holdings_tab, summary_tab = st.tabs(["📊 Overview", "📈 Holdings", "📋 Summary"])
    is_virtual = trading_mode == "virtual"

    with overview_tab:
        st.subheader("Portfolio Overview")
        portfolio_balance = get_portfolio_balance(db, client, trading_mode)
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Capital", f"${format_currency_safe(portfolio_balance['capital'])}")
            st.metric("Available", f"${format_currency_safe(portfolio_balance['available'])}")
        with col2:
            st.metric("Portfolio Value", f"${format_currency_safe(portfolio_balance['value'])}")
            st.metric("Open Positions", portfolio_balance['open_positions'])
        with col3:
            st.metric("Unrealized P&L", f"${format_currency_safe(portfolio_balance['unrealized_pnl'])}",
                      delta=f"{portfolio_balance['unrealized_pnl']:+.2f}",
                      delta_color="normal" if portfolio_balance['unrealized_pnl'] >= 0 else "inverse")
        if st.button("🔄 Refresh Overview", key="portfolio_refresh_overview"):
            st.rerun()

    with holdings_tab:
        st.subheader("Portfolio Holdings")
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
            recent_signals = db.get_signals(limit=20)
            recent_signals = [normalize_signal(sig) for sig in recent_signals]
            display_signals(
                recent_signals,
                st,
                "Recent Signals",
                st.session_state.recent_signals_page,
                page_size=5
            )
        if st.button("🔄 Refresh Summary", key="portfolio_refresh_summary"):
            st.rerun()

def display_signals(signals: List, container, title: str, page: int = 1, page_size: int = 5):
    try:
        if not signals:
            container.info(f"🌙 No {title.lower()} to display")
            return
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        signals_data = []
        for signal in signals[start_idx:end_idx]:
            signals_data.append({
                "Symbol": signal.get("symbol", "N/A"),
                "Side": signal.get("side", "N/A"),
                "Entry": f"${format_price_safe(signal.get('entry'))}",
                "TP": f"${format_price_safe(signal.get('tp'))}",
                "SL": f"${format_price_safe(signal.get('sl'))}",
                "Score": f"{signal.get('score', 0):.1f}%"
            })
        if signals_data:
            df = pd.DataFrame(signals_data)
            container.dataframe(df, use_container_width=True)
        else:
            container.info(f"🌙 No {title.lower()} to display")
    except Exception as e:
        logger.error(f"Error displaying signals: {e}")
        container.error(f"🚨 Error displaying signals: {e}")

# Initialize components
db = db_manager
engine = TradingEngine()
client = engine.client

# Run the app
show_portfolio(db, engine, client, st.session_state.trading_mode)
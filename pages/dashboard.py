import streamlit as st
import pandas as pd
import logging
from datetime import datetime, timezone
from typing import List, Optional, Dict
from bybit_client import BybitClient
from engine import TradingEngine
from db import db_manager
from utils import format_price_safe, format_currency_safe, display_trades_table, get_trades_safe

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, filename="app.log", filemode="a", format="%(asctime)s - %(levelname)s - %(message)s", encoding="utf-8")

def get_trades_safe(db, symbol: Optional[str] = None, limit: int = 50) -> List[Dict]:
    """
    Safely fetch trades from the database and normalize them into dicts.
    Filters out unwanted meme-coins.
    """
    try:
        if not db or not hasattr(db, "get_trades"):
            logger.error("❌ db has no method 'get_trades'")
            return []

        trades = db.get_trades(symbol=symbol, limit=limit) or []

        # Normalize to dict
        normalized = []
        for t in trades:
            if getattr(t, "symbol", "N/A") in ["1000000BABYDOGEUSDT", "1000000CHEEMSUSDT", "1000000MOGUSDT"]:
                continue

            normalized.append({
                "id": getattr(t, "id", None),
                "symbol": getattr(t, "symbol", "N/A"),
                "side": getattr(t, "side", "Buy"),
                "qty": float(getattr(t, "qty", 0)),
                "entry_price": float(getattr(t, "entry_price", 0)),
                "pnl": float(getattr(t, "pnl", 0)),
                "status": getattr(t, "status", "N/A"),
                "virtual": getattr(t, "virtual", True),
                "timestamp": str(getattr(t, "timestamp", "")),
            })

        return normalized

    except Exception as e:
        logger.error(f"🚨 Error fetching trades (symbol={symbol}): {e}")
        return []


def show_dashboard(db, engine, client, trading_mode: str):
    st.title("📈 Dashboard")
    overview_tab, market_tab, trades_tab = st.tabs(["📊 Overview", "🌐 Market", "📋 Trades"])

    with overview_tab:
        with st.container(border=True):
            st.subheader("Portfolio Overview")
            portfolio_balance = engine.load_capital(trading_mode)
            total_balance = portfolio_balance.get("capital", 0.0)
            open_positions = len(db.get_open_trades())
            daily_pnl = db.get_daily_pnl_pct()
            trades = get_trades_safe(db)
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Portfolio Balance", f"{format_currency_safe(total_balance)}")
            with col2:
                st.metric("Open Positions", open_positions)
            with col3:
                st.metric("Daily P&L", f"{format_currency_safe(daily_pnl)}", 
                         delta=f"{daily_pnl:+.2f}", 
                         delta_color="normal" if daily_pnl >= 0 else "inverse")
            with col4:
                st.metric("Total Trades", len(trades))
            if st.button("🔄 Refresh Metrics", key="refresh_metrics_overview_tab"):
                st.rerun()

    with market_tab:
        st.subheader("🌐 Market Overview")
        with st.spinner("Fetching market data..."):
            market_data = client.get_tickers()
        if market_data:
            cols = st.columns(min(6, len(market_data)))
            for i, ticker in enumerate(market_data[:6]):
                symbol = ticker.get("symbol", "N/A")
                price = float(ticker.get("lastPrice", 0))
                change = float(ticker.get("price24hPcnt", 0)) * 100
                with cols[i]:
                    with st.container(border=True):
                        try:
                            change_pct = float(change)
                            delta_color = "normal" if change_pct >= 0 else "inverse"
                            st.metric(
                                label=symbol.replace("USDT", ""),
                                value=format_currency_safe(price),
                                delta=f"{change_pct:+.2f}%",
                                delta_color=delta_color,
                            )
                        except (ValueError, TypeError) as e:
                            logger.error(f"Error formatting market data for {symbol}: {e}")
                            st.metric(symbol.replace("USDT", ""), format_currency_safe(price))
            if st.button("🔄 Refresh Market Data", key="market_refresh_data"):
                st.rerun()
        else:
            st.info("🌙 No market data available. Please try refreshing.")

    with trades_tab:
        st.subheader("📋 Recent Trades")
        display_trades_table(get_trades_safe(db), st, client)
        if st.button("🔄 Refresh Trades", key="trades_refresh_data"):
            st.rerun()

# Initialize components
db = db_manager
engine = TradingEngine()
client = engine.client

# Run the app
show_dashboard(db, engine, client, st.session_state.trading_mode)
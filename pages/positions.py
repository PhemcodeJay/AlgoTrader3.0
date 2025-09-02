import streamlit as st
import logging
from datetime import datetime, timezone
from typing import List, Optional
from bybit_client import BybitClient
from engine import TradingEngine
from db import db_manager
import pandas as pd
from utils import format_price_safe, format_currency_safe, display_trades_table

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, filename="app.log", filemode="a", format="%(asctime)s - %(levelname)s - %(message)s", encoding="utf-8")

def get_current_price_safe(symbol: str, client: BybitClient) -> float:
    try:
        return client.get_current_price(symbol)
    except Exception as e:
        logger.error(f"Error getting price for {symbol}: {e}")
        return 0.0

def get_open_trades_safe(db, trading_mode: str) -> List:
    try:
        is_virtual = (trading_mode.lower() == "virtual")
        trades = db.get_open_trades() or []
        filtered = []
        for t in trades:
            symbol = getattr(t, "symbol", "N/A")
            is_virtual_trade = getattr(t, "virtual", True)
            if symbol not in ["1000000BABYDOGEUSDT", "1000000CHEEMSUSDT", "1000000MOGUSDT"] \
               and is_virtual_trade == is_virtual:
                filtered.append(t)
        return filtered
    except Exception as e:
        logger.error(f"🚨 Error getting open trades (mode={trading_mode}): {e}")
        return []

def show_positions(db, engine, client, trading_mode: str):
    # Initialize trading_mode in session_state if not set
    if 'trading_mode' not in st.session_state:
        st.session_state.trading_mode = trading_mode  # Default to passed value or set explicitly

    st.title("📊 Positions")
    st.markdown("""
        <style>
        .stApp {
            background: linear-gradient(135deg, #1e1e2f 0%, #2a2a4a 100%);
            color: #e0e0e0;
            font-family: 'Segoe UI', sans-serif;
        }
        </style>
    """, unsafe_allow_html=True)
    open_tab, new_tab = st.tabs(["🟢 Open Positions", "➕ New Position"])
    is_virtual = st.session_state.trading_mode == "virtual"

    with open_tab:
        st.subheader("🟢 Open Positions")
        open_trades = get_open_trades_safe(db, st.session_state.trading_mode)
        display_trades_table(open_trades, st, client)
        if st.button("🔄 Refresh Positions", key="refresh_positions"):
            st.rerun()

    with new_tab:
        st.subheader("➕ Open New Position")
        with st.container(border=True):
            col1, col2 = st.columns(2)
            with col1:
                symbol = st.selectbox("Symbol", engine.get_usdt_symbols(), key="pos_symbol")
                side = st.selectbox("Side", ["LONG", "SHORT"], key="pos_side")
                order_type = st.selectbox("Order Type", ["Market", "Limit"], key="pos_order_type")
            with col2:
                entry_price = st.number_input("Entry Price", value=get_current_price_safe(symbol, client), min_value=0.0, key="pos_entry_price")
                leverage = st.number_input("Leverage", value=10, min_value=1, max_value=100, key="pos_leverage")
                margin_usdt = st.number_input("Margin (USDT)", value=10.0, min_value=1.0, key="pos_margin")
                position_size = (margin_usdt * leverage) / entry_price if entry_price > 0 else 0
                st.info(f"Position Size: {position_size:.6f}")
            col1, col2 = st.columns(2)
            with col1:
                tp_pct = st.number_input("Take Profit %", value=3.0, min_value=0.1, max_value=100.0, key="pos_tp_pct")
                tp_price = entry_price * (1 + tp_pct/100) if side == "LONG" else entry_price * (1 - tp_pct/100)
                st.metric("TP", f"${format_price_safe(tp_price)}")
            with col2:
                sl_pct = st.number_input("Stop Loss %", value=1.5, min_value=0.1, max_value=100.0, key="pos_sl_pct")
                sl_price = entry_price * (1 - sl_pct/100) if side == "LONG" else entry_price * (1 + sl_pct/100)
                st.metric("SL", f"${format_price_safe(sl_price)}")
            if st.button("🚀 Open Position", type="primary", key="open_position"):
                try:
                    capital_data = client.load_capital(st.session_state.trading_mode)
                    if margin_usdt > capital_data.get("available", 0.0):
                        st.error(f"🚨 Insufficient {st.session_state.trading_mode} funds: {margin_usdt} > {capital_data.get('available', 0.0)}")
                        return
                    if entry_price <= 0 or margin_usdt <= 0 or position_size <= 0:
                        st.error("🚨 Invalid input: Entry price, margin, or position size must be positive")
                        return
                    order_side = "Buy" if side == "LONG" else "Sell"
                    result = client.place_order(
                        symbol=symbol,
                        side=order_side,
                        order_type=order_type,
                        qty=position_size,
                        price=entry_price if order_type == "Limit" else 0.0,
                        stop_loss=sl_price,
                        take_profit=tp_price
                    )
                    if result:
                        trade_data = {
                            "symbol": symbol,
                            "side": order_side,
                            "qty": position_size,
                            "entry_price": entry_price,
                            "stop_loss": sl_price,
                            "take_profit": tp_price,
                            "leverage": leverage,
                            "margin_usdt": margin_usdt,
                            "status": "open",
                            "order_id": result.get("order_id"),
                            "virtual": is_virtual
                        }
                        db.add_trade(trade_data)
                        st.success(f"✅ Position opened at ${format_price_safe(entry_price)}")
                        st.rerun()
                    else:
                        st.error("🚨 Failed to open position via client")
                except Exception as e:
                    logger.error(f"Error opening position: {e}")
                    st.error(f"Error opening position: {e}")

# Initialize components
db = db_manager
engine = TradingEngine()
client = engine.client

# Initialize trading_mode if not set
if 'trading_mode' not in st.session_state:
    st.session_state.trading_mode = "virtual"  # Default to 'virtual' or your preferred mode

# Run the app
show_positions(db, engine, client, st.session_state.trading_mode)
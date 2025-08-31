import streamlit as st
import logging
import pandas as pd
from datetime import datetime, timezone
from typing import List, Optional
from bybit_client import BybitClient
from engine import TradingEngine
from db import db_manager
from utils import format_price_safe, format_currency_safe, display_trades_table, get_trades_safe

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, filename="app.log", filemode="a", format="%(asctime)s - %(levelname)s - %(message)s", encoding="utf-8")

def get_current_price_safe(symbol: str, client: BybitClient) -> float:
    try:
        return client.get_current_price(symbol)
    except Exception as e:
        logger.error(f"Error getting price for {symbol}: {e}")
        return 0.0

def show_orders(db, engine, client, trading_mode: str):
    st.title("📋 Orders")
    st.markdown("""
        <style>
        .stApp {
            background: linear-gradient(135deg, #1e1e2f 0%, #2a2a4a 100%);
            color: #e0e0e0;
            font-family: 'Segoe UI', sans-serif;
        }
        </style>
    """, unsafe_allow_html=True)
    is_virtual = trading_mode == "virtual"
    open_tab, closed_tab = st.tabs(["🟢 Open Orders", "🔴 Closed Orders"])

    with open_tab:
        st.subheader("🟢 Open Orders")
        open_trades = [t for t in get_trades_safe(db) if getattr(t, 'status', '').lower() == 'open' and getattr(t, 'virtual', True) == is_virtual]
        if open_trades:
            for index, trade in enumerate(open_trades):
                with st.container(border=True):
                    symbol = getattr(trade, 'symbol', 'N/A')
                    side = getattr(trade, 'side', 'Buy')
                    is_virtual_trade = getattr(trade, 'virtual', True)
                    qty = float(getattr(trade, 'qty', 0))
                    entry_price = float(getattr(trade, 'entry_price', 0))
                    current_price = get_current_price_safe(symbol, client)
                    unreal_pnl = (current_price - entry_price) * qty if side in ["Buy", "LONG"] else (entry_price - current_price) * qty
                    st.markdown(f"**{symbol} | {side} | {'🟢 Virtual' if is_virtual_trade else '🔴 Real'}**")
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("Quantity", f"{qty:.6f}")
                        st.metric("Entry Price", f"${format_price_safe(entry_price)}")
                    with col2:
                        st.metric("Current Price", f"${format_price_safe(current_price)}")
                        st.metric("Unrealized P&L", f"${format_currency_safe(unreal_pnl)}", 
                                 delta=f"{unreal_pnl:+.2f}", 
                                 delta_color="normal" if unreal_pnl >= 0 else "inverse")
                    with col3:
                        order_id = getattr(trade, 'order_id', None)
                        if order_id:
                            if st.button("❌ Close", key=f"close_order_{order_id}_{index}"):
                                logger.info(f"Attempting to close order: {order_id}, symbol={symbol}, side={side}, qty={qty}")
                                result = client.close_position(symbol=symbol, side=side, qty=qty)
                                if result:
                                    logger.info(f"Updating trade in DB: order_id={order_id}, exit_price={current_price}, pnl={unreal_pnl}")
                                    db.close_trade(order_id=order_id, exit_price=current_price, pnl=unreal_pnl)
                                    st.success(f"✅ Order {order_id} closed")
                                    st.rerun()
                                else:
                                    st.error(f"🚨 Failed to close order {order_id}: Check logs for details")
                        else:
                            st.error("🚨 Missing order ID")
        else:
            st.info("🌙 No open orders")
        if st.button("🔄 Refresh Orders", key="refresh_open_orders"):
            st.rerun()

    with closed_tab:
        st.subheader("🔴 Closed Orders")
        closed_trades = [t for t in get_trades_safe(db) if getattr(t, 'status', '').lower() == 'closed' and getattr(t, 'virtual', True) == is_virtual]
        display_trades_table(closed_trades, st, client)
        if st.button("🔄 Refresh Closed Orders", key="refresh_closed_orders"):
            st.rerun()

# Initialize components
db = db_manager
engine = TradingEngine()
client = engine.client

# Run the app
show_orders(db, engine, client, st.session_state.trading_mode)
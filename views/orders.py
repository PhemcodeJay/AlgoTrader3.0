import streamlit as st
import logging
import pandas as pd
from datetime import datetime, timezone
from typing import List, Optional
from bybit_client import BybitClient
from engine import TradingEngine
from db import db_manager
from utils import format_price_safe, format_currency_safe

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, filename="app.log", filemode="a", format="%(asctime)s - %(levelname)s - %(message)s", encoding="utf-8")

def get_current_price_safe(symbol: str, client: BybitClient) -> float:
    try:
        return client.get_current_price(symbol)
    except Exception as e:
        logger.error(f"Error getting price for {symbol}: {e}")
        return 0.0

def get_trades_safe(db, limit: int = 50) -> List:
    try:
        trades = db.get_trades(limit=limit) or []
        return [t for t in trades if getattr(t, 'symbol', 'N/A') not in ["1000000BABYDOGEUSDT", "1000000CHEEMSUSDT", "1000000MOGUSDT"]]
    except Exception as e:
        logger.error(f"Error getting trades: {e}")
        return []

def display_trades_table(trades, container, client: BybitClient, max_trades=5):
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

def show_orders(db, engine, client, trading_mode: str = "virtual"):
    """Orders page with tabs and card-based layout"""
    st.title("📋 Orders")

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
            font-weight: 400;
            border-radius: 8px;
            margin: 5px;
            padding: 10px 20px;
            transition: all 0.3s ease;
        }
        .stTabs [data-baseweb="tab"][aria-selected="true"] {
            background: linear-gradient(45deg, #6366f1, #a855f7);
            color: #ffffff;
            font-weight: 400;
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
            overflow: hidden;
        }
        .stMetric > div {
            font-size: 1.2rem;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .stSelectbox, .stNumberInput {
            background: #3b3b5e;
            border-radius: 8px;
            padding: 5px;
        }
        </style>
    """, unsafe_allow_html=True)

    # Define tabs
    open_tab, closed_tab = st.tabs(["🟢 Open Orders", "🔴 Closed Orders"])

    # Open Orders tab
    with open_tab:
        st.subheader("🟢 Open Orders")
        is_virtual = trading_mode == "virtual"
        if not is_virtual and client.is_connected():
            with st.spinner("Fetching real-time orders from Bybit..."):
                orders = client.get_open_orders() or []
                logger.info(f"Real orders fetched: {orders}")
                if orders:
                    for index, order in enumerate(orders):
                        with st.container(border=True):
                            symbol = order.get('symbol', 'N/A')
                            side = order.get('side', 'N/A')
                            qty = float(order.get('qty', 0))
                            entry_price = float(order.get('price', 0))
                            current_price = get_current_price_safe(symbol, client)
                            unreal_pnl = (current_price - entry_price) * qty if side == "Buy" else (entry_price - current_price) * qty
                            st.markdown(f"**{symbol} | {side} | 🔴 Real**")
                            col1, col2, col3 = st.columns(3)
                            with col1:
                                st.metric("Quantity", f"{qty:.6f}")
                                st.metric("Entry Price", f"${format_price_safe(entry_price)}")
                            with col2:
                                st.metric("Current Price", f"${format_price_safe(current_price)}")
                                st.metric("Unrealized P&L", f"{format_currency_safe(unreal_pnl)}", 
                                         delta=f"{unreal_pnl:+.2f}", 
                                         delta_color="normal" if unreal_pnl >= 0 else "inverse")
                            with col3:
                                order_id = order.get('orderId', None)
                                if order_id:
                                    if st.button("❌ Close", key=f"close_real_order_{order_id}_{index}"):
                                        logger.info(f"Attempting to close real order: {order_id}, symbol={symbol}, side={side}, qty={qty}")
                                        result = client.close_position(symbol=symbol, side=side, qty=qty)
                                        if result:
                                            st.success(f"✅ Order {order_id} closed")
                                            st.rerun()
                                        else:
                                            st.error(f"🚨 Failed to close order {order_id}: Check logs for details")
                                else:
                                    st.error("🚨 Missing order ID")
                else:
                    st.info("🌙 No open orders on Bybit")
        else:
            open_trades = get_trades_safe(db)
            filtered_trades = [t for t in open_trades if getattr(t, 'status', '').lower() == 'open' and getattr(t, 'virtual', True) == is_virtual]
            logger.info(f"Virtual open trades: {filtered_trades}")
            if filtered_trades:
                for index, trade in enumerate(filtered_trades):
                    with st.container(border=True):
                        symbol = getattr(trade, 'symbol', 'N/A')
                        side = getattr(trade, 'side', 'N/A')
                        qty = float(getattr(trade, 'qty', 0))
                        entry_price = float(getattr(trade, 'entry_price', 0))
                        current_price = get_current_price_safe(symbol, client)
                        unreal_pnl = (current_price - entry_price) * qty if side == "Buy" else (entry_price - current_price) * qty
                        st.markdown(f"**{symbol} | {side} | {'🟢 Virtual' if is_virtual else '🔴 Real'}**")
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
                                    logger.info(f"Attempting to close virtual order: {order_id}, symbol={symbol}, side={side}, qty={qty}")
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

    # Closed Orders tab
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
show_orders(db, engine, client)
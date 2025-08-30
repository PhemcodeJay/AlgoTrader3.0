import streamlit as st
import time
import logging
from datetime import datetime, timezone
from typing import List, Optional
from bybit_client import BybitClient
from engine import TradingEngine
from db import db_manager, Trade
import pandas as pd

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, filename="app.log", filemode="a", format="%(asctime)s - %(levelname)s - %(message)s", encoding="utf-8")

def get_current_price_safe(symbol: str, client: BybitClient) -> float:
    try:
        return client.get_current_price(symbol)
    except Exception as e:
        logger.error(f"Error getting price for {symbol}: {e}")
        return 0.0

def format_price_safe(value: Optional[float]) -> str:
    return f"{value:.2f}" if value is not None and value > 0 else "N/A"

def format_currency_safe(value: Optional[float]) -> str:
    return f"{value:.2f}" if value is not None else "0.00"

def get_open_trades_safe(db) -> List:
    try:
        trades = db.get_open_trades() or []
        return [t for t in trades if getattr(t, 'symbol', 'N/A') not in ["1000000BABYDOGEUSDT", "1000000CHEEMSUSDT", "1000000MOGUSDT"]]
    except Exception as e:
        logger.error(f"Error getting open trades: {e}")
        return []

def display_trades_table(trades: List, container, client: BybitClient):
    if not trades:
        container.info("🌙 No open positions at the moment.")
        return
    trades_data = []
    for trade in trades:
        symbol = getattr(trade, 'symbol', 'N/A')
        current_price = get_current_price_safe(symbol, client)
        qty = float(getattr(trade, 'qty', 0))
        entry_price = float(getattr(trade, 'entry_price', 0))
        unreal_pnl = (current_price - entry_price) * qty if getattr(trade, 'side', 'Buy') == "Buy" else (entry_price - current_price) * qty
        trades_data.append({
            "Symbol": symbol,
            "Side": getattr(trade, 'side', 'N/A'),
            "Quantity": qty,
            "Entry Price": f"${format_price_safe(entry_price)}",
            "Current Price": f"${format_price_safe(current_price)}",
            "Unrealized P&L": f"${format_currency_safe(unreal_pnl)}",
            "Status": getattr(trade, 'status', 'N/A').title(),
            "Mode": "Virtual" if getattr(trade, 'virtual', True) else "Real"
        })
    if trades_data:
        df = pd.DataFrame(trades_data)
        container.dataframe(df, use_container_width=True)
    else:
        container.info("🌙 No open positions")

def show_positions(db, engine, client, trading_mode: str = "virtual"):
    """Positions page with tabs and card-based layout"""
    st.title("📊 Positions")

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
    positions_tab, open_tab = st.tabs(["📈 Positions", "🚀 Open Position"])

    # Positions tab
    with positions_tab:
        st.subheader("📋 Open Positions")
        is_virtual = trading_mode == "virtual"
        if not is_virtual and client.is_connected():
            with st.spinner("Fetching real-time positions from Bybit..."):
                positions = client.get_positions() or []
                if positions:
                    for pos in positions:
                        with st.container(border=True):
                            symbol = pos.get('symbol', 'N/A')
                            side = pos.get('side', 'N/A')
                            size = float(pos.get('size', 0))
                            entry_price = float(pos.get('entryPrice', 0))
                            unreal_pnl = float(pos.get('unrealisedPnl', 0))
                            current_price = get_current_price_safe(symbol, client)
                            st.markdown(f"**{symbol} | {side} | 🔴 Real**")
                            col1, col2, col3 = st.columns(3)
                            with col1:
                                st.metric("Size", f"{size:.6f}")
                                st.metric("Entry Price", f"${format_price_safe(entry_price)}")
                            with col2:
                                st.metric("Current Price", f"${format_price_safe(current_price)}")
                                st.metric("Unrealized P&L", f"${format_currency_safe(unreal_pnl)}", 
                                         delta=f"{unreal_pnl:+.2f}", 
                                         delta_color="normal" if unreal_pnl >= 0 else "inverse")
                            with col3:
                                if st.button("❌ Close", key=f"close_real_pos_{pos.get('orderId')}"):
                                    result = client.close_position(symbol=symbol, side=side, qty=size)
                                    if result:
                                        st.success(f"✅ Position closed")
                                        st.rerun()
                                    else:
                                        st.error("🚨 Failed to close position")
                else:
                    st.info("🌙 No open positions on Bybit")
        else:
            open_trades = get_open_trades_safe(db)
            filtered_trades = [t for t in open_trades if getattr(t, 'virtual', True) == is_virtual]
            display_trades_table(filtered_trades, st, client)
        if st.button("🔄 Refresh Positions", key="refresh_positions"):
            st.rerun()

    # Open Position tab
    with open_tab:
        st.subheader("🚀 Open New Position")
        col1, col2, col3 = st.columns(3)
        with col1:
            symbols = engine.get_usdt_symbols()
            symbol = st.selectbox("Symbol", symbols, key="pos_symbol")
            current_price = get_current_price_safe(symbol, client)
            st.metric("Current Price", f"${format_price_safe(current_price)}")
        with col2:
            side = st.selectbox("Side", ["LONG", "SHORT"], key="pos_side")
            order_type = st.selectbox("Order Type", ["Market", "Limit"], key="pos_order_type")
            if order_type == "Limit":
                entry_price = st.number_input("Entry Price", value=current_price or 0.0, min_value=0.0001, step=0.0001, key="pos_entry_price")
            else:
                entry_price = current_price
        with col3:
            leverage = st.slider("Leverage", 1, 50, 10, key="pos_leverage")
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

# Run the app
show_positions(db, engine, client)
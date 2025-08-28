import streamlit as st
import time
import logging
from datetime import datetime
from typing import List, Optional
from bybit_client import BybitClient
from engine import TradingEngine
from db import db_manager

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Utility functions
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
        return db.get_open_trades()
    except Exception as e:
        logger.error(f"Error getting open trades: {e}")
        return []

def display_trades_table(trades: List, st):
    if not trades:
        st.info("🌙 No open positions at the moment.")
        return
    st.markdown("### 📊 Open Trades")
    data = [trade.to_dict() for trade in trades]
    st.dataframe(data, use_container_width=True)

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
    .stButton > button[kind="primary"] {
        background: linear-gradient(45deg, #10b981, #34d399);
    }
    .stButton > button[kind="primary"]:hover {
        background: linear-gradient(45deg, #34d399, #6ee7b7);
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

    /* Info and success messages */
    .stAlert {
        border-radius: 8px;
        background: rgba(255,255,255,0.1);
        color: #ffffff;
    }

    /* Selectbox and inputs */
    .stSelectbox, .stNumberInput {
        background: #3b3b5e;
        border-radius: 8px;
        padding: 5px;
    }
    .stSelectbox > div > div, .stNumberInput > div > div {
        color: #ffffff;
    }
    </style>
""", unsafe_allow_html=True)

def show_positions(db, engine, client):
    """Position management with tabs and card-based layout"""
    st.title("💼 Position Management")

    if not db or not hasattr(db, 'get_open_trades'):
        st.error("🚨 Database connection not available")
        return

    try:
        # Define tabs
        form_tab, positions_tab = st.tabs(["🚀 Open Position", "📊 Positions"])

        # Open Position Form tab
        with form_tab:
            with st.container(border=True):
                st.markdown("### Open New Position")
                show_position_form(db, client, engine)

        # Positions tab
        with positions_tab:
            st.subheader("📊 Open Positions")
            open_trades = get_open_trades_safe(db)
            if open_trades:
                for i, trade in enumerate(open_trades):
                    with st.container(border=True):
                        try:
                            symbol = getattr(trade, 'symbol', 'N/A')
                            current_price = get_current_price_safe(symbol, client)
                            entry_price = float(getattr(trade, 'entry_price', 0))
                            qty = float(getattr(trade, 'qty', 0))
                            side = getattr(trade, 'side', 'N/A')
                            leverage = getattr(trade, 'leverage', 1)
                            margin_usdt = getattr(trade, 'margin_usdt', 0)
                            tp_price = getattr(trade, 'take_profit', None)
                            sl_price = getattr(trade, 'stop_loss', None)
                            # Handle missing attributes
                            trail_price = getattr(trade, 'trail', None)
                            liquidation_price = getattr(trade, 'liquidation', None)

                            # Calculate P&L
                            if qty > 0:
                                if side.upper() in ['BUY', 'LONG']:
                                    unrealized_pnl = (current_price - entry_price) * qty
                                else:
                                    unrealized_pnl = (entry_price - current_price) * qty
                            else:
                                unrealized_pnl = 0

                            st.markdown(f"**{symbol} | {side} | {'🟢 Virtual' if getattr(trade, 'virtual', True) else '🔴 Real'}**")
                            col1, col2, col3, col4 = st.columns(4)
                            with col1:
                                st.metric("Entry", f"${format_price_safe(entry_price)}")
                                st.metric("Market", f"${format_price_safe(current_price)}")
                            with col2:
                                st.metric("TP", f"${format_price_safe(tp_price)}")
                                st.metric("SL", f"${format_price_safe(sl_price)}")
                            with col3:
                                st.metric("P&L", f"${format_currency_safe(unrealized_pnl)}")
                                st.metric("Margin", f"${format_currency_safe(margin_usdt)}")
                            with col4:
                                st.markdown(f"**Leverage**: {leverage}x")
                                st.metric("Liquidation", f"${format_price_safe(liquidation_price)}")
                            col1, col2, col3 = st.columns(3)
                            with col1:
                                if st.button("❌ Close Position", key=f"close_pos_{i}"):
                                    try:
                                        order_id = getattr(trade, 'order_id', None)
                                        if order_id:
                                            # Close trade using BybitClient
                                            result = client.close_position(symbol=symbol, side=side, qty=str(qty))
                                            if result:
                                                # Update database with closed trade details
                                                db.close_trade(
                                                    order_id=order_id,
                                                    exit_price=current_price,
                                                    pnl=unrealized_pnl
                                                )
                                                st.success(f"✅ Position {symbol} closed successfully")
                                                st.rerun()
                                            else:
                                                st.error("Failed to close position via client")
                                        else:
                                            st.error("Cannot close position - missing order ID")
                                    except Exception as e:
                                        logger.error(f"Error closing position: {e}")
                                        st.error(f"Error closing position: {e}")
                            with col2:
                                if st.button("🎯 Update TP/SL", key=f"update_tpsl_{i}"):
                                    st.info("🔧 TP/SL update feature coming soon")
                            with col3:
                                mode_color = "🟢" if getattr(trade, 'virtual', True) else "🔴"
                                mode_text = "Virtual" if getattr(trade, 'virtual', True) else "Real"
                                st.info(f"{mode_color} {mode_text} Trade")
                        except Exception as e:
                            logger.error(f"Error processing trade: {e}")
                            st.error(f"Error displaying trade {i}: {e}")
            else:
                display_trades_table(open_trades, st)
            if st.button("🔄 Refresh Positions", key="refresh_positions"):
                st.rerun()

    except Exception as e:
        logger.error(f"Error in positions: {e}")
        st.error(f"Positions error: {str(e)}")

def show_position_form(db, client, engine):
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
            entry_price = st.number_input("Entry Price", value=current_price, min_value=0.0001, step=0.0001, key="pos_entry_price")
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
                    "virtual": not client.use_real
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
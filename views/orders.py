import streamlit as st
import logging
from datetime import datetime
from typing import List, Optional
from bybit_client import BybitClient
from engine import TradingEngine
from db import db_manager
import pandas as pd

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Utility functions
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

    /* Selectbox and inputs */
    .stSelectbox, .stNumberInput {
        background: #3b3b5e;
        border-radius: 8px;
        padding: 5px;
    }
    .stSelectbox > div > div, .stNumberInput > div > div {
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

def get_filtered_trades(db, status_filter: str, mode_filter: str, limit: int) -> List:
    """Filter trades based on status and mode"""
    try:
        if status_filter == "All":
            trades = get_trades_safe(db, limit=limit)
        else:
            trades = db.get_trades_by_status(status_filter.lower())
            trades = trades[:limit]  # Apply limit after filtering
        filtered_trades = []
        for trade in trades:
            is_virtual = getattr(trade, 'virtual', True)
            if mode_filter == "Virtual" and not is_virtual:
                continue
            elif mode_filter == "Real" and is_virtual:
                continue
            filtered_trades.append(trade)
        return filtered_trades
    except Exception as e:
        logger.error(f"Error filtering trades: {e}")
        return []

def show_orders(db, engine, client):
    """Enhanced order management with tabs, cards, and buttons"""
    st.title("📋 Order Management")

    if not db or not hasattr(db, 'get_trades'):
        st.error("🚨 Database connection not available")
        return

    try:
        # Define tabs
        filters_tab, orders_tab = st.tabs(["🔍 Filters", "📊 Orders"])

        # Filters tab
        with filters_tab:
            with st.container(border=True):
                st.markdown("### Order Filters")
                col1, col2, col3 = st.columns(3)
                with col1:
                    status_filter = st.selectbox("Status", ["All", "Open", "Closed"], key="status_filter")
                with col2:
                    mode_filter = st.selectbox("Mode", ["All", "Virtual", "Real"], key="mode_filter")
                with col3:
                    limit = st.number_input("Max Orders", min_value=1, max_value=500, value=50, key="limit_orders")
                if st.button("🔄 Apply Filters", key="apply_filters"):
                    st.rerun()

        # Orders tab
        with orders_tab:
            filtered_trades = get_filtered_trades(db, status_filter, mode_filter, limit)
            st.subheader(f"📊 Orders ({len(filtered_trades)} found)")
            if filtered_trades:
                for i, trade in enumerate(filtered_trades):
                    with st.container(border=True):
                        try:
                            symbol = getattr(trade, 'symbol', 'N/A')
                            current_price = get_current_price_safe(symbol, client)
                            entry_price = float(getattr(trade, 'entry_price', 0))
                            exit_price = getattr(trade, 'exit_price', None)
                            qty = float(getattr(trade, 'qty', 0))
                            side = getattr(trade, 'side', 'N/A')
                            leverage = getattr(trade, 'leverage', 1)
                            margin_usdt = getattr(trade, 'margin_usdt', 0)
                            tp_price = getattr(trade, 'take_profit', None) or (entry_price * 1.3 if side.upper() in ['BUY', 'LONG'] else entry_price * 0.7)
                            sl_price = getattr(trade, 'stop_loss', None) or (entry_price * 0.9 if side.upper() in ['BUY', 'LONG'] else entry_price * 1.1)
                            # Handle missing attributes
                            trail_price = getattr(trade, 'trail', None)
                            liquidation_price = getattr(trade, 'liquidation', None)
                            timestamp = getattr(trade, 'timestamp', None)
                            time_str = timestamp.strftime("%Y-%m-%d %H:%M:%S") if timestamp and hasattr(timestamp, 'strftime') else "N/A"

                            # Calculate P&L
                            if exit_price:
                                if side.upper() in ['BUY', 'LONG']:
                                    realized_pnl = (float(exit_price) - entry_price) * qty if qty > 0 else 0
                                else:
                                    realized_pnl = (entry_price - float(exit_price)) * qty if qty > 0 else 0
                                estimated_pnl = realized_pnl
                            else:
                                if side.upper() in ['BUY', 'LONG']:
                                    unrealized_pnl = (current_price - entry_price) * qty if qty > 0 else 0
                                else:
                                    unrealized_pnl = (entry_price - current_price) * qty if qty > 0 else 0
                                estimated_pnl = unrealized_pnl

                            st.markdown(f"**{symbol} | {side} | {getattr(trade, 'status', 'N/A').title()} | {'🟢 Virtual' if getattr(trade, 'virtual', True) else '🔴 Real'}**")
                            col1, col2, col3 = st.columns(3)
                            with col1:
                                st.metric("Entry", f"${format_price_safe(entry_price)}")
                                st.metric("Market", f"${format_price_safe(current_price)}")
                                st.metric("Exit", f"${format_price_safe(exit_price)}")
                            with col2:
                                st.metric("TP", f"${format_price_safe(tp_price)}")
                                st.metric("SL", f"${format_price_safe(sl_price)}")
                                st.metric("Timestamp", time_str)
                            with col3:
                                st.metric("P&L", f"${format_currency_safe(estimated_pnl)}")
                                st.markdown(f"**Leverage**: {leverage}x")
                                st.metric("Margin", f"${format_currency_safe(margin_usdt)}")
                            if getattr(trade, 'status', '').lower() == 'open':
                                if st.button("❌ Close Order", key=f"close_order_{i}_{getattr(trade, 'order_id', id(trade))}"):
                                    try:
                                        order_id = getattr(trade, 'order_id', None)
                                        if order_id:
                                            # Close trade using BybitClient
                                            result = client.close_position(symbol=symbol, side=side, qty=str(qty))
                                            if result:
                                                # Update database
                                                db.close_trade(
                                                    order_id=order_id,
                                                    exit_price=current_price,
                                                    pnl=unrealized_pnl
                                                )
                                                st.success(f"✅ Order {symbol} closed successfully")
                                                st.rerun()
                                            else:
                                                st.error("🚨 Failed to close order via client")
                                        else:
                                            st.error("🚨 Cannot close order - missing order ID")
                                    except Exception as e:
                                        logger.error(f"Error closing order: {e}")
                                        st.error(f"Error closing order: {e}")
                        except Exception as e:
                            logger.error(f"Error processing trade for orders: {e}")
                            st.error(f"Error displaying order: {e}")
            else:
                display_trades_table(filtered_trades, st)
            if st.button("🔄 Refresh Orders", key="refresh_orders"):
                st.rerun()

    except Exception as e:
        logger.error(f"Error in orders: {e}")
        st.error(f"🚨 Orders error: {str(e)}")

# Initialize components
db = db_manager
engine = TradingEngine()
client = engine.client

# Run the app
show_orders(db, engine, client)
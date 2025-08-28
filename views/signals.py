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
def get_signals_safe(db) -> List:
    """Safe wrapper for getting signals"""
    try:
        return db.get_signals()
    except Exception as e:
        logger.error(f"Error getting signals: {e}")
        return []

def format_price_safe(value: Optional[float]) -> str:
    """Format price safely"""
    return f"{value:.2f}" if value is not None and value > 0 else "N/A"

def format_currency_safe(value: Optional[float]) -> str:
    """Format currency safely"""
    return f"{value:.2f}" if value is not None else "0.00"

def generate_real_signals(symbols: List[str], interval: str, limit: int, client: BybitClient) -> List[dict]:
    """Generate trading signals based on simple price movement analysis"""
    try:
        signals = []
        for symbol in symbols:
            try:
                # Fetch recent price data using BybitClient
                kline_data = client.get_kline(symbol=symbol, interval=interval, limit=limit)
                if not kline_data or not isinstance(kline_data.get("result", {}).get("list"), list):
                    continue

                # Simple signal logic: if last candle close > open (bullish), generate BUY; else SELL
                last_candle = kline_data["result"]["list"][0]
                open_price = float(last_candle.get("open", 0))
                close_price = float(last_candle.get("close", 0))
                side = "BUY" if close_price > open_price else "SELL"
                signal_price = close_price
                signal_time = datetime.fromtimestamp(int(last_candle.get("timestamp")) / 1000)

                signals.append({
                    "symbol": symbol,
                    "side": side,
                    "price": signal_price,
                    "timestamp": signal_time,
                    "interval": interval,
                    "confidence": 0.75,  # Placeholder confidence score
                    "strategy": "price_movement"
                })
            except Exception as e:
                logger.error(f"Error generating signal for {symbol}: {e}")
        return signals
    except Exception as e:
        logger.error(f"Error generating signals: {e}")
        return []

def display_signals(signals, container, title: str):
    """Display signals in card form or table if empty"""
    try:
        if not signals:
            container.info(f"🌙 No {title.lower()} to display")
            return

        container.subheader(f"📡 {title} ({len(signals)})")
        for i, signal in enumerate(signals):
            with container.container(border=True):
                try:
                    symbol = getattr(signal, 'symbol', 'N/A')
                    side = getattr(signal, 'side', 'N/A')
                    price = getattr(signal, 'price', 0)
                    timestamp = getattr(signal, 'timestamp', None)
                    interval = getattr(signal, 'interval', 'N/A')
                    confidence = getattr(signal, 'confidence', 0)
                    strategy = getattr(signal, 'strategy', 'N/A')
                    time_str = timestamp.strftime("%Y-%m-%d %H:%M:%S") if timestamp and hasattr(timestamp, 'strftime') else "N/A"

                    st.markdown(f"**{symbol} | {side} | {interval}**")
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("Signal Price", f"${format_price_safe(price)}")
                    with col2:
                        st.metric("Timestamp", time_str)
                    with col3:
                        st.metric("Confidence", f"{confidence:.2%}")
                        st.markdown(f"**Strategy**: {strategy}")
                except Exception as e:
                    logger.error(f"Error displaying signal {i}: {e}")
                    container.error(f"Error displaying signal: {e}")
    except Exception as e:
        logger.error(f"Error in display_signals: {e}")
        container.error(f"🚨 Error displaying {title.lower()}: {e}")

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

    /* Info and error messages */
    .stAlert {
        border-radius: 8px;
        background: rgba(255,255,255,0.1);
        color: #ffffff;
    }

    /* Selectbox and multiselect */
    .stSelectbox, .stMultiSelect {
        background: #3b3b5e;
        border-radius: 8px;
        padding: 5px;
    }
    .stSelectbox > div > div, .stMultiSelect > div > div {
        color: #ffffff;
    }
    </style>
""", unsafe_allow_html=True)

def show_signals(db, engine, client):
    """Signal management with tabs, cards, and signal_generator.py logic"""
    st.title("📡 Trading Signals")

    if not db or not hasattr(db, 'get_signals'):
        st.error("🚨 Database connection not available")
        return

    try:
        # Define tabs
        all_tab, buy_tab, sell_tab = st.tabs(["📜 All Signals", "📈 Buy Signals", "📉 Sell Signals"])

        # Generate signals button
        with st.container(border=True):
            st.markdown("### Generate Signals")
            symbols = engine.get_usdt_symbols()[:10]  # Limit to 10 symbols for performance
            selected_symbols = st.multiselect("Select Symbols", symbols, default=symbols[:3], key="signal_symbols")
            interval = st.selectbox("Timeframe", ["15", "60", "240"], index=1, key="signal_interval")
            if st.button("🔍 Generate Signals", type="primary", key="generate_signals"):
                try:
                    if not selected_symbols:
                        st.error("🚨 Please select at least one symbol")
                        return
                    signals = generate_real_signals(selected_symbols, interval=interval, limit=10, client=client)
                    if signals and db and hasattr(db, 'add_signal'):
                        for signal in signals:
                            db.add_signal(signal)
                        st.success(f"✅ Generated {len(signals)} signals")
                        st.rerun()
                    else:
                        st.info("🌙 No signals generated")
                except Exception as e:
                    logger.error(f"Error generating signals: {e}")
                    st.error(f"🚨 Error generating signals: {e}")

        # Fetch signals
        signals = get_signals_safe(db)

        # All Signals tab
        with all_tab:
            display_signals(signals, st, "All Signals")

        # Buy Signals tab
        with buy_tab:
            buy_signals = [s for s in signals if getattr(s, 'side', '').upper() in ['BUY', 'LONG']]
            display_signals(buy_signals, st, "Buy Signals")

        # Sell Signals tab
        with sell_tab:
            sell_signals = [s for s in signals if getattr(s, 'side', '').upper() in ['SELL', 'SHORT']]
            display_signals(sell_signals, st, "Sell Signals")

        if st.button("🔄 Refresh Signals", key="refresh_signals"):
            st.rerun()

    except Exception as e:
        logger.error(f"Error in signals: {e}")
        st.error(f"🚨 Signals error: {str(e)}")

# Initialize components
db = db_manager
engine = TradingEngine()
client = engine.client

# Run the app
show_signals(db, engine, client)
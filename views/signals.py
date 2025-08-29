import streamlit as st
import logging
from datetime import datetime, timezone
from typing import List, Optional, Dict
from bybit_client import BybitClient
from engine import TradingEngine
from db import db_manager
import pandas as pd
import numpy as np
import requests
from signal_generator import analyze, get_usdt_symbols, get_candles, classify_trend, ema, sma, rsi, bollinger, atr, macd

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, filename="app.log", filemode="a", format="%(asctime)s - %(levelname)s - %(message)s", encoding="utf-8")

# Constants from utils.py
RISK_PCT = 0.01
ACCOUNT_BALANCE = 100.0
LEVERAGE = 10
ENTRY_BUFFER_PCT = 0.002
MIN_VOLUME = 1000
MIN_ATR_PCT = 0.001
RSI_ZONE = (20, 80)
INTERVALS = ['15', '60', '240']
MAX_SYMBOLS = 50
TP_PERCENT = 0.15
SL_PERCENT = 0.05

def calculate_indicators(data: pd.DataFrame) -> pd.DataFrame:
    """Calculate technical indicators for signal generation"""
    if data.empty or 'close' not in data.columns:
        logger.warning("Empty or invalid DataFrame for indicators")
        return data

    df = data.sort_values("timestamp").reset_index(drop=True)
    df['close'] = pd.to_numeric(df['close'], errors='coerce')
    df['high'] = pd.to_numeric(df['high'], errors='coerce')
    df['low'] = pd.to_numeric(df['low'], errors='coerce')
    df['volume'] = pd.to_numeric(df['volume'], errors='coerce')

    # RSI
    delta = df['close'].diff().astype(float)
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / (avg_loss + 1e-14)
    df['RSI'] = 100 - (100 / (1 + rs))
    df['RSI'] = df['RSI'].fillna(50)

    # EMAs and SMA
    df['EMA_9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['EMA_21'] = df['close'].ewm(span=21, adjust=False).mean()
    df['SMA_20'] = df['close'].rolling(window=20).mean()

    # MACD
    ema_12 = df['close'].ewm(span=12, adjust=False).mean()
    ema_26 = df['close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = ema_12 - ema_26
    df['MACD_signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['MACD_hist'] = df['MACD'] - df['MACD_signal']

    # Bollinger Bands
    sma = df['close'].rolling(window=20).mean()
    std = df['close'].rolling(window=20).std()
    df['BB_upper'] = sma + (2 * std)
    df['BB_lower'] = sma - (2 * std)

    return df

def format_price_safe(value: Union[float, str, None]) -> str:
    """Format value as price"""
    if value is None:
        logger.debug("None value passed to format_price_safe")
        return "0.0000"
    try:
        val = float(value)
        if val <= 0:
            return "0.0000"
        if val >= 1_000_000:
            return f"{val / 1_000_000:.4f}M"
        elif val >= 1_000:
            return f"{val / 1_000:.4f}K"
        else:
            return f"{val:.4f}"
    except (ValueError, TypeError) as e:
        logger.warning(f"Invalid value for price formatting: {value}, error: {e}")
        return "0.0000"

def classify_trend(ema9: float, ema21: float, sma20: float) -> str:
    """Classify market trend based on moving averages"""
    try:
        if ema9 > ema21 > sma20:
            return "Up"
        elif ema9 < ema21 < sma20:
            return "Down"
        elif ema9 > ema21:
            return "Bullish"
        elif ema9 < ema21:
            return "Bearish"
        return "Neutral"
    except (TypeError, ValueError) as e:
        logger.warning(f"Invalid values for trend classification: {e}")
        return "Neutral"

def score_signal(df: pd.DataFrame) -> float:
    """Score trading signal based on indicators"""
    required_cols = ['EMA_9', 'EMA_21', 'SMA_20', 'MACD', 'RSI', 'close', 'BB_upper', 'BB_lower']
    if any(col not in df.columns or df[col].isna().iloc[-1] for col in required_cols):
        return 0.0

    score = 0.0
    ema9 = df['EMA_9'].iloc[-1]
    ema21 = df['EMA_21'].iloc[-1]
    sma20 = df['SMA_20'].iloc[-1]
    macd = df['MACD'].iloc[-1]
    rsi = df['RSI'].iloc[-1]
    close = df['close'].iloc[-1]
    bb_upper = df['BB_upper'].iloc[-1]
    bb_lower = df['BB_lower'].iloc[-1]

    if ema9 > ema21 > sma20:
        score += 30
    elif ema9 > ema21:
        score += 20
    if macd > 0:
        score += 20
    if rsi < 30:
        score += 15
    elif rsi > 70:
        score += 15
    if close > bb_upper or close < bb_lower:
        score += 15

    return min(score, 100.0)

def get_signals_safe(db) -> List:
    """Safe wrapper for getting signals"""
    try:
        return db.get_signals(limit=50)
    except Exception as e:
        logger.error(f"Error getting signals: {e}")
        return []

def generate_real_signals(client: BybitClient, symbols: List[str], interval: str = "60", limit: int = 5) -> List[Dict]:
    """Generate trading signals using signal_generator.py logic"""
    signals = []
    for symbol in symbols[:limit]:
        try:
            signal = analyze(symbol, interval=interval)
            if signal:
                signal['created_at'] = datetime.now(timezone.utc).isoformat()
                signals.append(signal)
        except Exception as e:
            logger.error(f"Error generating signal for {symbol}: {e}")
    return signals

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

def show_signals(db, engine, client, trading_mode: str = "virtual"):
    """Signals page with tabs and card-based layout"""
    st.title("📡 Signals")

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
        .stSelectbox, .stNumberInput, .stMultiSelect {
            background: #3b3b5e;
            border-radius: 8px;
            padding: 5px;
        }
        </style>
    """, unsafe_allow_html=True)

    # Signal Generation section
    with st.expander("Generate New Signals"):
        with st.container(border=True):
            st.markdown("### Generate Signals")
            symbols = [s["symbol"] for s in client.get_symbols() if s["symbol"].endswith("USDT")]
            symbols = [s for s in symbols if s not in ["1000000BABYDOGEUSDT", "1000000CHEEMSUSDT", "1000000MOGUSDT"]]
            selected_symbols = st.multiselect("Select Symbols", symbols, default=symbols[:3], key="signal_symbols_select")
            interval = st.selectbox("Timeframe", ["15", "60", "240"], index=1, key="signal_interval_select")
            if st.button("🔍 Generate Signals", type="primary", key="generate_signals_button"):
                try:
                    if not selected_symbols:
                        st.error("🚨 Please select at least one symbol")
                        return
                    signals = generate_real_signals(client, selected_symbols, interval=interval, limit=10)
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

    # Initialize pagination state
    if "all_signals_page" not in st.session_state:
        st.session_state.all_signals_page = 1
    if "buy_signals_page" not in st.session_state:
        st.session_state.buy_signals_page = 1
    if "sell_signals_page" not in st.session_state:
        st.session_state.sell_signals_page = 1

    # Fetch signals
    signals = get_signals_safe(db)

    # Define tabs
    all_tab, buy_tab, sell_tab = st.tabs(["All Signals", "Buy Signals", "Sell Signals"])

    # All Signals tab
    with all_tab:
        display_signals(signals, st, "All Signals", st.session_state.all_signals_page, page_size=10)

    # Buy Signals tab
    with buy_tab:
        buy_signals = [s for s in signals if s.get("side", "").upper() in ["BUY", "LONG"]]
        display_signals(buy_signals, st, "Buy Signals", st.session_state.buy_signals_page, page_size=10)

    # Sell Signals tab
    with sell_tab:
        sell_signals = [s for s in signals if s.get("side", "").upper() in ["SELL", "SHORT"]]
        display_signals(sell_signals, st, "Sell Signals", st.session_state.sell_signals_page, page_size=10)

    if st.button("🔄 Refresh Signals", key="refresh_signals_button"):
        st.rerun()

# Initialize components
db = db_manager
engine = TradingEngine()
client = engine.client

# Run the app
show_signals(db, engine, client)
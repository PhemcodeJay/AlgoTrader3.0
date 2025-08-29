import streamlit as st
import logging
from datetime import datetime
from typing import List, Optional, Dict
from bybit_client import BybitClient
from engine import TradingEngine
from db import db_manager
import pandas as pd
import numpy as np
import requests

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Constants from utils.py
RISK_PCT = 0.01
ACCOUNT_BALANCE = 100.0
LEVERAGE = 10
ENTRY_BUFFER_PCT = 0.002
MIN_VOLUME = 1000
MIN_ATR_PCT = 0.001
RSI_ZONE = (30, 70)
INTERVALS = ['15', '60', '240']
MAX_SYMBOLS = 50
TP_PERCENT = 0.015
SL_PERCENT = 0.015

# Indicator functions from utils.py
def calculate_indicators(data: pd.DataFrame) -> pd.DataFrame:
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

def classify_trend(ema9: float, ema21: float, sma20: float) -> str:
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
    required_cols = ['EMA_9', 'EMA_21', 'SMA_20', 'MACD', 'RSI', 'close', 'BB_upper', 'BB_lower']
    if any(col not in df.columns or df[col].isna().iloc[-1] for col in required_cols):
        logger.debug("Missing or NaN columns for signal scoring")
        return 0.0

    try:
        ema_9 = float(df['EMA_9'].iloc[-1])
        ema_21 = float(df['EMA_21'].iloc[-1])
        sma_20 = float(df['SMA_20'].iloc[-1])
        macd = float(df['MACD'].iloc[-1])
        rsi = float(df['RSI'].iloc[-1])
        price = float(df['close'].iloc[-1])
        bb_up = float(df['BB_upper'].iloc[-1])
        bb_low = float(df['BB_lower'].iloc[-1])
    except (TypeError, ValueError) as e:
        logger.warning(f"Error converting indicator values: {e}")
        return 0.0

    trend = classify_trend(ema_9, ema_21, sma_20)
    bb_dir = "Up" if price > bb_up else "Down" if price < bb_low else "No"

    score = 0.0
    score += 0.3 if macd > 0 else 0
    score += 0.2 if rsi < RSI_ZONE[0] or rsi > RSI_ZONE[1] else 0
    score += 0.2 if bb_dir != "No" else 0
    score += 0.3 if trend in ["Up", "Bullish"] else 0.3 if trend in ["Down", "Bearish"] else 0.0

    return round(score * 100, 2)

# Utility functions
def get_signals_safe(db) -> List[dict]:
    """Safe wrapper for getting signals"""
    try:
        return [s.to_dict() for s in db.get_signals()]
    except Exception as e:
        logger.error(f"Error getting signals: {e}")
        return []

def format_price_safe(value: Optional[float]) -> str:
    """Format price safely"""
    return f"{value:.2f}" if value is not None and value > 0 else "N/A"

def format_currency_safe(value: Optional[float]) -> str:
    """Format currency safely"""
    return f"{value:.2f}" if value is not None else "0.00"

def get_candles(client: BybitClient, symbol: str, tf: str) -> List[Dict]:
    """Fetch candles using BybitClient or public API"""
    try:
        if client.is_connected():
            kline_data = client.get_kline(category="linear", symbol=symbol, interval=tf, limit=50)
        else:
            base_url = f"https://api{'-testnet' if client.testnet else ''}.bybit.com"
            url = f"{base_url}/v5/market/kline?category=linear&symbol={symbol}&interval={tf}&limit=50"
            kline_data = requests.get(url).json()

        if not kline_data or not isinstance(kline_data.get("result", {}).get("list"), list):
            return []
        list_data = kline_data["result"]["list"]
        candles = []
        for item in list_data:
            candles.append({
                "close": float(item.get("close", 0)),
                "high": float(item.get("high", 0)),
                "low": float(item.get("low", 0)),
                "volume": float(item.get("volume", 0)),
                "timestamp": int(item.get("start", 0))
            })
        return candles
    except Exception as e:
        logger.error(f"Error fetching candles for {symbol} on {tf}: {e}")
        return []

def generate_real_signals(client: BybitClient, symbols: List[str], interval: str = "60", limit: int = 5) -> List[Dict]:
    """Generate trading signals"""
    signals = []
    valid_symbols = [s for s in symbols if s not in ["1000000BABYDOGEUSDT", "1000000CHEEMSUSDT", "1000000MOGUSDT"]]

    for symbol in valid_symbols[:limit]:
        try:
            sides = []
            for tf in INTERVALS:
                candles = get_candles(client, symbol, tf)
                if not candles or len(candles) < 50:
                    logger.warning(f"Insufficient data for {symbol} on timeframe {tf}")
                    continue

                df = pd.DataFrame({
                    'close': [c['close'] for c in candles],
                    'high': [c['high'] for c in candles],
                    'low': [c['low'] for c in candles],
                    'volume': [c['volume'] for c in candles],
                    'timestamp': [c['timestamp'] for c in candles]
                })

                df = calculate_indicators(df)
                ema_9 = float(df['EMA_9'].iloc[-1])
                ema_21 = float(df['EMA_21'].iloc[-1])
                sma_20 = float(df['SMA_20'].iloc[-1])
                trend = classify_trend(ema_9, ema_21, sma_20)
                side = "LONG" if trend in ["Up", "Bullish"] else "SHORT" if trend in ["Down", "Bearish"] else "NEUTRAL"
                sides.append(side)

            if len(set(sides)) != 1 or sides[0] == "NEUTRAL":
                logger.debug(f"Skipping {symbol} due to inconsistent or neutral trend")
                continue

            candles = get_candles(client, symbol, interval)
            if not candles or len(candles) < 50:
                logger.warning(f"Insufficient data for {symbol} on timeframe {interval}")
                continue

            df = pd.DataFrame({
                'close': [c['close'] for c in candles],
                'high': [c['high'] for c in candles],
                'low': [c['low'] for c in candles],
                'volume': [c['volume'] for c in candles],
                'timestamp': [c['timestamp'] for c in candles],
                'symbol': symbol
            })

            df = calculate_indicators(df)
            score = score_signal(df)
            if score < 60:
                logger.debug(f"Skipping {symbol} due to low score: {score}")
                continue

            ema_9 = float(df['EMA_9'].iloc[-1])
            ema_21 = float(df['EMA_21'].iloc[-1])
            sma_20 = float(df['SMA_20'].iloc[-1])
            macd = float(df['MACD'].iloc[-1])
            rsi = float(df['RSI'].iloc[-1])
            bb_up = float(df['BB_upper'].iloc[-1])
            bb_low = float(df['BB_lower'].iloc[-1])
            price = float(df['close'].iloc[-1])

            if price <= 0:
                logger.warning(f"Invalid price for {symbol}: {price}")
                continue

            trend = classify_trend(ema_9, ema_21, sma_20)
            bb_dir = "Up" if price > bb_up else "Down" if price < bb_low else "No"

            opts = [sma_20, ema_9, ema_21]
            entry = min(opts, key=lambda x: abs(x - price))

            side = 'Buy' if sides[0] == 'LONG' else 'Sell'

            tp = round(entry * (1 + TP_PERCENT) if side == 'Buy' else entry * (1 - TP_PERCENT), 6)
            sl = round(entry * (1 - SL_PERCENT) if side == 'Buy' else entry * (1 + SL_PERCENT), 6)
            trail = round(entry * (1 - ENTRY_BUFFER_PCT) if side == 'Buy' else entry * (1 + ENTRY_BUFFER_PCT), 6)
            liq = round(entry * (1 - 1 / LEVERAGE) if side == 'Buy' else entry * (1 + 1 / LEVERAGE), 6)

            try:
                risk_amt = ACCOUNT_BALANCE * RISK_PCT
                sl_diff = abs(entry - sl)
                if sl_diff <= 0:
                    logger.warning(f"Invalid stop-loss difference for {symbol}: {sl_diff}")
                    continue
                qty = risk_amt / sl_diff
                margin_usdt = round((qty * entry) / LEVERAGE, 3)
                qty = round(qty, 3)
            except (ZeroDivisionError, ValueError) as e:
                logger.warning(f"Error calculating position size for {symbol}: {e}")
                margin_usdt = 1.0
                qty = 1.0

            signal = {
                "symbol": symbol,
                "interval": interval,
                "signal_type": side,
                "score": score,
                "indicators": {
                    "rsi": rsi,
                    "ema_9": ema_9,
                    "ema_21": ema_21,
                    "sma_20": sma_20,
                    "macd": macd,
                    "bb_upper": bb_up,
                    "bb_lower": bb_low
                },
                "strategy": "Multi-TF Signal",
                "side": "LONG" if side == 'Buy' else "SHORT",
                "entry": entry,
                "tp": tp,
                "sl": sl,
                "trail": trail,
                "liquidation": liq,
                "leverage": LEVERAGE,
                "margin_usdt": margin_usdt,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }

            logger.info(f"Generated signal for {symbol}: {side}, score={score}")
            signals.append(signal)

        except Exception as e:
            logger.error(f"Error generating signal for {symbol}: {e}")
            continue

    return signals[:5]

def display_signals(signals: List[dict], container, title: str, page: int, page_size: int):
    """Display signals in card form with pagination"""
    try:
        if not signals:
            container.info(f"🌙 No {title.lower()} to display")
            return

        # Calculate pagination
        total_signals = len(signals)
        total_pages = (total_signals + page_size - 1) // page_size
        start_idx = (page - 1) * page_size
        end_idx = min(start_idx + page_size, total_signals)
        paginated_signals = signals[start_idx:end_idx]

        container.subheader(f"📡 {title} ({total_signals})")

        # Display paginated signals
        for signal in paginated_signals:
            with container.container(border=True):
                try:
                    symbol = signal.get("symbol", "N/A")
                    side = signal.get("side", "N/A")
                    signal_type = signal.get("signal_type", "N/A")
                    interval = signal.get("interval", "N/A")
                    score = signal.get("score", 0)
                    strategy = signal.get("strategy", "N/A")
                    entry = signal.get("entry", 0)
                    tp = signal.get("tp", 0)
                    sl = signal.get("sl", 0)
                    trail = signal.get("trail", 0)
                    liquidation = signal.get("liquidation", 0)
                    leverage = signal.get("leverage", 0)
                    margin_usdt = signal.get("margin_usdt", 0)
                    created_at = signal.get("created_at", "N/A")
                    indicators = signal.get("indicators", {})
                    time_str = created_at if isinstance(created_at, str) else created_at.strftime("%Y-%m-%d %H:%M:%S") if created_at else "N/A"

                    st.markdown(f"**{symbol} | {side} | {interval}**")
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("Entry Price", f"${format_price_safe(entry)}")
                        st.metric("Take Profit", f"${format_price_safe(tp)}")
                        st.metric("Stop Loss", f"${format_price_safe(sl)}")
                    with col2:
                        st.metric("Trail Price", f"${format_price_safe(trail)}")
                        st.metric("Liquidation Price", f"${format_price_safe(liquidation)}")
                        st.metric("Timestamp", time_str)
                    with col3:
                        st.metric("Confidence", f"{score:.2f}%")
                        st.metric("Leverage", f"{leverage}x")
                        st.metric("Margin USDT", f"${format_currency_safe(margin_usdt)}")
                    st.markdown(f"**Strategy**: {strategy}")
                    with st.expander("Indicators"):
                        st.json(indicators)
                except Exception as e:
                    logger.error(f"Error displaying signal: {e}")
                    container.error(f"Error displaying signal: {e}")

        # Pagination controls
        if total_pages > 1:
            col1, col2, col3 = container.columns([1, 2, 1])
            with col2:
                page_key = f"{title.lower().replace(' ', '_')}_page_select"
                page = st.selectbox(
                    "Page",
                    options=list(range(1, total_pages + 1)),
                    index=page - 1,
                    key=page_key
                )
                st.session_state[f"{title.lower().replace(' ', '_')}_page"] = page

    except Exception as e:
        logger.error(f"Error in display_signals: {e}")
        container.error(f"🚨 Error displaying {title.lower()}: {e}")

# Custom CSS for modern, colorful styling
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
        transition: transform 0.2s ease;
    }
    .stContainer:hover {
        transform: translateY(-5px);
    }
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
    .stAlert {
        border-radius: 8px;
        background: rgba(255,255,255,0.1);
        color: #ffffff;
    }
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
    """Signal management with tabs, cards, and pagination"""
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

    except Exception as e:
        logger.error(f"Error in signals: {e}")
        st.error(f"🚨 Signals error: {str(e)}")

# Initialize components
db = db_manager
engine = TradingEngine()
client = engine.client

# Run the app
show_signals(db, engine, client)
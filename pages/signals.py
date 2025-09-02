import streamlit as st
import logging
from datetime import datetime, timezone
from typing import List, Dict, Sequence
from bybit_client import BybitClient
from engine import TradingEngine
from db import db_manager
import pandas as pd
import numpy as np
from utils import format_price_safe, normalize_signal, TP_PERCENT, SL_PERCENT

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, filename="app.log", filemode="a", format="%(asctime)s - %(levelname)s - %(message)s", encoding="utf-8")

# Constants
RISK_PCT = 0.01
ACCOUNT_BALANCE = 100.0
LEVERAGE = 10
ENTRY_BUFFER_PCT = 0.002
MIN_VOLUME = 1000
MIN_ATR_PCT = 0.001
RSI_ZONE = (20, 80)
INTERVALS = ['15', '60', '240']
MAX_SYMBOLS = 50
RSI_PERIOD = 14
ATR_PERIOD = 14

def calculate_rsi(prices: np.ndarray, period: int = RSI_PERIOD) -> float:
    """Calculate RSI from price series"""
    try:
        prices = np.array(prices)
        if len(prices) < period + 1:
            return 50.0  # Neutral fallback if insufficient data
        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        
        avg_gain = np.mean(gains[-period:]) if len(gains) >= period else 0
        avg_loss = np.mean(losses[-period:]) if len(losses) >= period else 0
        
        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0
        
        rs = avg_gain / avg_loss
        return float(100 - (100 / (1 + rs)))
    except Exception as e:
        logger.error(f"Error calculating RSI: {e}")
        return 50.0  # Neutral fallback

def calculate_atr(highs: List[float], lows: List[float], closes: List[float], period: int = ATR_PERIOD) -> float:
    """Calculate ATR from high, low, and close prices"""
    try:
        if len(closes) < period + 1:
            return 0.0  # Insufficient data
        trs = []
        for i in range(1, len(closes)):
            high_low = highs[i] - lows[i]
            high_prev_close = abs(highs[i] - closes[i-1])
            low_prev_close = abs(lows[i] - closes[i-1])
            tr = max(high_low, high_prev_close, low_prev_close)
            trs.append(tr)
        
        if len(trs) < period:
            return 0.0
        return float(np.mean(trs[-period:]))
    except Exception as e:
        logger.error(f"Error calculating ATR: {e}")
        return 0.0

def generate_signals(client: BybitClient, symbols: Sequence[str], interval: str = "60") -> List[Dict]:
    """Generate signals based on market data from BybitClient using kline data"""
    try:
        signals = []
        for symbol in symbols:
            # Fetch kline data (last 200 candles for sufficient history)
            kline_data = client.get_kline(symbol=symbol, interval=interval, limit=200)
            if not kline_data or len(kline_data) < RSI_PERIOD + 1:
                logger.warning(f"Insufficient kline data for {symbol}")
                continue

            # Extract prices (validate kline_data format)
            try:
                closes = [float(k['close']) for k in kline_data]
                highs = [float(k['high']) for k in kline_data]
                lows = [float(k['low']) for k in kline_data]
            except (KeyError, TypeError, ValueError) as e:
                logger.warning(f"Invalid kline data format for {symbol}: {e}")
                continue

            current_price = closes[-1] if closes else 0.0
            if current_price == 0.0:
                logger.warning(f"Invalid price data for {symbol}")
                continue

            # Calculate indicators
            rsi = calculate_rsi(np.array(closes))
            atr = calculate_atr(highs, lows, closes)
            atr_pct = atr / current_price if current_price > 0 else 0.0

            if atr_pct < MIN_ATR_PCT:
                logger.debug(f"ATR {atr_pct:.4f} below minimum for {symbol}")
                continue

            if rsi < RSI_ZONE[0]:
                side = "Buy"
                entry = current_price * (1 + ENTRY_BUFFER_PCT)
                sl = entry * (1 - SL_PERCENT)
                tp = entry * (1 + TP_PERCENT)
            elif rsi > RSI_ZONE[1]:
                side = "Sell"
                entry = current_price * (1 - ENTRY_BUFFER_PCT)
                sl = entry * (1 + SL_PERCENT)
                tp = entry * (1 - TP_PERCENT)
            else:
                continue

            qty = (ACCOUNT_BALANCE * RISK_PCT * LEVERAGE) / entry if entry > 0 else 0
            signals.append({
                "symbol": symbol,
                "side": side,
                "entry": entry,
                "qty": qty,
                "sl": sl,
                "tp": tp,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "score": max(50.0, 60.0 + (abs(rsi - 50) * 0.5))  # Dynamic score based on RSI strength
            })
        return signals
    except Exception as e:
        logger.error(f"Error generating signals: {e}")
        return []

def display_signals(signals: List[Dict], container, title: str, page: int = 1, page_size: int = 10):
    """Display signals in a paginated table"""
    if not signals:
        container.info(f"🌙 No {title.lower()} to display")
        return
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    signals_data = []
    for signal in signals[start_idx:end_idx]:
        signals_data.append({
            "Symbol": signal.get("symbol", "N/A"),
            "Side": signal.get("side", "N/A"),
            "Entry": f"${format_price_safe(signal.get('entry'))}",
            "TP": f"${format_price_safe(signal.get('tp'))}",
            "SL": f"${format_price_safe(signal.get('sl'))}",
            "Qty": f"{signal.get('qty', 0):.4f}",
            "Score": f"{signal.get('score', 0):.1f}%"
        })
    if signals_data:
        df = pd.DataFrame(signals_data)
        container.dataframe(df, use_container_width=True)
    else:
        container.info(f"🌙 No {title.lower()} to display")

def show_signals(db, engine: TradingEngine, client: BybitClient, trading_mode: str):
    """Display the signals page with signal generation and viewing tabs"""
    st.title("📡 Signals")

    PAGE_SIZE = 10  # Number of signals per page

    # Ensure session state keys exist
    for key in ["all_signals_page", "buy_signals_page", "sell_signals_page"]:
        if key not in st.session_state:
            st.session_state[key] = 1

    generator_tab, all_tab, buy_tab, sell_tab = st.tabs(
        ["⚙️ Generator", "All Signals", "Buy Signals", "Sell Signals"]
    )

    with generator_tab:
        st.subheader("Generate Signals")
        # Get available symbols and validate defaults
        available_symbols = client.get_symbols()
        default_symbols = ["BTCUSDT", "ETHUSDT"]
        valid_defaults = [s for s in default_symbols if s in available_symbols]
        if not available_symbols:
            st.warning("⚠️ No symbols available from Bybit. Check API connection or credentials.")
            symbols = []
        else:
            symbols = st.multiselect(
                "Select Symbols",
                available_symbols,
                default=valid_defaults if valid_defaults else [available_symbols[0]] if available_symbols else [],
                key="signals_symbols"
            )
        interval = st.selectbox("Interval", INTERVALS, index=1, key="signals_interval")
        if st.button("Generate Signals", key="generate_signals"):
            with st.spinner("Generating..."):
                if not symbols:
                    st.error("🚨 Please select at least one symbol")
                else:
                    # Ensure symbols is a list of strings
                    symbol_names = [str(s) for s in symbols]
                    signals = generate_signals(client, symbol_names, interval)
                    if signals:
                        for signal in signals:
                            db.add_signal(signal)
                        st.success(f"✅ Generated {len(signals)} signals")
                    else:
                        st.warning("⚠️ No signals generated")

    # Fetch signals from DB safely
    try:
        db_signals = db.get_signals() or []
    except Exception as e:
        st.error(f"Error fetching signals: {e}")
        db_signals = []

    # Pagination helper
    def pagination_controls(label: str, page_key: str, items: list):
        total_pages = max(1, (len(items) + PAGE_SIZE - 1) // PAGE_SIZE)
        col1, col2, col3 = st.columns([1, 2, 1])
        with col1:
            if st.button("⬅️ Prev", key=f"{label}_prev"):
                if st.session_state[page_key] > 1:
                    st.session_state[page_key] -= 1
        with col2:
            st.markdown(f"<p style='text-align:center;'>Page {st.session_state[page_key]} of {total_pages}</p>", unsafe_allow_html=True)
        with col3:
            if st.button("Next ➡️", key=f"{label}_next"):
                if st.session_state[page_key] < total_pages:
                    st.session_state[page_key] += 1

    # All signals
    with all_tab:
        display_signals(db_signals, st, "All Signals", st.session_state.all_signals_page, PAGE_SIZE)
        pagination_controls("all", "all_signals_page", db_signals)

    # Buy signals
    with buy_tab:
        buy_signals = [s for s in db_signals if s.get("side") == "Buy"]
        display_signals(buy_signals, st, "Buy Signals", st.session_state.buy_signals_page, PAGE_SIZE)
        pagination_controls("buy", "buy_signals_page", buy_signals)

    # Sell signals
    with sell_tab:
        sell_signals = [s for s in db_signals if s.get("side") == "Sell"]
        display_signals(sell_signals, st, "Sell Signals", st.session_state.sell_signals_page, PAGE_SIZE)
        pagination_controls("sell", "sell_signals_page", sell_signals)

    if st.button("🔄 Refresh Signals", key="refresh_signals"):
        st.rerun()

# Remove module-level execution to avoid running outside app.py navigation
# The following lines are commented out as they should be handled by app.py
db = db_manager
client = BybitClient()
engine = TradingEngine()
trading_mode = st.session_state.get("trading_mode", "virtual")
show_signals(db, engine, client, trading_mode)
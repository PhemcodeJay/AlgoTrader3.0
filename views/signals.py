import streamlit as st
import logging
from datetime import datetime, timezone, timedelta 
from typing import List, Optional, Dict, Union
from bybit_client import BybitClient
from engine import TradingEngine
from db import db_manager
import pandas as pd
import numpy as np
import requests
import os
from signal_generator import get_usdt_symbols, SignalPDF
from utils import get_candles, ema, sma, rsi, bollinger, atr, macd, classify_trend, format_price_safe, calculate_indicators

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
TP_PERCENT = 0.015  # Aligned with signal_generator.py
SL_PERCENT = 0.015  # Aligned with signal_generator.py

def analyze(symbol: str, interval: str = "60") -> Optional[Dict]:
    """Analyze a symbol and generate a trading signal (from signal_generator.py)"""
    try:
        data = {}
        for tf in INTERVALS:
            candles = get_candles(symbol, tf)
            if len(candles) < 30:
                logger.warning(f"Insufficient candles for {symbol} on timeframe {tf}")
                return None
            closes = [c['close'] for c in candles]
            highs = [c['high'] for c in candles]
            lows = [c['low'] for c in candles]
            vols = [c['volume'] for c in candles]
            data[tf] = {
                'close': closes[-1],
                'ema9': ema(closes, 9),
                'ema21': ema(closes, 21),
                'sma20': sma(closes, 20),
                'rsi': rsi(closes),
                'macd': macd(closes),
                'bb_up': bollinger(closes)[0],
                'bb_mid': bollinger(closes)[1],
                'bb_low': bollinger(closes)[2],
                'atr': atr(highs, lows, closes),
                'volume': vols[-1]
            }

        tf60 = data['60']
        if (tf60['volume'] < MIN_VOLUME or tf60['atr'] / tf60['close'] < MIN_ATR_PCT or
            not (RSI_ZONE[0] < tf60['rsi'] < RSI_ZONE[1])):
            logger.debug(f"Skipping {symbol} due to low volume, ATR, or RSI")
            return None

        sides = []
        for d in data.values():
            if d['close'] > d['bb_up']: sides.append('LONG')
            elif d['close'] < d['bb_low']: sides.append('SHORT')
            elif d['close'] > d['ema21']: sides.append('LONG')
            elif d['close'] < d['ema21']: sides.append('SHORT')

        if len(set(sides)) != 1:
            logger.debug(f"Skipping {symbol} due to inconsistent trend across timeframes")
            return None

        tf = tf60
        price = tf['close']
        trend = classify_trend(tf['ema9'], tf['ema21'], tf['sma20'])
        bb_dir = "Up" if price > tf['bb_up'] else "Down" if price < tf['bb_low'] else "No"
        opts = [tf['sma20'], tf['ema9'], tf['ema21']]
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
                return None
            qty = risk_amt / sl_diff
            margin_usdt = round((qty * entry) / LEVERAGE, 3)
            qty = round(qty, 3)
        except (ZeroDivisionError, ValueError) as e:
            logger.warning(f"Error calculating position size for {symbol}: {e}")
            margin_usdt = 1.0
            qty = 1.0

        score = 0
        score += 0.3 if tf['macd'] and tf['macd'] > 0 else 0
        score += 0.2 if tf['rsi'] < 30 or tf['rsi'] > 70 else 0
        score += 0.2 if bb_dir != "No" else 0
        score += 0.3 if trend in ["Up", "Bullish"] else 0.1

        return {
            'symbol': symbol,
            'side': side,
            'type': trend,
            'score': round(score * 100, 1),
            'entry_price': round(entry, 6),
            'tp': tp,
            'sl': sl,
            'trail': trail,
            'margin_usdt': margin_usdt,
            'qty': qty,
            'market': price,
            'liquidation': liq,
            'bb_direction': bb_dir,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'timeframe': interval,
            'strategy': "Multi-TF Signal",
            'virtual': True
        }
    except Exception as e:
        logger.error(f"Error analyzing {symbol}: {e}")
        return None

def generate_real_signals(client: BybitClient, symbols: List[str], interval: str = "60", limit: int = 5) -> List[Dict]:
    """Generate trading signals and create a PDF"""
    signals = []
    try:
        for symbol in symbols[:limit]:
            signal = analyze(symbol, interval=interval)
            if signal:
                signals.append(signal)
        signals.sort(key=lambda x: x['score'], reverse=True)
        signals = signals[:5]  # Limit to top 5 signals

        if signals:
            # Generate PDF
            pdf = SignalPDF()
            pdf.add_page()
            pdf.add_signals(signals)
            fname = f"signals_{datetime.now(timezone(timedelta(hours=3))).strftime('%H%M')}.pdf"
            pdf.output(fname)
            logger.info(f"PDF saved: {fname}")
        else:
            logger.info("No valid signals generated")
        return signals, fname if signals else None
    except Exception as e:
        logger.error(f"Error generating signals: {e}")
        return [], None

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
            symbols = get_usdt_symbols()  # Use signal_generator.py's function
            selected_symbols = st.multiselect("Select Symbols", symbols, default=symbols[:3], key="signal_symbols_select")
            interval = st.selectbox("Timeframe", ["15", "60", "240"], index=1, key="signal_interval_select")
            if st.button("🔍 Generate Signals", type="primary", key="generate_signals_button"):
                try:
                    if not selected_symbols:
                        st.error("🚨 Please select at least one symbol")
                        return
                    signals, pdf_filename = generate_real_signals(client, selected_symbols, interval=interval, limit=10)
                    if signals and db and hasattr(db, 'add_signal'):
                        for signal in signals:
                            db.add_signal(signal)
                        st.success(f"✅ Generated {len(signals)} signals")
                        with st.container(border=True):
                            st.markdown("### Generated Signals")
                            display_signals(signals, st, "Generated Signals")
                        if pdf_filename and os.path.exists(pdf_filename):
                            with open(pdf_filename, "rb") as f:
                                st.download_button(
                                    label="📄 Download Signals PDF",
                                    data=f,
                                    file_name=pdf_filename,
                                    mime="application/pdf",
                                    key="download_signals_pdf"
                                )
                        else:
                            st.warning("⚠️ No PDF generated")
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
    def get_signals_safe(db):
        """Safely fetch signals from the database."""
        try:
            if db and hasattr(db, "get_signals"):
                return db.get_signals()
            else:
                return []
        except Exception as e:
            logger.error(f"Error fetching signals: {e}")
            return []
    
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
import streamlit as st
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Union
from bybit_client import BybitClient
from engine import TradingEngine
from db import db_manager
import pandas as pd
import numpy as np
import subprocess
import json
import os
import sys
from utils import format_price_safe

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
TP_PERCENT = 0.015
SL_PERCENT = 0.015

def normalize_signal(signal: Union[Dict, object]) -> Dict:
    """Convert a Signal object or dictionary to a consistent dictionary format."""
    try:
        if isinstance(signal, dict):
            return {
                "symbol": signal.get("Symbol", "N/A"),  # Match signal_generator.py keys
                "side": signal.get("Side", "N/A"),
                "entry_price": signal.get("Entry", 0),
                "tp": signal.get("TP", 0),
                "sl": signal.get("SL", 0),
                "score": signal.get("Score", 0),
                "strategy": signal.get("Type", "N/A"),
                "created_at": signal.get("Time", "N/A")
            }
        else:
            # Assume Signal object with attributes
            return {
                "symbol": getattr(signal, "symbol", "N/A"),
                "side": getattr(signal, "side", "N/A"),
                "entry_price": getattr(signal, "entry_price", 0),
                "tp": getattr(signal, "tp", 0),
                "sl": getattr(signal, "sl", 0),
                "score": getattr(signal, "score", 0),
                "strategy": getattr(signal, "strategy", "N/A"),
                "created_at": getattr(signal, "created_at", "N/A")
            }
    except Exception as e:
        logger.error(f"Error normalizing signal: {e}")
        return {
            "symbol": "N/A",
            "side": "N/A",
            "entry_price": 0,
            "tp": 0,
            "sl": 0,
            "score": 0,
            "strategy": "N/A",
            "created_at": "N/A"
        }

def generate_real_signals(symbols: List[str], interval: str = "60") -> List[Dict]:
    """Run signal_generator.py and read the generated signals and PDF."""
    try:
        # Prepare command to run signal_generator.py
        cmd = [sys.executable, "signal_generator.py", "--symbols", ",".join(symbols), "--interval", interval]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        
        if result.returncode != 0:
            logger.error(f"signal_generator.py failed: {result.stderr}")
            st.error(f"🚨 Error running signal generator: {result.stderr}")
            return [], None

        # Read signals from JSON
        signals = []
        json_file = "signals.json"
        if os.path.exists(json_file):
            with open(json_file, "r") as f:
                signals = json.load(f)
        
        # Find the latest PDF
        pdf_files = [f for f in os.listdir() if f.startswith("signals_") and f.endswith(".pdf")]
        pdf_filename = max(pdf_files, key=os.path.getmtime, default=None) if pdf_files else None
        
        return signals, pdf_filename
    except subprocess.TimeoutExpired:
        logger.error("signal_generator.py timed out")
        st.error("🚨 Signal generation timed out")
        return [], None
    except Exception as e:
        logger.error(f"Error generating signals: {e}")
        st.error(f"🚨 Error generating signals: {e}")
        return [], None

def display_signals(signals: List, container, title: str, page: int = 1, page_size: int = 5):
    """Reusable function to display signals"""
    try:
        if not signals:
            container.info("🌙 No signals to display")
            return

        signals_data = []
        for signal in signals:
            normalized = normalize_signal(signal)
            signals_data.append({
                "Symbol": normalized["symbol"],
                "Side": normalized["side"],
                "Entry": f"${format_price_safe(normalized['entry_price'])}",
                "TP": f"${format_price_safe(normalized['tp'])}",
                "SL": f"${format_price_safe(normalized['sl'])}",
                "Score": f"{normalized['score']:.1f}%",
                "Strategy": normalized["strategy"],
                "Time": normalized["created_at"]
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

def get_signals_safe(db) -> List:
    """Safe wrapper for getting signals"""
    try:
        return db.get_signals(limit=50)
    except Exception as e:
        logger.error(f"Error getting signals: {e}")
        return []

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
            symbols = client.get_symbols()  # Use client for symbols to ensure consistency
            symbols = [s["symbol"] for s in symbols if s["symbol"].endswith("USDT")]
            symbols = [s for s in symbols if s not in ["1000000BABYDOGEUSDT", "1000000CHEEMSUSDT", "1000000MOGUSDT"]]
            selected_symbols = st.multiselect("Select Symbols", symbols, default=symbols[:3], key="signal_symbols_select")
            interval = st.selectbox("Timeframe", ["15", "60", "240"], index=1, key="signal_interval_select")
            if st.button("🔍 Generate Signals", type="primary", key="generate_signals_button"):
                try:
                    if not selected_symbols:
                        st.error("🚨 Please select at least one symbol")
                        return
                    signals, pdf_filename = generate_real_signals(selected_symbols, interval=interval)
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
    signals = get_signals_safe(db)

    # Define tabs
    all_tab, buy_tab, sell_tab = st.tabs(["All Signals", "Buy Signals", "Sell Signals"])

    # All Signals tab
    with all_tab:
        display_signals(signals, st, "All Signals", st.session_state.all_signals_page, page_size=10)

    # Buy Signals tab
    with buy_tab:
        buy_signals = [s for s in signals if getattr(s, "side", "").upper() in ["BUY", "LONG"]]
        display_signals(buy_signals, st, "Buy Signals", st.session_state.buy_signals_page, page_size=10)

    # Sell Signals tab
    with sell_tab:
        sell_signals = [s for s in signals if getattr(s, "side", "").upper() in ["SELL", "SHORT"]]
        display_signals(sell_signals, st, "Sell Signals", st.session_state.sell_signals_page, page_size=10)

    if st.button("🔄 Refresh Signals", key="refresh_signals_button"):
        st.rerun()

# Initialize components
db = db_manager
engine = TradingEngine()
client = engine.client

# Run the app
show_signals(db, engine, client)
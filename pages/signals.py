import streamlit as st
import logging
from datetime import datetime, timezone
from typing import List, Dict, Sequence
from bybit_client import BybitClient
from engine import TradingEngine
from db import db_manager
import pandas as pd
from signal_generator import generate_signals, generate_pdf_bytes, format_signal_block, send_telegram, send_discord  # Import from signal_generator.py

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    filename="app.log",
    filemode="a",
    format="%(asctime)s - %(levelname)s - %(message)s",
    encoding="utf-8"
)

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
            "Symbol": signal.get("Symbol", "N/A"),
            "Side": signal.get("Side", "N/A"),
            "Entry": f"${signal.get('Entry', 0):.2f}",
            "TP": f"${signal.get('TP', 0):.2f}",
            "SL": f"${signal.get('SL', 0):.2f}",
            "Qty": f"{signal.get('Margin', 0):.4f}",
            "Score": f"{signal.get('Score', 0):.1f}%"
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
        interval = st.selectbox("Interval", ['15', '60', '240'], index=1, key="signals_interval")
        if st.button("Generate Signals", key="generate_signals"):
            with st.spinner("Generating..."):
                if not symbols:
                    st.error("🚨 Please select at least one symbol")
                else:
                    # Call generate_signals from signal_generator.py
                    signals = generate_signals(symbols, trading_mode)
                    if signals:
                        for signal in signals:
                            # Normalize signal for database compatibility
                            db_signal = {
                                "symbol": signal["Symbol"],
                                "side": signal["Side"],
                                "entry": signal["Entry"],
                                "qty": signal["Margin"],
                                "sl": signal["SL"],
                                "tp": signal["TP"],
                                "timestamp": signal["Time"],
                                "score": signal["Score"]
                            }
                            db.add_signal(db_signal)
                        st.success(f"✅ Generated {len(signals)} signals")
                        # Store signals in session state for export
                        st.session_state.generated_signals = signals
                    else:
                        st.warning("⚠️ No signals generated")

        # Export options
        if "generated_signals" in st.session_state and st.session_state.generated_signals:
            signals = st.session_state.generated_signals
            top5 = signals[:5]
            agg_msg = "\n".join([format_signal_block(s) for s in top5])
            pdf_bytes = generate_pdf_bytes(signals)
            if pdf_bytes:
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.download_button(
                        label="📥 Download PDF",
                        data=pdf_bytes,
                        file_name=f"signals_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                        mime="application/pdf",
                        key="download_signals_pdf"
                    )
                with col2:
                    if st.button("📤 Send to Telegram", key="send_telegram"):
                        if send_telegram("📊 *Top 5 Bybit Signals*\n\n" + agg_msg):
                            st.success("✅ Sent to Telegram")
                        else:
                            st.error("🚨 Failed to send to Telegram")
                with col3:
                    if st.button("📤 Send to Discord", key="send_discord"):
                        if send_discord("📊 **Top 5 Bybit Signals**\n\n" + agg_msg):
                            st.success("✅ Sent to Discord")
                        else:
                            st.error("🚨 Failed to send to Discord")

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
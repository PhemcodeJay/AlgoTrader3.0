import streamlit as st
import os
import logging
from datetime import datetime, timezone
import threading
import time
from typing import Dict, Optional, List
from bybit_client import BybitClient
from engine import TradingEngine
from db import db_manager
from ml import MLFilter
import pandas as pd
from utils import format_currency_safe, display_trades_table, get_trades_safe

# Configure logging
logging.basicConfig(level=logging.INFO, filename="app.log", filemode="a", format="%(asctime)s - %(levelname)s - %(message)s", encoding="utf-8")
logger = logging.getLogger(__name__)

st.session_state.trading_mode = st.radio(
    "Select Trading Mode:",
    options=["virtual", "real"],
    index=0  # default = virtual
)


class AutomatedTrader:
    def __init__(self, engine):
        self.is_running = False
        self.thread = None
        self.start_time = None
        self.engine = engine
        self.ml_filter = MLFilter() if os.getenv("ML_ENABLED", "true").lower() == "true" else None
        self.stats = {
            "signals_generated": 0,
            "trades_executed": 0,
            "success_rate": 0.0,
            "uptime": "0:00:00"
        }

    def start(self) -> bool:
        if self.is_running:
            logger.warning("Automation is already running")
            return False
        try:
            self.is_running = True
            self.start_time = datetime.now(timezone.utc)
            self.thread = threading.Thread(target=self._trading_loop, args=(st.session_state.trading_mode,), daemon=True)
            self.thread.start()
            logger.info("Automated trading system started")
            return True
        except Exception as e:
            logger.error(f"Failed to start automation: {e}")
            self.is_running = False
            return False

    def stop(self):
        if not self.is_running:
            logger.warning("Automation is not running")
            return
        self.is_running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5)
        logger.info("Automated trading system stopped")

    def _trading_loop(self, trading_mode: str, db_manager, client, container):
        """
        Main trading loop:
        - Generates signals
        - Executes trades
        - Saves to DB
        - Updates Streamlit trades table
        """
        logger.info("Trading loop started")
        while self.is_running:
            try:
                # === Run signals ===
                signals = self.engine.run_once(trading_mode=trading_mode)
                if self.ml_filter:
                    signals = [self.ml_filter.enhance_signal(signal, trading_mode) for signal in signals]

                self.stats["signals_generated"] += len(signals)

                # === Execute trades ===
                for signal in signals:
                    trade = self.engine.execute_signal(signal, trading_mode)
                    if trade:
                        self.stats["trades_executed"] += 1
                        try:
                            db_manager.add_trade(trade)
                        except Exception as e:
                            logger.error(f"Error saving trade to database: {e}")

                # === Refresh trades in UI ===
                try:
                    trades = get_trades_safe(db_manager, limit=10)
                    display_trades_table(trades, container, client, max_trades=5)
                except Exception as e:
                    logger.error(f"Error refreshing trades table: {e}")

                # === Update stats ===
                trade_stats = self.engine.get_trade_statistics()
                self.stats["success_rate"] = trade_stats.get("win_rate", 0.0)
                self._update_uptime()

                # Wait until next cycle
                time.sleep(60)

            except Exception as e:
                logger.error(f"Error in trading loop: {e}")
                time.sleep(30)


    def _update_uptime(self):
        if self.start_time:
            uptime = datetime.now(timezone.utc) - self.start_time
            self.stats["uptime"] = str(uptime).split(".")[0]

    def get_status(self) -> Dict:
        return {
            "is_running": self.is_running,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "stats": self.stats.copy()
        }

    def reset_stats(self):
        self.stats = {
            "signals_generated": 0,
            "trades_executed": 0,
            "success_rate": 0.0,
            "uptime": "0:00:00"
        }
        logger.info("Statistics reset")

def show_automation(automated_trader, db, engine, client, trading_mode: str):
    st.title("🤖 Automation")
    st.markdown("---")
    automation_tab, logs_tab, stats_tab = st.tabs(["⚙️ Automation", "📜 Logs", "📊 Statistics"])

    with automation_tab:
        with st.container(border=True):
            st.markdown("### Automation Controls")
            automation_enabled = automated_trader.get_status()["is_running"]
            col1, col2 = st.columns(2)
            with col1:
                leverage = st.number_input("Leverage", value=10, min_value=1, max_value=100, key="auto_leverage")
            with col2:
                strategy = st.selectbox("Strategy", ["Trend", "Mean", "Breakout"], key="auto_strategy")
            col3, col4 = st.columns(2)
            with col3:
                if st.button("🚀 Start Automation", type="primary", key="start_automation", disabled=automation_enabled):
                    automated_trader.start()
                    st.success("✅ Automation started successfully")
                    st.rerun()
            with col4:
                if st.button("⏹️ Stop Automation", key="stop_automation", disabled=not automation_enabled):
                    automated_trader.stop()
                    st.success("✅ Automation stopped successfully")
                    st.rerun()
            if automation_enabled:
                st.success(f"✅ Automation is running (Leverage: {leverage}x, Strategy: {strategy})")
            else:
                st.warning("⏸️ Automation is stopped")
            if st.button("🔄 Refresh Automation", key="refresh_automation"):
                st.rerun()
            if st.button("🔄 Reset Statistics", key="reset_stats"):
                automated_trader.reset_stats()
                st.success("✅ Statistics reset successfully")
                st.rerun()

    with logs_tab:
        with st.container(border=True):
            st.markdown("### Automation Logs")
            try:
                log_file = "app.log"
                if os.path.exists(log_file) and os.access(log_file, os.R_OK):
                    with open(log_file, "r", encoding="utf-8") as f:
                        lines = f.readlines()
                    lines = lines[-200:]
                    if lines:
                        log_text = "".join(lines)
                        st.text_area("Logs", log_text, height=400, key="automation_logs")
                        st.download_button(
                            label="📥 Download Logs",
                            data=log_text,
                            file_name=f"automation_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                            mime="text/plain",
                            key="download_automation_logs"
                        )
                    else:
                        st.info("🌙 No logs found for automation yet")
                else:
                    st.warning("⚠️ No automation log file found or not readable")
            except Exception as e:
                logger.error(f"Error displaying automation logs: {e}")
                st.error(f"🚨 Error displaying automation logs: {e}")

    with stats_tab:
        with st.container(border=True):
            st.markdown("### 📊 Automation Statistics")
            status = automated_trader.get_status()
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Signals Generated", status["stats"]["signals_generated"])
                st.metric("Trades Executed", status["stats"]["trades_executed"])
            with col2:
                st.metric("Success Rate", f"{status['stats']['success_rate']:.2%}")
                st.metric("Uptime", status["stats"]["uptime"])

# Initialize components
db = db_manager
engine = TradingEngine()
client = engine.client
automated_trader = AutomatedTrader(engine)

# Run the app
show_automation(automated_trader, db, engine, client, st.session_state.trading_mode)
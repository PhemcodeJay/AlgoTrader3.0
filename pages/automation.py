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
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    filename="app.log",
    filemode="a",
    format="%(asctime)s - %(levelname)s - %(message)s",
    encoding="utf-8"
)
logger = logging.getLogger(__name__)

# Initialize session state for trading mode
if "trading_mode" not in st.session_state:
    st.session_state.trading_mode = "virtual"

class AutomatedTrader:
    def __init__(self, engine, client: BybitClient, risk_per_trade: float = 0.01):
        self.is_running = False
        self.threads = []
        self.start_time = None
        self.engine = engine
        self.client = client
        self.ml_filter = MLFilter() if os.getenv("ML_ENABLED", "true").lower() == "true" else None
        self.risk_per_trade = risk_per_trade
        self.min_sl_points = float(os.getenv("MIN_SL_POINTS", "10"))
        self.max_sl_points = float(os.getenv("MAX_SL_POINTS", "100"))
        self.stats_lock = threading.Lock()
        self.stats = {
            "signals_generated": 0,
            "trades_executed": 0,
            "successful_trades": 0,
            "failed_trades": 0,
            "success_rate": 0.0,
            "uptime": "0:00:00"
        }
        self.container = None  # To hold Streamlit container for trade updates

    def start(self, container) -> bool:
        if self.is_running:
            logger.warning("Automation is already running")
            return False
        try:
            self.is_running = True
            self.start_time = datetime.now(timezone.utc)
            self.container = container
            symbols = os.getenv("SYMBOLS", "BTCUSDT,ETHUSDT,XRPUSDT").split(",")
            interval = os.getenv("INTERVAL", "60")
            strategy = os.getenv("STRATEGY", "MACD")
            for symbol in symbols:
                thread = threading.Thread(
                    target=self._trading_loop,
                    args=(symbol, interval, strategy, st.session_state.trading_mode, db_manager, self.client, container),
                    daemon=True
                )
                self.threads.append(thread)
                thread.start()
                logger.info(f"Started trading thread for {symbol}")
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
        for thread in self.threads:
            if thread.is_alive():
                thread.join(timeout=5)
        self.threads = []
        self.container = None
        logger.info("Automated trading system stopped")

    def _calculate_position_size(self, entry_price: float, stop_loss: float, account_balance: float) -> float:
        if not entry_price or not stop_loss:
            return 0.0
        risk_amount = account_balance * self.risk_per_trade
        stop_distance = abs(entry_price - stop_loss)
        return risk_amount / stop_distance if stop_distance > 0 else 0.0

    def _validate_sl_tp(self, signal: Dict) -> bool:
        try:
            entry = float(signal.get("entry", 0))
            sl = float(signal.get("sl", 0))
            tp = float(signal.get("tp", 0))
            
            if entry <= 0 or sl <= 0 or tp <= 0:
                logger.error(f"Invalid signal values: entry={entry}, sl={sl}, tp={tp}")
                return False

            sl_distance = abs(entry - sl)
            if sl_distance < self.min_sl_points or sl_distance > self.max_sl_points:
                logger.error(f"Stop loss distance {sl_distance} outside allowed range")
                return False

            if signal["side"].lower() == "buy":
                if not (tp > entry > sl):
                    logger.error("Invalid buy signal: TP must be > entry > SL")
                    return False
            else:  # sell
                if not (tp < entry < sl):
                    logger.error("Invalid sell signal: TP must be < entry < SL")
                    return False

            return True
        except (ValueError, TypeError) as e:
            logger.error(f"Error validating SL/TP: {e}")
            return False

    def _trading_loop(self, symbol: str, interval: str, strategy: str, trading_mode: str, db_manager, client, container):
        logger.info(f"Trading loop started for {symbol} on {interval} with {strategy}")
        while self.is_running:
            try:
                signals = self.engine.run_once(
                    trading_mode=trading_mode,
                    symbol=symbol,
                    interval=interval,
                    strategy=strategy
                )
                
                with self.stats_lock:
                    self.stats["signals_generated"] += len(signals)

                account_balance = self.client.get_wallet_balance().get("available", 0.0)

                for signal in signals:
                    if self.ml_filter:
                        try:
                            signal = self.ml_filter.enhance_signal(signal, trading_mode)
                            if signal.get("score", 0.0) < 60.0:
                                logger.info(f"Signal filtered out by ML for {symbol}: score={signal.get('score')}")
                                with self.stats_lock:
                                    self.stats["failed_trades"] += 1
                                continue
                        except Exception as e:
                            logger.error(f"MLFilter enhancement error for {symbol}: {e}")
                            with self.stats_lock:
                                self.stats["failed_trades"] += 1
                            continue

                    if not self._validate_sl_tp(signal):
                        with self.stats_lock:
                            self.stats["failed_trades"] += 1
                        continue

                    price = float(signal.get("entry", 0))
                    if price <= 0:
                        logger.error(f"Invalid price for signal: {signal}")
                        with self.stats_lock:
                            self.stats["failed_trades"] += 1
                        continue

                    qty = self._calculate_position_size(
                        entry_price=price,
                        stop_loss=signal["sl"],
                        account_balance=account_balance
                    )

                    if qty <= 0:
                        logger.error(f"Invalid position size for signal: {signal}")
                        with self.stats_lock:
                            self.stats["failed_trades"] += 1
                        continue

                    trade = self.client.place_order(
                        symbol=signal["symbol"],
                        side=signal["side"],
                        order_type="Limit" if price else "Market",
                        qty=qty,
                        price=price,
                        stop_loss=signal.get("sl"),
                        take_profit=signal.get("tp"),
                    )

                    with self.stats_lock:
                        if trade:
                            self.stats["trades_executed"] += 1
                            self.stats["successful_trades"] += 1
                            try:
                                db_manager.add_trade(trade)
                            except Exception as e:
                                logger.error(f"Error saving trade for {symbol}: {e}")
                        else:
                            self.stats["failed_trades"] += 1

                        total_trades = self.stats["successful_trades"] + self.stats["failed_trades"]
                        self.stats["success_rate"] = (
                            (self.stats["successful_trades"] / total_trades) * 100
                            if total_trades > 0 else 0.0
                        )

                    # Refresh trades in UI
                    try:
                        trades = get_trades_safe(db_manager, limit=10)
                        with container:
                            display_trades_table(trades, container, client, max_trades=5)
                    except Exception as e:
                        logger.error(f"Error refreshing trades table: {e}")

                self._update_uptime()
                time.sleep(60)

            except Exception as e:
                logger.error(f"Error in trading loop for {symbol}: {e}")
                with self.stats_lock:
                    self.stats["failed_trades"] += 1
                time.sleep(30)

    def _update_uptime(self):
        if self.start_time:
            uptime = datetime.now(timezone.utc) - self.start_time
            with self.stats_lock:
                self.stats["uptime"] = str(uptime).split(".")[0]

    def get_status(self) -> Dict:
        with self.stats_lock:
            return {
                "is_running": self.is_running,
                "start_time": self.start_time.isoformat() if self.start_time else None,
                "stats": self.stats.copy()
            }

    def reset_stats(self):
        with self.stats_lock:
            self.stats = {
                "signals_generated": 0,
                "trades_executed": 0,
                "successful_trades": 0,
                "failed_trades": 0,
                "success_rate": 0.0,
                "uptime": "0:00:00"
            }
        logger.info("Statistics reset")

def show_automation(automated_trader, db, engine, client, trading_mode: str):
    st.title("🤖 Automation")
    st.markdown("---")
    automation_tab, logs_tab, stats_tab = st.tabs(["⚙️ Automation", "📜 Logs", "📊 Statistics"])

    with automation_tab:
        with st.container(border=True) as automation_container:
            st.markdown("### Automation Controls")
            automation_enabled = automated_trader.get_status()["is_running"]
            col1, col2 = st.columns(2)
            with col1:
                leverage = st.number_input("Leverage", value=10, min_value=1, max_value=100, key="auto_leverage")
            with col2:
                strategy = st.selectbox("Strategy", ["MACD", "Trend", "Mean", "Breakout"], key="auto_strategy")
            col3, col4 = st.columns(2)
            with col3:
                if st.button("🚀 Start Automation", type="primary", key="start_automation", disabled=automation_enabled):
                    if automated_trader.start(automation_container):
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
                st.metric("Successful Trades", status["stats"]["successful_trades"])
            with col2:
                st.metric("Success Rate", f"{status['stats']['success_rate']:.2f}%")
                st.metric("Failed Trades", status["stats"]["failed_trades"])
                st.metric("Uptime", status["stats"]["uptime"])

# Initialize components
db = db_manager
engine = TradingEngine()
client = engine.client
automated_trader = AutomatedTrader(engine, client)

# Set trading mode via radio button
st.session_state.trading_mode = st.radio(
    "Select Trading Mode:",
    options=["virtual", "real"],
    index=0  # default = virtual
)

# Run the app
show_automation(automated_trader, db, engine, client, st.session_state.trading_mode)
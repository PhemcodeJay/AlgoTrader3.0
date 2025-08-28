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
import pandas as pd

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# AutomatedTrader class (from uploaded document)
class AutomatedTrader:
    """Automated trading system"""
    
    def __init__(self, engine):
        self.is_running = False
        self.thread = None
        self.start_time = None
        self.engine = engine
        self.stats = {
            "signals_generated": 0,
            "trades_executed": 0,
            "success_rate": 0.0,
            "uptime": "0:00:00"
        }
        
    def start(self) -> bool:
        """Start the automated trading system"""
        if self.is_running:
            logger.warning("Automation is already running")
            return False
            
        try:
            self.is_running = True
            self.start_time = datetime.now(timezone.utc)
            self.thread = threading.Thread(target=self._trading_loop, daemon=True)
            self.thread.start()
            logger.info("Automated trading system started")
            return True
        except Exception as e:
            logger.error(f"Failed to start automation: {e}")
            self.is_running = False
            return False
    
    def stop(self):
        """Stop the automated trading system"""
        if not self.is_running:
            logger.warning("Automation is not running")
            return
            
        self.is_running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5)
        logger.info("Automated trading system stopped")
    
    def _trading_loop(self):
        """Main trading loop"""
        logger.info("Trading loop started")
        
        while self.is_running:
            try:
                # Generate signals
                signals = self.engine.run_once()
                self.stats["signals_generated"] += len(signals)
                
                # Execute top signals
                for signal in signals:
                    trade = self.engine.execute_signal(signal)
                    if trade:
                        self.stats["trades_executed"] += 1
                        # Save trade to database
                        try:
                            db_manager.add_trade(trade)
                        except Exception as e:
                            logger.error(f"Error saving trade to database: {e}")
                
                # Update success rate
                trade_stats = self.engine.get_trade_statistics()
                self.stats["success_rate"] = trade_stats.get("win_rate", 0.0)
                
                self._update_uptime()
                time.sleep(60)  # Run every minute
                
            except Exception as e:
                logger.error(f"Error in trading loop: {e}")
                time.sleep(30)  # Wait before retrying
    
    def _update_uptime(self):
        """Update uptime"""
        if self.start_time:
            uptime = datetime.now(timezone.utc) - self.start_time
            hours, remainder = divmod(uptime.total_seconds(), 3600)
            minutes, seconds = divmod(remainder, 60)
            self.stats["uptime"] = f"{int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}"
    
    def get_status(self) -> Dict:
        """Get current automation status"""
        return {
            "is_running": self.is_running,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "stats": self.stats.copy()
        }
    
    def reset_stats(self):
        """Reset trading statistics"""
        self.stats = {
            "signals_generated": 0,
            "trades_executed": 0,
            "success_rate": 0.0,
            "uptime": "0:00:00"
        }
        logger.info("Statistics reset")

# Utility function for log stats
def display_log_stats(log_file: str, container, refresh_key: str):
    """Display automation log statistics"""
    try:
        if not os.path.exists(log_file) or not os.access(log_file, os.R_OK):
            container.warning("🌙 No automation log file found or not readable")
            return

        error_count = 0
        warning_count = 0
        info_count = 0
        last_lines = []
        
        with open(log_file, "r") as f:
            lines = f.readlines()
            last_lines = lines[-10:]  # Last 10 lines for recent activity
            for line in lines:
                if "ERROR" in line:
                    error_count += 1
                elif "WARNING" in line:
                    warning_count += 1
                elif "INFO" in line:
                    info_count += 1

        col1, col2, col3 = container.columns(3)
        with col1:
            container.metric("Errors", error_count)
        with col2:
            container.metric("Warnings", warning_count)
        with col3:
            container.metric("Info Logs", info_count)
        
        container.markdown("**Recent Log Entries**")
        if last_lines:
            log_text = "".join(last_lines)
            container.text_area("Recent Logs", log_text, height=150, key=f"log_area_{refresh_key}")
        else:
            container.info("🌙 No recent log entries")
    except Exception as e:
        logger.error(f"Error displaying log stats: {e}")
        container.error(f"🚨 Error displaying log stats: {e}")

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
    .stButton > button[kind="secondary"] {
        background: linear-gradient(45deg, #ef4444, #f87171);
    }
    .stButton > button[kind="secondary"]:hover {
        background: linear-gradient(45deg, #f87171, #fca5a5);
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

    /* Text area */
    .stTextArea textarea {
        background: rgba(255,255,255,0.05);
        color: #ffffff;
        border-radius: 8px;
    }

    /* Modal styling */
    .modal {
        background: #2c2c4e;
        border-radius: 10px;
        padding: 20px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.4);
        color: #ffffff;
    }
    </style>
""", unsafe_allow_html=True)

def show_automation(automated_trader, db, engine, client):
    """Automation settings and monitoring page"""
    st.title("⚙️ Automation Control")

    # Check database connection
    if not db or not hasattr(db, 'add_trade'):
        st.error("🚨 Database connection not available")
        return

    # Initialize session state for modal and status
    if "show_progress_modal" not in st.session_state:
        st.session_state.show_progress_modal = False
    if "last_status" not in st.session_state:
        st.session_state.last_status = automated_trader.get_status()

    # Modal for real-time progress
    def show_progress_modal():
        with st.container():
            st.markdown('<div class="modal">', unsafe_allow_html=True)
            st.markdown("### 📊 Automation Progress")
            status = automated_trader.get_status()
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Signals Generated", status["stats"]["signals_generated"])
                st.metric("Trades Executed", status["stats"]["trades_executed"])
            with col2:
                st.metric("Success Rate", f"{status['stats']['success_rate']:.2%}")
                st.metric("Uptime", status["stats"]["uptime"])
            if st.button("🛑 Close Progress", key="close_progress_modal"):
                st.session_state.show_progress_modal = False
                st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)

    # Show modal if automation is running
    if st.session_state.show_progress_modal and automated_trader.get_status()["is_running"]:
        show_progress_modal()

    # Define tabs
    control_tab, logs_tab, stats_tab = st.tabs(["🎮 Control", "📜 Logs", "📊 Statistics"])

    # --- Control tab ---
    with control_tab:
        with st.container(border=True):
            st.markdown("### Automation Settings")
            trader_status = automated_trader.get_status()
            automation_enabled = st.checkbox("Enable Automation", value=trader_status["is_running"], key="automation_toggle")

            col1, col2 = st.columns(2)
            with col1:
                leverage = st.number_input("Leverage", min_value=1, max_value=100, value=10, step=1, key="automation_leverage")
            with col2:
                strategy = st.selectbox("Strategy", ["Scalping", "Swing", "Day Trading"], index=0, key="automation_strategy")

            col1, col2 = st.columns(2)
            with col1:
                if st.button("🚀 Start Automation", type="primary", key="start_automation"):
                    if not trader_status["is_running"]:
                        success = automated_trader.start()
                        if success:
                            st.success("✅ Automation started successfully")
                            st.session_state.show_progress_modal = True
                            st.rerun()
                        else:
                            st.error("🚨 Failed to start automation")
                    else:
                        st.warning("⚠️ Automation is already running")
            with col2:
                if st.button("🛑 Stop Automation", type="secondary", key="stop_automation"):
                    if trader_status["is_running"]:
                        automated_trader.stop()
                        st.success("✅ Automation stopped successfully")
                        st.session_state.show_progress_modal = False
                        st.rerun()
                    else:
                        st.warning("⚠️ Automation is not running")

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

    # --- Logs tab ---
    with logs_tab:
        with st.container(border=True):
            st.markdown("### Automation Logs")
            try:
                log_file = "automation.log"
                if os.path.exists(log_file) and os.access(log_file, os.R_OK):
                    with open(log_file, "r") as f:
                        lines = f.readlines()
                    lines = lines[-200:]  # Show last 200 lines max
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

    # --- Statistics tab ---
    with stats_tab:
        with st.container(border=True):
            st.markdown("### 📊 Automation Statistics")
            display_log_stats("automation.log", st, "refresh_automation_stats")
            # Display trader stats
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
show_automation(automated_trader, db, engine, client)
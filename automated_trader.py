import os
import threading
import time
from datetime import datetime, timezone
from typing import Dict, Optional
import logging
from bybit_client import BybitClient
from ml import MLFilter
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

class AutomatedTrader:
    def __init__(self, engine, client: BybitClient, risk_per_trade: float = 0.01):
        self.is_running = False
        self.thread = None
        self.start_time = None
        self.engine = engine
        self.client = client
        self.ml_filter = MLFilter() if os.getenv("ML_ENABLED", "true").lower() == "true" else None
        self.risk_per_trade = risk_per_trade  # Risk % per trade (default 1%)
        self.min_sl_points = float(os.getenv("MIN_SL_POINTS", "10"))  # Minimum stop loss points
        self.max_sl_points = float(os.getenv("MAX_SL_POINTS", "100"))  # Maximum stop loss points
        self.stats = {
            "signals_generated": 0,
            "trades_executed": 0,
            "successful_trades": 0,
            "failed_trades": 0,
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
            self.thread = threading.Thread(target=self._trading_loop, daemon=True)
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

    def _calculate_position_size(self, entry_price: float, stop_loss: float, account_balance: float) -> float:
        """Calculate position size based on risk per trade and stop loss distance"""
        if not entry_price or not stop_loss:
            return 0.0
        risk_amount = account_balance * self.risk_per_trade
        stop_distance = abs(entry_price - stop_loss)
        return risk_amount / stop_distance if stop_distance > 0 else 0.0

    def _validate_sl_tp(self, signal: Dict) -> bool:
        """Validate stop loss and take profit values"""
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

            # Ensure TP is in the right direction relative to entry and side
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

    def _trading_loop(self):
        while self.is_running:
            try:
                signals = self.engine.run_once()
                self.stats["signals_generated"] += len(signals)
                
                account_balance = self.client.get_account_balance()
                
                for signal in signals:
                    if not self._validate_sl_tp(signal):
                        self.stats["failed_trades"] += 1
                        continue

                    # Calculate position size based on risk management
                    qty = self._calculate_position_size(
                        signal["entry"],
                        signal["sl"],
                        account_balance
                    )

                    if qty <= 0:
                        logger.error(f"Invalid position size for signal: {signal}")
                        self.stats["failed_trades"] += 1
                        continue

                    trade = self.client.place_order(
                        symbol=signal["symbol"],
                        side=signal["side"],
                        order_type="Limit" if signal["entry"] else "Market",
                        qty=qty,
                        price=signal["entry"],
                        stop_loss=signal["sl"],
                        take_profit=signal["tp"]
                    )
                    
                    if trade:
                        self.stats["trades_executed"] += 1
                        self.stats["successful_trades"] += 1
                    else:
                        self.stats["failed_trades"] += 1

                    # Update success rate
                    total_trades = self.stats["successful_trades"] + self.stats["failed_trades"]
                    self.stats["success_rate"] = (
                        self.stats["successful_trades"] / total_trades * 100
                        if total_trades > 0 else 0.0
                    )

                self._update_uptime()
                time.sleep(1)  # Prevent excessive CPU usage
            except Exception as e:
                logger.error(f"Error in trading loop: {e}")
                self.stats["failed_trades"] += 1
                time.sleep(5)  # Wait before retrying on error

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
            "successful_trades": 0,
            "failed_trades": 0,
            "success_rate": 0.0,
            "uptime": "0:00:00"
        }
        logger.info("Statistics reset")
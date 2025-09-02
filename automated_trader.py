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
logging.basicConfig(
    level=logging.INFO,
    filename="app.log",
    filemode="a",
    format="%(asctime)s - %(levelname)s - %(message)s",
    encoding="utf-8"
)
logger = logging.getLogger(__name__)

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

    def start(self) -> bool:
        if self.is_running:
            logger.warning("Automation is already running")
            return False
        try:
            self.is_running = True
            self.start_time = datetime.now(timezone.utc)
            symbols = os.getenv("SYMBOLS", "BTCUSDT,ETHUSDT,XRPUSDT").split(",")
            interval = os.getenv("INTERVAL", "60")
            strategy = os.getenv("STRATEGY", "MACD")
            for symbol in symbols:
                thread = threading.Thread(
                    target=self._trading_loop,
                    args=(symbol, interval, strategy),
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

    def _trading_loop(self, symbol: str, interval: str, strategy: str):
        logger.info(f"Automated trading loop started for {symbol} on {interval} with {strategy}")

        while self.is_running:
            try:
                trading_mode = "virtual" if self.client.virtual_mode else "real"
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
                    # Enhance and validate signal using MLFilter
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

                    # Explicitly define price as a float
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
                                self.engine.db.add_trade(trade)
                            except Exception as e:
                                logger.error(f"Error saving trade for {symbol}: {e}")
                        else:
                            self.stats["failed_trades"] += 1

                        total_trades = self.stats["successful_trades"] + self.stats["failed_trades"]
                        self.stats["success_rate"] = (
                            (self.stats["successful_trades"] / total_trades) * 100
                            if total_trades > 0 else 0.0
                        )

                self._update_uptime()
                time.sleep(1)

            except Exception as e:
                logger.error(f"Error in trading loop for {symbol}: {e}")
                with self.stats_lock:
                    self.stats["failed_trades"] += 1
                time.sleep(5)

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
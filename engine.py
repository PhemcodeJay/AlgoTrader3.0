import os
import sys
import pandas as pd
import time
import json
import logging
import uuid
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from typing import Any, List, Union, Optional
from db import db_manager
from bybit_client import BybitClient
from utils import get_current_price
import portalocker

load_dotenv()
logger = logging.getLogger(__name__)

DEFAULT_SCAN_INTERVAL = int(os.getenv("DEFAULT_SCAN_INTERVAL", 3600))
DEFAULT_TOP_N_SIGNALS = int(os.getenv("DEFAULT_TOP_N_SIGNALS", 5))

class TradingEngine:
    def __init__(self):
        logger.info("[Engine] Initializing TradingEngine...")
        self.client = BybitClient()
        self.db = db_manager
        self.capital_file = "capital.json"

    def get_settings(self):
        scan_interval = self.db.get_setting("SCAN_INTERVAL")
        top_n_signals = self.db.get_setting("TOP_N_SIGNALS")
        scan_interval = int(scan_interval) if scan_interval else DEFAULT_SCAN_INTERVAL
        top_n_signals = int(top_n_signals) if top_n_signals else DEFAULT_TOP_N_SIGNALS
        return scan_interval, top_n_signals

    def update_settings(self, updates: dict):
        for key, value in updates.items():
            self.db.set_setting(key, value)

    def get_usdt_symbols(self):
        try:
            symbols = self.client.get_symbols()
            usdt_symbols = [s["symbol"] for s in symbols if s["symbol"].endswith("USDT")]
            return usdt_symbols[:50]
        except Exception as e:
            logger.error(f"Error getting USDT symbols: {e}")
            return ["BTCUSDT", "ETHUSDT", "DOGEUSDT", "SOLUSDT", "XRPUSDT"]

    def get_open_real_trades(self):
        trades = self.db.get_open_trades()
        return [trade for trade in trades if not trade.virtual]

    def get_open_virtual_trades(self):
        trades = self.db.get_open_trades()
        return [trade for trade in trades if trade.virtual]

    def get_closed_real_trades(self):
        trades = self.db.get_trades_by_status('closed')
        return [trade for trade in trades if not trade.virtual]

    def get_closed_virtual_trades(self):
        trades = self.db.get_trades_by_status('closed')
        return [trade for trade in trades if trade.virtual]

    def get_trade_statistics(self):
        all_trades = self.db.get_trades(limit=1000)
        if not all_trades:
            return {}
        total_trades = len(all_trades)
        profitable_trades = sum(1 for t in all_trades if t.pnl and t.pnl > 0)
        total_pnl = sum(t.pnl for t in all_trades if t.pnl)
        return {
            "total_trades": total_trades,
            "profitable_trades": profitable_trades,
            "win_rate": (profitable_trades / total_trades * 100) if total_trades > 0 else 0,
            "total_pnl": total_pnl
        }

    def calculate_virtual_pnl(self, trade):
        try:
            current_price = self.client.get_current_price(trade.get("symbol", ""))
            entry_price = float(trade.get("entry_price", 0))
            qty = float(trade.get("qty", 0))
            side = trade.get("side", "Buy").upper()
            if side == "BUY":
                pnl = (current_price - entry_price) * qty
            else:
                pnl = (entry_price - current_price) * qty
            return pnl
        except Exception as e:
            logger.error(f"Error calculating virtual PnL: {e}")
            return 0.0

    def get_ticker(self, symbol):
        try:
            price = self.client.get_current_price(symbol)
            return {"lastPrice": price}
        except Exception as e:
            logger.error(f"Error getting ticker for {symbol}: {e}")
            return {}

    def get_ticker_data(self):
        try:
            from utils import get_ticker_snapshot
            ticker_data = get_ticker_snapshot()
            if ticker_data:
                logger.info(f"Retrieved real-time data for {len(ticker_data)} symbols")
            return ticker_data
        except Exception as e:
            logger.error(f"Error getting real-time ticker data: {e}")
            return []

    def get_signals(self):
        signals = self.db.get_signals(limit=20)
        return [signal.to_dict() for signal in signals]

    def run_once(self, trading_mode="virtual"):
        logger.info("[Engine] Automated Trading Starting...")
        signals = []
        try:
            from utils import generate_real_signals
            from settings import load_settings
            settings = load_settings()
            symbols = settings.get("SYMBOLS", ["BTCUSDT", "ETHUSDT", "DOGEUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "AVAXUSDT"])
            real_signals = generate_real_signals(symbols, interval="60", trading_mode=trading_mode)

            for signal in real_signals:
                try:
                    if not all(key in signal for key in ["symbol", "side", "entry_price", "tp", "sl", "score", "strategy"]):
                        logger.warning(f"Skipping signal due to missing required fields: {signal}")
                        continue

                    entry_price = signal["entry_price"]
                    leverage = signal.get("leverage", 10)
                    side = signal["side"]

                    if side == "Buy":
                        trail_price = entry_price + (signal["tp"] - entry_price) * 0.5
                        liquidation_price = entry_price * (1 - 0.8 / leverage)
                    else:
                        trail_price = entry_price - (entry_price - signal["tp"]) * 0.5
                        liquidation_price = entry_price * (1 + 0.8 / leverage)

                    signal_data = {
                        "symbol": signal["symbol"],
                        "interval": "1h",
                        "signal_type": signal["side"],
                        "score": signal["score"],
                        "indicators": {
                            "rsi": signal.get("rsi", 50),
                            "ema_21": signal.get("ema_21", 0),
                            "strategy": signal["strategy"],
                            "leverage": leverage,
                            "margin_usdt": signal.get("margin_usdt", 15),
                            "qty": signal.get("qty", 15 / entry_price)
                        },
                        "strategy": signal["strategy"],
                        "side": side,
                        "entry": entry_price,
                        "tp": signal["tp"],
                        "sl": signal["sl"],
                        "trail": trail_price,
                        "liquidation": liquidation_price,
                        "leverage": leverage,
                        "margin_usdt": signal.get("margin_usdt", 15.0)
                    }

                    self.db.add_signal(signal_data)
                    signals.append(signal_data)

                except Exception as e:
                    logger.error(f"Error processing signal for {signal['symbol']}: {e}")

            # Fallback demo signals
            if not signals:
                for symbol in symbols[:2]:
                    try:
                        current_price = self.client.get_current_price(symbol)
                        if not current_price:
                            logger.warning(f"No price data for {symbol}")
                            continue
                        signal = {
                            "symbol": symbol,
                            "side": "Buy",
                            "entry_price": current_price,
                            "tp": current_price * 1.025,
                            "sl": current_price * 0.985,
                            "score": 65.0,
                            "strategy": "Fallback Demo",
                            "leverage": 10,
                            "margin_usdt": 15,
                            "qty": 15 / current_price
                        }
                        trail_price = current_price * 1.0125
                        liquidation_price = current_price * (1 - 0.8 / 10)
                        signal_data = {
                            "symbol": symbol,
                            "interval": "1h",
                            "signal_type": "Buy",
                            "score": 65.0,
                            "indicators": {"demo": True},
                            "strategy": "Fallback Demo",
                            "side": "LONG",
                            "entry": current_price,
                            "tp": current_price * 1.025,
                            "sl": current_price * 0.985,
                            "trail": trail_price,
                            "liquidation": liquidation_price,
                            "leverage": 10,
                            "margin_usdt": 15.0
                        }
                        self.db.add_signal(signal_data)
                        signals.append(signal_data)
                    except Exception as e:
                        logger.error(f"Error creating demo signal for {symbol}: {e}")

        except Exception as e:
            logger.error(f"Error in signal generation: {e}")

        logger.info(f"[Engine] Generated {len(signals)} signals")
        return signals

    def execute_signal(self, signal: dict, trading_mode: str = "real") -> Optional[dict]:
        try:
            symbol = signal.get("symbol")
            side = signal.get("side", "Buy")
            entry = signal.get("entry_price") or signal.get("entry")
            qty = signal.get("qty") or signal.get("quantity") or 0.0
            leverage = signal.get("leverage", 10)
            virtual = trading_mode == "virtual"
            take_profit = signal.get("tp")
            stop_loss = signal.get("sl")
            margin_usdt = signal.get("margin_usdt", 15.0)

            if not symbol or not entry or not qty:
                logger.warning(f"⚠️ Invalid signal for execution: {signal}")
                return None

            capital_data = self.load_capital(mode=trading_mode)
            available = capital_data.get("available", 0.0)
            if margin_usdt > available:
                logger.warning(f"Insufficient {trading_mode} funds: {margin_usdt} > {available}")
                return None

            if self.client.is_connected() and not virtual:
                order_result = self.client.place_order(
                    symbol=symbol,
                    side=side,
                    order_type="Market",
                    qty=qty,
                    price=entry,
                    stop_loss=stop_loss,
                    take_profit=take_profit
                )
                if not order_result:
                    logger.error(f"Failed to place order for {symbol}")
                    return None

                trade_data = {
                    "symbol": symbol,
                    "side": side,
                    "entry_price": round(order_result.get("price", entry), 6),
                    "take_profit": order_result.get("takeProfit"),
                    "stop_loss": order_result.get("stopLoss"),
                    "qty": order_result.get("qty", qty),
                    "leverage": leverage,
                    "margin_usdt": margin_usdt,
                    "strategy": signal.get("strategy", "Unknown"),
                    "score": signal.get("score", 0),
                    "status": order_result.get("status", "open"),
                    "virtual": False,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "order_id": order_result.get("order_id")
                }
                capital_data["available"] -= margin_usdt
                capital_data["used"] += margin_usdt
                self.save_capital(trading_mode, capital_data)
            else:
                trade_data = {
                    "symbol": symbol,
                    "side": side,
                    "entry_price": round(entry, 6),
                    "take_profit": take_profit,
                    "stop_loss": stop_loss,
                    "qty": qty,
                    "leverage": leverage,
                    "margin_usdt": margin_usdt,
                    "strategy": signal.get("strategy", "Unknown"),
                    "score": signal.get("score", 0),
                    "status": "open",
                    "virtual": True,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "order_id": str(uuid.uuid4())
                }
                capital_data["available"] -= margin_usdt
                capital_data["used"] += margin_usdt
                self.save_capital(trading_mode, capital_data)

            self.db.add_trade(trade_data)
            logger.info(f"Executed signal: {symbol} | Side: {side} | Qty: {qty} | Virtual: {virtual}")
            return trade_data

        except Exception as e:
            logger.error(f"❌ Error executing signal: {e}")
            return None

    def load_capital(self, mode="all"):
        try:
            with open(self.capital_file, "r") as f:
                portalocker.lock(f, portalocker.LOCK_SH)
                capital_data = json.load(f)
                portalocker.unlock(f)
                if mode == "all":
                    return capital_data
                return capital_data.get(mode, {})
        except FileNotFoundError:
            default_capital = {
                "real": {"capital": 0.0, "available": 0.0, "used": 0.0, "start_balance": 0.0, "currency": "USDT"},
                "virtual": {"capital": 100.0, "available": 100.0, "used": 0.0, "start_balance": 100.0, "currency": "USDT"}
            }
            self.save_capital("all", default_capital)
            return default_capital if mode == "all" else default_capital.get(mode, {})
        except Exception as e:
            logger.error(f"Error loading capital: {e}")
            return {}

    def save_capital(self, mode, capital_data):
        try:
            all_capital = self.load_capital("all") if mode != "all" else {}
            if mode != "all":
                all_capital[mode] = capital_data
            else:
                all_capital = capital_data
            with open(self.capital_file, "w") as f:
                portalocker.lock(f, portalocker.LOCK_EX)
                json.dump(all_capital, f, indent=4)
                portalocker.unlock(f)
        except Exception as e:
            logger.error(f"Error saving capital: {e}")

    def is_connected(self) -> bool:
        return self.client is not None
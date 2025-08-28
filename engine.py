import os
import sys
import pandas as pd
import time
import json
import logging
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from typing import Any, List, Union, Optional
from db import db_manager
from bybit_client import BybitClient
from utils import get_current_price

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

DEFAULT_SCAN_INTERVAL = int(os.getenv("DEFAULT_SCAN_INTERVAL", 3600))  # 60 minutes
DEFAULT_TOP_N_SIGNALS = int(os.getenv("DEFAULT_TOP_N_SIGNALS", 5))


class TradingEngine:
    def __init__(self):
        logger.info("[Engine] 🚀 Initializing TradingEngine...")
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
        """Get list of USDT trading pairs"""
        try:
            symbols = self.client.get_symbols()
            usdt_symbols = [s["symbol"] for s in symbols if s["symbol"].endswith("USDT")]
            return usdt_symbols[:50]  # Return top 50 symbols
        except Exception as e:
            logger.error(f"Error getting USDT symbols: {e}")
            return ["BTCUSDT", "ETHUSDT", "ADAUSDT", "SOLUSDT", "XRPUSDT"]

    def get_open_real_trades(self):
        """Get open real trades"""
        trades = self.db.get_open_trades()
        return [trade for trade in trades if not trade.virtual]
    
    def get_open_virtual_trades(self):
        """Get open virtual trades"""
        trades = self.db.get_open_trades()
        return [trade for trade in trades if trade.virtual]
    
    def get_closed_real_trades(self):
        """Get closed real trades"""
        trades = self.db.get_trades_by_status('closed')
        return [trade for trade in trades if not trade.virtual]
    
    def get_closed_virtual_trades(self):
        """Get closed virtual trades"""  
        trades = self.db.get_trades_by_status('closed')
        return [trade for trade in trades if trade.virtual]
    
    def get_trade_statistics(self):
        """Get trading statistics"""
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
        """Calculate virtual PnL for a trade"""
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
        """Get ticker information for a symbol"""
        try:
            price = self.client.get_current_price(symbol)
            return {"lastPrice": price}
        except Exception as e:
            logger.error(f"Error getting ticker for {symbol}: {e}")
            return {}

    def get_ticker_data(self):
        """Get real-time ticker data for display"""
        try:
            from utils import get_ticker_snapshot
            ticker_data = get_ticker_snapshot()
            if ticker_data:
                logger.info(f"✅ Retrieved real-time data for {len(ticker_data)} symbols")
            return ticker_data
        except Exception as e:
            logger.error(f"Error getting real-time ticker data: {e}")
            return []

    def get_signals(self):
        """Get recent signals"""
        signals = self.db.get_signals(limit=20)
        return [signal.to_dict() for signal in signals]

    def run_once(self):
        """Generate real trading signals using market data"""
        logger.info("[Engine] 🔍 Scanning market...\n")
        signals = []
        
        try:
            # Import the real signal generation function
            from utils import generate_real_signals
            
            # Get active trading symbols
            symbols = ["BTCUSDT", "ETHUSDT", "ADAUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "AVAXUSDT"]
            
            # Generate real signals using market data
            real_signals = generate_real_signals(symbols, interval="60")
            
            # Save signals to database
            for signal in real_signals:
                try:
                    # Calculate trail and liquidation prices
                    entry_price = signal["entry_price"]
                    leverage = signal["leverage"]
                    side = signal["side"]
                    
                    if side == "Buy":
                        trail_price = entry_price + (signal["tp_price"] - entry_price) * 0.5
                        liquidation_price = entry_price * (1 - 0.8 / leverage)  # 80% margin level
                    else:
                        trail_price = entry_price - (entry_price - signal["tp_price"]) * 0.5
                        liquidation_price = entry_price * (1 + 0.8 / leverage)
                    
                    signal_data = {
                        "symbol": signal["symbol"],
                        "interval": "1h",
                        "signal_type": signal["side"],
                        "score": signal["score"],
                        "indicators": {
                            "rsi": signal.get("rsi", 50),
                            "ema_21": signal.get("ema_21", 0),
                            "ema_50": signal.get("ema_50", 0),
                            "macd_hist": signal.get("macd_hist", 0)
                        },
                        "strategy": signal["strategy"],
                        "side": "LONG" if signal["side"] == "Buy" else "SHORT",
                        "entry": signal["entry_price"],
                        "tp": signal["tp_price"],
                        "sl": signal["sl_price"],
                        "trail": trail_price,
                        "liquidation": liquidation_price,
                        "leverage": signal["leverage"],
                        "margin_usdt": signal["margin_usdt"]
                    }
                    
                    self.db.add_signal(signal_data)
                    signals.append(signal)
                    
                except Exception as e:
                    logger.error(f"Error saving signal for {signal.get('symbol')}: {e}")
                    
            # If no real signals generated, create a few demo signals
            if not signals:
                for symbol in symbols[:3]:  # Just use first 3 symbols
                    try:
                        current_price = self.client.get_current_price(symbol)
                        if current_price > 0:
                            signal = {
                                "symbol": symbol,
                                "side": "Buy",
                                "entry_price": current_price,
                                "tp_price": current_price * 1.025,
                                "sl_price": current_price * 0.985,
                                "score": 65,
                                "strategy": "Fallback Demo",
                                "leverage": 10,
                                "margin_usdt": 15,
                                "qty": 15 / current_price
                            }
                            
                            trail_price = current_price * 1.0125  # 50% of TP distance
                            liquidation_price = current_price * (1 - 0.8 / 10)  # 80% margin level at 10x leverage
                            
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
                            signals.append(signal)
                            
                    except Exception as e:
                        logger.error(f"Error creating demo signal for {symbol}: {e}")
                        
        except Exception as e:
            logger.error(f"Error in signal generation: {e}")
            signals = []
                
        logger.info(f"[Engine] ✅ Generated {len(signals)} signals")
        return signals

    def load_capital(self, mode="all"):
        """Load capital from JSON file"""
        try:
            with open(self.capital_file, "r") as f:
                capital_data = json.load(f)
                if mode == "all":
                    return capital_data
                else:
                    return capital_data.get(mode, {})
        except FileNotFoundError:
            # Create default capital file
            default_capital = {
                "real": {"capital": 0.0, "available": 0.0, "used": 0.0, "start_balance": 0.0, "currency": "USDT"},
                "virtual": {"capital": 100.0, "available": 100.0, "used": 0.0, "start_balance": 100.0, "currency": "USDT"}
            }
            with open(self.capital_file, "w") as f:
                json.dump(default_capital, f, indent=4)
            return default_capital if mode == "all" else default_capital.get(mode, {})
        except Exception as e:
            logger.error(f"Error loading capital: {e}")
            return {}

    def save_capital(self, mode, capital_data):
        """Save capital to JSON file"""
        try:
            all_capital = self.load_capital("all")
            all_capital[mode] = capital_data
            with open(self.capital_file, "w") as f:
                json.dump(all_capital, f, indent=4)
        except Exception as e:
            logger.error(f"Error saving capital: {e}")
import os
import json
import logging
import pandas as pd
import numpy as np
import requests
import subprocess
import sys
from typing import List, Tuple, Dict, Any, Optional
from datetime import datetime, timezone
from dotenv import load_dotenv
import streamlit as st
from tenacity import retry, stop_after_attempt, wait_fixed

load_dotenv()
logger = logging.getLogger(__name__)

# Load settings with fallbacks from .env
try:
    from settings import load_settings
    settings = load_settings()
    RISK_PCT = float(os.getenv("RISK_PCT", settings.get("RISK_PCT", 0.01)))
    ACCOUNT_BALANCE = float(os.getenv("ACCOUNT_BALANCE", settings.get("VIRTUAL_BALANCE", 100.0)))
    LEVERAGE = float(os.getenv("LEVERAGE", settings.get("LEVERAGE", 20)))
    ENTRY_BUFFER_PCT = float(os.getenv("ENTRY_BUFFER_PCT", settings.get("ENTRY_BUFFER_PCT", 0.002)))
    TP_PERCENT = float(os.getenv("TP_PERCENT", settings.get("TP_PERCENT", 0.015)))
    SL_PERCENT = float(os.getenv("SL_PERCENT", settings.get("SL_PERCENT", 0.015)))
    SYMBOLS = settings.get("SYMBOLS", ["BTCUSDT", "ETHUSDT", "DOGEUSDT", "SOLUSDT", "XRPUSDT"])
except ImportError:
    RISK_PCT = float(os.getenv("RISK_PCT", 0.01))
    ACCOUNT_BALANCE = float(os.getenv("ACCOUNT_BALANCE", 100.0))
    LEVERAGE = float(os.getenv("LEVERAGE", 20))
    ENTRY_BUFFER_PCT = float(os.getenv("ENTRY_BUFFER_PCT", 0.002))
    TP_PERCENT = float(os.getenv("TP_PERCENT", 0.015))
    SL_PERCENT = float(os.getenv("SL_PERCENT", 0.015))
    SYMBOLS = ["BTCUSDT", "ETHUSDT", "DOGEUSDT", "SOLUSDT", "XRPUSDT"]

MIN_VOLUME = float(os.getenv("MIN_VOLUME", 1000))
MIN_ATR_PCT = float(os.getenv("MIN_ATR_PCT", 0.001))
RSI_ZONE = tuple(map(int, os.getenv("RSI_ZONE", "20,80").split(",")))
INTERVALS = os.getenv("INTERVALS", "15,60,240").split(",")
MAX_SYMBOLS = int(os.getenv("MAX_SYMBOLS", 50))

BASE_URL = "https://api.bybit.com"  # You can change this to testnet if needed

@retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
def get_current_price(symbol: str) -> float:
    try:
        url = f"{BASE_URL}/v5/market/tickers?category=linear&symbol={symbol}"
        response = requests.get(url).json()
        if response.get("retCode") == 0:
            return float(response["result"]["list"][0]["lastPrice"])
        logger.error(f"Error getting price for {symbol}: {response.get('retMsg')}")
        return 0.0
    except Exception as e:
        logger.error(f"Exception getting price for {symbol}: {e}")
        return 0.0

def get_candles(symbol: str, interval: str, limit: int = 100) -> List[Dict]:
    try:
        url = f"https://api.bybit.com/v5/market/kline?category=linear&symbol={symbol}&interval={interval}&limit={limit}"
        response = requests.get(url).json()
        if response.get("retCode") == 0:
            return [
                {
                    "time": int(candle[0]),
                    "open": float(candle[1]),
                    "high": float(candle[2]),
                    "low": float(candle[3]),
                    "close": float(candle[4]),
                    "volume": float(candle[5])
                }
                for candle in response.get("result", {}).get("list", [])
            ]
        else:
            logger.error(f"Error fetching candles for {symbol}: {response.get('retMsg')}")
            return []
    except Exception as e:
        logger.error(f"Error fetching candles for {symbol}: {e}")
        return []

def generate_real_signals(symbols: List[str], interval: str = "60", trading_mode: str = "virtual") -> List[Dict]:
    try:
        cmd = [sys.executable, "signal_generator.py", "--symbols", ",".join(symbols), "--interval", interval, "--mode", trading_mode]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            logger.error(f"signal_generator.py failed: {result.stderr}")
            return []
        json_file = "signals.json"
        if os.path.exists(json_file):
            with open(json_file, "r", encoding="utf-8") as f:
                signals = json.load(f)
            return signals
        return []
    except subprocess.TimeoutExpired:
        logger.error("signal_generator.py timed out")
        return []
    except Exception as e:
        logger.error(f"Error generating signals: {e}")
        return []

def normalize_signal(signal: Any) -> Dict:
    if isinstance(signal, dict):
        return signal
    return {
        "symbol": getattr(signal, "symbol", "N/A"),
        "interval": getattr(signal, "interval", "N/A"),
        "signal_type": getattr(signal, "signal_type", "N/A"),
        "score": getattr(signal, "score", 0.0),
        "indicators": getattr(signal, "indicators", {}),
        "strategy": getattr(signal, "strategy", "Auto"),
        "side": getattr(signal, "side", "LONG"),
        "sl": getattr(signal, "sl", None),
        "tp": getattr(signal, "tp", None),
        "trail": getattr(signal, "trail", None),
        "liquidation": getattr(signal, "liquidation", None),
        "leverage": getattr(signal, "leverage", 10),
        "margin_usdt": getattr(signal, "margin_usdt", None),
        "entry": getattr(signal, "entry", None),
        "market": getattr(signal, "market", None),
        "created_at": getattr(signal, "created_at", None)
    }

def format_price_safe(value: Optional[float]) -> str:
    try:
        return f"{float(value):.2f}" if value is not None and value > 0 else "N/A"
    except (ValueError, TypeError):
        return "N/A"

def format_currency_safe(value: Optional[float]) -> str:
    try:
        return f"{float(value):.2f}" if value is not None else "0.00"
    except (ValueError, TypeError):
        return "0.00"

def ema(data: List[float], period: int) -> float:
    try:
        if not data or len(data) < period:
            logger.warning(f"Insufficient data for EMA: {len(data)} < {period}")
            return 0.0
        series = pd.Series(data, dtype=float)
        return series.ewm(span=period, adjust=False).mean().iloc[-1]
    except Exception as e:
        logger.error(f"Error calculating EMA: {e}")
        return 0.0

def sma(data: List[float], period: int) -> float:
    try:
        if not data or len(data) < period:
            logger.warning(f"Insufficient data for SMA: {len(data)} < {period}")
            return 0.0
        series = pd.Series(data, dtype=float)
        return series.rolling(window=period).mean().iloc[-1]
    except Exception as e:
        logger.error(f"Error calculating SMA: {e}")
        return 0.0

def rsi(data: List[float], period: int = 14) -> float:
    try:
        if not data or len(data) < period:
            logger.warning(f"Insufficient data for RSI: {len(data)} < {period}")
            return 50.0
        series = pd.Series(data, dtype=float)
        delta = series.diff()
        gain = delta.where(delta > 0, 0).rolling(window=period).mean()
        loss = -delta.where(delta < 0, 0).rolling(window=period).mean()
        rs = gain / loss if loss != 0 else np.inf
        return 100 - (100 / (1 + rs))
    except Exception as e:
        logger.error(f"Error calculating RSI: {e}")
        return 50.0

def bollinger(data: List[float], period: int = 20, std_dev: float = 2.0) -> Tuple[float, float, float]:
    try:
        if not data or len(data) < period:
            logger.warning(f"Insufficient data for Bollinger Bands: {len(data)} < {period}")
            return 0.0, 0.0, 0.0
        series = pd.Series(data, dtype=float)
        sma_val = series.rolling(window=period).mean().iloc[-1]
        std_val = series.rolling(window=period).std().iloc[-1]
        upper = sma_val + std_dev * std_val
        lower = sma_val - std_dev * std_val
        return upper, sma_val, lower
    except Exception as e:
        logger.error(f"Error calculating Bollinger Bands: {e}")
        return 0.0, 0.0, 0.0

def atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
    try:
        if not highs or len(highs) < period or len(highs) != len(lows) or len(highs) != len(closes):
            logger.warning(f"Insufficient or mismatched data for ATR: highs={len(highs)}, lows={len(lows)}, closes={len(closes)}")
            return 0.0
        tr = [max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(closes[i-1] - lows[i])) for i in range(1, len(highs))]
        return pd.Series(tr, dtype=float).rolling(window=period).mean().iloc[-1]
    except Exception as e:
        logger.error(f"Error calculating ATR: {e}")
        return 0.0

def macd(data: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> float:
    try:
        if not data or len(data) < slow:
            logger.warning(f"Insufficient data for MACD: {len(data)} < {slow}")
            return 0.0
        series = pd.Series(data, dtype=float)
        ema_fast = series.ewm(span=fast, adjust=False).mean()
        ema_slow = series.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        return macd_line.ewm(span=signal, adjust=False).mean().iloc[-1]
    except Exception as e:
        logger.error(f"Error calculating MACD: {e}")
        return 0.0

def classify_trend(ema9: float, ema21: float, sma20: float) -> str:
    try:
        if ema9 > ema21 > sma20:
            return "Up"
        elif ema9 < ema21 < sma20:
            return "Down"
        return "Neutral"
    except Exception as e:
        logger.error(f"Error classifying trend: {e}")
        return "Neutral"

def get_ticker_snapshot() -> List[Dict]:
    try:
        url = "https://api.bybit.com/v5/market/tickers?category=linear"
        response = requests.get(url).json()
        if response.get("retCode") == 0:
            return [
                {
                    "symbol": ticker["symbol"],
                    "lastPrice": float(ticker["lastPrice"]),
                    "priceChangePercent": float(ticker["price24hPcnt"]) * 100
                }
                for ticker in response["result"]["list"]
                if ticker["symbol"].endswith("USDT")
            ]
        return []
    except Exception as e:
        logger.error(f"Error getting ticker snapshot: {e}")
        return []

def display_trades_table(trades: List, container, client, max_trades: int = 5):
    try:
        if not trades:
            container.info("🌙 No trades to display")
            return
        trades_data = []
        for trade in trades[:max_trades]:
            symbol = getattr(trade, 'symbol', 'N/A')
            current_price = client.get_current_price(symbol) if client and hasattr(client, 'get_current_price') else 0.0
            qty = float(getattr(trade, 'qty', 0))
            entry_price = float(getattr(trade, 'entry_price', 0))
            side = getattr(trade, 'side', 'Buy')
            unreal_pnl = (current_price - entry_price) * qty if side in ["Buy", "LONG"] else (entry_price - current_price) * qty
            trades_data.append({
                "Symbol": symbol,
                "Side": side,
                "Entry": f"${format_price_safe(entry_price)}",
                "P&L": f"${format_currency_safe(unreal_pnl if getattr(trade, 'status', '').lower() == 'open' else getattr(trade, 'pnl', 0))}",
                "Status": getattr(trade, 'status', 'N/A').title(),
                "Mode": "Virtual" if getattr(trade, 'virtual', True) else "Real"
            })
        if trades_data:
            df = pd.DataFrame(trades_data)
            container.dataframe(df, use_container_width=True, height=300)
        else:
            container.info("🌙 No trade data to display")
    except Exception as e:
        logger.error(f"Error displaying trades table: {e}")
        container.error(f"🚨 Error displaying trades")

def display_log_stats(log_file: str, container, refresh_key: str):
    try:
        if os.path.exists(log_file) and os.access(log_file, os.R_OK):
            with open(log_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
            if not lines:
                container.info("🌙 No logs found")
                return
            error_count = sum(1 for line in lines if "ERROR" in line.upper())
            warning_count = sum(1 for line in lines if "WARNING" in line.upper())
            info_count = sum(1 for line in lines if "INFO" in line.upper())
            recent_lines = lines[-10:]
            log_text = "".join(recent_lines)
            container.text_area("Recent Logs", log_text, height=150, key=f"recent_log_area_{refresh_key}")
            col1, col2, col3 = container.columns(3)
            with col1:
                st.metric("Errors", error_count)
            with col2:
                st.metric("Warnings", warning_count)
            with col3:
                st.metric("Info", info_count)
        else:
            container.info("🌙 No log file found")
    except Exception as e:
        logger.error(f"Error displaying log stats: {e}")
        container.error(f"🚨 Error displaying log stats: {e}")

def get_trades_safe(db_manager, symbol: Optional[str] = None, limit: int = 50) -> List[Dict]:
    try:
        if not db_manager:
            logger.error("❌ No db_manager provided to get_trades_safe")
            return []

        if symbol:
            trades = db_manager.get_trades_by_symbol(symbol, limit=limit)
        else:
            trades = db_manager.get_recent_trades(limit=limit)

        return trades if trades else []
    except Exception as e:
        logger.error(f"🚨 Error fetching trades (symbol={symbol}): {e}")
        return []

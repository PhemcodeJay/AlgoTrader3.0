import os
import logging
import pandas as pd
import numpy as np
import requests
from typing import List, Tuple, Union, Dict, Any, Optional
from datetime import datetime, timezone
import time
import json
import streamlit as st

logger = logging.getLogger(__name__)

# === CONFIGURATION ===
try:
    from settings import load_settings
    settings = load_settings()
    RISK_PCT = settings.get('RISK_PCT', 0.01)
    ACCOUNT_BALANCE = settings.get('VIRTUAL_BALANCE', 100.0)
    LEVERAGE = settings.get('LEVERAGE', 10)
    ENTRY_BUFFER_PCT = settings.get('ENTRY_BUFFER_PCT', 0.002)
except ImportError:
    RISK_PCT = 0.01
    ACCOUNT_BALANCE = 100.0
    LEVERAGE = 10
    ENTRY_BUFFER_PCT = 0.002

MIN_VOLUME = 1000
MIN_ATR_PCT = 0.001
RSI_ZONE = (20, 80)
INTERVALS = ['15', '60', '240']
MAX_SYMBOLS = 50

# === DISPLAY FUNCTIONS ===
def display_trades_table(trades, container, max_trades=5):
    """Reusable function to display trades table."""
    try:
        if not trades:
            container.info("No trades to display")
            return

        trades_data = []
        for trade in trades[:max_trades]:
            trades_data.append({
                "Symbol": getattr(trade, 'symbol', 'N/A'),
                "Side": getattr(trade, 'side', 'N/A'),
                "Entry": f"${format_price_safe(getattr(trade, 'entry_price', 0))}",
                "P&L": f"${format_currency_safe(getattr(trade, 'pnl', 0))}",
                "Status": getattr(trade, 'status', 'N/A').title(),
                "Mode": "Virtual" if getattr(trade, 'virtual', True) else "Real"
            })

        if trades_data:
            df = pd.DataFrame(trades_data)
            container.dataframe(df, use_container_width=True, height=300)
        else:
            container.info("No trade data to display")
    except Exception as e:
        logger.error(f"Error displaying trades table: {e}")
        container.error("Error displaying trades")

# === INDICATORS ===
def ema(data: List[float], period: int) -> float:
    """Calculate Exponential Moving Average for the last value."""
    try:
        series = pd.Series(data, dtype=float)
        if len(series) < period:
            logger.warning(f"Insufficient data for EMA calculation: {len(series)} < {period}")
            return 0.0
        return series.ewm(span=period, adjust=False).mean().iloc[-1]
    except Exception as e:
        logger.error(f"Error calculating EMA: {e}")
        return 0.0

def sma(data: List[float], period: int) -> float:
    """Calculate Simple Moving Average for the last value."""
    try:
        series = pd.Series(data, dtype=float)
        if len(series) < period:
            logger.warning(f"Insufficient data for SMA calculation: {len(series)} < {period}")
            return 0.0
        return series.rolling(window=period).mean().iloc[-1]
    except Exception as e:
        logger.error(f"Error calculating SMA: {e}")
        return 0.0

def rsi(data: List[float], period: int = 14) -> float:
    """Calculate Relative Strength Index for the last value."""
    try:
        series = pd.Series(data, dtype=float)
        if len(series) < period:
            logger.warning(f"Insufficient data for RSI calculation: {len(series)} < {period}")
            return 50.0
        delta = series.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        avg_gain = gain.rolling(period).mean()
        avg_loss = loss.rolling(period).mean()
        rs = avg_gain / (avg_loss + 1e-14)
        rsi_value = 100 - (100 / (1 + rs))
        return rsi_value.iloc[-1]
    except Exception as e:
        logger.error(f"Error calculating RSI: {e}")
        return 50.0

def bollinger(data: List[float], period: int = 20) -> Tuple[float, float, float]:
    """Calculate Bollinger Bands (upper, middle, lower) for the last value."""
    try:
        series = pd.Series(data, dtype=float)
        if len(series) < period:
            logger.warning(f"Insufficient data for Bollinger Bands calculation: {len(series)} < {period}")
            return 0.0, 0.0, 0.0
        sma = series.rolling(window=period).mean()
        std = series.rolling(window=period).std()
        bb_upper = sma + (2 * std)
        bb_lower = sma - (2 * std)
        return bb_upper.iloc[-1], sma.iloc[-1], bb_lower.iloc[-1]
    except Exception as e:
        logger.error(f"Error calculating Bollinger Bands: {e}")
        return 0.0, 0.0, 0.0

def atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
    """Calculate Average True Range for the last value."""
    try:
        if len(highs) != len(lows) or len(lows) != len(closes) or len(closes) < period:
            logger.warning(f"Insufficient or mismatched data for ATR calculation: {len(highs)}")
            return 0.0
        df = pd.DataFrame({'high': highs, 'low': lows, 'close': closes}, dtype=float)
        high_low = df['high'] - df['low']
        high_close = (df['high'] - df['close'].shift()).abs()
        low_close = (df['low'] - df['close'].shift()).abs()
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr_value = true_range.rolling(window=period).mean()
        return atr_value.iloc[-1]
    except Exception as e:
        logger.error(f"Error calculating ATR: {e}")
        return 0.0

def macd(data: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> float:
    """Calculate MACD line for the last value."""
    try:
        series = pd.Series(data, dtype=float)
        if len(series) < max(fast, slow, signal):
            logger.warning(f"Insufficient data for MACD calculation: {len(series)}")
            return 0.0
        ema_fast = series.ewm(span=fast, adjust=False).mean()
        ema_slow = series.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        return macd_line.iloc[-1]
    except Exception as e:
        logger.error(f"Error calculating MACD: {e}")
        return 0.0

def calculate_indicators(data: Union[List[Dict], pd.DataFrame]) -> pd.DataFrame:
    """Calculate technical indicators"""
    if isinstance(data, list):
        if not data or len(data) < 30:
            return pd.DataFrame(data)
        df = pd.DataFrame(data)
    else:
        df = data.copy()

    if df.empty or 'close' not in df.columns:
        logger.warning("Empty or invalid DataFrame for indicators")
        return df

    df = df.sort_values("timestamp").reset_index(drop=True)
    df['close'] = pd.to_numeric(df['close'], errors='coerce')
    df['high'] = pd.to_numeric(df['high'], errors='coerce')
    df['low'] = pd.to_numeric(df['low'], errors='coerce')
    df['volume'] = pd.to_numeric(df['volume'], errors='coerce')

    # RSI
    delta = df['close'].diff().astype(float)
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / (avg_loss + 1e-14)
    df['RSI'] = 100 - (100 / (1 + rs))
    df['RSI'] = df['RSI'].fillna(50)

    # EMAs and SMA
    df['EMA_9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['EMA_21'] = df['close'].ewm(span=21, adjust=False).mean()
    df['SMA_20'] = df['close'].rolling(window=20).mean()

    # MACD
    ema_12 = df['close'].ewm(span=12, adjust=False).mean()
    ema_26 = df['close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = ema_12 - ema_26
    df['MACD_signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['MACD_hist'] = df['MACD'] - df['MACD_signal']

    # Bollinger Bands
    sma = df['close'].rolling(window=20).mean()
    std = df['close'].rolling(window=20).std()
    df['BB_upper'] = sma + (2 * std)
    df['BB_lower'] = sma - (2 * std)

    return df

def classify_trend(ema9: float, ema21: float, sma20: float) -> str:
    """Classify market trend based on EMAs and SMA"""
    try:
        if ema9 > ema21 > sma20:
            return "Up"
        elif ema9 < ema21 < sma20:
            return "Down"
        elif ema9 > ema21:
            return "Bullish"
        elif ema9 < ema21:
            return "Bearish"
        return "Neutral"
    except (TypeError, ValueError) as e:
        logger.warning(f"Invalid values for trend classification: {e}")
        return "Neutral"

def score_signal(df: pd.DataFrame) -> float:
    """Score signal based on indicators"""
    required_cols = ['EMA_9', 'EMA_21', 'SMA_20', 'MACD', 'RSI', 'close', 'BB_upper', 'BB_lower']
    if any(col not in df.columns or df[col].isna().iloc[-1] for col in required_cols):
        logger.debug("Missing or NaN columns for signal scoring")
        return 0.0

    try:
        ema_9 = float(df['EMA_9'].iloc[-1])
        ema_21 = float(df['EMA_21'].iloc[-1])
        sma_20 = float(df['SMA_20'].iloc[-1])
        macd = float(df['MACD'].iloc[-1])
        rsi = float(df['RSI'].iloc[-1])
        price = float(df['close'].iloc[-1])
        bb_up = float(df['BB_upper'].iloc[-1])
        bb_low = float(df['BB_lower'].iloc[-1])
    except (TypeError, ValueError) as e:
        logger.warning(f"Error converting indicator values: {e}")
        return 0.0

    trend = classify_trend(ema_9, ema_21, sma_20)
    bb_dir = "Up" if price > bb_up else "Down" if price < bb_low else "No"

    score = 0.0
    score += 0.3 if macd > 0 else 0
    score += 0.2 if rsi < RSI_ZONE[0] or rsi > RSI_ZONE[1] else 0
    score += 0.2 if bb_dir != "No" else 0
    score += 0.3 if trend in ["Up", "Bullish"] else 0.3 if trend in ["Down", "Bearish"] else 0.0

    logger.debug(f"Signal score for {df.get('symbol', 'unknown')}: {score}")
    return round(score * 100, 2)

def format_currency_safe(value: Union[float, str, None], symbol: str = "$") -> str:
    """Format value as currency"""
    if value is None:
        logger.debug("None value passed to format_currency_safe")
        return f"{symbol}0.00"
    try:
        val = float(value)
        return f"{symbol}{val:,.2f}"
    except (ValueError, TypeError) as e:
        logger.warning(f"Invalid value for currency formatting: {value}, error: {e}")
        return f"{symbol}0.00"

def format_price_safe(value: Union[float, str, None]) -> str:
    """Format value as price"""
    if value is None:
        logger.debug("None value passed to format_price_safe")
        return "0.0000"
    try:
        val = float(value)
        if val <= 0:
            return "0.0000"
        if val >= 1_000_000:
            return f"{val / 1_000_000:.4f}M"
        elif val >= 1_000:
            return f"{val / 1_000:.4f}K"
        else:
            return f"{val:.4f}"
    except (ValueError, TypeError) as e:
        logger.warning(f"Invalid value for price formatting: {value}, error: {e}")
        return "0.0000"

def get_trade_attr(trade: Union[Dict, Any], key: str, default: Any = None) -> Any:
    """Safely get attribute from object or dict"""
    try:
        return getattr(trade, key, default) if hasattr(trade, key) else trade.get(key, default)
    except Exception as e:
        logger.warning(f"Error accessing trade attribute {key}: {e}")
        return default

def format_percentage(value: Optional[float]) -> str:
    """Format value as percentage"""
    if value is None:
        logger.debug("None value passed to format_percentage")
        return "0.00%"
    try:
        val = float(value)
        return f"{val:.2f}%"
    except (ValueError, TypeError) as e:
        logger.warning(f"Invalid value for percentage formatting: {value}, error: {e}")
        return "0.00%"

def get_trend_color(trend: str) -> str:
    """Get color based on trend"""
    trend = trend.lower()
    if trend in ("up", "bullish"):
        return "green"
    elif trend in ("down", "bearish"):
        return "red"
    return "gray"

def get_status_color(status: str) -> str:
    """Get color based on status"""
    status = status.lower()
    if status in ("success", "complete", "active", "ok"):
        return "green"
    elif status in ("failed", "error", "inactive"):
        return "red"
    elif status in ("pending", "waiting", "in_progress"):
        return "orange"
    return "gray"

def calculate_drawdown(equity_curve: Union[List[float], pd.Series]) -> Tuple[float, pd.Series]:
    """Calculate max drawdown and drawdown series"""
    try:
        if equity_curve is None or len(equity_curve) < 2:
            return 0.0, pd.Series(dtype=float)
        series = pd.Series(equity_curve, dtype=float)
        peak = series.cummax()
        drawdown = (series - peak) / peak * 100
        max_drawdown = drawdown.min()
        return round(float(max_drawdown), 2), drawdown
    except Exception as e:
        logger.error(f"Error calculating drawdown: {e}")
        return 0.0, pd.Series(dtype=float)

def get_ticker_snapshot() -> List[Dict[str, Any]]:
    """Get ticker snapshot from Bybit API"""
    major_symbols = ["BTCUSDT", "ETHUSDT", "ADAUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "AVAXUSDT"]
    
    try:
        response = requests.get("https://api.bybit.com/v5/market/tickers", params={"category": "linear"}, timeout=10)
        response.raise_for_status()
        data = response.json()
        tickers = data.get("result", {}).get("list", [])
        live_data = []
        for ticker in tickers:
            symbol = ticker.get("symbol")
            if symbol in major_symbols:
                try:
                    live_data.append({
                        "symbol": symbol,
                        "lastPrice": float(ticker.get("lastPrice", 0)),
                        "priceChangePercent": float(ticker.get("priceChangePercent", 0))
                    })
                except (ValueError, TypeError) as e:
                    logger.warning(f"Invalid ticker data for {symbol}: {e}")
                    continue
        if live_data:
            logger.info("Successfully fetched ticker data from Bybit")
            return live_data
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching ticker from Bybit: {e}")
        if response.status_code == 429:
            logger.warning("Rate limit exceeded, retrying after delay")
            time.sleep(5)
    
    logger.warning("Failed to fetch ticker data from Bybit")
    return []

def get_ticker_snapshot_safe() -> List[Dict[str, Any]]:
    """Safe wrapper for get_ticker_snapshot"""
    try:
        return get_ticker_snapshot()
    except Exception as e:
        logger.error(f"Error getting ticker snapshot: {e}")
        return []

def get_kline_data(symbol: str, interval: str, limit: int = 200) -> pd.DataFrame:
    """Get kline data from Bybit API"""
    try:
        response = requests.get(
            "https://api.bybit.com/v5/market/kline",
            params={"category": "linear", "symbol": symbol, "interval": interval, "limit": limit},
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'},
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
        if data.get("retCode") == 0 and data.get("result", {}).get("list"):
            klines = data["result"]["list"]
            df_data = [
                {
                    'timestamp': pd.to_datetime(int(kline[0]), unit='ms'),
                    'open': float(kline[1]),
                    'high': float(kline[2]),
                    'low': float(kline[3]),
                    'close': float(kline[4]),
                    'volume': float(kline[5])
                } for kline in reversed(klines)
            ]
            logger.info(f"Successfully fetched kline data for {symbol} from Bybit")
            return pd.DataFrame(df_data)
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching kline data from Bybit: {e}")
        if response.status_code == 429:
            logger.warning("Rate limit exceeded, retrying after delay")
            time.sleep(5)

    logger.warning(f"Failed to fetch kline data for {symbol} from Bybit")
    return pd.DataFrame()

def get_candles(symbol: str, interval: str) -> List[Dict]:
    """Fetch candles from Bybit API"""
    try:
        response = requests.get(
            "https://api.bybit.com/v5/market/kline",
            params={"category": "linear", "symbol": symbol, "interval": interval, "limit": 200},
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'},
            timeout=5
        )
        response.raise_for_status()
        data = response.json()
        if data.get("retCode") == 0 and data.get("result", {}).get("list"):
            klines = data["result"]["list"]
            candles = [
                {
                    'high': float(kline[2]),
                    'low': float(kline[3]),
                    'close': float(kline[4]),
                    'volume': float(kline[5]),
                    'timestamp': pd.to_datetime(int(kline[0]), unit='ms')
                } for kline in reversed(klines)
            ]
            logger.info(f"Successfully fetched candles for {symbol} from Bybit")
            return candles
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching candles for {symbol} from Bybit: {e}")
        if response.status_code == 429:
            logger.warning("Rate limit exceeded, retrying after delay")
            time.sleep(5)

    logger.warning(f"Failed to fetch candles for {symbol} from Bybit")
    return []

def get_current_price(symbol: str) -> float:
    """Get current price from Bybit API"""
    try:
        response = requests.get(
            f"https://api.bybit.com/v5/market/tickers?category=linear&symbol={symbol}",
            timeout=5
        )
        response.raise_for_status()
        data = response.json()
        if data.get("retCode") == 0:
            price = float(data["result"]["list"][0]["lastPrice"])
            logger.info(f"Successfully fetched price for {symbol} from Bybit: {price}")
            return price
    except requests.exceptions.RequestException as e:
        logger.error(f"Error getting price for {symbol} from Bybit: {e}")
        if response.status_code == 429:
            logger.warning("Rate limit exceeded, retrying after delay")
            time.sleep(5)

    logger.warning(f"Failed to fetch price for {symbol} from Bybit")
    return 0.0

def get_current_price_safe(symbol: str) -> float:
    """Safe wrapper for get_current_price"""
    try:
        return get_current_price(symbol)
    except Exception as e:
        logger.error(f"Error in get_current_price_safe for {symbol}: {e}")
        return 0.0

def load_virtual_balance() -> Dict[str, float]:
    """Load virtual balance from file or return default"""
    try:
        if os.path.exists("capital.json") and os.access("capital.json", os.R_OK):
            with open("capital.json", "r") as f:
                data = json.load(f)
                return data.get("virtual", {"capital": 100.0, "available": 100.0})
        return {"capital": 100.0, "available": 100.0}
    except Exception as e:
        logger.error(f"Error loading virtual balance: {e}")
        return {"capital": 100.0, "available": 100.0}

def get_open_trades_safe(db) -> List[Any]:
    """Safe wrapper for getting open trades"""
    try:
        if db and hasattr(db, 'get_open_trades'):
            return db.get_open_trades()
        logger.warning("Database not available for get_open_trades")
        return []
    except Exception as e:
        logger.error(f"Error in get_open_trades_safe: {e}")
        return []

def get_trades_safe(db, limit: int = 100) -> List[Any]:
    """Safe wrapper for getting trades"""
    try:
        if db and hasattr(db, 'get_trades'):
            return db.get_trades(limit=limit)
        logger.warning("Database not available for get_trades")
        return []
    except Exception as e:
        logger.error(f"Error in get_trades_safe: {e}")
        return []

def get_signals_safe(db) -> List[Any]:
    """Safe wrapper for getting signals"""
    try:
        if db and hasattr(db, 'get_signals'):
            return db.get_signals()
        logger.warning("Database not available for get_signals")
        return []
    except Exception as e:
        logger.error(f"Error in get_signals_safe: {e}")
        return []

def get_portfolio_safe(db) -> List[Any]:
    """Safe wrapper for getting portfolio holdings"""
    try:
        if db and hasattr(db, 'get_portfolio'):
            return db.get_portfolio()
        logger.warning("Database not available for get_portfolio")
        return []
    except Exception as e:
        logger.error(f"Error in get_portfolio_safe: {e}")
        return []

def get_daily_pnl(client) -> float:
    """Calculate daily P&L from open and closed trades"""
    try:
        if not client or not hasattr(client, 'get_trades'):
            logger.warning("Client not available for get_daily_pnl")
            return 0.0

        today = datetime.now(timezone.utc).date()
        trades = client.get_trades(limit=100)
        daily_pnl = 0.0
        for trade in trades:
            trade_time = getattr(trade, 'created_at', None)
            if trade_time and trade_time.date() == today:
                realized_pnl = float(getattr(trade, 'pnl', 0))
                daily_pnl += realized_pnl
            elif not trade_time:
                logger.debug(f"Trade {getattr(trade, 'id', 'unknown')} missing timestamp")
        logger.info(f"Calculated daily P&L: {daily_pnl}")
        return daily_pnl
    except Exception as e:
        logger.error(f"Error in get_daily_pnl: {e}")
        return 0.0

def get_daily_pnl_safe(client) -> float:
    """Safe wrapper for get_daily_pnl"""
    try:
        return get_daily_pnl(client)
    except Exception as e:
        logger.error(f"Error in get_daily_pnl_safe: {e}")
        return 0.0

def generate_real_signals(symbols: List[str], interval: str = "60", limit: int = 5) -> List[Dict]:
    """Generate trading signals"""
    signals = []

    for symbol in symbols[:limit]:
        try:
            sides = []
            for tf in INTERVALS:
                candles = get_candles(symbol, tf)
                if not candles or len(candles) < 50:
                    logger.warning(f"Insufficient data for {symbol} on timeframe {tf}")
                    continue

                df = pd.DataFrame({
                    'close': [c['close'] for c in candles],
                    'high': [c['high'] for c in candles],
                    'low': [c['low'] for c in candles],
                    'volume': [c['volume'] for c in candles],
                    'timestamp': [c['timestamp'] for c in candles]
                })

                df = calculate_indicators(df)
                ema_9 = float(df['EMA_9'].iloc[-1])
                ema_21 = float(df['EMA_21'].iloc[-1])
                sma_20 = float(df['SMA_20'].iloc[-1])
                trend = classify_trend(ema_9, ema_21, sma_20)
                side = "LONG" if trend in ["Up", "Bullish"] else "SHORT" if trend in ["Down", "Bearish"] else "NEUTRAL"
                sides.append(side)

            if len(set(sides)) != 1 or sides[0] == "NEUTRAL":
                logger.debug(f"Skipping {symbol} due to inconsistent or neutral trend")
                continue

            candles = get_candles(symbol, interval)
            if not candles or len(candles) < 50:
                logger.warning(f"Insufficient data for {symbol} on timeframe {interval}")
                continue

            df = pd.DataFrame({
                'close': [c['close'] for c in candles],
                'high': [c['high'] for c in candles],
                'low': [c['low'] for c in candles],
                'volume': [c['volume'] for c in candles],
                'timestamp': [c['timestamp'] for c in candles],
                'symbol': symbol
            })

            df = calculate_indicators(df)
            score = score_signal(df)
            if score < 60:
                logger.debug(f"Skipping {symbol} due to low score: {score}")
                continue

            ema_9 = float(df['EMA_9'].iloc[-1])
            ema_21 = float(df['EMA_21'].iloc[-1])
            sma_20 = float(df['SMA_20'].iloc[-1])
            macd = float(df['MACD'].iloc[-1])
            rsi = float(df['RSI'].iloc[-1])
            bb_up = float(df['BB_upper'].iloc[-1])
            bb_low = float(df['BB_lower'].iloc[-1])
            price = float(df['close'].iloc[-1])

            if price <= 0:
                logger.warning(f"Invalid price for {symbol}: {price}")
                continue

            trend = classify_trend(ema_9, ema_21, sma_20)
            bb_dir = "Up" if price > bb_up else "Down" if price < bb_low else "No"

            opts = [sma_20, ema_9, ema_21]
            entry = min(opts, key=lambda x: abs(x - price))

            side = 'Buy' if sides[0] == 'LONG' else 'Sell'

            tp = round(entry * (1 + settings.get('TP_PERCENT', 0.015)) if side == 'Buy' else entry * (1 - settings.get('TP_PERCENT', 0.015)), 6)
            sl = round(entry * (1 - settings.get('SL_PERCENT', 0.015)) if side == 'Buy' else entry * (1 + settings.get('SL_PERCENT', 0.015)), 6)
            trail = round(entry * (1 - ENTRY_BUFFER_PCT) if side == 'Buy' else entry * (1 + ENTRY_BUFFER_PCT), 6)
            liq = round(entry * (1 - 1 / LEVERAGE) if side == 'Buy' else entry * (1 + 1 / LEVERAGE), 6)

            try:
                risk_amt = ACCOUNT_BALANCE * RISK_PCT
                sl_diff = abs(entry - sl)
                if sl_diff <= 0:
                    logger.warning(f"Invalid stop-loss difference for {symbol}: {sl_diff}")
                    continue
                qty = risk_amt / sl_diff
                margin_usdt = round((qty * entry) / LEVERAGE, 3)
                qty = round(qty, 3)
            except (ZeroDivisionError, ValueError) as e:
                logger.warning(f"Error calculating position size for {symbol}: {e}")
                margin_usdt = 1.0
                qty = 1.0

            signal = {
                "symbol": symbol,
                "side": side,
                "entry_price": entry,
                "tp": tp,
                "sl": sl,
                "trail": trail,
                "liquidation": liq,
                "qty": qty,
                "margin_usdt": margin_usdt,
                "score": score,
                "strategy": "Multi-TF Signal",
                "trend": trend,
                "bb_direction": bb_dir,
                "timeframe": interval,
                "confidence": score,
                "market": "Bybit",
                "virtual": False,
                "indicators": {
                    "rsi": rsi,
                    "ema_9": ema_9,
                    "ema_21": ema_21,
                    "sma_20": sma_20,
                    "macd": macd,
                    "bb_upper": bb_up,
                    "bb_lower": bb_low
                }
            }

            logger.info(f"Generated signal for {symbol}: {side}, score={score}")
            signals.append(signal)

        except Exception as e:
            logger.error(f"Error generating signal for {symbol}: {e}")
            continue

    return signals[:settings.get('TOP_N_SIGNALS', 5)]
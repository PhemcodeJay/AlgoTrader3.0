import os
import json
import logging
import requests
import hmac
import hashlib
import time
import uuid
from typing import Dict, Optional, List
from dotenv import load_dotenv
import portalocker
from utils import LEVERAGE

load_dotenv()
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    filename="app.log",
    filemode="a",
    format="%(asctime)s - %(levelname)s - %(message)s",
    encoding="utf-8"
)

class BybitClient:
    def __init__(self):
        self.api_key = os.getenv("BYBIT_API_KEY", "F7aQeUkd3obyUSDeNJ")
        self.api_secret = os.getenv("BYBIT_API_SECRET", "A8WNJSiQodExiy2U2GsKTp2Na5ytSwBlK7iD")
        self.account_type = os.getenv("BYBIT_ACCOUNT_TYPE", "UNIFIED")
        self.real_mode = os.getenv("REAL", "false").lower() == "true"
        self.virtual_mode = os.getenv("VIRTUAL", "true").lower() == "true"
        self.base_url = "https://api.bybit.com"  # Always use mainnet for live market data
        self.is_connected_flag = self.real_mode and not self.virtual_mode and bool(self.api_key and self.api_secret)
        self.capital_file = "capital.json"
        self.virtual_trades_file = "virtual_trades.json"

    def is_connected(self) -> bool:
        return self.is_connected_flag

    def _generate_signature(self, params: Dict, timestamp: str) -> str:
        param_str = timestamp + self.api_key + "5000" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        return hmac.new(self.api_secret.encode('utf-8'), param_str.encode('utf-8'), hashlib.sha256).hexdigest()

    from tenacity import retry, stop_after_attempt, wait_fixed
    @retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
    def get_current_price(self, symbol: str) -> float:
        try:
            url = f"{self.base_url}/v5/market/tickers?category=linear&symbol={symbol}"
            response = requests.get(url).json()
            if response.get("retCode") == 0:
                return float(response["result"]["list"][0]["lastPrice"])
            logger.error(f"Error getting price for {symbol}: {response.get('retMsg')}")
            return 0.0
        except Exception as e:
            logger.error(f"Error getting price for {symbol}: {e}")
            return 0.0

    def get_wallet_balance(self) -> Dict:
        if self.virtual_mode or not self.is_connected():
            logger.info("Using virtual wallet balance from capital.json")
            return self.load_capital("virtual")
        try:
            timestamp = str(int(time.time() * 1000))
            params = {"accountType": self.account_type}
            headers = {
                "X-BAPI-API-KEY": self.api_key,
                "X-BAPI-SIGN": self._generate_signature(params, timestamp),
                "X-BAPI-TIMESTAMP": timestamp,
                "X-BAPI-RECV-WINDOW": "5000"
            }
            url = f"{self.base_url}/v5/account/wallet-balance"
            response = requests.get(url, headers=headers, params=params).json()
            if response.get("retCode") == 0:
                balance = response["result"]["list"][0]
                return {
                    "capital": float(balance.get("totalEquity", 0.0)),
                    "available": float(balance.get("availableBalance", 0.0)),
                    "used": float(balance.get("usedMargin", 0.0)),
                    "start_balance": float(balance.get("totalEquity", 0.0)),
                    "currency": balance.get("accountType", "USDT")
                }
            logger.error(f"Error getting wallet balance: {response.get('retMsg')}")
            return {}
        except Exception as e:
            logger.error(f"Error getting wallet balance: {e}")
            return {}

    def get_tickers(self, category: str = "linear") -> List[Dict]:
        try:
            url = f"{self.base_url}/v5/market/tickers?category={category}"
            response = requests.get(url).json()
            if response.get("retCode") == 0:
                return [
                    {
                        "symbol": ticker["symbol"],
                        "lastPrice": float(ticker["lastPrice"]),
                        "price24hPcnt": float(ticker["price24hPcnt"])
                    }
                    for ticker in response["result"]["list"]
                    if ticker["symbol"].endswith("USDT")
                ]
            logger.error(f"Error getting tickers: {response.get('retMsg')}")
            return []
        except Exception as e:
            logger.error(f"Error getting tickers: {e}")
            return []

    def get_symbols(self) -> List[Dict]:
        try:
            url = f"{self.base_url}/v5/market/instruments-info?category=linear"
            response = requests.get(url).json()
            if response.get("retCode") == 0:
                return [
                    {"symbol": instrument["symbol"]}
                    for instrument in response["result"]["list"]
                    if instrument["symbol"].endswith("USDT")
                ]
            logger.error(f"Error getting symbols: {response.get('retMsg')}")
            return []
        except Exception as e:
            logger.error(f"Error getting symbols: {e}")
            return []

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
    def get_kline(
        self,
        symbol: str,
        interval: str = "60",
        limit: int = 200,
        category: str = "linear"
    ) -> List[Dict]:
        """
        Fetch historical kline (candlestick) data from Bybit.

        Args:
            symbol (str): Trading pair symbol (e.g., "BTCUSDT").
            interval (str): Kline interval ("1","3","5","15","30","60","240","720","D","M","W").
            limit (int): Number of klines (max 200).
            category (str): Market type (linear, spot, inverse, option).

        Returns:
            List[Dict]: OHLCV candles sorted oldest → newest.
        """
        try:
            url = f"{self.base_url}/v5/market/kline"
            params = {
                "category": category,
                "symbol": symbol,
                "interval": interval,
                "limit": str(limit)
            }
            response = requests.get(url, params=params).json()
            if response.get("retCode") == 0:
                candles = [
                    {
                        "timestamp": int(c[0]),
                        "open": float(c[1]),
                        "high": float(c[2]),
                        "low": float(c[3]),
                        "close": float(c[4]),
                        "volume": float(c[5])
                    }
                    for c in response["result"]["list"]
                ]
                # Ensure chronological order (Bybit often returns newest first)
                return sorted(candles, key=lambda x: x["timestamp"])
            logger.error(f"Error fetching kline for {symbol}: {response.get('retMsg')}")
            return []
        except Exception as e:
            logger.error(f"Exception fetching kline for {symbol}: {e}")
            return []

    def place_order(self, symbol: str, side: str, order_type: str, qty: float, price: float = 0.0, stop_loss: Optional[float] = None, take_profit: Optional[float] = None) -> Optional[Dict]:
        try:
            # Validate inputs
            if qty <= 0:
                logger.error(f"Invalid quantity: {qty}")
                return None
            if price < 0 or (order_type == "Limit" and price <= 0):
                logger.error(f"Invalid price for {order_type} order: {price}")
                return None
            if stop_loss is not None and (stop_loss <= 0 or (side in ["Buy", "LONG"] and stop_loss >= price) or (side in ["Sell", "SHORT"] and stop_loss <= price)):
                logger.error(f"Invalid stop loss: {stop_loss} for side {side} and price {price}")
                return None
            if take_profit is not None and (take_profit <= 0 or (side in ["Buy", "LONG"] and take_profit <= price) or (side in ["Sell", "SHORT"] and take_profit >= price)):
                logger.error(f"Invalid take profit: {take_profit} for side {side} and price {price}")
                return None

            if self.virtual_mode or not self.is_connected():
                logger.info(f"Simulating order in virtual mode: {symbol}, {side}, {qty}, price={price}, sl={stop_loss}, tp={take_profit}")
                capital_data = self.load_capital("virtual")
                margin_usdt = qty * price / LEVERAGE if price > 0 else 0.0
                if margin_usdt > capital_data.get("available", 0.0):
                    logger.error(f"Insufficient virtual funds: {margin_usdt} > {capital_data.get('available', 0.0)}")
                    return None
                capital_data["available"] -= margin_usdt
                capital_data["used"] = capital_data.get("used", 0.0) + margin_usdt
                self.save_capital("virtual", capital_data)
                trade_data = {
                    "order_id": str(uuid.uuid4()),
                    "symbol": symbol,
                    "side": side,
                    "qty": qty,
                    "price": price,
                    "stopLoss": stop_loss,
                    "takeProfit": take_profit,
                    "status": "open",
                    "timestamp": time.time()
                }
                virtual_trades = self._load_json_file(self.virtual_trades_file, [])
                virtual_trades.append(trade_data)
                self._save_json_file(self.virtual_trades_file, virtual_trades)
                return trade_data
            timestamp = str(int(time.time() * 1000))
            params = {
                "category": "linear",
                "symbol": symbol,
                "side": side,
                "orderType": order_type,
                "qty": str(qty),
                "price": str(price) if order_type == "Limit" else None,
                "stopLoss": str(stop_loss) if stop_loss is not None else None,
                "takeProfit": str(take_profit) if take_profit is not None else None
            }
            params = {k: v for k, v in params.items() if v is not None}
            headers = {
                "X-BAPI-API-KEY": self.api_key,
                "X-BAPI-SIGN": self._generate_signature(params, timestamp),
                "X-BAPI-TIMESTAMP": timestamp,
                "X-BAPI-RECV-WINDOW": "5000"
            }
            url = f"{self.base_url}/v5/order/create"
            response = requests.post(url, json=params, headers=headers).json()
            if response.get("retCode") == 0:
                return response["result"]
            logger.error(f"Error placing order: {response.get('retMsg')}")
            return None
        except Exception as e:
            logger.error(f"Error placing order: {e}")
            return None

    def close_position(self, symbol: str, side: str, qty: float) -> bool:
        try:
            if self.virtual_mode or not self.is_connected():
                logger.info(f"Simulating close in virtual mode: {symbol}, {side}, {qty}")
                capital_data = self.load_capital("virtual")
                current_price = self.get_current_price(symbol)
                margin_usdt = qty * current_price / LEVERAGE
                capital_data["available"] += margin_usdt
                capital_data["used"] = max(0.0, capital_data.get("used", 0.0) - margin_usdt)
                virtual_trades = self._load_json_file(self.virtual_trades_file, [])
                for trade in virtual_trades:
                    if trade["symbol"] == symbol and trade["side"] == side and trade["status"] == "open" and abs(trade["qty"] - qty) < 1e-6:
                        trade["status"] = "closed"
                        trade["exit_price"] = current_price
                        trade["pnl"] = (current_price - trade["price"]) * qty if side in ["Buy", "LONG"] else (trade["price"] - current_price) * qty
                        trade["close_timestamp"] = time.time()
                        # Check if TP or SL was triggered
                        if trade.get("stopLoss") and (
                            (side in ["Buy", "LONG"] and current_price <= trade["stopLoss"]) or
                            (side in ["Sell", "SHORT"] and current_price >= trade["stopLoss"])
                        ):
                            trade["exit_reason"] = "stop_loss"
                        elif trade.get("takeProfit") and (
                            (side in ["Buy", "LONG"] and current_price >= trade["takeProfit"]) or
                            (side in ["Sell", "SHORT"] and current_price <= trade["takeProfit"])
                        ):
                            trade["exit_reason"] = "take_profit"
                        else:
                            trade["exit_reason"] = "manual"
                        capital_data["capital"] += trade["pnl"]
                        self.save_capital("virtual", capital_data)
                        break
                else:
                    logger.error(f"No matching open virtual trade found for {symbol}, {side}, {qty}")
                    return False
                self._save_json_file(self.virtual_trades_file, virtual_trades)
                return True
            timestamp = str(int(time.time() * 1000))
            params = {
                "category": "linear",
                "symbol": symbol,
                "side": "Sell" if side in ["Buy", "LONG"] else "Buy",
                "orderType": "Market",
                "qty": str(qty)
            }
            headers = {
                "X-BAPI-API-KEY": self.api_key,
                "X-BAPI-SIGN": self._generate_signature(params, timestamp),
                "X-BAPI-TIMESTAMP": timestamp,
                "X-BAPI-RECV-WINDOW": "5000"
            }
            url = f"{self.base_url}/v5/order/create"
            response = requests.post(url, json=params, headers=headers).json()
            if response.get("retCode") == 0:
                return True
            logger.error(f"Error closing position: {response.get('retMsg')}")
            return False
        except Exception as e:
            logger.error(f"Error closing position: {e}")
            return False

    def check_tp_sl(self, symbol: str, side: str, entry_price: float, qty: float, stop_loss: Optional[float], take_profit: Optional[float]) -> Optional[str]:
        try:
            if not stop_loss and not take_profit:
                return None
            current_price = self.get_current_price(symbol)
            if current_price == 0.0:
                logger.error(f"Cannot check TP/SL for {symbol}: Invalid current price")
                return None
            if stop_loss and (
                (side in ["Buy", "LONG"] and current_price <= stop_loss) or
                (side in ["Sell", "SHORT"] and current_price >= stop_loss)
            ):
                return "stop_loss"
            if take_profit and (
                (side in ["Buy", "LONG"] and current_price >= take_profit) or
                (side in ["Sell", "SHORT"] and current_price <= take_profit)
            ):
                return "take_profit"
            return None
        except Exception as e:
            logger.error(f"Error checking TP/SL for {symbol}: {e}")
            return None

    def get_open_pnl(self, symbol: str, side: str, qty: float, entry_price: float) -> float:
        try:
            current_price = self.get_current_price(symbol)
            if current_price == 0.0:
                logger.error(f"Cannot calculate P&L for {symbol}: Invalid current price")
                return 0.0
            return (current_price - entry_price) * qty if side in ["Buy", "LONG"] else (entry_price - current_price) * qty
        except Exception as e:
            logger.error(f"Error calculating open P&L for {symbol}: {e}")
            return 0.0

    def load_capital(self, mode: str) -> Dict:
        try:
            with open(self.capital_file, "r") as f:
                portalocker.lock(f, portalocker.LOCK_SH)
                capital_data = json.load(f)
                portalocker.unlock(f)
                return capital_data.get(mode, {"capital": 100.0, "available": 100.0, "used": 0.0, "start_balance": 100.0, "currency": "USDT"})
        except FileNotFoundError:
            default_capital = {
                "real": {"capital": 0.0, "available": 0.0, "used": 0.0, "start_balance": 0.0, "currency": "USDT"},
                "virtual": {"capital": 100.0, "available": 100.0, "used": 0.0, "start_balance": 100.0, "currency": "USDT"}
            }
            self.save_capital("all", default_capital)
            return default_capital[mode]
        except Exception as e:
            logger.error(f"Error loading capital: {e}")
            return {"capital": 100.0, "available": 100.0, "used": 0.0, "start_balance": 100.0, "currency": "USDT"}

    def save_capital(self, mode: str, capital_data: Dict):
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

    def _load_json_file(self, path: str, default):
        try:
            with open(path, "r") as f:
                portalocker.lock(f, portalocker.LOCK_SH)
                data = json.load(f)
                portalocker.unlock(f)
                return data
        except (FileNotFoundError, PermissionError, json.JSONDecodeError) as e:
            logger.warning(f"Could not read {path}: {e}")
            return default
        except Exception as e:
            logger.error(f"Unexpected error reading {path}: {e}")
            return default

    def _save_json_file(self, path: str, data):
        try:
            with open(path, "w") as f:
                portalocker.lock(f, portalocker.LOCK_EX)
                json.dump(data, f, indent=4)
                f.flush()
                portalocker.unlock(f)
        except (PermissionError, OSError) as e:
            logger.error(f"Could not write {path}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error writing {path}: {e}")

    def safe_float(self, value, default=0.0):
        try:
            if value is None or (isinstance(value, str) and value.strip() == ""):
                return default
            return float(value)
        except (ValueError, TypeError):
            logger.warning(f"Could not convert {value} to float, returning {default}")
            return default
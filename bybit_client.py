import os
import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, List, Any, TYPE_CHECKING
import json
import uuid
import portalocker


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bybit_client.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

PYBIT_AVAILABLE: bool = False

# Default
leverage=10

if TYPE_CHECKING:
    from pybit.unified_trading import HTTP
    HTTPClient = HTTP
else:
    try:
        from pybit.unified_trading import HTTP as HTTPClient
        PYBIT_AVAILABLE = True
    except ImportError:
        logger.warning("pybit not available, running in demo mode")
        PYBIT_AVAILABLE = False
        HTTPClient = Any

from db import db_manager

VIRTUAL_TRADES_FILE = "virtual_trades.json"
CAPITAL_FILE = "capital.json"

import json
import logging
import portalocker

logger = logging.getLogger(__name__)

def _load_json_file(path: str, default):
    try:
        with open(path, "r") as f:
            portalocker.lock(f, portalocker.LOCK_SH)  # Shared lock for reading
            data = json.load(f)
            portalocker.unlock(f)
            return data

    except (FileNotFoundError, PermissionError, json.JSONDecodeError) as e:
        logger.warning(f"Could not read {path}: {e}")
        return default
    except Exception as e:
        logger.error(f"Unexpected error reading {path}: {e}")
        return default

def _save_json_file(path: str, data):
    try:
        with open(path, "w") as f:
            portalocker.lock(f, portalocker.LOCK_EX)  # Exclusive lock for writing
            json.dump(data, f, indent=4)
            f.flush()
            portalocker.unlock(f)

    except (PermissionError, OSError) as e:
        logger.error(f"Could not write {path}: {e}")
    except Exception as e:
        logger.error(f"Unexpected error writing {path}: {e}")


def safe_float(value, default=0.0):
    try:
        if value is None or (isinstance(value, str) and value.strip() == ""):
            return default
        return float(value)
    except (ValueError, TypeError):
        return default

class BybitClient:
    """Bybit client with real mode (pybit) and enhanced virtual mode with trade tracking + PnL simulation."""
    def __init__(self):
        self.testnet = os.getenv("BYBIT_TESTNET", "true").lower() == "true"
        self.account_type = os.getenv("BYBIT_ACCOUNT_TYPE", "UNIFIED").upper()
        self.session = self._connect()
        key_env = "BYBIT_TESTNET_API_KEY" if self.testnet else "BYBIT_API_KEY"
        secret_env = "BYBIT_TESTNET_API_SECRET" if self.testnet else "BYBIT_API_SECRET"
        logger.info(f"Connected to Bybit Mainnet")
        self.api_key = (os.getenv(key_env) or "").strip()
        self.api_secret = (os.getenv(secret_env) or "").strip()
        self.client: Optional[HTTPClient] = None
        self.use_real = False

        if PYBIT_AVAILABLE and self.api_key and self.api_secret:
            try:
                self.client = HTTPClient(
                    testnet=self.testnet,
                    api_key=self.api_key,
                    api_secret=self.api_secret,
                )
                response = self.client.get_server_time()
                if isinstance(response, dict) and response.get("retCode") == 0:
                    logger.info(f" Connected to Bybit Mainnet")
                    self.use_real = True
                else:
                    msg = response.get("retMsg") if isinstance(response, dict) else "Invalid response"
                    logger.error(f"❌ Failed to authenticate: {msg}")
                    self.client = None
            except Exception as e:
                logger.error(f"❌ Failed to initialize Bybit client: {e}")
                self.client = None
        else:
            logger.warning("⚠️ No API credentials or pybit not available, running in virtual mode")

        self._ensure_virtual_storage()

    def _ensure_virtual_storage(self):
        default_capital = {"virtual": {"capital": 100.0, "available": 100.0, "used": 0.0, "currency": "USDT"}}
        capital_data = _load_json_file(CAPITAL_FILE, default_capital)
        if "virtual" not in capital_data:
            capital_data["virtual"] = default_capital["virtual"]
            _save_json_file(CAPITAL_FILE, capital_data)
        trades = _load_json_file(VIRTUAL_TRADES_FILE, [])
        if trades == []:
            _save_json_file(VIRTUAL_TRADES_FILE, trades)

    def _read_virtual_trades(self) -> List[Dict[str, Any]]:
        return _load_json_file(VIRTUAL_TRADES_FILE, [])

    def _write_virtual_trades(self, trades: List[Dict[str, Any]]):
        _save_json_file(VIRTUAL_TRADES_FILE, trades)

    def _read_capital(self) -> Dict[str, Any]:
        return _load_json_file(CAPITAL_FILE, {"virtual": {"capital": 100.0, "available": 100.0, "used": 0.0, "currency": "USDT"}})

    def _write_capital(self, data: Dict[str, Any]):
        _save_json_file(CAPITAL_FILE, data)

    def _connect(self):
        return True  # Placeholder for connection logic

    def is_connected(self) -> bool:
        return self.client is not None

    def get_account_info(self) -> Dict[str, Any]:
        if not self.client:
            return {"accountType": "VIRTUAL", "unifiedMarginStatus": 1}
        try:
            response = self.client.get_account_info()
            if isinstance(response, dict) and response.get("retCode") == 0:
                return response.get("result", {})
            else:
                logger.error(f"Account info error: {response.get('retMsg') if isinstance(response, dict) else 'Invalid response'}")
                return {"error": response.get("retMsg") if isinstance(response, dict) else "Invalid response"}
        except Exception as e:
            logger.error(f"Error getting account info: {e}")
            return {"error": str(e)}

    def get_wallet_balance(self) -> Dict[str, Any]:
        if not self.client:
            return self._get_virtual_balance()
        
        try:
            response = self.client.get_wallet_balance(accountType=self.account_type)

            if isinstance(response, dict) and response.get("retCode") == 0:
                result = response.get("result", {})
                account_list = result.get("list", [])

                if not account_list:
                    logger.warning("No account data returned from Bybit API")
                    return {
                        "totalEquity": 0,
                        "totalWalletBalance": 0,
                        "totalMarginBalance": 0,
                        "totalAvailableBalance": 0,
                        "USDT": {
                            "availableBalance": 0,
                            "walletBalance": 0,
                            "equity": 0,
                        },
                        "error": "No account data"
                    }

                account = account_list[0]
                coins = account.get("coin", [])
                usdt_balance = next((c for c in coins if c.get("coin") == "USDT"), {})

                return {
                    "totalEquity": safe_float(account.get("totalEquity")),
                    "totalWalletBalance": safe_float(account.get("totalWalletBalance")),
                    "totalMarginBalance": safe_float(account.get("totalMarginBalance")),
                    "totalAvailableBalance": safe_float(account.get("totalAvailableBalance")),
                    "USDT": {
                        "availableBalance": safe_float(usdt_balance.get("availableBalance")),
                        "walletBalance": safe_float(usdt_balance.get("walletBalance")),
                        "equity": safe_float(usdt_balance.get("equity")),
                    }
                }
            else:
                msg = response.get("retMsg", "Unknown error") if isinstance(response, dict) else "Invalid response"
                logger.error(f"Wallet balance API error: {msg}")
                return self._get_virtual_balance()

        except Exception as e:
            logger.error(f"Exception getting wallet balance: {str(e)}")
            return self._get_virtual_balance()


    def _get_virtual_balance(self) -> Dict[str, Any]:
        try:
            capital_data = self._read_capital()
            virtual = capital_data.get("virtual", {})
            return {
                "capital": safe_float(virtual.get("capital", 100.0)),
                "available": safe_float(virtual.get("available", 100.0)),
                "used": safe_float(virtual.get("used", 0.0)),
                "start_balance": safe_float(virtual.get("start_balance", 100.0)),
                "currency": virtual.get("currency", "USDT")
            }
        except Exception as e:
            logger.warning(f"Could not read capital.json: {e}")
            return {
                "capital": 100.0,
                "available": 100.0,
                "used": 0.0,
                "start_balance": 100.0,
                "currency": "USDT"
            }

    def get_symbols(self) -> List[Dict[str, Any]]:
        if not self.client:
            return [
                {"symbol": "BTCUSDT", "category": "linear", "status": "Trading"},
                {"symbol": "ETHUSDT", "category": "linear", "status": "Trading"},
                {"symbol": "DOGEUSDT", "category": "linear", "status": "Trading"},
                {"symbol": "SOLUSDT", "category": "linear", "status": "Trading"},
                {"symbol": "XRPUSDT", "category": "linear", "status": "Trading"},
            ]
        try:
            response = self.client.get_instruments_info(category="linear")
            if isinstance(response, dict) and response.get("retCode") == 0:
                return response.get("result", {}).get("list", [])[:100]
            else:
                logger.error(f"Symbols error: {response.get('retMsg') if isinstance(response, dict) else 'Invalid response'}")
                return []
        except Exception as e:
            logger.error(f"Error getting symbols: {e}")
            return []

    def get_current_price(self, symbol: str) -> float:
        if self.client:
            try:
                response = self.client.get_tickers(category="linear", symbol=symbol)
                if isinstance(response, dict) and response.get("retCode") == 0:
                    tickers = response.get("result", {}).get("list", [])
                    if tickers:
                        price = safe_float(tickers[0].get("lastPrice", 0))
                        if price > 0:
                            logger.debug(f"✅ Got authenticated price for {symbol}: ${price}")
                            return price
                logger.warning(f"Failed to get price from Bybit API for {symbol}")
            except Exception as e:
                logger.warning(f"Authenticated API failed for {symbol}: {e}")
        
        # Fallback for virtual mode
        mock_prices = {
            "BTCUSDT": 60000.0,
            "ETHUSDT": 2500.0,
            "DOGEUSDT": 0.10,
            "SOLUSDT": 150.0,
            "XRPUSDT": 0.60
        }
        price = mock_prices.get(symbol, 0.0)
        if price > 0:
            logger.debug(f"✅ Got mock price for {symbol}: ${price}")
            return price
        logger.error(f"No price available for {symbol}")
        return 0.0

    def place_order(self, symbol: str, side: str, order_type: str, qty: float,
                    price: float = 0.0, time_in_force: str = "GTC",
                    stop_loss: Optional[float] = None, take_profit: Optional[float] = None,
                    leverage: Optional[int] = None) -> Optional[Dict[str, Any]]:
        # Normalize side
        side = "Buy" if side.upper() == "LONG" else "Sell" if side.upper() == "SHORT" else side
        if side not in ["Buy", "Sell"]:
            logger.error(f"Invalid side: {side}")
            return None

        # Validate inputs
        if qty <= 0 or (order_type == "Limit" and price <= 0):
            logger.error(f"Invalid order parameters: qty={qty}, price={price}")
            return None

        # Virtual mode
        if not self.client:
            # Validate balance
            capital_data = self._read_capital()
            virtual_cap = capital_data.get("virtual", {"capital": 100.0, "available": 100.0, "used": 0.0})
            margin_required = (qty * (price or self.get_current_price(symbol))) / (leverage or 1)
            if margin_required > virtual_cap["available"]:
                logger.error(f"Insufficient virtual balance: {margin_required} required, {virtual_cap['available']} available")
                return None

            virtual_price = price or self.get_current_price(symbol)
            if virtual_price <= 0:
                logger.error(f"Invalid price for {symbol}: {virtual_price}")
                return None

            virtual_tp = take_profit if take_profit and take_profit > 0 else (virtual_price * 1.30 if side == "Buy" else virtual_price * 0.70)
            virtual_sl = stop_loss if stop_loss and stop_loss > 0 else (virtual_price * 0.90 if side == "Buy" else virtual_price * 1.10)

            trade_id = f"virtual_{uuid.uuid4().hex}"
            now_ms = int(time.time() * 1000)

            trade = {
                "id": trade_id,
                "symbol": symbol,
                "side": side,
                "size": float(qty),
                "entryPrice": float(virtual_price),
                "entryTime": now_ms,
                "status": "Open",
                "order_type": order_type,
                "stopLoss": float(virtual_sl),
                "takeProfit": float(virtual_tp),
                "close_price": None,
                "close_time": None,
                "realized_pnl": None,
                "leverage": leverage or 1
            }

            # Update virtual capital
            virtual_cap["used"] = safe_float(virtual_cap.get("used", 0.0)) + margin_required
            virtual_cap["available"] = safe_float(virtual_cap.get("available", 100.0)) - margin_required
            self._write_capital({"virtual": virtual_cap})

            # Persist trade
            trades = self._read_virtual_trades()
            trades.append(trade)
            self._write_virtual_trades(trades)

            # Save to DB
            try:
                if hasattr(db_manager, "save_trade"):
                    db_manager.save_trade(trade)
            except Exception as e:
                logger.debug(f"Could not save virtual trade to DB: {e}")

            logger.info(f"[VIRTUAL] Opened {side} {symbol} qty={qty} at {virtual_price} (id={trade_id})")
            self.update_unrealized_positions()

            return {
                "symbol": symbol,
                "side": side,
                "qty": float(qty),
                "price": float(virtual_price),
                "order_id": trade_id,
                "create_time": now_ms,
                "status": "Filled",
                "orderType": order_type,
                "stopLoss": float(virtual_sl),
                "takeProfit": float(virtual_tp),
                "leverage": leverage or 1
            }

        # Real mode
        try:
            params = {
                "category": "linear",
                "symbol": symbol,
                "side": side,
                "orderType": order_type,
                "qty": str(float(qty)),
                "timeInForce": time_in_force,
            }
            if order_type == "Limit" and price > 0:
                params["price"] = str(float(price))
            if stop_loss and stop_loss > 0:
                params["stopLoss"] = str(float(stop_loss))
            if take_profit and take_profit > 0:
                params["takeProfit"] = str(float(take_profit))
            if leverage and leverage > 0:
                params["leverage"] = str(int(leverage))

            response = self.client.place_order(**params)
            if isinstance(response, dict) and response.get("retCode") == 0:
                result = response.get("result", {})
                order_id = result.get("orderId", f"real_{int(time.time() * 1000)}")
                logger.info(f"[REAL] Placed order {order_id} {side} {symbol} qty={qty} price={price}")
                return {
                    "symbol": symbol,
                    "side": side,
                    "qty": float(qty),
                    "price": price,
                    "order_id": order_id,
                    "create_time": int(time.time() * 1000),
                    "status": "Created",
                    "orderType": order_type,
                    "stopLoss": safe_float(stop_loss),
                    "takeProfit": safe_float(take_profit),
                    "leverage": leverage or 1
                }
            else:
                logger.error(f"Order placement error: {response.get('retMsg', 'Unknown error') if isinstance(response, dict) else 'Invalid response'}")
                return None
        except Exception as e:
            logger.error(f"Error placing order: {e}")
            return None

    def get_positions(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        self.monitor_sl_tp()
        if not self.client:
            trades = self._read_virtual_trades()
            open_trades = [t for t in trades if t.get("status") == "Open"]
            positions = []
            for t in open_trades:
                if symbol and t.get("symbol") != symbol:
                    continue
                current_price = self.get_current_price(t["symbol"])
                unrealized = self._compute_unrealized_for_trade(t, current_price)
                pos = {
                    "id": t["id"],
                    "symbol": t["symbol"],
                    "side": t["side"],
                    "size": t["size"],
                    "entryPrice": t["entryPrice"],
                    "entryTime": t["entryTime"],
                    "unrealizedPnl": unrealized,
                    "currentPrice": current_price,
                    "stopLoss": t.get("stopLoss"),
                    "takeProfit": t.get("takeProfit"),
                    "leverage": t.get("leverage", 1)
                }
                positions.append(pos)
            return positions
        try:
            params = {"category": "linear"}
            if symbol is not None:
                params["symbol"] = symbol
            response = self.client.get_positions(**params)
            if isinstance(response, dict) and response.get("retCode") == 0:
                return response.get("result", {}).get("list", [])
            else:
                logger.error(f"Positions error: {response.get('retMsg', 'Unknown error') if isinstance(response, dict) else 'Invalid response'}")
                return []
        except Exception as e:
            logger.error(f"Error getting positions: {e}")
            return []

    def close_position(self, symbol: str, side: str, qty: Optional[str] = None) -> Optional[Dict[str, Any]]:
        # Normalize side
        side = "Buy" if side.upper() == "LONG" else "Sell" if side.upper() == "SHORT" else side
        if side not in ["Buy", "Sell"]:
            logger.error(f"Invalid side for closing position: {side}")
            return None

        # Virtual mode
        if not self.client:
            trades = self._read_virtual_trades()
            matching = [t for t in trades if t.get("symbol") == symbol and t.get("status") == "Open" and t.get("side") == side]
            if not matching:
                logger.warning(f"No open virtual position found for {symbol} with side {side}")
                return None

            close_qty = None
            try:
                if qty is not None:
                    close_qty = safe_float(qty)
            except Exception:
                logger.error(f"Invalid qty specified for closing: {qty}")
                return None

            now_ms = int(time.time() * 1000)
            closed_results = []
            capital_data = self._read_capital()
            virtual_cap = capital_data.get("virtual", {"capital": 100.0, "available": 100.0, "used": 0.0})
            remaining_qty = close_qty
            for t in matching:
                if remaining_qty is not None and remaining_qty <= 0:
                    break
                qty_to_close = t["size"] if remaining_qty is None else min(t["size"], remaining_qty)
                close_price = self.get_current_price(symbol)
                if close_price <= 0:
                    logger.error(f"Invalid close price for {symbol}: {close_price}")
                    continue

                margin_used = (qty_to_close * t["entryPrice"]) / t.get("leverage", 1)
                if t["side"] == "Buy":
                    pnl = (close_price - t["entryPrice"]) * qty_to_close
                else:
                    pnl = (t["entryPrice"] - close_price) * qty_to_close

                if qty_to_close >= t["size"]:
                    t["status"] = "Closed"
                    t["close_price"] = float(close_price)
                    t["close_time"] = now_ms
                    t["realized_pnl"] = float(pnl)
                else:
                    t["size"] = float(t["size"] - qty_to_close)
                    closed_trade = {
                        "id": f"{t['id']}_partial_{uuid.uuid4().hex}",
                        "symbol": t["symbol"],
                        "side": t["side"],
                        "size": float(qty_to_close),
                        "entryPrice": t["entryPrice"],
                        "entryTime": t["entryTime"],
                        "status": "Closed",
                        "order_type": t.get("order_type"),
                        "stopLoss": t.get("stopLoss"),
                        "takeProfit": t.get("takeProfit"),
                        "close_price": float(close_price),
                        "close_time": now_ms,
                        "realized_pnl": float(pnl),
                        "leverage": t.get("leverage", 1)
                    }
                    trades.append(closed_trade)

                virtual_cap["capital"] = safe_float(virtual_cap.get("capital", 0.0)) + float(pnl)
                virtual_cap["used"] = safe_float(virtual_cap.get("used", 0.0)) - margin_used
                virtual_cap["available"] = safe_float(virtual_cap.get("capital", 0.0)) - virtual_cap["used"]
                if remaining_qty is not None:
                    remaining_qty -= qty_to_close
                closed_results.append({
                    "symbol": symbol,
                    "close_price": float(close_price),
                    "qty_closed": float(qty_to_close),
                    "pnl": float(pnl)
                })

            self._write_virtual_trades(trades)
            self._write_capital({"virtual": virtual_cap})
            try:
                if hasattr(db_manager, "save_trade"):
                    for cr in closed_results:
                        db_manager.save_trade({
                            "symbol": symbol,
                            "side": side,
                            "size": cr["qty_closed"],
                            "close_price": cr["close_price"],
                            "pnl": cr["pnl"],
                            "close_time": now_ms,
                            "status": "Closed",
                            "leverage": leverage or 10,
                        })
            except Exception as e:
                logger.debug(f"Could not save closed virtual trade to DB: {e}")

            self.update_unrealized_positions()
            logger.info(f"[VIRTUAL] Closed {len(closed_results)} chunks for {symbol}. Details: {closed_results}")
            return {
                "symbol": symbol,
                "closed": closed_results,
                "status": "Closed",
                "close_time": now_ms
            }

        # Real mode
        try:
            positions = self.get_positions(symbol)
            position = next((p for p in positions if p.get("symbol") == symbol and p.get("side") == side), None)
            close_qty = None
            if qty is not None:
                close_qty = safe_float(qty)
            elif position:
                close_qty = safe_float(position.get("size", 0))
            if close_qty is None or close_qty <= 0:
                logger.error(f"Could not determine qty to close for {symbol}")
                return None
            opposite_side = "Sell" if side == "Buy" else "Buy"
            return self.place_order(
                symbol=symbol,
                side=opposite_side,
                order_type="Market",
                qty=close_qty,
                time_in_force="IOC"
            )
        except Exception as e:
            logger.error(f"Error closing position: {e}")
            return None

    def _compute_unrealized_for_trade(self, trade: Dict[str, Any], current_price: float) -> float:
        try:
            qty = safe_float(trade.get("size", 0))
            entry = safe_float(trade.get("entryPrice", 0))
            if trade.get("side") == "Buy":
                return (current_price - entry) * qty
            else:
                return (entry - current_price) * qty
        except Exception as e:
            logger.debug(f"Could not compute unrealized for trade {trade.get('id')}: {e}")
            return 0.0

    def update_unrealized_positions(self):
        self.monitor_sl_tp()
        trades = self._read_virtual_trades()
        changed = False
        for t in trades:
            if t.get("status") != "Open":
                continue
            current_price = self.get_current_price(t["symbol"])
            unreal = self._compute_unrealized_for_trade(t, current_price)
            if t.get("unrealized_pnl") != unreal:
                t["unrealized_pnl"] = unreal
                changed = True
        if changed:
            self._write_virtual_trades(trades)

    def monitor_sl_tp(self):
        if self.client:
            return
        trades = self._read_virtual_trades()
        updated_trades = []
        closed = []
        now_ms = int(time.time() * 1000)
        capital_data = self._read_capital()
        virtual_cap = capital_data.get("virtual", {"capital": 100.0, "available": 100.0, "used": 0.0})
        for t in trades:
            if t["status"] != "Open":
                updated_trades.append(t)
                continue
            current = self.get_current_price(t["symbol"])
            sl = safe_float(t.get("stopLoss", 0))
            tp = safe_float(t.get("takeProfit", 0))
            hit_sl = False
            hit_tp = False
            if t["side"] == "Buy":
                if sl > 0 and current <= sl:
                    hit_sl = True
                elif tp > 0 and current >= tp:
                    hit_tp = True
            else:
                if sl > 0 and current >= sl:
                    hit_sl = True
                elif tp > 0 and current <= tp:
                    hit_tp = True
            if hit_sl or hit_tp:
                close_price = sl if hit_sl else tp if hit_tp else current
                qty = safe_float(t["size"])
                margin_used = (qty * t["entryPrice"]) / t.get("leverage", 1)
                if t["side"] == "Buy":
                    pnl = (close_price - t["entryPrice"]) * qty
                else:
                    pnl = (t["entryPrice"] - close_price) * qty
                t["status"] = "Closed"
                t["close_price"] = close_price
                t["close_time"] = now_ms
                t["realized_pnl"] = pnl
                virtual_cap["capital"] += pnl
                virtual_cap["used"] -= margin_used
                virtual_cap["available"] = virtual_cap["capital"] - virtual_cap["used"]
                closed.append(t)
                updated_trades.append(t)
                try:
                    if hasattr(db_manager, "save_trade"):
                        db_manager.save_trade(t)
                except Exception as e:
                    logger.debug(f"Could not save closed virtual trade to DB: {e}")
            else:
                updated_trades.append(t)
        if closed:
            self._write_virtual_trades(updated_trades)
            self._write_capital({"virtual": virtual_cap})
            logger.info(f"[VIRTUAL] Closed {len(closed)} trades due to SL/TP hits.")
        return {"closed": len(closed)}

    def get_daily_pnl(self) -> float:
        if not self.client:
            try:
                trades = self._read_virtual_trades()
                utc_today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
                start_ms = int(utc_today.timestamp() * 1000)
                total = 0.0
                for t in trades:
                    if t.get("status") != "Closed":
                        continue
                    close_time = t.get("close_time")
                    if close_time and int(close_time) >= start_ms:
                        pnl = safe_float(t.get("realized_pnl", 0.0))
                        total += pnl
                return total
            except Exception as e:
                logger.error(f"Error computing virtual daily pnl: {e}")
                return 0.0
        try:
            today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            start_time = int(today.timestamp() * 1000)
            response = self.client.get_closed_pnl(category="linear", startTime=start_time)
            if isinstance(response, dict) and response.get("retCode") == 0:
                pnl_list = response.get("result", {}).get("list", [])
                total_pnl = sum(safe_float(pnl.get("closedPnl", 0)) for pnl in pnl_list)
                return total_pnl
            else:
                logger.error(f"Daily P&L error: {response.get('retMsg', 'Unknown error') if isinstance(response, dict) else 'Invalid response'}")
                return 0.0
        except Exception as e:
            logger.error(f"Error getting daily P&L: {e}")
            return 0.0

    def get_portfolio_unrealized(self) -> Dict[str, Any]:
        self.monitor_sl_tp()
        if not self.client:
            trades = self._read_virtual_trades()
            open_trades = [t for t in trades if t.get("status") == "Open"]
            total_unreal = 0.0
            by_symbol = {}
            for t in open_trades:
                cur = self.get_current_price(t["symbol"])
                unreal = self._compute_unrealized_for_trade(t, cur)
                total_unreal += unreal
                by_symbol.setdefault(t["symbol"], 0.0)
                by_symbol[t["symbol"]] += unreal
            return {"total_unrealized": total_unreal, "by_symbol": by_symbol}
        try:
            positions = self.get_positions()
            total = 0.0
            by_symbol = {}
            for p in positions:
                unreal = safe_float(p.get("unrealisedPnl", p.get("unrealizedPnl", 0)))
                if not unreal:
                    size = safe_float(p.get("size", 0))
                    entry = safe_float(p.get("entryPrice", 0))
                    cur = self.get_current_price(p.get("symbol"))
                    if p.get("side") == "Buy":
                        unreal = (cur - entry) * size
                    else:
                        unreal = (entry - cur) * size
                by_symbol.setdefault(p.get("symbol"), 0.0)
                by_symbol[p.get("symbol")] += unreal
                total += unreal
            return {"total_unrealized": total, "by_symbol": by_symbol}
        except Exception as e:
            logger.debug(f"Could not compute real unrealized: {e}")
            return {"total_unrealized": 0.0, "by_symbol": {}}

    def dump_virtual_state(self) -> Dict[str, Any]:
        return {
            "capital": self._read_capital(),
            "trades": self._read_virtual_trades()
        }

    def get_tickers(self, category: str = "linear") -> List[Dict[str, Any]]:
        if not self.client:
            return [
                {"symbol": "BTCUSDT", "lastPrice": "100000.0"},
                {"symbol": "ETHUSDT", "lastPrice": "4500.0"},
                {"symbol": "DOGEUSDT", "lastPrice": "0.20"},
                {"symbol": "SOLUSDT", "lastPrice": "190.0"},
                {"symbol": "XRPUSDT", "lastPrice": "1.60"},
            ]
        try:
            response = self.client.get_tickers(category=category)
            if isinstance(response, dict) and response.get("retCode") == 0:
                return response.get("result", {}).get("list", [])
            logger.error(f"Error getting tickers: {response.get('retMsg', 'Unknown error') if isinstance(response, dict) else 'Invalid response'}")
            return []
        except Exception as e:
            logger.error(f"Error getting tickers: {e}")
            return []
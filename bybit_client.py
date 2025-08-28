import os
import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, List, Any, TYPE_CHECKING
import json
import uuid

# Configure logging
logging.basicConfig(level=logging.INFO, encoding="utf-8")
logger = logging.getLogger(__name__)

PYBIT_AVAILABLE: bool = False

if TYPE_CHECKING:
    # Only used for type hints; Pylance will see the real class
    from pybit.unified_trading import HTTP
    HTTPClient = HTTP
else:
    try:
        from pybit.unified_trading import HTTP as HTTPClient
        PYBIT_AVAILABLE = True
    except ImportError:
        logger.warning("pybit not available, running in demo mode")
        PYBIT_AVAILABLE = False
        HTTPClient = Any  # fallback so it's always callable

# Import db for optional persistence / PnL retrieval
from db import db

VIRTUAL_TRADES_FILE = "virtual_trades.json"
CAPITAL_FILE = "capital.json"


def _load_json_file(path: str, default):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except Exception as e:
        logger.warning(f"Could not read {path}: {e}")
        return default


def _save_json_file(path: str, data):
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)
    except Exception as e:
        logger.error(f"Could not write {path}: {e}")


class BybitClient:
    """Bybit client with real mode (pybit) and enhanced virtual mode with trade tracking + PnL simulation."""
    def __init__(self):
        self.testnet = os.getenv("BYBIT_TESTNET", "true").lower() == "true"
        self.account_type = os.getenv("BYBIT_ACCOUNT_TYPE", "UNIFIED").upper()  # Normalize to upper case, e.g., "CONTRACT"

        key_env = "BYBIT_TESTNET_API_KEY" if self.testnet else "BYBIT_API_KEY"
        secret_env = "BYBIT_TESTNET_API_SECRET" if self.testnet else "BYBIT_API_SECRET"

        self.api_key = (os.getenv(key_env) or "").strip()
        self.api_secret = (os.getenv(secret_env) or "").strip()

        # Proper typing: Optional[HTTPClient]
        self.client: Optional[HTTPClient] = None
        self.use_real = False

        if PYBIT_AVAILABLE and self.api_key and self.api_secret:
            try:
                if not self.api_key or not self.api_secret:
                    raise ValueError("API key or secret is empty")

                # Only instantiate if HTTPClient (real pybit) is available
                self.client = HTTPClient(
                    testnet=self.testnet,
                    api_key=self.api_key,
                    api_secret=self.api_secret,
                )

                response = self.client.get_server_time() if self.client else None

                if isinstance(response, dict) and response.get("retCode") == 0:
                    logger.info(f"✅ Connected to Bybit {'Testnet' if self.testnet else 'Mainnet'}")
                    self.use_real = True
                else:
                    msg = response.get("retMsg") if isinstance(response, dict) else "Invalid response"
                    logger.error(f"❌ Failed to authenticate: {msg}")
                    self.client = None

            except Exception as e:
                logger.error(f"❌ Failed to initialize Bybit client: {e}")
                self.client = None
        else:
            logger.warning("⚠️ No API credentials or pybit not available, running in virtual mode with live market data")

        # Ensure virtual storage exists
        self._ensure_virtual_storage()

    # -------------------------
    # Virtual storage utilities
    # -------------------------
    def _ensure_virtual_storage(self):
        # Create default capital.json if missing
        default_capital = {"virtual": {"capital": 100.0, "available": 100.0}}
        capital_data = _load_json_file(CAPITAL_FILE, default_capital)
        # sanitize
        if "virtual" not in capital_data:
            capital_data["virtual"] = default_capital["virtual"]
            _save_json_file(CAPITAL_FILE, capital_data)

        # Create virtual_trades.json if missing
        trades = _load_json_file(VIRTUAL_TRADES_FILE, [])
        if trades == []:
            _save_json_file(VIRTUAL_TRADES_FILE, trades)

    def _read_virtual_trades(self) -> List[Dict[str, Any]]:
        return _load_json_file(VIRTUAL_TRADES_FILE, [])

    def _write_virtual_trades(self, trades: List[Dict[str, Any]]):
        _save_json_file(VIRTUAL_TRADES_FILE, trades)

    def _read_capital(self) -> Dict[str, Any]:
        return _load_json_file(CAPITAL_FILE, {"virtual": {"capital": 100.0, "available": 100.0}})

    def _write_capital(self, data: Dict[str, Any]):
        _save_json_file(CAPITAL_FILE, data)

    # -------------------------
    # Connection helpers
    # -------------------------
    def is_connected(self) -> bool:
        return self.client is not None

    # -------------------------
    # Account / Balance
    # -------------------------
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
                    return {"error": "No account data"}

                account = account_list[0]
                coins = account.get("coin", [])
                usdt_balance = next((c for c in coins if c.get("coin") == "USDT"), {})

                return {
                    "totalEquity": float(account.get("totalEquity", 0)),
                    "totalWalletBalance": float(account.get("totalWalletBalance", 0)),
                    "totalMarginBalance": float(account.get("totalMarginBalance", 0)),
                    "totalAvailableBalance": float(account.get("totalAvailableBalance", 0)),
                    "USDT": {
                        "availableBalance": float(usdt_balance.get("availableBalance", 0)),
                        "walletBalance": float(usdt_balance.get("walletBalance", 0)),
                        "equity": float(usdt_balance.get("equity", 0)),
                    }
                }

            else:
                msg = response.get("retMsg", "Unknown error") if isinstance(response, dict) else "Invalid response"
                logger.error(f"Wallet balance API error: {msg}")
                return self._get_virtual_balance()

        except Exception as e:
            safe_msg = str(e).encode('utf-8', errors='replace').decode('utf-8')
            logger.error(f"Exception getting wallet balance: {safe_msg}")
            return self._get_virtual_balance()

    def _get_virtual_balance(self) -> Dict[str, Any]:
        try:
            capital_data = self._read_capital()
            virtual = capital_data.get("virtual", {})

            return {
                "capital": float(virtual.get("capital", 100.0)),
                "available": float(virtual.get("available", 100.0)),
                "used": float(virtual.get("used", 0.0)),
                "start_balance": float(virtual.get("start_balance", 100.0)),
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

    # -------------------------
    # Market data helpers
    # -------------------------
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
                        price = float(tickers[0].get("lastPrice", 0))
                        if price > 0:
                            logger.debug(f"✅ Got authenticated price for {symbol}: ${price}")
                            return price
            except Exception as e:
                logger.warning(f"Authenticated API failed for {symbol}: {e}")

        # Fallback to public
        from utils import get_current_price
        price = get_current_price(symbol)
        logger.debug(f"✅ Got public API price for {symbol}: ${price}")
        return price

    # -------------------------
    # Order placement
    # -------------------------
    def place_order(self, symbol: str, side: str, order_type: str, qty: float,
                    price: float = 0.0, time_in_force: str = "GTC",
                    stop_loss: Optional[float] = None, take_profit: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """
        Place a trading order.
        In virtual mode: simulate immediate fill and create a virtual position + persist it.
        In real mode: call pybit place_order and return structured dict (minimal fields).
        """

        # --- Virtual mode ---
        if not self.client:
            # Determine entry price
            virtual_price = price or self.get_current_price(symbol)

            # Determine TP/SL from inputs or fallback behavior
            virtual_tp = take_profit if take_profit is not None and take_profit > 0 else \
                (virtual_price * 1.30 if side == "Buy" else virtual_price * 0.70)
            virtual_sl = stop_loss if stop_loss is not None and stop_loss > 0 else \
                (virtual_price * 0.90 if side == "Buy" else virtual_price * 1.10)

            trade_id = f"virtual_{uuid.uuid4().hex}"
            now_ms = int(time.time() * 1000)

            # Simulate immediate fill and open a position
            trade = {
                "id": trade_id,
                "symbol": symbol,
                "side": side,
                "qty": float(qty),
                "entry_price": float(virtual_price),
                "entry_time": now_ms,
                "status": "Open",  # Open until closed
                "order_type": order_type,
                "stopLoss": float(virtual_sl),
                "takeProfit": float(virtual_tp),
                "close_price": None,
                "close_time": None,
                "realized_pnl": None  # updated on close
            }

            # Persist trade
            trades = self._read_virtual_trades()
            trades.append(trade)
            self._write_virtual_trades(trades)

            # Optionally persist to DB (non-blocking)
            try:
                if hasattr(db, "save_trade"):
                    db.save_trade(trade)
            except Exception as e:
                logger.debug(f"Could not save virtual trade to DB: {e}")

            logger.info(f"[VIRTUAL] Opened {side} {symbol} qty={qty} at {virtual_price} (id={trade_id})")
            # Update unrealized immediately
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
                "takeProfit": float(virtual_tp)
            }

        # --- Real mode ---
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

            effective_price = price if price > 0 else self.get_current_price(symbol)
            if effective_price <= 0:
                logger.error(f"Invalid price for {symbol}: {effective_price}")
                return None

            final_tp = take_profit if take_profit is not None and take_profit > 0 else \
                effective_price * (1.015 if side == "Buy" else 0.985)
            final_sl = stop_loss if stop_loss is not None and stop_loss > 0 else \
                effective_price * (0.985 if side == "Buy" else 1.015)

            # Fallbacks (30% TP / 10% SL)
            if final_tp <= 0 or (side == "Buy" and final_tp <= effective_price) or (side == "Sell" and final_tp >= effective_price):
                final_tp = effective_price * (1.30 if side == "Buy" else 0.70)
            if final_sl <= 0 or (side == "Buy" and final_sl >= effective_price) or (side == "Sell" and final_sl <= effective_price):
                final_sl = effective_price * (0.90 if side == "Buy" else 1.10)

            params["stopLoss"] = str(float(final_sl))
            params["takeProfit"] = str(float(final_tp))

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
                    "stopLoss": final_sl,
                    "takeProfit": final_tp
                }
            else:
                logger.error(f"Order placement error: {response.get('retMsg', 'Unknown error') if isinstance(response, dict) else 'Invalid response'}")
                return None

        except Exception as e:
            logger.error(f"Error placing order: {e}")
            return None

    # -------------------------
    # Positions
    # -------------------------
    def get_positions(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Return open positions.
        - Real mode: proxy to Bybit get_positions.
        - Virtual mode: return open virtual trades with current unrealized PnL.
        """
        self.monitor_sl_tp()  # Ensure SL/TP are checked before getting positions

        if not self.client:
            # Return open virtual trades
            trades = self._read_virtual_trades()
            open_trades = [t for t in trades if t.get("status") == "Open"]
            # Enrich with unrealized PnL and current price
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
                    "size": t["qty"],
                    "entryPrice": t["entry_price"],
                    "entryTime": t["entry_time"],
                    "unrealizedPnl": unrealized,
                    "currentPrice": current_price,
                    "stopLoss": t.get("stopLoss"),
                    "takeProfit": t.get("takeProfit")
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

    # -------------------------
    # Close position
    # -------------------------
    def close_position(self, symbol: str, side: str, qty: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Close position by placing opposite order.
        - Virtual: close matching open virtual trade(s) and realize PnL, update capital.json
        - Real: place opposite Market order (IOC) as before.
        """
        # Virtual mode
        if not self.client:
            trades = self._read_virtual_trades()
            # Find open trades matching symbol & side
            # side param is current position side (Buy or Sell). We close by doing opposite.
            matching = [t for t in trades if t.get("symbol") == symbol and t.get("status") == "Open"]
            if not matching:
                logger.warning(f"No open virtual position found for {symbol}")
                return None

            # If qty specified, close partially; else close all matching trades
            close_qty = None
            try:
                if qty is not None:
                    close_qty = float(qty)
            except Exception:
                logger.error(f"Invalid qty specified for closing: {qty}")
                return None

            now_ms = int(time.time() * 1000)
            closed_results = []
            capital_data = self._read_capital()
            virtual_cap = capital_data.get("virtual", {"capital": 100.0, "available": 100.0})
            # iterate in FIFO order
            remaining_qty = close_qty
            for t in matching:
                if remaining_qty is not None and remaining_qty <= 0:
                    break

                qty_to_close = t["qty"] if remaining_qty is None else min(t["qty"], remaining_qty)

                # compute close price = current market price
                close_price = self.get_current_price(symbol)

                # PnL calculation: for Buy: (close - entry) * qty, for Sell: (entry - close) * qty
                if t["side"] == "Buy":
                    pnl = (close_price - t["entry_price"]) * qty_to_close
                else:
                    pnl = (t["entry_price"] - close_price) * qty_to_close

                # Realize pnl and update the trade
                if qty_to_close >= t["qty"]:
                    # fully close trade
                    t["status"] = "Closed"
                    t["close_price"] = float(close_price)
                    t["close_time"] = now_ms
                    t["realized_pnl"] = float(pnl)
                else:
                    # partial close: reduce qty and create a new closed record
                    t["qty"] = float(t["qty"] - qty_to_close)
                    closed_trade = {
                        "id": f"{t['id']}_partial_{uuid.uuid4().hex}",
                        "symbol": t["symbol"],
                        "side": t["side"],
                        "qty": float(qty_to_close),
                        "entry_price": t["entry_price"],
                        "entry_time": t["entry_time"],
                        "status": "Closed",
                        "order_type": t.get("order_type"),
                        "stopLoss": t.get("stopLoss"),
                        "takeProfit": t.get("takeProfit"),
                        "close_price": float(close_price),
                        "close_time": now_ms,
                        "realized_pnl": float(pnl)
                    }
                    trades.append(closed_trade)

                # Update virtual capital
                virtual_cap["capital"] = float(virtual_cap.get("capital", 0.0)) + float(pnl)
                # adjust available as well (simple model)
                virtual_cap["available"] = float(virtual_cap.get("available", virtual_cap["capital"]))

                if remaining_qty is not None:
                    remaining_qty -= qty_to_close

                closed_results.append({
                    "symbol": symbol,
                    "close_price": float(close_price),
                    "qty_closed": float(qty_to_close),
                    "pnl": float(pnl)
                })

            # persist changes
            self._write_virtual_trades(trades)
            self._write_capital({"virtual": virtual_cap})

            # Optionally persist closed trades to DB
            try:
                if hasattr(db, "save_trade"):
                    for cr in closed_results:
                        db.save_trade({
                            "symbol": symbol,
                            "side": side,
                            "qty": cr["qty_closed"],
                            "close_price": cr["close_price"],
                            "pnl": cr["pnl"],
                            "close_time": int(time.time() * 1000)
                        })
            except Exception as e:
                logger.debug(f"Could not save closed virtual trade to DB: {e}")

            # Update unrealized cache
            self.update_unrealized_positions()

            logger.info(f"[VIRTUAL] Closed {len(closed_results)} chunks for {symbol}. Details: {closed_results}")
            # return summary
            return {
                "symbol": symbol,
                "closed": closed_results,
                "status": "Closed",
                "close_time": int(time.time() * 1000)
            }

        # Real mode
        try:
            # Get position from Bybit to determine size if needed
            positions = self.get_positions(symbol)
            position = None
            if positions:
                # pick first position matching
                position = next((p for p in positions if p.get("symbol") == symbol), None)
            close_qty = None
            if qty is not None:
                try:
                    close_qty = float(qty)
                except Exception:
                    logger.error(f"Invalid quantity for closing position: {qty}")
                    return None
            else:
                if position:
                    close_qty = float(position.get("size", 0))

            if close_qty is None or close_qty <= 0:
                logger.error(f"Could not determine qty to close for {symbol}")
                return None

            current_side = position.get("side", "") if position else side
            opposite_side = "Sell" if current_side == "Buy" else "Buy"
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

    # -------------------------
    # PnL simulation helpers
    # -------------------------
    def _compute_unrealized_for_trade(self, trade: Dict[str, Any], current_price: float) -> float:
        """
        Compute unrealized PnL in USDT for a single virtual trade.
        Uses simple formula: (current - entry) * qty for long; (entry - current) * qty for short.
        """
        try:
            qty = float(trade.get("qty", 0))
            entry = float(trade.get("entry_price", 0))
            if trade.get("side") == "Buy":
                return (float(current_price) - entry) * qty
            else:
                return (entry - float(current_price)) * qty
        except Exception as e:
            logger.debug(f"Could not compute unrealized for trade {trade.get('id')}: {e}")
            return 0.0

    def update_unrealized_positions(self):
        """
        Recompute unrealized PnL for all open virtual trades and persist (as a convenience).
        """
        self.monitor_sl_tp()  # Check SL/TP before updating unrealized

        trades = self._read_virtual_trades()
        changed = False
        for t in trades:
            if t.get("status") != "Open":
                continue
            current_price = self.get_current_price(t["symbol"])
            unreal = self._compute_unrealized_for_trade(t, current_price)
            # store an ephemeral field for convenience (not used for accounting)
            if t.get("unrealized_pnl") != unreal:
                t["unrealized_pnl"] = unreal
                changed = True
        if changed:
            self._write_virtual_trades(trades)

    def monitor_sl_tp(self):
        """
        Monitor open virtual trades and close them if SL or TP is hit.
        For real mode, Bybit handles it server-side.
        """
        if self.client:
            return  # Real mode: server handles TP/SL

        trades = self._read_virtual_trades()
        updated_trades = []
        closed = []
        now_ms = int(time.time() * 1000)
        capital_data = self._read_capital()
        virtual_cap = capital_data.get("virtual", {"capital": 100.0, "available": 100.0})

        for t in trades:
            if t["status"] != "Open":
                updated_trades.append(t)
                continue

            current = self.get_current_price(t["symbol"])
            sl = float(t.get("stopLoss", 0))
            tp = float(t.get("takeProfit", 0))
            hit_sl = False
            hit_tp = False

            if t["side"] == "Buy":
                if sl > 0 and current <= sl:
                    hit_sl = True
                elif tp > 0 and current >= tp:
                    hit_tp = True
            else:  # Sell
                if sl > 0 and current >= sl:
                    hit_sl = True
                elif tp > 0 and current <= tp:
                    hit_tp = True

            if hit_sl or hit_tp:
                # Close at the trigger price for simulation accuracy
                close_price = sl if hit_sl else tp if hit_tp else current

                # Compute pnl
                qty = float(t["qty"])
                if t["side"] == "Buy":
                    pnl = (close_price - t["entry_price"]) * qty
                else:
                    pnl = (t["entry_price"] - close_price) * qty

                # Update trade
                t["status"] = "Closed"
                t["close_price"] = close_price
                t["close_time"] = now_ms
                t["realized_pnl"] = pnl

                # Update capital
                virtual_cap["capital"] += pnl
                virtual_cap["available"] = virtual_cap["capital"]  # Simple model

                closed.append(t)
                updated_trades.append(t)

                # Optionally persist to DB
                try:
                    if hasattr(db, "save_trade"):
                        db.save_trade(t)
                except Exception as e:
                    logger.debug(f"Could not save closed virtual trade to DB: {e}")
            else:
                updated_trades.append(t)

        if closed:
            self._write_virtual_trades(updated_trades)
            capital_data["virtual"] = virtual_cap
            self._write_capital(capital_data)
            logger.info(f"[VIRTUAL] Closed {len(closed)} trades due to SL/TP hits.")

        return {"closed": len(closed)}

    # -------------------------
    # Daily PnL
    # -------------------------
    def get_daily_pnl(self) -> float:
        """
        Return daily realized PnL in USDT.
        - Virtual mode: sum realized_pnl of trades closed today (UTC).
        - Real mode: call Bybit closed PnL endpoint.
        """
        if not self.client:
            # Virtual: sum realized_pnl for trades closed today
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
                        pnl = float(t.get("realized_pnl", 0.0) or 0.0)
                        total += pnl
                return total
            except Exception as e:
                logger.error(f"Error computing virtual daily pnl: {e}")
                return 0.0

        try:
            # Real: call Bybit closed pnl endpoint
            today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            start_time = int(today.timestamp() * 1000)

            response = self.client.get_closed_pnl(
                category="linear",
                startTime=start_time
            )

            if isinstance(response, dict) and response.get("retCode") == 0:
                pnl_list = response.get("result", {}).get("list", [])
                total_pnl = sum(float(pnl.get("closedPnl", 0)) for pnl in pnl_list)
                return total_pnl
            else:
                logger.error(f"Daily P&L error: {response.get('retMsg', 'Unknown error') if isinstance(response, dict) else 'Invalid response'}")
                return 0.0

        except Exception as e:
            logger.error(f"Error getting daily P&L: {e}")
            return 0.0

    # -------------------------
    # Utility: compute portfolio unrealized (virtual)
    # -------------------------
    def get_portfolio_unrealized(self) -> Dict[str, Any]:
        """
        For virtual mode: return combined unrealized PnL and per-symbol breakdown.
        For real mode: attempt to fetch positions and compute unrealized PnL from API positions (if returned).
        """
        self.monitor_sl_tp()  # Ensure SL/TP are checked before computing unrealized

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
        else:
            # Try to compute from Bybit positions if available
            try:
                positions = self.get_positions()
                total = 0.0
                by_symbol = {}
                for p in positions:
                    # Expecting pos to have unrealizedPnl or an equity/entry/size fields
                    unreal = 0.0
                    if "unrealisedPnl" in p:
                        unreal = float(p.get("unrealisedPnl", 0))
                    elif "unrealizedPnl" in p:
                        unreal = float(p.get("unrealizedPnl", 0))
                    elif "positionValue" in p and "entryPrice" in p:
                        # approximate
                        size = float(p.get("size", 0))
                        entry = float(p.get("entryPrice", 0))
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

    # -------------------------
    # Extra helpers (dev)
    # -------------------------
    def dump_virtual_state(self) -> Dict[str, Any]:
        """Return full virtual storage snapshot for debugging."""
        return {
            "capital": self._read_capital(),
            "trades": self._read_virtual_trades()
        }

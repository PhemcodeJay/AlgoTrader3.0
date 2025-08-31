import streamlit as st
import pandas as pd
import logging
from datetime import datetime, timezone
from typing import List, Optional, Dict
from bybit_client import BybitClient
from engine import TradingEngine
from db import db_manager
import time
import requests
from utils import format_price_safe, format_currency_safe, display_trades_table, get_trades_safe

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, filename="app.log", filemode="a", format="%(asctime)s - %(levelname)s - %(message)s", encoding="utf-8")

# Constants (loaded from settings.json or defaults from utils.py)
try:
    from settings import load_settings
    settings = load_settings()
    RISK_PCT = settings.get('RISK_PCT', 0.01)
    ACCOUNT_BALANCE = settings.get('VIRTUAL_BALANCE', 100.0)
    LEVERAGE = settings.get('LEVERAGE', 10)
except ImportError:
    RISK_PCT = 0.01
    ACCOUNT_BALANCE = 100.0
    LEVERAGE = 10

def get_tickers(client: BybitClient, max_retries: int = 3) -> List[dict]:
    """Safe wrapper for getting ticker snapshot from Bybit MAINNET with retry logic"""
    base_url = "https://api.bybit.com"  # Force MAINNET
    url = f"{base_url}/v5/market/tickers?category=linear"
    headers = {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/58.0.3029.110 Safari/537.36'
        )
    }

    for attempt in range(max_retries):
        try:
            if client and hasattr(client, 'get_tickers') and client.is_connected():
                response = client.get_tickers(category="linear")
            else:
                response = requests.get(url, headers=headers).json()

            logger.debug(f"Ticker API response: {response}")

            # Bybit mainnet unified API uses `retCode` not `ret_code`
            if isinstance(response, dict) and response.get("retCode") == 0:
                tickers = [
                    {
                        "symbol": ticker.get("symbol", "N/A"),
                        "lastPrice": float(ticker.get("lastPrice", 0)),
                        "priceChangePercent": float(ticker.get("price24hPcnt", '0')) * 100
                    }
                    for ticker in response.get("result", {}).get("list", [])
                    if ticker.get("symbol", "").endswith("USDT")
                    and ticker.get("symbol", "") not in [
                        "1000000BABYDOGEUSDT",
                        "1000000CHEEMSUSDT",
                        "1000000MOGUSDT",
                    ]
                ]
                return sorted(tickers, key=lambda x: x.get("lastPrice", 0), reverse=True)[:6]

            logger.warning(
                f"Invalid ticker response on attempt {attempt + 1}: "
                f"{response.get('retMsg', 'No error message')}"
            )
            time.sleep(2)

        except AttributeError as e:
            logger.error(f"BybitClient method error on attempt {attempt + 1}: {e}")
            time.sleep(2)
        except Exception as e:
            logger.error(f"Error getting ticker snapshot on attempt {attempt + 1}: {e}")
            time.sleep(2)

    logger.warning("All retries failed, returning default ticker data")
    default_tickers = []
    for ticker in default_tickers:
        try:
            ticker["lastPrice"] = get_current_price_safe(ticker["symbol"], client)
        except Exception:
            pass
    return default_tickers[:6]


def get_portfolio_balance(db, client: BybitClient, is_virtual: bool = True) -> Dict:
    """Calculate portfolio balance and unrealized P&L"""
    try:
        portfolio_holdings = db.get_portfolio()
        total_capital = ACCOUNT_BALANCE if is_virtual else 0.0
        total_value = 0.0
        unrealized_pnl = 0.0
        used_margin = 0.0

        if not is_virtual and client.is_connected():
            wallet_info = client.get_wallet_balance() or {}
            total_capital = float(wallet_info.get('totalEquity', 0.0))

        for holding in portfolio_holdings:
            if getattr(holding, 'is_virtual', True) == is_virtual:
                qty = float(getattr(holding, 'qty', 0) or 0)
                avg_price = float(getattr(holding, 'avg_price', 0) or 0)
                symbol = getattr(holding, 'symbol', 'N/A')
                if symbol in ["1000000BABYDOGEUSDT", "1000000CHEEMSUSDT", "1000000MOGUSDT"]:
                    continue
                current_price = get_current_price_safe(symbol, client)
                value = qty * current_price if qty and current_price else 0
                holding_unrealized_pnl = value - (qty * avg_price) if qty and avg_price else 0
                total_value += value
                unrealized_pnl += holding_unrealized_pnl
                used_margin += float(getattr(holding, 'margin_usdt', 0) or 0)

        available_balance = total_capital - used_margin

        return {
            "capital": total_capital,
            "available": available_balance,
            "value": total_value,
            "unrealized_pnl": unrealized_pnl,
            "open_positions": sum(1 for h in portfolio_holdings if getattr(h, 'is_virtual', True) == is_virtual and h.symbol not in ["1000000BABYDOGEUSDT", "1000000CHEEMSUSDT", "1000000MOGUSDT"])
        }
    except Exception as e:
        logger.error(f"Error calculating portfolio balance (virtual={is_virtual}): {e}")
        return {
            "capital": ACCOUNT_BALANCE if is_virtual else 0.0,
            "available": ACCOUNT_BALANCE if is_virtual else 0.0,
            "value": 0.0,
            "unrealized_pnl": 0.0,
            "open_positions": 0
        }

def get_current_price_safe(symbol: str, client: Optional["BybitClient"] = None) -> float:
    """Safe wrapper for getting current price from Bybit MAINNET"""
    try:
        base_url = "https://api.bybit.com"  # Force MAINNET
        url = f"{base_url}/v5/market/tickers?category=linear&symbol={symbol}"
        headers = {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/58.0.3029.110 Safari/537.36'
            )
        }

        # Prefer BybitClient if available
        if client and hasattr(client, "get_current_price") and client.is_connected():
            return float(client.get_current_price(symbol))

        # Otherwise fallback to REST
        response = requests.get(url, headers=headers, timeout=10).json()
        if isinstance(response, dict) and response.get("retCode") == 0:
            ticker = response.get("result", {}).get("list", [{}])[0]
            return float(ticker.get("lastPrice", 0))

        logger.warning(f"Invalid price response for {symbol}: {response}")
        return 0.0

    except Exception as e:
        logger.error(f"Error getting price for {symbol}: {e}")
        return 0.0

def show_dashboard(db, engine, client, trading_mode: str = "virtual"):
    """Dashboard page with tabs and card-based layout"""
    st.title("📊 Dashboard")

    # Custom CSS for styling
    st.markdown("""
        <style>
        .stApp {
            background: linear-gradient(135deg, #1e1e2f 0%, #2a2a4a 100%);
            color: #e0e0e0;
            font-family: 'Segoe UI', sans-serif;
        }
        .stTabs [data-baseweb="tab-list"] {
            background: #2c2c4e;
            border-radius: 10px;
            padding: 5px;
        }
        .stTabs [data-baseweb="tab"] {
            color: #a0a0c0;
            font-weight: 400;
            border-radius: 8px;
            margin: 5px;
            padding: 10px 20px;
            transition: all 0.3s ease;
        }
        .stTabs [data-baseweb="tab"][aria-selected="true"] {
            background: linear-gradient(45deg, #6366f1, #a855f7);
            color: #ffffff;
            font-weight: 400;
            box-shadow: 0 2px 5px rgba(0,0,0,0.2);
        }
        .stTabs [data-baseweb="tab"]:hover {
            background: #3b3b5e;
            color: #ffffff;
        }
        .stContainer {
            background: linear-gradient(145deg, #2a2a4a, #3b3b5e);
            border-radius: 15px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.3);
            border: 1px solid rgba(99, 102, 241, 0.2);
        }
        .stButton > button {
            background: linear-gradient(45deg, #6366f1, #a855f7);
            color: white;
            border: none;
            border-radius: 8px;
            padding: 10px 20px;
            font-weight: 500;
        }
        .stButton > button:hover {
            background: linear-gradient(45deg, #8183ff, #c084fc);
        }
        .stButton > button[kind="primary"] {
            background: linear-gradient(45deg, #10b981, #34d399);
        }
        .stButton > button[kind="primary"]:hover {
            background: linear-gradient(45deg, #34d399, #6ee7b7);
        }
        .stMetric {
            background: rgba(255,255,255,0.05);
            border-radius: 8px;
            padding: 10px;
            margin: 5px 0;
        }
        .stMetric > div {
            font-size: 1.2rem;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .stSelectbox, .stNumberInput {
            background: #3b3b5e;
            border-radius: 8px;
            padding: 5px;
        }
        .stTextArea textarea {
            background: rgba(255,255,255,0.05);
            color: #ffffff;
            border-radius: 8px;
        }
        </style>
    """, unsafe_allow_html=True)

    # Define tabs
    overview_tab, market_tab, trades_tab = st.tabs(["📈 Overview", "🌐 Market", "📋 Trades"])

    # Overview tab
    with overview_tab:
        with st.container(border=True):
            st.markdown("### Portfolio Metrics")
            is_virtual = trading_mode == "virtual"
            portfolio_balance = get_portfolio_balance(db, client, is_virtual)
            total_balance = portfolio_balance.get("capital", 0.0)
            open_positions = portfolio_balance.get("open_positions", 0)
            daily_pnl = portfolio_balance.get("unrealized_pnl", 0.0)
            trades = get_trades_safe(db)
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Portfolio Balance", f"{format_currency_safe(total_balance)}")
            with col2:
                st.metric("Open Positions", open_positions)
            with col3:
                st.metric("Daily P&L", f"{format_currency_safe(daily_pnl)}", 
                         delta=f"{daily_pnl:+.2f}", 
                         delta_color="normal" if daily_pnl >= 0 else "inverse")
            with col4:
                st.metric("Total Trades", len(trades))
            if st.button("🔄 Refresh Metrics", key="refresh_metrics_overview_tab"):
                st.rerun()

    # Market tab
    with market_tab:
        st.subheader("🌐 Market Overview")
        with st.spinner("Fetching market data..."):
            market_data = get_tickers(client)
        if market_data:
            cols = st.columns(min(6, len(market_data)))
            for i, ticker in enumerate(market_data[:6]):
                with cols[i]:
                    with st.container(border=True):
                        symbol = ticker.get('symbol', 'N/A')
                        price = ticker.get('lastPrice', 0)
                        change = ticker.get('priceChangePercent', 0)
                        try:
                            change_pct = float(change)
                            delta_color = "normal" if change_pct >= 0 else "inverse"
                            st.metric(
                                label=symbol.replace('USDT', ''),
                                value=format_currency_safe(price),  # Changed to format_currency_safe
                                delta=f"{change_pct:+.2f}%",
                                delta_color=delta_color
                            )
                        except (ValueError, TypeError) as e:
                            logger.error(f"Error formatting market data for {symbol}: {e}")
                            st.metric(symbol.replace('USDT', ''), format_currency_safe(price))  # Changed to format_currency_safe
            if st.button("🔄 Refresh Market Data", key="market_refresh_data"):
                st.rerun()
        else:
            st.info("🌙 No market data available. Please try refreshing.")

    # Trades tab
    with trades_tab:
        st.subheader("📋 Recent Trades")
        display_trades_table(get_trades_safe(db), st)
        if st.button("🔄 Refresh Trades", key="trades_refresh_data"):
            st.rerun()
# Initialize components
db = db_manager
engine = TradingEngine()
client = engine.client

# Run the app
show_dashboard(db, engine, client)
import streamlit as st
import pandas as pd
import logging
from datetime import datetime
from typing import List, Optional, Dict
from bybit_client import BybitClient
from engine import TradingEngine
from db import db_manager
import time
import requests

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Constants from utils.py
RISK_PCT = 0.01
ACCOUNT_BALANCE = 100.0
LEVERAGE = 20

# Utility functions
def get_ticker_snapshot_safe(client: BybitClient, max_retries: int = 3) -> List[dict]:
    """Safe wrapper for getting ticker snapshot with retry logic"""
    base_url = f"https://api{'-testnet' if client.testnet else ''}.bybit.com"
    url = f"{base_url}/v5/market/tickers?category=linear"
    for attempt in range(max_retries):
        try:
            if client.is_connected():
                response = client.get_tickers(category="linear")
            else:
                response = requests.get(url).json()
            if isinstance(response, dict) and response.get("retCode") == 0:
                tickers = [
                    {
                        "symbol": ticker.get("symbol", "N/A"),
                        "lastPrice": float(ticker.get("lastPrice", 0)),
                        "priceChangePercent": float(ticker.get("priceChangePercent", 0))
                    }
                    for ticker in response.get("result", {}).get("list", [])
                    if ticker.get("symbol", "").endswith("USDT") and 
                       ticker.get("symbol", "") not in ["1000000BABYDOGEUSDT", "1000000CHEEMSUSDT", "1000000MOGUSDT"]
                ]
                return sorted(tickers, key=lambda x: x.get("lastPrice", 0), reverse=True)[:6]
            logger.warning(f"Invalid ticker response structure on attempt {attempt + 1}")
            time.sleep(1)
        except AttributeError as e:
            logger.error(f"BybitClient method error on attempt {attempt + 1}: {e}")
            time.sleep(1)
        except Exception as e:
            logger.error(f"Error getting ticker snapshot on attempt {attempt + 1}: {e}")
            time.sleep(1)
    # Fallback: Return default tickers if all retries fail
    logger.warning("All retries failed, returning default ticker data")
    default_tickers = [
        {"symbol": "BTCUSDT", "lastPrice": 100000.0, "priceChangePercent": 0.0},
        {"symbol": "ETHUSDT", "lastPrice": 4500.0, "priceChangePercent": 0.0},
        {"symbol": "XRPUSDT", "lastPrice": 0.5, "priceChangePercent": 0.0},
        {"symbol": "BNBUSDT", "lastPrice": 800.0, "priceChangePercent": 0.0},
        {"symbol": "DOGEUSDT", "lastPrice": 0.2, "priceChangePercent": 0.0},
        {"symbol": "SOLUSDT", "lastPrice": 170.0, "priceChangePercent": 0.0}
    ]
    for ticker in default_tickers:
        try:
            ticker["lastPrice"] = get_current_price_safe(ticker["symbol"], client)
        except Exception:
            pass
    return default_tickers[:6]

def get_portfolio_balance(db, client, is_virtual: bool = True) -> Dict:
    """Calculate portfolio balance and unrealized P&L"""
    try:
        portfolio_holdings = db.get_portfolio()
        total_capital = 0.0
        total_value = 0.0
        unrealized_pnl = 0.0
        used_margin = 0.0

        for holding in portfolio_holdings:
            if holding.is_virtual == is_virtual:
                qty = float(getattr(holding, 'qty', 0))
                avg_price = float(getattr(holding, 'avg_price', 0))
                symbol = getattr(holding, 'symbol', 'N/A')
                current_price = get_current_price_safe(symbol, client)
                value = qty * current_price if qty and current_price else 0
                holding_unrealized_pnl = value - (qty * avg_price) if qty and avg_price else 0
                total_capital += float(getattr(holding, 'capital', 0))
                total_value += value
                unrealized_pnl += holding_unrealized_pnl
                used_margin += float(getattr(holding, 'margin_usdt', 0) or 0)

        available_balance = total_capital - used_margin

        return {
            "capital": total_capital,
            "available": available_balance,
            "value": total_value,
            "unrealized_pnl": unrealized_pnl,
            "open_positions": sum(1 for h in portfolio_holdings if h.is_virtual == is_virtual)
        }
    except Exception as e:
        logger.error(f"Error calculating portfolio balance (virtual={is_virtual}): {e}")
        return {
            "capital": 100.0 if is_virtual else 0.0,
            "available": 100.0 if is_virtual else 0.0,
            "value": 0.0,
            "unrealized_pnl": 0.0,
            "open_positions": 0
        }

def get_current_price_safe(symbol: str, client: BybitClient) -> float:
    """Safe wrapper for getting current price"""
    try:
        return client.get_current_price(symbol)
    except Exception as e:
        logger.error(f"Error getting price for {symbol}: {e}")
        return 0.0

def get_portfolio_safe(db) -> List:
    """Safe wrapper for getting portfolio"""
    try:
        return db.get_portfolio()
    except Exception as e:
        logger.error(f"Error getting portfolio: {e}")
        return []

def get_trades_safe(db, limit: int = 10) -> List:
    """Safe wrapper for getting trades"""
    try:
        return db.get_trades(limit=limit)
    except Exception as e:
        logger.error(f"Error getting trades: {e}")
        return []

def get_open_trades_safe(db) -> List:
    """Safe wrapper for getting open trades"""
    try:
        return db.get_open_trades()
    except Exception as e:
        logger.error(f"Error getting open trades: {e}")
        return []

def get_daily_pnl_safe(db, client: BybitClient) -> float:
    """Safe wrapper for getting daily P&L"""
    try:
        return client.get_daily_pnl()
    except Exception as e:
        logger.error(f"Error getting daily P&L: {e}")
        return 0.0

def format_price_safe(value: Optional[float]) -> str:
    """Format price safely"""
    return f"{value:.2f}" if value is not None and value > 0 else "N/A"

def format_currency_safe(value: Optional[float]) -> str:
    """Format currency safely"""
    return f"{value:.2f}" if value is not None else "0.00"

def display_trades_table(trades, container, max_trades=5):
    """Reusable function to display trades table"""
    try:
        if not trades:
            container.info("🌙 No trades to display")
            return

        trades_data = []
        for trade in trades[:max_trades]:
            trades_data.append({
                "Symbol": getattr(trade, 'symbol', 'N/A'),
                "Side": getattr(trade, 'side', 'N/A'),
                "Entry": f"${format_price_safe(getattr(trade, 'entry_price', 0))}",
                "P&L": f"${format_currency_safe(getattr(trade, 'pnl', 0))}",
                "Status": getattr(trade, 'status', 'N/A').title(),
                "Mode": "🟢 Virtual" if getattr(trade, 'virtual', True) else "🔴 Real",
                "Strategy": getattr(trade, 'strategy', 'N/A')
            })

        if trades_data:
            df = pd.DataFrame(trades_data)
            container.dataframe(df, use_container_width=True, height=250)
        else:
            container.info("🌙 No trade data to display")
    except Exception as e:
        logger.error(f"Error displaying trades table: {e}")
        container.error("🚨 Error displaying trades")

# Custom CSS for smaller, bold fonts
st.markdown("""
    <style>
    .stApp {
        background: linear-gradient(135deg, #1e1e2f 0%, #2a2a4a 100%);
        color: #e0e0e0;
        font-family: 'Segoe UI', sans-serif;
        font-size: 14px;
        font-weight: 600;
    }
    .stTabs [data-baseweb="tab-list"] {
        background: #2c2c4e;
        border-radius: 10px;
        padding: 5px;
    }
    .stTabs [data-baseweb="tab"] {
        color: #a0a0c0;
        font-weight: 600;
        font-size: 13px;
        border-radius: 8px;
        margin: 5px;
        padding: 8px 16px;
        transition: all 0.3s ease;
    }
    .stTabs [data-baseweb="tab"][aria-selected="true"] {
        background: linear-gradient(45deg, #6366f1, #a855f7);
        color: #ffffff;
        font-weight: 700;
        box-shadow: 0 2px 5px rgba(0,0,0,0.2);
    }
    .stTabs [data-baseweb="tab"]:hover {
        background: #3b3b5e;
        color: #ffffff;
    }
    .stContainer {
        background: linear-gradient(145deg, #2a2a4a, #3b3b5e);
        border-radius: 12px;
        padding: 15px;
        margin-bottom: 15px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.3);
        border: 1px solid rgba(99, 102, 241, 0.2);
        transition: transform 0.2s ease;
    }
    .stContainer:hover {
        transform: translateY(-5px);
    }
    .stButton > button {
        background: linear-gradient(45deg, #6366f1, #a855f7);
        color: white;
        border: none;
        border-radius: 8px;
        padding: 8px 16px;
        font-size: 13px;
        font-weight: 600;
        transition: all 0.3s ease;
    }
    .stButton > button:hover {
        background: linear-gradient(45deg, #8183ff, #c084fc);
        box-shadow: 0 2px 8px rgba(0,0,0,0.3);
    }
    .stMetric {
        background: rgba(255,255,255,0.05);
        border-radius: 8px;
        padding: 8px;
        margin: 5px 0;
    }
    .stMetric label {
        color: #a0a0c0;
        font-size: 12px;
        font-weight: 600;
    }
    .stMetric .stMetricValue {
        color: #ffffff;
        font-size: 14px;
        font-weight: 700;
    }
    .stMetric [data-testid="stMetricDelta"] {
        font-size: 12px;
        font-weight: 600;
    }
    .stAlert {
        border-radius: 8px;
        background: rgba(255,255,255,0.1);
        color: #ffffff;
        font-size: 13px;
        font-weight: 600;
    }
    .stDataFrame {
        background: rgba(255,255,255,0.05);
        border-radius: 8px;
        padding: 8px;
        font-size: 13px;
        font-weight: 600;
    }
    h3, .stMarkdown h3 {
        font-size: 18px;
        font-weight: 700;
    }
    </style>
""", unsafe_allow_html=True)

def show_dashboard(db, engine, client):
    """Main trading dashboard with tabs and card-based layout"""
    st.title("📊 Trading Dashboard")

    # Define tabs
    overview_tab, market_tab, trades_tab = st.tabs(["📈 Overview", "🌐 Market", "📋 Recent Trades"])

    try:
        # Get data safely
        portfolio = get_portfolio_safe(db)
        trades = get_trades_safe(db, limit=10)
        open_trades = get_open_trades_safe(db)
        daily_pnl = get_daily_pnl_safe(db, client)

        # Calculate metrics using portfolio balance
        virtual_balance = get_portfolio_balance(db, client, is_virtual=True)
        real_balance = get_portfolio_balance(db, client, is_virtual=False)
        total_balance = virtual_balance['value'] + real_balance['value']
        total_unrealized_pnl = virtual_balance['unrealized_pnl'] + real_balance['unrealized_pnl']
        open_positions = len(open_trades)

        # Overview tab: Key metrics
        with overview_tab:
            with st.container(border=True):
                st.markdown("### Portfolio Metrics")
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Portfolio Balance", f"${format_currency_safe(total_balance)}")
                with col2:
                    st.metric("Open Positions", open_positions)
                with col3:
                    st.metric("Daily P&L", f"${format_currency_safe(daily_pnl)}", 
                             delta=f"{daily_pnl:+.2f}", 
                             delta_color="normal" if daily_pnl >= 0 else "inverse")
                with col4:
                    st.metric("Total Trades", len(trades))
                if st.button("🔄 Refresh Metrics", key="refresh_metrics_overview_tab"):
                    st.rerun()

        # Market tab: Market overview
        with market_tab:
            st.subheader("🌐 Market Overview")
            with st.spinner("Fetching market data..."):
                market_data = get_ticker_snapshot_safe(client)
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
                                    value=f"${format_price_safe(price)}",
                                    delta=f"{change_pct:+.2f}%",
                                    delta_color=delta_color
                                )
                            except (ValueError, TypeError) as e:
                                logger.error(f"Error formatting market data for {symbol}: {e}")
                                st.metric(symbol.replace('USDT', ''), f"${format_price_safe(price)}")
                if st.button("🔄 Refresh Market Data", key="market_refresh_data"):
                    st.rerun()
            else:
                st.info("🌙 No market data available. Please try refreshing.")

        # Trades tab: Recent trades
        with trades_tab:
            st.subheader("📋 Recent Trades")
            display_trades_table(trades, st)
            if st.button("🔄 Refresh Trades", key="trades_refresh_data"):
                st.rerun()

    except Exception as e:
        logger.error(f"Error in dashboard: {e}")
        st.error(f"🚨 Dashboard error: {str(e)}")

# Initialize components
db = db_manager
engine = TradingEngine()
client = engine.client

# Run the app
show_dashboard(db, engine, client)
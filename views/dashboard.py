import streamlit as st
import pandas as pd
import logging
from datetime import datetime
from typing import List, Optional
from bybit_client import BybitClient
from engine import TradingEngine
from db import db_manager

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Utility functions
def get_ticker_snapshot_safe(client: BybitClient) -> List[dict]:
    """Safe wrapper for getting ticker snapshot using BybitClient"""
    try:
        response = client.get_tickers(category="linear")
        if isinstance(response, dict) and response.get("retCode") == 0:
            return [
                {
                    "symbol": ticker["symbol"],
                    "lastPrice": float(ticker.get("lastPrice", 0)),
                    "priceChangePercent": float(ticker.get("priceChangePercent", 0))
                }
                for ticker in response.get("result", {}).get("list", [])[:6]
            ]
        return []
    except Exception as e:
        logger.error(f"Error getting ticker snapshot: {e}")
        return []

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

def get_daily_pnl_safe(client: BybitClient) -> float:
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
    """Reusable function to display trades table."""
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
                "Mode": "🟢 Virtual" if getattr(trade, 'virtual', True) else "🔴 Real"
            })

        if trades_data:
            df = pd.DataFrame(trades_data)
            container.dataframe(df, use_container_width=True, height=300)
        else:
            container.info("🌙 No trade data to display")
    except Exception as e:
        logger.error(f"Error displaying trades table: {e}")
        container.error("🚨 Error displaying trades")

# Custom CSS for modern, colorful styling
st.markdown("""
    <style>
    /* Global styles */
    .stApp {
        background: linear-gradient(135deg, #1e1e2f 0%, #2a2a4a 100%);
        color: #e0e0e0;
        font-family: 'Segoe UI', sans-serif;
    }

    /* Tab styling */
    .stTabs [data-baseweb="tab-list"] {
        background: #2c2c4e;
        border-radius: 10px;
        padding: 5px;
    }
    .stTabs [data-baseweb="tab"] {
        color: #a0a0c0;
        font-weight: 500;
        border-radius: 8px;
        margin: 5px;
        padding: 10px 20px;
        transition: all 0.3s ease;
    }
    .stTabs [data-baseweb="tab"][aria-selected="true"] {
        background: linear-gradient(45deg, #6366f1, #a855f7);
        color: #ffffff;
        font-weight: 600;
        box-shadow: 0 2px 5px rgba(0,0,0,0.2);
    }
    .stTabs [data-baseweb="tab"]:hover {
        background: #3b3b5e;
        color: #ffffff;
    }

    /* Card styling */
    .stContainer {
        background: linear-gradient(145deg, #2a2a4a, #3b3b5e);
        border-radius: 15px;
        padding: 20px;
        margin-bottom: 20px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.3);
        border: 1px solid rgba(99, 102, 241, 0.2);
        transition: transform 0.2s ease;
    }
    .stContainer:hover {
        transform: translateY(-5px);
    }

    /* Buttons */
    .stButton > button {
        background: linear-gradient(45deg, #6366f1, #a855f7);
        color: white;
        border: none;
        border-radius: 8px;
        padding: 10px 20px;
        font-weight: 500;
        transition: all 0.3s ease;
    }
    .stButton > button:hover {
        background: linear-gradient(45deg, #8183ff, #c084fc);
        box-shadow: 0 2px 8px rgba(0,0,0,0.3);
    }

    /* Metrics */
    .stMetric {
        background: rgba(255,255,255,0.05);
        border-radius: 8px;
        padding: 10px;
        margin: 5px 0;
    }
    .stMetric label {
        color: #a0a0c0;
        font-size: 14px;
    }
    .stMetric .stMetricValue {
        color: #ffffff;
        font-weight: 600;
    }
    .stMetric [data-testid="stMetricDelta"] {
        font-size: 14px;
    }

    /* Info and error messages */
    .stAlert {
        border-radius: 8px;
        background: rgba(255,255,255,0.1);
        color: #ffffff;
    }

    /* Dataframe styling */
    .stDataFrame {
        background: rgba(255,255,255,0.05);
        border-radius: 8px;
        padding: 10px;
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
        daily_pnl = get_daily_pnl_safe(client)

        # Calculate metrics
        total_balance = sum(getattr(p, 'capital', 0) for p in portfolio) if portfolio else 100.0
        total_unrealized_pnl = sum(getattr(p, 'unrealized_pnl', 0) for p in portfolio) if portfolio else 0.0
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
                    st.metric("Daily P&L", f"${format_currency_safe(daily_pnl)}", delta=f"{daily_pnl:+.2f}", delta_color="normal" if daily_pnl >= 0 else "inverse")
                with col4:
                    st.metric("Total Trades", len(trades))
                if st.button("🔄 Refresh Metrics", key="refresh_metrics"):
                    st.rerun()

        # Market tab: Market overview
        with market_tab:
            st.subheader("🌐 Market Overview")
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
                if st.button("🔄 Refresh Market Data", key="refresh_market"):
                    st.rerun()
            else:
                st.info("🌙 No market data available")

        # Trades tab: Recent trades
        with trades_tab:
            st.subheader("📋 Recent Trades")
            display_trades_table(trades, st)
            if st.button("🔄 Refresh Trades", key="refresh_trades"):
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
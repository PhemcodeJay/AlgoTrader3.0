import os
import json
from datetime import datetime, date, timezone
from typing import List, Optional, Dict, Union, cast, Any
from dotenv import load_dotenv
from sqlalchemy import (
    create_engine, String, Integer, Float, DateTime, Boolean, JSON, text
)
import pandas as pd
from sqlalchemy import func
from sqlalchemy.orm import (
    declarative_base, sessionmaker, Session, Mapped, mapped_column
)
from sqlalchemy import update
import logging

logger = logging.getLogger(__name__)


# Load .env file if it exists
load_dotenv()

Base = declarative_base()

# === SQLAlchemy Models ===
class Signal(Base):
    __tablename__ = 'signals'
    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String)
    interval: Mapped[str] = mapped_column(String)
    signal_type: Mapped[str] = mapped_column(String)
    score: Mapped[float] = mapped_column(Float)
    indicators: Mapped[dict] = mapped_column(JSON)
    strategy: Mapped[str] = mapped_column(String, default="Auto")
    side: Mapped[str] = mapped_column(String, default="LONG")
    sl: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tp: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    trail: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    liquidation: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    leverage: Mapped[Optional[int]] = mapped_column(Integer, default=20)
    margin_usdt: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    entry: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    market: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "interval": self.interval,
            "signal_type": self.signal_type,
            "score": self.score,
            "strategy": self.strategy,
            "side": self.side,
            "sl": self.sl,
            "tp": self.tp,
            "trail": self.trail,
            "liquidation": self.liquidation,
            "entry": self.entry,
            "leverage": self.leverage,
            "margin_usdt": self.margin_usdt,
            "market": self.market,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "indicators": self.indicators,
        }

class Trade(Base):
    __tablename__ = 'trades'
    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String)
    side: Mapped[str] = mapped_column(String)
    qty: Mapped[float] = mapped_column(Float)
    entry_price: Mapped[float] = mapped_column(Float)
    exit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    stop_loss: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    take_profit: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    leverage: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    margin_usdt: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pnl: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    status: Mapped[str] = mapped_column(String)
    order_id: Mapped[str] = mapped_column(String)
    unrealized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    virtual: Mapped[bool] = mapped_column(Boolean, default=True)
    strategy: Mapped[str] = mapped_column(String, default="Auto")
    score: Mapped[float] = mapped_column(Float)

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "side": self.side,
            "qty": self.qty,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "leverage": self.leverage,
            "margin": self.margin_usdt,
            "pnl": self.pnl,
            "timestamp": self.timestamp.strftime("%Y-%m-%d %H:%M:%S") if self.timestamp else None,
            "status": self.status,
            "order_id": self.order_id,
            "unrealized_pnl": self.unrealized_pnl,
            "virtual": self.virtual,
            "strategy": self.strategy,
            "score": self.score,
        }

class Portfolio(Base):
    __tablename__ = 'portfolio'
    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String, unique=True)
    qty: Mapped[float] = mapped_column(Float)
    avg_price: Mapped[float] = mapped_column(Float)
    value: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    capital: Mapped[float] = mapped_column(Float, nullable=False, default=100.0)
    unrealized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    is_virtual: Mapped[bool] = mapped_column(Boolean, default=True)

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "qty": self.qty,
            "avg_price": self.avg_price,
            "value": self.value,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
            "capital": self.capital,
            "unrealized_pnl": self.unrealized_pnl,
            "is_virtual": self.is_virtual,
        }

class SystemSetting(Base):
    __tablename__ = 'settings'
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String, unique=True)
    value: Mapped[str] = mapped_column(String)

# === DB Setup ===
DATABASE_URL = os.getenv("DATABASE_URL") or "sqlite:///trading.db"  # Fallback to SQLite
if not DATABASE_URL:
    logger.error("DATABASE_URL not set in .env and no fallback provided")
    raise RuntimeError("DATABASE_URL is not set and no fallback provided")

def init_db():
    Base.metadata.create_all(bind=create_engine(DATABASE_URL))

class DatabaseManager:
    def __init__(self, url: str):
        self.engine = create_engine(url)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        init_db()

    def get_session(self) -> Session:
        return self.SessionLocal()

    def add_signal(self, signal_data: Dict):
        with self.get_session() as session:
            signal = Signal(**signal_data)
            session.add(signal)
            session.commit()
            logger.info("Signal added to DB")

    def get_signals(self, limit: int = 50) -> List[Signal]:
        with self.get_session() as session:
            return session.query(Signal).order_by(Signal.created_at.desc()).limit(limit).all()

    def add_trade(self, trade_data: Dict):
        with self.get_session() as session:
            trade = Trade(**trade_data)
            session.add(trade)
            session.commit()
            logger.info("Trade added to DB")

    def get_trades(self, symbol: Optional[str] = None, limit: int = 50) -> List[Trade]:
        with self.get_session() as session:
            query = session.query(Trade).order_by(Trade.timestamp.desc())
            if symbol:
                query = query.filter(Trade.symbol == symbol)
            return query.limit(limit).all()

    def get_recent_trades(self, symbol: Optional[str] = None, limit: int = 50) -> List[Trade]:
        return self.get_trades(symbol=symbol, limit=limit)

    def get_open_trades(self) -> List[Trade]:
        with self.get_session() as session:
            return session.query(Trade).filter(Trade.status == 'open').all()

    def get_trades_by_status(self, status: str) -> List[Trade]:
        with self.get_session() as session:
            return session.query(Trade).filter(Trade.status == status).all()

    def close_trade(self, order_id: str, exit_price: float, pnl: float):
        with self.get_session() as session:
            trade = session.query(Trade).filter_by(order_id=order_id).first()
            if trade:
                trade.exit_price = exit_price
                trade.pnl = pnl
                trade.status = 'closed'
                session.commit()

    def update_trade_unrealized_pnl(self, order_id: str, unrealized_pnl: float) -> None:
        with self.get_session() as session:
            session.execute(
                update(Trade)
                .where(Trade.order_id == order_id)
                .values(unrealized_pnl=unrealized_pnl)
            )
            session.commit()

    def update_portfolio_unrealized_pnl(self, symbol: str, unrealized_pnl: float, is_virtual: bool = False) -> None:
        with self.get_session() as session:
            session.execute(
                update(Portfolio)
                .where(
                    Portfolio.symbol == symbol,
                    Portfolio.is_virtual == is_virtual
                )
                .values(unrealized_pnl=unrealized_pnl, updated_at=datetime.now(timezone.utc))
            )
            session.commit()

    def update_portfolio_balance(self, symbol: str, qty: float, avg_price: float, value: float):
        with self.get_session() as session:
            portfolio = session.query(Portfolio).filter_by(symbol=symbol).first()
            if portfolio:
                portfolio.qty = qty
                portfolio.avg_price = avg_price
                portfolio.value = value
                portfolio.updated_at = datetime.now(timezone.utc)
            else:
                portfolio = Portfolio(
                    symbol=symbol,
                    qty=qty,
                    avg_price=avg_price,
                    value=value,
                    updated_at=datetime.now(timezone.utc)
                )
                session.add(portfolio)
            session.commit()

    def get_portfolio(self, symbol: Optional[str] = None) -> List[Portfolio]:
        with self.get_session() as session:
            if symbol:
                return session.query(Portfolio).filter_by(symbol=symbol).all()
            return session.query(Portfolio).all()

    def set_setting(self, key: str, value: str):
        with self.get_session() as session:
            setting = session.query(SystemSetting).filter_by(key=key).first()
            if setting:
                setting.value = value
            else:
                session.add(SystemSetting(key=key, value=value))
            session.commit()

    def get_setting(self, key: str) -> Optional[str]:
        with self.get_session() as session:
            setting = session.query(SystemSetting).filter_by(key=key).first()
            return setting.value if setting else None

    def get_all_settings(self) -> Dict[str, str]:
        with self.get_session() as session:
            settings = session.query(SystemSetting).all()
            return {s.key: s.value for s in settings}

    def get_automation_stats(self) -> Dict[str, str]:
        return {
            "total_signals": str(len(self.get_signals())),
            "open_trades": str(len(self.get_open_trades())),
            "timestamp": str(datetime.now())
        }

    def get_daily_pnl_pct(self) -> float:
        with self.get_session() as session:
            today = datetime.now().date()
            trades = session.query(Trade).filter(
                Trade.timestamp >= today,
                Trade.pnl.isnot(None)
            ).all()

            total_pnl = sum([trade.pnl for trade in trades if trade.pnl])
            return total_pnl

    def get_trades_count(self) -> int:
        with self.get_session() as session:
            return session.query(Trade).count()

    def get_signals_count(self) -> int:
        with self.get_session() as session:
            return session.query(Signal).count()

# Initialize database manager
db_manager = DatabaseManager(DATABASE_URL)
db = db_manager
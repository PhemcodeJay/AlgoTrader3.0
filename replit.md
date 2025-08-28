# AlgoTrader Dashboard

## Overview

AlgoTrader Dashboard is a comprehensive cryptocurrency trading application built with Streamlit that combines automated trading, signal generation, and portfolio management. The system supports both virtual trading for testing strategies and real trading through Bybit integration. It features machine learning-enhanced signal filtering, multi-timeframe technical analysis, and automated risk management capabilities.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Frontend Architecture
- **Framework**: Streamlit web application with wide layout configuration
- **Visualization**: Plotly for interactive charts and real-time data display
- **Components**: Modular dashboard components for signals, portfolio, automation, and settings
- **Real-time Updates**: Optional auto-refresh capability for live data monitoring

### Backend Architecture
- **Trading Engine**: Core `TradingEngine` class that orchestrates signal generation, trade execution, and risk management
- **Signal Generation**: Multi-timeframe technical analysis system supporting 15m, 1h, and 4h intervals
- **Automated Trading**: Background threading system with configurable automation parameters
- **Machine Learning**: XGBoost-based signal filtering and enhancement system

### Data Storage Solutions
- **Primary Database**: PostgreSQL with SQLAlchemy ORM for persistent data storage
- **Models**: Signal, Trade, and Portfolio entities with JSON field support for flexible indicator storage
- **Configuration**: JSON files for settings, automation parameters, and capital management
- **Caching**: File-based caching for capital balances and trading statistics

### Authentication and Authorization
- **API Keys**: Environment variable-based configuration for Bybit API credentials
- **Trading Modes**: Support for testnet, virtual, and live trading environments
- **Security**: HMAC SHA256 signature generation for secure API communications

### Risk Management System
- **Position Sizing**: Dynamic calculation based on account balance and risk percentage
- **Stop Loss/Take Profit**: Automated SL/TP placement with configurable percentages
- **Drawdown Protection**: Maximum drawdown limits with automatic trading suspension
- **Daily Limits**: Maximum trades per day and position size constraints

## External Dependencies

### Trading Platform Integration
- **Bybit API**: Primary exchange integration supporting both testnet and production environments
- **pybit Library**: Unified trading API client for order management and market data
- **Real-time Data**: WebSocket connections for live price feeds and order updates

### Machine Learning Stack
- **XGBoost**: Gradient boosting framework for signal classification and scoring
- **scikit-learn**: Model training pipeline and feature preprocessing
- **NumPy/Pandas**: Data manipulation and numerical computing libraries

### Notification Systems
- **Discord Integration**: Trade alerts and system notifications via Discord webhooks
- **Telegram Bot**: Alternative notification channel for trading updates
- **PDF Reporting**: Automated signal reports using FPDF library

### Technical Analysis Libraries
- **Custom Indicators**: RSI, MACD, Bollinger Bands, and EMA calculations
- **Multi-timeframe Analysis**: Support for multiple interval scanning (15m, 1h, 4h)
- **Volume Analysis**: Volume-based filtering and signal validation

### Infrastructure Dependencies
- **PostgreSQL**: Primary database for persistent storage
- **SQLAlchemy**: ORM and database abstraction layer
- **Threading**: Background automation and concurrent signal processing
- **Environment Management**: python-dotenv for configuration management
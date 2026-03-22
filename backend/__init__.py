"""Backend Blueprint Package

This package contains Flask blueprints for the IB Trading Platform:
- api: Core API endpoints
- market: Market data endpoints  
- orders: Order management endpoints
- trades: Trade tracking endpoints
- ai: AI analysis endpoints
"""

from .api import api_bp
from .market import market_bp
from .orders import orders_bp
from .trades import trades_bp
from .ai import ai_bp

__all__ = ['api_bp', 'market_bp', 'orders_bp', 'trades_bp', 'ai_bp']

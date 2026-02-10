"""Configuration file for IB Trading Platform

Edit these settings to match your IB Gateway/TWS setup.

Author: Perplexity AI Assistant
Version: 1.0.0
"""

# ========== IB Gateway Connection ==========

# Host (usually localhost)
IB_HOST = '127.0.0.1'

# Port settings:
# - 4002: IB Gateway (Paper Trading)
# - 4001: IB Gateway (Live Trading)
# - 7497: TWS (Paper Trading)
# - 7496: TWS (Live Trading)
IB_PORT = 4002  # Paper trading by default

# Client ID (each connection needs unique ID)
IB_CLIENT_ID = 1

# ========== Trading Settings ==========

# Default symbol
DEFAULT_SYMBOL = 'AAPL'

# Default timeframe
DEFAULT_TIMEFRAME = '5 mins'

# Default duration
DEFAULT_DURATION = '1 D'

# ========== UI Settings ==========

# Theme colors
PRIMARY_COLOR = '#667eea'
SECONDARY_COLOR = '#764ba2'
GREEN_COLOR = '#26a69a'
RED_COLOR = '#ef5350'
BACKGROUND_COLOR = '#1e1e2e'
PANEL_COLOR = '#2d2d3a'

# ========== Notes ==========

"""
TO SWITCH TO LIVE TRADING:
1. Change IB_PORT to 4001 (IB Gateway) or 7496 (TWS)
2. Make sure you understand the risks!
3. Start with small position sizes
4. Always use stop losses

IMPORTANT:
- Paper trading = simulated money (safe for testing)
- Live trading = real money (be careful!)
- Always test strategies in paper trading first
"""

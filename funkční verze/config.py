"""Configuration file for IB Trading Platform

Edit these settings to match your IB Gateway/TWS setup.

Author: Perplexity AI Assistant
Version: 2.0.0 - Added port switching and connection modes
"""

import os

# ========== IB Connection Mode ==========

# Available connection modes:
# - 'TWS_PAPER': Paper Trading TWS (port 7497) - DEFAULT
# - 'GATEWAY_PAPER': Paper Trading Gateway (port 4002)
# - 'TWS_LIVE': Live Trading TWS (port 7496) ⚠️ REAL MONEY
# - 'GATEWAY_LIVE': Live Trading Gateway (port 4001) ⚠️ REAL MONEY

# Change this to switch between different connections
CONNECTION_MODE = os.getenv('IB_CONNECTION_MODE', 'TWS_PAPER')

# Port mapping
CONNECTION_PORTS = {
    'TWS_PAPER': 7497,      # Paper Trading TWS
    'GATEWAY_PAPER': 4002,  # Paper Trading Gateway
    'TWS_LIVE': 7496,       # Live Trading TWS ⚠️ REAL MONEY
    'GATEWAY_LIVE': 4001,   # Live Trading Gateway ⚠️ REAL MONEY
}

# Connection labels for UI
CONNECTION_LABELS = {
    'TWS_PAPER': '📊 TWS Paper Trading',
    'GATEWAY_PAPER': '🌐 Gateway Paper Trading',
    'TWS_LIVE': '💰 TWS LIVE TRADING',
    'GATEWAY_LIVE': '💰 Gateway LIVE TRADING',
}

# ========== IB Gateway Connection ==========

# Host (usually localhost)
IB_HOST = '127.0.0.1'

# Port - automatically set based on CONNECTION_MODE
IB_PORT = CONNECTION_PORTS.get(CONNECTION_MODE, 7497)

# Client ID (each connection needs unique ID)
IB_CLIENT_ID = 1

# Connection label for display
CONNECTION_LABEL = CONNECTION_LABELS.get(CONNECTION_MODE, 'Unknown Mode')

# ========== Trading Settings ==========

# Default symbol
DEFAULT_SYMBOL = 'AAPL'

# Default timeframe
DEFAULT_TIMEFRAME = '5 mins'

# Default duration
DEFAULT_DURATION = '1 D'

# Order timeout (seconds)
ORDER_TIMEOUT = 15

# ========== Debug Settings ==========

# Enable verbose order logging
DEBUG_ORDERS = True

# Enable connection debug info
DEBUG_CONNECTION = True

# ========== UI Settings ==========

# Theme colors
PRIMARY_COLOR = '#667eea'
SECONDARY_COLOR = '#764ba2'
GREEN_COLOR = '#26a69a'
RED_COLOR = '#ef5350'
BACKGROUND_COLOR = '#1e1e2e'
PANEL_COLOR = '#2d2d3a'

# ========== Helper Functions ==========

def set_connection_mode(mode: str) -> bool:
    """Change connection mode at runtime
    
    Args:
        mode: One of 'TWS_PAPER', 'GATEWAY_PAPER', 'TWS_LIVE', 'GATEWAY_LIVE'
        
    Returns:
        bool: True if mode is valid and changed
    """
    global CONNECTION_MODE, IB_PORT, CONNECTION_LABEL
    
    if mode not in CONNECTION_PORTS:
        print(f"❌ Invalid connection mode: {mode}")
        print(f"   Valid modes: {', '.join(CONNECTION_PORTS.keys())}")
        return False
    
    CONNECTION_MODE = mode
    IB_PORT = CONNECTION_PORTS[mode]
    CONNECTION_LABEL = CONNECTION_LABELS[mode]
    
    # Warn for live trading
    if 'LIVE' in mode:
        print("⚠️" * 30)
        print("⚠️  WARNING: LIVE TRADING MODE ACTIVATED")
        print("⚠️  THIS WILL USE REAL MONEY!")
        print("⚠️" * 30)
    
    print(f"✅ Connection mode changed to: {CONNECTION_LABEL}")
    print(f"📡 Port: {IB_PORT}")
    return True

def get_available_modes() -> dict:
    """Get all available connection modes with descriptions"""
    return {
        mode: {
            'port': port,
            'label': CONNECTION_LABELS[mode],
            'is_live': 'LIVE' in mode
        }
        for mode, port in CONNECTION_PORTS.items()
    }

def is_live_trading() -> bool:
    """Check if current mode is live trading"""
    return 'LIVE' in CONNECTION_MODE

# ========== Notes ==========

"""
TO SWITCH CONNECTION AT RUNTIME:

In Python code:
    import config
    config.set_connection_mode('TWS_PAPER')  # Switch to TWS paper
    config.set_connection_mode('GATEWAY_PAPER')  # Switch to Gateway paper
    
Via environment variable before starting:
    # Windows PowerShell
    $env:IB_CONNECTION_MODE="TWS_PAPER"
    python app.py
    
    # Linux/Mac
    export IB_CONNECTION_MODE="TWS_PAPER"
    python app.py

CONNECTION MODES:
✅ TWS_PAPER (7497) - Paper Trading TWS - SAFE, DEFAULT
✅ GATEWAY_PAPER (4002) - Paper Trading Gateway - SAFE
⚠️ TWS_LIVE (7496) - Live Trading TWS - REAL MONEY!
⚠️ GATEWAY_LIVE (4001) - Live Trading Gateway - REAL MONEY!

IMPORTANT:
- Paper trading = simulated money (safe for testing)
- Live trading = real money (be very careful!)
- Always test strategies in paper trading first
- Start with small position sizes in live trading
- Always use stop losses
"""

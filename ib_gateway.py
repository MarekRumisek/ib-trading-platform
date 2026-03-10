"""IB Gateway — Unified Facade for Interactive Brokers API

This module provides a simple, self-contained interface for all IB operations.
Import ONLY this module — never import ib_connector or order_handler directly.

Usage:
    import ib_gateway
    
    # Connect
    ib_gateway.connect()
    
    # Get historical candles
    candles = ib_gateway.get_candles('AAPL', '5 mins', count=60)
    
    # Get current tick
    tick = ib_gateway.get_tick('AAPL')
    
    # Subscribe to live ticks
    ib_gateway.subscribe_tick('AAPL')
    tick = ib_gateway.get_tick('AAPL')  # Will have live data
    
    # Account info
    info = ib_gateway.get_account_info()
    
    # Positions
    positions = ib_gateway.get_positions()
    
    # Place order
    result = ib_gateway.place_order('AAPL', 'BUY', 1, 'MARKET')
    
    # Cleanup
    ib_gateway.disconnect()
    
    # Kill all connections (including orphaned processes)
    ib_gateway.kill_all_connections()

Author: AI Assistant
Version: 1.0.0
"""

import logging
import subprocess
import time
import threading
from typing import Optional, Dict, Any, List

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('ib_gateway')

# File handler for debug logging
try:
    import os
    os.makedirs('data', exist_ok=True)
    file_handler = logging.FileHandler('data/debug.log', encoding='utf-8')
    file_handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)-8s | %(message)s'))
    file_handler.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)
except Exception as e:
    logger.warning(f"Could not create log file: {e}")

# Internal imports (these are hidden from callers)
from ib_connector import IBConnector, _TickSubscriber
from order_handler import OrderHandler
import config
from contract_utils import normalize_asset_type, sanitize_symbol, ASSET_TYPE_STOCK


# ================================================================
# Global State (module-level singleton)
# ================================================================

_connector: Optional[IBConnector] = None
_order_handler: Optional[OrderHandler] = None
_client_id_offset: int = 0
_lock = threading.Lock()


# ================================================================
# Connection Management
# ================================================================

def connect(client_id_offset: int = 0) -> bool:
    """
    Connect to IB TWS/Gateway.
    
    Args:
        client_id_offset: Offset for all clientIds (use 10+ for debug.py 
                          to run parallel with app.py)
    
    Returns:
        True if connected successfully, False otherwise
    """
    global _connector, _order_handler, _client_id_offset
    
    with _lock:
        if _connector is not None and _connector.is_connected():
            logger.warning("Already connected")
            return True
        
        _client_id_offset = client_id_offset
        
        try:
            # Temporarily modify config for clientId offset
            original_client_id = config.IB_CLIENT_ID
            config.IB_CLIENT_ID = original_client_id + client_id_offset
            
            # Create connector
            _connector = IBConnector()
            success = _connector.connect()
            
            if not success:
                logger.error("Failed to connect IBConnector")
                config.IB_CLIENT_ID = original_client_id
                return False
            
            # Start order handler
            _order_handler = OrderHandler()
            _order_handler.start()
            
            # Wait for order handler to connect
            time.sleep(1)
            
            logger.info(f"Connected to IB (clientId offset={client_id_offset})")
            return True
            
        except Exception as e:
            logger.error(f"Connection error: {e}")
            return False


def disconnect() -> None:
    """Disconnect from IB TWS/Gateway."""
    global _connector, _order_handler
    
    with _lock:
        try:
            if _order_handler is not None:
                _order_handler.stop()
                _order_handler = None
                logger.info("Order handler stopped")
        except Exception as e:
            logger.error(f"Error stopping order handler: {e}")
        
        try:
            if _connector is not None:
                _connector.disconnect()
                _connector = None
                logger.info("IBConnector disconnected")
        except Exception as e:
            logger.error(f"Error disconnecting: {e}")


def reconnect() -> bool:
    """Disconnect and reconnect."""
    disconnect()
    time.sleep(2)
    return connect(_client_id_offset)


def is_connected() -> bool:
    """Check if connected to IB."""
    return _connector is not None and _connector.is_connected()


# ================================================================
# Historical Data (Candles)
# ================================================================

def get_candles(
    symbol: str,
    timeframe: str = '5 mins',
    count: int = 60,
    asset_type: str = 'STOCK'
) -> List[Dict[str, Any]]:
    """
    Get historical OHLCV candles.
    
    Args:
        symbol: Trading symbol (e.g., 'AAPL', 'EURUSD')
        timeframe: Bar size ('1 min', '5 mins', '15 mins', '1 hour', '1 day')
        count: Approximate number of candles (used to calculate duration)
        asset_type: 'STOCK', 'FOREX', or 'CRYPTO'
    
    Returns:
        List of dicts with keys: time, open, high, low, close, volume
        Empty list on error.
    """
    if not is_connected():
        logger.warning("Not connected")
        return []
    
    try:
        # Map timeframe to duration string
        tf_to_duration = {
            '1 min':   ('1 D', '1 min'),
            '1 mins':  ('1 D', '1 min'),
            '5 mins':  ('1 D', '5 mins'),
            '15 mins': ('1 D', '15 mins'),
            '30 mins': ('1 D', '30 mins'),
            '1 hour':  ('2 D', '1 hour'),
            '1 hours': ('2 D', '1 hour'),
            '4 hours': ('7 D', '4 hours'),
            '1 day':   ('30 D', '1 day'),
            '1 days':  ('30 D', '1 day'),
        }
        
        tf_lower = timeframe.lower().strip()
        if tf_lower in tf_to_duration:
            duration, bar_size = tf_to_duration[tf_lower]
        else:
            # Default fallback
            duration = '1 D'
            bar_size = timeframe
        
        bars = _connector.get_historical_data(
            symbol=symbol,
            duration=duration,
            bar_size=bar_size,
            asset_type=asset_type
        )
        
        if bars:
            logger.info(f"Got {len(bars)} candles for {symbol} ({timeframe})")
        else:
            logger.warning(f"No candles for {symbol}")
        
        return bars if bars else []
        
    except Exception as e:
        logger.error(f"Error getting candles for {symbol}: {e}")
        return []


# ================================================================
# Tick Data (Real-time Prices)
# ================================================================

def get_tick(symbol: str, asset_type: str = 'STOCK') -> Optional[Dict[str, Any]]:
    """
    Get current tick data for a symbol.
    
    Args:
        symbol: Trading symbol
        asset_type: 'STOCK', 'FOREX', or 'CRYPTO'
    
    Returns:
        Dict with keys: price, last, bid, ask, volume, mode
        None if no data available.
    """
    if not is_connected():
        logger.warning("Not connected")
        return None
    
    try:
        ticker = _connector.get_ticker(symbol, asset_type)
        if ticker:
            return ticker
        return None
    except Exception as e:
        logger.error(f"Error getting tick for {symbol}: {e}")
        return None


def subscribe_tick(symbol: str, asset_type: str = 'STOCK') -> None:
    """
    Subscribe to live tick updates for a symbol.
    
    Args:
        symbol: Trading symbol
        asset_type: 'STOCK', 'FOREX', or 'CRYPTO'
    """
    if not is_connected():
        logger.warning("Not connected")
        return
    
    try:
        _connector._tick_sub.set_primary_subscription(symbol, asset_type)
        logger.info(f"Subscribed to {symbol} ({asset_type})")
    except Exception as e:
        logger.error(f"Error subscribing to {symbol}: {e}")


def unsubscribe_tick(symbol: str, asset_type: str = 'STOCK') -> None:
    """
    Unsubscribe from tick updates.
    
    Args:
        symbol: Trading symbol
        asset_type: 'STOCK', 'FOREX', or 'CRYPTO'
    """
    if not is_connected():
        logger.warning("Not connected")
        return
    
    try:
        _connector._tick_sub.unsubscribe(symbol, asset_type)
        logger.info(f"Unsubscribed from {symbol} ({asset_type})")
    except Exception as e:
        logger.error(f"Error unsubscribing from {symbol}: {e}")


def get_tick_diagnostics() -> Dict[str, Any]:
    """
    Get tick subscriber diagnostics.
    
    Returns:
        Dict with mode, iterations, errors, subscribed symbols
    """
    if not is_connected():
        return {'error': 'not connected'}
    
    try:
        ts = _connector._tick_sub
        return {
            'mode': ts.mode,
            'iterations': ts.iterations,
            'connected': ts.is_connected,
            'subscribed': ts.subscribed_symbols,
            'last_errors': ts.get_last_errors()[-5:]
        }
    except Exception as e:
        return {'error': str(e)}


# ================================================================
# Account Information
# ================================================================

def get_account_info() -> Dict[str, Any]:
    """
    Get account information (balance, margin, etc.).
    
    Returns:
        Dict with account details, or empty dict on error.
    """
    if not is_connected():
        logger.warning("Not connected")
        return {}
    
    try:
        info = _connector.get_account_info()
        if info:
            logger.debug(f"Account info: {info.get('account_id', 'unknown')}")
        return info if info else {}
    except Exception as e:
        logger.error(f"Error getting account info: {e}")
        return {}


def get_positions() -> List[Dict[str, Any]]:
    """
    Get current positions.
    
    Returns:
        List of position dicts with keys: symbol, position, avg_cost, 
        market_price, market_value, unrealized_pnl
    """
    if not is_connected():
        logger.warning("Not connected")
        return []
    
    try:
        positions = _connector.get_positions()
        if positions:
            logger.debug(f"Got {len(positions)} positions")
        return positions if positions else []
    except Exception as e:
        logger.error(f"Error getting positions: {e}")
        return []


# ================================================================
# Order Management
# ================================================================

def place_order(
    symbol: str,
    action: str,
    quantity: int,
    order_type: str = 'MARKET',
    limit_price: Optional[float] = None,
    asset_type: str = 'STOCK',
    timeout: float = 30.0
) -> Dict[str, Any]:
    """
    Place an order.
    
    Args:
        symbol: Trading symbol
        action: 'BUY' or 'SELL'
        quantity: Number of shares/contracts
        order_type: 'MARKET' or 'LIMIT'
        limit_price: Required for LIMIT orders
        asset_type: 'STOCK', 'FOREX', or 'CRYPTO'
        timeout: Seconds to wait for order confirmation
    
    Returns:
        Dict with keys: success, order_id, status, message
    """
    if not is_connected():
        logger.warning("Not connected")
        return {'success': False, 'message': 'Not connected'}
    
    if _order_handler is None:
        logger.error("Order handler not initialized")
        return {'success': False, 'message': 'Order handler not initialized'}
    
    try:
        action = action.upper().strip()
        if action not in ('BUY', 'SELL'):
            return {'success': False, 'message': f'Invalid action: {action}'}
        
        order_type = order_type.upper().strip()
        if order_type not in ('MARKET', 'LIMIT'):
            return {'success': False, 'message': f'Invalid order type: {order_type}'}
        
        if order_type == 'LIMIT' and limit_price is None:
            return {'success': False, 'message': 'LIMIT order requires limit_price'}
        
        result = _order_handler.place_order(
            symbol=symbol,
            action=action,
            quantity=quantity,
            order_type=order_type,
            limit_price=limit_price,
            timeout=timeout,
            asset_type=asset_type
        )
        
        if result.get('success'):
            logger.info(f"Order placed: {action} {quantity} {symbol} @ {order_type}")
        else:
            logger.warning(f"Order failed: {result.get('message', 'unknown error')}")
        
        return result
        
    except Exception as e:
        logger.error(f"Error placing order: {e}")
        return {'success': False, 'message': str(e)}


# ================================================================
# Kill All Connections (Cleanup)
# ================================================================

def kill_all_connections() -> Dict[str, Any]:
    """
    Forcefully terminate ALL IB API connections and free ports.
    
    This includes:
    - Current app connections
    - Orphaned processes from previous debug sessions
    - All tick subscriptions
    
    Returns:
        Dict with killed processes and status
    """
    global _connector, _order_handler
    
    result = {
        'killed_processes': [],
        'freed_ports': [],
        'errors': []
    }
    
    logger.warning("KILL ALL CONNECTIONS initiated")
    
    # 1. Disconnect our own connections
    try:
        disconnect()
        logger.info("Own connections disconnected")
    except Exception as e:
        result['errors'].append(f"Disconnect error: {e}")
    
    # 2. Find processes on IB ports
    ib_ports = [7496, 7497, 4001, 4002]
    
    try:
        # Use PowerShell to find processes on IB ports
        ps_cmd = "Get-NetTCPConnection -LocalPort 7496,7497,4001,4002 -ErrorAction SilentlyContinue | Select-Object OwningProcess, LocalPort | ConvertTo-Json"
        
        proc_result = subprocess.run(
            ['powershell', '-Command', ps_cmd],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if proc_result.returncode == 0 and proc_result.stdout.strip():
            import json
            try:
                connections = json.loads(proc_result.stdout)
                if not isinstance(connections, list):
                    connections = [connections]
                
                process_ports = {}
                for conn in connections:
                    pid = conn.get('OwningProcess')
                    port = conn.get('LocalPort')
                    if pid and port:
                        if pid not in process_ports:
                            process_ports[pid] = []
                        process_ports[pid].append(port)
                
                # Kill each unique process
                for pid, ports in process_ports.items():
                    try:
                        kill_result = subprocess.run(
                            ['taskkill', '/F', '/PID', str(pid)],
                            capture_output=True,
                            text=True,
                            timeout=10
                        )
                        if kill_result.returncode == 0:
                            result['killed_processes'].append({
                                'pid': pid,
                                'ports': ports
                            })
                            result['freed_ports'].extend(ports)
                            logger.info(f"Killed process {pid} on ports {ports}")
                        else:
                            result['errors'].append(f"Failed to kill {pid}: {kill_result.stderr.strip()}")
                    except Exception as e:
                        result['errors'].append(f"Error killing {pid}: {e}")
                
            except json.JSONDecodeError as e:
                result['errors'].append(f"JSON parse error: {e}")
        
    except subprocess.TimeoutExpired:
        result['errors'].append("Timeout finding processes")
    except Exception as e:
        result['errors'].append(f"Process scan error: {e}")
    
    # 3. Kill all python processes (nuclear option)
    try:
        kill_python = subprocess.run(
            ['taskkill', '/F', '/IM', 'python.exe'],
            capture_output=True,
            text=True,
            timeout=15
        )
        if kill_python.returncode == 0:
            logger.info("All python.exe processes killed")
            result['killed_processes'].append({'all_python': True})
    except Exception as e:
        result['errors'].append(f"Kill python error: {e}")
    
    # Deduplicate freed ports
    result['freed_ports'] = list(set(result['freed_ports']))
    
    logger.info(f"Kill complete: {len(result['killed_processes'])} processes, ports {result['freed_ports']}")
    return result


# ================================================================
# Convenience Functions
# ================================================================

def get_connection_status() -> Dict[str, Any]:
    """
    Get detailed connection status.
    
    Returns:
        Dict with connection details
    """
    return {
        'connected': is_connected(),
        'client_id_offset': _client_id_offset,
        'config': {
            'host': config.IB_HOST,
            'port': config.IB_PORT,
            'mode': config.CONNECTION_LABEL
        },
        'order_handler_running': _order_handler is not None and _order_handler.running
    }


def test_connection() -> Dict[str, Any]:
    """
    Test IB connection and return diagnostics.
    
    Returns:
        Dict with test results
    """
    result = {
        'success': False,
        'connection': None,
        'account': None,
        'positions': 0,
        'errors': []
    }
    
    try:
        # Try to connect
        if not connect():
            result['errors'].append("Failed to connect")
            return result
        
        result['connection'] = get_connection_status()
        
        # Try to get account info
        account = get_account_info()
        if account:
            result['account'] = account.get('account_id', 'unknown')
        
        # Try to get positions
        positions = get_positions()
        result['positions'] = len(positions)
        
        result['success'] = True
        logger.info("Connection test successful")
        
    except Exception as e:
        result['errors'].append(str(e))
        logger.error(f"Connection test failed: {e}")
    
    return result


# ================================================================
# Additional IBConnector Methods (pass-through)
# ================================================================

def get_latest_price(symbol: str, asset_type: str = 'STOCK') -> float:
    """
    Get the latest price for a symbol.
    
    Args:
        symbol: Trading symbol
        asset_type: 'STOCK', 'FOREX', or 'CRYPTO'
    
    Returns:
        Latest price as float, or 0.0 if unavailable.
    """
    if not is_connected():
        return 0.0
    
    try:
        return _connector.get_latest_price(symbol, asset_type)
    except Exception as e:
        logger.error(f"Error getting latest price for {symbol}: {e}")
        return 0.0


def get_deep_load_status(symbol: str, timeframe: str, asset_type: str = 'STOCK') -> Dict[str, Any]:
    """
    Get status of deep historical data loading.
    
    Args:
        symbol: Trading symbol
        timeframe: Bar size
        asset_type: 'STOCK', 'FOREX', or 'CRYPTO'
    
    Returns:
        Dict with status info
    """
    if not is_connected():
        return {'status': 'disconnected'}
    
    try:
        return _connector.get_deep_load_status(symbol, timeframe, asset_type)
    except Exception as e:
        logger.error(f"Error getting deep load status: {e}")
        return {'status': 'error', 'message': str(e)}


def get_n_bars(
    symbol: str,
    n: int,
    timeframe: str,
    asset_type: str = 'STOCK',
    end_time=None
) -> List[Dict[str, Any]]:
    """
    Get N historical bars.
    
    Args:
        symbol: Trading symbol
        n: Number of bars
        timeframe: Bar size
        asset_type: 'STOCK', 'FOREX', or 'CRYPTO'
        end_time: Optional end timestamp
    
    Returns:
        List of bar dicts
    """
    if not is_connected():
        return []
    
    try:
        return _connector.get_n_bars(symbol, n, timeframe, asset_type, end_time)
    except Exception as e:
        logger.error(f"Error getting {n} bars for {symbol}: {e}")
        return []


def get_fill_avg_cost(symbol: str, asset_type: str = 'STOCK') -> tuple:
    """
    Get average cost from recent fill.
    
    Args:
        symbol: Trading symbol
        asset_type: 'STOCK', 'FOREX', or 'CRYPTO'
    
    Returns:
        Tuple of (avg_cost, commission) or (None, None)
    """
    if not is_connected():
        return None, None
    
    try:
        return _connector.get_fill_avg_cost(symbol, asset_type)
    except Exception as e:
        logger.error(f"Error getting fill avg cost for {symbol}: {e}")
        return None, None


def get_recent_orders(limit: int = 10) -> List[Dict[str, Any]]:
    """
    Get recent orders.
    
    Args:
        limit: Maximum number of orders to return
    
    Returns:
        List of order dicts
    """
    if not is_connected():
        return []
    
    try:
        return _connector.get_recent_orders(limit)
    except Exception as e:
        logger.error(f"Error getting recent orders: {e}")
        return []


def get_account_id() -> Optional[str]:
    """
    Get the current account ID.
    
    Returns:
        Account ID string or None
    """
    if not is_connected():
        return None
    
    try:
        return _connector.account_id
    except Exception as e:
        logger.error(f"Error getting account ID: {e}")
        return None


# ================================================================
# Internal Access (for advanced use)
# ================================================================

def get_tick_subscriber():
    """
    Get the internal tick subscriber for diagnostics.
    
    Returns:
        _TickSubscriber instance or None
    """
    if _connector is None:
        return None
    return _connector._tick_sub


def get_internal_connector():
    """
    Get the internal IBConnector instance.
    
    WARNING: This exposes internal implementation. Use only when
    ib_gateway doesn't provide the needed functionality.
    
    Returns:
        IBConnector instance or None
    """
    return _connector


def get_internal_order_handler():
    """
    Get the internal OrderHandler instance.
    
    WARNING: This exposes internal implementation. Use only when
    ib_gateway doesn't provide the needed functionality.
    
    Returns:
        OrderHandler instance or None
    """
    return _order_handler

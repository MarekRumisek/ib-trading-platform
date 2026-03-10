#!/usr/bin/env python
"""
IB Gateway Debug Tool
=====================

Interactive CLI for testing IB communication.
Imports ONLY ib_gateway — no direct ib_connector or order_handler imports.

Usage:
    python debug.py

Features:
    - Test connection to IB TWS/Gateway
    - Download historical candles (OHLCV)
    - Stream live ticks
    - View account info and positions
    - Place test orders
    - Kill orphaned connections

Author: AI Assistant
Version: 1.0.0
"""

import sys
import time
import json
import threading
from datetime import datetime

# Import ONLY ib_gateway
import ib_gateway


# ================================================================
# Console Utilities
# ================================================================

def clear_screen():
    """Clear the console."""
    print('\033[2J\033[H', end='')


def print_header(title: str):
    """Print a formatted header."""
    width = 60
    print()
    print('=' * width)
    print(f'  {title}')
    print('=' * width)


def print_section(title: str):
    """Print a section title."""
    print()
    print(f'--- {title} ---')
    print()


def print_json(data, indent: int = 2):
    """Pretty print JSON data."""
    if data is None:
        print('  (none)')
    elif isinstance(data, (dict, list)):
        print(json.dumps(data, indent=indent, default=str))
    else:
        print(f'  {data}')


def input_with_default(prompt: str, default: str = '') -> str:
    """Get user input with default value."""
    if default:
        result = input(f'{prompt} [{default}]: ').strip()
        return result if result else default
    return input(f'{prompt}: ').strip()


def pause():
    """Wait for user to press Enter."""
    input('\nPress Enter to continue...')


# ================================================================
# Menu Actions
# ================================================================

def action_test_connection():
    """Test connection to IB."""
    print_header('TEST CONNECTION')
    
    print('Attempting to connect...')
    result = ib_gateway.test_connection()
    
    print_section('Results')
    print(f"  Success: {result.get('success', False)}")
    
    if result.get('connection'):
        conn = result['connection']
        print(f"  Connected: {conn.get('connected', False)}")
        print(f"  Host: {conn.get('config', {}).get('host', '?')}")
        print(f"  Port: {conn.get('config', {}).get('port', '?')}")
        print(f"  Mode: {conn.get('config', {}).get('mode', '?')}")
    
    if result.get('account'):
        print(f"  Account: {result['account']}")
    
    print(f"  Positions: {result.get('positions', 0)}")
    
    if result.get('errors'):
        print_section('Errors')
        for err in result['errors']:
            print(f"  - {err}")
    
    pause()


def action_get_candles():
    """Download historical candles."""
    print_header('GET CANDLES')
    
    symbol = input_with_default('Symbol', 'AAPL').upper()
    timeframe = input_with_default('Timeframe (1 min, 5 mins, 15 mins, 1 hour, 1 day)', '5 mins')
    count = int(input_with_default('Count', '60'))
    asset_type = input_with_default('Asset type (STOCK, FOREX, CRYPTO)', 'STOCK').upper()
    
    print(f'\nFetching {count} {timeframe} candles for {symbol}...')
    
    # Connect if needed
    if not ib_gateway.is_connected():
        print('Connecting...')
        if not ib_gateway.connect(client_id_offset=10):
            print('ERROR: Failed to connect')
            pause()
            return
    
    start_time = time.time()
    candles = ib_gateway.get_candles(symbol, timeframe, count, asset_type)
    elapsed = time.time() - start_time
    
    print(f'\nReceived {len(candles)} candles in {elapsed:.2f}s')
    
    if candles:
        print_section('First 3 candles')
        for c in candles[:3]:
            dt = datetime.fromtimestamp(c['time']).strftime('%Y-%m-%d %H:%M')
            print(f"  {dt} | O:{c['open']:.2f} H:{c['high']:.2f} L:{c['low']:.2f} C:{c['close']:.2f} V:{c.get('volume', 0)}")
        
        print_section('Last 3 candles')
        for c in candles[-3:]:
            dt = datetime.fromtimestamp(c['time']).strftime('%Y-%m-%d %H:%M')
            print(f"  {dt} | O:{c['open']:.2f} H:{c['high']:.2f} L:{c['low']:.2f} C:{c['close']:.2f} V:{c.get('volume', 0)}")
    else:
        print('No candles received')
    
    pause()


def action_stream_ticks():
    """Stream live ticks."""
    print_header('STREAM TICKS')
    
    symbol = input_with_default('Symbol', 'AAPL').upper()
    asset_type = input_with_default('Asset type (STOCK, FOREX, CRYPTO)', 'STOCK').upper()
    duration = int(input_with_default('Duration (seconds)', '30'))
    
    # Connect if needed
    if not ib_gateway.is_connected():
        print('Connecting...')
        if not ib_gateway.connect(client_id_offset=10):
            print('ERROR: Failed to connect')
            pause()
            return
    
    print(f'\nSubscribing to {symbol} ticks for {duration} seconds...')
    ib_gateway.subscribe_tick(symbol, asset_type)
    
    # Stream ticks
    start_time = time.time()
    last_price = None
    tick_count = 0
    
    print('\nTick stream (Ctrl+C to stop):')
    print('-' * 50)
    
    try:
        while time.time() - start_time < duration:
            tick = ib_gateway.get_tick(symbol, asset_type)
            
            if tick:
                price = tick.get('price', 0) or tick.get('last', 0) or tick.get('close', 0)
                bid = tick.get('bid', 0)
                ask = tick.get('ask', 0)
                volume = tick.get('volume', 0)
                mode = tick.get('mode', '?')
                
                if price != last_price:
                    ts = datetime.now().strftime('%H:%M:%S')
                    print(f"  [{ts}] {symbol}: {price:.4f} | B:{bid:.4f} A:{ask:.4f} | mode={mode}")
                    last_price = price
                    tick_count += 1
            
            time.sleep(0.5)
    
    except KeyboardInterrupt:
        print('\nInterrupted by user')
    
    print('-' * 50)
    print(f'Received {tick_count} price updates')
    
    ib_gateway.unsubscribe_tick(symbol, asset_type)
    print(f'Unsubscribed from {symbol}')
    
    pause()


def action_account_info():
    """Show account information."""
    print_header('ACCOUNT INFO')
    
    # Connect if needed
    if not ib_gateway.is_connected():
        print('Connecting...')
        if not ib_gateway.connect(client_id_offset=10):
            print('ERROR: Failed to connect')
            pause()
            return
    
    info = ib_gateway.get_account_info()
    
    if info:
        print_section('Account Details')
        for key, value in sorted(info.items()):
            print(f"  {key}: {value}")
    else:
        print('No account info available')
    
    pause()


def action_positions():
    """Show current positions."""
    print_header('POSITIONS')
    
    # Connect if needed
    if not ib_gateway.is_connected():
        print('Connecting...')
        if not ib_gateway.connect(client_id_offset=10):
            print('ERROR: Failed to connect')
            pause()
            return
    
    positions = ib_gateway.get_positions()
    
    if positions:
        print_section(f'Open Positions ({len(positions)})')
        for pos in positions:
            sym = pos.get('symbol', '?')
            qty = pos.get('position', 0)
            avg = pos.get('avg_cost', 0)
            mv = pos.get('market_value', 0)
            upnl = pos.get('unrealized_pnl', 0)
            upnl_pct = pos.get('unrealized_pnl_pct', 0)
            
            pnl_sign = '+' if upnl >= 0 else ''
            print(f"  {sym}: {qty} shares @ ${avg:.2f}")
            print(f"       MV: ${mv:.2f} | PnL: {pnl_sign}${upnl:.2f} ({pnl_sign}{upnl_pct:.2f}%)")
    else:
        print('No open positions')
    
    pause()


def action_place_order():
    """Place a test order."""
    print_header('PLACE ORDER')
    
    print('⚠️  WARNING: This will place a REAL order on your IB account!')
    confirm = input('Type "YES" to continue: ').strip()
    if confirm != 'YES':
        print('Cancelled')
        pause()
        return
    
    symbol = input_with_default('Symbol', 'AAPL').upper()
    action = input_with_default('Action (BUY/SELL)', 'BUY').upper()
    quantity = int(input_with_default('Quantity', '1'))
    order_type = input_with_default('Order type (MARKET/LIMIT)', 'MARKET').upper()
    asset_type = input_with_default('Asset type (STOCK, FOREX, CRYPTO)', 'STOCK').upper()
    
    limit_price = None
    if order_type == 'LIMIT':
        limit_price = float(input_with_default('Limit price', '0'))
    
    # Connect if needed
    if not ib_gateway.is_connected():
        print('Connecting...')
        if not ib_gateway.connect(client_id_offset=10):
            print('ERROR: Failed to connect')
            pause()
            return
    
    print(f'\nPlacing {action} {quantity} {symbol} @ {order_type}...')
    
    result = ib_gateway.place_order(
        symbol=symbol,
        action=action,
        quantity=quantity,
        order_type=order_type,
        limit_price=limit_price,
        asset_type=asset_type
    )
    
    print_section('Order Result')
    print_json(result)
    
    pause()


def action_tick_diagnostics():
    """Show tick subscriber diagnostics."""
    print_header('TICK DIAGNOSTICS')
    
    # Connect if needed
    if not ib_gateway.is_connected():
        print('Connecting...')
        if not ib_gateway.connect(client_id_offset=10):
            print('ERROR: Failed to connect')
            pause()
            return
    
    diag = ib_gateway.get_tick_diagnostics()
    
    print_section('Tick Subscriber Status')
    print_json(diag)
    
    pause()


def action_kill_connections():
    """Kill all IB connections."""
    print_header('KILL ALL CONNECTIONS')
    
    print('⚠️  WARNING: This will kill ALL IB connections and Python processes!')
    print('This includes the running app.py if it is active.')
    confirm = input('Type "KILL" to confirm: ').strip()
    if confirm != 'KILL':
        print('Cancelled')
        pause()
        return
    
    result = ib_gateway.kill_all_connections()
    
    print_section('Results')
    print_json(result)
    
    pause()


def action_disconnect():
    """Disconnect from IB."""
    print_header('DISCONNECT')
    
    ib_gateway.disconnect()
    print('Disconnected')
    
    pause()


# ================================================================
# Main Menu
# ================================================================

def show_menu():
    """Display the main menu."""
    clear_screen()
    print_header('IB GATEWAY DEBUG TOOL')
    
    # Show connection status
    status = 'CONNECTED' if ib_gateway.is_connected() else 'DISCONNECTED'
    print(f'\n  Status: {status}')
    
    print('''
  1. Test Connection
  2. Get Candles (OHLCV)
  3. Stream Ticks
  4. Account Info
  5. Positions
  6. Place Order
  7. Tick Diagnostics
  8. Kill All Connections
  9. Disconnect
  0. Exit
''')


def main():
    """Main entry point."""
    actions = {
        '1': action_test_connection,
        '2': action_get_candles,
        '3': action_stream_ticks,
        '4': action_account_info,
        '5': action_positions,
        '6': action_place_order,
        '7': action_tick_diagnostics,
        '8': action_kill_connections,
        '9': action_disconnect,
        '0': None,
    }
    
    while True:
        show_menu()
        choice = input('Select option: ').strip()
        
        if choice == '0':
            print('\nExiting...')
            ib_gateway.disconnect()
            break
        
        action = actions.get(choice)
        if action:
            try:
                action()
            except Exception as e:
                print(f'\nERROR: {e}')
                pause()
        else:
            print('Invalid option')
            time.sleep(1)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nInterrupted')
        ib_gateway.disconnect()
        sys.exit(0)

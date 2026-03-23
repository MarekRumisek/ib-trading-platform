"""Trades Blueprint - Trade Management Endpoints

Provides trade management functionality:
- Get open trades
- Get active trade lines
- Get trade history
- Close trades
- Breakeven updates
- Trade patches
"""

from flask import Blueprint, jsonify, request
from modules.trade_tracker import trade_tracker
import ib_gateway
from contract_utils import normalize_asset_type

trades_bp = Blueprint('trades', __name__, url_prefix='/api/trades')


@trades_bp.route('/open', methods=['GET'])
def get_open_trades():
    """Get all open trades with live P&L from IB."""
    trades = trade_tracker.get_open_trades()
    
    # Get IB positions for live P&L
    ib_positions = ib_gateway.get_positions() if ib_gateway.is_connected() else []
    
    # Build lookup for IB positions by symbol+asset_type
    ib_pos_by_key = {}
    for pos in ib_positions:
        sym = pos.get('symbol', '').upper()
        asset_type = normalize_asset_type(pos.get('asset_type', 'STOCK'))
        key = f"{sym}_{asset_type}"
        ib_pos_by_key[key] = pos
    
    for t in trades:
        t['entry_time_fmt'] = trade_tracker.fmt_time(t.get('entry_time'))
        
        # Enrich with live IB data
        sym = t.get('symbol', '').upper()
        asset_type = normalize_asset_type(t.get('asset_type', 'STOCK'))
        key = f"{sym}_{asset_type}"
        ib_pos = ib_pos_by_key.get(key)
        
        if ib_pos:
            # Note: IB positions use underscore keys: unrealized_pnl, market_price, avg_cost
            t['pnl'] = ib_pos.get('unrealized_pnl')
            t['market_price'] = ib_pos.get('market_price')
            t['avg_cost'] = ib_pos.get('avg_cost')
            t['market_value'] = ib_pos.get('market_value')
            t['position'] = ib_pos.get('position')
        else:
            t['pnl'] = None
            t['market_price'] = None
            t['avg_cost'] = t.get('avg_cost')
            t['market_value'] = None
            t['position'] = t.get('qty')
    
    return jsonify({'ok': True, 'trades': trades})


@trades_bp.route('/active_lines', methods=['GET'])
def get_active_lines():
    """Get active trade lines for a symbol."""
    sym = (request.args.get('symbol') or 'AAPL').upper()
    asset_type = normalize_asset_type(request.args.get('asset_type', 'STOCK'))
    trades = []

    # Issue #4 + #3: use avgCost from IB positions (live) or from stored avg_cost in trade record.
    # Priority: IB live avgCost > stored avg_cost from fills > fill_price (entry_price).
    ib_positions = ib_gateway.get_positions() if ib_gateway.is_connected() else []

    for t in trade_tracker.get_open_trades():
        if t.get('symbol') != sym:
            continue
        if normalize_asset_type(t.get('asset_type', 'STOCK')) != asset_type:
            continue
        ib_pos = next((p for p in ib_positions if p['symbol'] == sym and
                       normalize_asset_type(p.get('asset_type', 'STOCK')) == asset_type), None)
        avg_cost_used = False
        # Fallback chain: IB live avgCost → stored avg_cost from fills → fill_price
        if ib_pos and ib_pos.get('avgCost'):
            entry_price = float(ib_pos['avgCost'])
            avg_cost_used = True
        elif t.get('avg_cost'):
            entry_price = float(t['avg_cost'])
            avg_cost_used = True
        else:
            entry_price = t.get('entry_price')
        trades.append({
            'symbol': t.get('symbol'),
            'asset_type': normalize_asset_type(t.get('asset_type', 'STOCK')),
            'entry_price': entry_price,
            'sl': t.get('sl'),
            'tp': t.get('tp'),
            'side': t.get('side'),
            'avg_cost_used': avg_cost_used,
        })

    return jsonify(trades)


@trades_bp.route('/history', methods=['GET'])
def get_history():
    """Get trade history."""
    limit = int(request.args.get('limit', 50))
    trades = trade_tracker.get_history(limit=limit)
    for t in trades:
        t['entry_time_fmt'] = trade_tracker.fmt_time(t.get('entry_time'))
        t['exit_time_fmt'] = trade_tracker.fmt_time(t.get('exit_time'))
    return jsonify({'ok': True, 'trades': trades})


@trades_bp.route('/close/<trade_id>', methods=['POST'])
def close_trade(trade_id):
    """Close a specific trade.
    
    Closes trade in trade_tracker AND sends closing order to IB if connected.
    """
    body = request.get_json(silent=True) or {}
    override_exit_price = body.get('exit_price')

    # 1. Load trade record
    trade = trade_tracker.get_trade(trade_id)
    if not trade:
        return jsonify({'ok': False, 'error': 'trade_not_found'}), 404

    exit_price = override_exit_price
    ib_order_id = None
    warnings = []

    # 2. Check IB connection
    if ib_gateway.is_connected():
        try:
            # 3a. Get current IB position
            ib_positions = ib_gateway.get_positions()
            ib_pos = next((p for p in ib_positions
                          if p.get('symbol', '').upper() == trade.get('symbol', '').upper()), None)

            if ib_pos:
                # 3b. Position exists in IB → send closing order
                position_qty = abs(ib_pos.get('position', 0))
                if position_qty > 0:
                    # Opposite side to close
                    side = trade.get('side', 'BUY').upper()
                    if side == 'BUY':
                        close_action = 'SELL'
                    else:  # SELL → close short
                        close_action = 'BUY'

                    asset_type = trade.get('asset_type', 'STOCK')

                    # Send closing order
                    result = ib_gateway.place_order(
                        symbol=trade['symbol'],
                        action=close_action,
                        quantity=position_qty,
                        order_type='MARKET',
                        asset_type=asset_type,
                        timeout=10.0
                    )

                    if result.get('success'):
                        ib_order_id = result.get('order_id')
                        # Use fill price if available
                        fill_price = result.get('fill_price')
                        if fill_price and fill_price > 0:
                            exit_price = fill_price
                        else:
                            # Fallback to ticker if no fill price
                            if not exit_price:
                                ticker = ib_gateway.get_tick(trade['symbol'], asset_type)
                                if ticker:
                                    exit_price = ticker.get('price') or ticker.get('last')
                    else:
                        warnings.append('ib_close_failed')
                        logger.warning(f"IB close order failed: {result.get('message', 'unknown')}")
                        # Continue with local close only
            else:
                # 3d. Position not in IB → just close locally (may have been closed externally)
                warnings.append('ib_position_not_found')
        except Exception as e:
            warnings.append('ib_error')
            logger.error(f"Error closing trade via IB: {e}")
            # Continue with local close only
    else:
        # IB not connected → local close only
        warnings.append('ib_not_connected_local_only')

    # 4. Determine exit price if still missing
    if not exit_price:
        ticker = ib_gateway.get_tick(trade['symbol'], trade.get('asset_type', 'STOCK'))
        if ticker:
            exit_price = ticker.get('price') or ticker.get('last')
        if not exit_price and trade.get('entry_price'):
            exit_price = trade.get('entry_price')

    if not exit_price:
        return jsonify({'ok': False, 'error': 'exit_price_missing'}), 400

    # 5. Close trade locally
    updated = trade_tracker.close_trade(trade_id, exit_price)
    if not updated:
        return jsonify({'ok': False, 'error': 'trade_not_found_or_already_closed'}), 404

    updated['exit_time_fmt'] = trade_tracker.fmt_time(updated.get('exit_time'))
    updated['entry_time_fmt'] = trade_tracker.fmt_time(updated.get('entry_time'))

    # 6. Build response
    response = {'ok': True, 'trade': updated}
    if ib_order_id:
        response['ib_order_id'] = ib_order_id
    if warnings:
        if 'ib_close_failed' in warnings:
            response['warning'] = 'ib_close_failed'
            response['local_closed'] = True
        elif 'ib_not_connected_local_only' in warnings:
            response['warning'] = 'ib_not_connected_local_only'
        elif 'ib_position_not_found' in warnings:
            response['warning'] = 'ib_position_not_found'
        elif 'ib_error' in warnings:
            response['warning'] = 'ib_error'
            response['local_closed'] = True

    return jsonify(response)


@trades_bp.route('/close_all', methods=['POST'])
def close_all_trades():
    """Close all open trades.
    
    Iterates over all open trades and closes each one via IB if connected.
    Uses same logic as close_trade() for each trade.
    """
    open_trades = trade_tracker.get_open_trades()
    if not open_trades:
        return jsonify({'ok': True, 'closed': 0, 'trades': [], 'warnings': []})

    closed_trades = []
    warnings = []
    ib_closed = 0
    local_only = 0

    # Get IB positions once for all trades
    ib_connected = ib_gateway.is_connected()
    ib_positions = ib_gateway.get_positions() if ib_connected else []
    ib_pos_by_symbol = {p.get('symbol', '').upper(): p for p in ib_positions}

    for trade in open_trades:
        trade_id = trade.get('id')
        if not trade_id:
            continue

        exit_price = None
        ib_order_id = None
        trade_warning = None

        # Check IB connection
        if ib_connected:
            try:
                ib_pos = ib_pos_by_symbol.get(trade.get('symbol', '').upper())

                if ib_pos:
                    position_qty = abs(ib_pos.get('position', 0))
                    if position_qty > 0:
                        side = trade.get('side', 'BUY').upper()
                        close_action = 'SELL' if side == 'BUY' else 'BUY'
                        asset_type = trade.get('asset_type', 'STOCK')

                        result = ib_gateway.place_order(
                            symbol=trade['symbol'],
                            action=close_action,
                            quantity=position_qty,
                            order_type='MARKET',
                            asset_type=asset_type,
                            timeout=10.0
                        )

                        if result.get('success'):
                            ib_order_id = result.get('order_id')
                            fill_price = result.get('fill_price')
                            if fill_price and fill_price > 0:
                                exit_price = fill_price
                            ib_closed += 1
                        else:
                            trade_warning = 'ib_close_failed'
                            local_only += 1
                else:
                    trade_warning = 'ib_position_not_found'
            except Exception as e:
                trade_warning = 'ib_error'
                local_only += 1
                logger.error(f"Error closing trade {trade_id} via IB: {e}")
        else:
            trade_warning = 'ib_not_connected_local_only'
            local_only += 1

        # Get exit price if missing
        if not exit_price:
            ticker = ib_gateway.get_tick(trade['symbol'], trade.get('asset_type', 'STOCK'))
            if ticker:
                exit_price = ticker.get('price') or ticker.get('last')
            if not exit_price and trade.get('entry_price'):
                exit_price = trade.get('entry_price')

        # Close trade locally
        if exit_price:
            updated = trade_tracker.close_trade(trade_id, exit_price)
            if updated:
                updated['exit_time_fmt'] = trade_tracker.fmt_time(updated.get('exit_time'))
                updated['entry_time_fmt'] = trade_tracker.fmt_time(updated.get('entry_time'))
                if ib_order_id:
                    updated['ib_order_id'] = ib_order_id
                if trade_warning:
                    updated['warning'] = trade_warning
                closed_trades.append(updated)
        else:
            warnings.append(f"Could not determine exit_price for trade {trade_id}")

    response = {
        'ok': True,
        'closed': len(closed_trades),
        'trades': closed_trades
    }
    if warnings:
        response['warnings'] = warnings
    if ib_closed > 0:
        response['ib_closed'] = ib_closed
    if local_only > 0:
        response['local_only'] = local_only

    return jsonify(response)


@trades_bp.route('/breakeven', methods=['GET'])
def get_breakeven():
    """Get breakeven information for open trades."""
    sym = (request.args.get('symbol') or 'AAPL').upper()
    asset_type = normalize_asset_type(request.args.get('asset_type', 'STOCK'))
    
    breakeven_trades = []
    for t in trade_tracker.get_open_trades():
        if t.get('symbol') != sym:
            continue
        if normalize_asset_type(t.get('asset_type', 'STOCK')) != asset_type:
            continue
        
        entry_price = t.get('entry_price')
        side = t.get('side', 'BUY').upper()
        
        # Calculate breakeven price (same as entry for stock, accounting for spread for forex)
        if side == 'BUY':
            breakeven = entry_price
        else:  # SELL
            breakeven = entry_price
        
        breakeven_trades.append({
            'trade_id': t.get('id'),
            'symbol': sym,
            'asset_type': asset_type,
            'side': side,
            'entry_price': entry_price,
            'breakeven_price': breakeven,
            'current_pnl': t.get('pnl', 0)
        })
    
    return jsonify({'ok': True, 'trades': breakeven_trades})


@trades_bp.route('/patch', methods=['PATCH'])
def patch_trade():
    """Patch/update trade information."""
    data = request.get_json() or {}
    trade_id = data.get('trade_id')
    
    if not trade_id:
        return jsonify({'ok': False, 'error': 'trade_id is required'}), 400
    
    trade = trade_tracker.get_trade(trade_id)
    if not trade:
        return jsonify({'ok': False, 'error': 'trade_not_found'}), 404
    
    # Update allowed fields
    updates = {}
    if 'sl' in data:
        updates['sl'] = data['sl']
    if 'tp' in data:
        updates['tp'] = data['tp']
    if 'notes' in data:
        updates['notes'] = data['notes']
    
    if updates:
        updated = trade_tracker.update_trade(trade_id, updates)
        if updated:
            return jsonify({'ok': True, 'trade': updated})
        else:
            return jsonify({'ok': False, 'error': 'failed_to_update_trade'}), 500
    
    return jsonify({'ok': True, 'trade': trade})


@trades_bp.route('/<trade_id>', methods=['GET'])
def get_trade(trade_id):
    """Get a specific trade by ID."""
    trade = trade_tracker.get_trade(trade_id)
    if not trade:
        return jsonify({'ok': False, 'error': 'trade_not_found'}), 404
    
    trade['entry_time_fmt'] = trade_tracker.fmt_time(trade.get('entry_time'))
    trade['exit_time_fmt'] = trade_tracker.fmt_time(trade.get('exit_time'))
    return jsonify({'ok': True, 'trade': trade})

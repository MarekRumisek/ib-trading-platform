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
    """Get all open trades."""
    trades = trade_tracker.get_open_trades()
    for t in trades:
        t['entry_time_fmt'] = trade_tracker.fmt_time(t.get('entry_time'))
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
    """Close a specific trade."""
    body = request.get_json(silent=True) or {}
    exit_price = body.get('exit_price')

    if not exit_price:
        trade = trade_tracker.get_trade(trade_id)
        if trade:
            ticker = ib_gateway.get_tick(trade['symbol'], trade.get('asset_type', 'STOCK'))
            if ticker:
                exit_price = ticker.get('price') or ticker.get('last') or trade.get('entry_price')

    if not exit_price:
        return jsonify({'ok': False, 'error': 'exit_price_missing'}), 400

    updated = trade_tracker.close_trade(trade_id, exit_price)
    if not updated:
        return jsonify({'ok': False, 'error': 'trade_not_found_or_already_closed'}), 404

    updated['exit_time_fmt'] = trade_tracker.fmt_time(updated.get('exit_time'))
    updated['entry_time_fmt'] = trade_tracker.fmt_time(updated.get('entry_time'))
    return jsonify({'ok': True, 'trade': updated})


@trades_bp.route('/close_all', methods=['POST'])
def close_all_trades():
    """Close all open trades."""
    open_trades = trade_tracker.get_open_trades()
    symbols = list({(t['symbol'], t.get('asset_type', 'STOCK')) for t in open_trades})
    exit_prices = {}
    for sym, asset_type in symbols:
        ticker = ib_gateway.get_tick(sym, asset_type)
        if ticker:
            p = ticker.get('price') or ticker.get('last')
            if p:
                exit_prices[sym] = p
    closed = trade_tracker.close_all_open(exit_prices)
    return jsonify({'ok': True, 'closed': len(closed), 'trades': closed})


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

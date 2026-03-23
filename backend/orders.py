"""Orders Blueprint - Order Management Endpoints

Provides order management functionality:
- Place new orders
- Cancel orders
- Modify existing orders
- Get order status and history
- Get open positions
"""

from flask import Blueprint, jsonify, request
import ib_gateway
from contract_utils import normalize_asset_type

orders_bp = Blueprint('orders', __name__, url_prefix='/api')


@orders_bp.route('/orders', methods=['GET', 'POST'])
def orders_endpoint():
    """Get all orders (GET) or place a new order (POST)."""
    # Handle POST request - place new order
    if request.method == 'POST':
        data = request.get_json() or {}
        symbol = data.get('symbol')
        side = data.get('action') or data.get('side')  # UI sends 'action', internal uses 'side'
        qty = data.get('quantity')
        order_type = data.get('order_type', 'MARKET')
        limit_price = data.get('limit_price')
        sl = data.get('sl')
        tp = data.get('tp')
        note = data.get('note')
        asset_type = normalize_asset_type(data.get('asset_type', 'STOCK'))
        exchange = data.get('exchange', 'SMART')
        
        if not symbol or not side or not qty:
            return jsonify({'ok': False, 'error': 'missing required fields: symbol, action, quantity'}), 400
        
        result = ib_gateway.place_order(
            symbol=symbol.upper(),
            action=side.upper(),
            quantity=int(qty),
            order_type=order_type.upper() if order_type else 'MARKET',
            limit_price=limit_price,
            asset_type=asset_type
        )
        
        if result and result.get('order_id'):
            # Record the trade
            trade_recorded = False
            trade_id = None
            try:
                from modules.trade_tracker import trade_tracker
                # Use fill_price from result if available, otherwise 0 (will be updated by sync)
                entry_price = result.get('fill_price') or result.get('avgFillPrice') or 0
                trade = trade_tracker.open_trade(
                    symbol=symbol.upper(),
                    side=side.upper(),
                    qty=int(qty),
                    entry_price=entry_price,
                    order_type=order_type.upper() if order_type else 'MARKET',
                    sl=sl,
                    tp=tp,
                    note=note,
                    asset_type=asset_type,
                    avg_cost=entry_price if entry_price else None
                )
                trade_id = trade.get('id') if trade else None
                trade_recorded = True
                
                # If order is Filled but fill_price was 0, try to get actual fill price
                if result.get('status') == 'Filled' and entry_price == 0 and result.get('avgFillPrice'):
                    fill_price = result.get('avgFillPrice')
                    if trade_id:
                        trade_tracker.update_trade(trade_id, entry_price=fill_price, avg_cost=fill_price)
                        trade_recorded = True
                        
            except Exception as e:
                print(f"Error recording trade: {e}")
            
            return jsonify({
                'ok': True,
                'order_id': result.get('order_id'),
                'fill_price': result.get('fill_price') or result.get('avgFillPrice'),
                'status': result.get('status'),
                'message': f"Order placed successfully. Trade recorded: {trade_recorded}"
            })
        else:
            return jsonify({'ok': False, 'error': result.get('error', 'order failed')}), 500
    
    # Handle GET request - return all orders
    status = request.args.get('status', 'all')
    
    if not ib_gateway.is_connected():
        return jsonify({'ok': True, 'orders': []})
    
    try:
        orders = ib_gateway.get_recent_orders(limit=50)
        return jsonify({
            'ok': True,
            'status': status,
            'orders': orders or []
        })
    except Exception as e:
        return jsonify({'ok': True, 'orders': []})


@orders_bp.route('/orders/open', methods=['GET'])
def get_open_orders():
    """Get all open orders."""
    if not ib_gateway.is_connected():
        return jsonify({'ok': True, 'orders': []})
    
    try:
        orders = ib_gateway.get_recent_orders(limit=50)
        # Filter to only open orders (status api.BarDataConsumer.ORDER_STATUS)
        open_orders = [o for o in (orders or []) if o.get('status') in ('Submitted', 'PendingSubmit', 'PendingCancel', 'ApiPending', 'ApiCancelled')]
        return jsonify({
            'ok': True,
            'orders': open_orders
        })
    except Exception as e:
        return jsonify({'ok': True, 'orders': []})


@orders_bp.route('/orders/place', methods=['POST'])
def place_order():
    """Place a new order."""
    data = request.get_json() or {}
    symbol = data.get('symbol')
    side = data.get('side')  # BUY or SELL
    qty = data.get('qty') or data.get('quantity')
    order_type = data.get('order_type', 'MARKET')
    limit_price = data.get('limit_price')
    asset_type = normalize_asset_type(data.get('asset_type', 'STOCK'))
    
    if not symbol or not side or not qty:
        return jsonify({'ok': False, 'error': 'missing required fields: symbol, side, qty'}), 400
    
    result = ib_gateway.place_order(
        symbol=symbol.upper(),
        action=side.upper(),
        quantity=int(qty),
        order_type=order_type.upper(),
        limit_price=limit_price,
        asset_type=asset_type
    )
    
    if result and result.get('order_id'):
        return jsonify({'ok': True, 'order': result})
    else:
        return jsonify({'ok': False, 'error': result.get('error', 'order failed')}), 500


@orders_bp.route('/orders/<order_id>', methods=['DELETE'])
def cancel_order(order_id):
    """Cancel an existing order."""
    if not ib_gateway.is_connected():
        return jsonify({'error': 'not connected to IB'}), 503
    
    # Try to get the internal connector to cancel the order
    try:
        connector = ib_gateway.get_internal_connector()
        if connector and hasattr(connector, 'ib') and connector.ib.isConnected():
            # Find the order in open orders
            order_id_int = None
            try:
                order_id_int = int(order_id)
            except ValueError:
                pass
            
            if order_id_int is None:
                return jsonify({'ok': False, 'error': 'order_not_found'}), 404
            
            # Get open orders and check if the order exists
            try:
                open_orders = connector.ib.openOrders()
                order_exists = any(
                    hasattr(o.order, 'orderId') and o.order.orderId == order_id_int 
                    for o in open_orders
                )
            except Exception:
                order_exists = False
            
            if not order_exists:
                return jsonify({'ok': False, 'error': 'order_not_found'}), 404
            
            # Cancel the order
            try:
                connector.ib.cancelOrder(order_id_int)
                return jsonify({'ok': True, 'order_id': order_id, 'status': 'cancelled'})
            except Exception as e:
                error_msg = str(e)
                # Check for IB error codes 201 (rejected) or 202 (cancelled)
                if '201' in error_msg or 'order rejected' in error_msg.lower():
                    return jsonify({'ok': False, 'error': 'order_rejected'}), 400
                if '202' in error_msg or 'cancelled' in error_msg.lower():
                    return jsonify({'ok': True, 'order_id': order_id, 'status': 'already_cancelled'})
                return jsonify({'ok': False, 'error': 'order_not_found'}), 404
        else:
            return jsonify({'ok': False, 'error': 'order_not_found'}), 404
    except Exception as e:
        return jsonify({'ok': False, 'error': 'order_not_found'}), 404


@orders_bp.route('/orders/<order_id>', methods=['PATCH'])
def modify_order(order_id):
    """Modify an existing order."""
    data = request.get_json() or {}
    
    if not ib_gateway.is_connected():
        return jsonify({'error': 'not connected to IB'}), 503
    
    result = ib_gateway.modify_order(order_id, data)
    if result:
        return jsonify({'ok': True, 'order_id': order_id, 'modifications': data})
    else:
        return jsonify({'ok': False, 'error': 'failed to modify order'}), 500


@orders_bp.route('/positions', methods=['GET'])
def get_positions():
    """Get current positions."""
    if not ib_gateway.is_connected():
        return jsonify({'error': 'not connected to IB'}), 503
    
    positions = ib_gateway.get_positions()
    return jsonify({'positions': positions})

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


@orders_bp.route('/orders', methods=['GET'])
def get_orders():
    """Get all orders (open and historical)."""
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

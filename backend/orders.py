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
        return jsonify({'error': 'not connected to IB'}), 503
    
    orders = ib_gateway.get_orders()
    return jsonify({
        'status': status,
        'orders': orders
    })


@orders_bp.route('/orders/open', methods=['GET'])
def get_open_orders():
    """Get all open orders."""
    if not ib_gateway.is_connected():
        return jsonify({'error': 'not connected to IB'}), 503
    
    orders = ib_gateway.get_open_orders()
    return jsonify({
        'orders': orders
    })


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
    
    result = ib_gateway.cancel_order(order_id)
    if result:
        return jsonify({'ok': True, 'order_id': order_id, 'status': 'cancelled'})
    else:
        return jsonify({'ok': False, 'error': 'failed to cancel order'}), 500


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

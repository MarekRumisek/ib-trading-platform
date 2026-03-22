"""API Blueprint - Core API Endpoints

Provides fundamental API functionality:
- Health check and status endpoints
- System information
- Configuration management
- IB connection status
- Market hours
- Account information
"""

from flask import Blueprint, jsonify, request
import ib_gateway
from modules.market_hours import get_session_display

api_bp = Blueprint('api', __name__, url_prefix='/api')


@api_bp.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({'status': 'healthy', 'service': 'ib-trading-platform'})


@api_bp.route('/status', methods=['GET'])
def status():
    """System status endpoint."""
    return jsonify({
        'status': 'operational',
        'version': '1.0.0'
    })


@api_bp.route('/info', methods=['GET'])
def info():
    """System information endpoint."""
    return jsonify({
        'platform': 'IB Trading Platform',
        'version': '1.0.0'
    })


@api_bp.route('/connection/status', methods=['GET'])
def connection_status():
    """Get IB connection status."""
    status = ib_gateway.get_connection_status()
    return jsonify(status)


@api_bp.route('/market/hours', methods=['GET'])
def market_hours():
    """Get current market session hours and status."""
    timezone = request.args.get('timezone', 'Europe/Prague')
    session_info = get_session_display(timezone)
    return jsonify(session_info)


@api_bp.route('/account/info', methods=['GET'])
def account_info():
    """Get IB account information."""
    info = ib_gateway.get_account_info()
    if not info:
        return jsonify({'error': 'not connected or no account info available'}), 503
    return jsonify(info)

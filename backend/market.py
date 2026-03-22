"""Market Blueprint - Market Data Endpoints

Provides market data functionality:
- Historical candle data
- Real-time tick data
- Symbol search and resolution
- Market hours information
"""

from flask import Blueprint, jsonify, request
from datetime import datetime
import ib_gateway
from contract_utils import normalize_asset_type
from modules.data_store import data_store
from modules.indicators import SMA, EMA, RSI, MACD
from contract_utils import get_cache_symbol

market_bp = Blueprint('market', __name__, url_prefix='/api')


@market_bp.route('/tick/<symbol>', methods=['GET'])
def get_tick(symbol):
    """Get real-time tick data for a symbol."""
    sym = symbol.upper()
    asset_type = normalize_asset_type(request.args.get('asset_type', 'STOCK'))
    price = ib_gateway.get_latest_price(sym, asset_type)
    return jsonify({'time': int(datetime.now().timestamp()), 'price': price, 'asset_type': asset_type})


@market_bp.route('/bars/<symbol>', methods=['GET'])
def get_bars(symbol):
    """Get historical bar data for a symbol."""
    sym = symbol.upper()
    timeframe = request.args.get('timeframe', '5 mins')
    count = int(request.args.get('count', 100))
    asset_type = normalize_asset_type(request.args.get('asset_type', 'STOCK'))
    
    cache_symbol = get_cache_symbol(sym, asset_type)
    bars = data_store.get_bars(cache_symbol, timeframe)
    
    if bars is None or len(bars) == 0:
        return jsonify({'symbol': sym, 'timeframe': timeframe, 'bars': [], 'asset_type': asset_type})
    
    # Return most recent bars based on count
    recent_bars = bars[-count:] if len(bars) > count else bars
    
    formatted_bars = []
    for bar in recent_bars:
        formatted_bars.append({
            'time': bar.name.timestamp() if hasattr(bar.name, 'timestamp') else int(bar.name),
            'open': float(bar.Open),
            'high': float(bar.High),
            'low': float(bar.Low),
            'close': float(bar.Close),
            'volume': int(bar.Volume) if hasattr(bar, 'Volume') and bar.Volume else 0
        })
    
    return jsonify({
        'symbol': sym,
        'timeframe': timeframe,
        'bars': formatted_bars,
        'asset_type': asset_type,
        'count': len(formatted_bars)
    })


@market_bp.route('/deep_load_status/<symbol>/<tf>', methods=['GET'])
def deep_load_status(symbol, tf):
    """Get status of deep data load for a symbol/timeframe."""
    asset_type = normalize_asset_type(request.args.get('asset_type', 'STOCK'))
    return jsonify(ib_gateway.get_deep_load_status(symbol.upper(), tf.replace('_', ' '), asset_type))


@market_bp.route('/indicators/<symbol>/<tf>', methods=['GET'])
def api_indicators(symbol, tf):
    """Get technical indicators for a symbol/timeframe."""
    sym = symbol.upper()
    timeframe = tf.replace('_', ' ')
    asset_type = normalize_asset_type(request.args.get('asset_type', 'STOCK'))
    active = [x.strip() for x in request.args.get('active', 'ema,rsi').split(',') if x.strip()]
    
    bars = data_store.get_bars(get_cache_symbol(sym, asset_type), timeframe)
    if bars is None or len(bars) == 0:
        return jsonify({'error': 'no data available'}), 404
    
    result = {'symbol': sym, 'timeframe': timeframe, 'indicators': {}}
    
    for indicator_name in active:
        indicator_name = indicator_name.lower()
        if indicator_name == 'sma':
            period = int(request.args.get('sma_period', 20))
            ind = SMA(period)
            values = ind.calculate(bars)
            result['indicators']['sma'] = {'period': period, 'values': values[-50:]}
        elif indicator_name == 'ema':
            period = int(request.args.get('ema_period', 20))
            ind = EMA(period)
            values = ind.calculate(bars)
            result['indicators']['ema'] = {'period': period, 'values': values[-50:]}
        elif indicator_name == 'rsi':
            period = int(request.args.get('rsi_period', 14))
            ind = RSI(period)
            values = ind.calculate(bars)
            result['indicators']['rsi'] = {'period': period, 'values': values[-50:]}
        elif indicator_name == 'macd':
            ind = MACD()
            values = ind.calculate(bars)
            if values is not None:
                result['indicators']['macd'] = {
                    'macd': values['macd'][-50:].tolist() if hasattr(values['macd'][-50:], 'tolist') else list(values['macd'][-50:]),
                    'signal': values['signal'][-50:].tolist() if hasattr(values['signal'][-50:], 'tolist') else list(values['signal'][-50:]),
                    'histogram': values['histogram'][-50:].tolist() if hasattr(values['histogram'][-50:], 'tolist') else list(values['histogram'][-50:])
                }
    
    return jsonify(result)


@market_bp.route('/candles/<symbol>', methods=['GET'])
def get_candles(symbol):
    """Get historical candles for a symbol (alias for bars)."""
    return get_bars(symbol)


@market_bp.route('/subscribe/<symbol>', methods=['POST'])
def subscribe_tick(symbol):
    """Subscribe to real-time tick updates for a symbol."""
    asset_type = normalize_asset_type(request.args.get('asset_type', 'STOCK'))
    
    return jsonify({
        'symbol': symbol,
        'asset_type': asset_type,
        'status': 'subscribed'
    })

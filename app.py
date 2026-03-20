import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
import dash
from dash import dcc, html, Input, Output, State
from datetime import datetime, timedelta
from flask import jsonify, request as freq
from contract_utils import create_contract, get_cache_symbol, normalize_asset_type, set_default_exchange
from modules.logger import log
from modules.market_hours import get_session_display
from modules.config_store import config_store
import ib_gateway  # Unified IB API facade
import config
from modules.data_store import data_store
from modules.indicators import SMA, EMA, RSI, MACD
from modules.trade_tracker import trade_tracker
import time
import atexit
import signal

def graceful_shutdown():
    log("INFO", "[SHUTDOWN] Disconnecting from IB...")
    try:
        ib_gateway.disconnect()
    except:
        pass
    log("INFO", "[SHUTDOWN] Done.")

atexit.register(graceful_shutdown)

app = dash.Dash(
    __name__,
    title="IB Trading Platform",
    update_title=None,
    suppress_callback_exceptions=True,
    serve_locally=True
)

server = app.server


def fmt_price(price, asset_type=None):
    """Format price with appropriate decimal places: 4 for Forex, 2 for stocks."""
    if asset_type and normalize_asset_type(asset_type) == 'FOREX':
        return f"${price:.4f}"
    return f"${price:.2f}"


def submit_order(symbol, action, quantity, order_type, limit_price, asset_type='STOCK'):
    """Submit an order via ib_gateway (supports MARKET and LIMIT)."""
    return ib_gateway.place_order(
        symbol=(symbol or '').upper(),
        action=action,
        quantity=quantity,
        order_type=order_type,
        limit_price=limit_price,
        asset_type=normalize_asset_type(asset_type)
    )

DURATION_MAP = {
    '1 min':   '1 D',
    '5 mins':  '2 D',
    '15 mins': '5 D',
    '30 mins': '10 D',
    '1 hour':  '1 M',
    '1 day':   '6 M',
}

# ================================================================
# FLASK API
# ================================================================

@server.route('/api/tick/<symbol>')
def get_tick(symbol):
    sym        = symbol.upper()
    asset_type = normalize_asset_type(freq.args.get('asset_type', app_state.get('current_asset_type', 'STOCK')))
    price      = ib_gateway.get_latest_price(sym, asset_type)
    return jsonify({'time': int(datetime.now().timestamp()), 'price': price, 'asset_type': asset_type})

@server.route('/api/deep_load_status/<symbol>/<tf>')
def deep_load_status(symbol, tf):
    asset_type = normalize_asset_type(freq.args.get('asset_type', app_state.get('current_asset_type', 'STOCK')))
    return jsonify(ib_gateway.get_deep_load_status(symbol.upper(), tf.replace('_', ' '), asset_type))

@server.route('/api/indicators/<symbol>/<tf>')
def api_indicators(symbol, tf):
    sym       = symbol.upper()
    timeframe = tf.replace('_', ' ')
    asset_type = normalize_asset_type(freq.args.get('asset_type', app_state.get('current_asset_type', 'STOCK')))
    active    = [x.strip() for x in freq.args.get('active', 'ema,rsi').split(',') if x.strip()]

    bars = data_store.get_bars(get_cache_symbol(sym, asset_type), timeframe)
    if not bars:
        return jsonify({'ok': False, 'error': 'no_data', 'bars': 0,
                        'symbol': sym, 'asset_type': asset_type, 'tf': timeframe})

    result = {'ok': True, 'symbol': sym, 'asset_type': asset_type, 'tf': timeframe, 'bars': len(bars)}
    try:
        if 'sma' in active:
            p = int(freq.args.get('sma_p', 20))
            result['sma']        = SMA(period=p).calculate(bars)
            result['sma_period'] = p
        if 'ema' in active:
            p = int(freq.args.get('ema_p', 20))
            result['ema']        = EMA(period=p).calculate(bars)
            result['ema_period'] = p
        if 'rsi' in active:
            p = int(freq.args.get('rsi_p', 14))
            result['rsi']        = RSI(period=p).calculate(bars)
            result['rsi_period'] = p
        if 'macd' in active:
            fast = int(freq.args.get('macd_fast', 12))
            slow = int(freq.args.get('macd_slow', 26))
            sig  = int(freq.args.get('macd_sig',   9))
            result['macd'] = MACD(fast=fast, slow=slow, signal=sig).calculate(bars)
    except Exception as e:
        result['ok']      = False
        result['warning'] = str(e)

    return jsonify(result)


# ----------------------------------------------------------------
# TRADE API
# ----------------------------------------------------------------

@server.route('/api/trades/open', methods=['GET'])
def api_trades_open():
    trades = trade_tracker.get_open_trades()
    for t in trades:
        t['entry_time_fmt'] = trade_tracker.fmt_time(t.get('entry_time'))
    return jsonify({'ok': True, 'trades': trades})


@server.route('/api/trades/active_lines', methods=['GET'])
def api_trades_active_lines():
    sym = (freq.args.get('symbol') or app_state.get('current_symbol', 'AAPL')).upper()
    asset_type = normalize_asset_type(freq.args.get('asset_type', app_state.get('current_asset_type', 'STOCK')))
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


@server.route('/api/trades/history', methods=['GET'])
def api_trades_history():
    limit  = int(freq.args.get('limit', 50))
    trades = trade_tracker.get_history(limit=limit)
    for t in trades:
        t['entry_time_fmt'] = trade_tracker.fmt_time(t.get('entry_time'))
        t['exit_time_fmt']  = trade_tracker.fmt_time(t.get('exit_time'))
    return jsonify({'ok': True, 'trades': trades})


@server.route('/api/trades/close/<trade_id>', methods=['POST'])
def api_trade_close(trade_id):
    body       = freq.get_json(silent=True) or {}
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

    updated['exit_time_fmt']  = trade_tracker.fmt_time(updated.get('exit_time'))
    updated['entry_time_fmt'] = trade_tracker.fmt_time(updated.get('entry_time'))
    return jsonify({'ok': True, 'trade': updated})


@server.route('/api/trades/close_all', methods=['POST'])
def api_trades_close_all():
    open_trades  = trade_tracker.get_open_trades()
    symbols      = list({(t['symbol'], t.get('asset_type', 'STOCK')) for t in open_trades})
    exit_prices  = {}
    for sym, asset_type in symbols:
        ticker = ib_gateway.get_tick(sym, asset_type)
        if ticker:
            p = ticker.get('price') or ticker.get('last')
            if p:
                exit_prices[sym] = p
    closed = trade_tracker.close_all_open(exit_prices)
    return jsonify({'ok': True, 'closed': len(closed), 'trades': closed})


# ================================================================
app_state = {
    'current_symbol': config_store.get('default_symbol', 'AAPL'),
    'current_timeframe': config_store.get('default_timeframe', '5 mins'),
    'current_asset_type': config_store.get('default_asset_type', 'STOCK'),
    'current_exchange': config_store.get('default_exchange', 'SMART'),
}
# Sync contract_utils default exchange from persisted config
set_default_exchange(app_state['current_exchange'])

# ========== LAYOUT ==========

app.layout = html.Div([
    html.Div([
        html.H1("🚀 IB Trading Platform v3.0",
                style={'display': 'inline-block', 'margin': 0, 'color': '#00d4ff'}),
        html.Span(id='market-hours-badge',
                  style={'display': 'inline-block', 'marginLeft': '20px', 'fontSize': '14px',
                         'padding': '4px 12px', 'borderRadius': '12px', 'verticalAlign': 'middle'}),
        html.Div(id='connection-status',
                 style={'display': 'inline-block', 'float': 'right', 'fontSize': 18})
    ], style={'padding': '20px',
              'background': 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
              'borderRadius': '10px', 'marginBottom': '20px'}),

    html.Div([
        html.Div([html.Span("💼 Account: ", style={'fontWeight': 'bold'}),
                  html.Span(id='account-id', children='Connecting...')],
                 style={'display': 'inline-block', 'marginRight': '30px'}),
        html.Div([html.Span("💰 Balance: ", style={'fontWeight': 'bold'}),
                  html.Span(id='account-balance', children='$0.00')],
                 style={'display': 'inline-block', 'marginRight': '30px'}),
        html.Div([html.Span("📈 Buying Power: ", style={'fontWeight': 'bold'}),
                  html.Span(id='buying-power', children='$0.00')],
                 style={'display': 'inline-block'})
    ], style={'padding': '15px', 'background': '#2d2d3a',
              'borderRadius': '8px', 'marginBottom': '20px', 'fontSize': '16px'}),

    # Symbol + cena
    html.Div([
        html.Div([
            html.Label('Symbol:', style={'marginRight': '10px', 'fontWeight': 'bold'}),
            dcc.Input(
                id='symbol-input', type='text', value=config_store.get('default_symbol', 'AAPL'),
                style={'width': '150px', 'padding': '8px', 'borderRadius': '5px',
                       'border': '2px solid #667eea', 'background': '#1e1e2e',
                       'color': 'white', 'fontSize': '16px'}
            ),
            dcc.Dropdown(
                id='asset-type-select',
                options=[
                    {'label': 'Stock', 'value': 'STOCK'},
                    {'label': 'Forex', 'value': 'FOREX'},
                    {'label': 'Crypto', 'value': 'CRYPTO'},
                ],
                value=config_store.get('default_asset_type', 'STOCK'),
                clearable=False,
                searchable=False,
                style={'width': '140px', 'display': 'inline-block', 'marginLeft': '10px',
                       'verticalAlign': 'middle', 'color': '#111'}
            ),
            dcc.Dropdown(
                id='exchange-select',
                options=[
                    {'label': 'SMART (US)', 'value': 'SMART'},
                    {'label': 'IBIS (DE)', 'value': 'IBIS'},
                    {'label': 'AEB (NL)', 'value': 'AEB'},
                    {'label': 'SBF (FR)', 'value': 'SBF'},
                ],
                value=config_store.get('default_exchange', 'SMART'),
                clearable=False,
                searchable=False,
                style={'width': '140px', 'display': 'inline-block', 'marginLeft': '10px',
                       'verticalAlign': 'middle', 'color': '#111'}
            ),
            html.Span(' | ', style={'color': '#555', 'marginLeft': '15px', 'marginRight': '5px'}),
            dcc.Input(
                id='candles-count-input', type='number', value=60, min=10, max=500, step=10,
                style={'width': '65px', 'padding': '8px', 'borderRadius': '5px',
                       'border': '2px solid #667eea', 'background': '#1e1e2e',
                       'color': 'white', 'fontSize': '14px', 'textAlign': 'center'}
            ),
            html.Span(' svíček', style={'color': '#aaa', 'fontSize': '13px', 'marginRight': '10px'}),
            html.Button(
                'Load Chart', id='load-chart-btn', n_clicks=0,
                style={'marginLeft': '5px', 'padding': '8px 20px',
                       'background': 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
                       'border': 'none', 'borderRadius': '5px',
                       'color': 'white', 'cursor': 'pointer', 'fontWeight': 'bold'}
            ),
            html.Span(id='bars-count-display', children='',
                      style={'marginLeft': '15px', 'fontSize': '13px', 'color': '#888'})
        ], style={'display': 'inline-block', 'marginRight': '30px'}),
        html.Div([
            html.Span(id='price-display', children='Last: $0.00',
                      style={'fontSize': '20px', 'fontWeight': 'bold'}),
            html.Span(id='price-change-display', children='',
                      style={'fontSize': '16px', 'marginLeft': '15px'})
        ], style={'display': 'inline-block'})
    ], style={'padding': '15px', 'background': '#2d2d3a',
              'borderRadius': '8px', 'marginBottom': '20px'}),

    # Graf
    html.Div([
        html.Div([
            html.Div([
                html.Button('1m',  id='tf-1m',  n_clicks=0, className='tf-btn'),
                html.Button('5m',  id='tf-5m',  n_clicks=0, className='tf-btn tf-active'),
                html.Button('15m', id='tf-15m', n_clicks=0, className='tf-btn'),
                html.Button('30m', id='tf-30m', n_clicks=0, className='tf-btn'),
                html.Button('1h',  id='tf-1h',  n_clicks=0, className='tf-btn'),
                html.Button('1D',  id='tf-1d',  n_clicks=0, className='tf-btn'),
                html.Span(id='chart-loading-indicator', children='',
                          style={'marginLeft': '15px', 'fontSize': '13px',
                                 'color': '#ffa726', 'fontStyle': 'italic',
                                 'verticalAlign': 'middle'})
            ], style={'display': 'inline-block'}),
            html.Div([
                html.Div(id='cache-status-indicator', children='Cache: Zjišťuji...',
                         style={'display': 'inline-block', 'marginRight': '15px',
                                'fontSize': '12px', 'color': '#4caf50',
                                'padding': '5px 10px', 'background': '#1b5e20',
                                'borderRadius': '4px'}),
                html.Span('⚠️ 15min delay na demo',
                          style={'fontSize': '11px', 'color': '#666',
                                 'marginRight': '10px', 'verticalAlign': 'middle'}),
                html.Button('⚡ TICK: OFF', id='tick-toggle-btn',
                            n_clicks=0, className='tick-btn tick-off')
            ], style={'display': 'inline-block', 'float': 'right'})
        ], style={'marginBottom': '10px', 'overflow': 'hidden'}),

        html.Div([
            html.Span('📊 Indikátory:',
                      style={'fontWeight': 'bold', 'marginRight': '12px',
                             'fontSize': '13px', 'color': '#aaa', 'verticalAlign': 'middle'}),
            html.Button('SMA 20',  id='ind-sma-btn',  n_clicks=0, className='ind-btn',
                        title='Simple Moving Average (20)'),
            html.Button('EMA 20',  id='ind-ema-btn',  n_clicks=1, className='ind-btn ind-active',
                        title='Exponential Moving Average (20)'),
            html.Button('RSI 14',  id='ind-rsi-btn',  n_clicks=0, className='ind-btn',
                        title='Relative Strength Index (14)'),
            html.Button('MACD',    id='ind-macd-btn', n_clicks=0, className='ind-btn',
                        title='MACD 12/26/9'),
            html.Span(id='indicators-status', children='',
                      style={'marginLeft': '15px', 'fontSize': '12px',
                             'color': '#888', 'fontStyle': 'italic'}),
        ], style={'marginBottom': '10px', 'paddingTop': '10px',
                  'borderTop': '1px solid #3d3d4a'}),

        html.Div(id='lwc-container',
                 style={'width': '100%', 'height': '500px', 'position': 'relative',
                        'background': '#1e1e2e'}),

        dcc.Store(id='chart-data-store'),
        dcc.Store(id='chart-trigger-store'),
        dcc.Store(id='chart-append-store'),  # For loading older bars
        dcc.Store(id='chart-meta-store', data={'load_count': 0, 'oldest_time': None, 'total_bars': 0, 'symbol': None, 'tf': None}),
        dcc.Store(id='active-tf-store', data='tf-5m'),
        dcc.Store(id='tick-enabled-store', data=False),
        dcc.Store(id='tick-sync-dummy', data=None),
        dcc.Store(id='deep-load-finished-trigger', data=False),
        dcc.Store(id='indicator-settings-store',
                  data={'sma': False, 'ema': True, 'rsi': False, 'macd': False}),
        dcc.Store(id='indicators-data-store'),
        dcc.Store(id='trade-refresh-store', data=0),
        dcc.Store(id='trade-debug-store', data=None),

    ], style={'padding': '20px', 'background': '#2d2d3a',
              'borderRadius': '8px', 'marginBottom': '20px'}),

    # ================================================================
    # ORDER ENTRY – v3.0
    # ================================================================
    html.Div([
        html.H3('📥 Order Entry', style={'marginBottom': '15px'}),

        html.Div([
            html.Label('Množství:', style={'marginRight': '10px', 'fontWeight': 'bold',
                                           'fontSize': '13px', 'color': '#aaa'}),
            html.Button('1',   id='qty-1',   n_clicks=0, className='qty-btn'),
            html.Button('5',   id='qty-5',   n_clicks=0, className='qty-btn'),
            html.Button('10',  id='qty-10',  n_clicks=0, className='qty-btn'),
            html.Button('25',  id='qty-25',  n_clicks=0, className='qty-btn'),
            html.Button('100', id='qty-100', n_clicks=0, className='qty-btn'),
            dcc.Input(id='qty-custom', type='number', value=1, min=1,
                      placeholder='Vlastní',
                      style={'width': '80px', 'marginLeft': '10px', 'padding': '8px',
                             'borderRadius': '5px', 'border': '2px solid #667eea',
                             'background': '#1e1e2e', 'color': 'white'})
        ], style={'marginBottom': '14px'}),

        # Order type + Limit price row
        html.Div([
            html.Div([
                html.Span('Typ příkazu:', style={'fontSize': '13px', 'color': '#aaa', 'marginRight': '8px'}),
                dcc.RadioItems(
                    id='order-type-select',
                    options=[
                        {'label': ' Market ', 'value': 'MARKET'},
                        {'label': ' Limit ', 'value': 'LIMIT'},
                    ],
                    value='MARKET',
                    style={'display': 'inline-block', 'color': '#ccc'},
                    inputStyle={'marginRight': '4px', 'marginLeft': '8px'}
                ),
            ], style={'display': 'inline-block', 'marginRight': '25px'}),

            html.Div([
                html.Span('Limit Price:', style={'fontSize': '13px', 'color': '#ffd54f', 'marginRight': '8px'}),
                dcc.Input(id='limit-price-input', type='number', placeholder='Cena $',
                          min=0, step=0.01,
                          style={'width': '90px', 'padding': '6px',
                                 'borderRadius': '5px', 'border': '2px solid #ffd54f',
                                 'background': '#1e1e2e', 'color': 'white', 'fontSize': '13px'}),
            ], id='limit-price-row', style={'display': 'none'}),
        ], style={'marginBottom': '12px', 'padding': '12px',
                  'background': '#1a1a2e', 'borderRadius': '8px',
                  'border': '1px solid #3d3d4a'}),

        html.Div([
            html.Div([
                html.Span('🛡️ Stop-Loss:',
                          style={'fontSize': '13px', 'color': '#ef9a9a',
                                 'fontWeight': 'bold', 'marginRight': '8px'}),
                dcc.Input(id='sl-price-input', type='number', placeholder='Cena $',
                          min=0, step=0.01,
                          style={'width': '90px', 'padding': '6px', 'marginRight': '6px',
                                 'borderRadius': '5px', 'border': '2px solid #ef5350',
                                 'background': '#1e1e2e', 'color': 'white', 'fontSize': '13px'}),
                html.Span('nebo', style={'color': '#555', 'marginRight': '6px', 'fontSize': '12px'}),
                dcc.Input(id='sl-pct-input', type='number', placeholder='%',
                          min=0, max=100, step=0.1,
                          style={'width': '65px', 'padding': '6px', 'marginRight': '20px',
                                 'borderRadius': '5px', 'border': '2px solid #ef5350',
                                 'background': '#1e1e2e', 'color': 'white', 'fontSize': '13px'}),

                html.Span('🎯 Take-Profit:',
                          style={'fontSize': '13px', 'color': '#a5d6a7',
                                 'fontWeight': 'bold', 'marginRight': '8px'}),
                dcc.Input(id='tp-price-input', type='number', placeholder='Cena $',
                          min=0, step=0.01,
                          style={'width': '90px', 'padding': '6px', 'marginRight': '6px',
                                 'borderRadius': '5px', 'border': '2px solid #26a69a',
                                 'background': '#1e1e2e', 'color': 'white', 'fontSize': '13px'}),
                html.Span('nebo', style={'color': '#555', 'marginRight': '6px', 'fontSize': '12px'}),
                dcc.Input(id='tp-pct-input', type='number', placeholder='%',
                          min=0, step=0.1,
                          style={'width': '65px', 'padding': '6px',
                                 'borderRadius': '5px', 'border': '2px solid #26a69a',
                                 'background': '#1e1e2e', 'color': 'white', 'fontSize': '13px'}),
            ], style={'display': 'inline-block', 'marginRight': '20px'}),

            html.Div([
                html.Span('📝', style={'marginRight': '6px', 'fontSize': '13px'}),
                dcc.Input(id='order-note-input', type='text', placeholder='Poznámka (volitelné)',
                          maxLength=100,
                          style={'width': '200px', 'padding': '6px',
                                 'borderRadius': '5px', 'border': '2px solid #555',
                                 'background': '#1e1e2e', 'color': 'white', 'fontSize': '13px'})
            ], style={'display': 'inline-block'}),
        ], style={'marginBottom': '12px', 'padding': '12px',
                  'background': '#1a1a2e', 'borderRadius': '8px',
                  'border': '1px solid #3d3d4a'}),

        html.Div(id='order-preview',
                 style={'marginBottom': '8px', 'padding': '8px 14px',
                        'background': '#0d1a2e', 'borderRadius': '6px',
                        'fontSize': '13px', 'color': '#90caf9',
                        'fontFamily': 'monospace', 'minHeight': '28px'}),

        # R/R ratio and Risk display
        html.Div([
            html.Span(id='rr-display', children='R/R: –',
                      style={'fontSize': '14px', 'color': '#ffd54f', 'fontWeight': 'bold',
                             'marginRight': '25px'}),
            html.Span(id='risk-display', children='Risk: –',
                      style={'fontSize': '14px', 'color': '#ef9a9a', 'fontWeight': 'bold'}),
        ], style={'marginBottom': '14px'}),

        html.Div([
            html.Button('🟢 BUY', id='buy-btn', n_clicks=0,
                        style={'padding': '15px 40px',
                               'background': 'linear-gradient(135deg, #26a69a 0%, #1a7f6f 100%)',
                               'border': 'none', 'borderRadius': '8px', 'color': 'white',
                               'fontSize': '18px', 'fontWeight': 'bold',
                               'cursor': 'pointer', 'marginRight': '15px'}),
            html.Button('🔴 SELL', id='sell-btn', n_clicks=0,
                        style={'padding': '15px 40px',
                               'background': 'linear-gradient(135deg, #ef5350 0%, #c62828 100%)',
                               'border': 'none', 'borderRadius': '8px', 'color': 'white',
                               'fontSize': '18px', 'fontWeight': 'bold', 'cursor': 'pointer'})
        ]),
        html.Div(id='order-feedback', style={'marginTop': '15px', 'fontSize': '16px'})

    ], style={'padding': '20px', 'background': '#2d2d3a',
              'borderRadius': '8px', 'marginBottom': '20px'}),

    # ================================================================
    # OPEN POSITIONS
    # ================================================================
    html.Div([
        html.Div([
            html.H3('📊 Open Positions',
                    style={'display': 'inline-block', 'marginBottom': '0', 'marginRight': '20px'}),
            html.Button('🔄 Refresh', id='refresh-positions-btn', n_clicks=0,
                        style={'padding': '8px 14px', 'background': '#1565c0',
                               'border': 'none', 'borderRadius': '6px', 'color': 'white',
                               'fontWeight': 'bold', 'cursor': 'pointer', 'fontSize': '13px',
                               'marginRight': '10px'}),
            html.Button('❌ Close All Positions', id='close-all-btn', n_clicks=0,
                        style={'padding': '8px 18px', 'background': '#b71c1c',
                               'border': 'none', 'borderRadius': '6px', 'color': 'white',
                               'fontWeight': 'bold', 'cursor': 'pointer', 'fontSize': '13px'}),
            html.Span(id='close-all-feedback', children='',
                      style={'marginLeft': '12px', 'fontSize': '13px', 'color': '#ff8a65'})
        ], style={'marginBottom': '15px', 'display': 'flex',
                  'alignItems': 'center', 'flexWrap': 'wrap', 'gap': '10px'}),
        html.Div(id='positions-table')
    ], style={'padding': '20px', 'background': '#2d2d3a',
              'borderRadius': '8px', 'marginBottom': '20px'}),

    # ================================================================
    # TRADE HISTORY
    # ================================================================
    html.Div([
        html.H3('📈 Trade History', style={'marginBottom': '15px'}),
        html.Div(id='trade-history-table')
    ], style={'padding': '20px', 'background': '#2d2d3a',
              'borderRadius': '8px', 'marginBottom': '20px'}),

    dcc.Interval(id='cache-update-interval',     interval=2000,  n_intervals=0),
    dcc.Interval(id='price-update-interval',     interval=10000, n_intervals=0),
    dcc.Interval(id='positions-update-interval', interval=10000, n_intervals=0),
    dcc.Interval(id='connection-check-interval', interval=10000, n_intervals=0),
    dcc.Interval(id='trades-refresh-interval',   interval=5000,  n_intervals=0),
    dcc.Interval(id='market-hours-interval',     interval=60000, n_intervals=0),
    html.Div(id='hidden-state', style={'display': 'none'}),
    html.Div(id='deep-load-trigger-dummy', style={'display': 'none'})

], style={'maxWidth': '1400px', 'margin': '0 auto', 'padding': '20px',
          'background': '#1e1e2e', 'minHeight': '100vh',
          'color': 'white', 'fontFamily': 'Arial, sans-serif'})


# ========== PYTHON CALLBACKS ==========

@app.callback(
    Output('connection-status', 'children'),
    Input('connection-check-interval', 'n_intervals')
)
def update_connection_status(n):
    if ib_gateway.is_connected():
        return html.Span([html.Span('⚪', style={'color': '#26a69a', 'marginRight': '5px'}),
                          html.Span('Connected to IB Gateway')])
    return html.Span([html.Span('⚪', style={'color': '#ef5350', 'marginRight': '5px'}),
                      html.Span('Disconnected')])


@app.callback(
    Output('market-hours-badge', 'children'),
    Output('market-hours-badge', 'style'),
    Input('market-hours-interval', 'n_intervals')
)
def update_market_hours(n):
    info = get_session_display()
    style = {
        'display': 'inline-block', 'marginLeft': '20px', 'fontSize': '14px',
        'padding': '4px 12px', 'borderRadius': '12px', 'verticalAlign': 'middle',
        'color': info['color'], 'background': '#1a1a2e', 'border': f'1px solid {info["color"]}',
    }
    return info['label'], style


@app.callback(
    [Output('account-id', 'children'),
     Output('account-balance', 'children'),
     Output('buying-power', 'children')],
    Input('connection-check-interval', 'n_intervals')
)
def update_account_info(n):
    if not ib_gateway.is_connected():
        return 'Not Connected', '$0.00', '$0.00'
    d = ib_gateway.get_account_info()
    return (d.get('account_id', 'N/A'),
            f"${d.get('net_liquidation', 0):,.2f}",
            f"${d.get('buying_power', 0):,.2f}")


_TOPUP_DURATION = {
    '1 min':   '2 H',
    '5 mins':  '6 H',
    '15 mins': '1 D',
    '30 mins': '2 D',
    '1 hour':  '4 D',
    '1 day':   '3 M',
}

@app.callback(
    [Output('chart-data-store', 'data'),
     Output('chart-append-store', 'data'),
     Output('chart-meta-store', 'data'),
     Output('tick-enabled-store', 'data', allow_duplicate=True),
     Output('tick-toggle-btn', 'children', allow_duplicate=True),
     Output('tick-toggle-btn', 'className', allow_duplicate=True),
     Output('bars-count-display', 'children')],
    [Input('load-chart-btn', 'n_clicks'),
     Input('tf-1m',  'n_clicks'), Input('tf-5m',  'n_clicks'),
     Input('tf-15m', 'n_clicks'), Input('tf-30m', 'n_clicks'),
     Input('tf-1h',  'n_clicks'), Input('tf-1d',  'n_clicks'),
     Input('deep-load-finished-trigger', 'data')],
    [State('symbol-input', 'value'),
     State('asset-type-select', 'value'),
     State('candles-count-input', 'value'),
     State('chart-meta-store', 'data')],
    prevent_initial_call=True
)
def load_chart_data(load_clicks, tf1, tf5, tf15, tf30, tf1h, tf1d, dl_trigger, 
                    symbol, asset_type, n_candles, meta):
    try:
        ctx = dash.callback_context
        btn = (ctx.triggered[0]['prop_id'].split('.')[0]
               if ctx.triggered else 'load-chart-btn')
        tf_map = {'tf-1m': '1 min', 'tf-5m': '5 mins',
                  'tf-15m': '15 mins', 'tf-30m': '30 mins',
                  'tf-1h': '1 hour', 'tf-1d': '1 day'}
        
        # Determine if TF button was clicked
        if btn in tf_map:
            app_state['current_timeframe'] = tf_map[btn]
        
        symbol     = (symbol or 'AAPL').upper()
        asset_type = normalize_asset_type(asset_type)
        tf         = app_state['current_timeframe']
        n_candles  = max(10, min(500, int(n_candles or 60)))
        
        app_state['current_symbol'] = symbol
        app_state['current_asset_type'] = asset_type
        
        # Check if this is a reset (symbol/TF changed) or append
        prev_symbol = meta.get('symbol') if meta else None
        prev_tf     = meta.get('tf') if meta else None
        is_reset    = (btn in tf_map or 
                       btn == 'deep-load-finished-trigger' or
                       prev_symbol != symbol or 
                       prev_tf != tf)
        
        if is_reset:
            # === FIRST LOAD or RESET: fetch N candles from now ===
            log("DEBUG", f"[CB] INITIAL LOAD: {symbol} ({asset_type}) | {tf} | n={n_candles} | Trigger={btn}")
            bars = ib_gateway.get_n_bars(symbol, n_candles, tf, asset_type, end_time=None)
            log("DEBUG", f"[CB] IB returned {len(bars)} bars")
            
            if not bars:
                return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, '❌ Žádná data'
            
            # Update meta
            new_meta = {
                'load_count': 1,
                'oldest_time': bars[0]['time'] if bars else None,
                'total_bars': len(bars),
                'symbol': symbol,
                'tf': tf,
                'n_candles': n_candles
            }
            
            chart_data = {'symbol': symbol, 'asset_type': asset_type, 'timeframe': tf, 'bars': bars, 'mode': 'initial'}
            bars_display = f"📊 {len(bars)} svíček"
            
            log('DEBUG', '[TICK] Auto-enabled on chart load')
            return chart_data, None, new_meta, True, '⚡ TICK: ON', 'tick-btn tick-on', bars_display
        
        else:
            # === APPEND: fetch older candles ===
            oldest_time = meta.get('oldest_time') if meta else None
            if not oldest_time:
                log("DEBUG", "[CB] APPEND: no oldest_time, treating as initial")
                # Fall back to initial load
                bars = ib_gateway.get_n_bars(symbol, n_candles, tf, asset_type, end_time=None)
                new_meta = {
                    'load_count': 1,
                    'oldest_time': bars[0]['time'] if bars else None,
                    'total_bars': len(bars),
                    'symbol': symbol,
                    'tf': tf,
                    'n_candles': n_candles
                }
                chart_data = {'symbol': symbol, 'asset_type': asset_type, 'timeframe': tf, 'bars': bars, 'mode': 'initial'}
                return chart_data, None, new_meta, True, '⚡ TICK: ON', 'tick-btn tick-on', f"📊 {len(bars)} svíček"
            
            log("DEBUG", f"[CB] APPEND: {symbol} ({asset_type}) | {tf} | n={n_candles} | before={oldest_time}")
            
            # Fetch older bars ending just before oldest_time
            older_bars = ib_gateway.get_n_bars(symbol, n_candles, tf, asset_type, end_time=oldest_time - 1)
            log("DEBUG", f"[CB] IB returned {len(older_bars)} older bars")
            
            if not older_bars:
                # No more historical data available
                return dash.no_update, None, dash.no_update, dash.no_update, dash.no_update, dash.no_update, '⚠️ Žádná starší data'
            
            # Update meta with new oldest time
            new_meta = {
                'load_count': meta.get('load_count', 0) + 1,
                'oldest_time': older_bars[0]['time'],
                'total_bars': meta.get('total_bars', 0) + len(older_bars),
                'symbol': symbol,
                'tf': tf,
                'n_candles': n_candles
            }
            
            # Send older bars to append store
            append_data = {'symbol': symbol, 'asset_type': asset_type, 'timeframe': tf, 'bars': older_bars, 'mode': 'append'}
            bars_display = f"📊 {new_meta['total_bars']} svíček (+{len(older_bars)})"
            
            return dash.no_update, append_data, new_meta, dash.no_update, dash.no_update, dash.no_update, bars_display
    
    except Exception as e:
        log("INFO", f"[CB] EXCEPTION: {e}")
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, f'❌ {e}'


@app.callback(
    Output('cache-status-indicator', 'children'),
    Input('cache-update-interval', 'n_intervals'),
    [State('symbol-input', 'value'),
     State('asset-type-select', 'value')]
)
def update_cache_status(n, symbol, asset_type):
    if not symbol: return "Vyberte symbol"
    sym        = symbol.upper()
    asset_type = normalize_asset_type(asset_type)
    tf         = app_state.get('current_timeframe', '5 mins')
    status = data_store.get_cache_status(get_cache_symbol(sym, asset_type), tf)
    if not status['cached']:
        return ""
    bars_str = f"{status['total_bars']:,}".replace(',', ' ')
    age = status['age_seconds']
    if age < 60:      age_str = f"{int(age)}s"
    elif age < 3600:  age_str = f"{int(age//60)}m"
    elif age < 86400: age_str = f"{int(age//3600)}h"
    else:             age_str = f"{int(age//86400)}d"
    if status['is_fresh']:
        return html.Span(f"💾 Parquet: {bars_str} barů | Aktuální",
                         style={'color': '#4caf50', 'background': '#1b5e20'})
    return html.Span(f"💾 Parquet: {bars_str} barů | {age_str} staré",
                     style={'color': '#ffeb3b', 'background': '#e65100'})


# ------------------------------------------------------------------
# EXCHANGE SELECTOR: sync dropdown → app_state + contract_utils default
# ------------------------------------------------------------------
@app.callback(
    Output('exchange-select', 'id'),
    Input('exchange-select', 'value'),
    prevent_initial_call=True
)
def update_exchange(exchange):
    exchange = (exchange or 'SMART').strip().upper()
    app_state['current_exchange'] = exchange
    set_default_exchange(exchange)
    config_store.set('default_exchange', exchange)
    log("INFO", f"[EXCHANGE] Changed to: {exchange}")
    return dash.no_update


# ------------------------------------------------------------------
# ORDER ENTRY: live preview (clientside)
# ------------------------------------------------------------------
app.clientside_callback(
    """
    function(qty, slPrice, slPct, tpPrice, tpPct, symbol, priceTxt, orderType, limitPrice) {
        var sym  = (symbol || 'AAPL').toUpperCase();
        var q    = qty || 1;
        var cur  = 0;
        if (priceTxt) {
            var m = priceTxt.match(/\$[\d.]+/);
            if (m) cur = parseFloat(m[1]);
        }

        var sl = slPrice ? parseFloat(slPrice) : null;
        var tp = tpPrice ? parseFloat(tpPrice) : null;

        if (!sl && slPct && cur > 0)
            sl = Math.round(cur * (1 - slPct / 100) * 100) / 100;
        if (!tp && tpPct && cur > 0)
            tp = Math.round(cur * (1 + tpPct / 100) * 100) / 100;

        var orderTypeLabel = (orderType === 'LIMIT' && limitPrice)
            ? 'Limit @ $' + parseFloat(limitPrice).toFixed(2)
            : 'Market';
        var parts = ['📋 ' + q + '× ' + sym + ' @ ' + orderTypeLabel];
        if (sl) parts.push('🛡️ SL $' + sl.toFixed(2));
        if (tp) parts.push('🎯 TP $' + tp.toFixed(2));
        return parts.join('  |  ');
    }
    """,
    Output('order-preview', 'children'),
    [Input('qty-custom', 'value'),
     Input('sl-price-input', 'value'),
     Input('sl-pct-input', 'value'),
     Input('tp-price-input', 'value'),
     Input('tp-pct-input', 'value'),
     Input('symbol-input', 'value'),
     Input('price-display', 'children'),
     Input('order-type-select', 'value'),
     Input('limit-price-input', 'value')]
)


# ------------------------------------------------------------------
# TOGGLE LIMIT PRICE VISIBILITY based on order type
# ------------------------------------------------------------------
@app.callback(
    Output('limit-price-row', 'style'),
    Input('order-type-select', 'value')
)
def toggle_limit_price(order_type):
    if order_type == 'LIMIT':
        return {'display': 'inline-block'}
    return {'display': 'none'}


# ------------------------------------------------------------------
# R/R RATIO AND RISK DISPLAY
# ------------------------------------------------------------------
@app.callback(
    [Output('rr-display', 'children'),
     Output('risk-display', 'children')],
    [Input('sl-price-input', 'value'),
     Input('sl-pct-input', 'value'),
     Input('tp-price-input', 'value'),
     Input('tp-pct-input', 'value'),
     Input('qty-custom', 'value'),
     Input('symbol-input', 'value'),
     Input('price-display', 'children'),
     Input('order-type-select', 'value')]
)
def update_rr_and_risk(sl_price, sl_pct, tp_price, tp_pct, quantity, symbol, price_txt, order_type):
    try:
        # Get current price
        cur = 0
        if price_txt:
            import re
            m = re.search(r'\$([\d.]+)', str(price_txt))
            if m:
                cur = float(m.group(1))

        # Calculate SL
        sl = None
        if sl_price:
            sl = float(sl_price)
        elif sl_pct and cur > 0:
            sl = round(cur * (1 - float(sl_pct) / 100), 4 if order_type == 'FOREX' else 2)

        # Calculate TP
        tp = None
        if tp_price:
            tp = float(tp_price)
        elif tp_pct and cur > 0:
            tp = round(cur * (1 + float(tp_pct) / 100), 4 if order_type == 'FOREX' else 2)

        qty = quantity or 1

        # Calculate R/R ratio
        rr_txt = 'R/R: –'
        if sl and tp and cur > 0:
            risk = abs(cur - sl)
            reward = abs(tp - cur)
            if risk > 0:
                rr = reward / risk
                rr_txt = f'R/R: 1:{rr:.1f}'

        # Calculate dollar risk
        risk_txt = 'Risk: –'
        if sl and cur > 0:
            dollar_risk = abs(cur - sl) * qty
            risk_txt = f'Risk: ${dollar_risk:.2f}'

        return rr_txt, risk_txt
    except Exception:
        return 'R/R: –', 'Risk: –'


# ------------------------------------------------------------------
# PLACE ORDER – BUY / SELL + TradeTracker + [TRADE] debug log
# ------------------------------------------------------------------
@app.callback(
    [Output('order-feedback', 'children'),
     Output('trade-refresh-store', 'data'),
     Output('trade-debug-store', 'data')],
    [Input('buy-btn', 'n_clicks'), Input('sell-btn', 'n_clicks')],
    [State('symbol-input',    'value'),
     State('asset-type-select','value'),
     State('qty-custom',      'value'),
     State('sl-price-input',  'value'),
     State('sl-pct-input',    'value'),
     State('tp-price-input',  'value'),
     State('tp-pct-input',    'value'),
     State('order-note-input','value'),
     State('order-type-select','value'),
     State('limit-price-input','value'),
     State('trade-refresh-store', 'data')]
)
def place_order(buy_clicks, sell_clicks, symbol, asset_type, quantity,
                sl_price, sl_pct, tp_price, tp_pct, note, order_type, limit_price, refresh_counter):
    ctx = dash.callback_context
    if not ctx.triggered:
        return '', dash.no_update, dash.no_update
    btn = ctx.triggered[0]['prop_id'].split('.')[0]
    if btn == 'buy-btn' and buy_clicks > 0:
        action, color = 'BUY', '#26a69a'
    elif btn == 'sell-btn' and sell_clicks > 0:
        action, color = 'SELL', '#ef5350'
    else:
        return '', dash.no_update, dash.no_update

    asset_type = normalize_asset_type(asset_type)
    app_state['current_asset_type'] = asset_type

    if not ib_gateway.is_connected():
        dbg = {'msg': f'[TRADE][ERR] {action} {symbol} ({asset_type}) — NOT CONNECTED', 'ts': time.time()}
        return html.Div('❌ Not connected!',
                        style={'color': '#ef5350', 'fontWeight': 'bold'}), dash.no_update, dbg

    # Market hours warning (non-blocking)
    _session = get_session_display()
    _market_warn = ''
    exchange = app_state.get('current_exchange', 'SMART')
    if asset_type == 'STOCK':
        is_eu_exchange = exchange in ('IBIS', 'AEB', 'SBF')
        if is_eu_exchange and _session['status'] != 'EU_REGULAR':
            _market_warn = f'⚠️ EU market closed ({_session["label"]}). '
        elif not is_eu_exchange and _session['status'] != 'US_REGULAR':
            _market_warn = f'⚠️ US market not in regular session ({_session["label"]}). '

    ticker    = ib_gateway.get_tick(symbol, asset_type) or {}
    cur_price = ticker.get('price') or ticker.get('last') or 0

    sl = None
    if sl_price:
        sl = float(sl_price)
    elif sl_pct and cur_price:
        mult = (1 - float(sl_pct) / 100) if action == 'BUY' else (1 + float(sl_pct) / 100)
        _prec = 4 if asset_type == 'FOREX' else 2
        sl   = round(cur_price * mult, _prec)

    tp = None
    if tp_price:
        tp = float(tp_price)
    elif tp_pct and cur_price:
        mult = (1 + float(tp_pct) / 100) if action == 'BUY' else (1 - float(tp_pct) / 100)
        _prec = 4 if asset_type == 'FOREX' else 2
        tp   = round(cur_price * mult, _prec)

    result = submit_order(symbol, action, quantity, order_type, limit_price, asset_type)
    if not result['success']:
        err_msg = result.get('message') or result.get('error') or 'Unknown error'
        dbg = {'msg': f'[TRADE][ERR] {action} {quantity} {symbol} ({asset_type}) — {err_msg}', 'ts': time.time()}
        return html.Div(f'❌ {err_msg}',
                        style={'color': '#ef5350', 'fontWeight': 'bold'}), dash.no_update, dbg

    fill_price = result.get('fill_price') or cur_price
    symbol = (symbol or '').upper()
    remaining_qty = float(quantity or 0)
    tracker_status = 'opened'

    open_trades = trade_tracker.get_open_trades()
    opposing_trades = sorted(
        [
            t for t in open_trades
            if t.get('symbol') == symbol
            and normalize_asset_type(t.get('asset_type', 'STOCK')) == asset_type
            and t.get('side') != action
        ],
        key=lambda t: t.get('entry_time', 0)
    )

    if opposing_trades:
        log("INFO", f"[TRADE] MATCH | {action} {quantity}x {symbol} ({asset_type}) -> {len(opposing_trades)} opposing open trade(s)")

        for existing in opposing_trades:
            if remaining_qty <= 0:
                break

            existing_qty = float(existing.get('qty') or 0)
            if existing_qty <= 0:
                continue

            if remaining_qty < existing_qty:
                updated_qty = None
                with trade_tracker._lock:
                    trades = trade_tracker._read()
                    for stored in trades:
                        if stored.get('id') == existing.get('id') and stored.get('status') == 'open':
                            updated_qty = round(existing_qty - remaining_qty, 8)
                            stored['qty'] = updated_qty
                            trade_tracker._write_atomic(trades)
                            break

                if updated_qty is not None:
                    log("INFO", 
                        f"[TRADE] PARTIAL CLOSE | id={existing.get('id')} "
                        f"closed_qty={remaining_qty} remaining_qty={updated_qty} fill={fill_price}"
                    )
                    tracker_status = 'partially_closed'
                    remaining_qty = 0
                else:
                    log("INFO", f"[TRADE][WARN] PARTIAL CLOSE | id={existing.get('id')} not found during update")
                break

            closed_trade = trade_tracker.close_trade(existing.get('id'), fill_price)
            if closed_trade:
                tracker_status = 'closed'
                remaining_qty = round(remaining_qty - existing_qty, 8)
            else:
                log("INFO", f"[TRADE][WARN] CLOSE | id={existing.get('id')} failed during opposing match")

    if remaining_qty > 0:
        # Issue #3 + #2: use avg_cost from execution fills (fill_price + commission/shares)
        # This is more reliable than the positions cache which may be stale right after fill.
        open_avg_cost, open_commission = ib_gateway.get_fill_avg_cost(symbol, asset_type)
        log('INFO', f'[TRADE] open_trade avg_cost from fills: {open_avg_cost} commission: {open_commission}')
        trade_tracker.open_trade(
            symbol=symbol, side=action, qty=remaining_qty,
            entry_price=fill_price,
            asset_type=asset_type,
            sl=sl, tp=tp,
            note=note or '',
            avg_cost=open_avg_cost,
            commission=open_commission
        )
        if tracker_status in ('closed', 'partially_closed'):
            tracker_status = 'flipped'
        else:
            tracker_status = 'opened'

    sl_txt  = f' | SL {fmt_price(sl, asset_type)}' if sl else ''
    tp_txt  = f' | TP {fmt_price(tp, asset_type)}' if tp else ''
    tracker_txt = ''
    if tracker_status == 'closed':
        tracker_txt = ' | tracker=closed opposing open trade'
    elif tracker_status == 'partially_closed':
        tracker_txt = ' | tracker=partial close of opposing open trade'
    elif tracker_status == 'flipped':
        tracker_txt = f' | tracker=closed opposing trade + opened {remaining_qty:g}'
    dbg_msg = (f'[TRADE] {action} {quantity}x {symbol} ({asset_type}) @ Market'
               f' | fill={fmt_price(fill_price, asset_type)}{sl_txt}{tp_txt}'
               f'{tracker_txt}'
               f'{" | note: " + note if note else ""}')
    dbg = {'msg': dbg_msg, 'ts': time.time()}

    return (
        html.Div([
            html.Span(f'{_market_warn}', style={'color': '#ffb74d'}) if _market_warn else None,
            html.Span(f'✅ {action} {quantity} {symbol} ({asset_type}) @ Market{sl_txt}{tp_txt}'),
        ], style={'color': color, 'fontWeight': 'bold'}),
        (refresh_counter or 0) + 1,
        dbg
    )


# ------------------------------------------------------------------
# CLOSE ALL POSITIONS
# ------------------------------------------------------------------
@app.callback(
    [Output('close-all-feedback', 'children'),
     Output('trade-refresh-store', 'data', allow_duplicate=True),
     Output('trade-debug-store', 'data', allow_duplicate=True)],
    Input('close-all-btn', 'n_clicks'),
    State('trade-refresh-store', 'data'),
    prevent_initial_call=True
)
def close_all_positions(n, refresh_counter):
    if not n:
        return '', dash.no_update, dash.no_update
    if not ib_gateway.is_connected():
        dbg = {'msg': '[TRADE][ERR] CLOSE ALL — NOT CONNECTED', 'ts': time.time()}
        return '❌ Not connected', dash.no_update, dbg

    positions       = ib_gateway.get_positions() or []
    errors          = []
    closed          = 0
    closed_symbols  = set()
    exit_prices     = {}

    for pos in positions:
        sym = pos['symbol']
        qty = abs(pos['position'])
        asset_type = pos.get('asset_type', 'STOCK')
        if qty <= 0:
            continue
        action = 'SELL' if pos['position'] > 0 else 'BUY'
        res = submit_order(sym, action, qty, 'MARKET', None, asset_type)
        if res['success']:
            closed += 1
            closed_symbols.add(sym)
            ticker = ib_gateway.get_tick(sym, asset_type) or {}
            p      = ticker.get('price') or ticker.get('last')
            if p:
                exit_prices[sym] = p
        else:
            errors.append(sym)

    if closed_symbols:
        for trade in trade_tracker.get_open_trades():
            if trade['symbol'] not in closed_symbols:
                continue
            exit_price = exit_prices.get(trade['symbol'], trade.get('entry_price', 0))
            trade_tracker.close_trade(trade['id'], exit_price)

    err_txt = f' | chyba u: {", ".join(errors)}' if errors else ''
    dbg_msg = (f'[TRADE] CLOSE ALL → {closed}/{len(positions)} pozic zavřeno'
               f'{" | ERR: " + ", ".join(errors) if errors else " | OK"}')
    dbg = {'msg': dbg_msg, 'ts': time.time()}

    if errors:
        return f'⚠️ Zavřeno {closed}, chyba: {", ".join(errors)}', (refresh_counter or 0) + 1, dbg
    return f'✅ Zavřeno {closed} pozic', (refresh_counter or 0) + 1, dbg


# ------------------------------------------------------------------
# OPEN POSITIONS TABLE + orphan sync s GRACE PERIOD
# ------------------------------------------------------------------
@app.callback(
    [Output('positions-table', 'children'),
     Output('trade-debug-store', 'data', allow_duplicate=True)],
    [Input('positions-update-interval', 'n_intervals'),
     Input('trade-refresh-store', 'data'),
     Input('refresh-positions-btn', 'n_clicks')],
    prevent_initial_call='initial_duplicate'
)
def update_positions_table(n, _refresh, _btn):
    if not ib_gateway.is_connected():
        return html.Div('Not connected', style={'color': '#888'}), dash.no_update

    positions = ib_gateway.get_positions() or []
    open_trades_list = trade_tracker.get_open_trades()
    now = int(time.time())
    ib_symbols = {p['symbol'] for p in positions}
    debug_lines = []

    # Vždy loguj stav do konzole
    ib_pos_str = str([(p['symbol'], p['position']) for p in positions])
    tt_str     = str([(t['symbol'], f"age={(now - t.get('entry_time', now))}s",
                       f"SL={t.get('sl')} TP={t.get('tp')}")
                      for t in open_trades_list])
    log("DEBUG", f"[SYNC] n={n} | IB={ib_pos_str} | TT={tt_str}")

    # Do debug panelu pošli stav jen pokud jsou otevřené trady nebo IB pozice
    if open_trades_list or positions:
        debug_lines.append(f'[SYNC] ── tick n={n} ──────────────')
        debug_lines.append(f'[SYNC] IB pozice : {ib_pos_str}')
        debug_lines.append(f'[SYNC] TT open   : {tt_str}')

    for tt in open_trades_list:
        sym = tt['symbol']
        if sym in ib_symbols:
            ib_pos = next((p['position'] for p in positions if p['symbol'] == sym), '?')
            age = now - tt.get('entry_time', now)
            msg = (f'[SYNC] ✅ {sym} OK'
                   f' | age={age}s | IB pos={ib_pos}'
                   f' | SL={tt.get("sl")} TP={tt.get("tp")}')
        else:
            age = now - tt.get('entry_time', now)
            msg = (f'[SYNC] ℹ️ {sym} metadata only in TT'
                   f' | age={age}s | waiting for IB position')

        log("DEBUG", msg)
        debug_lines.append(msg)

    dbg = dash.no_update
    if debug_lines:
        dbg = {'msg': '\n'.join(debug_lines), 'ts': time.time(), 'multi': True}

    if not positions and not open_trades_list:
        return html.Div('Žádné otevřené pozice', style={'color': '#888'}), dbg

    rows = []
    
    # Group trades by symbol to match with IB positions
    trades_by_symbol = {}
    for t in open_trades_list:
        trades_by_symbol.setdefault(t['symbol'], []).append(t)
        
    # First, show all IB positions, matching them with TT trades if possible
    processed_trade_ids = set()
    for pos in positions:
        pnl_c = '#26a69a' if pos['unrealized_pnl'] >= 0 else '#ef5350'
        sym   = pos['symbol']
        
        # Find matching trades for this symbol
        matching_trades = trades_by_symbol.get(sym, [])
        
        if matching_trades:
            # If we have multiple trades for this position, we show them as separate rows
            # but we need to divide the position size and PnL proportionally
            total_qty = sum(t.get('qty', 0) for t in matching_trades)
            
            for tt in matching_trades:
                processed_trade_ids.add(tt['id'])
                asset_type = pos.get('asset_type', tt.get('asset_type', 'STOCK'))
                
                msg = (f'[SYNC] ✅ Row enrich {sym}'
                       f' | SL={tt.get("sl")} TP={tt.get("tp")}')
                log("DEBUG", msg)
                debug_lines.append(msg)

                entry_t  = trade_tracker.fmt_time(tt.get('entry_time'))
                sl_txt   = fmt_price(tt['sl'], asset_type) if tt.get('sl') else '–'
                tp_txt   = fmt_price(tt['tp'], asset_type) if tt.get('tp') else '–'
                trade_id = tt.get('id', '')
                
                # Calculate proportional values if there are multiple trades
                trade_qty = tt.get('qty', 0)
                proportion = trade_qty / total_qty if total_qty > 0 else 1
                
                # Use trade's entry price for PnL calculation if available, otherwise proportional IB PnL
                if tt.get('entry_price'):
                    mult = 1 if tt.get('side', 'BUY') == 'BUY' else -1
                    current_price = pos['market_value'] / abs(pos['position']) if pos['position'] != 0 else 0
                    trade_pnl = mult * (current_price - tt['entry_price']) * trade_qty
                    trade_pnl_pct = (trade_pnl / (tt['entry_price'] * trade_qty)) * 100 if tt['entry_price'] > 0 else 0
                else:
                    trade_pnl = pos['unrealized_pnl'] * proportion
                    trade_pnl_pct = pos['unrealized_pnl_pct']
                
                trade_pnl_c = '#26a69a' if trade_pnl >= 0 else '#ef5350'
                
                rows.append(html.Tr([
                    html.Td(f"{sym} ({asset_type})", style={'fontWeight': 'bold'}),
                    html.Td(tt.get('side', 'LONG' if pos['position'] > 0 else 'SHORT'),
                            style={'color': '#00d4ff'}),
                    html.Td(trade_qty),
                    html.Td(fmt_price(tt.get('entry_price', pos['avg_cost']), asset_type)),
                    html.Td(fmt_price(pos['market_value'] * proportion, asset_type)),
                    html.Td(f"${trade_pnl:.2f} ({trade_pnl_pct:.2f}%)",
                            style={'color': trade_pnl_c, 'fontWeight': 'bold'}),
                    html.Td(entry_t, style={'color': '#aaa', 'fontSize': '12px'}),
                    html.Td(sl_txt,  style={'color': '#ef9a9a', 'fontSize': '12px'}),
                    html.Td(tp_txt,  style={'color': '#a5d6a7', 'fontSize': '12px'}),
                    html.Td(
                        html.Button('⟲ BE', id={'type': 'breakeven-btn', 'trade_id': trade_id},
                                    n_clicks=0,
                                    style={'padding': '4px 8px', 'background': '#f57c00',
                                           'border': 'none', 'borderRadius': '4px',
                                           'color': 'white', 'cursor': 'pointer',
                                           'fontSize': '12px', 'marginRight': '4px'}),
                        html.Button('✖', id={'type': 'close-pos-btn', 'trade_id': trade_id},
                                    n_clicks=0,
                                    style={'padding': '4px 8px', 'background': '#b71c1c',
                                           'border': 'none', 'borderRadius': '4px',
                                           'color': 'white', 'cursor': 'pointer',
                                           'fontSize': '12px'})
                    ),
                ]))
        else:
            # Position without TT metadata
            msg = f'[SYNC] ℹ️ Row enrich {sym} | no TT metadata'
            log("DEBUG", msg)
            debug_lines.append(msg)

            _at = pos.get('asset_type', 'STOCK')
            rows.append(html.Tr([
                html.Td(f"{sym} ({_at})", style={'fontWeight': 'bold'}),
                html.Td('LONG' if pos['position'] > 0 else 'SHORT',
                        style={'color': '#00d4ff'}),
                html.Td(abs(pos['position'])),
                html.Td(fmt_price(pos['avg_cost'], _at)),
                html.Td(fmt_price(pos['market_value'], _at)),
                html.Td(f"${pos['unrealized_pnl']:.2f} ({pos['unrealized_pnl_pct']:.2f}%)",
                        style={'color': pnl_c, 'fontWeight': 'bold'}),
                html.Td('–', style={'color': '#aaa', 'fontSize': '12px'}),
                html.Td('–',  style={'color': '#ef9a9a', 'fontSize': '12px'}),
                html.Td('–',  style={'color': '#a5d6a7', 'fontSize': '12px'}),
                html.Td(html.Span('–', style={'color': '#555'})),
            ]))
            
    # Add any TT trades that don't have matching IB positions (e.g. waiting for fill)
    for tt in open_trades_list:
        if tt['id'] not in processed_trade_ids:
            sym = tt['symbol']
            asset_type = tt.get('asset_type', 'STOCK')
            entry_t  = trade_tracker.fmt_time(tt.get('entry_time'))
            sl_txt   = fmt_price(tt['sl'], asset_type) if tt.get('sl') else '–'
            tp_txt   = fmt_price(tt['tp'], asset_type) if tt.get('tp') else '–'
            trade_id = tt.get('id', '')
            
            rows.append(html.Tr([
                html.Td(f"{sym} ({asset_type})", style={'fontWeight': 'bold'}),
                html.Td(tt.get('side', 'LONG'), style={'color': '#00d4ff'}),
                html.Td(tt.get('qty', 0)),
                html.Td(fmt_price(tt.get('entry_price', 0), asset_type)),
                html.Td("Pending..."),
                html.Td("–", style={'color': '#888', 'fontWeight': 'bold'}),
                html.Td(entry_t, style={'color': '#aaa', 'fontSize': '12px'}),
                html.Td(sl_txt,  style={'color': '#ef9a9a', 'fontSize': '12px'}),
                html.Td(tp_txt,  style={'color': '#a5d6a7', 'fontSize': '12px'}),
                html.Td(
                    html.Button('⟲ BE', id={'type': 'breakeven-btn', 'trade_id': trade_id},
                                n_clicks=0,
                                style={'padding': '4px 8px', 'background': '#f57c00',
                                       'border': 'none', 'borderRadius': '4px',
                                       'color': 'white', 'cursor': 'pointer',
                                       'fontSize': '12px', 'marginRight': '4px'}),
                    html.Button('✖', id={'type': 'close-pos-btn', 'trade_id': trade_id},
                                n_clicks=0,
                                style={'padding': '4px 8px', 'background': '#b71c1c',
                                       'border': 'none', 'borderRadius': '4px',
                                       'color': 'white', 'cursor': 'pointer',
                                       'fontSize': '12px'})
                ),
            ]))

    return html.Table([
        html.Thead(html.Tr([
            html.Th('Symbol'), html.Th('Side'), html.Th('Qty'),
            html.Th('Avg Cost'), html.Th('Market Value'), html.Th('P&L'),
            html.Th('Vstup'), html.Th('SL'), html.Th('TP'), html.Th('')
        ])),
        html.Tbody(rows)
    ], style={'width': '100%', 'borderCollapse': 'collapse'}), dbg


# ------------------------------------------------------------------
# CLOSE SINGLE POSITION
# ------------------------------------------------------------------
@app.callback(
    [Output('order-feedback', 'children', allow_duplicate=True),
     Output('trade-debug-store', 'data', allow_duplicate=True),
     Output('trade-refresh-store', 'data', allow_duplicate=True)],
    Input({'type': 'close-pos-btn', 'trade_id': dash.ALL}, 'n_clicks'),
    State('trade-refresh-store', 'data'),
    prevent_initial_call=True
)
def close_single_position(n_clicks_list, refresh_counter):
    ctx = dash.callback_context
    if not ctx.triggered:
        return dash.no_update, dash.no_update, dash.no_update
    triggered = ctx.triggered[0]
    if not triggered['value']:
        return dash.no_update, dash.no_update, dash.no_update

    import json as _json
    prop_id  = triggered['prop_id']
    id_part  = prop_id.split('.')[0]
    trade_id = _json.loads(id_part).get('trade_id', '')
    if not trade_id:
        return dash.no_update, dash.no_update, dash.no_update

    trade = trade_tracker.get_trade(trade_id)
    if not trade:
        dbg = {'msg': f'[TRADE][ERR] Close single — trade {trade_id} nenalezen', 'ts': time.time()}
        return html.Div('❌ Trade nenalezen', style={'color': '#ef5350'}), dbg, dash.no_update

    sym = trade['symbol']

    if not ib_gateway.is_connected():
        dbg = {'msg': f'[TRADE][ERR] Close {sym} — NOT CONNECTED', 'ts': time.time()}
        return html.Div('❌ Not connected', style={'color': '#ef5350'}), dbg, dash.no_update

    positions = ib_gateway.get_positions() or []
    ib_pos    = next((p for p in positions if p['symbol'] == sym and p['position'] != 0), None)

    asset_type = ib_pos.get('asset_type', trade.get('asset_type', 'STOCK')) if ib_pos else trade.get('asset_type', 'STOCK')
    # Fix: use the individual trade's qty, not the total IB position (which sums all trades for that symbol).
    # Using ib_pos['position'] caused the close button to submit qty=N (all trades combined),
    # closing all positions at once and/or opening unintended reverse positions.
    qty = trade['qty']
    act = 'SELL' if ((ib_pos and ib_pos['position'] > 0) or (not ib_pos and trade['side'] == 'BUY')) else 'BUY'

    res = submit_order(sym, act, qty, 'MARKET', None, asset_type)
    if not res['success']:
        dbg = {'msg': f'[TRADE][ERR] CLOSE {sym} {qty}x — {res.get("error")}', 'ts': time.time()}
        return html.Div(f'❌ {res.get("error")}', style={'color': '#ef5350', 'fontWeight': 'bold'}), dbg, dash.no_update

    ticker     = ib_gateway.get_tick(sym, asset_type) or {}
    exit_price = ticker.get('price') or ticker.get('last') or trade.get('entry_price', 0)
    trade_tracker.close_trade(trade_id, exit_price)

    # Issue #2: recalculate P&L using IB avgCost as real cost basis
    if ib_pos and ib_pos.get('avgCost'):
        avg_cost = float(ib_pos['avgCost'])
        direction_mult = 1 if trade.get('side') == 'BUY' else -1
        real_pnl = round(direction_mult * (float(exit_price) - avg_cost) * float(trade.get('qty', qty)), 2)
        log('INFO', f'[TRADE] P&L recalc using avgCost={avg_cost} exit={exit_price} pnl={real_pnl}')
        trade_tracker.patch_trade(trade_id, {'pnl': real_pnl})

    updated = trade_tracker.get_trade(trade_id)
    pnl     = updated.get('pnl') if updated else None
    pnl_txt = f" | P&L: {'+'if (pnl or 0)>=0 else ''}${pnl:.2f}" if pnl is not None else ''

    color   = '#26a69a' if res['success'] else '#ef5350'
    msg_ui  = f"✅ Closed {sym} {qty}x{pnl_txt}" if res['success'] else f"❌ {res['error']}"
    dbg_msg = (f'[TRADE] CLOSE {sym} {qty}x @ {fmt_price(exit_price, asset_type)}{pnl_txt}'
               f' | IB: {"OK" if res["success"] else "ERR " + str(res.get("error",""))}')
    dbg = {'msg': dbg_msg, 'ts': time.time()}

    return html.Div(msg_ui, style={'color': color, 'fontWeight': 'bold'}), dbg, (refresh_counter or 0) + 1


# ------------------------------------------------------------------
# BREAKEVEN BUTTON
# ------------------------------------------------------------------
@app.callback(
    [Output('order-feedback', 'children', allow_duplicate=True),
     Output('trade-debug-store', 'data', allow_duplicate=True),
     Output('trade-refresh-store', 'data', allow_duplicate=True)],
    Input({'type': 'breakeven-btn', 'trade_id': dash.ALL}, 'n_clicks'),
    State('trade-refresh-store', 'data'),
    prevent_initial_call=True
)
def set_breakeven(n_clicks_list, refresh_counter):
    ctx = dash.callback_context
    if not ctx.triggered:
        return dash.no_update, dash.no_update, dash.no_update
    triggered = ctx.triggered[0]
    if not triggered['value']:
        return dash.no_update, dash.no_update, dash.no_update

    import json as _json
    prop_id  = triggered['prop_id']
    id_part  = prop_id.split('.')[0]
    trade_id = _json.loads(id_part).get('trade_id', '')
    if not trade_id:
        return dash.no_update, dash.no_update, dash.no_update

    trade = trade_tracker.get_trade(trade_id)
    if not trade:
        dbg = {'msg': f'[TRADE][ERR] Breakeven — trade {trade_id} not found', 'ts': time.time()}
        return html.Div('❌ Trade not found', style={'color': '#ef5350'}), dbg, dash.no_update

    sym = trade['symbol']
    asset_type = trade.get('asset_type', 'STOCK')

    # Use avg_cost if available, otherwise entry_price
    entry_price = trade.get('avg_cost') or trade.get('entry_price')
    if not entry_price:
        dbg = {'msg': f'[TRADE][ERR] Breakeven {sym} — no entry price', 'ts': time.time()}
        return html.Div('❌ No entry price for breakeven', style={'color': '#ef5350'}), dbg, dash.no_update

    # Update SL to entry price
    success = trade_tracker.patch_trade(trade_id, {'sl': entry_price})
    if success:
        dbg_msg = f'[TRADE] BE {sym} → SL set to {fmt_price(entry_price, asset_type)}'
        log('INFO', dbg_msg)
        dbg = {'msg': dbg_msg, 'ts': time.time()}
        return html.Div(f'⟲ Breakeven set: SL = {fmt_price(entry_price, asset_type)}',
                        style={'color': '#f57c00', 'fontWeight': 'bold'}), dbg, (refresh_counter or 0) + 1
    else:
        dbg = {'msg': f'[TRADE][ERR] Breakeven {sym} — patch failed', 'ts': time.time()}
        return html.Div('❌ Failed to set breakeven', style={'color': '#ef5350'}), dbg, dash.no_update


# ------------------------------------------------------------------
# TRADE HISTORY TABLE
# ------------------------------------------------------------------
@app.callback(
    Output('trade-history-table', 'children'),
    [Input('trades-refresh-interval', 'n_intervals'),
     Input('trade-refresh-store', 'data')]
)
def update_trade_history(_n, _refresh):
    history = trade_tracker.get_history(limit=50)
    if not history:
        return html.Div('Zatím žádná uzavřená pozice', style={'color': '#888'})

    rows = []
    for i, t in enumerate(history, 1):
        pnl    = t.get('pnl')
        pnl_c  = '#26a69a' if (pnl or 0) >= 0 else '#ef5350'
        _at = t.get('asset_type', 'STOCK')
        pnl_s  = f"{'+'if (pnl or 0)>=0 else ''}${pnl:.2f}" if pnl is not None else '–'
        sl_txt = fmt_price(t['sl'], _at) if t.get('sl') else '–'
        tp_txt = fmt_price(t['tp'], _at) if t.get('tp') else '–'
        # Commission: use stored value if available, fall back to (avg_cost - entry_price) * qty
        if t.get('commission') is not None:
            comm_s = f"-${abs(float(t['commission'])):.4f}"
        elif t.get('avg_cost') and t.get('entry_price') and t.get('qty'):
            commission = round((float(t['avg_cost']) - float(t['entry_price'])) * float(t['qty']), 4)
            comm_s = f"-${abs(commission):.4f}"
        else:
            comm_s = '–'
        rows.append(html.Tr([
            html.Td(str(i),  style={'color': '#555', 'fontSize': '12px'}),
            html.Td(t['symbol'], style={'fontWeight': 'bold'}),
            html.Td(t['side'],   style={'color': '#00d4ff'}),
            html.Td(t['qty']),
            html.Td(fmt_price(t['entry_price'], _at) if t.get('entry_price') else '–'),
            html.Td(trade_tracker.fmt_time(t.get('entry_time')),
                    style={'color': '#aaa', 'fontSize': '12px'}),
            html.Td(fmt_price(t['exit_price'], _at) if t.get('exit_price') else '–'),
            html.Td(trade_tracker.fmt_time(t.get('exit_time')),
                    style={'color': '#aaa', 'fontSize': '12px'}),
            html.Td(sl_txt, style={'color': '#ef9a9a', 'fontSize': '12px'}),
            html.Td(tp_txt, style={'color': '#a5d6a7', 'fontSize': '12px'}),
            html.Td(t.get('note', ''), style={'color': '#888', 'fontSize': '12px'}),
            html.Td(comm_s, style={'color': '#ef9a9a', 'fontSize': '12px'}),
            html.Td(pnl_s, style={'color': pnl_c, 'fontWeight': 'bold'}),
        ]))

    return html.Table([
        html.Thead(html.Tr([
            html.Th('#'), html.Th('Symbol'), html.Th('Side'), html.Th('Qty'),
            html.Th('Entry $'), html.Th('Vstup'),
            html.Th('Exit $'),  html.Th('Výstup'),
            html.Th('SL'), html.Th('TP'), html.Th('Poznámka'), html.Th('Komise'), html.Th('P&L')
        ])),
        html.Tbody(rows)
    ], style={'width': '100%', 'borderCollapse': 'collapse'})



# ------------------------------------------------------------------
# TRADE DEBUG STORE → debug-log-area (clientside)
# ------------------------------------------------------------------
app.clientside_callback(
    """
    function(tradeLog) {
        if (!tradeLog || !tradeLog.msg) return window.dash_clientside.no_update;
        var a = document.getElementById('debug-log-area');
        if (!a) return window.dash_clientside.no_update;
        var ts = new Date().toTimeString().slice(0, 8);
        var lines = tradeLog.msg.split('\\n');
        lines.forEach(function(line) {
            if (line) a.value += '[' + ts + '] ' + line + '\\n';
        });
        a.scrollTop = a.scrollHeight;
        return window.dash_clientside.no_update;
    }
    """,
    Output('hidden-state', 'children'),
    Input('trade-debug-store', 'data')
)


# ========== CLIENTSIDE CALLBACKS ==========

app.clientside_callback(
    """function(n){if(n>0&&window.lwcDebug)window.lwcDebug('BTN','Load Chart n='+n+' - cekam na Python/IB...');return n;}""",
    Output('chart-trigger-store', 'data', allow_duplicate=True), Input('load-chart-btn', 'n_clicks'),
    prevent_initial_call=True
)

app.clientside_callback(
    """
    function(n, currentEnabled) {
        var enabled = (n > 0) ? !currentEnabled : currentEnabled;
        if (n > 0) {
            if (window.lwcManager) window.lwcManager.setTickEnabled(enabled);
            if (window.lwcDebug)
                window.lwcDebug('TICK', 'Tick ' + (enabled ? 'ZAPNUT ⚡' : 'VYPNUT'));
        }
        return [enabled, '⚡ TICK: ' + (enabled ? 'ON' : 'OFF'),
                'tick-btn ' + (enabled ? 'tick-on' : 'tick-off')];
    }
    """,
    [Output('tick-enabled-store', 'data'),
     Output('tick-toggle-btn', 'children'),
     Output('tick-toggle-btn', 'className')],
    Input('tick-toggle-btn', 'n_clicks'),
    State('tick-enabled-store', 'data')
)

# Synchronize tick state to JS when Python changes tick-enabled-store (e.g., auto-enable on chart load)
app.clientside_callback(
    """
    function(enabled) {
        if (window.lwcManager) window.lwcManager.setTickEnabled(!!enabled);
        return window.dash_clientside.no_update;
    }
    """,
    Output('tick-sync-dummy', 'data'),
    Input('tick-enabled-store', 'data')
)

app.clientside_callback(
    """
    function(nSma, nEma, nRsi, nMacd, settings) {
        var ctx = window.dash_clientside.callback_context;
        if (!ctx || !ctx.triggered || ctx.triggered.length === 0)
            return [settings,
                    settings.sma  ? 'ind-btn ind-active' : 'ind-btn',
                    settings.ema  ? 'ind-btn ind-active' : 'ind-btn',
                    settings.rsi  ? 'ind-btn ind-active' : 'ind-btn',
                    settings.macd ? 'ind-btn ind-active' : 'ind-btn'];
        var tid = ctx.triggered_id || ctx.triggered[0].prop_id.split('.')[0];
        var s = Object.assign({}, settings);
        if (tid === 'ind-sma-btn')  s.sma  = !s.sma;
        if (tid === 'ind-ema-btn')  s.ema  = !s.ema;
        if (tid === 'ind-rsi-btn')  s.rsi  = !s.rsi;
        if (tid === 'ind-macd-btn') s.macd = !s.macd;
        if (window.lwcDebug) {
            var on = Object.keys(s).filter(function(k){return s[k];});
            window.lwcDebug('IND', 'Toggle -> ' + (on.length ? on.join(',') : 'zadny'));
        }
        return [s,
                s.sma  ? 'ind-btn ind-active' : 'ind-btn',
                s.ema  ? 'ind-btn ind-active' : 'ind-btn',
                s.rsi  ? 'ind-btn ind-active' : 'ind-btn',
                s.macd ? 'ind-btn ind-active' : 'ind-btn'];
    }
    """,
    [Output('indicator-settings-store', 'data'),
     Output('ind-sma-btn', 'className'), Output('ind-ema-btn', 'className'),
     Output('ind-rsi-btn', 'className'), Output('ind-macd-btn', 'className')],
    [Input('ind-sma-btn', 'n_clicks'), Input('ind-ema-btn', 'n_clicks'),
     Input('ind-rsi-btn', 'n_clicks'), Input('ind-macd-btn', 'n_clicks')],
    State('indicator-settings-store', 'data')
)

app.clientside_callback(
    """
    function(chartData, settings) {
        var d = window.lwcDebug || function() {};
        if (!chartData || !chartData.bars || chartData.bars.length === 0)
            return window.dash_clientside.no_update;
        var sym    = chartData.symbol;
        var tf     = chartData.timeframe.replace(/ /g, '_');
        var assetType = chartData.asset_type || 'STOCK';
        var active = [];
        if (settings.sma)  active.push('sma');
        if (settings.ema)  active.push('ema');
        if (settings.rsi)  active.push('rsi');
        if (settings.macd) active.push('macd');
        if (active.length === 0) {
            d('IND', 'Vsechny indikatory vypnuty');
            if (window.lwcManager && window.lwcManager.setIndicators)
                window.lwcManager.setIndicators({ok:true,sma:null,ema:null,rsi:null,macd:null});
            return null;
        }
        var url = '/api/indicators/' + sym + '/' + tf + '?active=' + active.join(',') + '&asset_type=' + encodeURIComponent(assetType);
        d('IND', 'Fetching: ' + url);
        fetch(url).then(function(r){return r.json();}).then(function(data){
            if (!data.ok){d('ERR','IND FAIL: '+(data.error||'unknown'));return;}
            d('IND','OK: '+active.join(',')+' | bars='+data.bars);
            if (window.lwcManager && window.lwcManager.setIndicators)
                window.lwcManager.setIndicators(data, settings);
            else d('ERR','lwcManager.setIndicators() neexistuje');
        }).catch(function(e){d('ERR','IND fetch error: '+e);});
        return window.dash_clientside.no_update;
    }
    """,
    Output('indicators-data-store', 'data'),
    [Input('chart-data-store', 'data'), Input('indicator-settings-store', 'data')]
)

app.clientside_callback(
    """
    function(n1m,n5m,n15m,n30m,n1h,n1d,nLoad,dlTrigger){
        var ctx=window.dash_clientside.callback_context;
        if(!ctx||!ctx.triggered||ctx.triggered.length===0)return '';
        var tid=ctx.triggered_id||ctx.triggered[0].prop_id.split('.')[0];
        if(tid==='deep-load-finished-trigger')return '✅ Data z cache načtena';
        var labels={'tf-1m':'1m','tf-5m':'5m','tf-15m':'15m','tf-30m':'30m','tf-1h':'1h','tf-1d':'1D','load-chart-btn':'Load'};
        return '⏳ Načítám '+(labels[tid]||tid)+'\u2026';
    }
    """,
    Output('chart-loading-indicator', 'children'),
    [Input('tf-1m','n_clicks'),Input('tf-5m','n_clicks'),Input('tf-15m','n_clicks'),
     Input('tf-30m','n_clicks'),Input('tf-1h','n_clicks'),Input('tf-1d','n_clicks'),
     Input('load-chart-btn','n_clicks'),Input('deep-load-finished-trigger','data')]
)

app.clientside_callback(
    """
    function(n1m,n5m,n15m,n30m,n1h,n1d){
        var ctx=window.dash_clientside.callback_context;
        if(!ctx||!ctx.triggered||ctx.triggered.length===0)return window.dash_clientside.no_update;
        var tid=ctx.triggered_id||ctx.triggered[0].prop_id.split('.')[0];
        if(window.lwcDebug){var lbl={'tf-1m':'1m','tf-5m':'5m','tf-15m':'15m','tf-30m':'30m','tf-1h':'1h','tf-1d':'1D'};window.lwcDebug('TF','Zmen -> '+(lbl[tid]||tid)+' (cekam na IB...)'); }
        return tid;
    }
    """,
    Output('active-tf-store', 'data'),
    [Input('tf-1m','n_clicks'),Input('tf-5m','n_clicks'),Input('tf-15m','n_clicks'),
     Input('tf-30m','n_clicks'),Input('tf-1h','n_clicks'),Input('tf-1d','n_clicks')]
)

app.clientside_callback(
    """
    function(activeTf){
        var ids=['tf-1m','tf-5m','tf-15m','tf-30m','tf-1h','tf-1d'];
        return ids.map(function(id){return id===activeTf?'tf-btn tf-active':'tf-btn';});
    }
    """,
    [Output('tf-1m','className'),Output('tf-5m','className'),Output('tf-15m','className'),
     Output('tf-30m','className'),Output('tf-1h','className'),Output('tf-1d','className')],
    Input('active-tf-store','data')
)

app.clientside_callback(
    """
    function(storeData){
        var d=window.lwcDebug||function(){};
        d('CB','=== Dash clientside callback spusten ===');
        var li=document.getElementById('chart-loading-indicator');
        if(li&&!li.textContent.includes('✅'))li.textContent='';
        if(!storeData){d('CB','storeData NULL -> no_update');return window.dash_clientside.no_update;}
        if(!storeData.bars||storeData.bars.length===0){d('CB','bars prazdne -> no_update');return window.dash_clientside.no_update;}
        d('CB','symbol='+storeData.symbol+' tf='+storeData.timeframe+' baru='+storeData.bars.length+' close[0]='+storeData.bars[0].close);
        if(window.lwcManager){d('CB','volam lwcManager.loadData()');window.lwcManager.loadData(storeData);}
        else{var a=0,r=setInterval(function(){a++;if(window.lwcManager){window.lwcManager.loadData(storeData);clearInterval(r);}else if(a>20){d('ERR','lwcManager nenalezen!');clearInterval(r);}},200);}
        return storeData.symbol||'ok';
    }
    """,
    Output('chart-trigger-store', 'data'), Input('chart-data-store', 'data')
)

app.clientside_callback(
    """
    function(appendData){
        var d=window.lwcDebug||function(){};
        if(!appendData){d('CB','appendData NULL -> no_update');return window.dash_clientside.no_update;}
        if(!appendData.bars||appendData.bars.length===0){d('CB','append bars prazdne -> no_update');return window.dash_clientside.no_update;}
        d('CB','APPEND: symbol='+appendData.symbol+' tf='+appendData.timeframe+' baru='+appendData.bars.length);
        if(window.lwcManager){d('CB','volam lwcManager.prependData()');window.lwcManager.prependData(appendData);}
        else{var a=0,r=setInterval(function(){a++;if(window.lwcManager){window.lwcManager.prependData(appendData);clearInterval(r);}else if(a>20){d('ERR','lwcManager nenalezen!');clearInterval(r);}},200);}
        return appendData.symbol||'ok';
    }
    """,
    Output('hidden-state', 'children', allow_duplicate=True), Input('chart-append-store', 'data'),
    prevent_initial_call=True
)

app.clientside_callback(
    """
    function(n, refreshCounter, chartData, symbolInput, assetTypeInput) {
        var d = window.lwcDebug || function() {};
        var sym = ((chartData && chartData.symbol) || symbolInput || 'AAPL').toUpperCase();
        var assetType = ((chartData && chartData.asset_type) || assetTypeInput || 'STOCK').toUpperCase();
        if (!sym) return window.dash_clientside.no_update;

        fetch('/api/trades/active_lines?symbol=' + encodeURIComponent(sym) + '&asset_type=' + encodeURIComponent(assetType))
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (window.lwcManager && window.lwcManager.setTradeLines) {
                    window.lwcManager.setTradeLines(data || []);
                    d('TRADE', 'Trade lines refreshed: ' + sym + ' (' + assetType + ') -> ' + ((data && data.length) || 0));
                } else {
                    d('ERR', 'lwcManager.setTradeLines() neexistuje');
                }
            })
            .catch(function(e) {
                d('ERR', 'TRADE lines fetch error: ' + e);
                if (window.lwcManager && window.lwcManager.setTradeLines) {
                    window.lwcManager.setTradeLines([]);
                }
            });

        return window.dash_clientside.no_update;
    }
    """,
    Output('hidden-state', 'children', allow_duplicate=True),
    [Input('trades-refresh-interval', 'n_intervals'),
     Input('trade-refresh-store', 'data')],
    [State('chart-data-store', 'data'),
     State('symbol-input', 'value'),
     State('asset-type-select', 'value')],
    prevent_initial_call=True
)


@app.callback(
    [Output('price-display', 'children'),
     Output('price-change-display', 'children')],
    Input('price-update-interval', 'n_intervals'),
    [State('symbol-input', 'value'),
     State('asset-type-select', 'value')]
)
def update_price_display(n, symbol, asset_type):
    if not symbol or not ib_gateway.is_connected(): return 'Last: $0.00', ''
    asset_type = normalize_asset_type(asset_type)
    ticker = ib_gateway.get_tick(symbol, asset_type)
    if not ticker: return 'Last: $0.00', ''
    lp = ticker.get('price', 0) or ticker.get('last', 0)
    pc = ticker.get('close', lp) or lp
    if lp <= 0: return 'Last: $0.00', ''
    change = lp - pc
    pct    = (change / pc * 100) if pc > 0 else 0
    arrow  = '▲' if change >= 0 else '▼'
    color  = '#26a69a' if change >= 0 else '#ef5350'
    sign   = '+' if change >= 0 else ''
    _prec = '4' if asset_type == 'FOREX' else '2'
    return (
        f'Last: ${lp:.{_prec}f}',
        html.Span(f' {arrow} {sign}${change:.{_prec}f} ({sign}{pct:.2f}%)', style={'color': color})
    )


@app.callback(
    Output('qty-custom', 'value'),
    [Input('qty-1','n_clicks'),Input('qty-5','n_clicks'),
     Input('qty-10','n_clicks'),Input('qty-25','n_clicks'),Input('qty-100','n_clicks')]
)
def update_quantity(q1,q5,q10,q25,q100):
    ctx = dash.callback_context
    if not ctx.triggered: return 1
    btn = ctx.triggered[0]['prop_id'].split('.')[0]
    return {'qty-1':1,'qty-5':5,'qty-10':10,'qty-25':25,'qty-100':100}.get(btn,1)


# ========== HTML TEMPLATE ==========

app.index_string = '''
<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
        <script src="https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"></script>
        <style>
            body { margin: 0; padding: 0; background: #1e1e2e; }
            #lwc-container { display: block; width: 100%; height: 500px; }
            .tf-btn, .qty-btn {
                padding: 8px 15px; margin: 0 5px;
                background: #2d2d3a; border: 2px solid #667eea;
                border-radius: 5px; color: white;
                cursor: pointer; font-weight: bold;
                transition: background 0.15s;
            }
            .tf-btn:hover, .qty-btn:hover { background: #4a4a6a; }
            .tf-active { background: #667eea !important; }
            .tick-btn {
                padding: 8px 14px; border-radius: 5px;
                cursor: pointer; font-weight: bold; font-size: 13px;
                border: 2px solid; transition: all 0.2s;
            }
            .tick-off { background: #2d2d3a; border-color: #555; color: #888; }
            .tick-off:hover { background: #3a3a4a; border-color: #777; color: #aaa; }
            .tick-on  { background: #1b5e20; border-color: #26a69a; color: #26a69a;
                        box-shadow: 0 0 8px #26a69a44; }
            .tick-on:hover { background: #2e7d32; }
            .ind-btn {
                padding: 6px 14px; margin: 0 4px;
                background: #2d2d3a; border: 2px solid #555;
                border-radius: 5px; color: #888;
                cursor: pointer; font-size: 12px; font-weight: bold;
                transition: all 0.15s;
            }
            .ind-btn:hover { border-color: #aaa; color: #ccc; background: #3a3a4a; }
            .ind-active {
                background: #1a3a5c !important; border-color: #42a5f5 !important;
                color: #42a5f5 !important; box-shadow: 0 0 6px #42a5f533;
            }
            table { border-collapse: collapse; width: 100%; }
            th, td { padding: 10px 12px; text-align: left; border-bottom: 1px solid #3d3d4a; }
            th { background: #3d3d4a; font-weight: bold; color: #00d4ff; font-size: 12px; }
            tr:hover { background: #3d3d4a33; }
        </style>
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            <script>
                (function () {
                    var tradePriceLines = [];

                    function getDebug() {
                        return window.lwcDebug || function () {};
                    }

                    function getCandleSeries() {
                        if (!window.lwcManager || typeof window.lwcManager.getCandleSeries !== 'function') {
                            return null;
                        }
                        try {
                            return window.lwcManager.getCandleSeries();
                        } catch (e) {
                            return null;
                        }
                    }

                    function clearTradeLines() {
                        var candleSeries = getCandleSeries();
                        if (!candleSeries) {
                            tradePriceLines = [];
                            return;
                        }
                        tradePriceLines.forEach(function (line) {
                            try {
                                candleSeries.removePriceLine(line);
                            } catch (e) {}
                        });
                        tradePriceLines = [];
                    }

                    function addTradeLine(candleSeries, price, color, title, lineStyle) {
                        if (!candleSeries || price === null || price === undefined || price === '') return;
                        var numericPrice = parseFloat(price);
                        if (!isFinite(numericPrice)) return;
                        try {
                            tradePriceLines.push(candleSeries.createPriceLine({
                                price: numericPrice,
                                color: color,
                                lineWidth: 1,
                                lineStyle: lineStyle,
                                axisLabelVisible: true,
                                title: title
                            }));
                        } catch (e) {
                            getDebug()('ERR', 'createPriceLine selhal: ' + e.message);
                        }
                    }

                    function setTradeLines(trades) {
                        var candleSeries = getCandleSeries();
                        if (!candleSeries) {
                            setTimeout(function () { setTradeLines(trades || []); }, 300);
                            return;
                        }

                        clearTradeLines();

                        if (!Array.isArray(trades) || trades.length === 0) {
                            getDebug()('TRADE', 'Trade lines cleared');
                            return;
                        }

                        trades.forEach(function (trade) {
                            var side = ((trade && trade.side) || 'BUY').toUpperCase();
                            addTradeLine(
                                candleSeries,
                                trade.entry_price,
                                side === 'BUY' ? '#ffd54f' : '#ffffff',
                                'Entry',
                                LightweightCharts.LineStyle.Solid
                            );
                            if (trade.sl !== null && trade.sl !== undefined) {
                                addTradeLine(
                                    candleSeries,
                                    trade.sl,
                                    '#ef5350',
                                    'SL',
                                    LightweightCharts.LineStyle.Dashed
                                );
                            }
                            if (trade.tp !== null && trade.tp !== undefined) {
                                addTradeLine(
                                    candleSeries,
                                    trade.tp,
                                    '#26a69a',
                                    'TP',
                                    LightweightCharts.LineStyle.Dashed
                                );
                            }
                        });

                        getDebug()('TRADE', 'Trade lines updated: ' + trades.length + ' trade(s), ' + tradePriceLines.length + ' line(s)');
                    }

                    function attachTradeLines() {
                        if (!window.lwcManager) {
                            setTimeout(attachTradeLines, 300);
                            return;
                        }
                        window.lwcManager.setTradeLines = setTradeLines;
                    }

                    attachTradeLines();
                })();
            </script>
            {%renderer%}
        </footer>
    </body>
</html>
'''


# ========== RUN ==========

if __name__ == '__main__':
    log("INFO", "🚀 Starting IB Trading Platform v3.0.0...")
    log("INFO", f"Connecting to {config.IB_HOST}:{config.IB_PORT}")
    if ib_gateway.connect():
        log("INFO", "✅ Connected to IB Gateway!")
        time.sleep(2)  # Give TWS time to release session
    else:
        log("INFO", "❌ Failed to connect")
    log("INFO", "http://localhost:8050  |  Ctrl+C to stop")
    app.run_server(debug=True, use_reloader=False, host='0.0.0.0', port=8050)

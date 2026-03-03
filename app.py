import dash
from dash import dcc, html, Input, Output, State
from datetime import datetime, timedelta
from flask import jsonify
from ib_connector import IBConnector
import config
from modules.data_store import data_store
from modules.indicators import SMA, EMA, RSI, MACD
import time

app = dash.Dash(
    __name__,
    title="IB Trading Platform",
    update_title=None,
    suppress_callback_exceptions=True,
    serve_locally=True
)

ib = IBConnector()
server = app.server

_cb_status = {
    'step': 'idle', 'symbol': None, 'tf': None,
    'bars': None, 'error': None, 'ts': None,
}

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
    sym   = symbol.upper()
    price = ib.get_latest_price(sym)
    return jsonify({'time': int(datetime.now().timestamp()), 'price': price})

@server.route('/api/deep_load_status/<symbol>/<tf>')
def deep_load_status(symbol, tf):
    return jsonify(ib.get_deep_load_status(symbol.upper(), tf.replace('_', ' ')))


@server.route('/api/diag/tick/<symbol>')
def api_diag_tick(symbol):
    sym = symbol.upper()
    ts  = ib._tick_sub
    return jsonify({
        'symbol':             sym,
        'tick_sub_connected': ts.is_connected,
        'iterations':         ts.iterations,
        'mdt':                ts._mdt,
        'mode':               ts.mode,
        'subscribed_symbols': ts.subscribed_symbols,
        'pending':            list(ts._pending),
        'latest':             ts._latest.get(sym, {}),
        'raw_fields':         ts.get_raw_data(sym),
        'ib_errors':          ts.get_last_errors(),
        'time':               datetime.now().strftime('%H:%M:%S')
    })


@server.route('/api/test/snapshot/<symbol>')
def api_test_snapshot(symbol):
    import asyncio
    from ib_async import IB, Stock

    sym    = symbol.upper()
    result = {}

    async def _do_snapshot():
        ib_test = IB()
        errors  = []
        def on_err(reqId, code, msg, c):
            errors.append(f"[{code}] {msg}")
        ib_test.errorEvent += on_err
        try:
            await ib_test.connectAsync(
                config.IB_HOST, config.IB_PORT,
                clientId=config.IB_CLIENT_ID + 9
            )
            ib_test.reqMarketDataType(3)
            contract = Stock(sym, 'SMART', 'USD')
            await ib_test.qualifyContractsAsync(contract)
            snaps = await ib_test.reqTickersAsync(contract)
            if snaps:
                t = snaps[0]
                def s(v):
                    if v is None: return None
                    if isinstance(v, float) and v != v: return 'NaN'
                    return v
                result.update({
                    'ok':     True,
                    'symbol': sym,
                    'conId':  contract.conId,
                    'last':   s(t.last),
                    'close':  s(t.close),
                    'bid':    s(t.bid),
                    'ask':    s(t.ask),
                    'volume': s(t.volume),
                    'errors': errors,
                    'time':   datetime.now().strftime('%H:%M:%S')
                })
            else:
                result.update({'ok': False, 'error': 'no tickers returned', 'errors': errors})
        except Exception as e:
            result.update({'ok': False, 'error': str(e), 'errors': errors})
        finally:
            try: ib_test.disconnect()
            except Exception: pass

    asyncio.run(_do_snapshot())
    return jsonify(result)


@server.route('/api/diag')
def api_diag():
    return jsonify({
        'connected':   ib.is_connected(),
        'account_id':  ib.account_id,
        'cb_status':   _cb_status,
        'app_state':   app_state,
        'tick_sub': {
            'connected':  ib._tick_sub.is_connected,
            'iterations': ib._tick_sub.iterations,
            'mdt':        ib._tick_sub._mdt,
            'mode':       ib._tick_sub.mode,
            'subscribed': ib._tick_sub.subscribed_symbols,
            'ib_errors':  ib._tick_sub.get_last_errors(),
        },
        'time': datetime.now().strftime('%H:%M:%S')
    })


@server.route('/api/test-hist/<symbol>')
def api_test_hist(symbol):
    t0 = time.time()
    try:
        if not ib.is_connected():
            return jsonify({'ok': False, 'error': 'NOT CONNECTED', 'elapsed': 0})
        bars    = ib.get_historical_data(symbol.upper(), '2 D', '5 mins')
        elapsed = round(time.time() - t0, 2)
        if bars:
            return jsonify({'ok': True, 'bars': len(bars), 'elapsed': elapsed,
                            'first': bars[0], 'last': bars[-1]})
        return jsonify({'ok': False, 'error': 'EMPTY', 'elapsed': elapsed})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e),
                        'elapsed': round(time.time() - t0, 2)})


@server.route('/api/cb-status')
def api_cb_status():
    return jsonify(_cb_status)


# ----------------------------------------------------------------
# INDICATORS ENDPOINT
# GET /api/indicators/<SYMBOL>/<TF>?active=sma,ema,rsi,macd
#     &sma_p=20 &ema_p=20 &rsi_p=14
# Vraci JSON s vypocitanymi hodnotami indikatorů z Parquet cache.
# ----------------------------------------------------------------
@server.route('/api/indicators/<symbol>/<tf>')
def api_indicators(symbol, tf):
    from flask import request as freq
    sym       = symbol.upper()
    timeframe = tf.replace('_', ' ')
    active    = [x.strip() for x in freq.args.get('active', 'ema,rsi').split(',') if x.strip()]

    bars = data_store.get_bars(sym, timeframe)
    if not bars:
        return jsonify({'ok': False, 'error': 'no_data', 'bars': 0,
                        'symbol': sym, 'tf': timeframe})

    result = {'ok': True, 'symbol': sym, 'tf': timeframe, 'bars': len(bars)}
    try:
        if 'sma' in active:
            p = int(freq.args.get('sma_p', 20))
            result['sma']  = SMA(period=p).calculate(bars)
            result['sma_period'] = p
        if 'ema' in active:
            p = int(freq.args.get('ema_p', 20))
            result['ema']  = EMA(period=p).calculate(bars)
            result['ema_period'] = p
        if 'rsi' in active:
            p = int(freq.args.get('rsi_p', 14))
            result['rsi']  = RSI(period=p).calculate(bars)
            result['rsi_period'] = p
        if 'macd' in active:
            result['macd'] = MACD().calculate(bars)
    except Exception as e:
        result['warning'] = str(e)

    return jsonify(result)


# ================================================================

app_state = {'current_symbol': 'AAPL', 'current_timeframe': '5 mins'}

# ========== LAYOUT ==========

app.layout = html.Div([
    html.Div([
        html.H1("🚀 IB Trading Platform v2.8",
                style={'display': 'inline-block', 'margin': 0, 'color': '#00d4ff'}),
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

    html.Div([
        html.Div([
            html.Label('Symbol:', style={'marginRight': '10px', 'fontWeight': 'bold'}),
            dcc.Input(
                id='symbol-input', type='text', value='AAPL',
                style={'width': '150px', 'padding': '8px', 'borderRadius': '5px',
                       'border': '2px solid #667eea', 'background': '#1e1e2e',
                       'color': 'white', 'fontSize': '16px'}
            ),
            html.Button(
                'Load Chart', id='load-chart-btn', n_clicks=0,
                style={'marginLeft': '10px', 'padding': '8px 20px',
                       'background': 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
                       'border': 'none', 'borderRadius': '5px',
                       'color': 'white', 'cursor': 'pointer', 'fontWeight': 'bold'}
            )
        ], style={'display': 'inline-block', 'marginRight': '30px'}),
        html.Div([
            html.Span(id='price-display', children='Last: $0.00',
                      style={'fontSize': '20px', 'fontWeight': 'bold'}),
            html.Span(id='price-change-display', children='',
                      style={'fontSize': '16px', 'marginLeft': '15px'})
        ], style={'display': 'inline-block'})
    ], style={'padding': '15px', 'background': '#2d2d3a',
              'borderRadius': '8px', 'marginBottom': '20px'}),

    html.Div([
        html.Div([
            html.Div([
                html.Button('1m',  id='tf-1m',  n_clicks=0, className='tf-btn'),
                html.Button('5m',  id='tf-5m',  n_clicks=0, className='tf-btn tf-active'),
                html.Button('15m', id='tf-15m', n_clicks=0, className='tf-btn'),
                html.Button('30m', id='tf-30m', n_clicks=0, className='tf-btn'),
                html.Button('1h',  id='tf-1h',  n_clicks=0, className='tf-btn'),
                html.Button('1D',  id='tf-1d',  n_clicks=0, className='tf-btn'),
                html.Button('📥 Stáhnout historii', id='deep-load-btn', n_clicks=0, style={'marginLeft': '20px', 'padding': '8px 15px', 'background': '#ff9800', 'color': 'black', 'border': 'none', 'borderRadius': '5px', 'cursor': 'pointer', 'fontWeight': 'bold'}),
                html.Span(id='chart-loading-indicator', children='',
                          style={'marginLeft': '15px', 'fontSize': '13px',
                                 'color': '#ffa726', 'fontStyle': 'italic',
                                 'verticalAlign': 'middle'})
            ], style={'display': 'inline-block'}),
            html.Div([
                html.Div(id='cache-status-indicator', children='Cache: Zjišťuji...', style={'display': 'inline-block', 'marginRight': '15px', 'fontSize': '12px', 'color': '#4caf50', 'padding': '5px 10px', 'background': '#1b5e20', 'borderRadius': '4px'}),
                html.Span('⚠️ 15min delay na demo',
                          style={'fontSize': '11px', 'color': '#666',
                                 'marginRight': '10px', 'verticalAlign': 'middle'}),
                html.Button('⚡ TICK: OFF', id='tick-toggle-btn',
                            n_clicks=0, className='tick-btn tick-off')
            ], style={'display': 'inline-block', 'float': 'right'})
        ], style={'marginBottom': '10px', 'overflow': 'hidden'}),

        # ----------------------------------------------------------
        # INDICATOR TOGGLE PANEL
        # ----------------------------------------------------------
        html.Div([
            html.Span('📊 Indikátory:',
                      style={'fontWeight': 'bold', 'marginRight': '12px',
                             'fontSize': '13px', 'color': '#aaa',
                             'verticalAlign': 'middle'}),
            html.Button('SMA 20',  id='ind-sma-btn',  n_clicks=0, className='ind-btn',
                        title='Simple Moving Average (20)'),
            html.Button('EMA 20',  id='ind-ema-btn',  n_clicks=1, className='ind-btn ind-active',
                        title='Exponential Moving Average (20)'),
            html.Button('RSI 14',  id='ind-rsi-btn',  n_clicks=1, className='ind-btn ind-active',
                        title='Relative Strength Index (14)'),
            html.Button('MACD',    id='ind-macd-btn', n_clicks=0, className='ind-btn',
                        title='MACD 12/26/9'),
            html.Span(id='indicators-status', children='',
                      style={'marginLeft': '15px', 'fontSize': '12px',
                             'color': '#888', 'fontStyle': 'italic'}),
        ], style={'marginBottom': '10px', 'paddingTop': '10px',
                  'borderTop': '1px solid #3d3d4a'}),
        # ----------------------------------------------------------

        html.Div(id='lwc-container',
                 style={'width': '100%', 'height': '500px', 'position': 'relative',
                        'background': '#1e1e2e'}),

        dcc.Store(id='chart-data-store'),
        dcc.Store(id='chart-trigger-store'),
        dcc.Store(id='test-chart-trigger'),
        dcc.Store(id='clear-log-trigger'),
        dcc.Store(id='copy-log-trigger'),
        dcc.Store(id='load-click-log'),
        dcc.Store(id='diag1-trigger'),
        dcc.Store(id='diag2-trigger'),
        dcc.Store(id='diag3-trigger'),
        dcc.Store(id='diag-tick-trigger'),
        dcc.Store(id='diag-snap-trigger'),
        dcc.Store(id='active-tf-store', data='tf-5m'),
        dcc.Store(id='tick-enabled-store', data=False),
        dcc.Store(id='deep-load-finished-trigger', data=False),
        # Indicator stores
        dcc.Store(id='indicator-settings-store',
                  data={'sma': False, 'ema': True, 'rsi': True, 'macd': False}),
        dcc.Store(id='indicators-data-store'),

    ], style={'padding': '20px', 'background': '#2d2d3a',
              'borderRadius': '8px', 'marginBottom': '20px'}),

    html.Div([
        html.H3('📥 Order Entry', style={'marginBottom': '15px'}),
        html.Div([
            html.Label('Quantity:', style={'marginRight': '10px', 'fontWeight': 'bold'}),
            html.Button('1',   id='qty-1',   n_clicks=0, className='qty-btn'),
            html.Button('5',   id='qty-5',   n_clicks=0, className='qty-btn'),
            html.Button('10',  id='qty-10',  n_clicks=0, className='qty-btn'),
            html.Button('25',  id='qty-25',  n_clicks=0, className='qty-btn'),
            html.Button('100', id='qty-100', n_clicks=0, className='qty-btn'),
            dcc.Input(id='qty-custom', type='number', value=1, min=1,
                      style={'width': '80px', 'marginLeft': '10px', 'padding': '8px',
                             'borderRadius': '5px', 'border': '2px solid #667eea',
                             'background': '#1e1e2e', 'color': 'white'})
        ], style={'marginBottom': '15px'}),
        html.Div([
            html.Button('🟢 BUY MARKET', id='buy-btn', n_clicks=0,
                        style={'padding': '15px 40px',
                               'background': 'linear-gradient(135deg, #26a69a 0%, #1a7f6f 100%)',
                               'border': 'none', 'borderRadius': '8px', 'color': 'white',
                               'fontSize': '18px', 'fontWeight': 'bold',
                               'cursor': 'pointer', 'marginRight': '15px'}),
            html.Button('🔴 SELL MARKET', id='sell-btn', n_clicks=0,
                        style={'padding': '15px 40px',
                               'background': 'linear-gradient(135deg, #ef5350 0%, #c62828 100%)',
                               'border': 'none', 'borderRadius': '8px', 'color': 'white',
                               'fontSize': '18px', 'fontWeight': 'bold', 'cursor': 'pointer'})
        ]),
        html.Div(id='order-feedback', style={'marginTop': '15px', 'fontSize': '16px'})
    ], style={'padding': '20px', 'background': '#2d2d3a',
              'borderRadius': '8px', 'marginBottom': '20px'}),

    html.Div([
        html.H3('📊 Open Positions', style={'marginBottom': '15px'}),
        html.Div(id='positions-table')
    ], style={'padding': '20px', 'background': '#2d2d3a',
              'borderRadius': '8px', 'marginBottom': '20px'}),

    html.Div([
        html.H3('📋 Recent Orders', style={'marginBottom': '15px'}),
        html.Div(id='orders-table')
    ], style={'padding': '20px', 'background': '#2d2d3a',
              'borderRadius': '8px', 'marginBottom': '20px'}),

    # DEBUG PANEL
    html.Div([
        html.H3('🔧 Debug Panel',
                style={'marginBottom': '10px', 'color': '#ff9800'}),
        html.Div([
            html.Span('Python callback: ', style={'fontWeight': 'bold', 'color': '#00d4ff'}),
            html.Span(id='debug-python-info', children='(ceka na Load Chart...)',
                      style={'fontFamily': 'monospace', 'fontSize': '13px'})
        ], style={'marginBottom': '12px', 'padding': '8px',
                  'background': '#0d0d1a', 'borderRadius': '5px'}),
        html.Div([
            html.Div('🧪 Diagnostika:',
                     style={'color': '#ff9800', 'fontWeight': 'bold',
                            'marginBottom': '8px', 'fontSize': '13px'}),
            html.Button('1️⃣ IB Spojeni', id='diag1-btn', n_clicks=0,
                        style={'padding': '10px 14px', 'marginRight': '6px',
                               'background': '#1565c0', 'border': 'none',
                               'borderRadius': '5px', 'color': 'white', 'cursor': 'pointer'}),
            html.Button('2️⃣ Hist. data', id='diag2-btn', n_clicks=0,
                        style={'padding': '10px 14px', 'marginRight': '6px',
                               'background': '#6a1599', 'border': 'none',
                               'borderRadius': '5px', 'color': 'white', 'cursor': 'pointer'}),
            html.Button('3️⃣ Nakreslit', id='diag3-btn', n_clicks=0,
                        style={'padding': '10px 14px', 'marginRight': '6px',
                               'background': '#1b5e20', 'border': 'none',
                               'borderRadius': '5px', 'color': 'white', 'cursor': 'pointer'}),
            html.Button('🔍 Tick Diag', id='diag-tick-btn', n_clicks=0,
                        style={'padding': '10px 14px', 'marginRight': '6px',
                               'background': '#4a148c', 'border': 'none',
                               'borderRadius': '5px', 'color': 'white', 'cursor': 'pointer',
                               'fontWeight': 'bold'}),
            html.Button('📸 Snapshot Test', id='diag-snap-btn', n_clicks=0,
                        style={'padding': '10px 14px', 'marginRight': '6px',
                               'background': '#b71c1c', 'border': 'none',
                               'borderRadius': '5px', 'color': 'white', 'cursor': 'pointer',
                               'fontWeight': 'bold'}),
        ], style={'marginBottom': '12px', 'padding': '10px',
                  'background': '#0d1a2e', 'borderRadius': '5px',
                  'border': '1px solid #1565c0'}),
        html.Div([
            html.Button('🧪 Test Chart', id='test-chart-btn', n_clicks=0,
                        style={'padding': '10px 20px', 'marginRight': '10px',
                               'background': '#ff9800', 'border': 'none',
                               'borderRadius': '5px', 'color': 'black', 'cursor': 'pointer'}),
            html.Button('📋 Zkopirovat', id='copy-log-btn', n_clicks=0,
                        style={'padding': '10px 20px', 'marginRight': '10px',
                               'background': '#26a69a', 'border': 'none',
                               'borderRadius': '5px', 'color': 'white', 'cursor': 'pointer'}),
            html.Button('🗑️ Smazat', id='clear-log-btn', n_clicks=0,
                        style={'padding': '10px 20px', 'background': '#555',
                               'border': 'none', 'borderRadius': '5px',
                               'color': 'white', 'cursor': 'pointer'}),
            html.Span(id='copy-status',
                      style={'marginLeft': '10px', 'color': '#26a69a', 'fontSize': '13px'})
        ], style={'marginBottom': '10px'}),
        html.Textarea(
            id='debug-log-area', rows=22,
            placeholder='JS debug log...',
            style={'width': '100%', 'boxSizing': 'border-box',
                   'background': '#0d0d0d', 'color': '#00ff00',
                   'fontFamily': 'monospace', 'fontSize': '12px',
                   'border': '1px solid #333', 'borderRadius': '5px',
                   'padding': '10px', 'resize': 'vertical'}
        ),
        html.Div('[INIT] [BTN] [CB] [TF] [TICK] [API] [DATA] [IND] [ERR] | v2.8',
                 style={'marginTop': '8px', 'fontSize': '12px', 'color': '#888'})
    ], style={'padding': '20px', 'background': '#1a1a2e',
              'borderRadius': '8px', 'marginBottom': '20px',
              'border': '2px solid #ff9800'}),

    dcc.Interval(id='cache-update-interval', interval=2000, n_intervals=0),
    dcc.Interval(id='price-update-interval',     interval=10000, n_intervals=0),
    dcc.Interval(id='positions-update-interval', interval=30000, n_intervals=0),
    dcc.Interval(id='connection-check-interval', interval=10000, n_intervals=0),
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
    if ib.is_connected():
        return html.Span([html.Span('⚪', style={'color': '#26a69a', 'marginRight': '5px'}),
                          html.Span('Connected to IB Gateway')])
    return html.Span([html.Span('⚪', style={'color': '#ef5350', 'marginRight': '5px'}),
                      html.Span('Disconnected')])


@app.callback(
    [Output('account-id', 'children'),
     Output('account-balance', 'children'),
     Output('buying-power', 'children')],
    Input('connection-check-interval', 'n_intervals')
)
def update_account_info(n):
    if not ib.is_connected():
        return 'Not Connected', '$0.00', '$0.00'
    d = ib.get_account_info()
    return (d.get('account_id', 'N/A'),
            f"${d.get('net_liquidation', 0):,.2f}",
            f"${d.get('buying_power', 0):,.2f}")


@app.callback(
    Output('chart-data-store', 'data'),
    [Input('load-chart-btn', 'n_clicks'),
     Input('tf-1m',  'n_clicks'), Input('tf-5m',  'n_clicks'),
     Input('tf-15m', 'n_clicks'), Input('tf-30m', 'n_clicks'),
     Input('tf-1h',  'n_clicks'), Input('tf-1d',  'n_clicks'),
     Input('deep-load-finished-trigger', 'data')],
    State('symbol-input', 'value'),
    prevent_initial_call=True
)
def load_chart_data(load_clicks, tf1, tf5, tf15, tf30, tf1h, tf1d, dl_trigger, symbol):
    global _cb_status
    try:
        ctx = dash.callback_context
        btn = (ctx.triggered[0]['prop_id'].split('.')[0]
               if ctx.triggered else 'load-chart-btn')

        tf_map = {'tf-1m': '1 min', 'tf-5m': '5 mins',
                  'tf-15m': '15 mins', 'tf-30m': '30 mins',
                  'tf-1h': '1 hour', 'tf-1d': '1 day'}
        if btn in tf_map:
            app_state['current_timeframe'] = tf_map[btn]

        symbol   = (symbol or 'AAPL').upper()
        app_state['current_symbol'] = symbol
        tf       = app_state['current_timeframe']
        duration = DURATION_MAP.get(tf, '1 D')

        _cb_status = {'step': 'started', 'symbol': symbol, 'tf': tf,
                      'bars': None, 'error': None,
                      'ts': datetime.now().strftime('%H:%M:%S')}
        print(f"[CB] START: {symbol} | {tf} | duration={duration} | Trigger={btn}")
        _cb_status['step'] = 'requesting_IB'

        bars = ib.get_historical_data(symbol, duration, tf)

        _cb_status['step'] = 'IB_returned'
        _cb_status['bars'] = len(bars)
        print(f"[CB] IB/Cache returned {len(bars)} bars")
        _cb_status['step'] = 'done'
        return {'symbol': symbol, 'timeframe': tf, 'bars': bars}
    except Exception as e:
        _cb_status['step'] = 'ERROR'
        _cb_status['error'] = str(e)
        print(f"[CB] EXCEPTION: {e}")
        return dash.no_update


@app.callback(
    Output('debug-python-info', 'children'),
    Input('chart-data-store', 'data')
)
def update_debug_python(data):
    if not data: return '(prazdne)'
    bars = data.get('bars', [])
    if not bars:
        return f"⚠️ {data.get('symbol')} | {data.get('timeframe')} | 0 BARU"
    b0 = bars[0]
    return (f"✅ {data.get('symbol')} | {data.get('timeframe')} "
            f"| {len(bars)} baru | close[0]={b0['close']} close[-1]={bars[-1]['close']:.2f}")


# --- DEEP LOAD LOGIC ---
@app.callback(
    Output('deep-load-trigger-dummy', 'children'),
    Input('deep-load-btn', 'n_clicks'),
    State('symbol-input', 'value')
)
def start_deep_load(n, symbol):
    if n > 0 and symbol:
        tf = app_state.get('current_timeframe', '5 mins')
        ib.start_deep_load(symbol.upper(), tf)
    return dash.no_update


@app.callback(
    [Output('cache-status-indicator', 'children'),
     Output('deep-load-finished-trigger', 'data')],
    Input('cache-update-interval', 'n_intervals'),
    [State('symbol-input', 'value'),
     State('deep-load-finished-trigger', 'data')]
)
def update_cache_status(n, symbol, last_dl_state):
    if not symbol: return "Vyberte symbol", dash.no_update
    sym = symbol.upper()
    tf  = app_state.get('current_timeframe', '5 mins')

    dl_status        = ib.get_deep_load_status(sym, tf)
    current_dl_state = dl_status.get('status')

    trigger_refresh = dash.no_update
    if current_dl_state == 'done':
        new_dl_trigger = f"{sym}_{tf}_done_{time.time()}"
        if not str(last_dl_state).startswith(f"{sym}_{tf}_done"):
            trigger_refresh = new_dl_trigger
            last_dl_state   = new_dl_trigger
    elif current_dl_state == 'running':
        last_dl_state = "running"

    if current_dl_state == 'running':
        return html.Span(
            f"⏳ Stahuji historii: {dl_status.get('progress', '0%')} ({dl_status.get('msg', '')})",
            style={'color': '#ff9800'}
        ), trigger_refresh

    status = data_store.get_cache_status(sym, tf)
    if not status['cached']:
        return html.Span("Cache: Prázdná", style={'color': '#888', 'background': '#333'}), trigger_refresh

    bars_str = f"{status['total_bars']:,}".replace(',', ' ')
    age = status['age_seconds']
    if age < 60:     age_str = f"{int(age)}s"
    elif age < 3600: age_str = f"{int(age//60)}m"
    elif age < 86400:age_str = f"{int(age//3600)}h"
    else:            age_str = f"{int(age//86400)}d"

    if status['is_fresh']:
        return html.Span(f"💾 Parquet: {bars_str} barů | Aktuální",
                         style={'color': '#4caf50', 'background': '#1b5e20'}), trigger_refresh
    return html.Span(f"💾 Parquet: {bars_str} barů | {age_str} staré",
                     style={'color': '#ffeb3b', 'background': '#e65100'}), trigger_refresh


# ========== CLIENTSIDE CALLBACKS ==========

app.clientside_callback(
    """function(n){if(n>0&&window.lwcDebug)window.lwcDebug('BTN','Load Chart n='+n+' - cekam na Python/IB...');return n;}""",
    Output('load-click-log', 'data'), Input('load-chart-btn', 'n_clicks')
)

app.clientside_callback(
    """
    function(n, currentEnabled) {
        var enabled = (n > 0) ? !currentEnabled : currentEnabled;
        if (n > 0) {
            if (window.lwcManager) window.lwcManager.setTickEnabled(enabled);
            if (window.lwcDebug)
                window.lwcDebug('TICK', 'Tick ' + (enabled ? 'ZAPNUT ⚡ (15min delay na demo!)' : 'VYPNUT'));
        }
        var label = '⚡ TICK: ' + (enabled ? 'ON' : 'OFF');
        var cls   = 'tick-btn ' + (enabled ? 'tick-on' : 'tick-off');
        return [enabled, label, cls];
    }
    """,
    [Output('tick-enabled-store', 'data'),
     Output('tick-toggle-btn', 'children'),
     Output('tick-toggle-btn', 'className')],
    Input('tick-toggle-btn', 'n_clicks'),
    State('tick-enabled-store', 'data')
)

# ----------------------------------------------------------
# INDICATOR TOGGLE: aktualizuje settings store + CSS třídy
# ----------------------------------------------------------
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
     Output('ind-sma-btn',  'className'),
     Output('ind-ema-btn',  'className'),
     Output('ind-rsi-btn',  'className'),
     Output('ind-macd-btn', 'className')],
    [Input('ind-sma-btn',  'n_clicks'),
     Input('ind-ema-btn',  'n_clicks'),
     Input('ind-rsi-btn',  'n_clicks'),
     Input('ind-macd-btn', 'n_clicks')],
    State('indicator-settings-store', 'data')
)

# ----------------------------------------------------------
# FETCH INDICATORS: spusti se kdyz se zmeni data grafu NEBO settings
# Vola /api/indicators a predava data do lwcManager.setIndicators()
# ----------------------------------------------------------
app.clientside_callback(
    """
    function(chartData, settings) {
        var d = window.lwcDebug || function() {};

        if (!chartData || !chartData.bars || chartData.bars.length === 0)
            return window.dash_clientside.no_update;

        var sym    = chartData.symbol;
        var tf     = chartData.timeframe.replace(/ /g, '_');
        var active = [];
        if (settings.sma)  active.push('sma');
        if (settings.ema)  active.push('ema');
        if (settings.rsi)  active.push('rsi');
        if (settings.macd) active.push('macd');

        // Zrus indikatory kdyz jsou vsechny vypnute
        if (active.length === 0) {
            d('IND', 'Vsechny indikatory vypnuty');
            if (window.lwcManager && window.lwcManager.setIndicators)
                window.lwcManager.setIndicators({ok: true, sma: null, ema: null,
                                                  rsi: null, macd: null});
            return null;
        }

        var url = '/api/indicators/' + sym + '/' + tf + '?active=' + active.join(',');
        d('IND', 'Fetching: ' + url);

        fetch(url)
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (!data.ok) {
                    d('ERR', 'IND FAIL: ' + (data.error || 'unknown'));
                    return;
                }
                d('IND', 'OK: ' + active.join(',') + ' | parquet bars=' + data.bars);
                if (window.lwcManager && window.lwcManager.setIndicators) {
                    window.lwcManager.setIndicators(data);
                } else {
                    d('ERR', 'lwcManager.setIndicators() neexistuje - nutno pridat do assets JS');
                }
            })
            .catch(function(e) { d('ERR', 'IND fetch error: ' + e); });

        return window.dash_clientside.no_update;
    }
    """,
    Output('indicators-data-store', 'data'),
    [Input('chart-data-store',        'data'),
     Input('indicator-settings-store','data')]
)

# Tick Diag
app.clientside_callback(
    """
    function(n) {
        if (n < 1) return n;
        var d = window.lwcDebug || function() {};
        var sym = (document.getElementById('symbol-input') &&
                   document.getElementById('symbol-input').value || 'AAPL').toUpperCase();
        d('API', '=== TICK DIAG: ' + sym + ' ===');
        fetch('/api/diag/tick/' + sym)
            .then(function(r) { return r.json(); })
            .then(function(j) {
                d('API', 'connected=' + j.tick_sub_connected
                    + '  iter=' + j.iterations
                    + '  mdt='  + j.mdt
                    + '  mode=' + j.mode);
                d('API', 'subscribed=' + JSON.stringify(j.subscribed_symbols));
                var lx = j.latest;
                d('API', 'LATEST: price=' + (lx.price||0)
                    + '  last=' + (lx.last||0) + '  close=' + (lx.close||0)
                    + '  bid='  + (lx.bid||0)  + '  ask='   + (lx.ask||0));
                var rf = j.raw_fields;
                if (rf.error) {
                    d('ERR', 'RAW: ' + rf.error);
                } else {
                    d('API', 'RAW: last=' + rf.last + '  close=' + rf.close
                        + '  bid=' + rf.bid + '  ask=' + rf.ask);
                }
                if (j.ib_errors && j.ib_errors.length > 0) {
                    d('ERR', '=== IB ERRORY (' + j.ib_errors.length + ') ===');
                    j.ib_errors.forEach(function(e) { d('ERR', 'IB: ' + e); });
                } else {
                    d('API', 'IB errory: zadne');
                }
            })
            .catch(function(e) { d('ERR', 'TICK DIAG FAIL: ' + e); });
        return n;
    }
    """,
    Output('diag-tick-trigger', 'data'),
    Input('diag-tick-btn', 'n_clicks')
)

# Snapshot Test
app.clientside_callback(
    """
    function(n) {
        if (n < 1) return n;
        var d = window.lwcDebug || function() {};
        var sym = (document.getElementById('symbol-input') &&
                   document.getElementById('symbol-input').value || 'AAPL').toUpperCase();
        d('API', '=== SNAPSHOT TEST: ' + sym + ' (ceka ~3s...) ===');
        fetch('/api/test/snapshot/' + sym)
            .then(function(r) { return r.json(); })
            .then(function(j) {
                if (j.ok) {
                    d('API', 'SNAP OK: last=' + j.last + '  close=' + j.close
                        + '  bid=' + j.bid + '  ask=' + j.ask
                        + '  vol=' + j.volume + '  conId=' + j.conId);
                } else {
                    d('ERR', 'SNAP FAIL: ' + j.error);
                }
                if (j.errors && j.errors.length > 0) {
                    d('ERR', 'Snapshot IB errory: ' + JSON.stringify(j.errors));
                }
            })
            .catch(function(e) { d('ERR', 'SNAP TEST FAIL: ' + e); });
        return n;
    }
    """,
    Output('diag-snap-trigger', 'data'),
    Input('diag-snap-btn', 'n_clicks')
)

# Loading indikator
app.clientside_callback(
    """
    function(n1m, n5m, n15m, n30m, n1h, n1d, nLoad, dlTrigger) {
        var ctx = window.dash_clientside.callback_context;
        if (!ctx || !ctx.triggered || ctx.triggered.length === 0) return '';
        var tid = ctx.triggered_id || ctx.triggered[0].prop_id.split('.')[0];
        if (tid === 'deep-load-finished-trigger') return '✅ Data z cache načtena';
        var labels = {'tf-1m':'1m','tf-5m':'5m','tf-15m':'15m',
                      'tf-30m':'30m','tf-1h':'1h','tf-1d':'1D','load-chart-btn':'Load'};
        return '⏳ Načítám ' + (labels[tid]||tid) + '\u2026';
    }
    """,
    Output('chart-loading-indicator', 'children'),
    [Input('tf-1m', 'n_clicks'), Input('tf-5m', 'n_clicks'),
     Input('tf-15m', 'n_clicks'), Input('tf-30m', 'n_clicks'),
     Input('tf-1h', 'n_clicks'), Input('tf-1d', 'n_clicks'),
     Input('load-chart-btn', 'n_clicks'), Input('deep-load-finished-trigger', 'data')]
)

app.clientside_callback(
    """
    function(n1m, n5m, n15m, n30m, n1h, n1d) {
        var ctx = window.dash_clientside.callback_context;
        if (!ctx || !ctx.triggered || ctx.triggered.length === 0)
            return window.dash_clientside.no_update;
        var tid = ctx.triggered_id || ctx.triggered[0].prop_id.split('.')[0];
        if (window.lwcDebug) {
            var lbl = {'tf-1m':'1m','tf-5m':'5m','tf-15m':'15m',
                       'tf-30m':'30m','tf-1h':'1h','tf-1d':'1D'};
            window.lwcDebug('TF', 'Zmen -> ' + (lbl[tid]||tid) + ' (cekam na IB...)');
        }
        return tid;
    }
    """,
    Output('active-tf-store', 'data'),
    [Input('tf-1m', 'n_clicks'), Input('tf-5m', 'n_clicks'),
     Input('tf-15m', 'n_clicks'), Input('tf-30m', 'n_clicks'),
     Input('tf-1h', 'n_clicks'), Input('tf-1d', 'n_clicks')]
)

app.clientside_callback(
    """
    function(activeTf) {
        var ids = ['tf-1m','tf-5m','tf-15m','tf-30m','tf-1h','tf-1d'];
        return ids.map(function(id) { return id===activeTf?'tf-btn tf-active':'tf-btn'; });
    }
    """,
    [Output('tf-1m',  'className'), Output('tf-5m',  'className'),
     Output('tf-15m', 'className'), Output('tf-30m', 'className'),
     Output('tf-1h',  'className'), Output('tf-1d',  'className')],
    Input('active-tf-store', 'data')
)

app.clientside_callback(
    """
    function(storeData) {
        var d = window.lwcDebug || function() {};
        d('CB', '=== Dash clientside callback spusten ===');
        var li = document.getElementById('chart-loading-indicator');
        if (li && !li.textContent.includes('✅')) li.textContent = '';
        if (!storeData) { d('CB', 'storeData NULL -> no_update'); return window.dash_clientside.no_update; }
        if (!storeData.bars || storeData.bars.length === 0) { d('CB', 'bars prazdne -> no_update'); return window.dash_clientside.no_update; }
        d('CB', 'symbol=' + storeData.symbol + ' tf=' + storeData.timeframe
          + ' baru=' + storeData.bars.length + ' close[0]=' + storeData.bars[0].close);
        if (window.lwcManager) {
            d('CB', 'volam lwcManager.loadData()');
            window.lwcManager.loadData(storeData);
        } else {
            var a=0, r=setInterval(function(){
                a++;
                if(window.lwcManager){window.lwcManager.loadData(storeData);clearInterval(r);}
                else if(a>20){d('ERR','lwcManager nenalezen!');clearInterval(r);}
            },200);
        }
        return storeData.symbol||'ok';
    }
    """,
    Output('chart-trigger-store', 'data'),
    Input('chart-data-store', 'data')
)

app.clientside_callback(
    """function(n){if(n<1)return n;var d=window.lwcDebug||function(){};d('API','=== TEST 1: IB spojeni ===');fetch('/api/diag').then(r=>r.json()).then(j=>{d('API','connected='+j.connected+' account='+j.account_id);d('API','tick_sub: connected='+j.tick_sub.connected+' iter='+j.tick_sub.iterations+' mdt='+j.tick_sub.mdt+' mode='+j.tick_sub.mode);if(j.tick_sub.ib_errors&&j.tick_sub.ib_errors.length>0){d('ERR','IB errory: '+JSON.stringify(j.tick_sub.ib_errors));}}).catch(e=>d('ERR','FAIL: '+e));return n;}""",
    Output('diag1-trigger', 'data'), Input('diag1-btn', 'n_clicks')
)
app.clientside_callback(
    """function(n){if(n<1)return n;var d=window.lwcDebug||function(){};d('API','TEST 2: Hist. data...');fetch('/api/test-hist/AAPL').then(r=>r.json()).then(j=>{if(j.ok)d('API','OK: '+j.bars+' baru za '+j.elapsed+'s');else d('ERR','FAIL: '+j.error);}).catch(e=>d('ERR','FAIL: '+e));return n;}""",
    Output('diag2-trigger', 'data'), Input('diag2-btn', 'n_clicks')
)
app.clientside_callback(
    """function(n){if(n<1)return n;var d=window.lwcDebug||function(){};d('API','TEST 3: Fetch+nakreslit...');fetch('/api/test-hist/AAPL').then(r=>r.json()).then(j=>{if(!j.ok){d('ERR','Fail: '+j.error);return;}d('API','OK: '+j.bars+' baru');if(window.lwcManager)window.lwcManager.testChart();}).catch(e=>d('ERR','FAIL: '+e));return n;}""",
    Output('diag3-trigger', 'data'), Input('diag3-btn', 'n_clicks')
)
app.clientside_callback(
    """function(n){if(n>0&&window.lwcManager)window.lwcManager.testChart();return n;}""",
    Output('test-chart-trigger', 'data'), Input('test-chart-btn', 'n_clicks')
)
app.clientside_callback(
    """function(n){if(n>0){var a=document.getElementById('debug-log-area');if(a){a.select();try{document.execCommand('copy');}catch(e){}a.setSelectionRange(0,0);navigator.clipboard&&navigator.clipboard.writeText(a.value);}}return n>0?'Zkopírováno ✓':'';}""" ,
    Output('copy-status', 'children'), Input('copy-log-btn', 'n_clicks')
)
app.clientside_callback(
    """function(n){if(n>0){var a=document.getElementById('debug-log-area');if(a)a.value='';}return n;}""",
    Output('clear-log-trigger', 'data'), Input('clear-log-btn', 'n_clicks')
)


@app.callback(
    [Output('price-display', 'children'),
     Output('price-change-display', 'children')],
    Input('price-update-interval', 'n_intervals'),
    State('symbol-input', 'value')
)
def update_price_display(n, symbol):
    if not symbol or not ib.is_connected(): return 'Last: $0.00', ''
    ticker = ib.get_ticker(symbol)
    if not ticker: return 'Last: $0.00', ''
    lp = ticker.get('price', 0) or ticker.get('last', 0)
    pc = ticker.get('close', lp) or lp
    if lp <= 0: return 'Last: $0.00', ''
    change = lp - pc
    pct    = (change / pc * 100) if pc > 0 else 0
    arrow  = '▲' if change >= 0 else '▼'
    color  = '#26a69a' if change >= 0 else '#ef5350'
    sign   = '+' if change >= 0 else ''
    return (
        f'Last: ${lp:.2f}',
        html.Span(f' {arrow} {sign}${change:.2f} ({sign}{pct:.2f}%)', style={'color': color})
    )


@app.callback(
    Output('qty-custom', 'value'),
    [Input('qty-1', 'n_clicks'), Input('qty-5', 'n_clicks'),
     Input('qty-10', 'n_clicks'), Input('qty-25', 'n_clicks'),
     Input('qty-100', 'n_clicks')]
)
def update_quantity(q1, q5, q10, q25, q100):
    ctx = dash.callback_context
    if not ctx.triggered: return 1
    btn = ctx.triggered[0]['prop_id'].split('.')[0]
    return {'qty-1': 1, 'qty-5': 5, 'qty-10': 10, 'qty-25': 25, 'qty-100': 100}.get(btn, 1)


@app.callback(
    Output('order-feedback', 'children'),
    [Input('buy-btn', 'n_clicks'), Input('sell-btn', 'n_clicks')],
    [State('symbol-input', 'value'), State('qty-custom', 'value')]
)
def place_order(buy_clicks, sell_clicks, symbol, quantity):
    ctx = dash.callback_context
    if not ctx.triggered: return ''
    btn = ctx.triggered[0]['prop_id'].split('.')[0]
    if btn == 'buy-btn' and buy_clicks > 0:    action, color = 'BUY',  '#26a69a'
    elif btn == 'sell-btn' and sell_clicks > 0: action, color = 'SELL', '#ef5350'
    else: return ''
    if not ib.is_connected():
        return html.Div('❌ Not connected!', style={'color': '#ef5350', 'fontWeight': 'bold'})
    result = ib.place_market_order(symbol, action, quantity)
    if result['success']:
        return html.Div(f'✅ {action} {quantity} {symbol} @ Market',
                        style={'color': color, 'fontWeight': 'bold'})
    return html.Div(f'❌ {result["error"]}',
                    style={'color': '#ef5350', 'fontWeight': 'bold'})


@app.callback(
    Output('positions-table', 'children'),
    Input('positions-update-interval', 'n_intervals')
)
def update_positions_table(n):
    if not ib.is_connected():
        return html.Div('Not connected', style={'color': '#888'})
    positions = ib.get_positions()
    if not positions:
        return html.Div('No open positions', style={'color': '#888'})
    rows = []
    for pos in positions:
        pnl_c = '#26a69a' if pos['unrealized_pnl'] >= 0 else '#ef5350'
        rows.append(html.Tr([
            html.Td(pos['symbol'], style={'fontWeight': 'bold'}),
            html.Td('LONG' if pos['position'] > 0 else 'SHORT', style={'color': '#00d4ff'}),
            html.Td(abs(pos['position'])),
            html.Td(f"${pos['avg_cost']:.2f}"),
            html.Td(f"${pos['market_value']:.2f}"),
            html.Td(f"${pos['unrealized_pnl']:.2f} ({pos['unrealized_pnl_pct']:.2f}%)",
                    style={'color': pnl_c, 'fontWeight': 'bold'})
        ]))
    return html.Table([
        html.Thead(html.Tr([html.Th('Symbol'), html.Th('Side'), html.Th('Qty'),
                            html.Th('Avg Cost'), html.Th('Market Value'), html.Th('P&L')])),
        html.Tbody(rows)
    ], style={'width': '100%', 'borderCollapse': 'collapse'})


@app.callback(
    Output('orders-table', 'children'),
    Input('positions-update-interval', 'n_intervals')
)
def update_orders_table(n):
    if not ib.is_connected():
        return html.Div('Not connected', style={'color': '#888'})
    orders = ib.get_recent_orders(limit=10)
    if not orders:
        return html.Div('No recent orders', style={'color': '#888'})
    icons  = {'Filled': '✅', 'Submitted': '⏳',
               'Cancelled': '❌', 'PendingSubmit': '🕒'}
    colors = {'Filled': '#26a69a', 'Submitted': '#ffa726',
               'Cancelled': '#ef5350', 'PendingSubmit': '#42a5f5'}
    rows = []
    for o in orders:
        rows.append(html.Tr([
            html.Td(o['time']),
            html.Td(f"{o['action']} {o['quantity']} {o['symbol']}"),
            html.Td(f"@ {o['price']}"),
            html.Td(f"{icons.get(o['status'],'?')} {o['status']}",
                    style={'color': colors.get(o['status'], '#888'), 'fontWeight': 'bold'})
        ]))
    return html.Table([
        html.Thead(html.Tr([html.Th('Time'), html.Th('Order'),
                            html.Th('Price'), html.Th('Status')])),
        html.Tbody(rows)
    ], style={'width': '100%', 'borderCollapse': 'collapse'})


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
            th, td { padding: 12px; text-align: left; border-bottom: 1px solid #3d3d4a; }
            th { background: #3d3d4a; font-weight: bold; color: #00d4ff; }
            tr:hover { background: #3d3d4a; }
        </style>
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>
'''


# ========== RUN ==========

if __name__ == '__main__':
    print("🚀 Starting IB Trading Platform v2.8.0...")
    print(f"Connecting to {config.IB_HOST}:{config.IB_PORT}")
    if ib.connect():
        print("✅ Connected to IB Gateway!")
    else:
        print("❌ Failed to connect")
    print("http://localhost:8050  |  Ctrl+C to stop\n")
    app.run_server(debug=True, use_reloader=False, host='0.0.0.0', port=8050)

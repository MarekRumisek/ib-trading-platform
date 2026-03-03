import dash
from dash import dcc, html, Input, Output, State
from datetime import datetime, timedelta
from flask import jsonify, request as freq
from ib_connector import IBConnector
import config
from modules.data_store import data_store
from modules.indicators import SMA, EMA, RSI, MACD
from modules.trade_tracker import trade_tracker
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


@server.route('/api/indicators/<symbol>/<tf>')
def api_indicators(symbol, tf):
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
            ticker = ib.get_ticker(trade['symbol'])
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
    symbols      = list({t['symbol'] for t in open_trades})
    exit_prices  = {}
    for sym in symbols:
        ticker = ib.get_ticker(sym)
        if ticker:
            p = ticker.get('price') or ticker.get('last')
            if p:
                exit_prices[sym] = p
    closed = trade_tracker.close_all_open(exit_prices)
    return jsonify({'ok': True, 'closed': len(closed), 'trades': closed})


# ================================================================
app_state = {'current_symbol': 'AAPL', 'current_timeframe': '5 mins'}

# ========== LAYOUT ==========

app.layout = html.Div([
    html.Div([
        html.H1("🚀 IB Trading Platform v3.0",
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

    # Symbol + cena
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
                html.Button('📥 Stáhnout historii', id='deep-load-btn', n_clicks=0,
                            style={'marginLeft': '20px', 'padding': '8px 15px',
                                   'background': '#ff9800', 'color': 'black',
                                   'border': 'none', 'borderRadius': '5px',
                                   'cursor': 'pointer', 'fontWeight': 'bold'}),
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
            html.Button('RSI 14',  id='ind-rsi-btn',  n_clicks=1, className='ind-btn ind-active',
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
        dcc.Store(id='indicator-settings-store',
                  data={'sma': False, 'ema': True, 'rsi': True, 'macd': False}),
        dcc.Store(id='indicators-data-store'),
        dcc.Store(id='trade-refresh-store', data=0),
        # NEW: trade debug log store — Python → JS debug panel
        dcc.Store(id='trade-debug-store', data=None),

    ], style={'padding': '20px', 'background': '#2d2d3a',
              'borderRadius': '8px', 'marginBottom': '20px'}),

    # ================================================================
    # ORDER ENTRY – v3.0
    # ================================================================
    html.Div([
        html.H3('📥 Order Entry', style={'marginBottom': '15px'}),

        # Řádek 1: Qty
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

        # Řádek 2: Risk management (SL / TP)
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

        # Řádek 3: Preview
        html.Div(id='order-preview',
                 style={'marginBottom': '14px', 'padding': '8px 14px',
                        'background': '#0d1a2e', 'borderRadius': '6px',
                        'fontSize': '13px', 'color': '#90caf9',
                        'fontFamily': 'monospace', 'minHeight': '28px'}),

        # Řádek 4: Tlačítka
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

    # ================================================================
    # OPEN POSITIONS
    # ================================================================
    html.Div([
        html.Div([
            html.H3('📊 Open Positions',
                    style={'display': 'inline-block', 'marginBottom': '0', 'marginRight': '20px'}),
            # NEW: ruční refresh tlačítko
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

    # ================================================================
    # RECENT ORDERS (IB)
    # ================================================================
    html.Div([
        html.H3('📋 Recent Orders', style={'marginBottom': '15px'}),
        html.Div(id='orders-table')
    ], style={'padding': '20px', 'background': '#2d2d3a',
              'borderRadius': '8px', 'marginBottom': '20px'}),

    # ================================================================
    # DEBUG PANEL
    # ================================================================
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
        html.Div('[INIT] [BTN] [CB] [TF] [TICK] [API] [DATA] [IND] [TRADE] [SYNC] [ERR] | v3.0',
                 style={'marginTop': '8px', 'fontSize': '12px', 'color': '#888'})
    ], style={'padding': '20px', 'background': '#1a1a2e',
              'borderRadius': '8px', 'marginBottom': '20px',
              'border': '2px solid #ff9800'}),

    dcc.Interval(id='cache-update-interval',     interval=2000,  n_intervals=0),
    dcc.Interval(id='price-update-interval',     interval=10000, n_intervals=0),
    # CHANGED: 30000 → 10000
    dcc.Interval(id='positions-update-interval', interval=10000, n_intervals=0),
    dcc.Interval(id='connection-check-interval', interval=10000, n_intervals=0),
    dcc.Interval(id='trades-refresh-interval',   interval=5000,  n_intervals=0),
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
    trigger_refresh  = dash.no_update
    if current_dl_state == 'done':
        new_dl_trigger = f"{sym}_{tf}_done_{time.time()}"
        if not str(last_dl_state).startswith(f"{sym}_{tf}_done"):
            trigger_refresh = new_dl_trigger
            last_dl_state   = new_dl_trigger
    elif current_dl_state == 'running':
        last_dl_state = 'running'
    if current_dl_state == 'running':
        return html.Span(
            f"⏳ Stahuji historii: {dl_status.get('progress', '0%')} ({dl_status.get('msg', '')})",
            style={'color': '#ff9800'}
        ), trigger_refresh
    status = data_store.get_cache_status(sym, tf)
    if not status['cached']:
        return html.Span('Cache: Prázdná', style={'color': '#888', 'background': '#333'}), trigger_refresh
    bars_str = f"{status['total_bars']:,}".replace(',', ' ')
    age = status['age_seconds']
    if age < 60:      age_str = f"{int(age)}s"
    elif age < 3600:  age_str = f"{int(age//60)}m"
    elif age < 86400: age_str = f"{int(age//3600)}h"
    else:             age_str = f"{int(age//86400)}d"
    if status['is_fresh']:
        return html.Span(f"💾 Parquet: {bars_str} barů | Aktuální",
                         style={'color': '#4caf50', 'background': '#1b5e20'}), trigger_refresh
    return html.Span(f"💾 Parquet: {bars_str} barů | {age_str} staré",
                     style={'color': '#ffeb3b', 'background': '#e65100'}), trigger_refresh


# ------------------------------------------------------------------
# ORDER ENTRY: live preview (clientside)
# ------------------------------------------------------------------
app.clientside_callback(
    """
    function(qty, slPrice, slPct, tpPrice, tpPct, symbol, priceTxt) {
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

        var parts = ['📋 ' + q + '× ' + sym + ' @ Market'];
        if (sl) parts.push('🛡️ SL $' + sl.toFixed(2));
        if (tp) parts.push('🎯 TP $' + tp.toFixed(2));
        if (cur > 0 && sl) {
            var risk = Math.round(Math.abs(cur - sl) * q * 100) / 100;
            parts.push('Risk: $' + risk);
        }
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
     Input('price-display', 'children')]
)


# ------------------------------------------------------------------
# PLACE ORDER – BUY / SELL + TradeTracker + [TRADE] debug log
# ------------------------------------------------------------------
@app.callback(
    [Output('order-feedback', 'children'),
     Output('trade-refresh-store', 'data'),
     Output('trade-debug-store', 'data')],
    [Input('buy-btn', 'n_clicks'), Input('sell-btn', 'n_clicks')],
    [State('symbol-input',    'value'),
     State('qty-custom',      'value'),
     State('sl-price-input',  'value'),
     State('sl-pct-input',    'value'),
     State('tp-price-input',  'value'),
     State('tp-pct-input',    'value'),
     State('order-note-input','value'),
     State('trade-refresh-store', 'data')]
)
def place_order(buy_clicks, sell_clicks, symbol, quantity,
                sl_price, sl_pct, tp_price, tp_pct, note, refresh_counter):
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

    if not ib.is_connected():
        dbg = {'msg': f'[TRADE][ERR] {action} {symbol} — NOT CONNECTED', 'ts': time.time()}
        return html.Div('❌ Not connected!',
                        style={'color': '#ef5350', 'fontWeight': 'bold'}), dash.no_update, dbg

    ticker    = ib.get_ticker(symbol) or {}
    cur_price = ticker.get('price') or ticker.get('last') or 0

    sl = None
    if sl_price:
        sl = float(sl_price)
    elif sl_pct and cur_price:
        mult = (1 - float(sl_pct) / 100) if action == 'BUY' else (1 + float(sl_pct) / 100)
        sl   = round(cur_price * mult, 2)

    tp = None
    if tp_price:
        tp = float(tp_price)
    elif tp_pct and cur_price:
        mult = (1 + float(tp_pct) / 100) if action == 'BUY' else (1 - float(tp_pct) / 100)
        tp   = round(cur_price * mult, 2)

    result = ib.place_market_order(symbol, action, quantity)
    if not result['success']:
        dbg = {'msg': f'[TRADE][ERR] {action} {quantity} {symbol} — {result["error"]}', 'ts': time.time()}
        return html.Div(f'❌ {result["error"]}',
                        style={'color': '#ef5350', 'fontWeight': 'bold'}), dash.no_update, dbg

    fill_price = result.get('fill_price') or cur_price
    trade_tracker.open_trade(
        symbol=symbol, side=action, qty=quantity,
        entry_price=fill_price,
        sl=sl, tp=tp,
        note=note or ''
    )

    sl_txt  = f' | SL ${sl:.2f}' if sl else ''
    tp_txt  = f' | TP ${tp:.2f}' if tp else ''
    dbg_msg = (f'[TRADE] {action} {quantity}x {symbol} @ Market'
               f' | fill=${fill_price:.2f}{sl_txt}{tp_txt}'
               f'{" | note: " + note if note else ""}')
    dbg = {'msg': dbg_msg, 'ts': time.time()}

    return (
        html.Div(f'✅ {action} {quantity} {symbol} @ Market{sl_txt}{tp_txt}',
                 style={'color': color, 'fontWeight': 'bold'}),
        (refresh_counter or 0) + 1,
        dbg
    )


# ------------------------------------------------------------------
# CLOSE ALL POSITIONS — bez self-HTTP, přímé volání TradeTracker
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
    if not ib.is_connected():
        dbg = {'msg': '[TRADE][ERR] CLOSE ALL — NOT CONNECTED', 'ts': time.time()}
        return '❌ Not connected', dash.no_update, dbg

    positions = ib.get_positions() or []
    errors    = []
    closed    = 0

    for pos in positions:
        qty = abs(pos['position'])
        if qty <= 0:
            continue
        action = 'SELL' if pos['position'] > 0 else 'BUY'
        res = ib.place_market_order(pos['symbol'], action, qty)
        if res['success']:
            closed += 1
        else:
            errors.append(pos['symbol'])

    # Zavři v TradeTracker přímo (bez HTTP self-call)
    exit_prices = {}
    for pos in positions:
        sym    = pos['symbol']
        ticker = ib.get_ticker(sym) or {}
        p      = ticker.get('price') or ticker.get('last')
        if p:
            exit_prices[sym] = p
    trade_tracker.close_all_open(exit_prices)

    err_txt = f' | chyba u: {", ".join(errors)}' if errors else ''
    dbg_msg = (f'[TRADE] CLOSE ALL → {closed}/{len(positions)} pozic zavřeno'
               f'{" | ERR: " + ", ".join(errors) if errors else " | OK"}')
    dbg = {'msg': dbg_msg, 'ts': time.time()}

    if errors:
        return f'⚠️ Zavřeno {closed}, chyba: {", ".join(errors)}', (refresh_counter or 0) + 1, dbg
    return f'✅ Zavřeno {closed} pozic', (refresh_counter or 0) + 1, dbg


# ------------------------------------------------------------------
# OPEN POSITIONS TABLE + orphan sync
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
    if not ib.is_connected():
        return html.Div('Not connected', style={'color': '#888'}), dash.no_update

    positions   = ib.get_positions() or []
    open_trades = {t['symbol']: t for t in trade_tracker.get_open_trades()}

    # --- ORPHAN SYNC: TradeTracker má "open", ale IB pozici nezná ---
    ib_symbols  = {p['symbol'] for p in positions}
    sync_msgs   = []
    for sym, tt in list(open_trades.items()):
        if sym not in ib_symbols:
            ticker = ib.get_ticker(sym) or {}
            exit_p = ticker.get('price') or ticker.get('last') or tt.get('entry_price', 0)
            trade_tracker.close_trade(tt['id'], exit_p)
            del open_trades[sym]
            sync_msgs.append(f'[SYNC] Orphan {sym} auto-closed @ ${exit_p:.2f} (IB pos=0)')
            print(f"[SYNC] Orphan trade {sym} closed in TradeTracker")

    dbg = dash.no_update
    if sync_msgs:
        dbg = {'msg': '\n'.join(sync_msgs), 'ts': time.time(), 'multi': True}

    if not positions:
        return html.Div('Žádné otevřené pozice', style={'color': '#888'}), dbg

    rows = []
    for pos in positions:
        pnl_c = '#26a69a' if pos['unrealized_pnl'] >= 0 else '#ef5350'
        sym   = pos['symbol']
        tt    = open_trades.get(sym, {})
        entry_t  = trade_tracker.fmt_time(tt.get('entry_time')) if tt else '–'
        sl_txt   = f"${tt['sl']:.2f}"  if tt.get('sl')  else '–'
        tp_txt   = f"${tt['tp']:.2f}"  if tt.get('tp')  else '–'
        trade_id = tt.get('id', '')
        rows.append(html.Tr([
            html.Td(sym, style={'fontWeight': 'bold'}),
            html.Td('LONG' if pos['position'] > 0 else 'SHORT',
                    style={'color': '#00d4ff'}),
            html.Td(abs(pos['position'])),
            html.Td(f"${pos['avg_cost']:.2f}"),
            html.Td(f"${pos['market_value']:.2f}"),
            html.Td(f"${pos['unrealized_pnl']:.2f} ({pos['unrealized_pnl_pct']:.2f}%)",
                    style={'color': pnl_c, 'fontWeight': 'bold'}),
            html.Td(entry_t, style={'color': '#aaa', 'fontSize': '12px'}),
            html.Td(sl_txt,  style={'color': '#ef9a9a', 'fontSize': '12px'}),
            html.Td(tp_txt,  style={'color': '#a5d6a7', 'fontSize': '12px'}),
            html.Td(
                html.Button('✖ Close', id={'type': 'close-pos-btn', 'trade_id': trade_id},
                            n_clicks=0,
                            style={'padding': '4px 10px', 'background': '#b71c1c',
                                   'border': 'none', 'borderRadius': '4px',
                                   'color': 'white', 'cursor': 'pointer',
                                   'fontSize': '12px'})
                if trade_id else html.Span('–', style={'color': '#555'})
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
     Output('trade-debug-store', 'data', allow_duplicate=True)],
    Input({'type': 'close-pos-btn', 'trade_id': dash.ALL}, 'n_clicks'),
    prevent_initial_call=True
)
def close_single_position(n_clicks_list):
    ctx = dash.callback_context
    if not ctx.triggered:
        return dash.no_update, dash.no_update
    triggered = ctx.triggered[0]
    if not triggered['value']:
        return dash.no_update, dash.no_update

    import json as _json
    prop_id  = triggered['prop_id']
    id_part  = prop_id.split('.')[0]
    trade_id = _json.loads(id_part).get('trade_id', '')
    if not trade_id:
        return dash.no_update, dash.no_update

    trade = trade_tracker.get_trade(trade_id)
    if not trade:
        dbg = {'msg': f'[TRADE][ERR] Close single — trade {trade_id} nenalezen', 'ts': time.time()}
        return html.Div('❌ Trade nenalezen', style={'color': '#ef5350'}), dbg

    sym = trade['symbol']
    qty = trade['qty']
    act = 'SELL' if trade['side'] == 'BUY' else 'BUY'

    if not ib.is_connected():
        dbg = {'msg': f'[TRADE][ERR] Close {sym} — NOT CONNECTED', 'ts': time.time()}
        return html.Div('❌ Not connected', style={'color': '#ef5350'}), dbg

    res        = ib.place_market_order(sym, act, qty)
    ticker     = ib.get_ticker(sym) or {}
    exit_price = ticker.get('price') or ticker.get('last') or trade.get('entry_price', 0)
    trade_tracker.close_trade(trade_id, exit_price)

    updated = trade_tracker.get_trade(trade_id)
    pnl     = updated.get('pnl') if updated else None
    pnl_txt = f" | P&L: {'+'if (pnl or 0)>=0 else ''}${pnl:.2f}" if pnl is not None else ''

    color   = '#26a69a' if res['success'] else '#ef5350'
    msg_ui  = f"✅ Closed {sym} {qty}x{pnl_txt}" if res['success'] else f"❌ {res['error']}"
    dbg_msg = (f'[TRADE] CLOSE {sym} {qty}x @ ${exit_price:.2f}{pnl_txt}'
               f' | IB: {"OK" if res["success"] else "ERR " + str(res.get("error",""))}')
    dbg = {'msg': dbg_msg, 'ts': time.time()}

    return html.Div(msg_ui, style={'color': color, 'fontWeight': 'bold'}), dbg


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
        pnl_s  = f"{'+'if (pnl or 0)>=0 else ''}${pnl:.2f}" if pnl is not None else '–'
        sl_txt = f"${t['sl']:.2f}"  if t.get('sl')  else '–'
        tp_txt = f"${t['tp']:.2f}"  if t.get('tp')  else '–'
        rows.append(html.Tr([
            html.Td(str(i),  style={'color': '#555', 'fontSize': '12px'}),
            html.Td(t['symbol'], style={'fontWeight': 'bold'}),
            html.Td(t['side'],   style={'color': '#00d4ff'}),
            html.Td(t['qty']),
            html.Td(f"${t['entry_price']:.2f}" if t.get('entry_price') else '–'),
            html.Td(trade_tracker.fmt_time(t.get('entry_time')),
                    style={'color': '#aaa', 'fontSize': '12px'}),
            html.Td(f"${t['exit_price']:.2f}" if t.get('exit_price') else '–'),
            html.Td(trade_tracker.fmt_time(t.get('exit_time')),
                    style={'color': '#aaa', 'fontSize': '12px'}),
            html.Td(sl_txt, style={'color': '#ef9a9a', 'fontSize': '12px'}),
            html.Td(tp_txt, style={'color': '#a5d6a7', 'fontSize': '12px'}),
            html.Td(t.get('note', ''), style={'color': '#888', 'fontSize': '12px'}),
            html.Td(pnl_s, style={'color': pnl_c, 'fontWeight': 'bold'}),
        ]))

    return html.Table([
        html.Thead(html.Tr([
            html.Th('#'), html.Th('Symbol'), html.Th('Side'), html.Th('Qty'),
            html.Th('Entry $'), html.Th('Vstup'),
            html.Th('Exit $'),  html.Th('Výstup'),
            html.Th('SL'), html.Th('TP'), html.Th('Poznámka'), html.Th('P&L')
        ])),
        html.Tbody(rows)
    ], style={'width': '100%', 'borderCollapse': 'collapse'})


# ------------------------------------------------------------------
# ORDERS TABLE (IB)
# ------------------------------------------------------------------
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
    icons  = {'Filled': '✅', 'Submitted': '⏳', 'Cancelled': '❌', 'PendingSubmit': '🕒'}
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
        // Podpora multi-line zprav (orphan sync)
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
    Output('load-click-log', 'data'), Input('load-chart-btn', 'n_clicks')
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
        var url = '/api/indicators/' + sym + '/' + tf + '?active=' + active.join(',');
        d('IND', 'Fetching: ' + url);
        fetch(url).then(function(r){return r.json();}).then(function(data){
            if (!data.ok){d('ERR','IND FAIL: '+(data.error||'unknown'));return;}
            d('IND','OK: '+active.join(',')+' | bars='+data.bars);
            if (window.lwcManager && window.lwcManager.setIndicators)
                window.lwcManager.setIndicators(data);
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
    function(n) {
        if (n < 1) return n;
        var d = window.lwcDebug || function() {};
        var sym = (document.getElementById('symbol-input')&&document.getElementById('symbol-input').value||'AAPL').toUpperCase();
        d('API','=== TICK DIAG: '+sym+' ===');
        fetch('/api/diag/tick/'+sym).then(function(r){return r.json();}).then(function(j){
            d('API','connected='+j.tick_sub_connected+'  iter='+j.iterations+'  mdt='+j.mdt+'  mode='+j.mode);
            d('API','subscribed='+JSON.stringify(j.subscribed_symbols));
            var lx=j.latest;
            d('API','LATEST: price='+(lx.price||0)+'  last='+(lx.last||0)+'  close='+(lx.close||0)+'  bid='+(lx.bid||0)+'  ask='+(lx.ask||0));
            var rf=j.raw_fields;
            if(rf.error)d('ERR','RAW: '+rf.error);
            else d('API','RAW: last='+rf.last+'  close='+rf.close+'  bid='+rf.bid+'  ask='+rf.ask);
            if(j.ib_errors&&j.ib_errors.length>0){d('ERR','=== IB ERRORY ('+j.ib_errors.length+') ===');j.ib_errors.forEach(function(e){d('ERR','IB: '+e);});}
            else d('API','IB errory: zadne');
        }).catch(function(e){d('ERR','TICK DIAG FAIL: '+e);});
        return n;
    }
    """,
    Output('diag-tick-trigger', 'data'), Input('diag-tick-btn', 'n_clicks')
)

app.clientside_callback(
    """
    function(n) {
        if (n < 1) return n;
        var d = window.lwcDebug || function() {};
        var sym = (document.getElementById('symbol-input')&&document.getElementById('symbol-input').value||'AAPL').toUpperCase();
        d('API','=== SNAPSHOT TEST: '+sym+' (ceka ~3s...) ===');
        fetch('/api/test/snapshot/'+sym).then(function(r){return r.json();}).then(function(j){
            if(j.ok)d('API','SNAP OK: last='+j.last+'  close='+j.close+'  bid='+j.bid+'  ask='+j.ask+'  vol='+j.volume+'  conId='+j.conId);
            else d('ERR','SNAP FAIL: '+j.error);
            if(j.errors&&j.errors.length>0)d('ERR','Snapshot IB errory: '+JSON.stringify(j.errors));
        }).catch(function(e){d('ERR','SNAP TEST FAIL: '+e);});
        return n;
    }
    """,
    Output('diag-snap-trigger', 'data'), Input('diag-snap-btn', 'n_clicks')
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
    """function(n){if(n<1)return n;var d=window.lwcDebug||function(){};d('API','=== TEST 1: IB spojeni ===');fetch('/api/diag').then(r=>r.json()).then(j=>{d('API','connected='+j.connected+' account='+j.account_id);d('API','tick_sub: connected='+j.tick_sub.connected+' iter='+j.tick_sub.iterations+' mdt='+j.tick_sub.mdt+' mode='+j.tick_sub.mode);if(j.tick_sub.ib_errors&&j.tick_sub.ib_errors.length>0){d('ERR','IB errory: '+JSON.stringify(j.tick_sub.ib_errors));}}).catch(e=>d('ERR','FAIL: '+e));return n;}""",
    Output('diag1-trigger','data'), Input('diag1-btn','n_clicks')
)
app.clientside_callback(
    """function(n){if(n<1)return n;var d=window.lwcDebug||function(){};d('API','TEST 2: Hist. data...');fetch('/api/test-hist/AAPL').then(r=>r.json()).then(j=>{if(j.ok)d('API','OK: '+j.bars+' baru za '+j.elapsed+'s');else d('ERR','FAIL: '+j.error);}).catch(e=>d('ERR','FAIL: '+e));return n;}""",
    Output('diag2-trigger','data'), Input('diag2-btn','n_clicks')
)
app.clientside_callback(
    """function(n){if(n<1)return n;var d=window.lwcDebug||function(){};d('API','TEST 3: Fetch+nakreslit...');fetch('/api/test-hist/AAPL').then(r=>r.json()).then(j=>{if(!j.ok){d('ERR','Fail: '+j.error);return;}d('API','OK: '+j.bars+' baru');if(window.lwcManager)window.lwcManager.testChart();}).catch(e=>d('ERR','FAIL: '+e));return n;}""",
    Output('diag3-trigger','data'), Input('diag3-btn','n_clicks')
)
app.clientside_callback(
    """function(n){if(n>0&&window.lwcManager)window.lwcManager.testChart();return n;}""",
    Output('test-chart-trigger','data'), Input('test-chart-btn','n_clicks')
)
app.clientside_callback(
    """function(n){if(n>0){var a=document.getElementById('debug-log-area');if(a){a.select();try{document.execCommand('copy');}catch(e){}a.setSelectionRange(0,0);navigator.clipboard&&navigator.clipboard.writeText(a.value);}}return n>0?'Zkopírováno ✓':'';}""",
    Output('copy-status','children'), Input('copy-log-btn','n_clicks')
)
app.clientside_callback(
    """function(n){if(n>0){var a=document.getElementById('debug-log-area');if(a)a.value='';}return n;}""",
    Output('clear-log-trigger','data'), Input('clear-log-btn','n_clicks')
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
            {%renderer%}
        </footer>
    </body>
</html>
'''


# ========== RUN ==========

if __name__ == '__main__':
    print("🚀 Starting IB Trading Platform v3.0.0...")
    print(f"Connecting to {config.IB_HOST}:{config.IB_PORT}")
    if ib.connect():
        print("✅ Connected to IB Gateway!")
    else:
        print("❌ Failed to connect")
    print("http://localhost:8050  |  Ctrl+C to stop\n")
    app.run_server(debug=True, use_reloader=False, host='0.0.0.0', port=8050)

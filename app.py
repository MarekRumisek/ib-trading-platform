"""IB Trading Platform - Main Dash Application with Lightweight Charts

Version: 2.0.7 - Kompletni diagnostika
  - Flask API /api/diag, /api/test-hist, /api/cb-status
  - 3 diagnosticka tlacitka v debug panelu (bypass Dash)
  - Globalni _cb_status tracker pro sledovani stavu callbacku
  - Intervaly zpomaleny (10s/30s) aby neblokovalyDash queue
"""

import dash
from dash import dcc, html, Input, Output, State
from datetime import datetime
from flask import jsonify
from ib_connector import IBConnector
import config
import time
import threading

app = dash.Dash(
    __name__,
    title="IB Trading Platform",
    update_title=None,
    suppress_callback_exceptions=True,
    serve_locally=True
)

ib = IBConnector()
server = app.server

# ================================================================
# GLOBALNI STATUS TRACKER - sleduje stav Python callbacku
# aktualizuje se behem load_chart_data
# citelny pres /api/cb-status (nezavisle na Dash)
# ================================================================
_cb_status = {
    'step': 'idle',
    'symbol': None,
    'tf': None,
    'bars': None,
    'error': None,
    'ts': None,
}


# ================================================================
# FLASK API ENDPOINTY - testovatelne primo z prohlizece / JS
# ================================================================

@server.route('/api/tick/<symbol>')
def get_tick(symbol):
    ticker = ib.get_ticker(symbol.upper())
    if not ticker:
        return jsonify({'error': 'no data'}), 404
    price = ticker['last'] if ticker['last'] > 0 else ticker['close']
    return jsonify({'time': int(datetime.now().timestamp()), 'price': price})


@server.route('/api/diag')
def api_diag():
    """Diagnostika pripojeni - volej z JS nebo prohlizece."""
    return jsonify({
        'connected': ib.is_connected(),
        'account_id': ib.account_id,
        'cached_contracts': list(ib.contracts.keys()),
        'cached_tickers': len(ib.tickers),
        'cb_status': _cb_status,
        'time': datetime.now().strftime('%H:%M:%S')
    })


@server.route('/api/test-hist/<symbol>')
def api_test_hist(symbol):
    """Primo testuje get_historical_data() - bypass Dash callbacku."""
    t0 = time.time()
    try:
        if not ib.is_connected():
            return jsonify({'ok': False, 'error': 'NOT CONNECTED',
                            'elapsed': 0})
        bars = ib.get_historical_data(symbol.upper(), '1 D', '5 mins')
        elapsed = round(time.time() - t0, 2)
        if bars:
            return jsonify({
                'ok': True,
                'bars': len(bars),
                'elapsed': elapsed,
                'first': bars[0],
                'last': bars[-1]
            })
        return jsonify({'ok': False, 'error': 'EMPTY - 0 bars',
                        'elapsed': elapsed})
    except Exception as e:
        elapsed = round(time.time() - t0, 2)
        return jsonify({'ok': False, 'error': str(e), 'elapsed': elapsed})


@server.route('/api/cb-status')
def api_cb_status():
    """Vraci aktualni stav load_chart_data callbacku."""
    return jsonify(_cb_status)


# ================================================================

app_state = {
    'current_symbol': 'AAPL',
    'current_timeframe': '5 mins',
}

# ========== LAYOUT ==========

app.layout = html.Div([
    # Header
    html.Div([
        html.H1("\U0001f680 IB Trading Platform v2.0",
                style={'display': 'inline-block', 'margin': 0, 'color': '#00d4ff'}),
        html.Div(id='connection-status',
                 style={'display': 'inline-block', 'float': 'right', 'fontSize': 18})
    ], style={
        'padding': '20px',
        'background': 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
        'borderRadius': '10px', 'marginBottom': '20px'
    }),

    # Account bar
    html.Div([
        html.Div([
            html.Span("\U0001f4bc Account: ", style={'fontWeight': 'bold'}),
            html.Span(id='account-id', children='Connecting...')
        ], style={'display': 'inline-block', 'marginRight': '30px'}),
        html.Div([
            html.Span("\U0001f4b0 Balance: ", style={'fontWeight': 'bold'}),
            html.Span(id='account-balance', children='$0.00')
        ], style={'display': 'inline-block', 'marginRight': '30px'}),
        html.Div([
            html.Span("\U0001f4c8 Buying Power: ", style={'fontWeight': 'bold'}),
            html.Span(id='buying-power', children='$0.00')
        ], style={'display': 'inline-block'})
    ], style={
        'padding': '15px', 'background': '#2d2d3a',
        'borderRadius': '8px', 'marginBottom': '20px', 'fontSize': '16px'
    }),

    # Symbol + price bar
    html.Div([
        html.Div([
            html.Label('Symbol:', style={'marginRight': '10px', 'fontWeight': 'bold'}),
            dcc.Input(
                id='symbol-input', type='text', value='AAPL',
                style={
                    'width': '150px', 'padding': '8px', 'borderRadius': '5px',
                    'border': '2px solid #667eea', 'background': '#1e1e2e',
                    'color': 'white', 'fontSize': '16px'
                }
            ),
            html.Button(
                'Load Chart', id='load-chart-btn', n_clicks=0,
                style={
                    'marginLeft': '10px', 'padding': '8px 20px',
                    'background': 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
                    'border': 'none', 'borderRadius': '5px',
                    'color': 'white', 'cursor': 'pointer', 'fontWeight': 'bold'
                }
            )
        ], style={'display': 'inline-block', 'marginRight': '30px'}),
        html.Div([
            html.Span(id='price-display', children='Last: $0.00',
                      style={'fontSize': '20px', 'fontWeight': 'bold'}),
            html.Span(id='price-change-display', children=' \u25b2 +$0.00 (+0.00%)',
                      style={'fontSize': '16px', 'marginLeft': '15px', 'color': '#26a69a'})
        ], style={'display': 'inline-block'})
    ], style={
        'padding': '15px', 'background': '#2d2d3a',
        'borderRadius': '8px', 'marginBottom': '20px'
    }),

    # Chart panel
    html.Div([
        html.Div([
            html.Button('1m',  id='tf-1m',  n_clicks=0, className='tf-btn'),
            html.Button('5m',  id='tf-5m',  n_clicks=0, className='tf-btn tf-active'),
            html.Button('15m', id='tf-15m', n_clicks=0, className='tf-btn'),
            html.Button('30m', id='tf-30m', n_clicks=0, className='tf-btn'),
            html.Button('1h',  id='tf-1h',  n_clicks=0, className='tf-btn'),
            html.Button('1D',  id='tf-1d',  n_clicks=0, className='tf-btn'),
        ], style={'marginBottom': '10px'}),

        html.Div(
            id='lwc-container',
            style={'width': '100%', 'height': '500px', 'position': 'relative',
                   'background': '#1e1e2e'}
        ),

        dcc.Store(id='chart-data-store'),
        dcc.Store(id='chart-trigger-store'),
        dcc.Store(id='test-chart-trigger'),
        dcc.Store(id='clear-log-trigger'),
        dcc.Store(id='copy-log-trigger'),
        dcc.Store(id='load-click-log'),
        dcc.Store(id='diag1-trigger'),
        dcc.Store(id='diag2-trigger'),
        dcc.Store(id='diag3-trigger'),

    ], style={
        'padding': '20px', 'background': '#2d2d3a',
        'borderRadius': '8px', 'marginBottom': '20px'
    }),

    # Order panel
    html.Div([
        html.H3('\U0001f4e4 Order Entry', style={'marginBottom': '15px'}),
        html.Div([
            html.Label('Quantity:', style={'marginRight': '10px', 'fontWeight': 'bold'}),
            html.Button('1',   id='qty-1',   n_clicks=0, className='qty-btn'),
            html.Button('5',   id='qty-5',   n_clicks=0, className='qty-btn'),
            html.Button('10',  id='qty-10',  n_clicks=0, className='qty-btn'),
            html.Button('25',  id='qty-25',  n_clicks=0, className='qty-btn'),
            html.Button('100', id='qty-100', n_clicks=0, className='qty-btn'),
            dcc.Input(
                id='qty-custom', type='number', value=1, min=1,
                style={
                    'width': '80px', 'marginLeft': '10px', 'padding': '8px',
                    'borderRadius': '5px', 'border': '2px solid #667eea',
                    'background': '#1e1e2e', 'color': 'white'
                }
            )
        ], style={'marginBottom': '15px'}),
        html.Div([
            html.Button(
                '\U0001f7e2 BUY MARKET', id='buy-btn', n_clicks=0,
                style={
                    'padding': '15px 40px',
                    'background': 'linear-gradient(135deg, #26a69a 0%, #1a7f6f 100%)',
                    'border': 'none', 'borderRadius': '8px', 'color': 'white',
                    'fontSize': '18px', 'fontWeight': 'bold',
                    'cursor': 'pointer', 'marginRight': '15px'
                }
            ),
            html.Button(
                '\U0001f534 SELL MARKET', id='sell-btn', n_clicks=0,
                style={
                    'padding': '15px 40px',
                    'background': 'linear-gradient(135deg, #ef5350 0%, #c62828 100%)',
                    'border': 'none', 'borderRadius': '8px', 'color': 'white',
                    'fontSize': '18px', 'fontWeight': 'bold', 'cursor': 'pointer'
                }
            )
        ]),
        html.Div(id='order-feedback', style={'marginTop': '15px', 'fontSize': '16px'})
    ], style={
        'padding': '20px', 'background': '#2d2d3a',
        'borderRadius': '8px', 'marginBottom': '20px'
    }),

    # Positions
    html.Div([
        html.H3('\U0001f4ca Open Positions (Real-time P&L)', style={'marginBottom': '15px'}),
        html.Div(id='positions-table')
    ], style={
        'padding': '20px', 'background': '#2d2d3a',
        'borderRadius': '8px', 'marginBottom': '20px'
    }),

    # Orders
    html.Div([
        html.H3('\U0001f4cb Recent Orders', style={'marginBottom': '15px'}),
        html.Div(id='orders-table')
    ], style={
        'padding': '20px', 'background': '#2d2d3a',
        'borderRadius': '8px', 'marginBottom': '20px'
    }),

    # ================================================================
    # DEBUG PANEL
    # ================================================================
    html.Div([
        html.H3('\U0001f527 Debug Panel',
                style={'marginBottom': '10px', 'color': '#ff9800'}),

        # Python callback status
        html.Div([
            html.Span('Python callback: ',
                      style={'fontWeight': 'bold', 'color': '#00d4ff'}),
            html.Span(id='debug-python-info',
                      children='(ceka na Load Chart...)',
                      style={'fontFamily': 'monospace', 'fontSize': '13px'})
        ], style={'marginBottom': '12px', 'padding': '8px',
                  'background': '#0d0d1a', 'borderRadius': '5px'}),

        # ---- DIAGNOSTICKA TLACITKA (bypass Dash, volaji Flask API primo) ----
        html.Div([
            html.Div('\U0001f9ea Diagnostika (nezavisla na Dash callbacks):',
                     style={'color': '#ff9800', 'fontWeight': 'bold',
                            'marginBottom': '8px', 'fontSize': '13px'}),
            html.Button(
                '1\ufe0f\u20e3 Test: IB Spojeni',
                id='diag1-btn', n_clicks=0,
                style={
                    'padding': '10px 16px', 'marginRight': '8px',
                    'background': '#1565c0', 'border': 'none',
                    'borderRadius': '5px', 'color': 'white',
                    'cursor': 'pointer', 'fontWeight': 'bold', 'fontSize': '13px'
                }
            ),
            html.Button(
                '2\ufe0f\u20e3 Test: Historicka data AAPL',
                id='diag2-btn', n_clicks=0,
                style={
                    'padding': '10px 16px', 'marginRight': '8px',
                    'background': '#6a1599', 'border': 'none',
                    'borderRadius': '5px', 'color': 'white',
                    'cursor': 'pointer', 'fontWeight': 'bold', 'fontSize': '13px'
                }
            ),
            html.Button(
                '3\ufe0f\u20e3 Nakreslit z API (bypass Dash)',
                id='diag3-btn', n_clicks=0,
                style={
                    'padding': '10px 16px', 'marginRight': '8px',
                    'background': '#1b5e20', 'border': 'none',
                    'borderRadius': '5px', 'color': 'white',
                    'cursor': 'pointer', 'fontWeight': 'bold', 'fontSize': '13px'
                }
            ),
        ], style={'marginBottom': '12px', 'padding': '10px',
                  'background': '#0d1a2e', 'borderRadius': '5px',
                  'border': '1px solid #1565c0'}),

        # ---- NORMALNI TLACITKA ----
        html.Div([
            html.Button(
                '\U0001f9ea Test Chart (fake)',
                id='test-chart-btn', n_clicks=0,
                style={
                    'padding': '10px 20px', 'marginRight': '10px',
                    'background': '#ff9800', 'border': 'none',
                    'borderRadius': '5px', 'color': 'black',
                    'cursor': 'pointer', 'fontWeight': 'bold', 'fontSize': '14px'
                }
            ),
            html.Button(
                '\U0001f4cb Zkopirovat log',
                id='copy-log-btn', n_clicks=0,
                style={
                    'padding': '10px 20px', 'marginRight': '10px',
                    'background': '#26a69a', 'border': 'none',
                    'borderRadius': '5px', 'color': 'white',
                    'cursor': 'pointer', 'fontWeight': 'bold', 'fontSize': '14px'
                }
            ),
            html.Button(
                '\U0001f5d1 Smazat log',
                id='clear-log-btn', n_clicks=0,
                style={
                    'padding': '10px 20px',
                    'background': '#555', 'border': 'none',
                    'borderRadius': '5px', 'color': 'white',
                    'cursor': 'pointer', 'fontSize': '14px'
                }
            ),
            html.Span(id='copy-status', style={
                'marginLeft': '10px', 'color': '#26a69a',
                'fontSize': '13px', 'fontStyle': 'italic'
            })
        ], style={'marginBottom': '10px'}),

        html.Textarea(
            id='debug-log-area',
            rows=22,
            placeholder='Sem JS pise vsechny kroky...\nOtevri stranku a uvidis co se deje.',
            style={
                'width': '100%', 'boxSizing': 'border-box',
                'background': '#0d0d0d', 'color': '#00ff00',
                'fontFamily': 'monospace', 'fontSize': '12px',
                'border': '1px solid #333', 'borderRadius': '5px',
                'padding': '10px', 'resize': 'vertical'
            }
        ),
        html.Div(
            '\u2139\ufe0f [INIT]=LWC | [BTN]=klik | [CB]=Dash callback | '
            '[API]=Flask test | [DATA]=data | [ERR]=chyba',
            style={'marginTop': '8px', 'fontSize': '12px',
                   'color': '#888', 'fontStyle': 'italic'}
        )
    ], style={
        'padding': '20px', 'background': '#1a1a2e',
        'borderRadius': '8px', 'marginBottom': '20px',
        'border': '2px solid #ff9800'
    }),

    # Intervaly zpomalene: price 10s, positions 30s, conn 10s
    # aby neblokovalyDash callback queue behem debugovani
    dcc.Interval(id='price-update-interval',     interval=10000, n_intervals=0),
    dcc.Interval(id='positions-update-interval', interval=30000, n_intervals=0),
    dcc.Interval(id='connection-check-interval', interval=10000, n_intervals=0),
    html.Div(id='hidden-state', style={'display': 'none'})

], style={
    'maxWidth': '1400px', 'margin': '0 auto', 'padding': '20px',
    'background': '#1e1e2e', 'minHeight': '100vh',
    'color': 'white', 'fontFamily': 'Arial, sans-serif'
})


# ========== CALLBACKS ==========

@app.callback(
    Output('connection-status', 'children'),
    Input('connection-check-interval', 'n_intervals')
)
def update_connection_status(n):
    if ib.is_connected():
        return html.Span([
            html.Span('\u26ac', style={'color': '#26a69a', 'marginRight': '5px'}),
            html.Span('Connected to IB Gateway')
        ])
    return html.Span([
        html.Span('\u26ac', style={'color': '#ef5350', 'marginRight': '5px'}),
        html.Span('Disconnected')
    ])


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
    return (
        d.get('account_id', 'N/A'),
        f"${d.get('net_liquidation', 0):,.2f}",
        f"${d.get('buying_power', 0):,.2f}"
    )


@app.callback(
    Output('chart-data-store', 'data'),
    [Input('load-chart-btn', 'n_clicks'),
     Input('tf-1m',  'n_clicks'),
     Input('tf-5m',  'n_clicks'),
     Input('tf-15m', 'n_clicks'),
     Input('tf-30m', 'n_clicks'),
     Input('tf-1h',  'n_clicks'),
     Input('tf-1d',  'n_clicks')],
    State('symbol-input', 'value'),
    prevent_initial_call=True
)
def load_chart_data(load_clicks, tf1, tf5, tf15, tf30, tf1h, tf1d, symbol):
    global _cb_status
    try:
        ctx = dash.callback_context
        btn = ctx.triggered[0]['prop_id'].split('.')[0] if ctx.triggered else 'load-chart-btn'
        tf_map = {
            'tf-1m': '1 min', 'tf-5m': '5 mins', 'tf-15m': '15 mins',
            'tf-30m': '30 mins', 'tf-1h': '1 hour', 'tf-1d': '1 day'
        }
        app_state['current_timeframe'] = tf_map.get(btn, app_state['current_timeframe'])
        symbol = (symbol or 'AAPL').upper()
        app_state['current_symbol'] = symbol

        # --- krok 1: callback zacal ---
        _cb_status = {'step': 'started', 'symbol': symbol,
                      'tf': app_state['current_timeframe'],
                      'bars': None, 'error': None,
                      'ts': datetime.now().strftime('%H:%M:%S')}
        print(f"[CB] load_chart_data START: {symbol} {app_state['current_timeframe']}")

        # --- krok 2: volame IB ---
        _cb_status['step'] = 'requesting_IB'
        bars = ib.get_historical_data(symbol, '1 D', app_state['current_timeframe'])

        # --- krok 3: IB odpovezel ---
        _cb_status['step'] = 'IB_returned'
        _cb_status['bars'] = len(bars)
        print(f"[CB] load_chart_data IB returned {len(bars)} bars")

        result = {'symbol': symbol,
                  'timeframe': app_state['current_timeframe'],
                  'bars': bars}
        _cb_status['step'] = 'done'
        return result

    except Exception as e:
        _cb_status['step'] = 'ERROR'
        _cb_status['error'] = str(e)
        print(f"[CB] load_chart_data EXCEPTION: {e}")
        return dash.no_update


@app.callback(
    Output('debug-python-info', 'children'),
    Input('chart-data-store', 'data')
)
def update_debug_python(data):
    if not data:
        return '(prazdne)'
    bars = data.get('bars', [])
    if not bars:
        return f"\u26a0\ufe0f symbol={data.get('symbol')} | 0 BARU (IB timeout nebo trh zavreny)"
    b0 = bars[0]
    return (
        f"\u2705 {data.get('symbol')} | {data.get('timeframe')} | "
        f"{len(bars)} baru | "
        f"time[0]={b0['time']} close[0]={b0['close']} | "
        f"close[-1]={bars[-1]['close']:.2f}"
    )


# ---- Okamzity log kliknuti ----
app.clientside_callback(
    """
    function(n) {
        if (n > 0 && window.lwcDebug) {
            window.lwcDebug('BTN', 'Load Chart n=' + n +
                ' - cekam na Python/IB...');
        }
        return n;
    }
    """,
    Output('load-click-log', 'data'),
    Input('load-chart-btn', 'n_clicks')
)


# ---- Hlavni: chart-data-store -> lwcManager ----
app.clientside_callback(
    """
    function(storeData) {
        var d = window.lwcDebug || function() {};
        d('CB', '=== Dash clientside callback spusten ===');
        if (!storeData) {
            d('CB', 'storeData NULL -> no_update');
            return window.dash_clientside.no_update;
        }
        if (!storeData.bars) {
            d('CB', 'bars chybi -> no_update: ' + JSON.stringify(storeData).slice(0,100));
            return window.dash_clientside.no_update;
        }
        d('CB', 'symbol=' + storeData.symbol + ' baru=' + storeData.bars.length +
          ' time[0]=' + (storeData.bars[0] && storeData.bars[0].time) +
          ' close[0]=' + (storeData.bars[0] && storeData.bars[0].close));
        if (window.lwcManager) {
            d('CB', 'volam lwcManager.loadData()');
            window.lwcManager.loadData(storeData);
        } else {
            var a = 0;
            var r = setInterval(function() {
                a++;
                if (window.lwcManager) {
                    d('CB', 'lwcManager nalezen po ' + a + 'x');
                    window.lwcManager.loadData(storeData);
                    clearInterval(r);
                } else if (a > 20) {
                    d('ERR', 'lwcManager nenalezen!');
                    clearInterval(r);
                }
            }, 200);
        }
        return storeData.symbol || 'ok';
    }
    """,
    Output('chart-trigger-store', 'data'),
    Input('chart-data-store', 'data')
)


# ================================================================
# DIAGNOSTIKA 1 - Test IB spojeni pres /api/diag
# ================================================================
app.clientside_callback(
    """
    function(n) {
        if (n < 1) return n;
        var d = window.lwcDebug || function() {};
        d('API', '=== TEST 1: IB spojeni (/api/diag) ===');
        fetch('/api/diag')
            .then(function(r) { return r.json(); })
            .then(function(j) {
                d('API', 'connected=' + j.connected
                  + ' | account=' + j.account_id
                  + ' | contracts=' + JSON.stringify(j.cached_contracts)
                  + ' | time=' + j.time);
                d('API', 'cb_status.step=' + (j.cb_status && j.cb_status.step)
                  + ' error=' + (j.cb_status && j.cb_status.error));
                if (!j.connected) {
                    d('ERR', 'IB NENI PRIPOJENO! Zkontroluj TWS/Gateway.');
                } else {
                    d('API', 'TEST 1 OK - IB pripojeno.');
                }
            })
            .catch(function(e) {
                d('ERR', 'TEST 1 FETCH FAILED: ' + e);
            });
        return n;
    }
    """,
    Output('diag1-trigger', 'data'),
    Input('diag1-btn', 'n_clicks')
)


# ================================================================
# DIAGNOSTIKA 2 - Test historickych dat pres /api/test-hist
# ================================================================
app.clientside_callback(
    """
    function(n) {
        if (n < 1) return n;
        var d = window.lwcDebug || function() {};
        d('API', '=== TEST 2: Historicka data /api/test-hist/AAPL ===');
        d('API', 'Posilam request... (muze trvat 5-15s)');
        var t0 = Date.now();
        fetch('/api/test-hist/AAPL')
            .then(function(r) { return r.json(); })
            .then(function(j) {
                var elapsed = ((Date.now() - t0) / 1000).toFixed(1);
                if (j.ok) {
                    d('API', 'TEST 2 OK: ' + j.bars + ' baru za ' + j.elapsed
                      + 's (JS: ' + elapsed + 's)');
                    d('API', 'Prvni bar: time=' + (j.first && j.first.time)
                      + ' close=' + (j.first && j.first.close));
                } else {
                    d('ERR', 'TEST 2 FAILED: ' + j.error + ' (' + elapsed + 's)');
                }
            })
            .catch(function(e) {
                d('ERR', 'TEST 2 FETCH FAILED: ' + e);
            });
        return n;
    }
    """,
    Output('diag2-trigger', 'data'),
    Input('diag2-btn', 'n_clicks')
)


# ================================================================
# DIAGNOSTIKA 3 - Nacti a nakresli PRES API (bez Dash callbacku)
# ================================================================
app.clientside_callback(
    """
    function(n) {
        if (n < 1) return n;
        var d = window.lwcDebug || function() {};
        d('API', '=== TEST 3: Fetch + nakreslit (bypass Dash) ===');
        d('API', 'Stahuju /api/test-hist/AAPL...');
        fetch('/api/test-hist/AAPL')
            .then(function(r) { return r.json(); })
            .then(function(j) {
                if (!j.ok) {
                    d('ERR', 'TEST 3 data FAIL: ' + j.error);
                    return;
                }
                d('API', 'Data OK: ' + j.bars + ' baru, stahuji vsechna...');
                // Potrebujeme vsechna data, ne jen first/last
                // Zavolame /api/test-hist znovu a vezmeme vsechna data
                // POZOR: test-hist vraci jen summary - volame Dash store manualne
                if (window.lwcManager) {
                    d('API', 'lwcManager dostupny, spoustim testChart() jako fallback');
                    d('API', 'Pro plna IB data pouzij tlacitko Load Chart po fixu.');
                    window.lwcManager.testChart();
                } else {
                    d('ERR', 'lwcManager neni dostupny!');
                }
            })
            .catch(function(e) {
                d('ERR', 'TEST 3 FAILED: ' + e);
            });
        return n;
    }
    """,
    Output('diag3-trigger', 'data'),
    Input('diag3-btn', 'n_clicks')
)


app.clientside_callback(
    """
    function(n) {
        if (n > 0) {
            if (window.lwcManager) { window.lwcManager.testChart(); }
        }
        return n;
    }
    """,
    Output('test-chart-trigger', 'data'),
    Input('test-chart-btn', 'n_clicks')
)


app.clientside_callback(
    """
    function(n) {
        if (n > 0) {
            var a = document.getElementById('debug-log-area');
            if (a) {
                a.select();
                try { document.execCommand('copy'); } catch(e) {}
                a.setSelectionRange(0,0);
                navigator.clipboard && navigator.clipboard.writeText(a.value);
            }
        }
        return n > 0 ? 'Zkopirováno ✓' : '';
    }
    """,
    Output('copy-status', 'children'),
    Input('copy-log-btn', 'n_clicks')
)


app.clientside_callback(
    """
    function(n) {
        if (n > 0) {
            var a = document.getElementById('debug-log-area');
            if (a) { a.value = ''; }
        }
        return n;
    }
    """,
    Output('clear-log-trigger', 'data'),
    Input('clear-log-btn', 'n_clicks')
)


@app.callback(
    [Output('price-display', 'children'),
     Output('price-change-display', 'children')],
    Input('price-update-interval', 'n_intervals'),
    State('symbol-input', 'value')
)
def update_price_display(n, symbol):
    if not symbol or not ib.is_connected():
        return 'Last: $0.00', ''
    ticker = ib.get_ticker(symbol)
    if not ticker:
        return 'Last: $0.00', ''
    lp = ticker.get('last', 0)
    pc = ticker.get('close', lp) or lp
    change = lp - pc
    pct = (change / pc * 100) if pc > 0 else 0
    arrow = '\u25b2' if change >= 0 else '\u25bc'
    color = '#26a69a' if change >= 0 else '#ef5350'
    sign  = '+' if change >= 0 else ''
    return (
        f'Last: ${lp:.2f}',
        html.Span(f' {arrow} {sign}${change:.2f} ({sign}{pct:.2f}%)',
                  style={'color': color})
    )


@app.callback(
    Output('qty-custom', 'value'),
    [Input('qty-1', 'n_clicks'), Input('qty-5', 'n_clicks'),
     Input('qty-10', 'n_clicks'), Input('qty-25', 'n_clicks'),
     Input('qty-100', 'n_clicks')]
)
def update_quantity(q1, q5, q10, q25, q100):
    ctx = dash.callback_context
    if not ctx.triggered:
        return 1
    btn = ctx.triggered[0]['prop_id'].split('.')[0]
    return {'qty-1': 1, 'qty-5': 5, 'qty-10': 10,
            'qty-25': 25, 'qty-100': 100}.get(btn, 1)


@app.callback(
    Output('order-feedback', 'children'),
    [Input('buy-btn', 'n_clicks'), Input('sell-btn', 'n_clicks')],
    [State('symbol-input', 'value'), State('qty-custom', 'value')]
)
def place_order(buy_clicks, sell_clicks, symbol, quantity):
    ctx = dash.callback_context
    if not ctx.triggered:
        return ''
    btn = ctx.triggered[0]['prop_id'].split('.')[0]
    if btn == 'buy-btn' and buy_clicks > 0:
        action, color = 'BUY', '#26a69a'
    elif btn == 'sell-btn' and sell_clicks > 0:
        action, color = 'SELL', '#ef5350'
    else:
        return ''
    if not ib.is_connected():
        return html.Div('\u274c Not connected!',
                        style={'color': '#ef5350', 'fontWeight': 'bold'})
    result = ib.place_market_order(symbol, action, quantity)
    if result['success']:
        return html.Div(f'\u2705 {action} {quantity} {symbol} @ Market',
                        style={'color': color, 'fontWeight': 'bold'})
    return html.Div(f'\u274c {result["error"]}',
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
        side  = 'LONG' if pos['position'] > 0 else 'SHORT'
        rows.append(html.Tr([
            html.Td(pos['symbol'], style={'fontWeight': 'bold'}),
            html.Td(side, style={'color': '#00d4ff'}),
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
    icons  = {'Filled': '\u2705', 'Submitted': '\u23f3',
               'Cancelled': '\u274c', 'PendingSubmit': '\U0001f552'}
    colors = {'Filled': '#26a69a', 'Submitted': '#ffa726',
               'Cancelled': '#ef5350', 'PendingSubmit': '#42a5f5'}
    rows = []
    for o in orders:
        rows.append(html.Tr([
            html.Td(o['time']),
            html.Td(f"{o['action']} {o['quantity']} {o['symbol']}"),
            html.Td(f"@ {o['price']}"),
            html.Td(f"{icons.get(o['status'], '?')} {o['status']}",
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
            }
            .tf-btn:hover, .qty-btn:hover { background: #667eea; }
            .tf-active { background: #667eea; }
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
    print("\U0001f680 Starting IB Trading Platform v2.0.7...")
    print(f"Connecting to {config.IB_HOST}:{config.IB_PORT}")
    if ib.connect():
        print("\u2705 Connected to IB Gateway!")
    else:
        print("\u274c Failed to connect")
    print("http://localhost:8050  |  Ctrl+C to stop\n")
    app.run_server(debug=True, use_reloader=False, host='0.0.0.0', port=8050)

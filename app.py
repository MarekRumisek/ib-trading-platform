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
from backend import api_bp, market_bp, orders_bp, trades_bp, ai_bp
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

# Register Flask blueprints for backend API
server.register_blueprint(api_bp)
server.register_blueprint(market_bp)
server.register_blueprint(orders_bp)
server.register_blueprint(trades_bp)
server.register_blueprint(ai_bp)


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
# app_state - shared state for Dash callbacks
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

        # Vertical stack for dual charts (one above the other)
        html.Div([
            # Main chart (top) with info header
            html.Div([
                # Chart 1 info header (moved from top of layout)
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
                            '+ Load More', id='load-chart-btn', n_clicks=0,
                            title='Load chart with current settings',
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
                          'borderRadius': '8px', 'marginBottom': '15px'}),

                html.Div(id='lwc-container',
                         style={'width': '100%', 'height': '500px', 'position': 'relative',
                                'background': '#1e1e2e'}),
            ], style={'width': '100%', 'display': 'block', 'marginBottom': '12px'}),

            # Context chart (bottom) - Phase 3
            html.Div([
                # Chart 2 info header (moved from top of layout)
                html.Div([
                    html.Div([
                        html.Label('Symbol:', style={'marginRight': '10px', 'fontWeight': 'bold', 'color': '#4caf50'}),
                        dcc.Input(
                            id='symbol-input-2', type='text', value=config_store.get('default_symbol', 'EURUSD'),
                            style={'width': '150px', 'padding': '8px', 'borderRadius': '5px',
                                   'border': '2px solid #4caf50', 'background': '#1e1e2e',
                                   'color': 'white', 'fontSize': '16px'}
                        ),
                        dcc.Dropdown(
                            id='asset-type-select-2',
                            options=[
                                {'label': 'Stock', 'value': 'STOCK'},
                                {'label': 'Forex', 'value': 'FOREX'},
                                {'label': 'Crypto', 'value': 'CRYPTO'},
                            ],
                            value='FOREX',
                            clearable=False,
                            searchable=False,
                            style={'width': '140px', 'display': 'inline-block', 'marginLeft': '10px',
                                   'verticalAlign': 'middle', 'color': '#111'}
                        ),
                        dcc.Dropdown(
                            id='exchange-select-2',
                            options=[
                                {'label': 'SMART (US)', 'value': 'SMART'},
                                {'label': 'IBIS (DE)', 'value': 'IBIS'},
                                {'label': 'AEB (NL)', 'value': 'AEB'},
                                {'label': 'SBF (FR)', 'value': 'SBF'},
                            ],
                            value='SMART',
                            clearable=False,
                            searchable=False,
                            style={'width': '140px', 'display': 'inline-block', 'marginLeft': '10px',
                                   'verticalAlign': 'middle', 'color': '#111'}
                        ),
                        html.Span(' | ', style={'color': '#555', 'marginLeft': '15px', 'marginRight': '5px'}),
                        dcc.Input(
                            id='candles-count-input-2', type='number', value=60, min=10, max=500, step=10,
                            style={'width': '65px', 'padding': '8px', 'borderRadius': '5px',
                                   'border': '2px solid #4caf50', 'background': '#1e1e2e',
                                   'color': 'white', 'fontSize': '14px', 'textAlign': 'center'}
                        ),
                        html.Span(' svíček', style={'color': '#aaa', 'fontSize': '13px', 'marginRight': '10px'}),
                        html.Button(
                            '+ Load More', id='load-chart-btn-2', n_clicks=0,
                            title='Load chart 2 with current settings',
                            style={'marginLeft': '5px', 'padding': '8px 20px',
                                   'background': 'linear-gradient(135deg, #43a047 0%, #2e7d32 100%)',
                                   'border': 'none', 'borderRadius': '5px',
                                   'color': 'white', 'cursor': 'pointer', 'fontWeight': 'bold'}
                        ),
                        html.Span(id='bars-count-display-2', children='',
                                  style={'marginLeft': '15px', 'fontSize': '13px', 'color': '#888'})
                    ], style={'display': 'inline-block', 'marginRight': '30px'}),
                    html.Div([
                        html.Span(id='price-display-2', children='Last: $0.00',
                                  style={'fontSize': '20px', 'fontWeight': 'bold', 'color': '#4caf50'}),
                        html.Span(id='price-change-display-2', children='',
                                  style={'fontSize': '16px', 'marginLeft': '15px'})
                    ], style={'display': 'inline-block'})
                ], style={'padding': '15px', 'background': '#2d2d3a',
                          'borderRadius': '8px', 'marginBottom': '15px'}),

                # Context chart header with TF buttons
                html.Div([
                    html.Span('📊 Context Chart', style={'marginRight': '15px', 'fontWeight': 'bold',
                                                        'fontSize': '14px', 'color': '#aaa'}),
                    html.Button('1m',  id='tf2-1m',  n_clicks=0, className='tf-btn'),
                    html.Button('5m',  id='tf2-5m',  n_clicks=0, className='tf-btn'),
                    html.Button('15m', id='tf2-15m', n_clicks=0, className='tf-btn'),
                    html.Button('30m', id='tf2-30m', n_clicks=0, className='tf-btn'),
                    html.Button('1h',  id='tf2-1h',  n_clicks=0, className='tf-btn'),
                    html.Button('1D',  id='tf2-1d',  n_clicks=0, className='tf-btn tf-active'),
                    html.Button(
                        'Load Chart 2', id='load-chart2-btn', n_clicks=0,
                        style={'marginLeft': '15px', 'padding': '8px 20px',
                               'background': 'linear-gradient(135deg, #43a047 0%, #2e7d32 100%)',
                               'border': 'none', 'borderRadius': '5px',
                               'color': 'white', 'cursor': 'pointer', 'fontWeight': 'bold'}
                    ),
                ], style={'marginBottom': '10px', 'overflow': 'hidden', 'padding': '5px 0'}),

                html.Div(id='lwc-container-2',
                         style={'width': '100%', 'height': '400px', 'position': 'relative',
                                'background': '#1e1e2e'}),
            ], style={'width': '100%', 'display': 'block'}),
        ], style={'display': 'block'}),

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
        # Phase 3: Chart 2 stores
        dcc.Store(id='chart2-data-store'),
        dcc.Store(id='chart2-trigger-store'),
        dcc.Store(id='chart2-append-store'),  # For loading older bars on chart2
        dcc.Store(id='chart2-meta-store', data={'load_count': 0, 'oldest_time': None, 'total_bars': 0, 'symbol': None, 'tf': None}),
        dcc.Store(id='active-tf2-store', data='tf2-1d'),
        # AI stores
        dcc.Store(id='ai-models-store', data=[]),
        dcc.Store(id='ai-evaluate-state', data={'visible': False, 'loading': False, 'result': None, 'error': None}),
        dcc.Store(id='ai-check-state', data={'visible': False, 'loading': False, 'result': None, 'error': None, 'trade': None}),
        dcc.Store(id='ai-check-trigger', data=None),
        dcc.Store(id='indicator2-settings-store',
                  data={'sma': False, 'ema': True, 'rsi': False, 'macd': False}),

    ], style={'padding': '20px', 'background': '#2d2d3a',
              'borderRadius': '8px', 'marginBottom': '20px'}),

    # ================================================================
    # AI TRADE ADVISOR — SEKCE A: EVALUATE ENTRY
    # ================================================================
    html.Div([
        html.H3('🔍 AI Trade Advisor — Evaluate Entry',
                style={'marginBottom': '15px', 'color': '#00d4ff'}),

        # Přepínač pro výběr primárního grafu
        html.Div([
            html.Label('AI pracuje s grafem:', style={'marginRight': '10px', 'fontWeight': 'bold'}),
            dcc.RadioItems(
                id='ai-evaluate-primary-graph',
                options=[
                    {'label': ' Graf 1 ', 'value': 1},
                    {'label': ' Graf 2 ', 'value': 2},
                ],
                value=1,
                style={'display': 'inline-block', 'color': '#ccc'},
                inputStyle={'marginRight': '4px', 'marginLeft': '8px'}
            ),
            html.Span(' | ', style={'color': '#555', 'marginLeft': '10px', 'marginRight': '10px'}),
            html.Span(id='ai-evaluate-symbol-info', children='AAPL | STOCK',
                      style={'color': '#aaa', 'fontSize': '13px'}),
        ], style={'marginBottom': '12px'}),

        # Checkboxy pro výběr grafů a limit svíček
        html.Div([
            html.Label('Zahrnout data z grafů:', style={'marginRight': '10px', 'fontWeight': 'bold'}),
            dcc.Checklist(
                id='ai-evaluate-graphs-checklist',
                options=[
                    {'label': ' Graf 1 ', 'value': 1},
                    {'label': ' Graf 2 ', 'value': 2},
                ],
                value=[1],
                style={'display': 'inline-block', 'color': '#ccc'},
                inputStyle={'marginRight': '8px', 'marginLeft': '4px'}
            ),
            html.Span(' | Max. svíček / graf:', style={'color': '#aaa', 'marginLeft': '15px', 'marginRight': '8px'}),
            dcc.Input(
                id='ai-evaluate-max-bars',
                type='number',
                value=100,
                min=10,
                max=500,
                style={'width': '70px', 'padding': '6px', 'borderRadius': '5px',
                       'border': '2px solid #667eea', 'background': '#1e1e2e',
                       'color': 'white', 'fontSize': '13px'}
            ),
            html.Span(id='ai-evaluate-bars-info', children='~100 řádků dat',
                      style={'color': '#888', 'marginLeft': '10px', 'fontSize': '12px'}),
        ], style={'marginBottom': '15px'}),

        # Tlačítko Evaluate
        html.Div([
            html.Button('🔍 Evaluate', id='ai-evaluate-btn', n_clicks=0,
                        style={'padding': '10px 25px', 'background': 'linear-gradient(135deg, #00d4ff 0%, #0099cc 100%)',
                               'border': 'none', 'borderRadius': '6px', 'color': 'white',
                               'fontWeight': 'bold', 'cursor': 'pointer', 'fontSize': '14px'}),
            html.Span(id='ai-evaluate-loading', children='',
                      style={'marginLeft': '15px', 'color': '#ffd54f', 'fontSize': '14px'}),
        ], style={'marginBottom': '15px'}),

        # Response oblast
        html.Div(id='ai-evaluate-response', style={'display': 'none'}, children=[
            html.Div([
                html.Div(id='ai-evaluate-result', style={'marginBottom': '10px'}),
                html.Div(id='ai-evaluate-reason', style={'marginBottom': '15px', 'color': '#aaa', 'fontSize': '13px'}),
                html.Div([
                    html.Button('✅ Accept', id='ai-evaluate-accept-btn', n_clicks=0,
                                style={'padding': '8px 20px', 'background': '#4caf50',
                                       'border': 'none', 'borderRadius': '5px', 'color': 'white',
                                       'cursor': 'pointer', 'marginRight': '10px'}),
                    html.Button('❌ Reject', id='ai-evaluate-reject-btn', n_clicks=0,
                                style={'padding': '8px 20px', 'background': '#ef5350',
                                       'border': 'none', 'borderRadius': '5px', 'color': 'white',
                                       'cursor': 'pointer'}),
                ]),
            ], style={'padding': '15px', 'background': '#1a1a2e', 'borderRadius': '8px',
                      'border': '1px solid #3d3d4a'}),
        ]),

        # Error oblast
        html.Div(id='ai-evaluate-error', style={'display': 'none', 'color': '#ef5350',
                  'marginTop': '10px', 'padding': '10px', 'background': '#2d1a1a',
                  'borderRadius': '5px'}),
    ], style={'padding': '20px', 'background': '#2d2d3a',
              'borderRadius': '8px', 'marginBottom': '20px'}),

    # ================================================================
    # AI TRADE ADVISOR — SEKCE B: CHECK POSITION
    # ================================================================
    html.Div(id='ai-check-section', children=[
        html.H3('🤖 AI Trade Advisor — Check Position',
                style={'marginBottom': '15px', 'color': '#00d4ff'}),

        # Info řádek (skrytý dokud není aktivován)
        html.Div(id='ai-check-info', style={'display': 'none', 'marginBottom': '12px',
                  'padding': '10px', 'background': '#1a1a2e', 'borderRadius': '5px',
                  'color': '#ffd54f', 'fontSize': '13px'}),

        # Přepínač pro výběr primárního grafu
        html.Div([
            html.Label('AI pracuje s grafem:', style={'marginRight': '10px', 'fontWeight': 'bold'}),
            dcc.RadioItems(
                id='ai-check-primary-graph',
                options=[
                    {'label': ' Graf 1 ', 'value': 1},
                    {'label': ' Graf 2 ', 'value': 2},
                ],
                value=1,
                style={'display': 'inline-block', 'color': '#ccc'},
                inputStyle={'marginRight': '4px', 'marginLeft': '8px'}
            ),
            html.Span(' | ', style={'color': '#555', 'marginLeft': '10px', 'marginRight': '10px'}),
            html.Label('Zahrnout data z grafů:', style={'marginRight': '10px', 'fontWeight': 'bold'}),
            dcc.Checklist(
                id='ai-check-graphs-checklist',
                options=[
                    {'label': ' Graf 1 ', 'value': 1},
                    {'label': ' Graf 2 ', 'value': 2},
                ],
                value=[1],
                style={'display': 'inline-block', 'color': '#ccc'},
                inputStyle={'marginRight': '8px', 'marginLeft': '4px'}
            ),
        ], style={'marginBottom': '15px'}),

        # Loading indikátor
        html.Div(id='ai-check-loading', children='',
                 style={'color': '#ffd54f', 'fontSize': '14px', 'marginBottom': '15px'}),

        # Response oblast
        html.Div(id='ai-check-response', style={'display': 'none'}, children=[
            html.Div([
                html.Div(id='ai-check-result', style={'marginBottom': '10px'}),
                html.Div(id='ai-check-reason', style={'marginBottom': '15px', 'color': '#aaa', 'fontSize': '13px'}),
                html.Div(id='ai-check-actions'),
            ], style={'padding': '15px', 'background': '#1a1a2e', 'borderRadius': '8px',
                      'border': '1px solid #3d3d4a'}),
        ]),

        # Error oblast
        html.Div(id='ai-check-error', style={'display': 'none', 'color': '#ef5350',
                  'marginTop': '10px', 'padding': '10px', 'background': '#2d1a1a',
                  'borderRadius': '5px'}),
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

    # ================================================================
    # SETTINGS
    # ================================================================
    html.Div([
        html.Div([
            html.Button('⚙️ Settings', id='settings-toggle-btn', n_clicks=0,
                        style={'background': '#2d2d3a', 'color': 'white', 'border': 'none',
                               'padding': '10px 20px', 'borderRadius': '5px', 'cursor': 'pointer'}),
        ]),
        html.Div(id='settings-content', style={'display': 'none'}, children=[
            html.H4('App Defaults', style={'marginTop': '15px', 'marginBottom': '10px'}),

            # Chart count (3.1)
            html.Div([
                html.Label('Chart count', style={'marginRight': '10px'}),
                dcc.Dropdown(
                    id='settings-chart-count',
                    options=[
                        {'label': '1 Chart', 'value': 1},
                        {'label': '2 Charts', 'value': 2},
                    ],
                    value=1,
                    style={'width': '120px'},
                    clearable=False,
                ),
            ], style={'marginBottom': '10px', 'display': 'flex', 'alignItems': 'center'}),

            # Default candles count (3.5)
            html.Div([
                html.Label('Default candles count', style={'marginRight': '10px'}),
                dcc.Input(id='settings-default-candles', type='number', min=10, max=500, value=60,
                          style={'width': '100px', 'padding': '8px', 'borderRadius': '5px'}),
            ], style={'marginBottom': '10px', 'display': 'flex', 'alignItems': 'center'}),

            # Favorite symbols
            html.Div([
                html.Label('Favorite symbols', style={'marginRight': '10px'}),
                dcc.Input(id='settings-favorites', type='text', placeholder='AAPL, EURUSD, TSLA',
                          style={'width': '250px', 'padding': '8px', 'borderRadius': '5px'}),
            ], style={'marginBottom': '10px', 'display': 'flex', 'alignItems': 'center'}),

            # Default quantity
            html.Div([
                html.Label('Default quantity', style={'marginRight': '10px'}),
                dcc.Input(id='settings-default-qty', type='number', min=1,
                          style={'width': '100px', 'padding': '8px', 'borderRadius': '5px'}),
            ], style={'marginBottom': '10px', 'display': 'flex', 'alignItems': 'center'}),

            # Default timeframe
            html.Div([
                html.Label('Default timeframe', style={'marginRight': '10px'}),
                dcc.Dropdown(
                    id='settings-default-tf',
                    options=[
                        {'label': '1 min', 'value': '1 min'},
                        {'label': '5 mins', 'value': '5 mins'},
                        {'label': '15 mins', 'value': '15 mins'},
                        {'label': '30 mins', 'value': '30 mins'},
                        {'label': '1 hour', 'value': '1 hour'},
                        {'label': '1 day', 'value': '1 day'},
                    ],
                    value='5 mins',
                    style={'width': '150px'},
                    clearable=False,
                ),
            ], style={'marginBottom': '10px', 'display': 'flex', 'alignItems': 'center'}),

            # Default asset type
            html.Div([
                html.Label('Default asset type', style={'marginRight': '10px'}),
                dcc.Dropdown(
                    id='settings-default-asset',
                    options=[
                        {'label': 'STOCK', 'value': 'STOCK'},
                        {'label': 'FOREX', 'value': 'FOREX'},
                        {'label': 'CRYPTO', 'value': 'CRYPTO'},
                    ],
                    value='STOCK',
                    style={'width': '150px'},
                    clearable=False,
                ),
            ], style={'marginBottom': '10px', 'display': 'flex', 'alignItems': 'center'}),

            # Default exchange
            html.Div([
                html.Label('Default exchange', style={'marginRight': '10px'}),
                dcc.Dropdown(
                    id='settings-default-exchange',
                    options=[
                        {'label': 'SMART', 'value': 'SMART'},
                        {'label': 'IBIS', 'value': 'IBIS'},
                        {'label': 'AEB', 'value': 'AEB'},
                        {'label': 'SBF', 'value': 'SBF'},
                    ],
                    value='SMART',
                    style={'width': '150px'},
                    clearable=False,
                ),
            ], style={'marginBottom': '20px', 'display': 'flex', 'alignItems': 'center'}),

            # AI Configuration section (inactive, Phase 5)
            html.H4('AI Configuration (Phase 5)', style={'marginBottom': '10px', 'color': '#ffeb3b'}),
            html.Div('⚠️ AI settings — will be activated in Phase 5',
                     style={'marginBottom': '15px', 'fontStyle': 'italic', 'color': '#ff9800'}),

            # OpenRouter API key
            html.Div([
                html.Label('OpenRouter API key', style={'marginRight': '10px', 'width': '150px'}),
                dcc.Input(id='settings-api-key', type='password',
                          placeholder='sk-or-...',
                          style={'width': '300px', 'padding': '8px', 'borderRadius': '5px'}),
            ], style={'marginBottom': '10px', 'display': 'flex', 'alignItems': 'center'}),

            # LLM model (dropdown with dynamic options from OpenRouter)
            html.Div([
                html.Label('LLM model', style={'marginRight': '10px', 'width': '150px'}),
                dcc.Dropdown(
                    id='settings-llm-model',
                    options=[
                        {'label': 'minimax/minimax-m2.5:free (default)', 'value': 'minimax/minimax-m2.5:free'},
                    ],
                    value='minimax/minimax-m2.5:free',
                    style={'width': '320px', 'color': '#111'},
                    clearable=False,
                ),
                html.Button('🔄', id='ai-refresh-models-btn', n_clicks=0,
                            title='Refresh models list',
                            style={'marginLeft': '8px', 'padding': '6px 10px',
                                   'background': '#667eea', 'border': 'none',
                                   'borderRadius': '5px', 'color': 'white',
                                   'cursor': 'pointer', 'fontSize': '12px'}),
                html.Span(id='ai-models-status', children='',
                          style={'marginLeft': '10px', 'fontSize': '12px', 'color': '#888'}),
            ], style={'marginBottom': '10px', 'display': 'flex', 'alignItems': 'center'}),

            # Max bars per chart for AI
            html.Div([
                html.Label('Max. svíček / graf pro AI', style={'marginRight': '10px', 'width': '200px'}),
                dcc.Input(id='settings-ai-max-bars', type='number', min=10, max=500, value=100,
                          style={'width': '100px', 'padding': '8px', 'borderRadius': '5px'}),
            ], style={'marginBottom': '10px', 'display': 'flex', 'alignItems': 'center'}),

            # Strategy / rules
            html.Div([
                html.Label('Strategy / rules', style={'marginRight': '10px', 'width': '150px', 'verticalAlign': 'top'}),
                dcc.Textarea(id='settings-strategy', rows=6,
                              placeholder='Describe your trading strategy and entry rules...',
                              style={'width': '400px', 'padding': '8px', 'borderRadius': '5px'}),
            ], style={'marginBottom': '10px', 'display': 'flex', 'alignItems': 'flex-start'}),

            # Money management rules
            html.Div([
                html.Label('Money management', style={'marginRight': '10px', 'width': '150px', 'verticalAlign': 'top'}),
                dcc.Textarea(id='settings-mm-rules', rows=4,
                              placeholder='e.g. max 2% risk per trade, max 3 open positions...',
                              style={'width': '400px', 'padding': '8px', 'borderRadius': '5px'}),
            ], style={'marginBottom': '15px', 'display': 'flex', 'alignItems': 'flex-start'}),

            # Save button and feedback
            html.Div([
                html.Button('💾 Save Settings', id='settings-save-btn', n_clicks=0,
                            style={'background': '#4caf50', 'color': 'white', 'border': 'none',
                                   'padding': '10px 20px', 'borderRadius': '5px', 'cursor': 'pointer'}),
                html.Span(id='settings-save-feedback', style={'marginLeft': '15px'}),
            ]),
        ]),
        # Hidden Interval to trigger settings load on page start
        dcc.Interval(id='settings-load-trigger', interval=100, max_intervals=1),
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
        return html.Span([html.Span('●', style={'color': '#4caf50', 'marginRight': '5px', 'fontSize': '12px'}),
                          html.Span('Connected to IB Gateway', style={'color': '#4caf50'})])
    return html.Span([html.Span('●', style={'color': '#ef5350', 'marginRight': '5px', 'fontSize': '12px'}),
                      html.Span('Disconnected', style={'color': '#ef5350'})])


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
    print(f"[LOAD_CHART] Called! load_clicks={load_clicks}, tf1={tf1}, tf5={tf5}, tf15={tf15}, tf30={tf30}, tf1h={tf1h}, tf1d={tf1d}")
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
        
        # INFO: Log inputs
        log("INFO", f"[CB-DIAG] symbol={symbol} asset_type={asset_type} tf={tf} n_candles={n_candles} btn={btn}")
        
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
            log("INFO", f"[CB] INITIAL LOAD: {symbol} ({asset_type}) | {tf} | n={n_candles} | Trigger={btn}")
            bars = ib_gateway.get_n_bars(symbol, n_candles, tf, asset_type, end_time=None)
            log("INFO", f"[CB] IB returned {len(bars)} bars")
            
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
            
            log('INFO', f'[CB] VRACIM {len(bars)} SVICCEK DO STORE | tf={tf} | bars[0].time={bars[0]["time"] if bars else "N/A"}')
            log('INFO', '[TICK] Auto-enabled on chart load')
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
            
            log("DEBUG", f"[CB] APPEND: {symbol} ({asset_type}) | {tf} | n={n_candles} | before={oldest_time} | load_count={meta.get('load_count', 0)}")
            
            # For 1D timeframe, IB's end_time handling is problematic
            # Instead, fetch without end_time and filter overlaps ourselves
            log("DIAG", f"[CB] TF check: tf='{tf}' (type={type(tf).__name__}) | tf == '1 day': {tf == '1 day'}")
            
            if tf == '1 day':
                # For daily bars: don't use end_time, just fetch and filter
                older_bars = ib_gateway.get_n_bars(symbol, n_candles * 3, tf, asset_type, end_time=None)
                log("DIAG", f"[CB] 1D: fetched {len(older_bars)} bars (no end_time filter)")
                log("DIAG", f"[CB] 1D: oldest_time={oldest_time} | first_bar_time={older_bars[0]['time'] if older_bars else 'N/A'}")
                
                # Filter out bars that overlap with existing chart data
                if older_bars and oldest_time:
                    original_count = len(older_bars)
                    older_bars = [b for b in older_bars if b['time'] < oldest_time]
                    log("DIAG", f"[CB] 1D: filtered {original_count} -> {len(older_bars)} bars (removed overlapping)")
                
                if not older_bars or len(older_bars) == 0:
                    log("DIAG", f"[CB] 1D: no older bars after filter - returning no_update")
                    return dash.no_update, None, dash.no_update, dash.no_update, dash.no_update, dash.no_update, '⚠️ Žádná starší data'
                
                # Take only the first n_candles after filtering
                older_bars = older_bars[:n_candles]
                log("DIAG", f"[CB] 1D: taking first {len(older_bars)} bars")
            else:
                # For other timeframes: use end_time as before
                tf_to_seconds = {'1 min': 60, '5 mins': 300, '15 mins': 900, '30 mins': 1800, '1 hour': 3600, '1 day': 86400}
                secs_per_bar = tf_to_seconds.get(tf, 300)
                append_offset = n_candles * secs_per_bar
                append_end_time = oldest_time - append_offset
                
                older_bars = ib_gateway.get_n_bars(symbol, n_candles, tf, asset_type, end_time=append_end_time)
                
                if not older_bars:
                    return dash.no_update, None, dash.no_update, dash.no_update, dash.no_update, dash.no_update, '⚠️ Žádná starší data'
            
            log("DEBUG", f"[CB] IB returned {len(older_bars)} older bars | first_time={older_bars[0]['time'] if older_bars else 'N/A'}")
            
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


# ------------------------------------------------------------------
# CHART 2 (Context Chart) - Independent per-block state (3.3)
# ------------------------------------------------------------------
@app.callback(
    [Output('chart2-data-store', 'data'),
     Output('chart2-append-store', 'data'),
     Output('chart2-meta-store', 'data'),
     Output('bars-count-display-2', 'children')],
    [Input('load-chart-btn-2', 'n_clicks'),
     Input('load-chart2-btn', 'n_clicks'),
     Input('tf2-1m', 'n_clicks'), Input('tf2-5m', 'n_clicks'),
     Input('tf2-15m', 'n_clicks'), Input('tf2-30m', 'n_clicks'),
     Input('tf2-1h', 'n_clicks'), Input('tf2-1d', 'n_clicks')],
    [State('symbol-input-2', 'value'),
     State('asset-type-select-2', 'value'),
     State('exchange-select-2', 'value'),
     State('candles-count-input-2', 'value'),
     State('chart2-meta-store', 'data')],
    prevent_initial_call=True
)
def load_chart2_data(load_clicks, load_clicks2, tf1, tf5, tf15, tf30, tf1h, tf1d,
                     symbol, asset_type, exchange, n_candles, meta):
    """Load data for chart 2. Independent per-block state (3.3)."""
    try:
        ctx = dash.callback_context
        btn = (ctx.triggered[0]['prop_id'].split('.')[0]
               if ctx.triggered else 'load-chart-btn-2')
        log("DEBUG", f"[CB2] TRIGGERED: {btn} | symbol={symbol} asset_type={asset_type}")
        tf_map = {'tf2-1m': '1 min', 'tf2-5m': '5 mins',
                  'tf2-15m': '15 mins', 'tf2-30m': '30 mins',
                  'tf2-1h': '1 hour', 'tf2-1d': '1 day',
                  'load-chart-btn-2': None, 'load-chart2-btn': None}

        symbol     = (symbol or 'EURUSD').upper()
        asset_type = normalize_asset_type(asset_type)
        n_candles  = max(10, min(500, int(n_candles or 60)))

        # Determine TF from button click
        if btn in tf_map:
            tf = tf_map[btn]
            if tf is None:
                # Load button clicked - use stored TF or default to 5 mins
                tf = (meta.get('tf') if meta else None) or '5 mins'
        else:
            # Default to 5 mins for chart 2 if not specified
            tf = '5 mins'

        # Check if this is a reset (symbol/TF changed) or append
        prev_symbol = meta.get('symbol') if meta else None
        prev_tf     = meta.get('tf') if meta else None
        is_reset    = (btn in tf_map or
                       prev_symbol != symbol or
                       prev_tf != tf)

        if is_reset:
            # === FIRST LOAD or RESET: fetch N candles from now ===
            log("DEBUG", f"[CB2] INITIAL LOAD: {symbol} ({asset_type}) | {tf} | n={n_candles} | Trigger={btn}")
            bars = ib_gateway.get_n_bars(symbol, n_candles, tf, asset_type, end_time=None)
            log("DEBUG", f"[CB2] IB returned {len(bars)} bars")

            if not bars:
                return dash.no_update, dash.no_update, dash.no_update, '❌ Žádná data'

            new_meta = {
                'load_count': 1,
                'oldest_time': bars[0]['time'] if bars else None,
                'total_bars': len(bars),
                'symbol': symbol,
                'tf': tf,
                'n_candles': n_candles
            }

            chart2_data = {'symbol': symbol, 'asset_type': asset_type, 'timeframe': tf, 'bars': bars, 'mode': 'initial'}
            bars_display = f"📊 {len(bars)} svíček"
            return chart2_data, None, new_meta, bars_display

        else:
            # === APPEND: fetch older candles ===
            oldest_time = meta.get('oldest_time') if meta else None
            if not oldest_time:
                log("DEBUG", "[CB2] APPEND: no oldest_time, treating as initial")
                bars = ib_gateway.get_n_bars(symbol, n_candles, tf, asset_type, end_time=None)
                new_meta = {
                    'load_count': 1,
                    'oldest_time': bars[0]['time'] if bars else None,
                    'total_bars': len(bars),
                    'symbol': symbol,
                    'tf': tf,
                    'n_candles': n_candles
                }
                chart2_data = {'symbol': symbol, 'asset_type': asset_type, 'timeframe': tf, 'bars': bars, 'mode': 'initial'}
                return chart2_data, None, new_meta, f"📊 {len(bars)} svíček"

            log("DEBUG", f"[CB2] APPEND: {symbol} ({asset_type}) | {tf} | n={n_candles} | before={oldest_time}")

            # Fetch older bars ending just before oldest_time
            older_bars = ib_gateway.get_n_bars(symbol, n_candles, tf, asset_type, end_time=oldest_time - 1)
            log("DEBUG", f"[CB2] IB returned {len(older_bars)} older bars")

            if not older_bars:
                return dash.no_update, None, dash.no_update, '⚠️ Žádná starší data'

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

            return dash.no_update, append_data, new_meta, bars_display

    except Exception as e:
        log("INFO", f"[CB2] EXCEPTION: {e}")
        return dash.no_update, dash.no_update, dash.no_update, f'❌ {e}'


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
# SETTINGS: toggle show/hide
# ------------------------------------------------------------------
@app.callback(
    Output('settings-content', 'style'),
    Input('settings-toggle-btn', 'n_clicks'),
    prevent_initial_call=True
)
def toggle_settings(n_clicks):
    return {'display': 'block'} if n_clicks % 2 == 1 else {'display': 'none'}


# ------------------------------------------------------------------
# SETTINGS: load settings from config_store on page start
# ------------------------------------------------------------------
@app.callback(
    [Output('settings-favorites', 'value'),
     Output('settings-default-qty', 'value'),
     Output('settings-default-tf', 'value'),
     Output('settings-default-asset', 'value'),
     Output('settings-default-exchange', 'value'),
     Output('settings-api-key', 'value'),
     Output('settings-llm-model', 'value'),
     Output('settings-strategy', 'value'),
     Output('settings-mm-rules', 'value'),
     Output('settings-ai-max-bars', 'value')],
    Input('settings-load-trigger', 'n_intervals'),
    prevent_initial_call=True
)
def load_settings(n_intervals):
    cfg = config_store.get_all()
    # favorite_symbols is a list - convert to comma-separated string
    fav = cfg.get('favorite_symbols', [])
    fav_str = ", ".join(fav) if isinstance(fav, list) else str(fav)
    return (
        fav_str,
        cfg.get('default_quantity', 1),
        cfg.get('default_timeframe', '5 mins'),
        cfg.get('default_asset_type', 'STOCK'),
        cfg.get('default_exchange', 'SMART'),
        cfg.get('openrouter_api_key', ''),
        cfg.get('llm_model', 'minimax/minimax-m2.5:free'),
        cfg.get('strategy_text', ''),
        cfg.get('mm_rules_text', ''),
        cfg.get('ai_max_bars_per_chart', 100),
    )


# ------------------------------------------------------------------
# SETTINGS: save settings and sync to app_state / UI components
# ------------------------------------------------------------------
@app.callback(
    [Output('settings-save-feedback', 'children'),
     Output('symbol-input', 'value'),
     Output('asset-type-select', 'value'),
     Output('exchange-select', 'value')],
    Input('settings-save-btn', 'n_clicks'),
    [State('settings-favorites', 'value'),
     State('settings-default-qty', 'value'),
     State('settings-default-tf', 'value'),
     State('settings-default-asset', 'value'),
     State('settings-default-exchange', 'value'),
     State('settings-api-key', 'value'),
     State('settings-llm-model', 'value'),
     State('settings-strategy', 'value'),
     State('settings-mm-rules', 'value'),
     State('settings-ai-max-bars', 'value')],
    prevent_initial_call=True
)
def save_settings(n_clicks, fav_str, default_qty, default_tf, default_asset,
                  default_exchange, api_key, llm_model, strategy_text, mm_rules_text, ai_max_bars):
    # Parse favorite symbols from comma-separated string to list
    favorite_symbols = [s.strip() for s in (fav_str or '').split(',') if s.strip()]

    # Save all values to config_store
    config_store.set('favorite_symbols', favorite_symbols)
    config_store.set('default_quantity', default_qty or 1)
    config_store.set('default_timeframe', default_tf or '5 mins')
    config_store.set('default_asset_type', default_asset or 'STOCK')
    config_store.set('default_exchange', default_exchange or 'SMART')
    config_store.set('openrouter_api_key', api_key or '')
    config_store.set('llm_model', llm_model or 'minimax/minimax-m2.5:free')
    config_store.set('strategy_text', strategy_text or '')
    config_store.set('mm_rules_text', mm_rules_text or '')
    config_store.set('ai_max_bars_per_chart', ai_max_bars or 100)

    # Sync to app_state
    app_state['current_timeframe'] = default_tf or '5 mins'
    app_state['current_asset_type'] = default_asset or 'STOCK'
    app_state['current_exchange'] = default_exchange or 'SMART'

    # Sync exchange to contract_utils
    set_default_exchange(default_exchange or 'SMART')

    # Determine default symbol (first in favorites, or AAPL)
    default_symbol = favorite_symbols[0] if favorite_symbols else 'AAPL'

    return (
        html.Span('✅ Settings saved', style={'color': '#4caf50'}),
        default_symbol,
        default_qty or 1,
        default_asset or 'STOCK',
        default_exchange or 'SMART',
    )


# ------------------------------------------------------------------
# AI: refresh models list from OpenRouter
# ------------------------------------------------------------------
@app.callback(
    [Output('ai-models-store', 'data'),
     Output('settings-llm-model', 'options'),
     Output('ai-models-status', 'children')],
    [Input('ai-refresh-models-btn', 'n_clicks'),
     Input('settings-load-trigger', 'n_intervals')],
    State('settings-api-key', 'value'),
    prevent_initial_call=True
)
def refresh_ai_models(n_clicks_refresh, n_intervals_load, api_key):
    ctx = dash.callback_context
    triggered = ctx.triggered[0]['prop_id'] if ctx.triggered else ''
    
    if not api_key:
        return [], [{'label': 'minimax/minimax-m2.5:free (default)', 'value': 'minimax/minimax-m2.5:free'}], '⚠️ Nastavte API key'
    
    try:
        import requests
        resp = requests.get(
            'https://openrouter.ai/api/v1/models',
            headers={'Authorization': f'Bearer {api_key}'},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        
        # Filter free models (pricing.prompt == "0")
        free_models = []
        for model in data.get('data', []):
            pricing = model.get('pricing', {})
            prompt_price = pricing.get('prompt', '0')
            if str(prompt_price) == '0' or str(prompt_price) == '0.0':
                model_id = model.get('id', '')
                model_name = model.get('name', model_id)
                free_models.append({
                    'id': model_id,
                    'name': model_name,
                    'label': f"{model_name} ({model_id})" if model_name != model_id else model_id,
                    'value': model_id,
                })
        
        # Sort by name
        free_models.sort(key=lambda x: x['name'].lower())
        
        # Build options for dropdown
        options = [{'label': m['label'], 'value': m['value']} for m in free_models]
        
        if not options:
            options = [{'label': 'minimax/minimax-m2.5:free (default)', 'value': 'minimax/minimax-m2.5:free'}]
        
        return free_models, options, f'✅ {len(free_models)} free models'
        
    except Exception as e:
        return [], [{'label': 'minimax/minimax-m2.5:free (default)', 'value': 'minimax/minimax-m2.5:free'}], f'❌ Chyba: {str(e)[:50]}'


# ------------------------------------------------------------------
# AI EVALUATE: update symbol info based on primary graph selection
# ------------------------------------------------------------------
@app.callback(
    Output('ai-evaluate-symbol-info', 'children'),
    Input('ai-evaluate-primary-graph', 'value'),
    [State('symbol-input', 'value'),
     State('asset-type-select', 'value'),
     State('symbol-input-2', 'value'),
     State('asset-type-select-2', 'value')]
)
def update_ai_evaluate_symbol(primary_graph, sym1, at1, sym2, at2):
    if primary_graph == 1:
        return f"{sym1 or 'AAPL'} | {at1 or 'STOCK'}"
    else:
        return f"{sym2 or 'EURUSD'} | {at2 or 'FOREX'}"


@app.callback(
    Output('ai-evaluate-bars-info', 'children'),
    Input('ai-evaluate-max-bars', 'value'),
    State('ai-evaluate-graphs-checklist', 'value')
)
def update_ai_evaluate_bars_info(max_bars, selected_graphs):
    count = len(selected_graphs) * (max_bars or 100)
    return f"~{count} řádků dat"


# ------------------------------------------------------------------
# AI EVALUATE: main evaluate callback
# ------------------------------------------------------------------
@app.callback(
    [Output('ai-evaluate-loading', 'children'),
     Output('ai-evaluate-response', 'style'),
     Output('ai-evaluate-error', 'style'),
     Output('ai-evaluate-result', 'children'),
     Output('ai-evaluate-reason', 'children'),
     Output('ai-evaluate-state', 'data'),
     Output('ai-evaluate-max-bars', 'value')],
    Input('ai-evaluate-btn', 'n_clicks'),
    [State('ai-evaluate-primary-graph', 'value'),
     State('ai-evaluate-graphs-checklist', 'value'),
     State('ai-evaluate-max-bars', 'value'),
     State('chart-data-store', 'data'),
     State('symbol-input', 'value'),
     State('asset-type-select', 'value'),
     State('symbol-input-2', 'value'),
     State('asset-type-select-2', 'value'),
     State('active-tf-store', 'data'),
     State('active-tf2-store', 'data'),
     State('indicator-settings-store', 'data'),
     State('indicator2-settings-store', 'data'),
     State('chart2-data-store', 'data')],
    prevent_initial_call=True
)
def ai_evaluate_callback(n_clicks, primary_graph, selected_graphs, max_bars,
                          chart1_data, sym1, at1, sym2, at2, tf1, tf2,
                          ind1_settings, ind2_settings, chart2_data):
    if n_clicks == 0:
        return '', {'display': 'none'}, {'display': 'none'}, '', '', dash.no_update, dash.no_update
    
    # Check if at least one graph is selected
    if not selected_graphs:
        return '', {'display': 'none'}, {'display': 'block'}, '', '⚠️ Vyberte alespoň jeden graf', dash.no_update, dash.no_update
    
    # Check API key
    api_key = config_store.get('openrouter_api_key', '')
    model = config_store.get('llm_model', '')
    if not api_key:
        return '', {'display': 'none'}, {'display': 'block'}, '', '⚠️ Nastavte OpenRouter API key v Settings', dash.no_update, dash.no_update
    
    # Show loading
    loading_style = {'color': '#ffd54f'}
    
    try:
        import requests
        import json
        
        # Prepare graphs data
        graphs = []
        indicators = {}
        
        # TF mapping
        tf_map = {
            'tf-1m': '1 min', 'tf-5m': '5 mins', 'tf-15m': '15 mins',
            'tf-30m': '30 mins', 'tf-1h': '1 hour', 'tf-1d': '1 day',
            'tf2-1m': '1 min', 'tf2-5m': '5 mins', 'tf2-15m': '15 mins',
            'tf2-30m': '30 mins', 'tf2-1h': '1 hour', 'tf2-1d': '1 day',
        }
        
        max_bars = max_bars or 100
        
        # Graph 1
        if 1 in selected_graphs and chart1_data:
            bars = chart1_data[-max_bars:] if len(chart1_data) > max_bars else chart1_data
            graphs.append({
                'symbol': sym1 or 'AAPL',
                'tf': tf_map.get(tf1, '5 mins'),
                'asset_type': at1 or 'STOCK',
                'bars': bars
            })
            if primary_graph == 1:
                indicators = ind1_settings or {}
        
        # Graph 2
        if 2 in selected_graphs and chart2_data:
            bars = chart2_data[-max_bars:] if len(chart2_data) > max_bars else chart2_data
            graphs.append({
                'symbol': sym2 or 'EURUSD',
                'tf': tf_map.get(tf2, '5 mins'),
                'asset_type': at2 or 'FOREX',
                'bars': bars
            })
            if primary_graph == 2:
                indicators = ind2_settings or {}
        
        # Get account info
        try:
            resp = requests.get(f'http://localhost:8050/api/account/info', timeout=5)
            account_info = resp.json() if resp.status_code == 200 else {}
        except:
            account_info = {}
        
        # Build request payload
        payload = {
            'primary_graph_index': primary_graph,
            'graphs': graphs,
            'indicators': indicators,
            'account': {
                'net_liquidation': account_info.get('net_liquidation', 0),
                'buying_power': account_info.get('buying_power', 0)
            }
        }
        
        # Call AI endpoint
        resp = requests.post(
            'http://localhost:8050/api/ai/evaluate',
            json=payload,
            timeout=60
        )
        
        if resp.status_code != 200:
            return '', {'display': 'none'}, {'display': 'block'}, '', f'❌ Chyba API: {resp.status_code}', dash.no_update, dash.no_update
        
        result = resp.json()
        
        if 'error' in result:
            return '', {'display': 'none'}, {'display': 'block'}, '', f'❌ {result["error"]}', dash.no_update, dash.no_update
        
        # Format result
        rec = result.get('recommendation', 'HOLD')
        order_type = result.get('order_type', 'MARKET')
        rr_ratio = result.get('rr_ratio', '–')
        entry = result.get('entry_price', 0)
        sl = result.get('sl', 0)
        tp = result.get('tp', 0)
        qty = result.get('quantity', 0)
        reason = result.get('reason', '')
        
        result_text = f"Recommendation: {rec} | Order: {order_type} | R/R: {rr_ratio}"
        entry_text = f"Entry: ${entry:.2f} | SL: ${sl:.2f} | TP: ${tp:.2f} | Qty: {qty}"
        
        return ('', {'display': 'block'}, {'display': 'none'},
                f"{result_text}\n{entry_text}", reason,
                {'visible': True, 'loading': False, 'result': result, 'error': None},
                dash.no_update)
        
    except Exception as e:
        import traceback
        log("ERROR", f"AI evaluate error: {e}\n{traceback.format_exc()}")
        return '', {'display': 'none'}, {'display': 'block'}, '', f'❌ {str(e)[:100]}', dash.no_update, dash.no_update


# ------------------------------------------------------------------
# AI EVALUATE: Accept button - fill order entry and submit
# ------------------------------------------------------------------
@app.callback(
    [Output('ai-evaluate-response', 'style', allow_duplicate=True),
     Output('ai-evaluate-state', 'data', allow_duplicate=True),
     Output('sl-price-input', 'value'),
     Output('tp-price-input', 'value'),
     Output('qty-custom', 'value'),
     Output('buy-btn', 'n_clicks'),
     Output('sell-btn', 'n_clicks')],
    Input('ai-evaluate-accept-btn', 'n_clicks'),
    State('ai-evaluate-state', 'data'),
    prevent_initial_call=True
)
def ai_evaluate_accept(n_clicks, state):
    if n_clicks == 0 or not state or not state.get('result'):
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update
    
    result = state['result']
    sl = result.get('sl', 0)
    tp = result.get('tp', 0)
    qty = result.get('quantity', 0)
    recommendation = result.get('recommendation', 'BUY')
    
    # Determine if BUY or SELL
    if recommendation == 'BUY':
        return {'display': 'none'}, {'visible': False, 'loading': False, 'result': None, 'error': None}, sl, tp, qty, 1, 0
    else:
        return {'display': 'none'}, {'visible': False, 'loading': False, 'result': None, 'error': None}, sl, tp, qty, 0, 1


@app.callback(
    [Output('ai-evaluate-response', 'style', allow_duplicate=True),
     Output('ai-evaluate-state', 'data', allow_duplicate=True)],
    Input('ai-evaluate-reject-btn', 'n_clicks'),
    State('ai-evaluate-state', 'data'),
    prevent_initial_call=True
)
def ai_evaluate_reject(n_clicks, state):
    if n_clicks == 0:
        return dash.no_update, dash.no_update
    return {'display': 'none'}, {'visible': False, 'loading': False, 'result': None, 'error': None}


# ------------------------------------------------------------------
# AI CHECK POSITION: trigger from position table button
# ------------------------------------------------------------------
@app.callback(
    Output('ai-check-trigger', 'data'),
    Input({'type': 'ai-check-pos-btn', 'trade_id': dash.ALL}, 'n_clicks'),
    State({'type': 'ai-check-pos-btn', 'trade_id': dash.ALL}, 'id'),
    prevent_initial_call=True
)
def ai_check_position_trigger(n_clicks_list, button_ids):
    ctx = dash.callback_context
    if not ctx.triggered:
        return dash.no_update
    
    triggered = ctx.triggered[0]
    if not triggered['value']:
        return dash.no_update
    
    import json
    prop_id = triggered['prop_id']
    id_part = prop_id.split('.')[0]
    trade_id_dict = json.loads(id_part)
    trade_id = trade_id_dict.get('trade_id', '')
    
    if trade_id:
        return {'trade_id': trade_id, 'triggered': True}
    return dash.no_update


# ------------------------------------------------------------------
# AI CHECK POSITION: main check callback
# ------------------------------------------------------------------
@app.callback(
    [Output('ai-check-info', 'style'),
     Output('ai-check-info', 'children'),
     Output('ai-check-loading', 'children'),
     Output('ai-check-response', 'style'),
     Output('ai-check-error', 'style'),
     Output('ai-check-result', 'children'),
     Output('ai-check-reason', 'children'),
     Output('ai-check-actions', 'children'),
     Output('ai-check-state', 'data'),
     Output('ai-check-primary-graph', 'value')],
    Input('ai-check-trigger', 'data'),
    [State('ai-check-primary-graph', 'value'),
     State('ai-check-graphs-checklist', 'value'),
     State('chart-data-store', 'data'),
     State('symbol-input', 'value'),
     State('asset-type-select', 'value'),
     State('symbol-input-2', 'value'),
     State('asset-type-select-2', 'value'),
     State('active-tf-store', 'data'),
     State('active-tf2-store', 'data'),
     State('indicator-settings-store', 'data'),
     State('indicator2-settings-store', 'data'),
     State('chart2-data-store', 'data')],
    prevent_initial_call=True
)
def ai_check_position_callback(trigger_data, primary_graph, selected_graphs,
                               chart1_data, sym1, at1, sym2, at2, tf1, tf2,
                               ind1_settings, ind2_settings, chart2_data):
    if not trigger_data or not trigger_data.get('triggered'):
        return dash.no_update, dash.no_update, '', {'display': 'none'}, {'display': 'none'}, '', '', '', dash.no_update, dash.no_update
    
    trade_id = trigger_data.get('trade_id', '')
    
    # Get trade details
    trade = trade_tracker.get_trade(trade_id)
    if not trade:
        return {'display': 'block'}, '⚠️ Trade nenalezen', '', {'display': 'none'}, {'display': 'block'}, '', '❌ Trade nenalezen', '', dash.no_update, dash.no_update
    
    # Build info line
    sym = trade.get('symbol', '?')
    side = trade.get('side', 'BUY')
    qty = trade.get('qty', 0)
    entry = trade.get('entry_price', 0)
    sl = trade.get('sl', 0)
    tp = trade.get('tp', 0)
    trade_sym = sym
    
    # Calculate P&L
    pnl = 0
    try:
        positions = ib_gateway.get_positions() or []
        for pos in positions:
            if pos.get('symbol') == sym:
                mult = 1 if side == 'BUY' else -1
                current_price = pos['market_value'] / abs(pos['position']) if pos['position'] != 0 else 0
                pnl = mult * (current_price - entry) * qty
                break
    except:
        pass
    
    pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
    info_line = f"Kontroluji: {sym} {side} {qty}× | Entry ${entry:.2f} | SL ${sl:.2f} | TP ${tp:.2f} | P&L {pnl_str}"
    
    # Check API key
    api_key = config_store.get('openrouter_api_key', '')
    if not api_key:
        return {'display': 'block'}, info_line, '', {'display': 'none'}, {'display': 'block'}, '', '⚠️ Nastavte OpenRouter API key v Settings', '', dash.no_update, dash.no_update
    
    # Auto-select primary graph based on symbol match
    if sym1 and sym1.upper() == sym.upper():
        auto_primary = 1
    elif sym2 and sym2.upper() == sym.upper():
        auto_primary = 2
    else:
        auto_primary = primary_graph
    
    try:
        import requests
        import json
        
        # Prepare graphs data
        graphs = []
        indicators = {}
        
        # TF mapping
        tf_map = {
            'tf-1m': '1 min', 'tf-5m': '5 mins', 'tf-15m': '15 mins',
            'tf-30m': '30 mins', 'tf-1h': '1 hour', 'tf-1d': '1 day',
            'tf2-1m': '1 min', 'tf2-5m': '5 mins', 'tf2-15m': '15 mins',
            'tf2-30m': '30 mins', 'tf2-1h': '1 hour', 'tf2-1d': '1 day',
        }
        
        max_bars = config_store.get('ai_max_bars_per_chart', 100)
        
        # Graph 1
        if 1 in selected_graphs and chart1_data:
            bars = chart1_data[-max_bars:] if len(chart1_data) > max_bars else chart1_data
            graphs.append({
                'symbol': sym1 or 'AAPL',
                'tf': tf_map.get(tf1, '5 mins'),
                'asset_type': at1 or 'STOCK',
                'bars': bars
            })
            if auto_primary == 1:
                indicators = ind1_settings or {}
        
        # Graph 2
        if 2 in selected_graphs and chart2_data:
            bars = chart2_data[-max_bars:] if len(chart2_data) > max_bars else chart2_data
            graphs.append({
                'symbol': sym2 or 'EURUSD',
                'tf': tf_map.get(tf2, '5 mins'),
                'asset_type': at2 or 'FOREX',
                'bars': bars
            })
            if auto_primary == 2:
                indicators = ind2_settings or {}
        
        # Build request payload
        payload = {
            'trade_id': trade_id,
            'primary_graph_index': auto_primary,
            'graphs': graphs,
            'indicators': indicators,
            'trade': {
                'entry_price': entry,
                'sl': sl,
                'tp': tp,
                'pnl': pnl
            }
        }
        
        # Call AI endpoint
        resp = requests.post(
            'http://localhost:8050/api/ai/check_position',
            json=payload,
            timeout=60
        )
        
        if resp.status_code != 200:
            return {'display': 'block'}, info_line, '', {'display': 'none'}, {'display': 'block'}, '', f'❌ Chyba API: {resp.status_code}', '', dash.no_update, dash.no_update
        
        result = resp.json()
        
        if 'error' in result:
            return {'display': 'block'}, info_line, '', {'display': 'none'}, {'display': 'block'}, '', f'❌ {result["error"]}', '', dash.no_update, dash.no_update
        
        # Format result
        action = result.get('action', 'HOLD')
        new_sl = result.get('new_sl')
        new_tp = result.get('new_tp')
        reason = result.get('reason', '')
        
        action_text = f"Action: {action}"
        if action == 'MOVE_SL' and new_sl:
            action_text += f" | New SL: ${new_sl:.2f}"
        elif action == 'MOVE_TP' and new_tp:
            action_text += f" | New TP: ${new_tp:.2f}"
        
        # Build action buttons based on action type
        action_buttons = []
        if action in ('MOVE_SL', 'MOVE_TP'):
            action_buttons.append(
                html.Button('✔ Apply', id='ai-check-apply-btn', n_clicks=0,
                           style={'padding': '8px 20px', 'background': '#4caf50',
                                  'border': 'none', 'borderRadius': '5px', 'color': 'white',
                                  'cursor': 'pointer', 'marginRight': '10px'})
            )
        elif action == 'CLOSE':
            action_buttons.append(
                html.Button('✖ Close Position', id='ai-check-close-btn', n_clicks=0,
                           style={'padding': '8px 20px', 'background': '#ef5350',
                                  'border': 'none', 'borderRadius': '5px', 'color': 'white',
                                  'cursor': 'pointer', 'marginRight': '10px'})
            )
        
        action_buttons.append(
            html.Button('❌ Dismiss', id='ai-check-dismiss-btn', n_clicks=0,
                       style={'padding': '8px 20px', 'background': '#666',
                              'border': 'none', 'borderRadius': '5px', 'color': 'white',
                              'cursor': 'pointer'})
        )
        
        state_data = {
            'visible': True,
            'loading': False,
            'result': result,
            'error': None,
            'trade': {'trade_id': trade_id, 'entry': entry, 'sl': sl, 'tp': tp, 'symbol': trade_sym}
        }
        
        return ({'display': 'block'}, info_line, '', {'display': 'block'}, {'display': 'none'},
                action_text, reason, action_buttons, state_data, auto_primary)
        
    except Exception as e:
        import traceback
        log("ERROR", f"AI check position error: {e}\n{traceback.format_exc()}")
        return {'display': 'block'}, info_line, '', {'display': 'none'}, {'display': 'block'}, '', f'❌ {str(e)[:100]}', '', dash.no_update, dash.no_update


# ------------------------------------------------------------------
# AI CHECK POSITION: Apply button (MOVE_SL/MOVE_TP)
# ------------------------------------------------------------------
@app.callback(
    [Output('ai-check-response', 'style', allow_duplicate=True),
     Output('ai-check-state', 'data', allow_duplicate=True),
     Output('trade-refresh-store', 'data', allow_duplicate=True)],
    Input('ai-check-apply-btn', 'n_clicks'),
    State('ai-check-state', 'data'),
    prevent_initial_call=True
)
def ai_check_apply(n_clicks, state):
    if n_clicks == 0 or not state or not state.get('result'):
        return dash.no_update, dash.no_update, dash.no_update
    
    result = state['result']
    trade_info = state.get('trade', {})
    trade_id = trade_info.get('trade_id', '')
    action = result.get('action', '')
    
    if not trade_id:
        return dash.no_update, dash.no_update, dash.no_update
    
    try:
        import requests
        
        if action == 'MOVE_SL' and result.get('new_sl'):
            payload = {'sl': result['new_sl']}
        elif action == 'MOVE_TP' and result.get('new_tp'):
            payload = {'tp': result['new_tp']}
        else:
            return dash.no_update, dash.no_update, dash.no_update
        
        resp = requests.post(
            f'http://localhost:8050/api/trades/patch/{trade_id}',
            json=payload,
            timeout=10
        )
        
        # Refresh trades
        return {'display': 'none'}, {'visible': False, 'loading': False, 'result': None, 'error': None}, dash.no_update
        
    except Exception as e:
        return dash.no_update, dash.no_update, dash.no_update


# ------------------------------------------------------------------
# AI CHECK POSITION: Close button
# ------------------------------------------------------------------
@app.callback(
    [Output('ai-check-response', 'style', allow_duplicate=True),
     Output('ai-check-state', 'data', allow_duplicate=True),
     Output('trade-refresh-store', 'data', allow_duplicate=True)],
    Input('ai-check-close-btn', 'n_clicks'),
    State('ai-check-state', 'data'),
    prevent_initial_call=True
)
def ai_check_close(n_clicks, state):
    if n_clicks == 0 or not state or not state.get('trade'):
        return dash.no_update, dash.no_update, dash.no_update
    
    trade_info = state.get('trade', {})
    trade_id = trade_info.get('trade_id', '')
    
    if not trade_id:
        return dash.no_update, dash.no_update, dash.no_update
    
    try:
        import requests
        
        resp = requests.post(
            f'http://localhost:8050/api/trades/close/{trade_id}',
            timeout=10
        )
        
        return {'display': 'none'}, {'visible': False, 'loading': False, 'result': None, 'error': None}, dash.no_update
        
    except Exception as e:
        return dash.no_update, dash.no_update, dash.no_update


@app.callback(
    [Output('ai-check-response', 'style', allow_duplicate=True),
     Output('ai-check-state', 'data', allow_duplicate=True)],
    Input('ai-check-dismiss-btn', 'n_clicks'),
    State('ai-check-state', 'data'),
    prevent_initial_call=True
)
def ai_check_dismiss(n_clicks, state):
    if n_clicks == 0:
        return dash.no_update, dash.no_update
    return {'display': 'none'}, {'visible': False, 'loading': False, 'result': None, 'error': None}


# ------------------------------------------------------------------
# AI: scroll to Check Position section
# ------------------------------------------------------------------
app.clientside_callback(
    """
    function(triggerData) {
        if (triggerData && triggerData.triggered) {
            setTimeout(function() {
                var el = document.getElementById('ai-check-section');
                if (el) {
                    el.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }
            }, 100);
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output('ai-check-trigger', 'data', allow_duplicate=True),
    Input('ai-check-trigger', 'data'),
    prevent_initial_call=True
)


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
     Output('trade-refresh-store', 'data', allow_duplicate=True),
     Output('trade-debug-store', 'data', allow_duplicate=True)],
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
     State('trade-refresh-store', 'data')],
    prevent_initial_call=True
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
    Output('positions-table', 'children'),
    [Input('positions-update-interval', 'n_intervals'),
     Input('trade-refresh-store', 'data'),
     Input('refresh-positions-btn', 'n_clicks')],
    prevent_initial_call='initial_duplicate'
)
def update_positions_table(n, _refresh, _btn):
    try:
        if not ib_gateway.is_connected():
            return html.Div('Not connected', style={'color': '#888'})

        positions = ib_gateway.get_positions() or []
        open_trades_list = trade_tracker.get_open_trades()

        if not positions and not open_trades_list:
            return html.Div('Žádné otevřené pozice', style={'color': '#888'})

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
                    
                    entry_t  = trade_tracker.fmt_time(tt.get('entry_time'))
                    sl_txt   = fmt_price(tt['sl'], asset_type) if tt.get('sl') else '–'
                    tp_txt   = fmt_price(tt['tp'], asset_type) if tt.get('tp') else '–'
                    trade_id = str(tt.get('id', '')) or f'pending_{sym}_{tt.get("entry_time", "unknown")}'
                    
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
                            html.Span([
                                html.Button('🤖 Check', id={'type': 'ai-check-pos-btn', 'trade_id': trade_id},
                                            n_clicks=0,
                                            style={'padding': '4px 8px', 'background': '#667eea',
                                                   'border': 'none', 'borderRadius': '4px',
                                                   'color': 'white', 'cursor': 'pointer',
                                                   'fontSize': '11px', 'marginRight': '4px'}),
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
                            ])
                        ),
                    ]))
            else:
                # Position without TT metadata
                _at = pos.get('asset_type', 'STOCK')
                _pnl_c = '#26a69a' if pos['unrealized_pnl'] >= 0 else '#ef5350'
                rows.append(html.Tr([
                    html.Td(f"{sym} ({_at})", style={'fontWeight': 'bold'}),
                    html.Td('LONG' if pos['position'] > 0 else 'SHORT',
                            style={'color': '#00d4ff'}),
                    html.Td(abs(pos['position'])),
                    html.Td(fmt_price(pos['avg_cost'], _at)),
                    html.Td(fmt_price(pos['market_value'], _at)),
                    html.Td(f"${pos['unrealized_pnl']:.2f} ({pos['unrealized_pnl_pct']:.2f}%)",
                            style={'color': _pnl_c, 'fontWeight': 'bold'}),
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
                trade_id = str(tt.get('id', '')) or f'pending_{sym}_{tt.get("entry_time", "unknown")}'
                
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
                        html.Span([
                            html.Button('🤖 Check', id={'type': 'ai-check-pos-btn', 'trade_id': trade_id},
                                        n_clicks=0,
                                        style={'padding': '4px 8px', 'background': '#667eea',
                                               'border': 'none', 'borderRadius': '4px',
                                               'color': 'white', 'cursor': 'pointer',
                                               'fontSize': '11px', 'marginRight': '4px'}),
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
                        ])
                    ),
                ]))

        return html.Table([
            html.Thead(html.Tr([
                html.Th('Symbol'), html.Th('Side'), html.Th('Qty'),
                html.Th('Avg Cost'), html.Th('Market Value'), html.Th('P&L'),
                html.Th('Vstup'), html.Th('SL'), html.Th('TP'), html.Th('')
            ])),
            html.Tbody(rows)
        ], style={'width': '100%', 'borderCollapse': 'collapse'})
    except Exception as e:
        import traceback
        log("ERROR", f"positions-table callback error: {e}\n{traceback.format_exc()}")
        return html.Div(f'Chyba: {str(e)[:200]}', style={'color': '#ef5350'})


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
    Output('tick-sync-dummy', 'data'),
    Input('trade-debug-store', 'data'),
    prevent_initial_call=True
)


# ========== CLIENTSIDE CALLBACKS ==========

app.clientside_callback(
    """function(n){if(n>0&&window.lwcDebug)window.lwcDebug('BTN','Load Chart n='+n+' - cekam na Python/IB...');return n;}""",
    Output('chart-trigger-store', 'data', allow_duplicate=True), Input('load-chart-btn', 'n_clicks'),
    prevent_initial_call=True
)

app.clientside_callback(
    """function(n){if(n>0&&window.lwcDebug)window.lwcDebug('BTN','Load Chart2 n='+n+' - cekam na Python/IB...');return n;}""",
    Output('chart2-trigger-store', 'data', allow_duplicate=True), Input('load-chart2-btn', 'n_clicks'),
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
    [Output('tick-enabled-store', 'data', allow_duplicate=True),
     Output('tick-toggle-btn', 'children', allow_duplicate=True),
     Output('tick-toggle-btn', 'className', allow_duplicate=True)],
    Input('tick-toggle-btn', 'n_clicks'),
    State('tick-enabled-store', 'data'),
    prevent_initial_call=True
)

# Synchronize tick state to JS when Python changes tick-enabled-store (e.g., auto-enable on chart load)
app.clientside_callback(
    """
    function(enabled) {
        if (window.lwcManager) window.lwcManager.setTickEnabled(!!enabled);
        return window.dash_clientside.no_update;
    }
    """,
    Output('tick-sync-dummy', 'data', allow_duplicate=True),
    Input('tick-enabled-store', 'data'),
    prevent_initial_call=True
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

# Phase 3: Chart 2 - update active-tf2-store when tf2 buttons clicked
app.clientside_callback(
    """
    function(tf2_1m,tf2_5m,tf2_15m,tf2_30m,tf2_1h,tf2_1d){
        var ctx=dash_clientside.callback_context;
        if(!ctx.triggered||ctx.triggered.length===0)return window.dash_clientside.no_update;
        var tid=ctx.triggered_id||ctx.triggered[0].prop_id.split('.')[0];
        return tid;
    }
    """,
    Output('active-tf2-store', 'data'),
    [Input('tf2-1m','n_clicks'),Input('tf2-5m','n_clicks'),Input('tf2-15m','n_clicks'),
     Input('tf2-30m','n_clicks'),Input('tf2-1h','n_clicks'),Input('tf2-1d','n_clicks')]
)

# Phase 3: Chart 2 - update tf2 button classNames based on active-tf2-store
app.clientside_callback(
    """
    function(activeTf2){
        var ids=['tf2-1m','tf2-5m','tf2-15m','tf2-30m','tf2-1h','tf2-1d'];
        return ids.map(function(id){return id===activeTf2?'tf-btn tf-active':'tf-btn';});
    }
    """,
    [Output('tf2-1m','className'),Output('tf2-5m','className'),Output('tf2-15m','className'),
     Output('tf2-30m','className'),Output('tf2-1h','className'),Output('tf2-1d','className')],
    Input('active-tf2-store','data')
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
    Output('chart-trigger-store', 'data', allow_duplicate=True), Input('chart-data-store', 'data'),
    prevent_initial_call=True
)

# Phase 3: Chart 2 clientside callback - feeds chart2-data-store to lwcManager2.loadData()
app.clientside_callback(
    """
    function(storeData){
        var d=window.lwcDebug||function(){};
        d('CB2','=== Chart2 clientside callback ===');
        if(!storeData){d('CB2','storeData NULL -> no_update');return window.dash_clientside.no_update;}
        if(!storeData.bars||storeData.bars.length===0){d('CB2','bars prazdne -> no_update');return window.dash_clientside.no_update;}
        d('CB2','symbol='+storeData.symbol+' tf='+storeData.timeframe+' baru='+storeData.bars.length);
        if(window.lwcManager2){d('CB2','volam lwcManager2.loadData()');window.lwcManager2.loadData(storeData);}
        else{var a=0,r=setInterval(function(){a++;if(window.lwcManager2){window.lwcManager2.loadData(storeData);clearInterval(r);}else if(a>20){d('ERR','lwcManager2 nenalezen!');clearInterval(r);}},200);}
        return storeData.symbol||'ok';
    }
    """,
    Output('chart2-trigger-store', 'data', allow_duplicate=True), Input('chart2-data-store', 'data'),
    prevent_initial_call=True
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
    Output('deep-load-finished-trigger', 'data', allow_duplicate=True), Input('chart-append-store', 'data'),
    prevent_initial_call=True
)

# Phase 3: Chart 2 prepend/append callback - feeds chart2-append-store to lwcManager2.prependData()
app.clientside_callback(
    """
    function(appendData){
        var d=window.lwcDebug||function(){};
        d('CB2-APPEND','=== Chart2 append callback ===');
        if(!appendData){d('CB2-APPEND','appendData NULL -> no_update');return window.dash_clientside.no_update;}
        if(!appendData.bars||appendData.bars.length===0){d('CB2-APPEND','append bars prazdne -> no_update');return window.dash_clientside.no_update;}
        d('CB2-APPEND','symbol='+appendData.symbol+' tf='+appendData.timeframe+' baru='+appendData.bars.length);
        if(window.lwcManager2){d('CB2-APPEND','volam lwcManager2.prependData()');window.lwcManager2.prependData(appendData);}
        else{var a=0,r=setInterval(function(){a++;if(window.lwcManager2){window.lwcManager2.prependData(appendData);clearInterval(r);}else if(a>20){d('ERR','lwcManager2 nenalezen!');clearInterval(r);}},200);}
        return appendData.symbol||'ok';
    }
    """,
    Output('indicator2-settings-store', 'data'), Input('chart2-append-store', 'data'),
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
    Output('active-tf-store', 'data', allow_duplicate=True),
    [Input('trades-refresh-interval', 'n_intervals'),
     Input('trade-refresh-store', 'data')],
    [State('chart-data-store', 'data'),
     State('symbol-input', 'value'),
     State('asset-type-select', 'value')],
    prevent_initial_call=True
)

# Chart 2 trade lines (3.11 - trade lines per block)
app.clientside_callback(
    """
    function(n, refreshCounter, chart2Data, symbolInput2, assetTypeInput2) {
        var d = window.lwcDebug || function() {};
        var sym = ((chart2Data && chart2Data.symbol) || symbolInput2 || 'EURUSD').toUpperCase();
        var assetType = ((chart2Data && chart2Data.asset_type) || assetTypeInput2 || 'FOREX').toUpperCase();
        if (!sym) return window.dash_clientside.no_update;

        fetch('/api/trades/active_lines?symbol=' + encodeURIComponent(sym) + '&asset_type=' + encodeURIComponent(assetType))
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (window.lwcManager2 && window.lwcManager2.setTradeLines) {
                    window.lwcManager2.setTradeLines(data || []);
                    d('TRADE2', 'Chart2 trade lines refreshed: ' + sym + ' (' + assetType + ') -> ' + ((data && data.length) || 0));
                } else {
                    d('ERR', 'lwcManager2.setTradeLines() neexistuje');
                }
            })
            .catch(function(e) {
                d('ERR', 'TRADE2 lines fetch error: ' + e);
                if (window.lwcManager2 && window.lwcManager2.setTradeLines) {
                    window.lwcManager2.setTradeLines([]);
                }
            });

        return window.dash_clientside.no_update;
    }
    """,
    Output('active-tf2-store', 'data', allow_duplicate=True),
    [Input('trades-refresh-interval', 'n_intervals'),
     Input('trade-refresh-store', 'data')],
    [State('chart2-data-store', 'data'),
     State('symbol-input-2', 'value'),
     State('asset-type-select-2', 'value')],
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


# Chart 2 price update (3.4 - tick per block)
@app.callback(
    [Output('price-display-2', 'children'),
     Output('price-change-display-2', 'children')],
    Input('price-update-interval', 'n_intervals'),
    [State('symbol-input-2', 'value'),
     State('asset-type-select-2', 'value')]
)
def update_price_display_2(n, symbol, asset_type):
    """Update price display for Chart 2 - independent per-block tick (3.4)."""
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
    Output('qty-custom', 'value', allow_duplicate=True),
    [Input('qty-1','n_clicks'),Input('qty-5','n_clicks'),
     Input('qty-10','n_clicks'),Input('qty-25','n_clicks'),Input('qty-100','n_clicks')],
    prevent_initial_call=True
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
            #lwc-container-2 { display: block; width: 100%; height: 500px; }
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

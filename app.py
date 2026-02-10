"""IB Trading Platform - Main Dash Application

Professional trading platform with real-time market data,
order execution, positions tracking, and beautiful UI.

Author: Perplexity AI Assistant
Version: 1.0.0
"""

import dash
from dash import dcc, html, Input, Output, State, dash_table
import plotly.graph_objs as go
from datetime import datetime
import pandas as pd
import time
from ib_connector import IBConnector
import config

# Initialize Dash app
app = dash.Dash(
    __name__,
    title="IB Trading Platform",
    update_title=None,
    suppress_callback_exceptions=True
)

# Initialize IB connector
ib = IBConnector()

# Global state
app_state = {
    'current_symbol': 'AAPL',
    'current_timeframe': '5 mins',
    'chart_data': [],
    'last_price': 0,
    'price_change': 0,
    'price_change_pct': 0
}

# ========== LAYOUT ==========

app.layout = html.Div([
    # Header
    html.Div([
        html.H1("🚀 IB Trading Platform v1.0", 
                style={'display': 'inline-block', 'margin': 0, 'color': '#00d4ff'}),
        html.Div(id='connection-status', 
                 style={'display': 'inline-block', 'float': 'right', 'fontSize': 18})
    ], style={
        'padding': '20px',
        'background': 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
        'borderRadius': '10px',
        'marginBottom': '20px'
    }),
    
    # Account info bar
    html.Div([
        html.Div([
            html.Span("💼 Account: ", style={'fontWeight': 'bold'}),
            html.Span(id='account-id', children='Connecting...')
        ], style={'display': 'inline-block', 'marginRight': '30px'}),
        
        html.Div([
            html.Span("💰 Balance: ", style={'fontWeight': 'bold'}),
            html.Span(id='account-balance', children='$0.00')
        ], style={'display': 'inline-block', 'marginRight': '30px'}),
        
        html.Div([
            html.Span("📈 Buying Power: ", style={'fontWeight': 'bold'}),
            html.Span(id='buying-power', children='$0.00')
        ], style={'display': 'inline-block'})
    ], style={
        'padding': '15px',
        'background': '#2d2d3a',
        'borderRadius': '8px',
        'marginBottom': '20px',
        'fontSize': '16px'
    }),
    
    # Symbol & Price info
    html.Div([
        html.Div([
            html.Label('Symbol:', style={'marginRight': '10px', 'fontWeight': 'bold'}),
            dcc.Input(
                id='symbol-input',
                type='text',
                value='AAPL',
                style={
                    'width': '150px',
                    'padding': '8px',
                    'borderRadius': '5px',
                    'border': '2px solid #667eea',
                    'background': '#1e1e2e',
                    'color': 'white',
                    'fontSize': '16px'
                }
            ),
            html.Button(
                'Load Chart',
                id='load-chart-btn',
                n_clicks=0,
                style={
                    'marginLeft': '10px',
                    'padding': '8px 20px',
                    'background': 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
                    'border': 'none',
                    'borderRadius': '5px',
                    'color': 'white',
                    'cursor': 'pointer',
                    'fontWeight': 'bold'
                }
            )
        ], style={'display': 'inline-block', 'marginRight': '30px'}),
        
        html.Div([
            html.Span(id='price-display', 
                     children='Last: $0.00',
                     style={'fontSize': '20px', 'fontWeight': 'bold'}),
            html.Span(id='price-change-display',
                     children=' ▲ +$0.00 (+0.00%)',
                     style={'fontSize': '16px', 'marginLeft': '15px', 'color': '#26a69a'})
        ], style={'display': 'inline-block'})
    ], style={
        'padding': '15px',
        'background': '#2d2d3a',
        'borderRadius': '8px',
        'marginBottom': '20px'
    }),
    
    # Chart
    html.Div([
        # Timeframe selector
        html.Div([
            html.Button('1m', id='tf-1m', n_clicks=0, className='tf-btn'),
            html.Button('5m', id='tf-5m', n_clicks=0, className='tf-btn tf-active'),
            html.Button('15m', id='tf-15m', n_clicks=0, className='tf-btn'),
            html.Button('30m', id='tf-30m', n_clicks=0, className='tf-btn'),
            html.Button('1h', id='tf-1h', n_clicks=0, className='tf-btn'),
            html.Button('1D', id='tf-1d', n_clicks=0, className='tf-btn')
        ], style={'marginBottom': '10px'}),
        
        dcc.Graph(
            id='price-chart',
            config={'displayModeBar': False},
            style={'height': '500px'}
        )
    ], style={
        'padding': '20px',
        'background': '#2d2d3a',
        'borderRadius': '8px',
        'marginBottom': '20px'
    }),
    
    # Order Entry Panel
    html.Div([
        html.H3('📤 Order Entry', style={'marginBottom': '15px'}),
        
        html.Div([
            html.Label('Quantity:', style={'marginRight': '10px', 'fontWeight': 'bold'}),
            html.Button('1', id='qty-1', n_clicks=0, className='qty-btn'),
            html.Button('5', id='qty-5', n_clicks=0, className='qty-btn'),
            html.Button('10', id='qty-10', n_clicks=0, className='qty-btn'),
            html.Button('25', id='qty-25', n_clicks=0, className='qty-btn'),
            html.Button('100', id='qty-100', n_clicks=0, className='qty-btn'),
            dcc.Input(
                id='qty-custom',
                type='number',
                value=1,
                min=1,
                style={
                    'width': '80px',
                    'marginLeft': '10px',
                    'padding': '8px',
                    'borderRadius': '5px',
                    'border': '2px solid #667eea',
                    'background': '#1e1e2e',
                    'color': 'white'
                }
            )
        ], style={'marginBottom': '15px'}),
        
        html.Div([
            html.Button(
                '🟢 BUY MARKET',
                id='buy-btn',
                n_clicks=0,
                style={
                    'padding': '15px 40px',
                    'background': 'linear-gradient(135deg, #26a69a 0%, #1a7f6f 100%)',
                    'border': 'none',
                    'borderRadius': '8px',
                    'color': 'white',
                    'fontSize': '18px',
                    'fontWeight': 'bold',
                    'cursor': 'pointer',
                    'marginRight': '15px'
                }
            ),
            html.Button(
                '🔴 SELL MARKET',
                id='sell-btn',
                n_clicks=0,
                style={
                    'padding': '15px 40px',
                    'background': 'linear-gradient(135deg, #ef5350 0%, #c62828 100%)',
                    'border': 'none',
                    'borderRadius': '8px',
                    'color': 'white',
                    'fontSize': '18px',
                    'fontWeight': 'bold',
                    'cursor': 'pointer'
                }
            )
        ]),
        
        html.Div(id='order-feedback', style={'marginTop': '15px', 'fontSize': '16px'})
    ], style={
        'padding': '20px',
        'background': '#2d2d3a',
        'borderRadius': '8px',
        'marginBottom': '20px'
    }),
    
    # Positions Panel
    html.Div([
        html.H3('📊 Open Positions (Real-time P&L)', style={'marginBottom': '15px'}),
        html.Div(id='positions-table')
    ], style={
        'padding': '20px',
        'background': '#2d2d3a',
        'borderRadius': '8px',
        'marginBottom': '20px'
    }),
    
    # Order History
    html.Div([
        html.H3('📋 Recent Orders', style={'marginBottom': '15px'}),
        html.Div(id='orders-table')
    ], style={
        'padding': '20px',
        'background': '#2d2d3a',
        'borderRadius': '8px',
        'marginBottom': '20px'
    }),
    
    # Intervals for real-time updates
    dcc.Interval(id='price-update-interval', interval=1000, n_intervals=0),
    dcc.Interval(id='positions-update-interval', interval=2000, n_intervals=0),
    dcc.Interval(id='connection-check-interval', interval=5000, n_intervals=0),
    
    # Hidden div for storing state
    html.Div(id='hidden-state', style={'display': 'none'})
    
], style={
    'maxWidth': '1400px',
    'margin': '0 auto',
    'padding': '20px',
    'background': '#1e1e2e',
    'minHeight': '100vh',
    'color': 'white',
    'fontFamily': 'Arial, sans-serif'
})

# ========== CALLBACKS ==========

# Connection status
@app.callback(
    Output('connection-status', 'children'),
    Input('connection-check-interval', 'n_intervals')
)
def update_connection_status(n):
    if ib.is_connected():
        return html.Span([
            html.Span('⬤', style={'color': '#26a69a', 'marginRight': '5px'}),
            html.Span('Connected to IB Gateway')
        ])
    else:
        return html.Span([
            html.Span('⬤', style={'color': '#ef5350', 'marginRight': '5px'}),
            html.Span('Disconnected - Check IB Gateway')
        ])

# Account info
@app.callback(
    [Output('account-id', 'children'),
     Output('account-balance', 'children'),
     Output('buying-power', 'children')],
    Input('connection-check-interval', 'n_intervals')
)
def update_account_info(n):
    if not ib.is_connected():
        return 'Not Connected', '$0.00', '$0.00'
    
    account_data = ib.get_account_info()
    account_id = account_data.get('account_id', 'N/A')
    balance = account_data.get('net_liquidation', 0)
    buying_power = account_data.get('buying_power', 0)
    
    return (
        account_id,
        f"${balance:,.2f}",
        f"${buying_power:,.2f}"
    )

# Load chart
@app.callback(
    Output('price-chart', 'figure'),
    [Input('load-chart-btn', 'n_clicks'),
     Input('tf-1m', 'n_clicks'),
     Input('tf-5m', 'n_clicks'),
     Input('tf-15m', 'n_clicks'),
     Input('tf-30m', 'n_clicks'),
     Input('tf-1h', 'n_clicks'),
     Input('tf-1d', 'n_clicks')],
    State('symbol-input', 'value')
)
def update_chart(load_clicks, tf1, tf5, tf15, tf30, tf1h, tf1d, symbol):
    ctx = dash.callback_context
    
    # Determine timeframe
    if ctx.triggered:
        button_id = ctx.triggered[0]['prop_id'].split('.')[0]
        timeframe_map = {
            'tf-1m': '1 min',
            'tf-5m': '5 mins',
            'tf-15m': '15 mins',
            'tf-30m': '30 mins',
            'tf-1h': '1 hour',
            'tf-1d': '1 day'
        }
        app_state['current_timeframe'] = timeframe_map.get(button_id, '5 mins')
    
    if not symbol:
        symbol = 'AAPL'
    
    app_state['current_symbol'] = symbol
    
    # Get historical data
    bars = ib.get_historical_data(symbol, '1 D', app_state['current_timeframe'])
    
    if not bars:
        # Return empty chart
        fig = go.Figure()
        fig.update_layout(
            template='plotly_dark',
            paper_bgcolor='#1e1e2e',
            plot_bgcolor='#2d2d3a',
            title=f'{symbol} - No data available',
            xaxis_title='Time',
            yaxis_title='Price ($)'
        )
        return fig
    
    # Create candlestick chart
    fig = go.Figure(data=[go.Candlestick(
        x=[bar['time'] for bar in bars],
        open=[bar['open'] for bar in bars],
        high=[bar['high'] for bar in bars],
        low=[bar['low'] for bar in bars],
        close=[bar['close'] for bar in bars],
        increasing_line_color='#26a69a',
        decreasing_line_color='#ef5350'
    )])
    
    fig.update_layout(
        template='plotly_dark',
        paper_bgcolor='#1e1e2e',
        plot_bgcolor='#2d2d3a',
        title=f'{symbol} - {app_state["current_timeframe"]} Chart',
        xaxis_title='Time',
        yaxis_title='Price ($)',
        xaxis_rangeslider_visible=False,
        height=500,
        margin=dict(l=50, r=50, t=50, b=50)
    )
    
    return fig

# Update price display
@app.callback(
    [Output('price-display', 'children'),
     Output('price-change-display', 'children')],
    Input('price-update-interval', 'n_intervals'),
    State('symbol-input', 'value')
)
def update_price_display(n, symbol):
    if not symbol or not ib.is_connected():
        return 'Last: $0.00', ' ▲ +$0.00 (+0.00%)'
    
    ticker = ib.get_ticker(symbol)
    if not ticker:
        return f'Last: $0.00', ' ▲ +$0.00 (+0.00%)'
    
    last_price = ticker.get('last', 0)
    prev_close = ticker.get('close', last_price)
    
    change = last_price - prev_close
    change_pct = (change / prev_close * 100) if prev_close > 0 else 0
    
    arrow = '▲' if change >= 0 else '▼'
    color = '#26a69a' if change >= 0 else '#ef5350'
    sign = '+' if change >= 0 else ''
    
    return (
        f'Last: ${last_price:.2f}',
        html.Span(
            f' {arrow} {sign}${change:.2f} ({sign}{change_pct:.2f}%)',
            style={'color': color}
        )
    )

# Quantity button clicks
@app.callback(
    Output('qty-custom', 'value'),
    [Input('qty-1', 'n_clicks'),
     Input('qty-5', 'n_clicks'),
     Input('qty-10', 'n_clicks'),
     Input('qty-25', 'n_clicks'),
     Input('qty-100', 'n_clicks')]
)
def update_quantity(q1, q5, q10, q25, q100):
    ctx = dash.callback_context
    if not ctx.triggered:
        return 1
    
    button_id = ctx.triggered[0]['prop_id'].split('.')[0]
    qty_map = {
        'qty-1': 1,
        'qty-5': 5,
        'qty-10': 10,
        'qty-25': 25,
        'qty-100': 100
    }
    return qty_map.get(button_id, 1)

# Place order (BUY/SELL)
@app.callback(
    Output('order-feedback', 'children'),
    [Input('buy-btn', 'n_clicks'),
     Input('sell-btn', 'n_clicks')],
    [State('symbol-input', 'value'),
     State('qty-custom', 'value')]
)
def place_order(buy_clicks, sell_clicks, symbol, quantity):
    ctx = dash.callback_context
    if not ctx.triggered:
        return ''
    
    button_id = ctx.triggered[0]['prop_id'].split('.')[0]
    
    if button_id == 'buy-btn' and buy_clicks > 0:
        action = 'BUY'
        color = '#26a69a'
    elif button_id == 'sell-btn' and sell_clicks > 0:
        action = 'SELL'
        color = '#ef5350'
    else:
        return ''
    
    if not ib.is_connected():
        return html.Div(
            '❌ Not connected to IB Gateway!',
            style={'color': '#ef5350', 'fontWeight': 'bold'}
        )
    
    # Place order
    result = ib.place_market_order(symbol, action, quantity)
    
    if result['success']:
        return html.Div(
            f'✅ Order placed: {action} {quantity} {symbol} @ Market',
            style={'color': color, 'fontWeight': 'bold'}
        )
    else:
        return html.Div(
            f'❌ Order failed: {result["error"]}',
            style={'color': '#ef5350', 'fontWeight': 'bold'}
        )

# Update positions table
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
    
    # Create table data
    table_data = []
    for pos in positions:
        pnl_color = '#26a69a' if pos['unrealized_pnl'] >= 0 else '#ef5350'
        side = 'LONG' if pos['position'] > 0 else 'SHORT'
        
        table_data.append(html.Tr([
            html.Td(pos['symbol'], style={'fontWeight': 'bold'}),
            html.Td(side, style={'color': '#00d4ff'}),
            html.Td(abs(pos['position'])),
            html.Td(f"${pos['avg_cost']:.2f}"),
            html.Td(f"${pos['market_value']:.2f}"),
            html.Td(
                f"${pos['unrealized_pnl']:.2f} ({pos['unrealized_pnl_pct']:.2f}%)",
                style={'color': pnl_color, 'fontWeight': 'bold'}
            )
        ]))
    
    table = html.Table([
        html.Thead(html.Tr([
            html.Th('Symbol'),
            html.Th('Side'),
            html.Th('Qty'),
            html.Th('Avg Cost'),
            html.Th('Market Value'),
            html.Th('P&L')
        ])),
        html.Tbody(table_data)
    ], style={'width': '100%', 'borderCollapse': 'collapse'})
    
    return table

# Update orders table
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
    
    # Create table data
    table_data = []
    for order in orders:
        status_icon = {
            'Filled': '✅',
            'Submitted': '⏳',
            'Cancelled': '❌',
            'PendingSubmit': '🕒'
        }.get(order['status'], '❔')
        
        status_color = {
            'Filled': '#26a69a',
            'Submitted': '#ffa726',
            'Cancelled': '#ef5350',
            'PendingSubmit': '#42a5f5'
        }.get(order['status'], '#888')
        
        table_data.append(html.Tr([
            html.Td(order['time']),
            html.Td(f"{order['action']} {order['quantity']} {order['symbol']}"),
            html.Td(f"@ {order['price']}"),
            html.Td(
                f"{status_icon} {order['status']}",
                style={'color': status_color, 'fontWeight': 'bold'}
            )
        ]))
    
    table = html.Table([
        html.Thead(html.Tr([
            html.Th('Time'),
            html.Th('Order'),
            html.Th('Price'),
            html.Th('Status')
        ])),
        html.Tbody(table_data)
    ], style={'width': '100%', 'borderCollapse': 'collapse'})
    
    return table

# ========== CUSTOM CSS ==========

app.index_string = '''
<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
        <style>
            body {
                margin: 0;
                padding: 0;
                background: #1e1e2e;
            }
            .tf-btn, .qty-btn {
                padding: 8px 15px;
                margin: 0 5px;
                background: #2d2d3a;
                border: 2px solid #667eea;
                border-radius: 5px;
                color: white;
                cursor: pointer;
                font-weight: bold;
            }
            .tf-btn:hover, .qty-btn:hover {
                background: #667eea;
            }
            .tf-active {
                background: #667eea;
            }
            table {
                border-collapse: collapse;
                width: 100%;
            }
            th, td {
                padding: 12px;
                text-align: left;
                border-bottom: 1px solid #3d3d4a;
            }
            th {
                background: #3d3d4a;
                font-weight: bold;
                color: #00d4ff;
            }
            tr:hover {
                background: #3d3d4a;
            }
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
    print("🚀 Starting IB Trading Platform...")
    print(f"Connecting to IB Gateway on {config.IB_HOST}:{config.IB_PORT}")
    
    # Connect to IB
    if ib.connect():
        print("✅ Connected to IB Gateway!")
    else:
        print("❌ Failed to connect - check IB Gateway is running")
    
    print("Opening web browser at http://localhost:8050")
    print("Press Ctrl+C to stop\n")
    
    app.run_server(debug=True, host='0.0.0.0', port=8050)

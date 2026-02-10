"""IB Trading Platform - Simple Flask Version (NO DASH)

Simplified version using pure Flask + vanilla JavaScript
to test if the issue is with Dash/Plotly or IB backend.

Author: Perplexity AI Assistant
Version: 1.0.0-simple
"""

from flask import Flask, render_template_string, jsonify, request
from ib_connector import IBConnector
import config
import threading
import time

app = Flask(__name__)
ib = IBConnector()

# HTML Template (embedded)
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>IB Trading Platform (Simple)</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: Arial, sans-serif;
            background: #1e1e2e;
            color: white;
            padding: 20px;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 20px;
            border-radius: 10px;
            margin-bottom: 20px;
        }
        .panel {
            background: #2d2d3a;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 20px;
        }
        .status {
            display: inline-block;
            width: 12px;
            height: 12px;
            border-radius: 50%;
            margin-right: 8px;
        }
        .status.connected { background: #26a69a; }
        .status.disconnected { background: #ef5350; }
        button {
            padding: 15px 30px;
            border: none;
            border-radius: 8px;
            font-size: 18px;
            font-weight: bold;
            cursor: pointer;
            margin: 5px;
        }
        .btn-buy {
            background: linear-gradient(135deg, #26a69a 0%, #1a7f6f 100%);
            color: white;
        }
        .btn-sell {
            background: linear-gradient(135deg, #ef5350 0%, #c62828 100%);
            color: white;
        }
        .btn-qty {
            background: #667eea;
            color: white;
            padding: 8px 15px;
            font-size: 14px;
        }
        input {
            padding: 10px;
            border: 2px solid #667eea;
            border-radius: 5px;
            background: #1e1e2e;
            color: white;
            font-size: 16px;
            margin: 5px;
        }
        table {
            width: 100%;
            border-collapse: collapse;
        }
        th, td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #3d3d4a;
        }
        th {
            background: #3d3d4a;
            color: #00d4ff;
        }
        .feedback {
            margin-top: 15px;
            padding: 10px;
            border-radius: 5px;
            font-weight: bold;
        }
        .feedback.success { background: #26a69a33; color: #26a69a; }
        .feedback.error { background: #ef535033; color: #ef5350; }
    </style>
</head>
<body>
    <div class="container">
        <!-- Header -->
        <div class="header">
            <h1>🚀 IB Trading Platform (Simple Version)</h1>
            <p id="connection-status">
                <span class="status disconnected"></span>
                Checking connection...
            </p>
        </div>

        <!-- Account Info -->
        <div class="panel">
            <h2>💼 Account Information</h2>
            <p>
                <strong>Account:</strong> <span id="account-id">Loading...</span> |
                <strong>Balance:</strong> <span id="balance">$0.00</span> |
                <strong>Buying Power:</strong> <span id="buying-power">$0.00</span>
            </p>
        </div>

        <!-- Order Entry -->
        <div class="panel">
            <h2>📤 Order Entry</h2>
            <div>
                <label><strong>Symbol:</strong></label>
                <input type="text" id="symbol" value="AAPL" style="width: 150px;">
            </div>
            <div style="margin-top: 15px;">
                <label><strong>Quantity:</strong></label>
                <button class="btn-qty" onclick="setQty(1)">1</button>
                <button class="btn-qty" onclick="setQty(5)">5</button>
                <button class="btn-qty" onclick="setQty(10)">10</button>
                <button class="btn-qty" onclick="setQty(25)">25</button>
                <button class="btn-qty" onclick="setQty(100)">100</button>
                <input type="number" id="quantity" value="1" min="1" style="width: 100px;">
            </div>
            <div style="margin-top: 20px;">
                <button class="btn-buy" onclick="placeOrder('BUY')">🟢 BUY MARKET</button>
                <button class="btn-sell" onclick="placeOrder('SELL')">🔴 SELL MARKET</button>
            </div>
            <div id="order-feedback"></div>
        </div>

        <!-- Positions -->
        <div class="panel">
            <h2>📊 Open Positions</h2>
            <div id="positions-container">
                <p style="color: #888;">Loading positions...</p>
            </div>
        </div>

        <!-- Orders -->
        <div class="panel">
            <h2>📋 Recent Orders</h2>
            <div id="orders-container">
                <p style="color: #888;">Loading orders...</p>
            </div>
        </div>
    </div>

    <script>
        // Update connection status
        function updateStatus() {
            fetch('/api/status')
                .then(r => r.json())
                .then(data => {
                    const statusEl = document.getElementById('connection-status');
                    if (data.connected) {
                        statusEl.innerHTML = '<span class="status connected"></span>Connected to IB Gateway';
                    } else {
                        statusEl.innerHTML = '<span class="status disconnected"></span>Disconnected';
                    }
                    
                    document.getElementById('account-id').textContent = data.account_id;
                    document.getElementById('balance').textContent = '$' + data.balance.toFixed(2);
                    document.getElementById('buying-power').textContent = '$' + data.buying_power.toFixed(2);
                });
        }

        // Update positions
        function updatePositions() {
            fetch('/api/positions')
                .then(r => r.json())
                .then(data => {
                    const container = document.getElementById('positions-container');
                    if (data.positions.length === 0) {
                        container.innerHTML = '<p style="color: #888;">No open positions</p>';
                        return;
                    }
                    
                    let html = '<table><thead><tr>';
                    html += '<th>Symbol</th><th>Side</th><th>Qty</th><th>Avg Cost</th><th>Market Value</th><th>P&L</th>';
                    html += '</tr></thead><tbody>';
                    
                    data.positions.forEach(pos => {
                        const pnlColor = pos.unrealized_pnl >= 0 ? '#26a69a' : '#ef5350';
                        const side = pos.position > 0 ? 'LONG' : 'SHORT';
                        html += '<tr>';
                        html += `<td><strong>${pos.symbol}</strong></td>`;
                        html += `<td style="color: #00d4ff;">${side}</td>`;
                        html += `<td>${Math.abs(pos.position)}</td>`;
                        html += `<td>$${pos.avg_cost.toFixed(2)}</td>`;
                        html += `<td>$${pos.market_value.toFixed(2)}</td>`;
                        html += `<td style="color: ${pnlColor}; font-weight: bold;">$${pos.unrealized_pnl.toFixed(2)} (${pos.unrealized_pnl_pct.toFixed(2)}%)</td>`;
                        html += '</tr>';
                    });
                    
                    html += '</tbody></table>';
                    container.innerHTML = html;
                });
        }

        // Update orders
        function updateOrders() {
            fetch('/api/orders')
                .then(r => r.json())
                .then(data => {
                    const container = document.getElementById('orders-container');
                    if (data.orders.length === 0) {
                        container.innerHTML = '<p style="color: #888;">No recent orders</p>';
                        return;
                    }
                    
                    let html = '<table><thead><tr>';
                    html += '<th>Time</th><th>Order</th><th>Price</th><th>Status</th>';
                    html += '</tr></thead><tbody>';
                    
                    data.orders.forEach(order => {
                        const statusIcons = {
                            'Filled': '✅',
                            'Submitted': '⏳',
                            'Cancelled': '❌',
                            'PendingSubmit': '🕒'
                        };
                        const statusColors = {
                            'Filled': '#26a69a',
                            'Submitted': '#ffa726',
                            'Cancelled': '#ef5350',
                            'PendingSubmit': '#42a5f5'
                        };
                        const icon = statusIcons[order.status] || '❓';
                        const color = statusColors[order.status] || '#888';
                        
                        html += '<tr>';
                        html += `<td>${order.time}</td>`;
                        html += `<td>${order.action} ${order.quantity} ${order.symbol}</td>`;
                        html += `<td>@ ${order.price}</td>`;
                        html += `<td style="color: ${color}; font-weight: bold;">${icon} ${order.status}</td>`;
                        html += '</tr>';
                    });
                    
                    html += '</tbody></table>';
                    container.innerHTML = html;
                });
        }

        // Set quantity
        function setQty(qty) {
            document.getElementById('quantity').value = qty;
        }

        // Place order
        function placeOrder(action) {
            const symbol = document.getElementById('symbol').value;
            const quantity = parseInt(document.getElementById('quantity').value);
            const feedbackEl = document.getElementById('order-feedback');
            
            if (!symbol) {
                feedbackEl.className = 'feedback error';
                feedbackEl.textContent = '❌ Please enter a symbol';
                return;
            }
            
            feedbackEl.textContent = '⏳ Placing order...';
            feedbackEl.className = 'feedback';
            
            fetch('/api/place_order', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({symbol, action, quantity})
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    feedbackEl.className = 'feedback success';
                    feedbackEl.textContent = `✅ Order placed: ${action} ${quantity} ${symbol} @ Market`;
                    // Update positions/orders after 2 seconds
                    setTimeout(() => {
                        updatePositions();
                        updateOrders();
                    }, 2000);
                } else {
                    feedbackEl.className = 'feedback error';
                    feedbackEl.textContent = `❌ Order failed: ${data.error}`;
                }
            })
            .catch(err => {
                feedbackEl.className = 'feedback error';
                feedbackEl.textContent = '❌ Connection error';
            });
        }

        // Initial load
        updateStatus();
        updatePositions();
        updateOrders();

        // Auto-refresh
        setInterval(updateStatus, 5000);
        setInterval(updatePositions, 3000);
        setInterval(updateOrders, 5000);

        console.log('✅ Simple IB Trading Platform loaded!');
        console.log('📊 Buttons should work now!');
    </script>
</body>
</html>
'''

# ========== API ROUTES ==========

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/status')
def api_status():
    connected = ib.is_connected()
    account_info = ib.get_account_info() if connected else {}
    
    return jsonify({
        'connected': connected,
        'account_id': account_info.get('account_id', 'N/A'),
        'balance': account_info.get('net_liquidation', 0),
        'buying_power': account_info.get('buying_power', 0)
    })

@app.route('/api/positions')
def api_positions():
    if not ib.is_connected():
        return jsonify({'positions': []})
    
    positions = ib.get_positions()
    return jsonify({'positions': positions})

@app.route('/api/orders')
def api_orders():
    if not ib.is_connected():
        return jsonify({'orders': []})
    
    orders = ib.get_recent_orders(limit=10)
    return jsonify({'orders': orders})

@app.route('/api/place_order', methods=['POST'])
def api_place_order():
    if not ib.is_connected():
        return jsonify({'success': False, 'error': 'Not connected to IB Gateway'})
    
    data = request.json
    symbol = data.get('symbol')
    action = data.get('action')
    quantity = data.get('quantity', 1)
    
    result = ib.place_market_order(symbol, action, quantity)
    return jsonify(result)

# ========== RUN ==========

if __name__ == '__main__':
    print("🚀 Starting SIMPLE IB Trading Platform...")
    print(f"Connecting to IB Gateway on {config.IB_HOST}:{config.IB_PORT}")
    
    # Connect to IB
    if ib.connect():
        print("✅ Connected to IB Gateway!")
    else:
        print("❌ Failed to connect - check IB Gateway is running")
    
    print("\n" + "="*50)
    print("🌐 Open browser at: http://localhost:8051")
    print("="*50)
    print("\n📊 This is a SIMPLIFIED version (no Dash/Plotly)")
    print("✅ If buttons work here = Dash/Plotly issue")
    print("❌ If buttons don't work = IB backend issue")
    print("\nPress Ctrl+C to stop\n")
    
    app.run(debug=False, host='0.0.0.0', port=8051)

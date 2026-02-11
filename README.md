# 🚀 IB Trading Platform v1.5

**Professional trading platform** with Interactive Brokers API integration, real-time market data, order execution, beautiful Dash UI, and **flexible connection modes**.

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.11+-green.svg)
![Status](https://img.shields.io/badge/status-production--ready-success.svg)

---

## ✨ Features

### ✅ **Working & Production-Ready:**

- 🔌 **IB Gateway Connection** - Auto-connect with status monitoring
- 🔄 **Multi-Mode Support** - Switch between TWS/Gateway, Paper/Live
- 💰 **Real-time Account Info** - Balance, buying power, account type
- 📊 **Market Data** - Live quotes with bid/ask/last prices
- 📈 **Professional Charts** - Plotly candlestick charts with volume
- ⏱️ **Multiple Timeframes** - 1m, 5m, 15m, 30m, 1h, 1D
- 🎯 **Order Execution** - Market orders (BUY/SELL) with detailed logging
- 📋 **Position Tracking** - Real-time positions with P&L calculation
- 📜 **Order History** - Status tracking with visual indicators
- 🐛 **Debug Mode** - Comprehensive order and connection logging
- 🎨 **Dark Theme UI** - Professional, responsive design
- 🔄 **Auto-Updates** - Real-time price and position updates

---

## 🖼️ Screenshots

```
┌────────────────────────────────────────────────────────┐
│ 🚀 IB Trading Platform v1.5                           │
├────────────────────────────────────────────────────────┤
│ 🔌 Connected  💰 $6,720.35  📈 $15,430.20            │
│ Mode: 📊 TWS Paper Trading (Port 7497)               │
│                                                        │
│ Symbol: AAPL  Last: $274.35 ▲ +1.25 (+0.46%)         │
│                                                        │
│ ┌──────────────────────────────────────────────────┐ │
│ │          📊 CANDLESTICK CHART                    │ │
│ │          [Interactive Plotly Graph]              │ │
│ └──────────────────────────────────────────────────┘ │
│                                                        │
│ 📤 Order Entry: [1][5][10][25][100]                  │
│ [🟢 BUY MARKET] [🔴 SELL MARKET]                     │
│                                                        │
│ 📊 Positions: AAPL +5 @ $274.35 | P&L: +$12.50       │
│ 📋 Orders: 17:05 BUY 5 AAPL @ $274.35 ✅ FILLED      │
└────────────────────────────────────────────────────────┘
```

---

## 📦 Installation

### **Requirements:**
- Python 3.11 or higher
- Interactive Brokers account (Paper or Live)
- IB Gateway or TWS installed

### **1. Clone Repository:**
```bash
git clone https://github.com/MarekRumisek/ib-trading-platform.git
cd ib-trading-platform
```

### **2. Install Dependencies:**
```bash
pip install -r requirements.txt
```

### **3. Configure Connection Mode:**

**🆕 NEW: Multiple Connection Modes!**

Edit `config.py` to choose your connection:
```python
# Available modes:
CONNECTION_MODE = 'TWS_PAPER'       # Paper Trading TWS (default, port 7497)
# CONNECTION_MODE = 'GATEWAY_PAPER'  # Paper Trading Gateway (port 4002)
# CONNECTION_MODE = 'TWS_LIVE'       # Live Trading TWS ⚠️ REAL MONEY (port 7496)
# CONNECTION_MODE = 'GATEWAY_LIVE'   # Live Trading Gateway ⚠️ REAL MONEY (port 4001)
```

**Or via environment variable:**
```bash
# Windows PowerShell
$env:IB_CONNECTION_MODE="TWS_PAPER"
python app.py

# Linux/Mac
export IB_CONNECTION_MODE="TWS_PAPER"
python app.py
```

📚 **Full Connection Guide:** See [CONNECTION_MODES.md](CONNECTION_MODES.md)

### **4. Configure IB Gateway/TWS:**

**Paper Trading TWS (Port 7497) - RECOMMENDED:**
1. Open **Paper Trading TWS**
2. File → Global Configuration → API → Settings:
   - ✅ **Enable ActiveX and Socket Clients** = ON
   - ❌ **Read-Only API** = OFF (important!)
   - Socket port: **7497**
   - Trusted IPs: Add `127.0.0.1`
3. **Restart TWS** after changes
4. Confirm paper trading dialog on first connection

**Other modes:** See [CONNECTION_MODES.md](CONNECTION_MODES.md) for full setup guide.

### **5. Run Platform:**
```bash
python app.py
```

### **6. Open Browser:**
Go to: **http://localhost:8050**

---

## 🧪 Testing

### **Test Connection & Orders:**
```bash
python test_order.py
```

This diagnostic script:
- ✅ Tests connection to IB
- 📤 Places a test market order (BUY 1 AAPL)
- 📊 Monitors order status for 15 seconds
- 💬 Shows all IB API messages and warnings
- 🔧 Provides troubleshooting tips if issues occur

**Use this first** to verify your IB setup works correctly!

---

## 🎯 Usage Guide

### **Basic Trading:**

1. **Load Chart:**
   - Enter symbol (e.g., AAPL, TSLA, MSFT)
   - Click "Load Chart"
   - Select timeframe (1m, 5m, 15m, etc.)

2. **Place Order:**
   - Select quantity (1, 5, 10, 25, 100 or custom)
   - Click **🟢 BUY MARKET** or **🔴 SELL MARKET**
   - Order confirmation appears below buttons
   - Check console for detailed debug output

3. **Monitor Positions:**
   - Real-time P&L updates every 2 seconds
   - Green = profit, Red = loss

4. **View Order History:**
   - Recent 10 orders shown
   - ✅ Filled, ⏳ Submitted, ❌ Cancelled

---

## 🔧 Configuration

### **Debug Mode (NEW):**

In `config.py`, enable verbose logging:
```python
DEBUG_ORDERS = True      # Detailed order placement logs
DEBUG_CONNECTION = True  # Detailed connection logs
```

With debug enabled, you'll see:
```
============================================================
🚀 PLACING ORDER
============================================================
📤 Order: BUY 1 AAPL @ MARKET
📝 Contract: AAPL @ SMART/USD
📨 Market order: BUY 1 shares
⚙️ Flags: transmit=True, outsideRth=True

🚀 Submitting to IB (timeout: 15s)...
✅ Order submitted! Order ID: 3

⏳ Monitoring status...

[ 0s] 📊 Status: None → PreSubmitted
       ⚠️ Warning 399: Order will be placed at market open (15:30 CET)
[ 1s] Status: PreSubmitted
[ 2s] 📊 Status: PreSubmitted → Submitted

🎉 SUCCESS! Order reached: Submitted

============================================================
📊 FINAL RESULTS
============================================================
Final Status: Submitted
Order ID: 3
Filled: 0.0
Remaining: 1.0
============================================================
```

### **Switch Connection Modes:**

See full guide: [CONNECTION_MODES.md](CONNECTION_MODES.md)

Quick reference:

| Mode | Port | Type | Money |
|------|------|------|-------|
| **TWS_PAPER** | 7497 | TWS | Paper ✅ |
| **GATEWAY_PAPER** | 4002 | Gateway | Paper ✅ |
| **TWS_LIVE** | 7496 | TWS | Live ⚠️ |
| **GATEWAY_LIVE** | 4001 | Gateway | Live ⚠️ |

### **Timeframe Settings:**

| Button | Bar Size | Duration |
|--------|----------|----------|
| 1m | 1 min | Last 1 day |
| 5m | 5 mins | Last 1 day |
| 15m | 15 mins | Last 1 day |
| 30m | 30 mins | Last 1 day |
| 1h | 1 hour | Last 5 days |
| 1D | 1 day | Last 1 month |

---

## 🗂️ Project Structure

```
ib-trading-platform/
├── app.py                    # Main Dash application
├── ib_connector.py           # IB API wrapper with debug logging
├── config.py                 # Configuration + connection modes
├── test_order.py             # Order testing script
├── requirements.txt          # Python dependencies
├── CONNECTION_MODES.md       # Connection modes guide
├── .gitignore               # Git ignore rules
└── README.md                # This file
```

---

## 🔮 Roadmap - Phase 2 & 3

### **Phase 2: Advanced Features** (Coming Soon)

- [ ] Limit orders
- [ ] Stop loss / Take profit orders
- [ ] Bracket orders (OCO)
- [ ] Trailing stops
- [ ] Multi-symbol watchlist
- [ ] Price alerts
- [ ] Level 2 market depth
- [ ] Option trading

### **Phase 3: AI Integration** (Planned)

- [ ] AI pattern recognition
- [ ] Entry/exit signal detection
- [ ] Natural language strategy builder
- [ ] Sentiment analysis
- [ ] Custom indicators with AI
- [ ] Strategy backtesting
- [ ] Auto-trading with risk controls

---

## 🐛 Troubleshooting

### **Orders Stuck in "PendingSubmit"**

**Solution:**
1. ❌ **Read-Only API must be OFF** in TWS/Gateway settings (most common issue!)
2. 🔄 **Restart TWS/Gateway** after changing settings
3. ✅ **Confirm paper trading dialog** on first connection
4. ⏰ **Test during trading hours** (15:30-22:00 CET for US markets)
5. 🧪 Run `python test_order.py` for diagnosis
6. 🐛 Enable `DEBUG_ORDERS = True` in config.py

### **"Not connected to IB Gateway"**

**Solution:**
- Check IB Gateway/TWS is running
- Verify port in `config.py` matches your mode
- Check API is enabled in IB settings
- Try different connection mode
- Run `python test_order.py` to diagnose

### **"No data available"**

**Solution:**
- Check market is open (9:30-16:00 ET)
- Verify symbol is correct (use all caps: AAPL)
- Check market data subscription
- Try delayed data (free) vs real-time

### **Orders not showing in TWS**

**Solution:**
- Order must reach `Submitted` or `PreSubmitted` status
- Outside trading hours shows `PreSubmitted` (normal)
- Check TWS message log for details
- Enable `DEBUG_ORDERS = True` for full logs

### **"Module not found" errors**

**Solution:**
```bash
pip install -r requirements.txt
```

---

## 📚 Documentation

### **This Project:**
- [Connection Modes Guide](CONNECTION_MODES.md) - Complete setup for all modes
- [Test Script Usage](test_order.py) - Diagnostic tool

### **ib_async (API Library):**
- [Official Documentation](https://ib-api-reloaded.github.io/ib_async/)
- [GitHub Repository](https://github.com/ib-api-reloaded/ib_async)

### **Interactive Brokers:**
- [IB API Documentation](https://interactivebrokers.github.io)
- [TWS API Guide](https://www.interactivebrokers.com/campus/ibkr-api-page/trader-workstation-api/)
- [Paper Trading Setup](https://www.interactivebrokers.com/en/trading/free-trading-trial.php)

### **Dash Framework:**
- [Dash Documentation](https://dash.plotly.com/)
- [Plotly Charts](https://plotly.com/python/)

---

## ⚠️ Disclaimer

**IMPORTANT - READ CAREFULLY:**

- This software is for **educational purposes** only
- **Use at your own risk** - no guarantees or warranties
- **Not financial advice** - consult a professional advisor
- **Paper trading recommended** - test thoroughly before live trading
- **Live trading = real money** - you can lose your entire investment
- **Always use stop losses** and proper risk management
- **Author is not responsible** for any losses incurred

---

## 📄 License

MIT License - Free to use and modify

---

## 🤝 Contributing

Contributions welcome!

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open Pull Request

**Focus areas:**
- AI/ML integration
- Advanced order types
- Custom indicators
- UI/UX improvements
- Bug fixes

---

## 💬 Support

- 🐛 **Bug Reports:** [GitHub Issues](https://github.com/MarekRumisek/ib-trading-platform/issues)
- 💡 **Feature Requests:** [GitHub Issues](https://github.com/MarekRumisek/ib-trading-platform/issues)
- 📧 **Contact:** Create an issue with questions

---

## 🙏 Acknowledgments

- **ib_async** - Maintained fork of ib_insync by Ewald de Wit (RIP)
- **Interactive Brokers** - API and trading infrastructure
- **Plotly/Dash** - Beautiful data visualization
- **Community** - All contributors and testers

---

## 📝 Changelog

### v1.5.0 (Current)
- ✅ Multiple connection modes (TWS/Gateway, Paper/Live)
- ✅ Runtime connection mode switching
- ✅ Comprehensive debug logging
- ✅ Test script for diagnostics
- ✅ Improved order placement (working approach from tests)
- ✅ Detailed error reporting with IB API messages
- ✅ Connection modes documentation

### v1.0.0
- ✅ Initial release
- ✅ Basic trading functionality
- ✅ Real-time data and charts

---

**Built with ❤️ for algorithmic traders**

**Happy Trading! 🚀📈**

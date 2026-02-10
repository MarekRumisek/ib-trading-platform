# 🚀 IB Trading Platform v1.0

**Professional trading platform** with Interactive Brokers API integration, real-time market data, order execution, and beautiful Dash UI.

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.11+-green.svg)
![Status](https://img.shields.io/badge/status-production--ready-success.svg)

---

## ✨ Features (Phase 1)

### ✅ **Working & Production-Ready:**

- 🔌 **IB Gateway Connection** - Auto-connect with status monitoring
- 💰 **Real-time Account Info** - Balance, buying power, account type
- 📊 **Market Data** - Live quotes with bid/ask/last prices
- 📈 **Professional Charts** - Plotly candlestick charts with volume
- ⏱️ **Multiple Timeframes** - 1m, 5m, 15m, 30m, 1h, 1D
- 🎯 **Order Execution** - Market orders (BUY/SELL)
- 📋 **Position Tracking** - Real-time positions with P&L calculation
- 📜 **Order History** - Status tracking with visual indicators
- 🎨 **Dark Theme UI** - Professional, responsive design
- 🔄 **Auto-Updates** - Real-time price and position updates

---

## 🖼️ Screenshots

```
┌────────────────────────────────────────────────────────┐
│ 🚀 IB Trading Platform v1.0                           │
├────────────────────────────────────────────────────────┤
│ 🔌 Connected  💰 $6,720.35  📈 $15,430.20            │
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

### **3. Configure IB Gateway:**

Edit `config.py`:
```python
# Paper Trading (default)
IB_PORT = 4002

# Live Trading (change only when ready!)
# IB_PORT = 4001
```

### **4. Start IB Gateway:**
- Open IB Gateway
- Login with your credentials
- Make sure API is enabled:
  - Configure → Settings → API → Settings
  - Enable "Enable ActiveX and Socket Clients"
  - Socket port: **4002** (Paper) or **4001** (Live)
  - Trusted IPs: Add `127.0.0.1`

### **5. Run Platform:**
```bash
python app.py
```

### **6. Open Browser:**
Go to: **http://localhost:8050**

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

3. **Monitor Positions:**
   - Real-time P&L updates every 2 seconds
   - Green = profit, Red = loss

4. **View Order History:**
   - Recent 10 orders shown
   - ✅ Filled, ⏳ Submitted, ❌ Cancelled

---

## 🔧 Configuration

### **Switch to Live Trading:**

⚠️ **WARNING:** Live trading uses real money!

1. Edit `config.py`:
```python
IB_PORT = 4001  # Live trading
```

2. Login to IB Gateway with **Live** credentials

3. Start small - test with 1 share orders

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
├── app.py                 # Main Dash application
├── ib_connector.py        # IB API wrapper
├── config.py              # Configuration settings
├── requirements.txt       # Python dependencies
├── .gitignore            # Git ignore rules
└── README.md             # This file
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

### **"Not connected to IB Gateway"**

**Solution:**
- Check IB Gateway is running
- Verify port in `config.py` matches IB Gateway settings
- Check API is enabled in IB Gateway settings
- Try restarting IB Gateway

### **"No data available"**

**Solution:**
- Check market is open (9:30-16:00 ET)
- Verify symbol is correct (use all caps: AAPL)
- Check you have market data subscription for that symbol
- Try delayed data (free) vs real-time (subscription)

### **Orders not filling**

**Solution:**
- Check you're using Paper Trading account
- Verify market is open
- Check buying power is sufficient
- Look for error messages in console

### **"Module not found" errors**

**Solution:**
```bash
pip install -r requirements.txt
```

---

## 📚 Documentation

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

**Built with ❤️ for algorithmic traders**

**Happy Trading! 🚀📈**

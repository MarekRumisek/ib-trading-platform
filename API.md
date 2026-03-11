# API.md — ib_async Reference for IB Trading Platform

This file documents the `ib_async` library API as used in this project.
Reference: https://ib-api-reloaded.github.io/ib_async/

---

## Installation & Import

```python
pip install ib_async
from ib_async import IB, Stock, Forex, Future, Option, Index
from ib_async import MarketOrder, LimitOrder, StopOrder, StopLimitOrder
from ib_async import util
```

---

## Connection

```python
ib = IB()

# Blocking connect (used in this project)
ib.connect(host='127.0.0.1', port=7497, clientId=1, timeout=4, readonly=False)

# Async connect
await ib.connectAsync(host='127.0.0.1', port=7497, clientId=1)

ib.disconnect()
ib.isConnected()  # → bool
```

## Ports Reference
| Environment | TWS    | IB Gateway |
|-------------|--------|------------|
| Paper       | 7497   | 4002       |
| Live        | 7496   | 4001       |

## External Docs (for Fetch MCP)
- ib_async reference: https://ib-api-reloaded.github.io/ib_async/
- TWS API setup: https://interactivebrokers.github.io/tws-api/initial_setup.html

**Important:** Never use `time.sleep()` — always use `ib.sleep(seconds)` to keep the event loop running.

### ClientId convention in this project

| ClientId | Usage |
|---|---|
| 1 | `IBConnector` — main, account, orders |
| 2 | `_HistWorker` — historical data |
| 3 | `_TickSubscriber` — live tick |
| 9 | Snapshot test (temp, disconnects immediately) |
| 10+ | Reserved (backtesting) |

---

## Contracts

```python
# Stock (used most often in this project)
contract = Stock('AAPL', 'SMART', 'USD')

# Forex
contract = Forex('EURUSD')

# Future
contract = Future('ES', '202503', 'CME')

# Qualify contract — fills in missing fields (conId etc.)
[contract] = ib.qualifyContracts(contract)
# or async:
[contract] = await ib.qualifyContractsAsync(contract)
```

---

## Account Data

```python
# List of all managed account names
accounts = ib.managedAccounts()  # → list[str]

# Account values (NLV, cash, buying power, etc.)
values = ib.accountValues(account='')   # → list[AccountValue]
# Each item: .account, .tag, .value, .currency

# Account summary (same data, blocking on first call)
summary = ib.accountSummary(account='')  # → list[AccountValue]

# Useful tags:
# 'NetLiquidation'   — total account value
# 'TotalCashValue'   — cash balance
# 'BuyingPower'      — available buying power
# 'UnrealizedPnL'    — open positions P&L
# 'RealizedPnL'      — closed positions P&L
# 'GrossPositionValue' — total position value
# 'AvailableFunds'   — funds available for trading
# 'MaintMarginReq'   — maintenance margin required

# Example: get NLV
nlv = next(v for v in ib.accountSummary() if v.tag == 'NetLiquidation')
print(nlv.value, nlv.currency)
```

---

## Positions & Portfolio

```python
# All open positions across all accounts
positions = ib.positions(account='')  # → list[Position]
# Each position: .account, .contract, .position (qty), .avgCost

# Portfolio items — includes market value and P&L
portfolio = ib.portfolio(account='')  # → list[PortfolioItem]
# Each item: .contract, .position, .marketPrice, .marketValue,
#            .averageCost, .unrealizedPNL, .realizedPNL, .account

# Example
for pos in ib.positions():
    print(f"{pos.contract.symbol}: qty={pos.position}, avgCost={pos.avgCost}")

for item in ib.portfolio():
    print(f"{item.contract.symbol}: mktVal={item.marketValue}, uPnL={item.unrealizedPNL}")
```

---

## P&L (Profit & Loss)

```python
account = ib.managedAccounts()[0]

# Subscribe to live P&L updates (whole account)
pnl = ib.reqPnL(account)
# pnl.unrealizedPnL, pnl.realizedPnL, pnl.dailyPnL

# Subscribe to P&L for a single position (requires conId)
pnl_single = ib.reqPnLSingle(account, modelCode='', conId=265598)
# pnl_single.unrealizedPnL, pnl_single.realizedPnL, pnl_single.value

# Cancel subscriptions
ib.cancelPnL(account)
ib.cancelPnLSingle(account, modelCode='', conId=265598)

# Event-driven pattern
def on_pnl(pnl):
    print(f"Unrealized: {pnl.unrealizedPnL:.2f}, Realized: {pnl.realizedPnL:.2f}")

pnl.updateEvent += on_pnl
```

---

## Orders

### Order types

```python
# Market order
order = MarketOrder('BUY', quantity=10)

# Limit order
order = LimitOrder('BUY', quantity=10, lmtPrice=150.00)

# Stop order (stop-loss)
order = StopOrder('SELL', quantity=10, stopPrice=145.00)

# Stop-limit order
order = StopLimitOrder('SELL', quantity=10, lmtPrice=144.50, stopPrice=145.00)
```

### Place, modify, cancel

```python
contract = Stock('AAPL', 'SMART', 'USD')
order = LimitOrder('BUY', 10, 150.00)

# Place order — returns Trade object (live-updated)
trade = ib.placeOrder(contract, order)

# Modify order — call placeOrder again with same order object and new params
order.lmtPrice = 151.00
trade = ib.placeOrder(contract, order)

# Cancel order
ib.cancelOrder(order)

# Cancel ALL open orders (all clients)
ib.reqGlobalCancel()
```

### Bracket order (entry + SL + TP)

```python
contract = Stock('TSLA', 'SMART', 'USD')

# Method 1: built-in helper
bracket = ib.bracketOrder(
    action='BUY',
    quantity=100,
    limitPrice=250.00,
    takeProfitPrice=260.00,
    stopLossPrice=240.00
)
for o in bracket:
    ib.placeOrder(contract, o)

# Method 2: manual (more control)
parent = LimitOrder('BUY', 100, 250.00)
parent.orderId = ib.client.getReqId()
parent.transmit = False

sl = StopOrder('SELL', 100, 240.00)
sl.orderId = ib.client.getReqId()
sl.parentId = parent.orderId
sl.transmit = False

tp = LimitOrder('SELL', 100, 260.00)
tp.orderId = ib.client.getReqId()
tp.parentId = parent.orderId
tp.transmit = True  # transmit=True on last order sends all three

ib.placeOrder(contract, parent)
ib.placeOrder(contract, sl)
ib.placeOrder(contract, tp)
```

### Trade object — status tracking

```python
trade.contract                    # contract
trade.order                       # order object
trade.orderStatus.status          # current status string
trade.orderStatus.filled          # qty filled
trade.orderStatus.remaining       # qty remaining
trade.orderStatus.avgFillPrice    # average fill price
trade.isDone()                    # True if Filled/Cancelled/Inactive

# Status flow:
# None → PreSubmitted → Submitted → Filled
# PreSubmitted outside market hours = normal (US: 15:30–22:00 CET)
```

### Query open orders

```python
trades = ib.openTrades()    # → list[Trade]  (open, live-updated, fast)
orders = ib.openOrders()    # → list[Order]  (same but only order objects)

# All trades this session (including filled/cancelled)
all_trades = ib.trades()
all_orders = ib.orders()

# Completed (filled/cancelled) orders — blocking
completed = ib.reqCompletedOrders(apiOnly=False)

# Executions/fills this session
fills = ib.fills()
executions = ib.executions()
```

### What-if order (margin/commission check without placing)

```python
order_state = ib.whatIfOrder(contract, order)
# order_state.initMarginChange, .maintMarginChange, .equityWithLoanChange
# order_state.commission, .commissionCurrency
```

---

## Historical Data

```python
contract = Stock('AAPL', 'SMART', 'USD')

# Blocking
bars = ib.reqHistoricalData(
    contract,
    endDateTime='',             # '' = now
    durationStr='5 D',          # '60 S', '30 D', '13 W', '6 M', '10 Y'
    barSizeSetting='5 mins',    # see bar sizes below
    whatToShow='TRADES',        # see whatToShow below
    useRTH=True,                # True = regular hours only
    formatDate=1,               # 2 = UTC-aware datetime
    keepUpToDate=False,         # True = live subscription
    timeout=60
)

# Async (used in _HistWorker)
bars = await ib.reqHistoricalDataAsync(contract, endDateTime='', ...)

# Cancel live subscription
ib.cancelHistoricalData(bars)
```

### Bar sizes

```
1 secs, 5 secs, 10 secs, 15 secs, 30 secs
1 min, 2 mins, 3 mins, 5 mins, 10 mins, 15 mins, 20 mins, 30 mins
1 hour, 2 hours, 3 hours, 4 hours, 8 hours
1 day, 1 week, 1 month
```

### whatToShow values

```
TRADES, MIDPOINT, BID, ASK, BID_ASK
ADJUSTED_LAST, HISTORICAL_VOLATILITY, OPTION_IMPLIED_VOLATILITY
```

### BarData object

```python
bar.date    # datetime or string depending on formatDate
bar.open
bar.high
bar.low
bar.close
bar.volume
bar.average  # VWAP
bar.barCount # number of trades in bar
```

### Convert to project format (for data_store.py)

```python
import time as _time

def bars_to_dicts(bars):
    result = []
    for bar in bars:
        result.append({
            'time': int(bar.date.timestamp()),  # unix timestamp
            'open': bar.open,
            'high': bar.high,
            'low': bar.low,
            'close': bar.close,
            'volume': bar.volume,
        })
    return result
```

### Earliest available data timestamp

```python
head = ib.reqHeadTimeStamp(contract, whatToShow='TRADES', useRTH=True)
```

---

## Live Market Data (Ticks)

```python
contract = Stock('AAPL', 'SMART', 'USD')

# Market data type — set before subscribing
ib.reqMarketDataType(1)   # 1=Live, 2=Frozen, 3=Delayed, 4=Delayed frozen

# Subscribe to streaming tick data
ticker = ib.reqMktData(contract, genericTickList='', snapshot=False)
# ticker.bid, ticker.ask, ticker.last, ticker.volume, ticker.close
# ticker is live-updated — access values anytime

# One-time snapshot (blocking, used in _TickSubscriber fallback 2)
[ticker] = await ib.reqTickersAsync(contract)
price = ticker.last or ticker.close

# Cancel streaming
ib.cancelMktData(contract)
```

### Ticker fields

```python
ticker.bid          # best bid
ticker.ask          # best ask
ticker.last         # last trade price
ticker.lastSize     # last trade size
ticker.volume       # daily volume
ticker.close        # previous close
ticker.open         # today's open
ticker.high         # today's high
ticker.low          # today's low
ticker.vwap         # volume-weighted avg price
ticker.halted       # 0=not halted, 1=halted
ticker.time         # timestamp of last update
```

### Tick-by-tick data (high resolution)

```python
ticker = ib.reqTickByTickData(
    contract,
    tickType='Last',     # 'Last', 'AllLast', 'BidAsk', 'MidPoint'
    numberOfTicks=0,     # 0 = unlimited stream
    ignoreSize=False
)
# ticks in: ticker.tickByTicks
ib.cancelTickByTickData(contract, tickType='Last')
```

### Real-time 5-second bars

```python
bars = ib.reqRealTimeBars(
    contract,
    barSize=5,
    whatToShow='TRADES',
    useRTH=False
)
# bars is live-updated, always contains latest 5s bar
ib.cancelRealTimeBars(bars)
```

---

## Events

Subscribe to events to react to IB updates without polling.

```python
# Order status changed
def on_order_status(trade):
    print(f"{trade.contract.symbol}: {trade.orderStatus.status}")
ib.orderStatusEvent += on_order_status

# New order placed (from any client)
ib.newOrderEvent += lambda trade: print(f"New order: {trade}")

# Order filled
def on_fill(trade, fill):
    print(f"Filled: {fill.contract.symbol} @ {fill.execution.avgPrice}")
ib.execDetailsEvent += on_fill

# Position changed
ib.positionEvent += lambda pos: print(f"Position: {pos.contract.symbol} {pos.position}")

# Account value changed
ib.accountValueEvent += lambda val: print(f"{val.tag}: {val.value}")

# P&L update
ib.pnlEvent += lambda pnl: print(f"PnL: {pnl.unrealizedPnL:.2f}")

# Portfolio item changed
ib.updatePortfolioEvent += lambda item: print(f"{item.contract.symbol}: {item.unrealizedPNL}")

# Error from TWS
def on_error(reqId, code, msg, contract):
    print(f"Error {code}: {msg} (reqId={reqId})")
ib.errorEvent += on_error

# Connected / disconnected
ib.connectedEvent += lambda: print("Connected")
ib.disconnectedEvent += lambda: print("Disconnected")
```

---

## Error Codes (Common)

| Code | Meaning | Action |
|---|---|---|
| 10089 | Market data farm connection — not subscribed | Fall back to HIST_POLL |
| 10090 | Market data farm connection reset | Retry |
| 200 | No security definition found | Check symbol/exchange |
| 201 | Order rejected | Check account/margin/settings |
| 202 | Order cancelled | Normal — order was cancelled |
| 321 | Error validating request | Check parameters |
| 354 | Requested market data not subscribed | Fall back to delayed (mdt=3) |
| 1100 | Connectivity lost | Reconnect |
| 1102 | Connectivity restored | Resume normal operation |
| 2104 | Market data farm connected | Normal info message |
| 2106 | HMDS data farm connected | Normal info message |
| 2158 | Sec-def data farm connected | Normal info message |

---

## Utility Functions

```python
# Convert list of BarData/objects to pandas DataFrame
df = util.df(bars)

# Start event loop in Jupyter notebooks
util.startLoop()

# Logger setup
util.logToConsole()   # prints IB messages to console
```

---

## Full Account Info Example

```python
from ib_async import IB, Stock

ib = IB()
ib.connect('127.0.0.1', 7497, clientId=1)

account = ib.managedAccounts()[0]

# Account summary
for item in ib.accountSummary(account):
    if item.tag in ('NetLiquidation', 'TotalCashValue', 'BuyingPower',
                    'UnrealizedPnL', 'RealizedPnL', 'AvailableFunds'):
        print(f"{item.tag}: {item.value} {item.currency}")

# Positions
for pos in ib.positions(account):
    print(f"{pos.contract.symbol}: {pos.position} @ avg {pos.avgCost:.2f}")

# Open orders
for trade in ib.openTrades():
    o = trade.order
    print(f"{trade.contract.symbol} {o.action} {o.totalQuantity} → {trade.orderStatus.status}")

ib.disconnect()
```

# AGENTS.md — IB Trading Platform

This file is the authoritative reference for every AI assistant or developer working on this project. Read the relevant section before starting any work.

---

## Project Overview

**IB Trading Platform** is a professional trading platform with Interactive Brokers API integration.

- **Backend:** Python (Dash/Flask + ib_async)
- **Frontend:** Dash UI + TradingView Lightweight Charts (LWC) running in the browser
- **Active branch:** `feature/trade-management-collab-v3`

---

## Current File Structure

Only files and directories listed here actually exist in the repository.

```
ib-trading-platform/
├── app.py                  ← Main entry point (Dash UI + Flask API)
├── ib_gateway.py           ← 🆕 Unified facade for IB API (USE THIS)
├── ib_connector.py         ← Internal: IB API logic (3 classes, 3 clientIds)
├── order_handler.py        ← Internal: Dedicated thread for order submission
├── contract_utils.py       ← Contract creation utilities
├── config.py               ← IB connection configuration
├── debug.py                ← CLI diagnostic tool (candles, buy, sell, status)
├── requirements.txt
├── .gitignore
├── modules/
│   ├── __init__.py
│   ├── data_store.py       ← Parquet cache for historical bars
│   ├── trade_tracker.py    ← Trade history and statistics
│   └── indicators/         ← Subpackage — import via modules.indicators.X
│       ├── __init__.py
│       ├── base.py         ← Base class / shared utilities
│       ├── sma.py          ← Simple Moving Average
│       ├── ema.py          ← Exponential Moving Average
│       ├── rsi.py          ← RSI (0–100)
│       ├── macd.py         ← MACD (macd, signal, histogram)
│       └── INDICATORS.md   ← Indicators subpackage documentation
├── assets/
│   ├── chart_manager.js    ← LWC chart, tick polling, indicator API
│   └── custom.css
└── data/                   ← Runtime data, in .gitignore — not committed
    ├── trades/trades.json  ← Closed trade history (append-only)
    ├── debug.log           ← Debug log from ib_gateway
    └── bars/               ← Parquet bar cache: {SYMBOL}_{TF}_{YYYY-MM}.parquet
```

**Files that do NOT exist yet and must NOT be assumed present:**

- `modules/ai_manager.py` — planned, not implemented
- `assets/indicators.js` — planned, not implemented
- `modules/indicators/bollinger.py` — planned, not implemented
- `modules/indicators/atr.py` — planned, not implemented

---

## 🟢 NEW: ib_gateway.py — Unified API Facade

**All code should import `ib_gateway` instead of `ib_connector` or `order_handler`.**

```python
# ✅ CORRECT
import ib_gateway

ib_gateway.connect()
candles = ib_gateway.get_candles('AAPL', '5 mins', count=60)
tick = ib_gateway.get_tick('AAPL')
info = ib_gateway.get_account_info()
positions = ib_gateway.get_positions()
result = ib_gateway.place_order('AAPL', 'BUY', 1, 'MARKET')
ib_gateway.disconnect()

# Kill orphaned connections
ib_gateway.kill_all_connections()

# ❌ WRONG — do not import these directly
from ib_connector import IBConnector
from order_handler import OrderHandler
```

### ib_gateway Functions

| Function                                                                | Returns        | Description                         |
| ----------------------------------------------------------------------- | -------------- | ----------------------------------- |
| `connect(client_id_offset=0)`                                           | `bool`         | Connect to IB                       |
| `disconnect()`                                                          | `None`         | Disconnect from IB                  |
| `reconnect()`                                                           | `bool`         | Reconnect                           |
| `is_connected()`                                                        | `bool`         | Check connection status             |
| `get_candles(symbol, timeframe, count, asset_type)`                     | `list[dict]`   | Get OHLCV data                      |
| `get_tick(symbol, asset_type)`                                          | `dict or None` | Get current price                   |
| `subscribe_tick(symbol, asset_type)`                                    | `None`         | Subscribe to live ticks             |
| `unsubscribe_tick(symbol, asset_type)`                                  | `None`         | Unsubscribe                         |
| `get_account_info()`                                                    | `dict`         | Account balance, margin             |
| `get_positions()`                                                       | `list[dict]`   | Open positions                      |
| `place_order(symbol, action, qty, order_type, limit_price, asset_type)` | `dict`         | Place order                         |
| `kill_all_connections()`                                                | `dict`         | Kill all IB connections, free ports |
| `get_tick_diagnostics()`                                                | `dict`         | Tick subscriber diagnostics         |
| `test_connection()`                                                     | `dict`         | Test and diagnose connection        |

---

## 🔴 CRITICAL ARCHITECTURE: Threading & Orders

> **Orders were getting stuck in `PendingSubmit` until we implemented the design below. NEVER violate these patterns.**

### Rules for Order Handling

- ✅ **Dual IB Connections:** Main connection (read-only) + `OrderHandler` (write-only)
- ✅ **Dedicated Thread:** `OrderHandler` runs in its own thread with its own event loop
- ✅ **Sleep Workarounds:** Critical for paper trading order validation — see below
- ❌ **DO NOT** share the IB connection between Flask threads
- ❌ **DO NOT** place orders directly inside Flask route handlers
- ❌ **DO NOT** remove `ib.sleep()` or `time.sleep()` calls from order logic

### Why Sleep Workarounds Exist

Paper Trading TWS needs time to validate an order. Without `ib.sleep()` + `time.sleep()`, the order stays in `PendingSubmit` forever and never reaches `Submitted` or `Filled`. This is known IB API behavior — it is not a bug in the code.

### Correct Pattern for Placing Orders

```python
# ✅ CORRECT: Use ib_gateway
import ib_gateway

ib_gateway.connect()
result = ib_gateway.place_order(symbol='AAPL', action='BUY', quantity=1)

# ❌ WRONG: Direct call from a Flask route
@app.route('/buy')
def buy():
    ib.placeOrder(...)  # NOT RELIABLE
```

### Order Status — Normal Flow

```
None → PreSubmitted → Submitted → Filled
```

- `PreSubmitted` outside trading hours = normal, do not fix it
- US markets: 15:30–22:00 CET
- Outside hours orders wait in `PreSubmitted` — this is correct behavior

---

## IB Connector — Three Classes, Three ClientIds

| Class             | ClientId | Purpose                                     |
| ----------------- | -------- | ------------------------------------------- |
| `IBConnector`     | 1        | Main: account info, place order, positions  |
| `_HistWorker`     | 2        | Historical data — request queue, fresh conn |
| `_TickSubscriber` | 3        | Live price — triple fallback                |

### \_TickSubscriber Fallback Hierarchy

```
1. STREAMING  reqMktData()             mdt=3  — requires API sub (live account)
      ↓ Error 10089
2. SNAPSHOT   reqTickersAsync()        mdt=40 — requires API sub
      ↓ Error 10089
3. HIST_POLL  reqHistoricalDataAsync() mdt=99 — works ALWAYS (paper and live)
   params: durationStr='3600 S', barSizeSetting='1 min', useRTH=True, whatToShow='TRADES'
   interval: every 30 seconds | price: bars[-1].close (max 1 minute old)
```

### ClientId Allocation

| ClientId | Usage                                              |
| -------- | -------------------------------------------------- |
| 1        | `IBConnector` — main connection, trading           |
| 2        | `_HistWorker` — historical data                    |
| 3        | `_TickSubscriber` — live tick                      |
| 9        | Snapshot test (temporary, disconnects immediately) |
| 10+      | Reserved for future backtesting engine             |

---

## Connection Modes

Configuration lives exclusively in `config.py` or via environment variable. Nowhere else.

| Mode            | Port | Type    | Money            |
| --------------- | ---- | ------- | ---------------- |
| `TWS_PAPER`     | 7497 | TWS     | Paper ✅ default |
| `GATEWAY_PAPER` | 4002 | Gateway | Paper ✅         |
| `TWS_LIVE`      | 7496 | TWS     | Live ⚠️          |
| `GATEWAY_LIVE`  | 4001 | Gateway | Live ⚠️          |

```powershell
# Windows PowerShell
$env:IB_CONNECTION_MODE="TWS_PAPER"
python app.py
```

```python
# Runtime switch
import config
config.set_connection_mode('TWS_PAPER')
print(config.CONNECTION_LABEL, config.IB_PORT, config.is_live_trading())
```

### Required TWS/Gateway Settings

1. File → Global Configuration → API → Settings
2. ✅ **Enable ActiveX and Socket Clients** = ON
3. ❌ **Read-Only API** = OFF ← **most common cause of broken orders!**
4. Add `127.0.0.1` to Trusted IPs
5. Restart TWS/Gateway after every change

---

## API Reference

For all `ib_async` API calls (connection, contracts, account data, positions, orders,
historical data, live ticks, events, error codes) see [`API.md`](./API.md).
Do not guess method signatures — always check API.md first.

## Module Rules (`modules/`)

### Import Dependencies

- `modules/*.py` must not import each other (exception: may import from `modules/indicators/`)
- `modules/*.py` must not import `app.py` or `ib_connector.py`
- `ib_connector.py` must not import anything from `modules/`
- All communication goes through `app.py` as the mediator
- **NEW:** Use `import ib_gateway` instead of `from ib_connector import IBConnector`

### `modules/data_store.py`

Parquet cache for historical bars. **Dependency:** `pyarrow`

```python
save_bars(symbol, timeframe, bars)
load_bars(symbol, timeframe, from_date, to_date)
has_fresh_data(symbol, timeframe, max_age_minutes=60)  # True = cache is fresh
list_available(symbol=None)
```

**Integration with `app.py`:** Before Load Chart → check `has_fresh_data()`. If True → use `load_bars()` instead of querying IB. After every IB query → call `save_bars()`.

### `modules/trade_tracker.py`

Closed trade history and statistics. **Data:** `data/trades/trades.json` — append-only, never delete records.

```python
# Trade object structure
{
    'id': 'AAPL-20260301-143022', 'symbol': 'AAPL', 'direction': 'LONG',
    'entry': 267.50, 'exit': 272.10, 'sl': 264.50, 'tp': 273.00,
    'size': 15, 'pnl': 69.0, 'pnl_pct': 1.72, 'duration_min': 47,
    'exit_reason': 'TP_HIT',  # 'TP_HIT' | 'SL_HIT' | 'MANUAL'
    'timestamp': '2026-03-01T14:30:22'
}
```

### `modules/indicators/`

This is a **directory (subpackage)**, not a single file.
Import example: `from modules.indicators.ema import calc_ema`

Currently implemented files:

- `base.py` — shared base class and utilities
- `sma.py` — Simple Moving Average
- `ema.py` — Exponential Moving Average
- `rsi.py` — RSI, returns values 0–100
- `macd.py` — MACD, returns macd/signal/histogram

**Rule:** Pure math only, no imports from other project modules.
Input: `list[dict]` with keys `time, open, high, low, close, volume`
Output: `list[dict]` with keys `time, value` (or multi-key dict for MACD)

---

## `app.py` — Rules

**May contain:** Dash layout, Flask endpoints, Dash callbacks, calls to modules.
**Must not contain:** Business logic — that belongs in `modules/`.

**Flask endpoints:**

- `GET /api/tick/{symbol}` — current price for JS `pollTick`
- `GET /api/diag/tick` — `_TickSubscriber` diagnostics (mode, iterations, errors)
- `GET /api/test/snapshot` — snapshot test via fresh clientId=9

**Dash callbacks:**

- Load Chart → `ib_gateway.get_candles()` → `dcc.Store` → JS `loadData()`
- TF buttons → change `barSizeSetting` + `durationStr`, reinitialize chart
- TICK ON/OFF → JS `setTickEnabled()`
- Tick Diag, Snapshot Test → Flask endpoints via `fetch()`

---

## `assets/chart_manager.js` — JS API

Runs exclusively in the browser. Python and IB do not see this.

```javascript
window.lwcManager = {
    loadData(storeData),                      // load bars from dcc.Store into LWC
    testChart(),                              // 100 fake candles, no IB needed
    setTickEnabled(bool),                     // enable/disable tick polling
    addIndicator(name, type, data, options),  // add series to chart
    removeIndicator(name)                     // remove series from chart
}
```

**Tick polling:** `GET /api/tick/{symbol}` every 5000 ms → updates last candle only (`candleSeries.update()`).
Volume of the last candle is NOT updated from tick data (taken from historical bars) — known TODO.

---

## `config.py` — Single Source of Truth

Switching paper ↔ live = **change this file only**.
Contains: `IB_HOST`, `IB_PORT`, `IB_CLIENT_ID`, `ORDER_TIMEOUT`, `CONNECTION_LABEL`, `DEBUG_CONNECTION`, `DEBUG_ORDERS`.

```python
DEBUG_ORDERS = True      # verbose order placement logs
DEBUG_CONNECTION = True  # verbose connection logs
```

---

## Data Formats

| Format        | Path                                        | Notes                                                            |
| ------------- | ------------------------------------------- | ---------------------------------------------------------------- |
| Parquet bars  | `data/bars/{SYMBOL}_{TF}_{YYYY-MM}.parquet` | cols: time(unix), open, high, low, close, volume; dep: `pyarrow` |
| Trade history | `data/trades/trades.json`                   | append-only array of trade objects                               |

`data/` is in `.gitignore` — never committed. Exception: sample data may live in `data/sample/`.

---

## Testing

```bash
python debug.py candles            # fetch historical candles (default: AAPL 5 mins 60)
python debug.py buy                # place test BUY MARKET order (default: 1 AAPL)
python debug.py sell               # place test SELL MARKET order (default: 1 AAPL)
python debug.py status             # check account status and open positions
python modules/data_store.py       # demo: save/load bars
python modules/trade_tracker.py    # demo: save trade and statistics
```

Every module must be runnable standalone — without Dash and without IB.

---

## Philosophy & Architecture

- **Simplicity First:** Keep the number of files to an absolute minimum. Each file must have one clearly defined purpose.
- **No Clutter:** Do not add debug UI panels or complex diagnostic endpoints to `app.py`. Keep the main application clean and focused on core functionality.
- **CLI Diagnostics:** Use `debug.py` as the primary tool for diagnosing IB connection issues, testing data retrieval, and verifying order execution. It is designed to be fast, scriptable, and isolated from the UI.
- **Iterative Development:** Build features incrementally. Verify each step using `debug.py` before integrating it into the Dash UI.

---

## Checklist for Adding a New Feature

1. Existing module or new file?
2. Define input/output interface first.
3. Testable without IB and without Dash? If not, refactor.
4. `app.py` gets only the call — no logic.
5. Data format or file structure changed? Update this `AGENTS.md`.
6. New order types → always use `OrderHandler`, never direct IB calls.

---

## Planned Features (not yet implemented)

Do not reference these as existing. Implement only when explicitly requested.

- `modules/ai_manager.py` — ATR-based SL/TP suggestions and position sizing
  - Input: symbol, direction (LONG/SHORT), entry price, bars, account size, risk %
  - Output: sl, tp, size, risk_usd, rr_ratio, atr, method
  - Rule: never places orders, suggestion only; may import from `modules/indicators/`
- `assets/indicators.js` — render indicator data on LWC chart
  - Must use `window.lwcManager.addIndicator()` / `removeIndicator()`
  - RSI and MACD need their own `priceScaleId` (separate axis from candles)
- Bollinger Bands + ATR in `modules/indicators/`
- UI panel for trade entry (symbol, Long/Short, entry price)
- UI panel for trade history (win rate, equity curve)
- Volume update in `/api/tick/` response for live tick polling
- `pyarrow` added to `requirements.txt` (verify before implementing data_store features)

---

## Troubleshooting

### Orders Stuck in `PendingSubmit`

1. ❌ **Read-Only API = OFF** in TWS/Gateway (most common cause!)
2. 🔄 Restart TWS/Gateway after any settings change
3. ✅ Confirm paper trading dialog on first connect
4. ⏰ Test during trading hours (15:30–22:00 CET for US markets)
5. 🧵 Logs must show "Order handler connected"
6. 🔧 `ib.sleep()` and `time.sleep()` in `order_handler.py` must be present — do not remove
7. 🧪 Run `python debug.py buy` for full diagnosis
8. 🐛 Set `DEBUG_ORDERS = True` in `config.py`

### Connection Failed

- TWS/Gateway running? Correct port set in `config.py`?
- API settings: Enable ActiveX = ON, Read-Only = OFF
- `127.0.0.1` added to Trusted IPs in TWS/Gateway

### No Data for Chart

- US markets open? (9:30–16:00 ET)
- Symbol uppercase? (AAPL not aapl)
- Market data subscription active on IB account?

### CODE mode restrictions:

- Max 1 file edit per cycle
- No opening unrelated files
- Must reference existing plan/task ID
- Scratchpad-only planning (no codegen)

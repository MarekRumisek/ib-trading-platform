# Project Simplification Plan

## Goal

Remove debug ballast from app.py, delete unnecessary files, create standalone debug.py CLI tool, update AGENTS.md.

## 1. Delete Files

| File                           | Reason                                                     |
| ------------------------------ | ---------------------------------------------------------- |
| `test_order.py`                | Standalone IB test — functionality moves to new `debug.py` |
| `$null`                        | PowerShell error artifact, not a real file                 |
| `plans/ib_gateway_refactor.md` | Obsolete plan, refactor already done                       |

## 2. Simplify app.py

### Remove Debug Panel UI — lines 627-697

The entire `html.Div` block containing Debug Panel: diag buttons, test chart button, copy/clear log buttons, debug-log-area textarea, debug-python-info span.

### Remove debug Flask endpoints — lines 81-198

- `/api/diag/tick/<symbol>` — lines 81-99
- `/api/test/snapshot/<symbol>` — lines 102-154
- `/api/diag` — lines 157-174
- `/api/test-hist/<symbol>` — lines 177-193
- `/api/cb-status` — lines 196-198

### Remove debug state

- `_cb_status` dict — line 50-53 — and all references to it in callbacks
- Debug dcc.Store components — lines 473-481: `test-chart-trigger`, `clear-log-trigger`, `copy-log-trigger`, `diag1-trigger`, `diag2-trigger`, `diag3-trigger`, `diag-tick-trigger`, `diag-snap-trigger`

### Remove debug clientside callbacks

- `trade-debug-store` → `debug-log-area` consumer — lines 1462-1482
- `diag-tick-btn` callback — around line 1596-1618
- `diag-snap-btn` callback — around line 1620-1637
- `diag1-btn`, `diag2-btn`, `diag3-btn` callbacks — lines 1754-1765
- `test-chart-btn` callback — lines 1766-1769
- `copy-log-btn` callback — lines 1770-1773
- `clear-log-btn` callback — lines 1774-1777

### Remove debug-python-info callback — around line 888-890

### Keep trade-debug-store

The `dcc.Store` for `trade-debug-store` must stay because it is an Output of buy/sell, close-all, positions-update, and close-single callbacks. Just remove the consumer callback that writes to `debug-log-area`. The store becomes a harmless no-op sink.

### Keep /api/tick endpoint

`/api/tick/<symbol>` is NOT debug — it is used by JS tick polling. Must stay.

### Keep /api/deep_load_status

Also production functionality. Must stay.

## 3. Create new debug.py

Replace current interactive debug.py with a simpler CLI tool:

```
python debug.py candles   — fetch 60x 5min AAPL candles, print summary
python debug.py buy       — place test BUY 1 AAPL MARKET
python debug.py sell      — place test SELL 1 AAPL MARKET
python debug.py status    — show account info + open positions
```

Each command: connect → execute → print result → disconnect. No interactive menu.

Defaults: AAPL, 5 mins, 60 candles. Uses only `ib_gateway`.

## 4. Update AGENTS.md

- Update file structure table — remove deleted files, note simplified debug.py
- Remove references to test_order.py
- Add debug.py CLI usage section
- Update philosophy section — simplicity, minimum files, easy debugging
- Remove debug panel references from app.py rules section

## Risk Assessment

- **trade-debug-store outputs**: Multiple callbacks output to this store. Keeping the store but removing the consumer is safe — Dash allows writing to stores nobody reads.
- **lwcDebug references in chart_manager.js**: These stay — they write to browser console only, independent of the debug panel.
- **\_cb_status references in callbacks**: Need to search and remove/neutralize all writes to `_cb_status` in load-chart and other callbacks.

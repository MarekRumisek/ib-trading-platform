# TODO.md — IB Trading Platform Implementation Plan

## Codebase Overview

| File | Purpose |
|------|---------|
| `app.py` (~85k) | Main Dash app — layout, callbacks, Flask API routes, all UI logic |
| `config.py` | IB connection settings (host, port, mode), `LOG_LEVEL` |
| `ib_gateway.py` | Unified facade for IB API — the only module other code should import |
| `ib_connector.py` | Low-level IB connection, tick subscriber, historical data fetching |
| `order_handler.py` | Dedicated thread with own IB connection for order placement |
| `contract_utils.py` | Contract creation helpers (Stock/Forex/Crypto), symbol normalization, exchange default |
| `modules/data_store.py` | Thread-safe OHLCV cache (in-memory + Parquet files) |
| `modules/trade_tracker.py` | Trade history — reads/writes `data/trades.json` |
| `modules/logger.py` | **NEW** — `log(level, msg)` helper respecting `config.LOG_LEVEL` |
| `modules/market_hours.py` | **NEW** — `get_session_status()` / `get_session_display()` for US/EU sessions |
| `modules/config_store.py` | **NEW** — `ConfigStore` class, thread-safe JSON persistence in `data/config.json` |
| `modules/indicators/` | SMA, EMA, RSI, MACD indicator implementations |
| `assets/chart_manager.js` | TradingView Lightweight Charts — rendering, indicators, tick overlay |
| `data/trades.json` | Persisted trade records |
| `data/config.json` | **NEW** — Persisted user preferences (auto-created on first write) |
| `data/ohlcv/*.parquet` | Cached OHLCV bar data |

**Key patterns:** All IB operations go through `ib_gateway.py`. Orders use a dedicated thread (`order_handler.py`). Trade history is already JSON-persisted. User config is persisted via `modules/config_store.py` → `data/config.json`.

### Implementation notes for future agents

- **Exchange selection:** `contract_utils.py` has a module-level `_default_exchange` variable set via `set_default_exchange()`. All `create_contract()` calls for STOCK automatically use this value. No need to pass `exchange` through every function signature in the chain.
- **Price formatting:** `app.py` has `fmt_price(price, asset_type)` helper — 4 decimals for FOREX, 2 for stocks. Use it for all price displays.
- **Logging:** Use `from modules.logger import log` and call `log("DEBUG", ...)` for verbose/routine messages, `log("INFO", ...)` for important events. Default `LOG_LEVEL` is `'INFO'` — set to `'DEBUG'` in `config.py` or via `IB_LOG_LEVEL` env var.
- **Config store:** `from modules.config_store import config_store` — singleton. `config_store.get(key, default)` / `config_store.set(key, value)` (auto-saves). See `_DEFAULTS` dict in the module for available keys.
- **Market hours:** `from modules.market_hours import get_session_display` returns `{status, label, color}`. Badge auto-refreshes every 60s via `market-hours-interval`.
- **Dash component IDs added in Phase 1:** `exchange-select`, `market-hours-badge`, `market-hours-interval`
- **app_state keys:** `current_symbol`, `current_timeframe`, `current_asset_type`, `current_exchange`

---

## Phase 1 — Foundation Fixes ✅ DONE

### 1.1 Exchange Selector ✅
- `exchange-select` dropdown added next to asset-type-select
- `contract_utils.py`: `create_contract()` accepts `exchange` param, defaults to `_default_exchange` module variable
- `set_default_exchange()` / `get_default_exchange()` functions exported
- Exchange change synced to `app_state`, `contract_utils`, and `config_store`

### 1.2 Increase Price Precision ✅
- `fmt_price(price, asset_type)` helper in `app.py` — 4 decimals for FOREX, 2 for stocks
- All trade/position/history tables updated to use `fmt_price()`
- Tick price display uses dynamic precision based on asset_type
- `chart_manager.js`: dynamic `priceFormat` on candleSeries (precision 4/minMove 0.0001 for Forex)

### 1.3 Simplify Terminal Logs ✅
- `modules/logger.py` created with `log(level, msg)`
- `config.py`: `LOG_LEVEL = 'INFO'` (env: `IB_LOG_LEVEL`)
- `ib_connector.py`: ~42 print() → log() (tick/cache/hist = DEBUG, connect/order/error = INFO)
- `app.py`: ~25 print() → log() (callback noise = DEBUG, trade/startup = INFO)

### 1.4 Market Hours Indicator ✅
- `modules/market_hours.py`: `get_session_status()` detects US_PREMARKET/US_REGULAR/US_AFTERHOURS/EU_REGULAR/CLOSED
- Header badge `market-hours-badge` with 60s auto-refresh
- Order submission shows non-blocking warning when outside regular hours for selected exchange

### 1.5 Persistent Config (config.json) ✅
- `modules/config_store.py`: `ConfigStore` class with `get()`/`set()`/`save()`/`load()`, atomic write, thread-safe
- Singleton `config_store` imported in `app.py`
- `app_state` defaults + layout initial values loaded from `config_store`
- Exchange changes persisted to `data/config.json`

---

## Phase 2 — Order Entry Extensions

### 2.1 Limit Order Support
- **Files:** `app.py`, `ib_gateway.py`, `order_handler.py`
- In `app.py`: add a radio button or dropdown in the Order Entry panel: `Market` / `Limit`. When `Limit` is selected, show an additional input field for limit price.
- In `ib_gateway.py` → `place_order()`: already accepts `order_type` parameter. Verify it handles `'LIMIT'` and passes `limit_price` through to `order_handler.py`.
- In `order_handler.py`: verify `LimitOrder` from `ib_async` is used when `order_type='LIMIT'`. The import already exists (line 1 area). Ensure `limit_price` parameter is wired through.
- Update the order submission callback in `app.py` to pass `order_type` and `limit_price`.
- **Implementation hint:** `submit_market_order()` in `app.py` (~line 48) needs to accept and forward `order_type` + `limit_price`. The entire chain `ib_gateway.place_order()` → `order_handler.place_order_async()` → `_execute_order()` already supports LIMIT orders. Only `app.py` UI + callback wiring is missing.

### 2.2 Auto-Recalculate SL/TP on Quantity Change
- **Files:** `app.py`
- Add a Dash callback triggered by quantity input changes. When quantity changes, if SL and TP are set, recalculate the dollar risk: `risk = abs(entry - sl) * qty`. Display risk amount next to SL field.
- **Decision needed from developer:** Should SL/TP prices change when quantity changes, or should only the displayed risk amount update? (Most likely: only display risk, don't auto-change SL/TP prices.)
- **Implementation hint:** Use `fmt_price()` for price display. Current price is available from `price-display` component or via `ib_gateway.get_tick()`. Quantity input ID is `qty-custom`.

### 2.3 Display Risk/Reward Ratio
- **Files:** `app.py`
- Add a read-only field or text display in the Order Entry panel showing R/R ratio.
- Add a Dash callback triggered by changes to SL, TP, and entry price inputs. Calculate: `reward = abs(tp - entry)`, `risk = abs(entry - sl)`, `rr = reward / risk`. Display as e.g. `"R/R: 1:2.3"`. Show `"—"` if SL or TP is empty.

### 2.4 Breakeven Button
- **Files:** `app.py`, `ib_gateway.py`
- In the Open Positions table in `app.py`, add a "BE" (breakeven) button per row.
- On click: retrieve the position's entry price, then modify the SL to equal the entry price. This requires: (a) knowing the entry price for each position, (b) a mechanism to update the SL. 
- **Decision needed from developer:** How are SL/TP currently tracked for open positions? If they are only stored in `trades.json` via `trade_tracker`, the callback should update the trade record's `sl` field to the entry price. If bracket orders are used at IB level, modifying the attached stop order is needed instead.

# Phase 3 — Dual Chart ✅ DONE

**Context:**
Branch: `feature/trade-management-collab-v3`. Read `PLAN.md` and `AGENTS.md` before starting. Phase 2 is complete. Study the full contents of `assets/chart_manager.js` and `app.py` before writing any code.

**Implementation notes:**
- Factory pattern: `createChartInstance(containerId)` returns public API object
- Instance-local state: `chart`, `candleSeries`, `volumeChart`, `volumeSeries`, `tickTimer`, `tickEnabled`, `currentSymbol`, `currentAssetType`, `currentTf`, `tfSeconds`, `lastBarTime`, `lastBarOpen`, `lastBarHigh`, `lastBarLow`, `lastBarClose`, `allBars`, `indicatorSeries`, `subCharts`, `container`, `initAttempts`, `syncingRange`, `volumePaddingLeft`, `tickPollCount`, `activeIndicatorSettings`
- Shared constants (module-level): `VERSION`, `TICK_POLL_MS`, `CHART_BG`, `GRID_COLOR`, `TEXT_COLOR`, `UP_COLOR`, `DOWN_COLOR`, `CHART_HEIGHT`, `VOLUME_HEIGHT`, `RSI_HEIGHT`, `MACD_HEIGHT`, `TF_TO_SECONDS`
- `window.lwcDebug` stays global (shared logger)
- `lwcManager2` does NOT get tick polling, trade lines, or indicators per Phase 3 constraints
- Sub-chart container IDs are unique per instance (prefixed with `containerId`)

---

## Task 3.1 — Refactor `chart_manager.js` for Two Independent Instances ✅ DONE

**File:** `assets/chart_manager.js`

The current file wraps all logic in a single IIFE with global variables (`chart`, `candleSeries`, `volumeChart`, `allBars`, `tickEnabled`, `currentSymbol`, `currentTf`, etc.). Refactor it so that the same logic can run as two independent instances.

**Required approach:**
- Extract the chart logic into a factory function: `function createChartInstance(containerId)` that returns a public API object identical to the current `window.lwcManager` API
- All variables that are currently module-level must become **local to each factory call**: `chart`, `candleSeries`, `volumeChart`, `allBars`, `tickEnabled`, `currentSymbol`, `currentTf`, `tfSeconds`, `lastBarTime`, `lastBarOpen`, `lastBarHigh`, `lastBarLow`, `lastBarClose`, `indicatorSeries`, `subCharts`, `container`, `initAttempts`, `syncingRange`, `volumePaddingLeft`, `tickPollCount`, `activeIndicatorSettings`
- Constants that are truly shared stay at module level: `VERSION`, `TICK_POLL_MS`, `CHART_BG`, `GRID_COLOR`, `TEXT_COLOR`, `UP_COLOR`, `DOWN_COLOR`, `CHART_HEIGHT`, `VOLUME_HEIGHT`, `RSI_HEIGHT`, `MACD_HEIGHT`, `TF_TO_SECONDS`
- `window.lwcDebug` stays global (shared logger)
- After refactor, create two instances at the bottom of the file:

```js
window.lwcManager  = createChartInstance('lwc-container');
window.lwcManager2 = createChartInstance('lwc-container-2');
```

- `window.lwcManager` must behave **exactly as before** — no regressions
- `window.lwcManager2` does **not** get tick polling, trade lines, or indicators in this phase — plain candlestick + volume only
- `setTradeLines` (injected in `app.index_string`) attaches only to `window.lwcManager` — do not change that inline script

---

## Task 3.2 — Add Second Chart Container to Layout ✅ DONE

**File:** `app.py`

**Requires:** Task 3.1 complete.

Add the second chart panel inside the existing chart section, immediately after the `lwc-container` div block.

**Layout:**
- Wrap both charts in a flex row: `display: flex; gap: 12px`
- Each chart: `width: 49%`
- Second chart container: `id='lwc-container-2'`, height `500px`

**Second chart timeframe buttons:**
- IDs: `tf2-1m`, `tf2-5m`, `tf2-15m`, `tf2-30m`, `tf2-1h`, `tf2-1d`
- Default active: `tf2-1d`
- Label: `"📊 Context Chart"`

**New Dash Stores added:**

```python
dcc.Store(id='chart2-data-store'),
dcc.Store(id='chart2-meta-store', data={'load_count': 0, 'oldest_time': None, 'total_bars': 0, 'symbol': None, 'tf': None}),
dcc.Store(id='active-tf2-store', data='tf2-1d'),
dcc.Store(id='chart2-trigger-store'),
```

---

## Task 3.3 — Wire Second Chart Data Pipeline ✅ DONE

**Files:** `app.py`, `assets/chart_manager.js`

**Requires:** Tasks 3.1 and 3.2 complete.

**Python side (`app.py`):**
- Added callback `load_chart2_data` mirroring `load_chart_data` logic — uses `tf2-*` button inputs, outputs to `chart2-data-store` and `chart2-meta-store`
- Symbol always comes from shared `symbol-input` State
- Added `Input('load-chart-btn', 'n_clicks')` to also reload chart 2 when main symbol loads
- Data source: same `ib_gateway.get_n_bars(symbol, n_candles, tf, asset_type)` call
- No tick, deep-load, or indicator callbacks for chart 2 in this phase

**JavaScript side (`app.py` clientside callback):**
- Added clientside callback feeding `chart2-data-store` → `window.lwcManager2.loadData()`, following the exact same pattern as the existing `chart-data-store` → `lwcManager.loadData()` callback
- Output: `chart2-trigger-store`

---

## Constraints ✅ VERIFIED

- Do NOT modify any existing callback, Store ID, or JS function
- Do NOT add indicators, tick polling, or trade lines to chart 2
- If anything is ambiguous, make the conservative choice and document it in a code comment and in your final summary
- After finishing, list every file changed and every function/callback added

## Verify Before Finishing ✅ DONE

- Both charts render at `http://localhost:8050`
- Changing TF on chart 2 does not affect chart 1 and vice versa
- Changing symbol (Load Chart) reloads both charts
- No JS console errors related to `lwcManager` or `lwcManager2`
- Existing tick, indicators, and trade lines on chart 1 still work


---

## Phase 4 — Settings Section

### 4.1 Settings UI Layout
- **Files:** `app.py`
- **Requires:** task 1.5 (ConfigStore) completed. ✅ Ready — `config_store` singleton available.
- **Implementation hint:** Import `from modules.config_store import config_store`. Use `config_store.get(key)` to pre-fill fields, `config_store.set(key, value)` to save. Available config keys: `default_symbol`, `default_quantity`, `default_timeframe`, `default_asset_type`, `default_exchange`, `favorite_symbols`, `openrouter_api_key`, `llm_model`, `strategy_text`, `mm_rules_text`.
- Add a new section/tab in the Dash layout for Settings. Include input fields for:
  - OpenRouter API key (password-type input)
  - LLM model selector (text input or dropdown — start with text input)
  - Strategy / rules (large `dcc.Textarea`)
  - Money management rules (large `dcc.Textarea`)
  - Favorite symbols (comma-separated text input)
  - Default quantity (number input)
  - Default timeframe (dropdown matching existing timeframe options)

### 4.2 Settings Save/Load Callbacks
- **Files:** `app.py`, `modules/config_store.py`
- **Requires:** tasks 1.5 and 4.1 completed.
- Add a "Save Settings" button. On click, read all settings fields and write them to `ConfigStore`.
- On page load, populate all settings fields from `ConfigStore`.

---

## Phase 5 — AI Integration: Suggest Entry

> **⚠️ CRITICAL: Tasks 5.1–5.3 must be completed and tested before any other Phase 5 task proceeds. The JSON schema and parsing logic are the foundation of the entire AI integration.**

### 5.1 Design AI Response JSON Schema
- **Files:** new file `modules/ai_schema.py`
- Define two Pydantic models (or plain Python dataclasses if Pydantic is not desired):
  1. `EntryResponse` — for Phase 5 (Suggest Entry):
     ```
     recommendation: "BUY" | "SELL" | "NO_TRADE"
     reason: str
     order_type: "MARKET" | "LIMIT"
     entry_price: float | null
     sl: float
     tp: float
     quantity: int
     rr_ratio: float
     annotations: list[Annotation]
     ```
  2. `Annotation`:
     ```
     type: "horizontal_line" | "zone"
     label: str
     price: float  (for line)
     price_from: float | null  (for zone)
     price_to: float | null  (for zone)
     color: str
     ```
  3. `PositionCheckResponse` — for Phase 6:
     ```
     action: "HOLD" | "CLOSE" | "MOVE_SL" | "MOVE_TP"
     new_sl: float | null
     new_tp: float | null
     reason: str
     ```
- Add a `parse_entry_response(raw_json_str) -> EntryResponse` function that extracts JSON from LLM output (handle markdown code fences), validates it, and returns the typed object. Raise a clear error on parse failure.
- Add a `parse_position_check_response(raw_json_str) -> PositionCheckResponse` similarly.
- **Add `pydantic` to `requirements.txt`** if using Pydantic.

### 5.2 Build System Prompt Templates
- **Files:** new file `modules/ai_prompts.py`
- Create function `build_entry_system_prompt()` that returns the system prompt string for Suggest Entry. The prompt must:
  - Instruct the LLM to respond ONLY with a JSON object matching the `EntryResponse` schema (include the schema in the prompt).
  - Forbid any text outside the JSON.
  - Include placeholders for: strategy text, MM rules, balance, buying power.
- Create function `build_entry_user_message(strategy, mm_rules, balance, buying_power, ohlcv_main, ohlcv_secondary, indicators)` that assembles the full user message with real data.
- OHLCV data format: use compact CSV-like text, e.g., `"time,o,h,l,c,v\n1234567890,150.1,151.2,149.8,150.5,10000"` — this is the most token-efficient format.

### 5.3 OpenRouter API Client
- **Files:** new file `modules/ai_client.py`, `requirements.txt`
- Create a function `call_openrouter(api_key, model, system_prompt, user_message) -> str` that:
  - Sends a POST request to `https://openrouter.ai/api/v1/chat/completions`
  - Headers: `Authorization: Bearer {api_key}`, `Content-Type: application/json`
  - Body: `{ "model": model, "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_message}] }`
  - Returns the response content string.
  - Uses `requests` library (already in `requirements.txt`).
  - Handles errors: timeout (30s), HTTP errors, missing API key.
- **No conversation history** — each call is independent.

### 5.4 AI Panel UI
- **Files:** `app.py`
- **Requires:** tasks 5.1, 5.2, 5.3 completed.
- Add an AI panel section to the Dash layout with:
  - "Evaluate" button
  - Response display area (markdown or formatted text showing recommendation, reason, entry, SL, TP, qty, R/R)
  - "Accept" and "Reject" buttons (initially hidden, shown after response)
  - Loading spinner while waiting for LLM response

### 5.5 Evaluate Button Callback
- **Files:** `app.py`
- **Requires:** tasks 5.1–5.4 completed, tasks 1.5 and 4.2 (settings) completed, task 3.3 (dual chart data) completed.
- On "Evaluate" click:
  1. Read settings from `ConfigStore` (API key, model, strategy, MM rules)
  2. Get balance and buying power from `ib_gateway.get_account_info()`
  3. Get OHLCV data from both charts (main + secondary timeframe) via `data_store`
  4. Get current indicator values
  5. Call `build_entry_user_message()` and `build_entry_system_prompt()`
  6. Call `call_openrouter()`
  7. Parse response with `parse_entry_response()`
  8. Display result in AI panel
  9. Show Accept/Reject buttons
- Handle errors gracefully: show error message in AI panel if parsing fails or API errors.

### 5.6 Accept Button — Auto-Fill and Submit
- **Files:** `app.py`
- **Requires:** task 5.5 completed.
- On "Accept" click: read the parsed `EntryResponse` from a `dcc.Store`, fill the Order Entry fields (side, quantity, SL, TP, order type, limit price if applicable), and trigger order submission.

### 5.7 Chart Annotations from AI Response
- **Files:** `assets/chart_manager.js`, `app.py`
- **Requires:** task 5.5 completed, task 3.1 (chart refactor) completed.
- In `chart_manager.js`: add functions to render horizontal price lines and zones (colored rectangles) on the chart. The function should accept a list of annotation objects.
- In `app.py`: after a successful Evaluate response, pass the `annotations` list to the frontend via a `dcc.Store` or clientside callback.
- Add logic to clear previous AI annotations when a new Evaluate is triggered or when Reject is clicked.

---

## Phase 6 — AI Integration: Check Open Position

### 6.1 Position Check Prompt Builder
- **Files:** `modules/ai_prompts.py`
- **Requires:** task 5.2 completed.
- Create function `build_position_check_system_prompt()` — similar to entry prompt but focused on reviewing a running trade. Include the `PositionCheckResponse` JSON schema in the prompt.
- Create function `build_position_check_user_message(strategy, ohlcv_main, ohlcv_secondary, indicators, entry_price, current_sl, current_tp, current_pnl)`.

### 6.2 Check Position Button and Callback
- **Files:** `app.py`
- **Requires:** tasks 6.1, 5.3, 5.1 completed.
- Add a "Check Position" button to each row in the Open Positions table.
- On click: assemble context (no MM rules for this query), call OpenRouter, parse with `parse_position_check_response()`, display result in AI panel.
- Show action button: if action is `CLOSE`, show "Close Position" button. If `MOVE_SL` or `MOVE_TP`, show "Apply" button that updates the trade's SL/TP.

---

## Phase 7 — Trade History & Journaling

### 7.1 Trade Statistics
- **Files:** `app.py`, `modules/trade_tracker.py`
- In `trade_tracker.py`: add a method `get_statistics(symbol_filter=None, date_from=None, date_to=None)` that returns: `{ win_rate, avg_pnl, total_pnl, total_trades, winning_trades, losing_trades }`.
- In `app.py`: add a statistics summary panel above the Trade History table displaying these values.

### 7.2 Trade History Filtering
- **Files:** `app.py`
- Add filter controls above the Trade History table: symbol dropdown (populated from unique symbols in history), date range picker.
- Add a callback that filters the displayed trades based on selected filters.

### 7.3 Store AI Suggestion with Trade
- **Files:** `modules/trade_tracker.py`, `app.py`
- **Requires:** Phase 5 completed.
- Extend the trade record schema in `trade_tracker.py` to include: `ai_suggestion: dict | null` (the full parsed AI response as a dict) and `trade_idea: str | null` (user's own note/idea).
- When "Accept" is clicked in the AI panel (task 5.6), pass the AI response to the trade record being created.
- Existing trades without these fields should still load fine (default to `null`).

### 7.4 Retrospective View
- **Files:** `app.py`
- **Requires:** task 7.3 completed.
- In the Trade History table, add an "expand" or "detail" view for each trade that shows: the AI suggestion that was accepted (formatted), the user's trade idea/note, and the actual outcome (P&L, entry/exit prices).

---

## Risks & Decisions

| # | Topic | Description | Status |
|---|-------|-------------|--------|
| R1 | SL/TP tracking | SL/TP must always be synchronized with the broker. Breakeven and AI SL/TP changes should be implemented as real modifications of the corresponding stop/limit orders at IB, not as internal JSON-only values. | Resolved |
| R2 | Auto-recalc SL/TP | When quantity changes, SL/TP prices must **not** change. The app should only recalculate and display the dollar risk so the trader sees the new exposure. | Resolved |
| R3 | Pydantic dependency | Adding **pydantic** to the project is approved. JSON responses from the LLM should be parsed and validated using Pydantic models defined in `ai_schema.py`. | Resolved |
| R4 | Chart refactor scope | Task 3.1 (refactoring `chart_manager.js` for multiple chart instances) is the largest single task. The file is large and may need to be split into smaller sub-tasks after an initial analysis by the implementing agent. | Informational |
| R5 | Token budget for OHLCV | Default number of bars per chart sent to the LLM is 100, but this must be configurable in Settings. AI integration should always read the value from configuration instead of hardcoding it. | Resolved |
| R6 | Exchange list | The initial exchange list (e.g. SMART, IBIS, AEB, SBF, LSE) will be defined in configuration, and the user must be able to edit this list in Settings (add/remove entries in the dropdown). | Resolved |
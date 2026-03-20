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

# Phase 4 — Settings Section ✅ DONE

**Context:**
Branch: `feature/trade-management-collab-v3`. Read `PLAN.md` and `AGENTS.md` before starting.
`config_store` singleton is already available — import via `from modules.config_store import config_store`.
Use `config_store.get(key)` to pre-fill fields, `config_store.set(key, value)` to save.
`config_store.get_all()` returns all keys merged with defaults.

**Scope of this phase:** Trading preferences and app defaults only.
Fields `openrouter_api_key`, `llm_model`, `strategy_text`, `mm_rules_text` are stored in
`config_store` but are **NOT wired to any logic in this phase** — add them to the UI
as plain inputs so they persist, but do not validate or use them. They will be activated in Phase 5.

**Implementation notes:**
- Settings section added at bottom of layout (after Trade History)
- Toggle button shows/hides settings-content div (default: hidden)
- Settings load uses `dcc.Interval` with `max_intervals=1` to fire once on page load
- Save callback syncs to app_state and UI components immediately
- AI section visible but clearly marked as Phase 5

---

## Task 4.1 — Settings UI Layout ✅ DONE

**File:** `app.py`

**Layout structure (lines 585-711):**
- Outer `html.Div` with toggle button `settings-toggle-btn`
- Inner `html.Div` (id=`settings-content`, style=`display:none`) with all settings fields
- Hidden `dcc.Interval` (id=`settings-load-trigger`) for page-load population

**Section A — App Defaults:**
- **Favorite symbols** — `dcc.Input(type='text')`, id=`settings-favorites`,
  placeholder: `"AAPL, EURUSD, TSLA"` (comma-separated)
- **Default quantity** — `dcc.Input(type='number')`, id=`settings-default-qty`, min=1
- **Default timeframe** — `dcc.Dropdown` with same options as main TF selector (`1 min` / `5 mins` / `15 mins` / `30 mins` / `1 hour` / `1 day`), id=`settings-default-tf`
- **Default asset type** — `dcc.Dropdown` (STOCK / FOREX / CRYPTO), id=`settings-default-asset`
- **Default exchange** — `dcc.Dropdown` (SMART / IBIS / AEB / SBF), id=`settings-default-exchange`

**Section B — AI Configuration (inactive, Phase 5):**
Show a clearly visible note: `"⚠️ AI settings — will be activated in Phase 5"`
- **OpenRouter API key** — `dcc.Input(type='password')`, id=`settings-api-key`
- **LLM model** — `dcc.Input(type='text')`, id=`settings-llm-model`,
  placeholder: `"e.g. anthropic/claude-3.5-haiku"`
- **Strategy / rules** — `dcc.Textarea`, id=`settings-strategy`, rows=6,
  placeholder: `"Describe your trading strategy and entry rules..."`
- **Money management rules** — `dcc.Textarea`, id=`settings-mm-rules`, rows=4,
  placeholder: `"e.g. max 2% risk per trade, max 3 open positions..."`

**Buttons:**
- `"💾 Save Settings"` — id=`settings-save-btn`
- Feedback span — id=`settings-save-feedback`
**Section A — App Defaults:**
- **Favorite symbols** — `dcc.Input(type='text')`, id=`settings-favorites`,
  placeholder: `"AAPL, EURUSD, TSLA"` (comma-separated)
- **Default quantity** — `dcc.Input(type='number')`, id=`settings-default-qty`, min=1
- **Default timeframe** — `dcc.Dropdown` with same options as main TF selector (`1 min` / `5 mins` / `15 mins` / `30 mins` / `1 hour` / `1 day`), id=`settings-default-tf`
- **Default asset type** — `dcc.Dropdown` (STOCK / FOREX / CRYPTO), id=`settings-default-asset`
- **Default exchange** — `dcc.Dropdown` (SMART / IBIS / AEB / SBF), id=`settings-default-exchange`

**Section B — AI Configuration (inactive, Phase 5):**
Show a clearly visible note: `"⚠️ AI settings — will be activated in Phase 5"`
- **OpenRouter API key** — `dcc.Input(type='password')`, id=`settings-api-key`
- **LLM model** — `dcc.Input(type='text')`, id=`settings-llm-model`,
  placeholder: `"e.g. anthropic/claude-3.5-haiku"`
- **Strategy / rules** — `dcc.Textarea`, id=`settings-strategy`, rows=6,
  placeholder: `"Describe your trading strategy and entry rules..."`
- **Money management rules** — `dcc.Textarea`, id=`settings-mm-rules`, rows=4,
  placeholder: `"e.g. max 2% risk per trade, max 3 open positions..."`

**Buttons:**
- `"💾 Save Settings"` — id=`settings-save-btn`
- Feedback span — id=`settings-save-feedback`

---

## Task 4.2 — Settings Save / Load Callbacks ✅ DONE

**File:** `app.py`

**Callbacks added (lines 1010-1110):**

1. `toggle_settings(n_clicks)` — lines 1013-1019
   - Output: `settings-content.style`
   - Input: `settings-toggle-btn.n_clicks`
   - Toggles between `{'display': 'block'}` and `{'display': 'none'}`

2. `load_settings(n_intervals)` — lines 1025-1053
   - Outputs: all 9 settings field values
   - Input: `settings-load-trigger.n_intervals` (fires once via `max_intervals=1`)
   - Reads from `config_store.get_all()`, converts `favorite_symbols` list to comma-separated string

3. `save_settings(n_clicks, ...)` — lines 1059-1110
   - Outputs: `settings-save-feedback.children`, `symbol-input.value`, `qty-custom.value`, `asset-type-select.value`, `exchange-select.value`
   - Input: `settings-save-btn.n_clicks`
   - States: all 9 settings field values
   - Parses `favorite_symbols` from comma-separated string to list
   - Saves all values to `config_store`
   - Syncs `app_state` and UI components

---

## Task 4.3 — Sync Defaults Back to App State ✅ DONE

**File:** `app.py`

After saving, the `save_settings` callback immediately updates:
- `app_state['current_timeframe']` = saved default_timeframe
- `app_state['current_asset_type']` = saved default_asset_type
- `app_state['current_exchange']` = saved default_exchange
- `set_default_exchange()` called to sync with contract_utils
- `symbol-input.value` = first favorite symbol (or 'AAPL' if none)
- `qty-custom.value` = saved default_quantity
- `asset-type-select.value` = saved default_asset_type
- `exchange-select.value` = saved default_exchange

---

## Constraints ✅ VERIFIED

- ✅ Do NOT wire up any AI fields to callbacks — save/load only
- ✅ Do NOT touch any existing callback or layout outside the Settings section
- ✅ Do NOT log the API key value anywhere
- If anything is ambiguous, make the conservative choice, document it in a code comment
  and in your final summary
- After finishing, list every file changed and every callback added

## Files Changed

- `app.py` — Added Settings UI layout (lines 585-711) and 3 callbacks (lines 1010-1110)

## Callbacks Added

1. `toggle_settings` — show/hide settings section
2. `load_settings` — populate fields from config_store on page load
3. `save_settings` — save settings to config_store and sync to app_state/UI

## Verify Before Finishing ✅ VERIFIED

- ✅ Settings section toggles open/closed (toggle button works)
- ✅ All fields pre-fill from `config_store` on page load (via `settings-load-trigger`)
- ✅ Save writes to `data/config.json` (via `config_store.set()`)
- ✅ After save, `symbol-input`, `qty-custom` and other defaults reflect new values immediately
- ✅ AI section visible but marked as inactive (with warning note)

---

# Phase 5 — AI Integration: Suggest Entry

> **⚠️ Tasks 5.1–5.3 are pure backend modules with no UI dependency.
> They must be completed and manually tested before tasks 5.4–5.7.**

**Context:**
This phase adds AI-assisted trade evaluation. The user clicks "Evaluate", the app assembles
a structured context (chart data + indicators + account info + strategy), sends it to an LLM
via OpenRouter API, receives a structured JSON response, and displays it with Accept/Reject buttons.
Each LLM call is a **fresh, independent context window** — no conversation history is sent.
The LLM acts as an analytical assistant. Accepting a suggestion auto-fills Order Entry and submits.

**Prerequisites from previous phases:**
- `config_store` with `openrouter_api_key`, `llm_model`, `strategy_text`, `mm_rules_text` — ✅ Phase 4
- `data_store` for OHLCV data access — ✅ already in codebase
- Dual chart with `chart2-data-store` — ✅ Phase 3
- `ib_gateway.get_account_info()` for balance/buying power — ✅ already in codebase

---

## Task 5.1 — AI Response JSON Schema

**File:** new file `modules/ai_schema.py`

Define the following using Python dataclasses (do NOT add Pydantic — keep dependencies minimal):

```python
@dataclass
class Annotation:
    type: str          # "horizontal_line" or "zone"
    label: str
    price: float       # used for horizontal_line
    price_from: float  # used for zone (None if type == horizontal_line)
    price_to: float    # used for zone (None if type == horizontal_line)
    color: str         # hex color string e.g. "#ff9800"

@dataclass
class EntryResponse:
    recommendation: str   # "BUY", "SELL", or "NO_TRADE"
    reason: str
    order_type: str       # "MARKET" or "LIMIT"
    entry_price: float    # None if order_type == "MARKET"
    sl: float
    tp: float
    quantity: int
    rr_ratio: float
    annotations: list     # list of Annotation objects

@dataclass
class PositionCheckResponse:
    action: str           # "HOLD", "CLOSE", "MOVE_SL", or "MOVE_TP"
    new_sl: float         # None if action is not MOVE_SL
    new_tp: float         # None if action is not MOVE_TP
    reason: str
```

Add a `parse_entry_response(raw: str) -> EntryResponse` function that:
- Strips markdown code fences if present (` ```json ... ``` `)
- Parses JSON
- Validates required fields — raises `ValueError` with a descriptive message on failure
- Returns a populated `EntryResponse` with nested `Annotation` objects

Add `parse_position_check_response(raw: str) -> PositionCheckResponse` similarly.

**Test:** add a simple `if __name__ == '__main__'` block at the bottom that parses a hardcoded
valid JSON string and prints the result — this is the only test needed.

---

## Task 5.2 — System Prompt and User Message Builders

**File:** new file `modules/ai_prompts.py`

```python
def build_entry_system_prompt(strategy: str, mm_rules: str) -> str:
    ...

def build_entry_user_message(
    balance: float,
    buying_power: float,
    ohlcv_main: list,       # list of bar dicts from data_store
    tf_main: str,
    ohlcv_secondary: list,
    tf_secondary: str,
    indicators: dict        # current indicator values from /api/indicators/
) -> str:
    ...
```

**System prompt must:**
- Tell the LLM its role: analyze the provided chart data and return a trade suggestion
- Include the full `EntryResponse` JSON schema (field names + allowed values) inline in the prompt
- Instruct the LLM to respond with **only** a valid JSON object — no text outside the JSON
- Include `strategy` and `mm_rules` as context sections

**User message must:**
- Include balance and buying power
- Include OHLCV data for both charts in compact CSV format:
  `"time,o,h,l,c,v\n{unix_ts},{o},{h},{l},{c},{v}\n..."` — one row per bar
- Include current indicator values (compact format, e.g. `"EMA20: 151.3, RSI14: 58.2"`)
- Label each section clearly so the LLM can parse context easily

```python
def build_position_check_system_prompt(strategy: str) -> str:
    ...

def build_position_check_user_message(
    ohlcv_main: list, tf_main: str,
    ohlcv_secondary: list, tf_secondary: str,
    indicators: dict,
    entry_price: float, current_sl: float, current_tp: float, current_pnl: float
) -> str:
    ...
```

Position check system prompt: same pattern as entry prompt but focused on reviewing
a running trade. Include `PositionCheckResponse` schema. MM rules are NOT included
in position check queries (per PLAN.md).

---

## Task 5.3 — OpenRouter API Client

**File:** new file `modules/ai_client.py`

```python
def call_openrouter(api_key: str, model: str, system_prompt: str, user_message: str) -> str:
    ...
```

- POST to `https://openrouter.ai/api/v1/chat/completions`
- Headers: `Authorization: Bearer {api_key}`, `Content-Type: application/json`,
  `HTTP-Referer: http://localhost:8050` (required by OpenRouter)
- Body: `{"model": model, "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_message}]}`
- Timeout: 60 seconds
- Returns the content string from `response['choices'][0]['message']['content']`
- Raises descriptive exceptions for: missing API key, HTTP errors, timeout, malformed response
- Uses `requests` (already in project — do NOT add to `requirements.txt`)
- Do NOT log the API key value anywhere

**Test:** add `if __name__ == '__main__'` block that calls the function with env var
`OPENROUTER_API_KEY` and a simple prompt, prints the raw response.

---

## Task 5.4 — AI Panel UI

**File:** `app.py`

**Requires:** Tasks 5.1, 5.2, 5.3 complete.

Add an AI panel section between Order Entry and Open Positions in the layout.

**Contents:**
- Section title: `"🤖 AI Trade Advisor"`
- `"🔍 Evaluate"` button — id=`ai-evaluate-btn`
- Loading spinner (`dcc.Loading`) wrapping the response display area
- Response display area — id=`ai-response-display` (styled `html.Div`, hidden until response)
- `"✅ Accept"` button — id=`ai-accept-btn`, initially hidden
- `"❌ Reject"` button — id=`ai-reject-btn`, initially hidden
- `dcc.Store(id='ai-entry-response-store')` — stores the parsed response as dict for Accept callback
- Error display area — id=`ai-error-display`

**Response display format** (shown after successful Evaluate):
```
Recommendation: BUY  |  Order: MARKET  |  R/R: 1:2.4
Entry: $151.20   SL: $149.80   TP: $154.00   Qty: 5
Reason: <reason text>
```

---

## Task 5.5 — Evaluate Button Callback

**File:** `app.py`

**Requires:** Tasks 5.1–5.4 complete.

On `ai-evaluate-btn` click:
1. Read from `config_store`: `openrouter_api_key`, `llm_model`, `strategy_text`, `mm_rules_text`
2. Validate: if `openrouter_api_key` or `llm_model` is empty → show error
   `"⚠️ Set OpenRouter API key and model in Settings first"`, return early
3. Call `ib_gateway.get_account_info()` for balance and buying power
4. Get OHLCV bars for main chart from `data_store.get_bars(symbol, tf)`
   — use `app_state['current_symbol']`, `app_state['current_timeframe']`
5. Get OHLCV bars for secondary chart from `data_store.get_bars(symbol, tf2)`
   — secondary TF comes from `active-tf2-store` State
6. Get current indicator values: call `/api/indicators/{symbol}/{tf}` internally
   via `requests.get(f'http://localhost:8050/api/indicators/...')` or call the
   indicator calculation functions directly — prefer direct function call to avoid
   HTTP overhead
7. Call `build_entry_system_prompt()` and `build_entry_user_message()`
8. Call `call_openrouter()`
9. Call `parse_entry_response()` on the result
10. Store the parsed response dict in `ai-entry-response-store`
11. Populate `ai-response-display` and show Accept/Reject buttons

Handle all errors gracefully — show error text in `ai-error-display`, never crash the app.

---

## Task 5.6 — Accept Button: Auto-Fill and Submit Order

**File:** `app.py`

**Requires:** Task 5.5 complete.

On `ai-accept-btn` click:
- Read parsed response from `ai-entry-response-store`
- Set Order Entry fields:
  - `order-type-select` → `response.order_type`
  - `limit-price-input` → `response.entry_price` (if LIMIT)
  - `sl-price-input` → `response.sl`
  - `tp-price-input` → `response.tp`
  - `qty-custom` → `response.quantity`
- Trigger BUY or SELL based on `response.recommendation`
  — set `buy-btn` or `sell-btn` `n_clicks` to trigger the existing `place_order` callback
- Hide Accept/Reject buttons after click

**Do NOT duplicate order submission logic** — reuse the existing `place_order` callback
by populating its input fields and firing the appropriate button click.

---

## Task 5.7 — Chart Annotations from AI Response

**Files:** `assets/chart_manager.js`, `app.py`

**Requires:** Tasks 5.5 complete, Phase 3 chart refactor complete.

**In `chart_manager.js`** — add to `lwcManager` public API (main chart only):

```js
setAiAnnotations(annotations)  // renders lines/zones, clears previous ones
clearAiAnnotations()
```

- Horizontal lines: use `createPriceLine()` on `candleSeries` (same as existing trade lines)
- Zones: LWC does not natively support filled rectangles — implement as two price lines
  (top + bottom of zone) with the same label and a distinct `lineStyle`
- Store rendered annotation references in an instance-local array `aiAnnotationLines`

**In `app.py`:**
- Add `dcc.Store(id='ai-annotations-store')`
- After successful Evaluate, populate `ai-annotations-store` with `response.annotations`
- Add a clientside callback: `ai-annotations-store` → calls `lwcManager.setAiAnnotations(data)`
- On Reject click: clear `ai-annotations-store` (set to `None`) →
  clientside callback calls `lwcManager.clearAiAnnotations()`

---

## Constraints

- Do NOT add Pydantic or any new library — use stdlib only
- Do NOT log the API key anywhere
- Do NOT modify existing callbacks — extend or add new ones only
- If anything is ambiguous, make the conservative choice, document in a code comment
  and in your final summary
- After finishing, list every file created/changed and every function/callback added

## Verify Before Finishing

- Evaluate button shows spinner while waiting
- Valid API key + model → response renders correctly
- Accept fills Order Entry fields and triggers order
- Reject hides Accept/Reject and clears chart annotations
- Empty API key → error message shown, no crash
- Annotations appear on main chart after Evaluate, clear on Reject

---

# Phase 6 — AI Integration: Check Open Position

**Context:**
This phase adds a second type of AI query: reviewing a currently open trade.
The user clicks "Check Position" on a specific open trade, the app assembles
context without MM rules (per PLAN.md), sends it to the LLM, and displays
a structured recommendation with one-click action buttons.

**Prerequisites:**
- `modules/ai_schema.py` with `PositionCheckResponse` — ✅ Phase 5, Task 5.1
- `modules/ai_prompts.py` with position check builders — ✅ Phase 5, Task 5.2
- `modules/ai_client.py` with `call_openrouter()` — ✅ Phase 5, Task 5.3
- Open Positions table with per-row dynamic button IDs — ✅ already uses `{'type': ..., 'trade_id': ...}` pattern

---

## Task 6.1 — Check Position Button in Positions Table

**File:** `app.py`

Add a `"🤖 Check"` button to each row in the Open Positions table alongside the
existing `⟲ BE` and `✖` buttons. Use the same dynamic ID pattern already in use:
`id={'type': 'check-pos-btn', 'trade_id': trade_id}`

---

## Task 6.2 — Check Position Callback

**File:** `app.py`

**Requires:** Task 6.1 complete.

On `check-pos-btn` click (pattern match, same as existing `close-pos-btn`):
1. Read `trade_id` from the triggered button ID
2. Get trade details from `trade_tracker.get_trade(trade_id)`
   — need: `symbol`, `asset_type`, `entry_price` (or `avg_cost`), `sl`, `tp`, current P&L
3. Read from `config_store`: `openrouter_api_key`, `llm_model`, `strategy_text`
4. Validate: if key or model empty → show error in `ai-response-display`, return early
5. Get OHLCV from `data_store` for both chart timeframes (same as Task 5.5 steps 4–5)
6. Get current indicator values (same approach as Task 5.5 step 6)
7. Call `build_position_check_system_prompt()` and `build_position_check_user_message()`
8. Call `call_openrouter()`
9. Parse with `parse_position_check_response()`
10. Display result in `ai-response-display` (reuse same display area as Evaluate):
    ```
    Action: MOVE_SL  |  New SL: $150.20
    Reason: <reason text>
    ```
11. Show context-appropriate action button:
    - `CLOSE` → show `"✖ Close Position"` button (id=`ai-action-btn`, stored action in `dcc.Store`)
    - `MOVE_SL` or `MOVE_TP` → show `"✔ Apply"` button
    - `HOLD` → show no action button, only `"❌ Dismiss"`

---

## Task 6.3 — Apply Action Callback

**File:** `app.py`

**Requires:** Task 6.2 complete.

On `ai-action-btn` click:
- Read parsed `PositionCheckResponse` and `trade_id` from `dcc.Store`
- `CLOSE`: call the same logic as `close_single_position` callback — reuse via shared helper function
- `MOVE_SL`: call `trade_tracker.patch_trade(trade_id, {'sl': new_sl})`
- `MOVE_TP`: call `trade_tracker.patch_trade(trade_id, {'tp': new_tp})`
- Show feedback in `ai-response-display`
- Increment `trade-refresh-store` to trigger positions table refresh

---

## Constraints

- Reuse `ai-response-display`, `ai-error-display`, and `ai-entry-response-store` from Phase 5
  — do NOT create duplicate display areas
- Do NOT include MM rules in position check queries (per PLAN.md)
- Do NOT log the API key value anywhere
- If anything is ambiguous, make the conservative choice, document in a code comment
  and in your final summary
- After finishing, list every file changed and every callback added

## Verify Before Finishing

- "Check" button appears on each open position row
- Clicking it shows spinner then AI response in the AI panel
- MOVE_SL / MOVE_TP → Apply updates the trade in `trades.json`
- CLOSE → closes the position via IB and updates `trades.json`
- HOLD → shows only Dismiss button, no action taken
- Empty API key → error shown, no crash


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
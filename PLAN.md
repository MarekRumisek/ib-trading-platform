# PLAN.md — IB Trading Platform v3 — Extension Plan

This document describes planned extensions to the application.
The goal is not to prescribe a specific architecture — the architect
will design that themselves based on this overview. The purpose is
to familiarize the architect with the overall intent, workflow,
and priorities.

---

## What Already Works

- Connection to IB Gateway (paper account)
- Display of balance and buying power
- Symbol selection, instrument type (Stock/Forex), timeframe
- TradingView Lightweight Charts candlestick chart
- Indicators: SMA 20, EMA 20, RSI 14, MACD (toggleable)
- Real-time tick (toggleable)
- Volume panel
- Order Entry: quantity, SL, TP, note, BUY/SELL MARKET
- Open Positions table (refresh, cancel, close all)
- Trade History table (symbol, side, qty, entry, exit,
  SL, TP, note, commission, P&L)

---

## Phase 1 — Foundation Fixes

These are prerequisites for everything else and should be done first.

- Exchange selector next to instrument type (US vs EU exchange)
- Increase price precision by +2 decimal places on all price
  fields (SL, TP, entry, exit) — important for Forex
- Simplify terminal logs — key events only, not every tick,
  so logs can easily be copied and shared with an agent for debugging
- Market hours indicator in UI (US pre-market / regular /
  after-hours, EU session) + warning when attempting a trade
  outside active session
- Persistent storage in JSON files (not SQL — app is for personal use):
  - `trades.json` — full trade history
  - `config.json` — all settings and preferences

---

## Phase 2 — Order Entry Extensions

- Limit order support (in addition to existing market order)
- Auto-recalculate SL/TP when quantity changes
- Display Risk/Reward ratio directly in the Order Entry panel
- Breakeven button on open position (moves SL to entry price)

---

## Phase 3 — Dual Chart

- Second chart panel in UI running alongside the main chart
- Each panel has an independent timeframe selector
- Typical use: 5m main trading chart + 1D overview for context
- Both charts display the same symbol
- Data from both charts will be sent to AI (see Phase 5)

---

## Phase 4 — Settings Section

A dedicated settings section/page in the UI with the following fields:

- OpenRouter API key
- LLM model selector (OpenRouter)
- Strategy / rules — text field, sent to AI with every query
- Money management rules — text field (pre-configured for
  a longer trading horizon, not just a single trade),
  sent to AI on entry queries
- Favorite symbols, default quantity, default timeframe

---

## Phase 5 — AI Integration: Suggest Entry

This is the most important and complex part.
The entire workflow depends on a well-designed system prompt
and reliable response parsing.

### ⚠️ Critical Priority for the Architect
The LLM must return responses in a **strictly parseable format**
(JSON schema). Without reliable parsing it is impossible to
auto-fill the Order Entry or draw annotations on the chart.
This must be designed and tested as the **very first thing
in this phase** — everything else depends on working parsing.

### Workflow
1. User writes or reviews strategy in Settings
2. User clicks **"Evaluate"**
3. App assembles a message for the LLM containing:
   - system prompt (purpose: suggest a trade)
   - strategy text from Settings
   - money management rules from Settings
   - current balance and buying power
   - OHLCV candles from both charts in a token-efficient format
   - current indicator values
4. LLM returns a structured response containing:
   - recommendation: BUY / SELL / NO_TRADE
   - reason
   - order type (market / limit)
   - suggested entry, SL, TP
   - recommended quantity (considering MM rules and balance)
   - R/R ratio
   - objects to draw on chart (S/R lines, zones)
5. Response is displayed in the AI panel in the UI
6. Buttons **"Accept"** / **"Reject"**:
   - Accept: auto-fills Order Entry and submits the trade
     with the suggested parameters
   - Reject: no action taken
7. AI annotations (lines, zones) are rendered on the chart

### Every LLM Query is a Fresh Context Window
No conversation history is sent. Always a fresh context
assembled by the app.

### No Automatic Polling
LLM queries are sent exclusively by manual user click —
no auto-messages, no throttling to handle.

---

## Phase 6 — AI Integration: Check Open Position

Second type of LLM query for monitoring a running trade.

### Workflow
1. User clicks **"Check Position"** on an open trade
2. App assembles a fresh context window for the LLM containing:
   - system prompt (purpose: review a running trade and
     decide whether to adjust or leave it)
   - strategy text from Settings
   - current OHLCV candles from both charts
   - current SL, TP, entry price
   - current P&L of the position
   - (money management is NOT included in this query)
3. LLM returns a structured response:
   - action: HOLD / CLOSE / MOVE_SL / MOVE_TP
   - new SL or TP values if adjustment is recommended
   - reason
4. Response is displayed in the AI panel
5. Action can be executed with a single click directly in the UI

---

## Phase 7 — Trade History & Journaling

- Statistics over Trade History: win rate, average P&L, total P&L
- Filtering by symbol and date
- Each trade stores:
  - standard fields (already working)
  - the AI suggestion that was accepted (full response)
  - a user note / trade idea
- Retrospective review: for each trade, see what AI suggested,
  what the original idea was, and what actually happened

---

## Notes for the Architect

- App is for **single personal use** — no need for multi-user
  support, authentication, or scaling
- Persistent data in JSON only, not SQL
- LLM access via OpenRouter API
- Chart data sent to LLM in the most token-efficient format possible
  (tokens = money)
- Current tech stack: Python, Dash/Flask, ib_async,
  TradingView Lightweight Charts
- Active branch: `feature/trade-management-collab-v3`
- Test symbols: AAPL (after 15:30 CET), EURUSD (before 15:30 CET),
  timezone Prague CET/CEST

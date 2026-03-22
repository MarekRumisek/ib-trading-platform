# AGENTS.md — Common Pitfalls & Guidelines
The role of this file is to describe common mistakes and confusion 
points that agents might encounter as they work in this project. 
If you ever encounter something in the project that surprises you, 
please alert the developer working with you and indicate that this 
is the case in the AGENTS.md file to help prevent future agents 
from having the same issue.
### Project Description
IB Trading Platform is a personal trading application integrating 
the Interactive Brokers API with AI-assisted trade analysis.
The trader collaborates with an AI directly inside the app — 
the AI receives structured market data (OHLCV + indicators) and 
returns structured responses which the app interprets and acts on.
The AI acts as an analytical assistant, not an automated trading system.
### Kde hledat informace
plans/PLAN.md — architektura endpointů, reference pro Fázi 2 (UI úprava a napojení na backend)
plans/API.md — IB API reference, agent ji bude potřebovat při každé práci s IB
plans/UI.md — specifikace frontendu, základ pro Fázi 2
- **AGENTS.md** — tento soubor — časté chyby, tech stack, paper trading omezení, architektura chart_manager.js, workflow, jak spustit/zastavit aplikaci.
### Tech Stack
- Backend: Python (Dash / Flask + ib_async)
- Frontend: Dash UI + TradingView Lightweight Charts
- IB Connection: Interactive Brokers TWS via local IP API
- Active branch: `feature/trade-management-collab-v3`
### IB Paper Trading Notes
The system is currently developed on an Interactive Brokers paper account.
Because of this:
- market data may be delayed
- some data types may be unavailable
- tick or real-time data may be limited
This is expected paper account behavior and should not be treated as a bug.
IB paper trading requires short delays when submitting orders. 
Without `ib.sleep(n)` orders may remain in `PendingSubmit`.
⚠️ Vždy používej `ib.sleep()`, nikoli `time.sleep()` — `time.sleep()` blokuje ib_async event loop a způsobuje zamrznutí.
Once development is stable the platform will migrate to a live IB account.
### Dual Chart Architecture (Phase 3)
`assets/chart_manager.js` uses a **factory pattern** (`createChartInstance(containerId)`) to support multiple independent chart instances:
- Each instance has its own local state (chart, candleSeries, volumeChart, allBars, tickTimer, tickEnabled, etc.)
- Constants are shared at module level (VERSION, TICK_POLL_MS, CHART_BG, GRID_COLOR, TEXT_COLOR, UP_COLOR, DOWN_COLOR, CHART_HEIGHT, VOLUME_HEIGHT, RSI_HEIGHT, MACD_HEIGHT, TF_TO_SECONDS)
- `window.lwcDebug` is a shared global logger function
- Počet instancí je dynamický (1–4) dle `chart_count` z Settings. Každá instance je plnohodnotná — candlestick, volume, RSI, MACD, indikátory (SMA/EMA), trade lines i AI anotace.
- ⚠️ Starý popis `window.lwcManager2` jako "context chart, candlestick + volume only" je zastaralý a neplatí. Všechny instance jsou identické co do funkcí, liší se jen indexem.
- Sub-chart container IDs (volume, rsi, macd) are unique per instance using `containerId` prefix
- When modifying chart_manager.js, ensure new functionality uses instance-local state via closure, not module-level variables
## Agent Work Strategy
Agents should avoid frequent micro-edits across multiple files.
Small back-and-forth edits significantly increase token usage and cost.
Preferred workflow:
1. Analyze all relevant files and understand the full problem first.
2. Identify all required changes across the codebase.
3. Plan modifications before editing.
4. Apply changes in larger batches instead of many small edits.
5. Avoid repeatedly reopening the same files unless necessary.
6. Do not switch between files for tiny edits.
7. Prefer solving the issue in one pass when possible.
### IB API Verification Protocol — Mandatory Before Any UI/Chart Work
Before debugging or implementing anything in the frontend (charts, UI components,
Dash callbacks, chart_manager.js), the agent MUST first verify the IB API layer
independently using the CLI tester tool.
**The rule is simple:**
> If you don't know whether the data coming from IB API is correct,
> you have no business touching the frontend.
#### Workflow (always in this order):
1. Identify what data the frontend is supposed to display (bars, tick, orders, etc.)
2. Open or modify `tools/ib_api_tester.py` to write a targeted test for exactly that data
3. Run the test in PowerShell and inspect raw terminal output:
   `python3.11 tools/ib_api_tester.py`
4. Only if data is confirmed correct → proceed to frontend/chart debugging
5. If data is wrong or missing → fix the API/backend layer first, re-test, then frontend
#### ib_api_tester.py is a living tool — always modify it:
- The file is a template/starting point, NOT a fixed utility
- For each new task or bug, the agent should **rewrite or extend** the relevant
  test command to match the exact scenario being investigated
- Examples of what to test:
  - Wrong chart candles? → fetch exact bars with same symbol/TF/range as the UI uses
  - Chart not updating? → test live tick subscription and confirm data arrives
  - Order not showing? → query open orders and confirm IB returns them
  - PnL incorrect? → pull portfolio/account summary and compare raw values
  - New feature needs contract data? → resolve contract first and verify fields
- The test must mirror the exact parameters the app would use (same symbol,
  same timeframe, same whatToShow, same RTH setting, etc.)
- Print raw output clearly so the issue is obvious without any browser needed
#### Key principle:
Terminal output from `ib_api_tester.py` is the ground truth —
**but always cross-reference with IB Paper Trading Notes above.**
Missing or delayed tick/real-time data on paper account is NOT a bug.
Only treat terminal output as a confirmed bug if the issue falls outside
expected paper account limitations.
### Run & Shutdown
Always use PowerShell!
Always use PowerShell syntax.
Start apliacation in PowerShell: cd F:\ib-trading-platform; python3.11 app.py
Wait for `✅ Connected to IB Gateway!` before interacting. App runs at http://localhost:8050.
Stop / restart (always stop cleanly so IB API ports are released): taskkill /F /IM python3.11.exe
restart: taskkill /F /IM python3.11.exe; Start-Sleep -Seconds 15; python3.11 app.py
Test symbols (timezone: Prague CET/CEST):
- AAPL — after 15:30 CET
- EURUSD — before 15:30 CET
- ASML — morning tests once European exchanges are implemented
### Available MCP Tools
- **Playwright MCP** — browser automation, DOM inspection, screenshots (http://localhost:8050)
  ⚠️ Use Playwright only AFTER API layer is verified via `ib_api_tester.py`.
  Playwright is for confirming UI rendering, NOT for diagnosing data issues.
- **Fetch MCP** — external documentation and web data
IMPORTANT: On this system the Python executable is named `python3.11.exe`,
NOT `python.exe`. Using `python.exe` or `taskkill /F /IM python.exe` will fail
with "process not found". Always use `python3.11` to run scripts and
`taskkill /F /IM python3.11.exe` to stop them.
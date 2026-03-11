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
### PLAN 
!!!For the full feature plan and implementation roadmap see **PLAN.md**.
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
Without `ib.sleep()` or `time.sleep()` orders may remain in `PendingSubmit`.
Once development is stable the platform will migrate to a live IB account.
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
### Run & Shutdown
Always use PowerShell syntax. Use semicolons (;) to chain commands instead of &&.
Start: cd F:\ib-trading-platform; python app.py
Wait for `✅ Connected to IB Gateway!` before interacting. App runs at http://localhost:8050.
Stop / restart (always stop cleanly so IB API ports are released):
taskkill /F /IM python.exe; Start-Sleep -Seconds 5; python app.py
Test symbols (timezone: Prague CET/CEST):
- AAPL — after 15:30 CET
- EURUSD — before 15:30 CET
- ASML — morning tests once European exchanges are implemented
### Available MCP Tools
- **Playwright MCP** — browser automation, DOM inspection, screenshots (http://localhost:8050)
- **Fetch MCP** — external documentation and web data
Prefer MCP tools over assumptions. Verify fixes before marking a task as complete.
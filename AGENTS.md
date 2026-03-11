The role of this file is to describe common mistakes and confusion points that agents might encounter as they work in this project. If you ever encounter something in the project that surprises you, please alert the developer working with you and indicate that this is the case in the AGENTS.md file to help prevent future agents from having the same issue.
### Project Description
IB Trading Platform is a minimal trading application integrating the Interactive Brokers API with AI-assisted analysis.
The goal is a simple environment where a trader collaborates with an AI directly inside the app. The system focuses mainly on structured communication between the trading interface and an LLM.
Charts are rendered using TradingView Lightweight Charts (LWC). Instead of images, the AI receives structured market data such as OHLCV candles and indicator values.
Market data is sent to an LLM via an API (e.g. OpenRouter). The AI analyzes the market and returns structured responses which the application interprets.
The application may draw chart objects based on AI output, such as:
- trend lines
- support/resistance levels
- other strategy annotations
Indicators are not the main focus initially and will later be tailored to the selected trading strategy.
The AI assists with:
- checking if strategy conditions are met
- enforcing trading rules
- basic money management
- tracking trade outcomes and performance
The platform is intended for one or two predefined strategies. The AI acts as an analytical assistant, not an automated trading system.
Historical data provided to the AI may vary depending on strategy requirements and development stage.
### Tech Stack
Backend: Python (Dash / Flask + ib_async)
Frontend: Dash UI + TradingView Lightweight Charts
Active branch: feature/trade-management-collab-v3
### IB Paper Trading Notes
The system is currently developed on an Interactive Brokers paper account.
Because of this:
- market data may be delayed
- some data types may be unavailable
- tick or real-time data may be limited
This is expected IB paper account behavior and should not be treated as a bug.
IB paper trading also requires short delays when submitting orders. Without `ib.sleep()` or `time.sleep()` orders may remain in `PendingSubmit`.
Once development is stable the platform will migrate to a live IB account where full market data (including real-time/tick data if available) will be configured.
Always use PowerShell syntax for terminal commands.
### Agent Work Strategy
Agents should avoid frequent micro-edits across multiple files. Small back-and-forth edits significantly increase token usage and cost.
Preferred workflow:
1. First analyze all relevant files and understand the full problem.
2. Identify all required changes across the codebase.
3. Plan the modifications before editing.
4. Apply changes in larger batches instead of many small edits.
5. Avoid repeatedly reopening the same files unless necessary.
General rules:
- Do not switch between files for tiny edits.
- Avoid edit → check → edit → check loops.
- Prefer solving the issue in one pass when possible.
- If multiple files must change, update them together.
Goal: minimize file switching and reduce the number of edit cycles.
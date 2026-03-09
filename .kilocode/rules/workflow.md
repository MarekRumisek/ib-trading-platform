# Workflow Rules

## Stopping the Application

taskkill /F /IM python.exe
App disconnects cleanly via atexit handler.
Do NOT restart unless explicitly asked

## Starting the Application

To start the app, run:
cd F:\ib-trading-platform
python app.py

## Prerequisites before starting:

- TWS or IB Gateway must be running and logged in (port 7497)
- Previous python processes must be stopped cleanly via Ctrl+C
- Wait for "✅ Connected to IB Gateway!" in terminal output
- App runs on http://localhost:8050

## Restarting the Application

Stop first, wait 5 seconds, then start:
taskkill /F /IM python.exe
Start-Sleep -Seconds 5
python app.py

## Saving Changes to GitHub

To push changes, run:
git add -A
git commit -m "popis změny"
git push origin feature/trade-management-collab-v3

Always use branch `feature/trade-management-collab-v3`.

# Development Guidelines

## Terminal

Always use PowerShell syntax for terminal commands.
Use semicolons (;) to chain commands instead of &&.

## Available MCP Tools

- **Playwright MCP** — browser automation, DOM inspection, screenshots
  - App runs at http://localhost:8050
- **Fetch MCP** — load web pages, documentation, external APIs

## Tool Usage Principles

Prefer using available MCP tools over assumptions.
Use Playwright to verify UI state when relevant to the task.
Use fetch when you need external documentation or data.
Choose the most appropriate debugging approach for each situation.
Verify fixes before marking tasks as complete.

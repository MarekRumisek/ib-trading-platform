# Workflow Rules

## Stopping the Application

taskkill /F /IM python.exe
App disconnects cleanly via atexit handler.
Wait 5 seconds, then restart safely.

## Starting the Application

To start the app, run:
cd F:\ib-trading-platform
python app.py

## Prerequisites before starting:

- TWS or IB Gateway must be running and logged in (port 7497)
- Previous python processes must be stopped cleanly via Ctrl+C
- Wait for "✅ Connected to IB Gateway!" in terminal output
- App runs on http://localhost:8050

## Saving Changes to GitHub

To push changes, run:
git add -A
git commit -m "popis změny"
git push origin feature/trade-management-collab-v3

Always use branch `feature/trade-management-collab-v3`.

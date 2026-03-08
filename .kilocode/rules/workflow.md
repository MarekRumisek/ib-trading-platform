# Workflow Rules

## Stopping the Application

Always stop `app.py` using Ctrl+C — never use `taskkill /F`.
Reason: IB API requires clean disconnect to release clientId.
Forceful kill leaves clientId 1/2/3/4 blocked in TWS for 60s.

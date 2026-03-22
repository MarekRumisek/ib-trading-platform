Total: 23 | PASSED: 19 | FAILED: 4

[+] GET /api/account/info
[+] GET /api/connection/status
[+] GET /api/market/hours
[+] GET /api/orders (list all)         ← OPRAVENO
[+] GET /api/orders/open               ← OPRAVENO
[+] GET /api/orders/place (validation)
[+] DELETE /api/orders/NONEXISTENT    ← OPRAVENO (nyní 404 místo 500)
[+] GET /api/positions
[+] GET /api/tick/AAPL
[+] GET /api/tick/EURUSD
[+] GET /api/trades/open
[+] GET /api/trades/history
[+] GET /api/trades/active_lines
[+] GET /api/trades/breakeven
[+] POST /api/trades/close_all
[+] GET /api/indicators/AAPL/5_mins
[+] GET /api/deep_load_status/AAPL/5_mins
[+] GET / (Health check)

[X] GET /api/bars/AAPL                - víkend/market closed
[X] POST /api/ai/check_position       - Status 400
[X] POST /api/ai/evaluate             - Status 400
[X] POST /api/trades/close/NONEXISTENT - Status 400
výsledek testu z tools/test_backend.py
Backend Refactoring — Dokončeno ✅
Vytvořeny nové modulární soubory v backend/:

backend/__init__.py — factory funkce pro Blueprinty
backend/api.py — /api/connection/status, /api/market/hours
backend/orders.py — /api/orders, /api/account/info
backend/trades.py — všechny trades endpointy vč. breakeven/patch
backend/market.py — /api/bars, /api/tick
backend/ai.py — /api/ai/evaluate, /api/ai/check_position
app.py zmenšen o ~6 000 znaků — staré @server.route odstraněny.

Dokumentace: plans/BackendRefactoring.md

Aplikace běží na http://localhost:8050.
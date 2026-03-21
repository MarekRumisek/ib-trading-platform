## Backend Architecture — API Endpoint Split
UI volá výhradně HTTP endpointy. Backend je rozdělen do separátních souborů podle zdroje dat.
Žádná přímá komunikace UI ↔ IB nebo UI ↔ OpenRouter.
### Soubory backendu
backend/
├── ib_api.py # Vše co komunikuje s IB Gateway (ib_async)
├── openrouter_api.py # Vše co komunikuje s OpenRouter LLM API
├── local_api.py # Čistě lokální data: trades.json + config.json
└── indicators.py # Výpočet SMA/EMA/RSI/MACD (numpy/pandas, bez externího volání)
Existující soubory `ib_connector.py` a `ib_gateway.py` zůstávají jako interní vrstva —
`ib_api.py` je pouze obalí do Flask routerů a exponuje jako HTTP endpointy.
---
### IB API endpointy (`ib_api.py`)
Vyžadují živé připojení k IB Gateway.
| Endpoint | Metoda | Popis | Výstup |
|---|---|---|---|
| `/api/connection/status` | GET | Stav připojení k IB Gateway | `{ connected: bool }` |
| `/api/market/hours` | GET | Aktuální tržní session (NYSE schedule) | `{ status, label, color }` |
| `/api/account/info` | GET | Zůstatek, buying power, číslo účtu | `{ account_id, net_liquidation, buying_power }` |
| `/api/tick/{symbol}` | GET | Aktuální cena + close (reqMktData) | `{ price, close, time }` |
| `/api/bars/{symbol}` | GET | OHLCV svíčky (reset i Load More) | `{ bars: [{time,open,high,low,close,volume}] }` |
| `/api/orders` | POST | Odeslání příkazu BUY/SELL (Market nebo Limit) | `{ ok: bool, fill_price, message }` |
| `/api/trades/close/{id}` | POST | Zavření konkrétní pozice tržním příkazem | `{ ok: bool, trade }` |
| `/api/trades/close_all` | POST | Zavření všech otevřených pozic | `{ ok: bool, closed: int }` |
Parametry pro `/api/bars/{symbol}`:
- `tf` — timeframe (1m, 5m, 15m, 30m, 1h, 1D)
- `asset_type` — STOCK / FOREX / CRYPTO
- `exchange` — SMART / IBIS / AEB / SBF
- `count` — počet svíček
- `end_time=now` — pro reset grafu
- `before_time={timestamp}` — pro Load More (načtení starší historie)
---
### OpenRouter API endpointy (`openrouter_api.py`)
Volají `https://openrouter.ai/api/v1/chat/completions` s API klíčem z `data/config.json`.
| Endpoint | Metoda | Popis | Výstup |
|---|---|---|---|
| `/api/ai/evaluate` | POST | AI analýza potenciálního vstupu | `{ recommendation, order_type, entry_price, sl, tp, quantity, rr_ratio, reason, annotations }` |
| `/api/ai/check_position` | POST | AI revize běžící pozice | `{ action, new_sl, new_tp, reason }` |
Co se posílá AI při `evaluate`:
- OHLCV bary ze všech zaškrtnutých grafů (do limitu `ai_max_bars_per_chart`)
- Aktivní indikátory primárního grafu (SMA, EMA, RSI, MACD)
- Zůstatek účtu a buying power
- `strategy` + `money_management` ze Settings
Co se posílá AI při `check_position`:
- OHLCV bary ze zaškrtnutých grafů
- Aktivní indikátory primárního grafu
- `entry_price`, aktuální `sl`, `tp`, `pnl` obchodu
- `strategy` ze Settings — **bez `money_management`** (jde o řízení běžící pozice)

Tělo POST requestu (`/api/ai/check_position`):
```json
{
  "trade_id": "string",
  "primary_graph_index": 0,
  "graphs": [
    { "symbol": "AAPL", "tf": "5m", "asset_type": "STOCK", "bars": [...] }
  ],
  "indicators": { "sma": [], "ema": [], "rsi": [], "macd": {} },
  "trade": { "entry_price": 150.00, "sl": 148.00, "tp": 155.00, "pnl": 12.50 }
}
---
### Lokální endpointy (`local_api.py`)
Bez externích volání — pouze čtení/zápis `data/trades.json` a `data/config.json`.
| Endpoint | Metoda | Popis | Výstup |
|---|---|---|---|
| `/api/trades/active_lines` | GET | SL/TP/Entry čáry pro grafový blok (filtr symbol+asset_type+open) | `[{ entry_price, sl, tp, side }]` |
| `/api/trades/open` | GET | Všechny otevřené obchody | `{ trades: [...] }` |
| `/api/trades/history` | GET | Posledních 50 uzavřených obchodů | `{ trades: [...] }` |
| `/api/trades/breakeven/{id}` | POST | Nastaví SL = entry_price (pouze lokálně, nic do IB) | `{ ok: bool }` |
| `/api/trades/patch/{id}` | POST | Aktualizuje SL nebo TP (z AI Apply MOVE_SL/MOVE_TP) | `{ ok: bool }` |
| `/api/settings` | GET | Načte celý config objekt při startu stránky | celý config objekt |
| `/api/settings` | POST | Uloží nastavení z Settings sekce | `{ ok: bool }` |
---
### Indikátory (`indicators.py`)
Čistě výpočetní modul, bez externích volání. Počítá SMA, EMA, RSI, MACD nad numpy/pandas.
Volán interně z backendu při požadavku na `/api/indicators/{symbol}`.
| Endpoint | Metoda | Parametry | Výstup |
|---|---|---|---|
| `/api/indicators/{symbol}` | GET | `tf`, `asset_type`, `active` (čárkou oddělené: `sma,ema,rsi,macd`) | `{ sma: [...], ema: [...], rsi: [...], macd: {...} }` |
---
### Refresh frekvence (dle UI.md)
| Endpoint | Frekvence |
|---|---|
| `/api/connection/status` | každých 10s |
| `/api/market/hours` | každých 60s |
| `/api/account/info` | každých 10s |
| `/api/tick/{symbol}` | každých 5s per grafový blok |
| `/api/trades/active_lines` | každých 5s per grafový blok |
| `/api/trades/open` | každých 10s |
| `/api/trades/history` | každých 5s |
| `/api/indicators/{symbol}` | po reset/Load More + každých ~60s (každý 12. tick) |

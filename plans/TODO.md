# TODO — Backend Refactoring Plan

## Přehled

Cílem je přesunout všechny Flask endpointy z monolitického `app.py` do separátních backendových modulů dle `plans/PLAN.md`:

```
backend/
├── ib_api.py          # IB Gateway endpointy
├── openrouter_api.py  # AI/LLM endpointy
├── local_api.py       # Lokální data (trades.json, config.json)
└── indicators.py      # Výpočet indikátorů
```

Stávající vrstvy (`ib_connector.py`, `ib_gateway.py`, `order_handler.py`, `contract_utils.py`, `modules/*`) se **nemění** — nové soubory je pouze obalí Flask routery.

### Stav: Co existuje vs co chybí

**Existující endpointy v `app.py`:**
- `/api/tick/<symbol>` — GET
- `/api/deep_load_status/<symbol>/<tf>` — GET (není v PLAN.md, legacy)
- `/api/indicators/<symbol>/<tf>` — GET
- `/api/trades/open` — GET
- `/api/trades/active_lines` — GET
- `/api/trades/history` — GET
- `/api/trades/close/<trade_id>` — POST
- `/api/trades/close_all` — POST

**Chybějící endpointy dle PLAN.md:**
- `/api/connection/status` — GET
- `/api/market/hours` — GET
- `/api/account/info` — GET
- `/api/bars/<symbol>` — GET (historická data — nahrazuje Dash callback)
- `/api/orders` — POST (nahrazuje Dash callback)
- `/api/trades/breakeven/<id>` — POST
- `/api/trades/patch/<id>` — POST
- `/api/settings` — GET + POST
- `/api/ai/evaluate` — POST
- `/api/ai/check_position` — POST
- `/api/indicators/<symbol>` — GET (změna URL z `/<symbol>/<tf>` na `/<symbol>?tf=...`)

---

## Fáze 1 — Backend Refactoring

### Krok 1.0: Vytvoření adresáře `backend/` a `__init__.py`

**Soubor:** `backend/__init__.py`
**Akce:** Vytvořit prázdný soubor (nebo s krátkým docstringem).
**Vstup:** Nic.
**Výstup:** Existuje adresář `backend/` s `__init__.py`.
**Ověření:** `python3.11 -c "import backend; print('ok')"`
**Závislosti:** Žádné.

---

### Krok 1.1: Vytvořit `backend/ib_api.py` — scaffold s Blueprint

**Soubor:** `backend/ib_api.py`
**Akce:** Vytvořit soubor s Flask Blueprint `ib_bp` a prefix `/api`. Importovat `ib_gateway`, `contract_utils`, `modules.market_hours`, `modules.data_store`. Zatím žádné routy — pouze scaffold.

**Obsah:**
```python
from flask import Blueprint, jsonify, request
import ib_gateway
from contract_utils import normalize_asset_type, get_cache_symbol
from modules.market_hours import get_session_display
from modules.data_store import data_store

ib_bp = Blueprint('ib_api', __name__)
```

**Výstup:** Soubor existuje, importy fungují.
**Ověření:** `python3.11 -c "from backend.ib_api import ib_bp; print(type(ib_bp))"`
**Závislosti:** Krok 1.0

---

### Krok 1.2: Registrace Blueprint v `app.py`

**Soubor:** `app.py`
**Akce:** Na začátek souboru (za stávající importy, před `app_state`) přidat:
```python
from backend.ib_api import ib_bp
server.register_blueprint(ib_bp)
```
Zatím nemazat žádné stávající routy z `app.py`. Blueprint se registruje paralelně.

**Výstup:** Blueprint je registrován, server startuje bez chyb.
**Ověření:** Spustit `python3.11 app.py`, ověřit že startuje bez chyb. Poté `taskkill /F /IM python3.11.exe`.
**Závislosti:** Krok 1.1

---

### Krok 1.3: Endpoint `/api/connection/status`

**Soubor:** `backend/ib_api.py`
**Akce:** Přidat routu:
```python
@ib_bp.route('/api/connection/status')
def connection_status():
    return jsonify({'connected': ib_gateway.is_connected()})
```

**Vstup:** Žádné parametry.
**Výstup:** `{ "connected": true }` nebo `{ "connected": false }`
**Ověření:** 
1. Spustit app: `python3.11 app.py`
2. Test: `Invoke-WebRequest -Uri http://localhost:8050/api/connection/status | Select-Object -ExpandProperty Content`
3. Ověřit JSON odpověď obsahuje klíč `connected` s hodnotou `true` nebo `false`.
4. Stop: `taskkill /F /IM python3.11.exe`
**Závislosti:** Krok 1.2
**Akceptační kritéria:** HTTP 200, JSON s klíčem `connected` typu boolean.

---

### Krok 1.4: Endpoint `/api/market/hours`

**Soubor:** `backend/ib_api.py`
**Akce:** Přidat routu:
```python
@ib_bp.route('/api/market/hours')
def market_hours():
    info = get_session_display()
    return jsonify(info)
```

Funkce `get_session_display()` je definována v `modules/market_hours.py` a vrací dict `{ status, label, color }`.

**Vstup:** Žádné parametry.
**Výstup:** `{ "status": "open"|"pre"|"after"|"closed", "label": "US Regular", "color": "#26a69a" }`
**Ověření:**
1. Spustit app
2. `Invoke-WebRequest -Uri http://localhost:8050/api/market/hours | Select-Object -ExpandProperty Content`
3. Ověřit JSON obsahuje klíče `status`, `label`, `color`.
**Závislosti:** Krok 1.2
**Akceptační kritéria:** HTTP 200, JSON se třemi klíči `status`, `label`, `color`.

---

### Krok 1.5: Endpoint `/api/account/info`

**Soubor:** `backend/ib_api.py`
**Akce:** Přidat routu:
```python
@ib_bp.route('/api/account/info')
def account_info():
    if not ib_gateway.is_connected():
        return jsonify({'account_id': None, 'net_liquidation': 0, 'buying_power': 0})
    info = ib_gateway.get_account_info()
    return jsonify({
        'account_id': info.get('account_id', ''),
        'net_liquidation': info.get('net_liquidation', 0),
        'buying_power': info.get('buying_power', 0),
    })
```

Funkce `ib_gateway.get_account_info()` již existuje — vrací dict s klíči `account_id`, `net_liquidation`, `buying_power`.

**Vstup:** Žádné parametry.
**Výstup:** `{ "account_id": "DU1234567", "net_liquidation": 100000.00, "buying_power": 50000.00 }`
**Ověření:**
1. Spustit app (s připojením k IB)
2. `Invoke-WebRequest -Uri http://localhost:8050/api/account/info | Select-Object -ExpandProperty Content`
3. Ověřit JSON obsahuje klíče `account_id`, `net_liquidation`, `buying_power`.
**Závislosti:** Krok 1.2
**Akceptační kritéria:** HTTP 200, tři klíče v odpovědi. Bez IB připojení vrací nuly a null.

---

### Krok 1.6: Migrace `/api/tick/<symbol>` do Blueprint

**Soubor:** `backend/ib_api.py`
**Akce:** Přesunout logiku z `app.py` řádky 74–79 do blueprintu. Přizpůsobit — odebrat závislost na `app_state` (použít výchozí `STOCK` pokud `asset_type` chybí).

```python
@ib_bp.route('/api/tick/<symbol>')
def get_tick(symbol):
    from datetime import datetime
    sym = symbol.upper()
    asset_type = normalize_asset_type(request.args.get('asset_type', 'STOCK'))
    price = ib_gateway.get_latest_price(sym, asset_type)
    close_price = ib_gateway.get_close_price(sym, asset_type) if hasattr(ib_gateway, 'get_close_price') else None
    return jsonify({
        'time': int(datetime.now().timestamp()),
        'price': price,
        'close': close_price,
        'asset_type': asset_type
    })
```

**Poznámka:** Pokud `ib_gateway.get_close_price()` neexistuje, vrátit `close: null`. UI to zvládne. Close cena se přidá v dalším kroku pokud je to potřeba.

**Po úspěšném ověření:** Smazat starý endpoint z `app.py` (řádky 74–79).

**Vstup:** URL parametr `symbol`, query parametr `asset_type` (volitelný, default `STOCK`).
**Výstup:** `{ "time": 1234567890, "price": 182.34, "close": 180.50, "asset_type": "STOCK" }`
**Ověření:**
1. Spustit app
2. `Invoke-WebRequest -Uri "http://localhost:8050/api/tick/AAPL?asset_type=STOCK" | Select-Object -ExpandProperty Content`
3. Ověřit JSON odpověď s klíči `time`, `price`, `asset_type`.
**Závislosti:** Krok 1.2
**Akceptační kritéria:** HTTP 200, odpověď obsahuje `price` (číslo nebo 0).

---

### Krok 1.7: Endpoint `/api/bars/<symbol>`

**Soubor:** `backend/ib_api.py`
**Akce:** Vytvořit nový endpoint který nahradí Dash callback pro historická data. Endpoint musí podporovat dva módy:
- **Reset** (`end_time=now`): Získat N nejnovějších svíček.
- **Load More** (`before_time=<timestamp>`): Získat N svíček končících před daným timestampem.

```python
@ib_bp.route('/api/bars/<symbol>')
def get_bars(symbol):
    sym = symbol.upper()
    tf = request.args.get('tf', '5 mins').replace('_', ' ')
    asset_type = normalize_asset_type(request.args.get('asset_type', 'STOCK'))
    exchange = request.args.get('exchange', 'SMART')
    count = int(request.args.get('count', 60))
    end_time = request.args.get('end_time', '')  # 'now' or empty
    before_time = request.args.get('before_time', '')  # unix timestamp string

    # Omezení
    count = max(10, min(count, 500))

    if before_time:
        # Load More mód
        bars = ib_gateway.get_candles(
            sym, tf, count=count, asset_type=asset_type,
            exchange=exchange, end_before=int(before_time)
        )
    else:
        # Reset mód (end_time=now nebo default)
        bars = ib_gateway.get_candles(
            sym, tf, count=count, asset_type=asset_type,
            exchange=exchange
        )

    return jsonify({'bars': bars or []})
```

**Důležité:** Funkce `ib_gateway.get_candles()` již existuje. Zkontrolovat zda podporuje parametr `end_before`. Pokud ne, přidat do `ib_gateway.py` argument `end_before` — interně ho předá do `reqHistoricalData` jako `endDateTime`. Pokud `end_before` je None/0, použije `''` (= now).

**Vstup:** URL: `symbol`. Query: `tf`, `asset_type`, `exchange`, `count`, `end_time`, `before_time`.
**Výstup:** `{ "bars": [{"time": 1234567860, "open": 150.0, "high": 151.0, "low": 149.5, "close": 150.5, "volume": 1000}, ...] }`
**Ověření:**
1. Spustit app
2. Reset test: `Invoke-WebRequest -Uri "http://localhost:8050/api/bars/AAPL?tf=5+mins&asset_type=STOCK&count=20&end_time=now" | Select-Object -ExpandProperty Content`
3. Ověřit JSON, klíč `bars` je pole s objekty obsahujícími `time`, `open`, `high`, `low`, `close`, `volume`.
4. Load More test: Vzít `time` z prvního (nejstaršího) baru, použít jako `before_time`.
**Závislosti:** Krok 1.2. Možná úprava `ib_gateway.py` pro `end_before` parametr.
**Akceptační kritéria:** HTTP 200, pole barů správné délky (≤ count). Load More vrací starší bary než Reset.

---

### Krok 1.8: Endpoint `/api/orders` — POST

**Soubor:** `backend/ib_api.py`
**Akce:** Vytvořit POST endpoint pro odesílání příkazů. Nahradí Dash callback pro BUY/SELL.

```python
@ib_bp.route('/api/orders', methods=['POST'])
def place_order():
    body = request.get_json(silent=True) or {}
    symbol = (body.get('symbol') or '').upper()
    asset_type = normalize_asset_type(body.get('asset_type', 'STOCK'))
    exchange = body.get('exchange', 'SMART')
    action = (body.get('action') or '').upper()  # BUY or SELL
    quantity = body.get('quantity', 0)
    order_type = (body.get('order_type') or 'MARKET').upper()
    limit_price = body.get('limit_price')
    sl = body.get('sl')
    tp = body.get('tp')
    note = body.get('note', '')

    if not symbol or action not in ('BUY', 'SELL') or not quantity:
        return jsonify({'ok': False, 'message': 'Missing required fields: symbol, action, quantity'}), 400

    if not ib_gateway.is_connected():
        return jsonify({'ok': False, 'message': 'Not connected to IB Gateway'}), 503

    result = ib_gateway.place_order(
        symbol=symbol,
        action=action,
        quantity=quantity,
        order_type=order_type,
        limit_price=limit_price,
        asset_type=asset_type,
    )

    # Uložit obchod do trades.json
    if result.get('success'):
        from modules.trade_tracker import trade_tracker
        trade_tracker.add_trade(
            symbol=symbol,
            side=action,
            qty=quantity,
            order_type=order_type,
            entry_price=result.get('fill_price') or result.get('avg_price') or limit_price,
            sl=sl,
            tp=tp,
            note=note,
            asset_type=asset_type,
        )

    return jsonify({
        'ok': result.get('success', False),
        'fill_price': result.get('fill_price') or result.get('avg_price'),
        'message': result.get('message', ''),
    })
```

**Vstup:** JSON body: `{ symbol, asset_type, exchange, action, quantity, order_type, limit_price?, sl?, tp?, note? }`
**Výstup:** `{ "ok": true, "fill_price": 182.34, "message": "Filled" }`
**Ověření:** Tento endpoint vyžaduje aktivní IB připojení a opatrnost (reálný příkaz i na paper). Test:
1. Spustit app
2. `Invoke-WebRequest -Method POST -Uri http://localhost:8050/api/orders -ContentType "application/json" -Body '{"symbol":"AAPL","action":"BUY","quantity":1,"order_type":"MARKET","asset_type":"STOCK"}' | Select-Object -ExpandProperty Content`
3. Ověřit `ok: true` a přítomnost fill_price.
**Závislosti:** Krok 1.2. Závisí na funkčním `ib_gateway.place_order()` a `trade_tracker.add_trade()`.
**Akceptační kritéria:** HTTP 200 s `ok: true` při úspěchu. HTTP 400 při chybějících polích. HTTP 503 při odpojeném IB.

---

### Krok 1.9: Vytvořit `backend/local_api.py` — scaffold s Blueprint

**Soubor:** `backend/local_api.py`
**Akce:** Vytvořit soubor s Flask Blueprint `local_bp`. Importovat `trade_tracker`, `config_store`.

```python
from flask import Blueprint, jsonify, request
from modules.trade_tracker import trade_tracker
from modules.config_store import config_store
from contract_utils import normalize_asset_type

local_bp = Blueprint('local_api', __name__)
```

**Výstup:** Soubor existuje, importuje se.
**Ověření:** `python3.11 -c "from backend.local_api import local_bp; print('ok')"`
**Závislosti:** Krok 1.0

---

### Krok 1.10: Registrace `local_bp` v `app.py`

**Soubor:** `app.py`
**Akce:** Přidat pod registraci `ib_bp`:
```python
from backend.local_api import local_bp
server.register_blueprint(local_bp)
```
**Výstup:** Server startuje bez chyb.
**Ověření:** Spustit app, ověřit start bez chyb.
**Závislosti:** Krok 1.9

---

### Krok 1.11: Migrace `/api/trades/open` do `local_api.py`

**Soubor:** `backend/local_api.py`
**Akce:** Přesunout logiku z `app.py` (řádky 128–133):
```python
@local_bp.route('/api/trades/open', methods=['GET'])
def trades_open():
    trades = trade_tracker.get_open_trades()
    for t in trades:
        t['entry_time_fmt'] = trade_tracker.fmt_time(t.get('entry_time'))
    return jsonify({'ok': True, 'trades': trades})
```

**Po ověření:** Smazat starý endpoint z `app.py` (řádky 128–133).

**Vstup:** Žádné.
**Výstup:** `{ "ok": true, "trades": [...] }`
**Ověření:** `Invoke-WebRequest -Uri http://localhost:8050/api/trades/open | Select-Object -ExpandProperty Content`
**Závislosti:** Krok 1.10
**Akceptační kritéria:** HTTP 200, `ok: true`, pole `trades`.

---

### Krok 1.12: Migrace `/api/trades/history` do `local_api.py`

**Soubor:** `backend/local_api.py`
**Akce:** Přesunout logiku z `app.py` (řádky 176–183):
```python
@local_bp.route('/api/trades/history', methods=['GET'])
def trades_history():
    limit = int(request.args.get('limit', 50))
    trades = trade_tracker.get_history(limit=limit)
    for t in trades:
        t['entry_time_fmt'] = trade_tracker.fmt_time(t.get('entry_time'))
        t['exit_time_fmt'] = trade_tracker.fmt_time(t.get('exit_time'))
    return jsonify({'ok': True, 'trades': trades})
```

**Po ověření:** Smazat starý endpoint z `app.py`.

**Vstup:** Query param `limit` (default 50).
**Výstup:** `{ "ok": true, "trades": [...] }`
**Ověření:** `Invoke-WebRequest -Uri http://localhost:8050/api/trades/history | Select-Object -ExpandProperty Content`
**Závislosti:** Krok 1.10
**Akceptační kritéria:** HTTP 200, `ok: true`, pole `trades` max 50 záznamů.

---

### Krok 1.13: Migrace `/api/trades/active_lines` do `local_api.py`

**Soubor:** `backend/local_api.py`
**Akce:** Přesunout logiku z `app.py` (řádky 136–173). Tato funkce čte z `trade_tracker` ale také volá `ib_gateway.get_positions()` pro live avgCost. Přesto patří do `local_api.py` protože primární zdroj je `trades.json`; IB pozice jsou jen enrichment.

```python
@local_bp.route('/api/trades/active_lines', methods=['GET'])
def trades_active_lines():
    import ib_gateway
    sym = (request.args.get('symbol') or 'AAPL').upper()
    asset_type = normalize_asset_type(request.args.get('asset_type', 'STOCK'))
    trades = []
    ib_positions = ib_gateway.get_positions() if ib_gateway.is_connected() else []
    for t in trade_tracker.get_open_trades():
        if t.get('symbol') != sym:
            continue
        if normalize_asset_type(t.get('asset_type', 'STOCK')) != asset_type:
            continue
        ib_pos = next((p for p in ib_positions if p['symbol'] == sym and
                       normalize_asset_type(p.get('asset_type', 'STOCK')) == asset_type), None)
        if ib_pos and ib_pos.get('avgCost'):
            entry_price = float(ib_pos['avgCost'])
        elif t.get('avg_cost'):
            entry_price = float(t['avg_cost'])
        else:
            entry_price = t.get('entry_price')
        trades.append({
            'entry_price': entry_price,
            'sl': t.get('sl'),
            'tp': t.get('tp'),
            'side': t.get('side'),
        })
    return jsonify(trades)
```

**Po ověření:** Smazat starý endpoint z `app.py`.

**Vstup:** Query: `symbol`, `asset_type`.
**Výstup:** `[{ "entry_price": 150.0, "sl": 148.0, "tp": 155.0, "side": "BUY" }]`
**Ověření:** `Invoke-WebRequest -Uri "http://localhost:8050/api/trades/active_lines?symbol=AAPL&asset_type=STOCK" | Select-Object -ExpandProperty Content`
**Závislosti:** Krok 1.10
**Akceptační kritéria:** HTTP 200, JSON pole (může být prázdné).

---

### Krok 1.14: Endpoint `/api/trades/breakeven/<id>`

**Soubor:** `backend/local_api.py`
**Akce:** Nový endpoint — nastaví SL obchodu na entry_price.

```python
@local_bp.route('/api/trades/breakeven/<trade_id>', methods=['POST'])
def trades_breakeven(trade_id):
    trade = trade_tracker.get_trade(trade_id)
    if not trade or trade.get('status') != 'open':
        return jsonify({'ok': False, 'error': 'trade_not_found'}), 404
    entry = trade.get('entry_price')
    if entry is None:
        return jsonify({'ok': False, 'error': 'no_entry_price'}), 400
    trade_tracker.update_trade(trade_id, {'sl': entry})
    return jsonify({'ok': True})
```

**Poznámka:** Ověřit že `trade_tracker.update_trade()` existuje. Pokud ne, přidat metodu do `modules/trade_tracker.py` — měla by přečíst všechny obchody, najít záznam podle ID, aktualizovat zadané klíče a atomicky uložit.

**Vstup:** URL: `trade_id`.
**Výstup:** `{ "ok": true }`
**Ověření:** Vytvořit testovací obchod, pak zavolat breakeven a ověřit že SL se změnil.
**Závislosti:** Krok 1.10. Možná nutnost přidat `update_trade()` do `trade_tracker.py`.
**Akceptační kritéria:** HTTP 200 s `ok: true`. SL v `trades.json` se rovná `entry_price`.

---

### Krok 1.15: Endpoint `/api/trades/patch/<id>`

**Soubor:** `backend/local_api.py`
**Akce:** Nový endpoint — aktualizuje SL nebo TP obchodu (z AI Apply MOVE_SL/MOVE_TP).

```python
@local_bp.route('/api/trades/patch/<trade_id>', methods=['POST'])
def trades_patch(trade_id):
    body = request.get_json(silent=True) or {}
    trade = trade_tracker.get_trade(trade_id)
    if not trade or trade.get('status') != 'open':
        return jsonify({'ok': False, 'error': 'trade_not_found'}), 404
    updates = {}
    if 'sl' in body:
        updates['sl'] = body['sl']
    if 'tp' in body:
        updates['tp'] = body['tp']
    if not updates:
        return jsonify({'ok': False, 'error': 'no_fields_to_update'}), 400
    trade_tracker.update_trade(trade_id, updates)
    return jsonify({'ok': True})
```

**Vstup:** URL: `trade_id`. JSON body: `{ sl?: number, tp?: number }`
**Výstup:** `{ "ok": true }`
**Ověření:** Zavolat s JSON body `{ "sl": 150.0 }`, ověřit změnu v `trades.json`.
**Závislosti:** Krok 1.14 (sdílí `update_trade()`).
**Akceptační kritéria:** HTTP 200, SL/TP aktualizováno.

---

### Krok 1.16: Migrace `/api/trades/close/<id>` do `local_api.py`

**Soubor:** `backend/local_api.py`
**Akce:** Přesunout logiku z `app.py` (řádky 186–207). Endpoint volá `ib_gateway.get_tick()` pro exit_price pokud chybí.

```python
@local_bp.route('/api/trades/close/<trade_id>', methods=['POST'])
def trade_close(trade_id):
    import ib_gateway
    body = request.get_json(silent=True) or {}
    exit_price = body.get('exit_price')
    if not exit_price:
        trade = trade_tracker.get_trade(trade_id)
        if trade:
            ticker = ib_gateway.get_tick(trade['symbol'], trade.get('asset_type', 'STOCK'))
            if ticker:
                exit_price = ticker.get('price') or ticker.get('last') or trade.get('entry_price')
    if not exit_price:
        return jsonify({'ok': False, 'error': 'exit_price_missing'}), 400
    updated = trade_tracker.close_trade(trade_id, exit_price)
    if not updated:
        return jsonify({'ok': False, 'error': 'trade_not_found_or_already_closed'}), 404
    updated['exit_time_fmt'] = trade_tracker.fmt_time(updated.get('exit_time'))
    updated['entry_time_fmt'] = trade_tracker.fmt_time(updated.get('entry_time'))
    return jsonify({'ok': True, 'trade': updated})
```

**Po ověření:** Smazat starý endpoint z `app.py`.

**Vstup:** URL: `trade_id`. Volitelné JSON body: `{ exit_price?: number }`.
**Výstup:** `{ "ok": true, "trade": {...} }`
**Závislosti:** Krok 1.10
**Akceptační kritéria:** HTTP 200, obchod uzavřen.

---

### Krok 1.17: Migrace `/api/trades/close_all` do `local_api.py`

**Soubor:** `backend/local_api.py`
**Akce:** Přesunout logiku z `app.py` (řádky 210–222).

```python
@local_bp.route('/api/trades/close_all', methods=['POST'])
def trades_close_all():
    import ib_gateway
    open_trades = trade_tracker.get_open_trades()
    symbols = list({(t['symbol'], t.get('asset_type', 'STOCK')) for t in open_trades})
    exit_prices = {}
    for sym, asset_type in symbols:
        ticker = ib_gateway.get_tick(sym, asset_type)
        if ticker:
            p = ticker.get('price') or ticker.get('last')
            if p:
                exit_prices[sym] = p
    closed = trade_tracker.close_all_open(exit_prices)
    return jsonify({'ok': True, 'closed': len(closed), 'trades': closed})
```

**Po ověření:** Smazat starý endpoint z `app.py`.

**Vstup:** Žádné.
**Výstup:** `{ "ok": true, "closed": 3, "trades": [...] }`
**Závislosti:** Krok 1.10
**Akceptační kritéria:** HTTP 200, správný počet uzavřených.

---

### Krok 1.18: Endpoint `/api/settings` — GET + POST

**Soubor:** `backend/local_api.py`
**Akce:** Dva endpointy pod jednou URL, rozlišené metodou.

```python
@local_bp.route('/api/settings', methods=['GET'])
def settings_get():
    return jsonify(config_store.get_all())

@local_bp.route('/api/settings', methods=['POST'])
def settings_post():
    body = request.get_json(silent=True) or {}
    for key, value in body.items():
        config_store.set(key, value)
    return jsonify({'ok': True})
```

**Vstup GET:** Žádné.
**Výstup GET:** Celý config objekt `{ "default_symbol": "AAPL", ... }`
**Vstup POST:** JSON body s klíč-hodnota páry.
**Výstup POST:** `{ "ok": true }`
**Ověření:**
1. GET: `Invoke-WebRequest -Uri http://localhost:8050/api/settings | Select-Object -ExpandProperty Content`
2. POST: `Invoke-WebRequest -Method POST -Uri http://localhost:8050/api/settings -ContentType "application/json" -Body '{"default_symbol":"TSLA"}' | Select-Object -ExpandProperty Content`
3. Ověřit GET po POST vrací aktualizovanou hodnotu.
**Závislosti:** Krok 1.10
**Akceptační kritéria:** GET vrací config, POST mění hodnoty a následný GET je reflektuje.

---

### Krok 1.19: Vytvořit `backend/indicators.py` — scaffold s Blueprint

**Soubor:** `backend/indicators.py`
**Akce:** Vytvořit soubor s Flask Blueprint `indicators_bp`.

```python
from flask import Blueprint, jsonify, request
from modules.indicators import SMA, EMA, RSI, MACD
from modules.data_store import data_store
from contract_utils import normalize_asset_type, get_cache_symbol

indicators_bp = Blueprint('indicators_api', __name__)
```

**Výstup:** Soubor existuje.
**Ověření:** `python3.11 -c "from backend.indicators import indicators_bp; print('ok')"`
**Závislosti:** Krok 1.0

---

### Krok 1.20: Registrace `indicators_bp` v `app.py`

**Soubor:** `app.py`
**Akce:** Přidat:
```python
from backend.indicators import indicators_bp
server.register_blueprint(indicators_bp)
```
**Závislosti:** Krok 1.19

---

### Krok 1.21: Migrace `/api/indicators/<symbol>` do Blueprint

**Soubor:** `backend/indicators.py`
**Akce:** Přesunout logiku z `app.py` (řádky 86–121). Změnit URL z `/<symbol>/<tf>` na `/<symbol>` s `tf` jako query parametrem (dle PLAN.md).

```python
@indicators_bp.route('/api/indicators/<symbol>')
def get_indicators(symbol):
    sym = symbol.upper()
    tf = request.args.get('tf', '5 mins').replace('_', ' ')
    asset_type = normalize_asset_type(request.args.get('asset_type', 'STOCK'))
    active = [x.strip() for x in request.args.get('active', 'ema,rsi').split(',') if x.strip()]

    bars = data_store.get_bars(get_cache_symbol(sym, asset_type), tf)
    if not bars:
        return jsonify({'ok': False, 'error': 'no_data', 'bars': 0,
                        'symbol': sym, 'asset_type': asset_type, 'tf': tf})

    result = {'ok': True, 'symbol': sym, 'asset_type': asset_type, 'tf': tf, 'bars': len(bars)}
    try:
        if 'sma' in active:
            p = int(request.args.get('sma_p', 20))
            result['sma'] = SMA(period=p).calculate(bars)
            result['sma_period'] = p
        if 'ema' in active:
            p = int(request.args.get('ema_p', 20))
            result['ema'] = EMA(period=p).calculate(bars)
            result['ema_period'] = p
        if 'rsi' in active:
            p = int(request.args.get('rsi_p', 14))
            result['rsi'] = RSI(period=p).calculate(bars)
            result['rsi_period'] = p
        if 'macd' in active:
            fast = int(request.args.get('macd_fast', 12))
            slow = int(request.args.get('macd_slow', 26))
            sig = int(request.args.get('macd_sig', 9))
            result['macd'] = MACD(fast=fast, slow=slow, signal=sig).calculate(bars)
    except Exception as e:
        result['ok'] = False
        result['warning'] = str(e)

    return jsonify(result)
```

**Po ověření:** Smazat starý endpoint z `app.py` (řádky 86–121).

**Vstup:** URL: `symbol`. Query: `tf`, `asset_type`, `active`, `sma_p`, `ema_p`, `rsi_p`, `macd_fast`, `macd_slow`, `macd_sig`.
**Výstup:** `{ "ok": true, "sma": [...], "ema": [...], "rsi": [...], "macd": {...} }`
**Ověření:** `Invoke-WebRequest -Uri "http://localhost:8050/api/indicators/AAPL?tf=5+mins&active=sma,ema" | Select-Object -ExpandProperty Content`
**Závislosti:** Krok 1.20
**Akceptační kritéria:** HTTP 200, obsahuje požadované indikátory.

---

### Krok 1.22: Vytvořit `backend/openrouter_api.py` — scaffold s Blueprint

**Soubor:** `backend/openrouter_api.py`
**Akce:** Vytvořit soubor s Flask Blueprint `ai_bp`. Importovat `config_store`, `requests` (HTTP klient).

```python
from flask import Blueprint, jsonify, request
from modules.config_store import config_store
import requests as http_client

ai_bp = Blueprint('ai_api', __name__)
```

**Výstup:** Soubor existuje.
**Ověření:** `python3.11 -c "from backend.openrouter_api import ai_bp; print('ok')"`
**Závislosti:** Krok 1.0

---

### Krok 1.23: Registrace `ai_bp` v `app.py`

**Soubor:** `app.py`
**Akce:** Přidat:
```python
from backend.openrouter_api import ai_bp
server.register_blueprint(ai_bp)
```
**Závislosti:** Krok 1.22

---

### Krok 1.24: Endpoint `/api/ai/evaluate` — POST

**Soubor:** `backend/openrouter_api.py`
**Akce:** Implementovat endpoint který přijme kontext (bary, indikátory, account info, strategy) a pošle do OpenRouter API.

```python
@ai_bp.route('/api/ai/evaluate', methods=['POST'])
def ai_evaluate():
    body = request.get_json(silent=True) or {}
    api_key = config_store.get('openrouter_api_key', '')
    model = config_store.get('llm_model', '')

    if not api_key or not model:
        return jsonify({'ok': False, 'error': 'Missing OpenRouter API key or model in Settings'}), 400

    # Sestavit prompt z dat
    graphs = body.get('graphs', [])
    indicators = body.get('indicators', {})
    account = body.get('account', {})
    strategy = config_store.get('strategy_text', '')
    mm_rules = config_store.get('mm_rules_text', '')

    # System prompt instruující AI jako trading analytika
    system_prompt = (
        "You are a professional trading analyst. Analyze the provided market data "
        "and return a JSON object with these exact keys: "
        "recommendation (BUY/SELL/HOLD), order_type (MARKET/LIMIT), "
        "entry_price (number), sl (number), tp (number), quantity (integer), "
        "rr_ratio (string like '1:2.4'), reason (string), annotations (array of objects)."
    )

    # User prompt s daty
    user_prompt = f"""
Strategy: {strategy}
Money Management: {mm_rules}
Account: Balance=${account.get('net_liquidation', 0)}, Buying Power=${account.get('buying_power', 0)}

Market Data:
"""
    for g in graphs:
        user_prompt += f"\n--- {g.get('symbol')} {g.get('tf')} ({g.get('asset_type')}) ---\n"
        bars = g.get('bars', [])
        for bar in bars[-50:]:  # Omezit na posledních 50 pro prompt
            user_prompt += f"T={bar.get('time')} O={bar.get('open')} H={bar.get('high')} L={bar.get('low')} C={bar.get('close')} V={bar.get('volume')}\n"

    if indicators:
        user_prompt += f"\nIndicators: {indicators}\n"

    user_prompt += "\nProvide your analysis as a valid JSON object."

    try:
        resp = http_client.post(
            'https://openrouter.ai/api/v1/chat/completions',
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
            },
            json={
                'model': model,
                'messages': [
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': user_prompt},
                ],
                'response_format': {'type': 'json_object'},
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data.get('choices', [{}])[0].get('message', {}).get('content', '{}')

        import json
        parsed = json.loads(content)
        return jsonify(parsed)

    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500
```

**Vstup:** JSON body dle PLAN.md: `{ primary_graph_index, graphs, indicators, account }`
**Výstup:** `{ recommendation, order_type, entry_price, sl, tp, quantity, rr_ratio, reason, annotations }`
**Ověření:** Bez API klíče vrací HTTP 400 s chybou. S API klíčem a testovacími daty vrací AI odpověď.
**Závislosti:** Krok 1.23. Nutné mít `requests` v `requirements.txt` (již by tam měl být).
**Akceptační kritéria:** HTTP 400 bez klíče. HTTP 200 s validním JSON při správném volání.

---

### Krok 1.25: Endpoint `/api/ai/check_position` — POST

**Soubor:** `backend/openrouter_api.py`
**Akce:** Implementovat endpoint pro kontrolu běžící pozice.

```python
@ai_bp.route('/api/ai/check_position', methods=['POST'])
def ai_check_position():
    body = request.get_json(silent=True) or {}
    api_key = config_store.get('openrouter_api_key', '')
    model = config_store.get('llm_model', '')

    if not api_key or not model:
        return jsonify({'ok': False, 'error': 'Missing OpenRouter API key or model in Settings'}), 400

    graphs = body.get('graphs', [])
    indicators = body.get('indicators', {})
    trade = body.get('trade', {})
    strategy = config_store.get('strategy_text', '')
    # MM pravidla se NEPOSÍLAJÍ — jde o řízení běžící pozice

    system_prompt = (
        "You are a professional trading analyst reviewing an open position. "
        "Return a JSON object with these exact keys: "
        "action (HOLD/MOVE_SL/MOVE_TP/CLOSE), new_sl (number or null), "
        "new_tp (number or null), reason (string)."
    )

    user_prompt = f"""
Strategy: {strategy}
Current Position: Entry={trade.get('entry_price')}, SL={trade.get('sl')}, TP={trade.get('tp')}, P&L={trade.get('pnl')}

Market Data:
"""
    for g in graphs:
        user_prompt += f"\n--- {g.get('symbol')} {g.get('tf')} ({g.get('asset_type')}) ---\n"
        bars = g.get('bars', [])
        for bar in bars[-50:]:
            user_prompt += f"T={bar.get('time')} O={bar.get('open')} H={bar.get('high')} L={bar.get('low')} C={bar.get('close')} V={bar.get('volume')}\n"

    if indicators:
        user_prompt += f"\nIndicators: {indicators}\n"

    user_prompt += "\nProvide your analysis as a valid JSON object."

    try:
        resp = http_client.post(
            'https://openrouter.ai/api/v1/chat/completions',
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
            },
            json={
                'model': model,
                'messages': [
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': user_prompt},
                ],
                'response_format': {'type': 'json_object'},
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data.get('choices', [{}])[0].get('message', {}).get('content', '{}')

        import json
        parsed = json.loads(content)
        return jsonify(parsed)

    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500
```

**Vstup:** JSON body: `{ trade_id, primary_graph_index, graphs, indicators, trade: { entry_price, sl, tp, pnl } }`
**Výstup:** `{ action, new_sl, new_tp, reason }`
**Ověření:** Stejné jako Krok 1.24 — HTTP 400 bez klíče, HTTP 200 s daty.
**Závislosti:** Krok 1.23
**Akceptační kritéria:** Validní JSON odpověď s klíči `action`, `new_sl`, `new_tp`, `reason`.

---

### Krok 1.26: Odstranění starých endpointů z `app.py`

**Soubor:** `app.py`
**Akce:** Smazat VŠECHNY `@server.route(...)` bloky které byly migrovány do blueprintů:
- `/api/tick/<symbol>` (řádky 74–79)
- `/api/deep_load_status/<symbol>/<tf>` (řádky 81–84) — legacy, nenachází se v PLAN.md, smazat úplně
- `/api/indicators/<symbol>/<tf>` (řádky 86–121)
- `/api/trades/open` (řádky 128–133)
- `/api/trades/active_lines` (řádky 136–173)
- `/api/trades/history` (řádky 176–183)
- `/api/trades/close/<trade_id>` (řádky 186–207)
- `/api/trades/close_all` (řádky 210–222)

Ponechat v `app.py` pouze: import blueprintů, layout, Dash callbacks.

**Vstup:** Nic.
**Výstup:** `app.py` neobsahuje žádné `@server.route` definice.
**Ověření:**
1. `Select-String -Path app.py -Pattern "@server.route"` — musí vrátit 0 výsledků.
2. Spustit app, ověřit že všechny endpointy stále fungují přes blueprinty.
3. Otestovat klíčové endpointy:
   - `GET /api/connection/status`
   - `GET /api/tick/AAPL?asset_type=STOCK`
   - `GET /api/trades/open`
   - `GET /api/settings`
   - `GET /api/indicators/AAPL?tf=5+mins&active=sma`
**Závislosti:** Kroky 1.6, 1.7, 1.8, 1.11–1.18, 1.21
**Akceptační kritéria:** Žádný `@server.route` v `app.py`. Všechny endpointy odpovídají HTTP 200.

---

### Krok 1.27: Přidat `update_trade()` do `trade_tracker.py` (pokud neexistuje)

**Soubor:** `modules/trade_tracker.py`
**Akce:** Zkontrolovat zda existuje metoda `update_trade(trade_id, updates_dict)`. Pokud neexistuje, přidat:

```python
def update_trade(self, trade_id: str, updates: dict) -> bool:
    """Update fields of a trade by ID. Only updates provided keys."""
    with self._lock:
        trades = self._read()
        for t in trades:
            if t.get('id') == trade_id:
                t.update(updates)
                self._write_atomic(trades)
                return True
        return False
```

**Vstup:** `trade_id` (string), `updates` (dict s klíči k aktualizaci).
**Výstup:** `True` pokud nalezeno a aktualizováno, `False` pokud ID nenalezeno.
**Ověření:** `python3.11 -c "from modules.trade_tracker import trade_tracker; print(hasattr(trade_tracker, 'update_trade'))"`
**Závislosti:** Žádné. Musí být hotovo před 1.14.
**Akceptační kritéria:** Metoda existuje a vrací bool.

---

### Krok 1.28: Ověření `ib_gateway.get_candles()` — podpora `end_before`

**Soubor:** `ib_gateway.py`
**Akce:** Zkontrolovat signaturu `get_candles()`. Pokud nepodporuje parametr pro koncový čas (pro Load More), přidat parametr `end_before: int = None`. Interně konvertovat unix timestamp na IB formát `endDateTime` (string `'YYYYMMDD HH:MM:SS'`) a předat do `reqHistoricalData`.

Pokud `end_before` je None → `endDateTime=''` (= now, pro Reset).
Pokud `end_before` je int timestamp → `endDateTime=datetime.utcfromtimestamp(end_before).strftime('%Y%m%d %H:%M:%S')`.

**Vstup:** Stávající parametry + nový `end_before`.
**Výstup:** Seznam barů.
**Ověření:** Použít `tools/ib_api_tester.py` — zavolat `get_candles` s i bez `end_before` a porovnat výstupy.
**Závislosti:** Žádné. Musí být hotovo před 1.7.
**Akceptační kritéria:** `get_candles(symbol, tf, count=20)` vrací bary do teď. `get_candles(symbol, tf, count=20, end_before=<timestamp>)` vrací starší bary.

---

### Krok 1.29: Kompletní integrační test

**Soubor:** Žádný nový soubor. Spustit app a otestovat ručně.
**Akce:** Spustit aplikaci a sekvenčně otestovat každý endpoint:

```powershell
# 1. Connection
Invoke-WebRequest -Uri http://localhost:8050/api/connection/status | Select-Object -ExpandProperty Content

# 2. Market hours
Invoke-WebRequest -Uri http://localhost:8050/api/market/hours | Select-Object -ExpandProperty Content

# 3. Account info
Invoke-WebRequest -Uri http://localhost:8050/api/account/info | Select-Object -ExpandProperty Content

# 4. Tick
Invoke-WebRequest -Uri "http://localhost:8050/api/tick/AAPL?asset_type=STOCK" | Select-Object -ExpandProperty Content

# 5. Bars (reset)
Invoke-WebRequest -Uri "http://localhost:8050/api/bars/AAPL?tf=5+mins&asset_type=STOCK&count=20&end_time=now" | Select-Object -ExpandProperty Content

# 6. Indicators
Invoke-WebRequest -Uri "http://localhost:8050/api/indicators/AAPL?tf=5+mins&active=sma,ema,rsi,macd" | Select-Object -ExpandProperty Content

# 7. Settings GET
Invoke-WebRequest -Uri http://localhost:8050/api/settings | Select-Object -ExpandProperty Content

# 8. Settings POST
Invoke-WebRequest -Method POST -Uri http://localhost:8050/api/settings -ContentType "application/json" -Body '{"test_key":"test_value"}' | Select-Object -ExpandProperty Content

# 9. Trades open
Invoke-WebRequest -Uri http://localhost:8050/api/trades/open | Select-Object -ExpandProperty Content

# 10. Trades history
Invoke-WebRequest -Uri http://localhost:8050/api/trades/history | Select-Object -ExpandProperty Content

# 11. Active lines
Invoke-WebRequest -Uri "http://localhost:8050/api/trades/active_lines?symbol=AAPL&asset_type=STOCK" | Select-Object -ExpandProperty Content
```

**Akceptační kritéria:** Všech 11 endpointů vrací HTTP 200 s validním JSON. Žádný endpoint z `app.py` (žádný `@server.route`). App startuje bez chyb.

---

## Fáze 2 — UI Refactoring

> **POZN:** Tato fáze se neplánuje nyní. Začne až po kompletním dokončení a otestování Fáze 1. UI bude přestavěno tak, aby komunikovalo výhradně přes nové HTTP endpointy z blueprintů.

---

## Doporučené pořadí provádění

Respektuje závislosti:

1. **1.0** — `backend/__init__.py`
2. **1.27** — `update_trade()` v trade_tracker (prerekvizita pro 1.14, 1.15)
3. **1.28** — `get_candles()` end_before v ib_gateway (prerekvizita pro 1.7)
4. **1.1** — `backend/ib_api.py` scaffold
5. **1.2** — Registrace ib_bp
6. **1.3** — `/api/connection/status`
7. **1.4** — `/api/market/hours`
8. **1.5** — `/api/account/info`
9. **1.6** — Migrace `/api/tick`
10. **1.7** — `/api/bars`
11. **1.8** — `/api/orders`
12. **1.9** — `backend/local_api.py` scaffold
13. **1.10** — Registrace local_bp
14. **1.11** — Migrace `/api/trades/open`
15. **1.12** — Migrace `/api/trades/history`
16. **1.13** — Migrace `/api/trades/active_lines`
17. **1.14** — `/api/trades/breakeven`
18. **1.15** — `/api/trades/patch`
19. **1.16** — Migrace `/api/trades/close`
20. **1.17** — Migrace `/api/trades/close_all`
21. **1.18** — `/api/settings`
22. **1.19** — `backend/indicators.py` scaffold
23. **1.20** — Registrace indicators_bp
24. **1.21** — Migrace `/api/indicators`
25. **1.22** — `backend/openrouter_api.py` scaffold
26. **1.23** — Registrace ai_bp
27. **1.24** — `/api/ai/evaluate`
28. **1.25** — `/api/ai/check_position`
29. **1.26** — Smazání starých rout z app.py
30. **1.29** — Kompletní integrační test

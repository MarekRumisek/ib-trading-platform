"""
IB Trading Platform - Diagnosticky nastroj
==========================================
Spustit: python debug.py

Testuje vsechny komponenty jeden po druhem a jasne rici
co funguje a co ne - aby bylo jasne kde je problem.
"""

import sys
import os
import json
import time

SEP = "=" * 60

print(SEP)
print("  IB TRADING PLATFORM - DIAGNOSTIKA")
print(SEP)

# ── 1. Python balicky ─────────────────────────────────────────
print("\n[1] Python balicky...")
for pkg in ['dash', 'flask', 'ib_async', 'pandas']:
    try:
        mod = __import__(pkg)
        ver = getattr(mod, '__version__', '?')
        print(f"  OK  {pkg} (v{ver})")
    except ImportError:
        print(f"  CHYBI  {pkg}  -->  pip install {pkg}")

# ── 2. Soubory ────────────────────────────────────────────────
print("\n[2] Potrebne soubory...")
for f in ['app.py', 'ib_connector.py', 'config.py',
          'assets/chart_manager.js']:
    if os.path.exists(f):
        size = os.path.getsize(f)
        print(f"  OK  {f}  ({size} bytes)")
    else:
        print(f"  CHYBI  {f}  <-- PROBLEM!")

# ── 3. Obsah chart_manager.js ─────────────────────────────────
print("\n[3] Kontrola chart_manager.js...")
try:
    with open('assets/chart_manager.js', 'r', encoding='utf-8') as fh:
        js = fh.read()
    checks = [
        ('addCandlestickSeries', 'LWC v4 API'),
        ('lwcManager',           'verejne API okno'),
        ('offsetWidth',          'oprava sirky grafu'),
        ('chart-trigger-store',  'POZOR: toto patri do app.py ne JS'),
        ('pollTick',             'live tick polling'),
    ]
    for keyword, desc in checks:
        found = keyword in js
        mark  = 'OK  ' if found else 'NENI'
        print(f"  {mark}  '{keyword}' ({desc})")
except Exception as e:
    print(f"  CHYBA cteni souboru: {e}")

# ── 4. Config ─────────────────────────────────────────────────
print("\n[4] Konfigurace (config.py)...")
try:
    import config
    print(f"  Host:      {config.IB_HOST}")
    print(f"  Port:      {config.IB_PORT}")
    print(f"  ClientID:  {config.IB_CLIENT_ID}")
    if hasattr(config, 'CONNECTION_LABEL'):
        print(f"  Rezim:     {config.CONNECTION_LABEL}")
except Exception as e:
    print(f"  CHYBA: {e}")
    sys.exit(1)

# ── 5. Pripojeni na IB ────────────────────────────────────────
print(f"\n[5] Pripojeni na IB Gateway/TWS ({config.IB_HOST}:{config.IB_PORT})...")
try:
    from ib_connector import IBConnector
    ib = IBConnector()
    ok = ib.connect()
except Exception as e:
    print(f"  VYJIMKA pri importu/connect: {e}")
    sys.exit(1)

if not ok:
    print("  SELHALO pripojeni!")
    print("  --> Je spusteny IB Gateway nebo TWS?")
    print("  --> Je povolene API v nastaveni TWS?")
    print(f"  --> Zkus port 7497 (TWS paper) nebo 4002 (Gateway paper)")
    sys.exit(1)

print(f"  OK  Pripojeno! Ucet: {ib.account_id}")

# ── 6. Kvalifikace kontraktu ──────────────────────────────────
print("\n[6] Kvalifikace kontraktu AAPL...")
try:
    c = ib._get_qualified_contract('AAPL')
    print(f"  OK  conId = {c.conId}, exchange = {c.exchange}")
except Exception as e:
    print(f"  CHYBA: {e}")

# ── 7. Historicka data ────────────────────────────────────────
print("\n[7] Historicka data AAPL (1 den, 5-minutove svicky)...")
try:
    bars = ib.get_historical_data('AAPL', '1 D', '5 mins')
    if bars:
        print(f"  OK  Nacten {len(bars)} baru")
        print(f"  Prvni bar: time={bars[0]['time']}, open={bars[0]['open']}, "
              f"high={bars[0]['high']}, low={bars[0]['low']}, close={bars[0]['close']}")
        print(f"  Posledni:  time={bars[-1]['time']}, close={bars[-1]['close']}")
        print(f"  Pozn: 'time' musi byt cele cislo (Unix timestamp), ne retezec")
        if isinstance(bars[0]['time'], int):
            print("  OK  'time' je int (spravne pro Lightweight Charts)")
        else:
            print(f"  PROBLEM  'time' je {type(bars[0]['time']).__name__} misto int!")
    else:
        print("  ZADNA DATA  --> trh je mozna zavreny nebo chyba IB")
except Exception as e:
    print(f"  CHYBA: {e}")

# ── 8. Live ticker ────────────────────────────────────────────
print("\n[8] Live ticker AAPL...")
try:
    t = ib.get_ticker('AAPL')
    if t:
        print(f"  OK  last={t['last']}, bid={t['bid']}, ask={t['ask']}, close={t['close']}")
        if t['last'] == 0 and t['close'] == 0:
            print("  POZOR  Vsechny ceny jsou 0 --> trh je zavreny nebo delayed data")
    else:
        print("  ZADNA DATA")
except Exception as e:
    print(f"  CHYBA: {e}")

# ── 9. /api/tick simulace ─────────────────────────────────────
print("\n[9] Simulace /api/tick/AAPL endpoint...")
try:
    from datetime import datetime
    ticker2 = ib.get_ticker('AAPL')
    if ticker2:
        price = ticker2['last'] if ticker2['last'] > 0 else ticker2['close']
        payload = {'time': int(datetime.now().timestamp()), 'price': price}
        print(f"  OK  Endpoint by vratil: {json.dumps(payload)}")
    else:
        print("  PROBLEM  ticker je None --> endpoint vrati 404")
except Exception as e:
    print(f"  CHYBA: {e}")

# ── 10. app.py verze kontrola ─────────────────────────────────
print("\n[10] Kontrola verze app.py...")
try:
    with open('app.py', 'r', encoding='utf-8') as fh:
        src = fh.read()
    checks_app = [
        ('chart-trigger-store',      'dummy Store output fix'),
        ('lightweight-charts@4.2.0', 'CDN pinned na v4.2.0'),
        ('_get_qualified_contract',  'pouziva qualifyContracts'),
    ]
    for keyword, desc in checks_app:
        found = keyword in src
        mark  = 'OK  ' if found else 'STARA VERZE'
        print(f"  {mark}  '{keyword}' ({desc})")
    if 'Version: 2.0.2' in src:
        print("  OK  app.py je verze 2.0.2 (nejnovejsi)")
    else:
        print("  POZOR  Mas starou verzi app.py!")
        print("         --> Spust: git pull origin feature/lightweight-charts")
except Exception as e:
    print(f"  CHYBA: {e}")

# ── Zaver ─────────────────────────────────────────────────────
print("\n" + SEP)
print("  DIAGNOSTIKA HOTOVA")
print(SEP)
print("\nCo delat dal:")
print("  1. Zkopiruj cely vystup a posli mi ho")
print("  2. Kdyz je vse OK --> spust app.py a v prohlizeci stiskni Ctrl+Shift+R")
print("     (to vycisti cache - jinak prohlizec pouziva stary JS soubor!)")
print()

ib.disconnect()

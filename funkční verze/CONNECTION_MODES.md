# IB Trading Platform - Connection Modes Guide

## 📡 Available Connection Modes

Aplikace podporuje 4 různé způsoby připojení k Interactive Brokers:

| Mode | Port | Type | Money | Description |
|------|------|------|-------|-------------|
| **TWS_PAPER** | 7497 | TWS | Paper | ✅ **Výchozí** - Paper Trading TWS (SAFE) |
| **GATEWAY_PAPER** | 4002 | Gateway | Paper | ✅ Paper Trading Gateway (SAFE) |
| **TWS_LIVE** | 7496 | TWS | Live | ⚠️ Live Trading TWS (REAL MONEY!) |
| **GATEWAY_LIVE** | 4001 | Gateway | Live | ⚠️ Live Trading Gateway (REAL MONEY!) |

## 🔄 Jak přepínat mezi režimy

### 1️⃣ Před spuštěním aplikace (Environment Variable)

#### Windows PowerShell:
```powershell
# Paper Trading TWS (výchozí)
$env:IB_CONNECTION_MODE="TWS_PAPER"
python app.py

# Paper Trading Gateway
$env:IB_CONNECTION_MODE="GATEWAY_PAPER"
python app.py

# Live Trading TWS (⚠️ REAL MONEY!)
$env:IB_CONNECTION_MODE="TWS_LIVE"
python app.py

# Live Trading Gateway (⚠️ REAL MONEY!)
$env:IB_CONNECTION_MODE="GATEWAY_LIVE"
python app.py
```

#### Linux/Mac:
```bash
# Paper Trading TWS (výchozí)
export IB_CONNECTION_MODE="TWS_PAPER"
python app.py

# Paper Trading Gateway
export IB_CONNECTION_MODE="GATEWAY_PAPER"
python app.py

# Live Trading TWS (⚠️ REAL MONEY!)
export IB_CONNECTION_MODE="TWS_LIVE"
python app.py

# Live Trading Gateway (⚠️ REAL MONEY!)
export IB_CONNECTION_MODE="GATEWAY_LIVE"
python app.py
```

### 2️⃣ Za běhu aplikace (Runtime Switching)

Přidat do `app.py` nebo skriptu:

```python
import config

# Přepínání mezi režimy
config.set_connection_mode('TWS_PAPER')      # Paper TWS
config.set_connection_mode('GATEWAY_PAPER')  # Paper Gateway
config.set_connection_mode('TWS_LIVE')       # Live TWS ⚠️
config.set_connection_mode('GATEWAY_LIVE')   # Live Gateway ⚠️

# Kontrola aktuálního režimu
print(f"Current mode: {config.CONNECTION_LABEL}")
print(f"Port: {config.IB_PORT}")
print(f"Is live? {config.is_live_trading()}")

# Získání všech dostupných režimů
modes = config.get_available_modes()
for mode_name, info in modes.items():
    print(f"{mode_name}: {info['label']} (Port {info['port']})")
```

### 3️⃣ Editace config.py (Permanent Change)

Otevři `config.py` a změň řádek:

```python
# Změň tuto hodnotu:
CONNECTION_MODE = 'TWS_PAPER'  # nebo 'GATEWAY_PAPER', 'TWS_LIVE', 'GATEWAY_LIVE'
```

## 🔧 Jak nastavit TWS/Gateway

### Pro Paper Trading:
1. Spušť **Paper Trading TWS** nebo **Paper Trading Gateway**
2. File → Global Configuration → API → Settings:
   - ✓ **Enable ActiveX and Socket Clients** = ON
   - ✗ **Read-Only API** = OFF (důležité!)
   - Port: 7497 (TWS) nebo 4002 (Gateway)
3. Restartuj TWS/Gateway
4. Potvrdit paper trading dialog při prvním připojení

### Pro Live Trading:
1. Spušť **Live TWS** nebo **Live Gateway**
2. Stejné nastavení jako výše
3. Port: 7496 (TWS) nebo 4001 (Gateway)
4. ⚠️ **BUĎ VELMI OPATRNÝ - TYD POUŽÍVÁŠ SKUTEČNÉ PENÍZE!**

## 📊 Debug Režim

V `config.py` můžeš zapnout/vypnout debug výpisy:

```python
# Debug Settings
DEBUG_ORDERS = True        # Detailní výpisy pro orders
DEBUG_CONNECTION = True    # Detailní výpisy pro připojení
```

Když je `DEBUG_ORDERS = True`, vidíš v konzoli:
- 📤 Order detaily
- 📊 Status změny (PendingSubmit → PreSubmitted → Submitted → Filled)
- ⚠️ Warnings z IB API
- ❌ Errors z IB API
- 🎉 Úspěšné dokončení

## ✅ Test Skripty

### Test Connection & Order:
```bash
python test_order.py
```

Tento script:
- Připojí se k IB
- Umístí testovací market order (BUY 1 AAPL)
- Sleduje status 15 sekund
- Zobrazuje všechny warnings a errors
- Ukazuje troubleshooting tipy pokud nefunguje

## 📝 Příklad použití

```python
from ib_connector import IBConnector
import config

# Nastav režim (volitelné - výchozí je TWS_PAPER)
config.set_connection_mode('TWS_PAPER')

# Vytvoř connector
ib = IBConnector()

# Připoj se
if ib.connect():
    print("Connected!")
    
    # Umísti order
    result = ib.place_order(
        symbol='AAPL',
        action='BUY',
        quantity=1,
        order_type='MARKET'
    )
    
    if result['success']:
        print(f"✅ Order successful! ID: {result['order_id']}")
        print(f"   Status: {result['status']}")
    else:
        print(f"❌ Order failed: {result['error']}")
    
    # Odpoj se
    ib.disconnect()
```

## ⚠️ Bezpečnost Live Trading

Když používáš **TWS_LIVE** nebo **GATEWAY_LIVE** režim:

1. **VŽDY testuj v paper tradingu nejdřív!**
2. **Začni s malými pozicemi** (1-10 akcií)
3. **Používej stop losses**
4. **Kontroluj account balance** před každým obchodem
5. **Monitoruj orders v TWS** - nikdy se nespoléhej jen na API
6. **Měj připravený manuální exit plan**

Aplikace zobrazí **červené varování** při připojení v live režimu:

```
⚠️⚠️⚠️⚠️⚠️⚠️⚠️⚠️⚠️⚠️⚠️⚠️⚠️⚠️⚠️⚠️⚠️⚠️⚠️⚠️
⚠️  WARNING: LIVE TRADING MODE ACTIVATED
⚠️  THIS WILL USE REAL MONEY!
⚠️⚠️⚠️⚠️⚠️⚠️⚠️⚠️⚠️⚠️⚠️⚠️⚠️⚠️⚠️⚠️⚠️⚠️⚠️⚠️
```

## 🐛 Troubleshooting

### Order zůstává v PendingSubmit:
1. Zkontroluj **Read-Only API = OFF** v TWS/Gateway
2. Restartuj TWS/Gateway po změně nastavení
3. Potvrdit paper trading dialog při prvním připojení
4. Testuj **během trading hours** (15:30-22:00 CET)
5. Zkus jiný port/režim

### Connection failed:
1. Zkontroluj, jestli běží TWS/Gateway
2. Zkontroluj správný port pro tvůj režim
3. Zkontroluj API settings v TWS/Gateway
4. Zkus jiný clientId

### Orders se nezobrazují v TWS:
1. Order musí dosáhnout stavu `Submitted` nebo `PreSubmitted`
2. Mimo trading hours může být `PreSubmitted` (normální)
3. Zkontroluj TWS message log

## 📞 Podpora

Pro více informací:
- Spusť `python test_order.py` pro diagnostiku
- Zapni `DEBUG_ORDERS = True` v `config.py`
- Zkontroluj TWS/Gateway message log

# IB Trading Platform — Architektura & Vývojový plán

> **Tento dokument je závazný referenční bod pro každého vývojáře nebo AI asistenta.**
> Před zahájením práce na jakékoliv sekci si přečti příslušnou část.
> Cílem je aby práce na jedné sekci **nikdy nezasáhla** do jiné.

---

## Stav k 1. 3. 2026

### Hotovo ✅
- TradingView Lightweight Charts (LWC) graf — svíčky + volume
- `_TickSubscriber` s trojnásobným fallbackem (streaming → snapshot → hist_poll)
- `_HistWorker` — historická data z IB ve vlastním threadu
- Diagnostické nástroje (Tick Diag, Snapshot Test, TICK ON/OFF)
- TF tlačítka (1m, 5m, 15m, 1h, 4h, 1D)
- Paper account podpora (hist_poll přes `reqHistoricalDataAsync`)

### Plánováno 🔜
- Indikátory (MA, RSI, MACD, Bollinger)
- AI Manager (SL/TP/size doporučení)
- Historie úspěšnosti obchodů
- Ukládání a načítání historických dat (offline cache)
- Uživatelský vstup do trhu (pouze entry — SL/TP navrhuje AI)

---

## Cílová struktura souborů

```
ib-trading-platform/
│
├── app.py                      ← Hlavní vstupní bod (Dash UI + Flask API)
├── config.py                   ← Konfigurace připojení IB
├── ib_connector.py             ← Vše IB API (3 třídy, 3 clientId)
├── order_handler.py            ← Logika a validace orderů
├── requirements.txt
│
├── modules/                    ← Byznys logika — každý soubor nezávislý
│   ├── indicators.py           ← Výpočet indikátorů (čistá matematika)
│   ├── ai_manager.py           ← AI: návrh SL, TP, position size
│   ├── trade_history.py        ← Ukládání obchodů, statistiky, win rate
│   └── data_store.py           ← Cache historických barů (Parquet)
│
├── assets/                     ← Vše co běží v prohlížeči
│   ├── chart_manager.js        ← LWC graf, tick polling, indicator API
│   └── indicators.js           ← Vykreslení indikátorů na graf (nový)
│
└── data/                       ← Datové soubory (v .gitignore!)
    ├── trades/
    │   └── trades.json         ← Historie uzavřených obchodů
    └── bars/
        ├── AAPL_5m_2026-03.parquet
        ├── AAPL_1h_2026-03.parquet
        └── ...                 ← Formát: {SYMBOL}_{TF}_{YYYY-MM}.parquet
```

---

## Aktuální soubory — co dělají

### `app.py` (38 KB) — mozek aplikace
**Smí obsahovat:** Dash layout, Flask endpointy, Dash callbacky, volání modulů.
**Nesmí obsahovat:** Žádnou byznys logiku — ta patří do `modules/`.

Flask endpointy:
- `GET /api/tick/{symbol}` — vrátí aktuální cenu pro JS pollTick
- `GET /api/diag/tick` — diagnostika `_TickSubscriber` (mode, iterations, errors)
- `GET /api/test/snapshot` — snapshot test přes fresh clientId=9

Dash callbacky:
- Load Chart → `ib_connector.get_historical_data()` → `dcc.Store` → JS `loadData()`
- TF tlačítka → změní `barSizeSetting` a `durationStr`, reiniciuje graf
- TICK ON/OFF → volá JS `setTickEnabled()`
- Tick Diag, Snapshot Test → volají Flask endpointy přes `fetch()`

---

### `ib_connector.py` (25 KB) — vše IB API
**Smí obsahovat:** Pouze komunikaci s IB Gateway přes `ib_async`.
**Nesmí obsahovat:** UI logiku, výpočty indikátorů, ukládání dat.

Tři třídy, každá má vlastní IB spojení (různé clientId):

| Třída | ClientId | Účel |
|---|---|---|
| `IBConnector` | 1 | Hlavní: account info, place order, positions |
| `_HistWorker` | 2 | Historická data — fronta dotazů, fresh conn |
| `_TickSubscriber` | 3 | Live cena — trojnásobný fallback |

**_TickSubscriber fallback hierarchie:**
```
1. STREAMING   reqMktData()              mdt=3  — vyžaduje API sub (live účet)
       ↓ Error 10089
2. SNAPSHOT    reqTickersAsync()         mdt=40 — vyžaduje API sub
       ↓ Error 10089
3. HIST_POLL   reqHistoricalDataAsync()  mdt=99 — funguje VŽDY (paper i live)
   params: durationStr='3600 S', barSizeSetting='1 min',
           useRTH=True, whatToShow='TRADES'
   interval: každých 30 sekund
   cena: bars[-1].close (max 1 minuta stará)
```

---

### `config.py` (4 KB) — jediné místo pro nastavení
**Přepínání paper ↔ live = změna tohoto souboru, nic jiného.**

Obsahuje: `IB_HOST`, `IB_PORT` (7497=TWS paper, 7496=TWS live, 4002=GW paper, 4001=GW live),
`IB_CLIENT_ID`, `ORDER_TIMEOUT`, `CONNECTION_LABEL`, `DEBUG_CONNECTION`.

---

### `order_handler.py` (13 KB) — order logika
Validace, risk management (max position size, max daily loss), order typy.
Odděleno od `app.py` záměrně — testovatelné samostatně bez spuštění Dash.

---

### `assets/chart_manager.js` (12 KB) — celý graf v prohlížeči
Běží v prohlížeči, Python/IB nevidí.

```javascript
window.lwcManager = {
    loadData(storeData)           // načte bary z dcc.Store do LWC
    testChart()                   // 100 fake svíček pro testování bez IB
    setTickEnabled(bool)          // zapne/vypne tick polling
    addIndicator(name, type, data, options)  // přidá sérii na graf
    removeIndicator(name)         // odebere sérii
}
```

**Tick polling** (`pollTick`):
- Každých 5000ms volá `GET /api/tick/{symbol}`
- Aktualizuje pouze poslední svíčku (`candleSeries.update()`)
- Volume poslední svíčky se NEaktualizuje (bere z hist dat) — viz TODO níže

---

## Plánované moduly — instrukce pro implementaci

### `modules/indicators.py` — NOVÝ
**Pravidlo: čistá matematika, žádné importy z jiných modulů projektu.**
Vstupy jsou vždy `list[dict]` s klíči `time, open, high, low, close, volume`.
Výstupy jsou vždy `list[dict]` s klíči `time, value` (nebo více hodnot pro MACD/BB).

Plánované funkce:
```python
def calc_ma(bars: list, period: int = 20) -> list[dict]
    # vrátí: [{'time': unix, 'value': 267.5}, ...]

def calc_ema(bars: list, period: int = 20) -> list[dict]

def calc_rsi(bars: list, period: int = 14) -> list[dict]
    # vrátí: [{'time': unix, 'value': 67.3}, ...]  # 0-100

def calc_macd(bars: list, fast=12, slow=26, signal=9) -> dict
    # vrátí: {'macd': [...], 'signal': [...], 'histogram': [...]}

def calc_bollinger(bars: list, period=20, std_dev=2) -> dict
    # vrátí: {'upper': [...], 'middle': [...], 'lower': [...]}

def calc_atr(bars: list, period: int = 14) -> list[dict]
    # používá ai_manager pro výpočet SL vzdálenosti
```

Testování bez Dash: `python modules/indicators.py` (spustí demo s fake daty na konci souboru).

---

### `modules/ai_manager.py` — NOVÝ
**Pravidlo: dostane data, vrátí návrh. Nikdy neposílá order — to dělá uživatel.**

Koncept: uživatel zadá pouze směr (Long/Short) a entry cenu.
AI Manager navrhne SL, TP a velikost pozice na základě:
- ATR (volatilita) — ze `indicators.calc_atr()`
- Minulé úspěšnosti — z `trade_history.get_stats()`
- Risk per trade nastavení — z `config.py`

```python
def suggest_trade(
    symbol: str,
    direction: str,   # 'LONG' nebo 'SHORT'
    entry: float,
    bars: list,       # historické bary pro ATR výpočet
    account_size: float,
    risk_pct: float = 1.0   # % účtu riskovat na obchod
) -> dict:
    # vrátí:
    # {
    #   'sl': 264.50,         # stop loss price
    #   'tp': 273.00,         # take profit price
    #   'size': 15,           # počet akcií
    #   'risk_usd': 37.50,    # riziko v USD
    #   'rr_ratio': 2.1,      # risk/reward ratio
    #   'atr': 2.50,          # aktuální ATR
    #   'method': 'ATR_1.5x'  # metoda výpočtu SL
    # }
```

SL kalkulace: `sl = entry - (atr * multiplier)` pro Long, opačně pro Short.
Size kalkulace: `size = floor((account * risk_pct/100) / sl_distance)`.

UI zobrazí návrh — uživatel může hodnoty upravit nebo potvrdit celé.

---

### `modules/trade_history.py` — NOVÝ
**Datový formát: `data/trades/trades.json`**

```python
def save_trade(trade: dict) -> None
    # trade = {
    #   'id': 'AAPL-20260301-143022',
    #   'symbol': 'AAPL', 'direction': 'LONG',
    #   'entry': 267.50, 'exit': 272.10,
    #   'sl': 264.50, 'tp': 273.00,
    #   'size': 15, 'pnl': 69.0, 'pnl_pct': 1.72,
    #   'duration_min': 47,
    #   'exit_reason': 'TP_HIT',   # 'TP_HIT', 'SL_HIT', 'MANUAL'
    #   'timestamp': '2026-03-01T14:30:22'
    # }

def get_trades(symbol: str = None, limit: int = 50) -> list[dict]

def get_stats(symbol: str = None) -> dict
    # vrátí:
    # {
    #   'total_trades': 47,
    #   'win_rate': 0.617,       # 61.7%
    #   'avg_rr': 1.85,          # průměrný R:R
    #   'profit_factor': 2.3,
    #   'max_drawdown': -4.2,    # % účtu
    #   'total_pnl': 1247.50
    # }

def get_equity_curve() -> list[dict]
    # vrátí: [{'time': unix, 'value': 10247.50}, ...]
    # pro vykreslení na grafu
```

---

### `modules/data_store.py` — NOVÝ
**Datový formát: `data/bars/{SYMBOL}_{TF}_{YYYY-MM}.parquet`**
**Závislost: `pip install pyarrow` (přidat do requirements.txt)**

```python
def save_bars(symbol: str, timeframe: str, bars: list) -> None
    # bars = list dictů: [{'time': unix, 'open': ..., 'high': ...,
    #                       'low': ..., 'close': ..., 'volume': ...}]
    # timeframe = '1m', '5m', '15m', '1h', '4h', '1D'
    # soubor: data/bars/AAPL_5m_2026-03.parquet

def load_bars(
    symbol: str,
    timeframe: str,
    from_date: str = None,   # 'YYYY-MM-DD' nebo None = vše
    to_date: str = None
) -> list[dict]

def has_fresh_data(
    symbol: str,
    timeframe: str,
    max_age_minutes: int = 60
) -> bool
    # True = cache je čerstvá, nepotřebujeme volat IB

def list_available(
    symbol: str = None
) -> list[dict]
    # vrátí: [{'symbol': 'AAPL', 'tf': '5m', 'bars': 1847,
    #           'from': '2026-02-01', 'to': '2026-03-01'}]
```

Integrace s `app.py`: před každým Load Chart zkontrolovat `has_fresh_data()` —
pokud True, použít `load_bars()` místo IB dotazu.
Po každém IB dotazu zavolat `save_bars()` pro uložení do cache.

---

### `assets/indicators.js` — NOVÝ
**Pravidlo: pouze volá `window.lwcManager.addIndicator()` / `removeIndicator()`.**
Vypočtená data přijdou z Pythonu přes `dcc.Store`, JS je pouze vykreslí.

```javascript
window.indicatorManager = {
    show(name, data, options) {
        // name: 'MA20', 'RSI', 'MACD_line' atd.
        // options: { color, lineWidth, priceScaleId }
        window.lwcManager.addIndicator(name, 'line', data, options);
    },
    hide(name) {
        window.lwcManager.removeIndicator(name);
    },
    showVolume(data) {
        // volume je již v chart_manager.js — tento soubor ho neřeší
    }
}
```

RSI a MACD musí mít vlastní `priceScaleId` (oddělené osy) —
nesmí být na stejné škále jako svíčky.

---

## Datové formáty — závazný standard

### Historické bary (Parquet)
```
data/bars/{SYMBOL}_{TF}_{YYYY-MM}.parquet
```
- Sloupce: `time` (int, unix timestamp), `open`, `high`, `low`, `close`, `volume`
- Jeden soubor = jeden symbol + timeframe + měsíc
- Rozdělení po měsících = rychlé načtení jen potřebného rozsahu
- Závislost: `pyarrow` (nebo `fastparquet`)

### Historie obchodů (JSON)
```
data/trades/trades.json
```
- Pole objektů, každý = jeden uzavřený obchod
- Append-only — nikdy nesmazat, pouze přidávat
- Viz struktura v `trade_history.py` výše

### Složka `data/` je v `.gitignore`
Reálná data se necommitují. Výjimka: ukázková/testovací data v `data/sample/`.

---

## Pravidla pro práci na projektu

### Nezávislost modulů
- `modules/*.py` **nesmí importovat** navzájem (výjimka: `ai_manager` může importovat `indicators`)
- `modules/*.py` **nesmí importovat** `app.py` ani `ib_connector.py`
- `ib_connector.py` **nesmí importovat** nic z `modules/`
- Komunikace vždy přes `app.py` jako prostředníka

### Testování
Každý modul musí být spustitelný samostatně:
```bash
python modules/indicators.py    # demo výpočet na fake datech
python modules/ai_manager.py    # demo návrh obchodu
python modules/trade_history.py # demo uložení a statistiky
python modules/data_store.py    # demo save/load barů
```

### ClientId alokace (IB Gateway)
| ClientId | Použití |
|---|---|
| 1 | `IBConnector` — hlavní spojení, trading |
| 2 | `_HistWorker` — historická data |
| 3 | `_TickSubscriber` — live tick |
| 9 | Snapshot test (dočasné, ihned se odpojí) |
| 10+ | Rezervováno pro budoucí backtesting engine |

### Přidávání nové funkce — checklist
1. Patří logika do existujícího modulu nebo potřebuje nový soubor?
2. Jaká data vstupují, jaká vystupují? Definuj interface první.
3. Lze testovat bez IB a bez Dash? Pokud ne, refaktoruj.
4. Přidej do `app.py` pouze volání — žádnou logiku.
5. Pokud se mění datový formát, aktualizuj tento dokument.

---

## TODO — konkrétní další kroky

- [ ] Vytvořit `modules/` složku
- [ ] `modules/indicators.py` — MA, EMA, RSI, MACD, ATR, Bollinger
- [ ] `assets/indicators.js` — vykreslení na LWC graf
- [ ] `modules/data_store.py` — Parquet cache, `has_fresh_data()` do Load Chart
- [ ] `modules/trade_history.py` — JSON persistence, stats, equity curve
- [ ] `modules/ai_manager.py` — ATR-based SL/TP, position sizing
- [ ] UI panel pro vstup do trhu (symbol + Long/Short + entry price)
- [ ] UI panel Historie úspěšnosti (win rate, equity curve)
- [ ] Volume update při tick pollingu (přidat `volume` do `/api/tick/` response)
- [ ] Přidat `pyarrow` do `requirements.txt`

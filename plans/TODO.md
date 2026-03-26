# TODO — Graf Debug Panel + Architektonické opravy

> **Pořadí je závazné.** Každý krok ověř před přechodem na další.
> Pracuj vždy na branchi `feature/trade-management-collab-v3`.
> Před každou prací si přečti `AGENTS.md` — tam jsou klíčové konvence.

---

## FÁZE 1 — Graf Debug Panel (udělej PRVNÍ)

### Proč nejdřív toto
Bez možnosti inspekce grafů přímo z konzole musíš po každé opravě ručně klikat a vizuálně ověřovat. Debug panel ti dá rychlou zpětnou vazbu a odhalí problémy (špatné timestampy, prázdná data, tick drift) automaticky.

### Co implementovat

Vytvoř globální JS objekt `window.chartDebug` v `assets/chart_manager.js` (přidej na konec IIFE, vedle `window.lwcManager`).

`window.chartDebug` musí mít tyto metody:

#### `chartDebug.status(chartId?)`
Vypíše do konzole přehled stavu grafu. Bez argumentu vypíše oba charty.
```
[CHART DEBUG] lwc-container
  symbol      : AAPL (STOCK)
  timeframe   : 5 mins  (300s)
  bars loaded : 120
  first bar   : 2026-03-25 15:30 UTC (1742913000)
  last bar    : 2026-03-26 15:25 UTC (1742999100)
  lastBarTime : 1742999100
  tfSeconds   : 300
  tickEnabled : true
  tickTimer   : running
  allBars[0]  : {time, open, high, low, close}
  allBars[-1] : {time, open, high, low, close}
  indicators  : {sma: false, ema: true, rsi: false, macd: false}
  subCharts   : {rsi: null, macd: null}
  listenerCount: (N/A - not tracked yet)
```

#### `chartDebug.validateTimestamps(chartId?)`
Zkontroluje všechny bary v `allBars` a reportuje:
- Duplicitní timestampy
- Neseřazené timestampy (bar[i].time > bar[i+1].time)
- Mezery větší než 3× tfSeconds (chybějící svíčky)
- Zda timestampy daily barů jsou UTC midnight (time % 86400 === 0)
```
[CHART DEBUG] validateTimestamps lwc-container
  Total bars  : 120
  Duplicates  : 0
  Unsorted    : 0
  Gaps (>3xTF): 2  [idx 45 gap=7200s, idx 89 gap=5400s]
  Daily align : ✓ all daily bars at UTC midnight
```

#### `chartDebug.testTick(chartId?)`
Spustí jednorázový fetch `/api/tick/{symbol}?asset_type={assetType}` a zobrazí raw odpověď + výpočet `tickBarTime`:
```
[CHART DEBUG] testTick lwc-container
  fetch: /api/tick/AAPL?asset_type=STOCK
  response: {price: 182.34, time: 1742999100, close: 182.10}
  tickTime    : 1742999100
  tickBarTime : 1742999100  (floor to 300s boundary)
  lastBarTime : 1742999100
  verdict     : ✓ tick matches current bar
```

#### `chartDebug.testBars(symbol, tf, assetType, count)`
Spustí jednorázový fetch `/api/bars/{symbol}?tf={tf}&asset_type={assetType}&count={count}&endtime=now` a zobrazí:
- Počet přijatých barů
- První a poslední timestamp (lidsky čitelný)
- Zda jsou timestampy seřazené
- Zda daily bary jsou na UTC midnight
```
[CHART DEBUG] testBars AAPL 1 day STOCK 60
  fetch: /api/bars/AAPL?tf=1+day&asset_type=STOCK&count=60&endtime=now
  status: 200 OK
  bars received: 60
  first: 2026-01-06 00:00 UTC (1736121600)  ← UTC midnight? ✓
  last:  2026-03-26 00:00 UTC (1742947200)  ← UTC midnight? ✓
  sorted: ✓
  gaps: 0
```

#### `chartDebug.listenerReport()`
Pomocná info metoda — vypíše do konzole text s varováním, že listener tracking je manuální a jak ho zkontrolovat:
```
[CHART DEBUG] listenerReport
  NOTE: lightweight-charts nepodporuje getSubscriberCount().
  Zkontroluj manuálně: po každém setIndicators() se volá syncTimeScales()
  bez unsubscribe — po 10+ minutách se mohou hromadit listenery.
  Doporučeno: zkontroluj CPU usage v DevTools Performance při scrollování.
```

#### `chartDebug.autoCheck(intervalMs?)`
Spustí opakovanou kontrolu každých `intervalMs` ms (default 30000 = 30s).
Každý cyklus zavolá `status()` a `validateTimestamps()` pro oba charty a vypíše výsledek do konzole s timestampem. Zastaví se po `chartDebug.stopAutoCheck()`.
```
[AUTO-CHECK 14:32:05] lwc-container: 120 bars, tick ✓, no timestamp errors
[AUTO-CHECK 14:32:05] lwc-container-2: 60 bars, tick ✓, no timestamp errors
```

### Jak implementovat

1. V `assets/chart_manager.js` přidej na konec IIFE (po `window.lwcManager2 = ...`) nový blok:
```js
// === CHART DEBUG PANEL ===
window.chartDebug = (function() {
  function getInstance(chartId) {
    if (chartId === 'lwc-container-2') return window.lwcManager2;
    return window.lwcManager;
  }
  // ... implementace metod ...
  return { status, validateTimestamps, testTick, testBars, listenerReport, autoCheck, stopAutoCheck };
})();
```

2. `lwcManager` a `lwcManager2` musí exportovat gettery pro debug:
   - `getAllBars()` — již existuje ✓
   - `getCurrentSymbol()` — přidej
   - `getCurrentAssetType()` — přidej
   - `getCurrentTf()` — přidej
   - `getTfSeconds()` — přidej
   - `getLastBarTime()` — přidej
   - `isTickEnabled()` — přidej
   - `hasTickTimer()` — přidej
   - `getActiveIndicators()` — přidej (vrátí `activeIndicatorSettings`)
   - `getSubCharts()` — přidej (vrátí `subCharts` object)

3. Přidej tyto gettery do `return {}` v `createChartInstance()`.

### Ověření Fáze 1
Spusť app, otevři DevTools konzoli a spusť:
```js
chartDebug.status()
chartDebug.validateTimestamps()
chartDebug.testBars('AAPL', '5 mins', 'STOCK', 60)
chartDebug.testTick()
chartDebug.autoCheck(15000)  // kontrola každých 15s
```
Všechny metody musí vrátit strukturovaný výstup bez JS chyb.

---

## FÁZE 2 — Oprava Daily timestamp (timezone bug)

### Problém
IB API vrací `bar.date` jako `datetime` objekt v lokálním čase.
Konverze `int(bar.date.timestamp())` v `ib_connector.py` přidává timezone offset (Praha UTC+1/+2) → daily bary nejsou na UTC midnight → LWC je zobrazí špatně nebo je odmítne jako duplikáty.

### Jak opravit
V `ib_connector.py` najdi konverzi timestamp pro historical bars a zajisti UTC midnight pro daily:

```python
import calendar

def bar_to_dict(bar, tf_seconds=300):
    if hasattr(bar.date, 'timestamp'):
        ts = int(calendar.timegm(bar.date.timetuple()))  # UTC, ne lokální čas
    else:
        # string format např. "20240115" pro daily
        from datetime import datetime
        dt = datetime.strptime(str(bar.date), "%Y%m%d")
        ts = int(calendar.timegm(dt.timetuple()))
    return {
        'time': ts,
        'open': bar.open, 'high': bar.high,
        'low': bar.low, 'close': bar.close,
        'volume': bar.volume
    }
```

### Ověření
Po opravě spusť:
```js
chartDebug.testBars('AAPL', '1 day', 'STOCK', 10)
// → first/last timestamps musí být UTC midnight (time % 86400 === 0)
chartDebug.validateTimestamps()
// → Daily align: ✓ all daily bars at UTC midnight
```

---

## FÁZE 3 — Oprava `tfSeconds` při přepnutí TF

### Problém
`currentTf` a `tfSeconds` se nastavují jen v `loadData()`. Pokud se TF přepne bez nového loadu (edge case), tickový alignovací výpočet používá starou hodnotu `tfSeconds`.

### Jak opravit
V `createChartInstance()` přidej veřejnou metodu `setCurrentTf(tf)`:
```js
function setCurrentTf(tf) {
  currentTf = tf;
  tfSeconds = TF_TO_SECONDS[tf] || 300;
  writeDebug("TF", "[" + containerId + "] TF manually set: " + tf + " -> " + tfSeconds + "s");
}
```
Přidej do `return {}`.

V `app.py` callback pro TF přepínání přidej volání `lwcManager.setCurrentTf(tf)` přes `clientside_callback` nebo přes JS store.

### Ověření
```js
chartDebug.status()  // tfSeconds musí odpovídat aktuálně zobrazenému TF
```

---

## FÁZE 4 — Oprava listener leaku v `syncTimeScales`

### Problém
`syncTimeScales()` se volá při `initVolumeChart()`, `createRsiChart()`, `createMacdChart()`.
Při každém refresh indikátorů (každých 60s) se RSI/MACD destroy + recreate → nový `subscribeVisibleLogicalRangeChange` bez unsubscribe předchozího. Po 10 minutách → desítky handlerů na stejném `chart.timeScale()`.

### Jak opravit

1. Ulož referenci na callback v closure:
```js
var rangeChangeHandler = null;  // instance-local state

function syncTimeScales(sourceChart, targetCharts) {
  // Unsubscribe předchozí handler (pokud existuje)
  if (rangeChangeHandler) {
    try { sourceChart.timeScale().unsubscribeVisibleLogicalRangeChange(rangeChangeHandler); } catch(e) {}
  }
  rangeChangeHandler = function(range) {
    if (syncingRange || !range || range.from == null || range.to == null) return;
    syncingRange = true;
    targetCharts.forEach(function(tc) {
      try { if (tc && tc.timeScale) tc.timeScale().setVisibleLogicalRange(range); } catch(e) {}
    });
    syncingRange = false;
  };
  sourceChart.timeScale().subscribeVisibleLogicalRangeChange(rangeChangeHandler);
}
```

2. Při `clearSubCharts()` přidej: `syncTimeScales(chart, [volumeChart]);` — tím se handler obnoví jen pro volume.

### Ověření
V DevTools Performance tab: spusť `chartDebug.autoCheck(5000)` na 2 minuty, pak zkontroluj CPU usage při scrollování grafu — nesmí lineárně narůstat.

---

## FÁZE 5 — Oprava `setIndicators` — update místo destroy

### Problém
`setIndicators()` při každém volání (i z auto-refresh každých 60s) dělá:
```js
subCharts.rsi.remove(); removeSubContainer("rsi"); createRsiChart(...)
```
→ Blikání DOM, ztráta sync, listener leak (viz Fáze 4).

### Jak opravit

Odděluj dva případy:
- **Poprvé** nebo **toggle on**: `createRsiChart()` / `createMacdChart()`
- **Refresh dat** (subchart již existuje): jen `series.setData(newData)` na existujících sériích

```js
// Místo destroy+create:
if (subCharts.rsi && rsiSeriesRef) {
  // Jen aktualizuj data
  rsiSeriesRef.setData(validData.map(...));
} else {
  createRsiChart(data.rsi, data.rsi_period || 14);
}
```

Ulož reference na RSI/MACD series do instance-local proměnných:
```js
var rsiSeriesRef = null;    // instance-local
var macdLineRef = null;     // instance-local
var macdSignalRef = null;   // instance-local
var macdHistRef = null;     // instance-local
```

### Ověření
```js
chartDebug.autoCheck(5000)
// Pozoruj konzoli: při auto-refresh indikátorů nesmí být žádný "remove" / "createRsiChart"
// log po prvním načtení
```

---

## FÁZE 6 — Oprava `prependData` viewport

### Problém
Po "Load More" se viewport resetuje na nejnovější data. `setVisibleLogicalRange` je přeskočen s komentářem "causes async errors".

### Jak opravit
Obal do `requestAnimationFrame`:
```js
if (visibleRange && visibleRange.from != null) {
  requestAnimationFrame(function() {
    try {
      chart.timeScale().setVisibleLogicalRange(visibleRange);
    } catch(e) {
      writeDebug("WARN", "setVisibleLogicalRange after prepend: " + e.message);
    }
  });
}
```

### Ověření
1. Načti graf s 60 svíčkami
2. Klikni "Load More"
3. Viewport musí zůstat na stejném místě, nesmí skočit na konec

---

## FÁZE 7 — Chart 2 unifikace s Chart 1

> Tento krok dělej AŽ PO Fázích 1–6. Opravy architektury se automaticky projeví i na Chart 2.

### Co musí být IDENTICKÉ s Chart 1

1. **Layout (shora dolů):**
   - Řádek 1: TF tlačítka (1m|5m|15m|30m|1h|1D) vlevo, status text vpravo
   - Řádek 2: Indikátory (SMA 20 | EMA 20 | RSI 14 | MACD)
   - Řádek 3: Symbol | Asset type | Exchange | svíček | Load More | info | Last: $cena
   - Graf (LWC candlestick)
   - Volume subchart
   - RSI subchart (pokud zapnut)
   - MACD subchart (pokud zapnut)

2. **Výchozí hodnoty:**
   - Symbol: AAPL, Asset type: STOCK, Exchange: SMART, TF: 1D, Svíček: 60

3. **Implementace v `app.py`:**
   - Projdi všechny Chart 1 callbacks
   - Pro každý vytvoř identickou kopii s `chart-` → `chart2-` a `lwc-container` → `lwc-container-2`
   - Žádné výjimky "Chart 2 má jen candlestick+volume"

### Ověření Fáze 7
```js
// Oba charty musí projít stejnými testy:
chartDebug.status('lwc-container')
chartDebug.status('lwc-container-2')
chartDebug.validateTimestamps('lwc-container')
chartDebug.validateTimestamps('lwc-container-2')
// + spusť: python3.11 tools/test_backend.py → min 20/23 passed
```

---

## Globální pravidla pro coding agenta

- **Nikdy** nedělej micro-edity — analyzuj celý problém, pak edituj v jednom průchodu
- **Vždy** ověř backend přes `tools/ib_api_tester.py` před prací na frontendu
- **Vždy** používej `python3.11`, ne `python`
- **Vždy** PowerShell syntaxe pro příkazy
- Po každé Fázi spusť `chartDebug.status()` + `chartDebug.validateTimestamps()` jako smoke test
- `AGENTS.md` má přednost před vším ostatním

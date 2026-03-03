# Indicator Plugin System — AI Developer Guide

> **Tento soubor je primárně určen pro AI asistenty** (Perplexity, GitHub Copilot, atd.)
> aby věděly přesně jak implementovat nový indikátor do celého stacku.
> Platí pro branch `feature/indicator-plugin-system` a vše co z ní vychází.

---

## Architektura přehled

```
modules/indicators/
  base.py          ← BaseIndicator ABC — MUSÍ dědit každý indikátor
  sma.py           ← příklad jednoduchého indikátoru
  ema.py           ← příklad EMA s kumulativním výpočtem
  rsi.py           ← příklad s interním stavem
  macd.py          ← příklad složeného indikátoru (vrací dict místo float)
  __init__.py      ← export: from modules.indicators import SMA, EMA, RSI, MACD
  INDICATORS.md    ← tento soubor

app.py
  └─ /api/indicators/<symbol>/<tf>   ← Flask endpoint volá .calculate(bars)

assets/chart_manager.js
  └─ setIndicators(data)             ← přijímá JSON z endpointu, kreslí na LWC
```

---

## Formát vstupních dat (`bars`)

Každý indikátor dostane seznam dict objektů — stejný formát jak vrací `data_store.get_bars()`:

```python
bars = [
    {
        'time':   1709500800,   # Unix timestamp (int)
        'open':   182.50,
        'high':   183.20,
        'low':    181.90,
        'close':  182.80,
        'volume': 1234567
    },
    # ...
]
```

---

## Formát výstupních dat

### Jednoduchý indikátor (SMA, EMA, RSI, ...)
Vrací `list[dict]` — každý bod má `time` + `value`:
```python
[
    {'time': 1709500800, 'value': None},    # prvnich (period-1) bodu je None
    {'time': 1709501100, 'value': 182.34},
    # ...
]
```

### Složený indikátor (MACD)
Vrací `list[dict]` s více klíči — klíče si pojmenuj sám, musí odpovídat JS rendereru:
```python
[
    {'time': 1709500800, 'macd': None, 'signal': None, 'histogram': None},
    {'time': 1709501100, 'macd': 0.45, 'signal': 0.38, 'histogram': 0.07},
    # ...
]
```

---

## Krok 1 — Vytvoř Python soubor v `modules/indicators/`

Děď z `BaseIndicator` (`base.py`):

```python
# modules/indicators/bollinger.py
from .base import BaseIndicator
from .sma import SMA

class BollingerBands(BaseIndicator):
    """
    Bollinger Bands (střední pásmo = SMA, horní/dolní = SMA ± k*std).
    Výstup: list[dict] s klíči: time, middle, upper, lower
    """
    name = 'bollinger'

    def __init__(self, period: int = 20, k: float = 2.0):
        self.period = period
        self.k      = k

    def calculate(self, bars: list) -> list:
        closes = [b['close'] for b in bars]
        result = []
        for i, b in enumerate(bars):
            if i < self.period - 1:
                result.append({'time': b['time'],
                                'middle': None, 'upper': None, 'lower': None})
                continue
            window = closes[i - self.period + 1 : i + 1]
            mid    = sum(window) / self.period
            std    = (sum((x - mid) ** 2 for x in window) / self.period) ** 0.5
            result.append({
                'time':   b['time'],
                'middle': round(mid, 4),
                'upper':  round(mid + self.k * std, 4),
                'lower':  round(mid - self.k * std, 4),
            })
        return result
```

**Pravidla:**
- Vždy definuj `name = 'nazev'` (snake_case, lowercase)
- Parametry přes `__init__`, výchozí hodnoty vždy nastav
- Výstup musí být `list` se stejnou délkou jako vstupní `bars`
- Pro prvních `period - 1` bodů vrať `None` ve všech value polích
- Zaokrouhluj výsledky na 4 desetinná místa (`round(x, 4)`)
- Nepoužívej pandas/numpy — jen pure Python (kvůli rychlosti importu)

---

## Krok 2 — Exportuj v `__init__.py`

```python
# modules/indicators/__init__.py — PŘIDEJ na konec:
from .bollinger import BollingerBands
```

---

## Krok 3 — Přidej do Flask endpointu (`app.py`)

V souboru `app.py` najdi sekci `# ── INDICATORS ENDPOINT ──` a přidej větev:

```python
# 1. Import nahoře v app.py:
from modules.indicators import SMA, EMA, RSI, MACD, BollingerBands

# 2. V routě /api/indicators/<symbol>/<tf> přidej do bloku try:
if 'bb' in active:
    p = int(freq.args.get('bb_p', 20))
    k = float(freq.args.get('bb_k', 2.0))
    result['bb'] = BollingerBands(period=p, k=k).calculate(bars)
    result['bb_period'] = p
    result['bb_k']      = k
```

**URL příklad:** `/api/indicators/AAPL/5_mins?active=bb&bb_p=20&bb_k=2.0`

---

## Krok 4 — Přidej toggle tlačítko do layoutu (`app.py`)

V sekci `# INDICATOR TOGGLE PANEL` v `app.layout` přidej button:

```python
html.Button('BB 20',  id='ind-bb-btn',  n_clicks=0, className='ind-btn',
            title='Bollinger Bands (20, 2.0)'),
```

Pak v clientside callbacku `INDICATOR TOGGLE`:
- přidej `Input('ind-bb-btn', 'n_clicks')` do `Input` listu
- přidej `Output('ind-bb-btn', 'className')` do `Output` listu
- přidej `Output('ind-bb-btn', 'className')` do return pole
- přidej `bb: False` do `indicator-settings-store` default data
- přidej `if (tid === 'ind-bb-btn') s.bb = !s.bb;` do JS toggle logiky

V clientside callbacku `FETCH INDICATORS`:
- přidej `if (settings.bb) active.push('bb');`

---

## Krok 5 — Přidej renderer do `chart_manager.js`

V `assets/chart_manager.js` v metodě `setIndicators(data)` přidej blok:

```javascript
// -- Bollinger Bands overlay --
if (data.bb) {
    // Middle line (=SMA)
    var bbMid = data.bb
        .filter(function(d) { return d.middle !== null; })
        .map(function(d) { return { time: d.time, value: d.middle }; });
    addIndicator('bb_mid', 'line', bbMid, {
        color: '#ffffff88', lineWidth: 1,
        priceScaleId: 'right', title: 'BB mid',
        lastValueVisible: false, priceLineVisible: false
    });
    // Upper band
    var bbUp = data.bb
        .filter(function(d) { return d.upper !== null; })
        .map(function(d) { return { time: d.time, value: d.upper }; });
    addIndicator('bb_up', 'line', bbUp, {
        color: '#ce93d888', lineWidth: 1, lineStyle: 2,
        priceScaleId: 'right', title: 'BB+',
        lastValueVisible: false, priceLineVisible: false
    });
    // Lower band
    var bbDn = data.bb
        .filter(function(d) { return d.lower !== null; })
        .map(function(d) { return { time: d.time, value: d.lower }; });
    addIndicator('bb_dn', 'line', bbDn, {
        color: '#ce93d888', lineWidth: 1, lineStyle: 2,
        priceScaleId: 'right', title: 'BB-',
        lastValueVisible: false, priceLineVisible: false
    });
} else {
    removeIndicator('bb_mid');
    removeIndicator('bb_up');
    removeIndicator('bb_dn');
}
```

**Indikátor v sub-panelu (jako RSI)?** Podívej se na funkci `createRsiChart()` v `chart_manager.js` jako vzor.

---

## Přehled existujících indikátorů

| Třída | Soubor | Parametry | Výstupní klíče | Typ vykreslení |
|---|---|---|---|---|
| `SMA` | `sma.py` | `period=20` | `value` | overlay line (oranžová) |
| `EMA` | `ema.py` | `period=20` | `value` | overlay line (modrá) |
| `RSI` | `rsi.py` | `period=14` | `value` | sub-panel line (fialová) |
| `MACD` | `macd.py` | `fast=12, slow=26, signal=9` | `macd, signal, histogram` | sub-panel hist+lines |

---

## Checklist pro nový indikátor

```
[ ] modules/indicators/<nazev>.py    — třída dědí BaseIndicator, implementuje calculate()
[ ] modules/indicators/__init__.py   — přidán export
[ ] app.py import                    — přidán do from modules.indicators import ...
[ ] app.py endpoint                  — přidána větev if 'nazev' in active:
[ ] app.py layout                    — přidáno toggle tlačítko
[ ] app.py toggle callback           — přidán Input/Output + JS logika
[ ] app.py fetch callback            — přidáno active.push('nazev')
[ ] chart_manager.js setIndicators() — přidán renderer blok
```

---

## Konvence pojmenování

- **Python třída:** `PascalCase` — `BollingerBands`, `StochasticOscillator`
- **`name` atribut:** `snake_case` — `'bollinger'`, `'stochastic'`
- **URL parametr:** `short` — `bb`, `stoch`
- **UI button id:** `ind-{short}-btn` — `ind-bb-btn`
- **JS indicator key:** `'bb'`, `'stoch'`
- **JS series name:** `'{short}_line'`, `'{short}_up'` atd.

---

## Data flow diagram

```
User klikne toggle btn
        │
        ▼
indicator-settings-store  { ema: true, rsi: true, bb: true, ... }
        │
        ▼
clientside callback  →  fetch /api/indicators/AAPL/5_mins?active=ema,rsi,bb
                                        │
                                        ▼
                               app.py FlaskRoute
                               data_store.get_bars()  ←  Parquet cache
                               EMA().calculate(bars)
                               RSI().calculate(bars)
                               BollingerBands().calculate(bars)
                               return jsonify(result)
                                        │
                                        ▼
                         window.lwcManager.setIndicators(data)
                                        │
                              ┌─────────┴─────────┐
                              ▼                   ▼
                        addIndicator()     createRsiChart()
                        (SMA/EMA/BB)       createMacdChart()
                        overlay na         nový div pod grafem
                        hlavní chart
```

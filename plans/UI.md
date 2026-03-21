**Účel:** Tento dokument popisuje kompletní chování frontend UI. Slouží jako zadání pro AI agenta při implementaci. Backend (datové funkce, IB komunikace) je řešen separátně — UI volá backend přes definované API endpointy. UI neví nic o tom jak backend data získává, jen co si má vyžádat a co dostane zpět.

---

## Architektonický princip

UI a backend jsou oddělené vrstvy. UI nikdy nepracuje přímo s IB ani s daty — vždy volá backend endpoint, dostane odpověď a tu zobrazí nebo předá do grafu. Každý endpoint má jasně definovaný vstup a výstup. Tím je možné backend testovat a vyvíjet nezávisle a UI stavět na jistotě že rozhraní funguje.

---

## 1. Celkový layout stránky

Aplikace je single-page, tmavý motiv, běží na `http://localhost:8050`.

Stránka se skládá ze dvou hlavních zón:

**Levá zóna (hlavní obsah)** — zabírá zbývající šířku:
- Header
- Account Info
- Grafové bloky (N kusů pod sebou)
- Open Positions
- Trade History
- Settings

**Pravá zóna (fixní panel ~340px)** — začíná na úrovni prvního grafového bloku:
- Order Entry panel

Pravá zóna je sticky — při scrollování zůstává v pravém sloupci a vizuálně se zarovnává s aktivním grafovým blokem (viz sekce Order Entry).

---

## 2. Header

Gradient pruh přes celou šířku nahoře stránky.

**Obsah:**
- `🚀 IB Trading Platform v3.0` — statický název vlevo
- **Market hours badge** — středem nebo vlevo za názvem, barevný štítek, refresh každých 60s
  - 🟢 `US Regular` — trh otevřen
  - 🟡 `Pre-Market` nebo `After-Hours`
  - 🔴 `Closed`
- **Connection status** — vpravo, refresh každých 10s
  - `⚪ Connected to IB Gateway` (zelená tečka)
  - `⚪ Disconnected` (červená tečka)

**Backend volání:** `GET /api/connection/status` → `{ connected: bool }` a `GET /api/market/hours` → `{ status, label, color }`

---

## 3. Account Info

Tmavá lišta těsně pod headerem, refresh každých 10s.

**Zobrazuje:**
- `💼 Account:` číslo IB účtu
- `💰 Balance:` Net Liquidation Value formátovaná jako `$0.00`
- `📈 Buying Power:` dostupná kupní síla formátovaná jako `$0.00`

Při odpojení: všechna pole zobrazí `Not Connected` resp. `$0.00`.

**Backend volání:** `GET /api/account/info` → `{ account_id, net_liquidation, buying_power }`

---

## 4. Grafové bloky

### 4.1 Počet bloků

Počet grafových bloků určuje nastavení `chart_count` (1–4) uložené v konfigurace. Načte se při startu stránky. Bloky se renderují dynamicky — je jich přesně tolik kolik říká `chart_count`. Všechny bloky jsou identické co do struktury, liší se pouze svým indexem a vlastním stavem.

### 4.2 Co každý blok obsahuje (shora dolů)
[ Symbol input ] [ Asset type ▼ ] [ Exchange ▼ ] Last: $182.34 ▲ +1.2%
[ 60 ▲▼ svíček ] [ + Load More ]
[ 1m ] [ 5m ] [ 15m ] [ 30m ] [ 1h ] [ 1D ] ⏳ Načítám...
[ SMA 20 ] [ EMA 20 ] [ RSI 14 ] [ MACD ]
─────────────────────────────────────────────────────
LWC Candlestick Chart
─────────────────────────────────────────────────────
Volume subchart
─────────────────────────────────────────────────────
RSI subchart (pouze pokud zapnut)
─────────────────────────────────────────────────────
MACD subchart (pouze pokud zapnut)

### 4.3 Symbol, Asset type, Exchange

- **Symbol input** — textový input, uživatel napíše ticker (např. `AAPL`, `EURUSD`)
- Potvrzení symbolu: Enter nebo kliknutí mimo pole → spustí reset grafu
- **Asset type** — dropdown: `STOCK / FOREX / CRYPTO`
- **Exchange** — dropdown: `SMART / IBIS / AEB / SBF`
- Změna Asset type nebo Exchange = reset grafu (stejně jako nový symbol)
- Tato tři pole jsou vlastní pro každý blok, nezávislá

### 4.4 Aktuální cena

Zobrazuje se napravo od Exchange dropdownu na stejném řádku.
- Formát: `Last: $182.34 ▲ +$1.20 (+0.66%)`
- Šipka a barva: zelená ▲ = kladná změna, červená ▼ = záporná
- Refresh každých 10s
- Cena se načítá z backendu pro symbol a asset type daného bloku
- Pro FOREX: 4 desetinná místa. Pro STOCK/CRYPTO: 2 desetinná místa.

**Backend volání:** `GET /api/tick/{symbol}?asset_type={asset_type}` → `{ price, close, time }`

### 4.5 Počet svíček a Load More

- **Input pole** — číslo, min 10, max 500, výchozí hodnota z `default_candles_count` v nastavení
- **`+ Load More` tlačítko** — přidá historii (viz 4.7)
- Hodnota v inputu platí pro oba typy operace (reset i load more)

### 4.6 Reset grafu

Spouští se při:
- Kliknutí na TF tlačítko (1m, 5m, 15m, 30m, 1h, 1D)
- Potvrzení nového symbolu
- Změně Asset type nebo Exchange

Co se stane:
1. Graf se vymaže (všechny svíčky, indikátory, subgrafy)
2. Backend dostane požadavek: dej mi N nejnovějších svíček pro tento symbol/TF/asset_type od teď dozadu
3. Svíčky se zobrazí v grafu
4. Indikátory se přepočítají na nových datech
5. Tick se napojí na nový symbol/TF — automaticky, bez akce uživatele
6. Historický ukazatel se resetuje (Load More začne znovu od nejstarší načtené svíčky)
7. Zobrazí se loading indikátor během načítání (`⏳ Načítám 5m…`)

**Backend volání:** `GET /api/bars/{symbol}?tf={tf}&asset_type={asset_type}&count={N}&end_time=now` → `{ bars: [{time, open, high, low, close, volume}] }`

### 4.7 Load More (přidání historie)

Spouští se kliknutím na `+ Load More`.

Co se stane:
1. Blok si pamatuje timestamp nejstarší svíčky aktuálně zobrazené v grafu
2. Backend dostane požadavek: dej mi N svíček pro tento symbol/TF/asset_type končící před tímto timestampem
3. Nové svíčky se přidají na začátek grafu doleva
4. Indikátory se přepočítají na celé rozšířené sadě dat (staré + nové dohromady)
5. Tick zůstane beze změny — stále tickuje aktuální konec
6. Historický ukazatel se posune — příští Load More jde ještě hlouběji do historie
7. Pokud backend vrátí prázdné pole, `+ Load More` se deaktivuje (žádná starší data)

**Backend volání:** `GET /api/bars/{symbol}?tf={tf}&asset_type={asset_type}&count={N}&before_time={oldest_timestamp}` → `{ bars: [...] }`

### 4.8 Tick

- Tick běží automaticky na pozadí po každém resetu nebo Load More
- Aktualizuje poslední (nejnovější) svíčku v grafu
- Interval: každých 5s
- Neexistuje žádné tlačítko pro zapnutí/vypnutí — tick prostě běží
- Každý blok má vlastní tick timer pro svůj symbol a asset type
- Bloky se navzájem neovlivní

**Backend volání:** `GET /api/tick/{symbol}?asset_type={asset_type}` → `{ time, price }` — UI samo aktualizuje poslední svíčku

### 4.9 TF tlačítka

Šest tlačítek: `1m | 5m | 15m | 30m | 1h | 1D`  
Aktivní TF je vizuálně zvýrazněno (jiná barva pozadí).  
Kliknutí = reset grafu pro daný blok.  
Stav aktivního TF je vlastní pro každý blok.

### 4.10 Indikátory

Čtyři přepínací tlačítka: `SMA 20 | EMA 20 | RSI 14 | MACD`  
Každé tlačítko je toggle — klik zapne/vypne.  
Vizuálně: aktivní = zvýrazněné modře, neaktivní = šedé.  
Stav každého indikátoru je vlastní pro daný blok.

**Chování SMA / EMA:**
- Kreslí se jako overlay čára přímo na hlavním candlestick grafu
- Barva: SMA = oranžová, EMA = modrá

**Chování RSI:**
- Zobrazí se jako samostatný subchart pod volume
- Výška ~160px
- Obsahuje horizontální čáry na úrovni 70 (překoupeno) a 30 (přeprodáno)

**Chování MACD:**
- Zobrazí se jako samostatný subchart pod RSI (pokud RSI zapnut), jinak pod volume
- Výška ~160px
- Obsahuje MACD linii, Signal linii a histogram

**Přepočet indikátorů:**
- Automaticky při každém resetu grafu
- Automaticky při každém Load More (na celé rozšířené sadě)
- Automaticky každých ~60s jako součást tick cyklu (každý 12. tick)

**Backend volání:** `GET /api/indicators/{symbol}?tf={tf}&asset_type={asset_type}&active=ema,rsi` → `{ ema: [...], rsi: [...], ... }`

### 4.11 Nezávislost bloků — přehled

Každý blok si udržuje vlastní stav pro:

| Stav | Vlastní pro každý blok |
|---|---|
| Symbol | ✅ |
| Asset type | ✅ |
| Exchange | ✅ |
| Timeframe | ✅ |
| Počet svíček v input | ✅ |
| Historický ukazatel (Load More) | ✅ |
| Indikátory zapnuto/vypnuto | ✅ |
| Tick timer | ✅ |
| Trade lines (Entry, SL, TP) | ✅ viz sekce 5.9 |
| RSI / MACD subgrafy | ✅ |

---

## 5. Order Entry panel

### 5.1 Pozice na obrazovce

Panel je v pravém sloupci (~340px), začíná na úrovni horní hrany prvního grafového bloku. Levá část stránky (grafy) zabírá zbytek šířky. Panel je vizuálně sticky — při scrollování se udržuje viditelný.

### 5.2 Výběr grafu

V horní části panelu je přepínač `Obchoduji graf:` s možnostmi Graf 1 / Graf 2 / … / Graf N (zobrazí se jen aktivní grafy dle `chart_count`).

Tento výběr říká panelu:
- Který symbol zadávat do příkazů
- Odkud brát aktuální cenu pro výpočty (SL %, TP %, R/R, Risk)
- Na který graf kreslit trade lines

Bezprostředně pod přepínačem se zobrazí read-only info řádek: `AAPL | STOCK | SMART` — symbol, asset type a exchange zvoleného grafu. Uživatel je nemůže měnit zde, mění je přímo na daném grafovém bloku.

### 5.3 Dynamické posouvání panelu

Panel se vertikálně zarovná s horní hranou grafového bloku, na který je napojený.

- Napojený na Graf 1 → panel začíná na stejné výšce jako horní hrana bloku 1
- Přepnutí na Graf 2 → panel plynule sjede (CSS transition) na výšku horní hrany bloku 2
- Pokud uživatel zapne/vypne indikátory a změní výšku bloku nad aktivním blokem, panel se automaticky přepočítá

Pohyb je plynulý, ne skokový.

### 5.4 Množství

- Quick-select tlačítka: `1 | 5 | 10 | 25 | 100` — kliknutí nastaví hodnotu do vlastního inputu
- Vlastní input — vždy zdroj pravdy pro příkaz
- Při změně množství se SL/TP ceny nemění, přepočítá se pouze zobrazený dolarový Risk

### 5.5 Typ příkazu

Radio: `MARKET` (default) / `LIMIT`  
Při výběru LIMIT se odkryje pole `Limit Price $`, jinak je skryté.

### 5.6 Stop-Loss a Take-Profit

Každý lze zadat dvěma způsoby — absolutní cenou nebo procentem:

- **SL cena** — input s červeným rámečkem, absolutní cena
- **SL %** — input, přepočítá se od aktuální ceny zvoleného grafu: `SL = cena × (1 − SL%/100)`
- **TP cena** — input se zeleným rámečkem, absolutní cena
- **TP %** — input, přepočítá se od aktuální ceny zvoleného grafu: `TP = cena × (1 + TP%/100)`

Pokud je vyplněna absolutní cena, % se ignoruje a naopak. Absolutní cena má prioritu.

⚠️ SL a TP se neposílají jako bracket orders do IB. Ukládají se pouze lokálně a slouží pro:
1. Zobrazení čar na grafu
2. Výpočet R/R a Risk v panelu

### 5.7 Order Preview, R/R, Risk

Zobrazují se live bez serverového volání — počítají se v prohlížeči z dostupných hodnot.

- **Order Preview:** `📋 10× AAPL @ Market | 🛡️ SL $149.80 | 🎯 TP $155.00`
- **R/R:** `R/R: 1:2.4` — vzorec `(TP − entry) / (entry − SL)`, zobrazí `R/R: –` pokud chybí SL nebo TP
- **Risk:** `Risk: $75.00` — vzorec `|entry − SL| × qty`, zobrazí `Risk: –` pokud chybí SL

Aktuální cena pro výpočty = poslední tick cena zvoleného grafu (ne close svíčky, vždy z `/api/tick/`).

Při přepnutí na jiný graf se všechny tři hodnoty okamžitě přepočítají pro nový symbol a jeho cenu.

### 5.8 Poznámka

Volitelný textový input, max 100 znaků. Uloží se k obchodu v `trades.json`.

### 5.9 Trade lines na grafech

Trade lines (Entry, SL, TP) se kreslí na základě **symbolu obchodu vs. symbolu grafu** — ne podle toho na který graf je panel zrovna napojený.

Pravidlo: každý grafový blok si sám kontroluje které otevřené obchody mají stejný symbol jako jeho aktuální symbol, a kreslí jejich čáry.

Příklad: Panel je napojený na Graf 2 (EURUSD). Existuje otevřená pozice AAPL. Graf 1 zobrazuje AAPL → kreslí čáry pro AAPL pozici automaticky. Graf 2 zobrazuje EURUSD → kreslí čáry pro případné EURUSD pozice.

Refresh trade lines: každých 5s automaticky pro každý blok zvlášť.

**Backend volání:** `GET /api/trades/active_lines?symbol={symbol}&asset_type={asset_type}` → `[{ entry_price, sl, tp, side }]`

### 5.10 Akční tlačítka

- `🟢 BUY` — odešle příkaz pro symbol zvoleného grafu
- `🔴 SELL` — odešle příkaz pro symbol zvoleného grafu
- Příkaz jde vždy pro symbol, asset type a exchange zvoleného grafu — ne globálně

**Chování po odeslání:**
1. Zkontroluje připojení k IB — pokud není, zobrazí `❌ Not connected` a nepokračuje
2. Zkontroluje tržní hodiny — pokud trh není v regular session, zobrazí `⚠️ US market not in regular session` jako varování (neblokuje odeslání)
3. Pokud existuje protichůdná otevřená pozice stejného symbolu, callback ji automaticky částečně nebo úplně zavře před otevřením nové
4. Příkaz se odešle do IB
5. Feedback se zobrazí pod tlačítky

**Feedback formát:**
- Úspěch: `✅ BUY 10 AAPL @ Market | 🛡️ SL $149.80 | 🎯 TP $155.00` (zelená)
- Chyba: `❌ Not connected` nebo `❌ {chybová zpráva}` (červená)
- Varování + úspěch: `⚠️ US market closed. ✅ BUY 10 AAPL @ Market` (oranžová + zelená)

Feedback zůstane viditelný do dalšího odeslání příkazu.

**Backend volání:** `POST /api/orders` s body `{ symbol, asset_type, exchange, action, quantity, order_type, limit_price, sl, tp, note }`

---

## 6. Open Positions

Sekce pod grafovými bloky v levé zóně. Automatický refresh každých 10s.

### Ovládací prvky
- `🔄 Refresh` — manuální okamžitý refresh tabulky
- `❌ Close All Positions` — zavře všechny otevřené pozice tržními příkazy přes IB, potvrzovací dialog není (přímá akce)
- Feedback vedle tlačítka: `✅ Zavřeno 3 pozic` nebo `⚠️ Zavřeno 2, chyba: TSLA`

### Tabulka

Sloupce: `Symbol | Side | Qty | Avg Cost | Market Value | P&L | Vstup | SL | TP | Akce`

- **P&L** — počítá se z IB `avgCost`. Pokud `avgCost` není dostupný, použije se uložená vstupní cena z `trades.json`
- **P&L barva** — zelená = zisk, červená = ztráta
- **Vstup** — datum a čas vstupu, lokalizovaný (Praha CET/CEST)
- **SL / TP** — absolutní ceny uložené lokálně, `–` pokud nejsou nastaveny

### Tlačítka na každém řádku
- `⟲ BE` — Breakeven: nastaví SL = vstupní ceně tohoto obchodu, pouze lokálně v `trades.json`, neposílá nic do IB. Po stisknutí se trade line SL na příslušném grafu automaticky překreslí na novou hodnotu.
- `✖` — zavře konkrétní pozici tržním příkazem přes IB. Použije qty z daného obchodu (ne celkovou IB pozici).

---

## 7. Trade History

Sekce pod Open Positions. Automatický refresh každých 5s. Zobrazuje posledních 50 uzavřených obchodů ze souboru `trades.json`.

### Tabulka

Sloupce: `# | Symbol | Side | Qty | Entry $ | Vstup | Exit $ | Výstup | SL | TP | Poznámka | Komise | P&L`

- **P&L** — zelená = zisk, červená = ztráta
- **Komise** — zobrazí se pokud je uložena, jinak `–`
- **Časy** — lokalizovány na Praha CET/CEST

---

## 8. Settings

Na konci stránky. Výchozí stav: skrytá. Toggle tlačítkem `⚙️ Settings`.

### Sekce A — App defaults (aktivní)

| Položka | Typ | Popis |
|---|---|---|
| Favorite symbols | Text input | Čárkou oddělený seznam tickerů (AAPL, EURUSD, TSLA). První symbol = default po Save. |
| Default quantity | Number input | Výchozí množství v Order Entry při startu |
| Default candles count | Number input | Výchozí hodnota pole svíček v každém grafovém bloku při startu (výchozí: 60) |
| Default timeframe | Dropdown | 1 min / 5 mins / 15 mins / 30 mins / 1 hour / 1 day |
| Default asset type | Dropdown | STOCK / FOREX / CRYPTO |
| Default exchange | Dropdown | SMART / IBIS / AEB / SBF |
| Počet grafů | Dropdown | 1 / 2 / 3 / 4 — počet grafových bloků zobrazených na stránce, projeví se po refreshi stránky |

### Sekce B — AI Configuration (neaktivní, připraveno pro Phase 5)

⚠️ Pole se ukládají ale zatím nic nedělají.

| Položka | Typ | Popis |
|---|---|---|
| OpenRouter API key | Password input | Nezobrazuje se, neloguje se |
| LLM model | Text input | Např. `anthropic/claude-3.5-haiku` |
| Strategie / pravidla | Textarea | Popis obchodní strategie, bude se posílat AI |
| Money management | Textarea | MM pravidla, bude se posílat AI při entry dotazech |

### Tlačítko Save

`💾 Save Settings` — uloží vše do `data/config.json`.

Po uložení se okamžitě aktualizují v UI:
- Symbol input (prvního bloku) = první ze Favorite symbols
- Default quantity v Order Entry
- Asset type
- Exchange

Počet grafů se projeví až po refreshi stránky.

---

## 9. Backend API — přehled volání z UI

Tento přehled slouží jako kontrakt mezi frontendem a backendem. Backend musí tyto endpointy implementovat se správnými vstupy a výstupy. UI na nich závisí.

| Endpoint | Metoda | Volá se | Výstup (klíčové pole) |
|---|---|---|---|
| `/api/connection/status` | GET | každých 10s | `{ connected: bool }` |
| `/api/market/hours` | GET | každých 60s | `{ status, label, color }` |
| `/api/account/info` | GET | každých 10s | `{ account_id, net_liquidation, buying_power }` |
| `/api/tick/{symbol}` | GET | každých 5s per blok | `{ price, close, time }` |
| `/api/bars/{symbol}` | GET | na reset grafu | `{ bars: [{time,open,high,low,close,volume}] }` |
| `/api/bars/{symbol}` | GET | na Load More | stejný endpoint, jiný parametr `before_time` |
| `/api/indicators/{symbol}` | GET | po reset/load/tick | `{ ema, sma, rsi, macd }` |
| `/api/trades/active_lines` | GET | každých 5s per blok | `[{ entry_price, sl, tp, side }]` |
| `/api/trades/open` | GET | každých 10s | `{ trades: [...] }` |
| `/api/trades/history` | GET | každých 5s | `{ trades: [...] }` |
| `/api/trades/close/{id}` | POST | na ✖ tlačítko | `{ ok: bool, trade }` |
| `/api/trades/close_all` | POST | na Close All | `{ ok: bool, closed: int }` |
| `/api/trades/breakeven/{id}` | POST | na ⟲ BE | `{ ok: bool }` |
| `/api/orders` | POST | na BUY/SELL | `{ ok: bool, fill_price, message }` |
| `/api/settings` | GET | při startu | celý config objekt |
| `/api/settings` | POST | na Save | `{ ok: bool }` |

---

## 10. Pravidla konzistence UI

1. **Cena pro výpočty** — SL %, TP %, R/R a Risk se vždy počítají z poslední tick ceny (`/api/tick/`), nikdy ze close hodnoty svíčky. Tick cena je aktuálnější a přesnější.

2. **Trade lines** — každý grafový blok si sám hlídá které obchody patří jeho symbolu a kreslí jejich čáry. Order Entry panel neřídí kde se čáry kreslí — určuje pouze pro který symbol se příkaz podá.

3. **BE update** — po stisknutí Breakeven se SL změní v `trades.json` a příslušný grafový blok (jehož symbol odpovídá obchodu) automaticky překreslí SL čáru na novou hodnotu při nejbližším refresh cyklu.

4. **Počet svíček** — výchozí hodnota z `default_candles_count` v Settings. Každý blok má vlastní input, hodnoty jsou nezávislé.

5. **Přepočet indikátorů po Load More** — backend dostane celou sadu timestampů (nebo jen nové bary), UI vždy přepočítá indikátory ze všech aktuálně načtených barů dohromady aby byly hodnoty správné i na starých svíčkách.

6. **Dynamická výška bloků** — Order Entry panel přepočítá svou vertikální pozici při každé změně výšky grafových bloků (zapnutí/vypnutí RSI, MACD). Zarovnání je vždy vůči horní hraně aktivního bloku.


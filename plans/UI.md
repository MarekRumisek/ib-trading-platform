**Účel:** Tento dokument popisuje kompletní chování frontend UI. Slouží jako zadání pro AI agenta při implementaci. Backend (datové funkce, IB komunikace) je řešen separátně — UI volá backend přes definované API endpointy. UI neví nic o tom jak backend data získává, jen co si má vyžádat a co dostane zpět. Pozice sekcí v layoutu jsou výchozí — v budoucnu lze jednotlivé sekce přemístit aniž by se měnila jejich funkce.
---
## Architektonický princip
UI a backend jsou oddělené vrstvy. UI nikdy nepracuje přímo s IB ani s daty — vždy volá backend endpoint, dostane odpověď a tu zobrazí nebo předá do grafu. Každý endpoint má jasně definovaný vstup a výstup. Tím je možné backend testovat a vyvíjet nezávisle a UI stavět na jistotě že rozhraní funguje.
---
## Celkový layout stránky
Aplikace je single-page, tmavý motiv, běží na `http://localhost:8050`.
Stránka se skládá ze dvou hlavních zón:
**Levá zóna (hlavní obsah)** — zabírá zbývající šířku:
- Header
- Account Info
- Grafové bloky (N kusů pod sebou)
- AI Trade Advisor — Sekce A (Evaluate Entry)
- AI Trade Advisor — Sekce B (Check Position)
- Open Positions
- Trade History
- Settings
**Pravá zóna (fixní panel ~340px)** — začíná na úrovni prvního grafového bloku:
- Order Entry panel
Pravá zóna je sticky — při scrollování zůstává v pravém sloupci a vizuálně se zarovnává s aktivním grafovým blokem.
---
## 1. Header
Gradient pruh přes celou šířku nahoře stránky.
**Obsah:**
- `🚀 IB Trading Platform v3.0` — statický název vlevo
- **Market hours badge** — barevný štítek, refresh každých 60s
  - 🟢 `US Regular`
  - 🟡 `Pre-Market` nebo `After-Hours`
  - 🔴 `Closed`
- **Connection status** — vpravo, refresh každých 10s
  - `● Connected to IB Gateway` (zelená tečka)
  - `● Disconnected` (červená tečka)
**Backend volání:**
- `GET /api/connection/status` → `{ connected: bool }`
- `GET /api/market/hours` → `{ status, label, color }`
---
## 2. Account Info
Tmavá lišta těsně pod headerem, refresh každých 10s.
**Zobrazuje:**
- `💼 Account:` číslo IB účtu
- `💰 Balance:` Net Liquidation Value formátovaná jako `$0.00`
- `📈 Buying Power:` dostupná kupní síla formátovaná jako `$0.00`
Při odpojení: všechna pole zobrazí `Not Connected` resp. `$0.00`.
**Backend volání:**
- `GET /api/account/info` → `{ account_id, net_liquidation, buying_power }`
---
## 3. Grafové bloky
### 3.1 Počet bloků
Počet grafových bloků určuje nastavení `chart_count` (1–4) uložené v konfiguraci. Načte se při startu stránky. Bloky se renderují dynamicky — je jich přesně tolik kolik říká `chart_count`. Všechny bloky jsou identické co do struktury a kódu, liší se pouze svým indexem a vlastním nezávislým stavem.
### 3.2 Struktura jednoho bloku (shora dolů)
[ Symbol input ] [ Asset type ▼ ] [ Exchange ▼ ] Last: $182.34 ▲ +$1.20 (+0.66%)
[ 60 ▲▼ svíček ] [ + Load More ]
─────────────────────────────────────────────────────────────────────
[ 1m ] [ 5m ] [ 15m ] [ 30m ] [ 1h ] [ 1D ] ⏳ Načítám...
[ SMA 20 ] [ EMA 20 ] [ RSI 14 ] [ MACD ]
─────────────────────────────────────────────────────────────────────
LWC Candlestick Chart
─────────────────────────────────────────────────────────────────────
Volume subchart
─────────────────────────────────────────────────────────────────────
RSI subchart (pouze pokud zapnut)
─────────────────────────────────────────────────────────────────────
MACD subchart (pouze pokud zapnut)
### 3.3 Symbol, Asset type, Exchange
- **Symbol input** — textový input, uživatel napíše ticker (např. `AAPL`, `EURUSD`)
- Potvrzení: Enter nebo kliknutí mimo pole → spustí reset grafu
- **Asset type** — dropdown: `STOCK / FOREX / CRYPTO`
- **Exchange** — dropdown: `SMART / IBIS / AEB / SBF`
- Změna Asset type nebo Exchange = reset grafu stejně jako nový symbol
- Všechna tři pole jsou vlastní pro každý blok, vzájemně nezávislá
### 3.4 Aktuální cena
Zobrazuje se napravo od Exchange dropdownu na stejném řádku.
- Formát: `Last: $182.34 ▲ +$1.20 (+0.66%)`
- Šipka a barva: zelená ▲ = kladná změna, červená ▼ = záporná
- Refresh každých 10s
- Cena se načítá z backendu pro symbol a asset type daného bloku
- FOREX: 4 desetinná místa. STOCK/CRYPTO: 2 desetinná místa
**Backend volání:**
- `GET /api/tick/{symbol}?asset_type={asset_type}` → `{ price, close, time }`
### 3.5 Počet svíček a Load More
- **Input pole** — číslo, min 10, max 500, výchozí z `default_candles_count` v Settings
- **`+ Load More` tlačítko** — přidá historii (viz 3.7)
- Hodnota v inputu platí pro oba typy operace (reset i load more)
- Stav inputu je vlastní pro každý blok
### 3.6 Reset grafu
Spouští se při:
- Kliknutí na TF tlačítko (1m, 5m, 15m, 30m, 1h, 1D)
- Potvrzení nového symbolu
- Změně Asset type nebo Exchange
Co se stane:
1. Graf se vymaže (všechny svíčky, indikátory, subgrafy, AI anotace)
2. Backend dostane požadavek: N nejnovějších svíček pro tento symbol/TF/asset_type od teď dozadu
3. Svíčky se zobrazí v grafu
4. Indikátory se přepočítají na nových datech
5. Tick se napojí na nový symbol/TF — automaticky bez akce uživatele
6. Historický ukazatel se resetuje (Load More začne od nejstarší načtené svíčky)
7. Loading indikátor během načítání: `⏳ Načítám 5m…`
**Backend volání:**
- `GET /api/bars/{symbol}?tf={tf}&asset_type={asset_type}&count={N}&end_time=now`
  → `{ bars: [{time, open, high, low, close, volume}] }`
### 3.7 Load More
Spouští se kliknutím na `+ Load More`.
Co se stane:
1. Blok si pamatuje timestamp nejstarší svíčky aktuálně zobrazené v grafu
2. Backend dostane požadavek: N svíček končící před tímto timestampem
3. Nové svíčky se přidají na začátek grafu doleva
4. Indikátory se přepočítají na celé rozšířené sadě (staré + nové dohromady)
5. Tick zůstane beze změny — stále tickuje aktuální konec
6. Historický ukazatel se posune — příští Load More jde ještě hlouběji
7. Pokud backend vrátí prázdné pole, `+ Load More` se deaktivuje (žádná starší data)
**Backend volání:**
- `GET /api/bars/{symbol}?tf={tf}&asset_type={asset_type}&exchange={exchange}&count={N}&before_time={oldest_timestamp}`
  → `{ bars: [...] }`
### 3.8 Tick
- Tick běží automaticky na pozadí po každém resetu nebo Load More
- Aktualizuje poslední (nejnovější) svíčku v grafu
- Interval: každých 5s
- Žádné tlačítko pro zapnutí/vypnutí — tick prostě běží tiše
- Každý blok má vlastní tick timer pro svůj symbol a asset type
- Bloky se navzájem neovlivní
**Backend volání:**
- `GET /api/tick/{symbol}?asset_type={asset_type}` → `{ time, price }`
- UI samo aktualizuje poslední svíčku
### 3.9 TF tlačítka
Šest tlačítek: `1m | 5m | 15m | 30m | 1h | 1D`
Aktivní TF je vizuálně zvýrazněno (jiná barva pozadí).
Kliknutí = reset grafu pro daný blok.
Stav aktivního TF je vlastní pro každý blok.
### 3.10 Indikátory
Čtyři přepínací tlačítka: `SMA 20 | EMA 20 | RSI 14 | MACD`
Každé je toggle — klik zapne/vypne.
Aktivní = zvýrazněné modře, neaktivní = šedé.
Stav každého indikátoru je vlastní pro daný blok.
**Chování SMA / EMA:**
- Kreslí se jako overlay čára na hlavním candlestick grafu
- Barva: SMA = oranžová, EMA = modrá
**Chování RSI:**
- Samostatný subchart pod volume, výška ~160px
- Horizontální čáry na 70 (překoupeno) a 30 (přeprodáno)
**Chování MACD:**
- Samostatný subchart pod RSI (pokud zapnut), jinak pod volume, výška ~160px
- Obsahuje MACD linii, Signal linii a histogram
**Přepočet indikátorů:**
- Automaticky při každém resetu grafu
- Automaticky při každém Load More (na celé rozšířené sadě)
- Automaticky každých ~60s jako součást tick cyklu (každý 12. tick)
**Backend volání:**
- `GET /api/bars/{symbol}?tf={tf}&asset_type={asset_type}&exchange={exchange}&count={N}&end_time=now`
  → `{ bars: [{time, open, high, low, close, volume}] }`
### 3.11 Trade lines na grafech
Každý grafový blok si sám kontroluje které otevřené obchody mají stejný symbol jako jeho aktuální symbol a kreslí jejich čáry. Order Entry panel ani AI panel neřídí kde se čáry kreslí — rozhoduje shoda symbolu obchodu a symbolu grafu.
Typy čar:
- **Entry** — bílá přerušovaná čára
- **SL** — červená čára
- **TP** — zelená čára
Refresh trade lines: každých 5s automaticky pro každý blok.
Po Breakeven akci: příslušný blok překreslí SL čáru při nejbližším refresh cyklu.
**Backend volání:**
- `GET /api/trades/active_lines?symbol={symbol}&asset_type={asset_type}`
  → `[{ entry_price, sl, tp, side }]`
### 3.12 AI anotace na grafech
Po úspěšném AI Evaluate se na grafu zvoleném v AI selectoru zobrazí čáry a zóny navržené AI (support/resistance, vstupní zóna, cílová zóna). AI anotace jsou vizuálně odlišné od trade lines — jiná barva, jiný styl čáry. Při Reject nebo Dismiss se anotace smažou. Při resetu grafu (nový TF, nový symbol) se anotace smažou automaticky.
### 3.13 Nezávislost bloků
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
| Trade lines (Entry, SL, TP) | ✅ |
| RSI / MACD subgrafy | ✅ |
| AI anotace | ✅ |
### 3.14 Vzorový princip duplikace
Všechny bloky vycházejí z jednoho vzoru. Pokud se opraví nebo přidá funkce (nový indikátor, jiné chování Load More, nový typ price line), změna se projeví ve všech blocích — sdílejí stejný kód a liší se jen indexem a stavem.
---
## 4. Order Entry panel
### 4.1 Pozice na obrazovce
Panel je v pravém sloupci (~340px), začíná na úrovni horní hrany prvního grafového bloku. Levá část stránky (grafy) zabírá zbytek šířky. Panel je vizuálně sticky — při scrollování zůstává viditelný.
### 4.2 Výběr grafu
V horní části panelu je přepínač `Obchoduji graf:` s možnostmi Graf 1 / … / Graf N (jen aktivní grafy dle `chart_count`).
Tento výběr říká panelu:
- Který symbol a asset type použít pro příkaz
- Odkud brát aktuální cenu pro výpočty (SL %, TP %, R/R, Risk)
- Na který graf kreslit trade lines po odeslání příkazu (kreslí se automaticky dle symbolu — viz 3.11)
Pod přepínačem se zobrazí read-only info řádek: `AAPL | STOCK | SMART`
Uživatel tyto hodnoty nemůže měnit zde — mění je přímo na grafovém bloku.
### 4.3 Dynamické posouvání panelu
Panel se vertikálně zarovná s horní hranou grafového bloku na který je napojený.
- Graf 1 → panel začíná na výšce horní hrany bloku 1
- Přepnutí na Graf 2 → panel plynule sjede (CSS transition) na výšku horní hrany bloku 2
- Pokud se změní výška bloku nad aktivním blokem (zapnutí/vypnutí indikátorů), panel se automaticky přepočítá
### 4.4 Množství
- Quick-select: `1 | 5 | 10 | 25 | 100` — kliknutí nastaví hodnotu do vlastního inputu
- Vlastní input — vždy zdroj pravdy pro příkaz
- Při změně množství se SL/TP ceny nemění, přepočítá se pouze zobrazený Risk
### 4.5 Typ příkazu
Radio: `MARKET` (default) / `LIMIT`
Při LIMIT se odkryje pole `Limit Price $`, jinak skryté.
### 4.6 Stop-Loss a Take-Profit
Každý lze zadat dvěma způsoby:
- **SL cena** — input s červeným rámečkem, absolutní cena
- **SL %** — přepočítá se od aktuální tick ceny zvoleného grafu: `SL = cena × (1 − SL%/100)`
- **TP cena** — input se zeleným rámečkem, absolutní cena
- **TP %** — přepočítá se od aktuální tick ceny: `TP = cena × (1 + TP%/100)`
Absolutní cena má prioritu nad procentem — pokud je vyplněna absolutní cena, % se ignoruje.
⚠️ SL a TP se neposílají jako bracket orders do IB. Ukládají se pouze lokálně v `trades.json` a slouží pro zobrazení čar na grafu a výpočet R/R a Risk.
### 4.7 Order Preview, R/R, Risk
Počítají se live v prohlížeči bez serverového volání.
Aktuální cena pro výpočty = vždy poslední tick cena (`/api/tick/`) zvoleného grafu, nikdy close hodnota svíčky.
- **Order Preview:** `📋 10× AAPL @ Market | 🛡️ SL $149.80 | 🎯 TP $155.00`
- **R/R:** `R/R: 1:2.4` — vzorec `(TP − entry) / (entry − SL)`, zobrazí `R/R: –` pokud chybí SL nebo TP
- **Risk:** `Risk: $75.00` — vzorec `|entry − SL| × qty`, zobrazí `Risk: –` pokud chybí SL
Při přepnutí na jiný graf se všechny tři hodnoty okamžitě přepočítají pro nový instrument.
### 4.8 Poznámka
Volitelný textový input, max 100 znaků. Uloží se k obchodu v `trades.json`.
### 4.9 Akční tlačítka
- `🟢 BUY` — odešle příkaz pro symbol zvoleného grafu
- `🔴 SELL` — odešle příkaz pro symbol zvoleného grafu
**Chování po odeslání:**
1. Zkontroluje připojení — pokud chybí, zobrazí `❌ Not connected`, nepokračuje
2. Zkontroluje tržní hodiny — pokud mimo regular session, zobrazí `⚠️ US market not in regular session` (neblokuje odeslání)
3. Pokud existuje protichůdná otevřená pozice stejného symbolu, automaticky se částečně nebo úplně zavře
4. Příkaz se odešle do IB
5. Feedback se zobrazí pod tlačítky
**Feedback formát:**
- Úspěch: `✅ BUY 10 AAPL @ Market | 🛡️ SL $149.80 | 🎯 TP $155.00` (zelená)
- Chyba: `❌ Not connected` nebo `❌ {chybová zpráva}` (červená)
- Varování + úspěch: `⚠️ US market closed — ✅ BUY 10 AAPL @ Market` (oranžová + zelená)
Feedback zůstane viditelný do dalšího odeslání.
**Backend volání:**
- `POST /api/orders` s body `{ symbol, asset_type, exchange, action, quantity, order_type, limit_price, sl, tp, note }`
---
## 5. AI Trade Advisor — Sekce A: Evaluate Entry
Tato sekce slouží k vyhodnocení potenciálního nového vstupu do trhu. Je umístěna pod grafovými bloky v levé zóně.
### 5.1 Výběr grafu pro AI
V horní části sekce je přepínač **"AI pracuje s grafem:"** — Graf 1 / … / Graf N (jen aktivní grafy). Tento výběr určuje:
- Který symbol a asset type se použije jako primární kontext pro AI dotaz
- Na který graf se nakreslí AI anotace po obdržení odpovědi
Pod přepínačem: read-only info řádek `AAPL | STOCK` — symbol a asset type zvoleného grafu.
### 5.2 Výběr grafů pro kontext
Pod selectorem hlavního grafu je řádek **"Zahrnout data z grafů:"** s checkboxy Graf 1 / … / Graf N. Uživatel zvolí ze kterých grafů se pošlou svíčky jako kontext.
Vedle checkboxů: číselný input **"Max. svíček / graf"** — omezuje kolik svíček se pošle z každého zaškrtnutého grafu. Výchozí hodnota se načítá z `ai_max_bars_per_chart` v Settings, ale uživatel ji může pro konkrétní dotaz přepsat. Vždy se posílají nejnovější bary (od konce doleva do limitu). Info text vedle inputu zobrazuje odhad: `~200 řádků dat`.
⚠️ Limit existuje z důvodu kontroly počtu tokenů — čím více svíček, tím dražší a pomalejší volání API.
### 5.3 Tlačítko Evaluate
`🔍 Evaluate` — spustí AI analýzu.
Před odesláním:
- Zkontroluje zda je nastaven API key a model v Settings — pokud ne, zobrazí `⚠️ Nastav OpenRouter API key a model v Settings` a nepokračuje
- Zkontroluje zda je zvolen aspoň jeden graf v checkboxech — pokud ne, zobrazí varování
Po kliknutí se zobrazí loading indikátor `⏳ Analyzuji…` — trvá typicky 5–15 sekund.
**Co se pošle na backend / AI:**
- Zůstatek účtu a buying power
- OHLCV svíčky ze všech zaškrtnutých grafů (každý do limitu max. svíček)
- Aktivní indikátory zvoleného hlavního grafu (EMA, SMA, RSI, MACD — jen zapnuté)
- Strategie a MM pravidla ze Settings
**Backend volání:**
- `POST /api/ai/evaluate` s body `{ primary_graph_index, graphs: [{symbol, tf, asset_type, bars: [...]}], indicators: {...}, account: {...} }`
  → `{ recommendation, order_type, entry_price, sl, tp, quantity, rr_ratio, reason, annotations: [...] }`
### 5.4 Response oblast A
Zobrazí se po úspěšné odpovědi:
Recommendation: BUY | Order: MARKET | R/R: 1:2.4
Entry: $151.20 SL: $149.80 TP: $154.00 Qty: 5
Reason: [text odůvodnění od AI]
Pod response textem:
- `✅ Accept` — automaticky vyplní Order Entry panel (symbol, typ příkazu, SL, TP, množství) a odešle příkaz pro instrument zvoleného AI grafu. Po kliknutí se Accept a Reject skryjí.
- `❌ Reject` — zavře response oblast, vymaže AI anotace z grafu. Po kliknutí se nic neodešle.
Error oblast — zobrazí chybový text pokud volání selže nebo API key chybí.
### 5.5 AI anotace z Evaluate
Po úspěšném Evaluate se na grafu zvoleném v AI selectoru zobrazí čáry a zóny z odpovědi (support, resistance, vstupní zóna, cílová zóna). Anotace jsou vizuálně odlišné od trade lines. Při Reject nebo resetu grafu se smažou automaticky.
---
## 6. AI Trade Advisor — Sekce B: Check Position
Tato sekce slouží k vyhodnocení již běžící otevřené pozice. Je umístěna pod Sekcí A v levé zóně. Má vlastní nezávislou response oblast — nezasahuje do Sekce A a nevymaže její výsledek.
### 6.1 Spuštění
Sekce B se aktivuje kliknutím na tlačítko `🤖 Check` na konkrétním řádku v tabulce Open Positions. Po kliknutí:
- Stránka automaticky scrolluje na Sekci B aby byl výsledek viditelný
- Sekce B zobrazí info řádek s detaily daného obchodu
- Okamžitě se spustí AI analýza (bez dalšího kliknutí)
### 6.2 Výběr grafů pro kontext
Sekce B má stejný mechanismus výběru grafů jako Sekce A:
- **"AI pracuje s grafem:"** — přepínač pro primární graf (výchozí = graf jehož symbol odpovídá obchodu, pokud existuje)
- **"Zahrnout data z grafů:"** — checkboxy s limitem svíček
- Uživatel může výběr upravit před opakovaným spuštěním analýzy
### 6.3 Info řádek
Zobrazuje kontext kontrolovaného obchodu:
Kontroluji: AAPL BUY 10× | Entry $151.20 | SL $149.80 | TP $154.00 | P&L +$32.00
### 6.4 Loading a Response oblast B
Loading indikátor: `⏳ Analyzuji pozici…`
Response po úspěšné odpovědi:
Action: MOVE_SL | New SL: $150.20
Reason: [text odůvodnění od AI]
Akční tlačítko se zobrazí kontextově dle doporučení:
- `MOVE_SL` nebo `MOVE_TP` → `✔ Apply` — aktualizuje SL/TP lokálně v `trades.json` a překreslí čáry na příslušném grafu při nejbližším refresh cyklu
- `CLOSE` → `✖ Close Position` — zavře pozici tržním příkazem přes IB
- `HOLD` → žádné akční tlačítko
Vždy přítomné: `❌ Dismiss` — zavře response oblast, žádná akce.
**Co se pošle na backend / AI:**
- OHLCV svíčky ze zaškrtnutých grafů (do limitu)
- Aktivní indikátory zvoleného primárního grafu
- Vstupní cena, aktuální SL, TP a aktuální P&L obchodu
- Strategie ze Settings — MM pravidla se **neposílají** (jde o řízení běžící pozice, ne nový vstup)
**Backend volání:**
- `POST /api/ai/check_position` s body `{ trade_id, primary_graph_index, graphs: [{symbol, tf, asset_type, bars: [...]}], indicators: {...}, trade: { entry_price, sl, tp, pnl } }`
  → `{ action, new_sl, new_tp, reason }`
---
## 7. Open Positions
Sekce pod AI sekcemi v levé zóně. Automatický refresh každých 10s.
### Ovládací prvky
- `🔄 Refresh` — manuální okamžitý refresh
- `❌ Close All Positions` — zavře všechny pozice tržními příkazy, přímá akce bez potvrzovacího dialogu
- Feedback: `✅ Zavřeno 3 pozic` nebo `⚠️ Zavřeno 2, chyba: TSLA`
### Tabulka
Sloupce: `Symbol | Side | Qty | Avg Cost | Market Value | P&L | Vstup | SL | TP | Akce`
- **P&L** — z IB `avgCost`. Pokud nedostupný, použije uloženou vstupní cenu z `trades.json`
- **P&L barva** — zelená = zisk, červená = ztráta
- **Vstup** — datum a čas, lokalizovaný (Praha CET/CEST)
- **SL / TP** — absolutní ceny z `trades.json`, `–` pokud nejsou nastaveny
### Tlačítka na každém řádku
- `⟲ BE` — nastaví SL = vstupní ceně, pouze lokálně v `trades.json`, neposílá nic do IB. Příslušný graf překreslí SL čáru při nejbližším refresh cyklu.
- `🤖 Check` — aktivuje Sekci B AI panelu pro tento obchod a scrolluje na ni
- `✖` — zavře konkrétní pozici tržním příkazem přes IB
---
## 8. Trade History
Sekce pod Open Positions. Automatický refresh každých 5s. Zobrazuje posledních 50 uzavřených obchodů ze souboru `trades.json`.
### Tabulka
Sloupce: `# | Symbol | Side | Qty | Entry $ | Vstup | Exit $ | Výstup | SL | TP | Poznámka | Komise | P&L`
- **P&L** — zelená = zisk, červená = ztráta
- **Komise** — zobrazí se pokud uložena, jinak `–`
- **Časy** — lokalizovány na Praha CET/CEST
- Zdroj: `data/trades.json`
---
## 9. Settings
Na konci stránky. Výchozí stav: skrytá. Toggle tlačítkem `⚙️ Settings`.
### Sekce A — App defaults
| Položka | Typ | Popis |
|---|---|---|
| Favorite symbols | Text input | Čárkou oddělený seznam tickerů (AAPL, EURUSD, TSLA). První = default symbol po Save. |
| Default quantity | Number input | Výchozí množství v Order Entry při startu |
| Default candles count | Number input | Výchozí hodnota pole svíček v každém grafovém bloku při startu (výchozí: 60) |
| Default timeframe | Dropdown | 1 min / 5 mins / 15 mins / 30 mins / 1 hour / 1 day |
| Default asset type | Dropdown | STOCK / FOREX / CRYPTO |
| Default exchange | Dropdown | SMART / IBIS / AEB / SBF |
| Počet grafů | Dropdown | 1 / 2 / 3 / 4 — projeví se po refreshi stránky |
### Sekce B — AI Configuration
⚠️ Pole se ukládají, ale AI logika bude aktivována v Phase 5.
| Položka | Typ | Popis |
|---|---|---|
| OpenRouter API key | Password input | Nezobrazuje se, neloguje se nikam |
| LLM model | Text input | Např. `anthropic/claude-3.5-haiku` |
| Max. svíček / graf pro AI | Number input | Výchozí limit svíček posílaných AI z každého grafu (výchozí: 100, rozsah: 10–500) |
| Strategie / pravidla | Textarea | Posílá se AI s každým Evaluate dotazem |
| Money management | Textarea | Posílá se AI jen s Evaluate — ne s Check Position |
### Tlačítko Save
`💾 Save Settings` — uloží vše do `data/config.json`.
Po uložení se okamžitě aktualizují v UI:
- Symbol input (prvního bloku) = první ze Favorite symbols
- Default quantity v Order Entry
- Asset type a Exchange
Počet grafů se projeví až po refreshi stránky.
---
## 10. Backend API — kontrakt UI ↔ backend
Tento přehled slouží jako kontrakt. Backend musí implementovat tyto endpointy se správnými vstupy a výstupy. UI na nich závisí a nepracuje jinak.
| Endpoint | Metoda | Volá se kdy | Klíčový výstup |
|---|---|---|---|
| `/api/connection/status` | GET | každých 10s | `{ connected: bool }` |
| `/api/market/hours` | GET | každých 60s | `{ status, label, color }` |
| `/api/account/info` | GET | každých 10s | `{ account_id, net_liquidation, buying_power }` |
| `/api/tick/{symbol}` | GET | každých 5s per blok | `{ price, close, time }` |
| `/api/bars/{symbol}` | GET | reset grafu | `{ bars: [{time,open,high,low,close,volume}] }` |
| `/api/bars/{symbol}` | GET | reset grafu — params: `tf, asset_type, exchange, count, end_time=now` | `{ bars: [{time,open,high,low,close,volume}] }` |
| `/api/bars/{symbol}` | GET | Load More — params: `tf, asset_type, exchange, count, before_time` | stejný výstup |
| `/api/indicators/{symbol}` | GET | po reset/load/tick | `{ ema, sma, rsi, macd }` |
| `/api/trades/active_lines` | GET | každých 5s per blok | `[{ entry_price, sl, tp, side }]` |
| `/api/trades/open` | GET | každých 10s | `{ trades: [...] }` |
| `/api/trades/history` | GET | každých 5s | `{ trades: [...] }` |
| `/api/trades/close/{id}` | POST | na ✖ tlačítko | `{ ok: bool, trade }` |
| `/api/trades/close_all` | POST | na Close All | `{ ok: bool, closed: int }` |
| `/api/trades/breakeven/{id}` | POST | na ⟲ BE | `{ ok: bool }` |
| `/api/trades/patch/{id}` | POST | Apply MOVE_SL/TP | `{ ok: bool }` |
| `/api/orders` | POST | na BUY/SELL | `{ ok: bool, fill_price, message }` |
| `/api/ai/evaluate` | POST | na 🔍 Evaluate | `{ recommendation, order_type, entry_price, sl, tp, quantity, rr_ratio, reason, annotations }` |
| `/api/ai/check_position` | POST | na 🤖 Check | `{ action, new_sl, new_tp, reason }` |
| `/api/settings` | GET | při startu | celý config objekt |
| `/api/settings` | POST | na Save | `{ ok: bool }` |
---
## 11. Pravidla konzistence UI
1. **Cena pro výpočty** — SL %, TP %, R/R a Risk se vždy počítají z poslední tick ceny (`/api/tick/`), nikdy ze close hodnoty svíčky.
2. **Trade lines** — každý grafový blok si sám hlídá které obchody odpovídají jeho symbolu a kreslí jejich čáry. Order Entry ani AI panel neřídí kde se čáry kreslí.
3. **BE update** — po stisknutí BE se SL změní v `trades.json` a grafový blok se správným symbolem automaticky překreslí SL čáru při nejbližším refresh cyklu.
4. **AI anotace** — kreslí se vždy na grafu zvoleném v AI selectoru (ne pevně na prvním bloku). Při resetu grafu nebo Reject/Dismiss se smažou automaticky.
5. **Výchozí primární graf v Sekci B** — při kliknutí na `🤖 Check` se v AI Sekci B automaticky předvybere graf jehož symbol odpovídá symbolu obchodu (pokud takový graf existuje). Uživatel může výběr změnit.
6. **Max. svíček pro AI** — Settings definuje globální výchozí hodnotu. Input přímo v AI sekci umožňuje override pro konkrétní dotaz. Vždy se posílají nejnovější bary do limitu.
7. **Přepočet indikátorů po Load More** — UI přepočítá indikátory vždy ze všech aktuálně načtených barů dohromady, nikoli jen z nových.
8. **Dynamická výška bloků** — Order Entry panel přepočítá svou vertikální pozici při každé změně výšky grafových bloků (zapnutí/vypnutí RSI, MACD). Zarovnání je vždy vůči horní hraně aktivního bloku.
9. **Sekce A a B jsou nezávislé** — výsledek Evaluate v Sekci A a výsledek Check Position v Sekci B jsou zobrazeny současně, jedna sekce nepřepíše výsledek druhé.
10. **Scroll na Sekci B** — po kliknutí na `🤖 Check` v tabulce Open Positions stránka automaticky scrolluje na Sekci B aby byl výsledek viditelný bez nutnosti ručního scrollování.

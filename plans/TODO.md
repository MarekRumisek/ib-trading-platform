## TODO: Chart 2 — kompletní sjednocení s Chart 1

### Problém
Chart 2 (Context Chart) není totožný s Chart 1.
Liší se v layoutu, chybějící funkce, jiný asset type default.

### Co musí být IDENTICKÉ s Chart 1:

1. Layout (shora dolů):
   - Řádek 1: TF tlačítka (1m|5m|15m|30m|1h|1D) vlevo,
     status text vpravo ("Data z cache načtena" atd.)
   - Řádek 2: Indikátory (SMA 20 | EMA 20 | RSI 14 | MACD)
   - Řádek 3: Symbol input | Asset type dropdown |
     Exchange dropdown | svíček input | + Load More tlačítko |
     info "120 svíček (+60)" | Last: $cena
   - Graf (LWC candlestick)
   - Volume subchart
   - RSI subchart (pokud zapnut)
   - MACD subchart (pokud zapnut)

2. Výchozí hodnoty stejné jako Chart 1:
   - Symbol: AAPL
   - Asset type: STOCK (ne Forex!)
   - Exchange: SMART (US)
   - TF: 1D (výchozí pro context chart)
   - Svíček: 60

3. Funkce které musí fungovat stejně:
   - Load Chart (ne "Load Chart 2" — stejný text)
   - + Load More (historické svíčky)
   - TF přepínání
   - Indikátory toggle (SMA/EMA/RSI/MACD)
   - Tick každých 5s
   - Trade lines (Entry/SL/TP pro stejný symbol)
   - Last price zobrazení

4. Co je ODLIŠNÉ (legitimně):
   - Výchozí TF = 1D (context = delší timeframe)
   - Bez RSI/MACD subchartů výchozí (lze zapnout)
   - Label "📊 Context Chart" místo žádného labelu

5. Implementace:
   - Všechny Chart 2 callbacks musí být přesná kopie
     Chart 1 callbacks se změněnými ID (chart2-* místo chart-*)
   - Sdílí stejné backend endpointy — /api/bars, /api/tick atd.
   - Kód nesmí mít výjimky "chart 2 má jen candlestick+volume"
     — musí mít plnou funkčnost

### Jak implementovat
Projdi app.py a najdi všechny Chart 1 callbacks.
Pro každý vytvoř identickou kopii s:
  - chart- → chart2-
  - lwc-container → lwc-container-2
  - tf-* → tf2-*
Spusť app a ověř vizuálně že oba charty vypadají identicky.

### Ověření
1. Chart 2 se načte s 1D AAPL STOCK svíčkami po Load Chart
2. EMA 20 funguje na Chart 2
3. Tick běží na Chart 2 (Last: cena se aktualizuje)
4. Load More přidá historická data do Chart 2
5. python3.11 tools/test_backend.py — 20+/23

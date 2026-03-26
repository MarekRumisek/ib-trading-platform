Základní příkazy v DevTools konzoli:
    chartDebug.status()                          // stav obou chartů
    chartDebug.validateTimestamps()              // detekce timestamp chyb
    chartDebug.testBars('AAPL', '1 day', 'STOCK', 10)  // test backend
    chartDebug.testTick()                        // test tick API
    chartDebug.autoCheck(5000)                   // auto-kontrola každých 5s
    chartDebug.stopAutoCheck()                   // zastav auto-kontrolu
      Časté chyby odhalené tímto panelem:
  - Daily bary nejsou na UTC midnight → opraveno v ib_connector.py
    přes calendar.timegm() místo datetime.timestamp()
  - /api/bars/ vrací 500 → zkontroluj backend/market.py konverzi
    dict klíčů (lowercase: 'open' ne 'Open', 'time' ne bar.name)
  - tfSeconds neodpovídá UI timeframu → Dash TF callback musí volat
    lwcManager.setCurrentTf(tf) přes clientside_callback
  - RSI/MACD blikají při auto-refresh → zkontroluj setIndicators()
    zda používá series.setData() místo destroy+recreate
  - [x] Fáze 1: Graf Debug Panel (window.chartDebug)
  - [x] Fáze 2: Daily timestamp timezone bug (calendar.timegm)
  - [x] Fáze 3: tfSeconds stale state při přepnutí TF
  - [x] Fáze 4: Listener leak v syncTimeScales
  - [x] Fáze 5: setIndicators update místo destroy/recreate
  - [x] Fáze 6: prependData viewport reset (requestAnimationFrame)
  - [x] Fáze 7: Chart 2 plná unifikace s Chart 1
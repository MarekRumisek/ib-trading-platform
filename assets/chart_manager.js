/**
 * IB Trading Platform - Lightweight Charts Manager v2.1.0
 * =========================================================
 * v2.1.0:
 *   - Tick polling defaultne OFF (ridi uzivatel tlacitkem)
 *   - Spravne H/L tracking pro aktualni svicku
 *   - setTickEnabled(bool) - public API
 *   - TICK_POLL_MS = 5000 (data jsou 15min delayed na demo uctu)
 */
(function () {
    'use strict';

    var VERSION         = 'v2.1.0';
    var TICK_POLL_MS    = 5000;   // 5s staci - data jsou 15min delayed na paper accountu
    var CHART_BG        = '#1e1e2e';
    var GRID_COLOR      = '#3d3d4a';
    var TEXT_COLOR      = '#d1d4dc';
    var UP_COLOR        = '#26a69a';
    var DOWN_COLOR      = '#ef5350';
    var CHART_HEIGHT    = 500;

    var chart           = null;
    var candleSeries    = null;
    var volumeSeries    = null;
    var tickTimer       = null;
    var tickEnabled     = false;   // defaultne OFF - ridi uzivatel
    var currentSymbol   = null;
    var lastBarTime     = null;
    var lastBarOpen     = null;
    var lastBarHigh     = null;    // tracking max price od otevreni svicky
    var lastBarLow      = null;    // tracking min price od otevreni svicky
    var lastBarClose    = null;
    var indicatorSeries = {};
    var container       = null;
    var initAttempts    = 0;

    // =================================================================
    // GLOBALNI debug logger
    // =================================================================
    function writeDebug(type, msg) {
        var ts   = new Date().toLocaleTimeString('cs-CZ');
        var line = '[' + ts + '] [' + type + '] ' + msg + '\n';
        if (type === 'ERR')  { console.error('[LWC] ' + msg); }
        else if (type === 'WARN') { console.warn('[LWC] ' + msg); }
        else                 { console.log('[LWC] ' + msg); }
        var area = document.getElementById('debug-log-area');
        if (area) { area.value = line + area.value; }
    }
    window.lwcDebug = writeDebug;

    // =================================================================
    // Placeholder
    // =================================================================
    function showPlaceholder(msg) {
        var c = document.getElementById('lwc-container');
        if (!c) { return; }
        c.innerHTML =
            '<div style="color:#667eea;font-size:14px;padding:20px;' +
            'font-family:monospace;background:#1e1e2e;height:100%;box-sizing:border-box;' +
            'display:flex;align-items:center;justify-content:center;">' +
            '\u23f3 ' + msg + '</div>';
    }

    // =================================================================
    // 1. initChart
    // =================================================================
    function initChart() {
        initAttempts++;
        container = document.getElementById('lwc-container');

        if (!container) {
            writeDebug('INIT', 'Pokus ' + initAttempts + ': #lwc-container nenalezen, cekam...');
            setTimeout(initChart, 200);
            return;
        }

        var w = container.offsetWidth;
        if (w === 0) {
            writeDebug('INIT', 'Pokus ' + initAttempts + ': sirka=0, cekam...');
            showPlaceholder('Cekam na vykreslovani... (pokus ' + initAttempts + ')');
            setTimeout(initChart, 200);
            return;
        }

        if (typeof LightweightCharts === 'undefined') {
            writeDebug('ERR', 'LightweightCharts NENI NACTENA!');
            showPlaceholder('CHYBA: Lightweight Charts CDN se nenactlo!');
            return;
        }

        writeDebug('INIT', 'Vytvarim graf ' + w + 'x' + CHART_HEIGHT + 'px');
        showPlaceholder('Inicializuji graf...');

        try {
            container.innerHTML = '';

            chart = LightweightCharts.createChart(container, {
                width:  w,
                height: CHART_HEIGHT,
                layout: { background: { color: CHART_BG }, textColor: TEXT_COLOR },
                grid:   { vertLines: { color: GRID_COLOR }, horzLines: { color: GRID_COLOR } },
                crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
                rightPriceScale: { borderColor: GRID_COLOR },
                timeScale: { borderColor: GRID_COLOR, timeVisible: true, secondsVisible: false }
            });

            candleSeries = chart.addCandlestickSeries({
                upColor: UP_COLOR, downColor: DOWN_COLOR,
                borderVisible: false,
                wickUpColor: UP_COLOR, wickDownColor: DOWN_COLOR
            });

            volumeSeries = chart.addHistogramSeries({
                color: '#667eea', priceFormat: { type: 'volume' },
                priceScaleId: 'volume', scaleMargins: { top: 0.85, bottom: 0 }
            });

            window.addEventListener('resize', function () {
                if (chart && container) {
                    chart.resize(container.offsetWidth, CHART_HEIGHT);
                }
            });

            writeDebug('INIT', 'Graf HOTOV. Klikni Load Chart (IB data) nebo Test Chart (fake).');

        } catch (e) {
            writeDebug('ERR', 'createChart selhal: ' + e.message);
            showPlaceholder('CHYBA: ' + e.message);
        }
    }

    // =================================================================
    // 2. loadData - vola se z clientside_callback
    // =================================================================
    function loadData(storeData) {
        writeDebug('DATA', 'loadData() zavolano. symbol=' +
            (storeData && storeData.symbol) +
            ' | baru=' + (storeData && storeData.bars ? storeData.bars.length : 'N/A'));

        if (!chart || !candleSeries) {
            writeDebug('DATA', 'Graf jeste neni ready, retry za 300ms...');
            setTimeout(function () { loadData(storeData); }, 300);
            return;
        }

        var bars   = storeData.bars   || [];
        var symbol = storeData.symbol || '?';

        if (bars.length === 0) {
            writeDebug('WARN', 'ZADNE BARY pro ' + symbol + ' - trh zavreny nebo IB timeout');
            showPlaceholder('Zadna data pro ' + symbol);
            return;
        }

        bars.sort(function (a, b) { return a.time - b.time; });

        var b0 = bars[0];
        writeDebug('DATA', 'Prvni bar: time=' + b0.time + ' (' + typeof b0.time + ')' +
            ' open=' + b0.open + ' high=' + b0.high +
            ' low=' + b0.low + ' close=' + b0.close);
        writeDebug('DATA', 'Posledni: time=' + bars[bars.length-1].time +
            ' close=' + bars[bars.length-1].close);

        if (typeof b0.time !== 'number') {
            writeDebug('ERR', 'PROBLEM: time je ' + typeof b0.time + ' misto number!');
        }

        try {
            candleSeries.setData(bars.map(function (b) {
                return { time: b.time, open: b.open,
                         high: b.high, low: b.low, close: b.close };
            }));
            volumeSeries.setData(bars.map(function (b) {
                return {
                    time:  b.time,
                    value: b.volume || 0,
                    color: b.close >= b.open ? UP_COLOR + '88' : DOWN_COLOR + '88'
                };
            }));

            // Uloz posledni svicku pro tick update
            var last      = bars[bars.length - 1];
            lastBarTime   = last.time;
            lastBarOpen   = last.open;
            lastBarHigh   = last.high;   // tracking max od otevreni
            lastBarLow    = last.low;    // tracking min od otevreni
            lastBarClose  = last.close;
            currentSymbol = symbol;

            chart.timeScale().fitContent();
            writeDebug('DATA', 'USPECH: Vykresleno ' + bars.length + ' svicek pro ' + symbol);

            // Tick polling - spusti jen kdyz je uzivatel zapnul
            if (tickEnabled) {
                startTickPolling(symbol);
            } else {
                // Zastav predchozi polling kdyz se nacita nova data
                if (tickTimer) { clearInterval(tickTimer); tickTimer = null; }
                writeDebug('TICK', 'Tick je OFF - k zapnuti pouzij tlacitko TICK');
            }

        } catch (e) {
            writeDebug('ERR', 'setData selhal: ' + e.message);
        }
    }

    // =================================================================
    // 3. testChart - 100 fake svicek
    // =================================================================
    function testChart() {
        writeDebug('TEST', '=== TEST CHART START - 100 fake svicek ===');
        var bars  = [];
        var now   = Math.floor(Date.now() / 1000);
        var price = 200;
        for (var i = 99; i >= 0; i--) {
            var t     = now - i * 300;
            var change = (Math.random() - 0.47) * 3;
            var open  = price;
            price     = Math.max(10, price + change);
            var close = price;
            var high  = Math.max(open, close) + Math.random() * 1.5;
            var low   = Math.min(open, close) - Math.random() * 1.5;
            bars.push({
                time: t, open: open, high: high,
                low: low, close: close,
                volume: Math.floor(Math.random() * 500000 + 50000)
            });
        }
        loadData({ symbol: 'TEST-DATA', timeframe: '5 mins (FAKE)', bars: bars });
    }

    // =================================================================
    // 4. Tick polling - Live update posledni svicky
    //
    // POZOR: Na paper/demo accountu vraci IB data s ~15min zpozdenim!
    // Tick ON/OFF ridi uzivatel - defaultne OFF.
    // =================================================================
    function startTickPolling(symbol) {
        if (tickTimer) { clearInterval(tickTimer); tickTimer = null; }
        if (!tickEnabled) {
            return;
        }
        writeDebug('TICK', 'Polling pro ' + symbol + ' kazdych ' + TICK_POLL_MS + 'ms (15min delay na demo!)');
        tickTimer = setInterval(function () { pollTick(symbol); }, TICK_POLL_MS);
    }

    function pollTick(symbol) {
        if (!tickEnabled || !symbol || !candleSeries || lastBarTime === null) { return; }
        fetch('/api/tick/' + encodeURIComponent(symbol))
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (!data || !data.price || data.price <= 0) { return; }
                var price = parseFloat(data.price);

                // Spravne sledovani HIGH a LOW od otevreni svicky
                lastBarHigh  = Math.max(lastBarHigh, price);
                lastBarLow   = Math.min(lastBarLow, price);
                lastBarClose = price;

                candleSeries.update({
                    time:  lastBarTime,
                    open:  lastBarOpen,
                    high:  lastBarHigh,
                    low:   lastBarLow,
                    close: lastBarClose
                });
            })
            .catch(function () {});
    }

    // =================================================================
    // 5. setTickEnabled - vola se z tlacitka v UI
    // =================================================================
    function setTickEnabled(enabled) {
        tickEnabled = !!enabled;
        if (tickEnabled) {
            if (currentSymbol) {
                startTickPolling(currentSymbol);
            } else {
                writeDebug('TICK', 'Tick ON - nejdrive nacti graf (Load Chart)');
            }
        } else {
            if (tickTimer) { clearInterval(tickTimer); tickTimer = null; }
        }
    }

    // =================================================================
    // 6. Indicator API
    // =================================================================
    function addIndicator(name, type, data, options) {
        if (!chart) { writeDebug('WARN', 'Graf neni ready pro indikator: ' + name); return; }
        if (indicatorSeries[name]) { chart.removeSeries(indicatorSeries[name]); }
        var series;
        if (type === 'histogram') { series = chart.addHistogramSeries(options || {}); }
        else if (type === 'area') { series = chart.addAreaSeries(options || {}); }
        else                      { series = chart.addLineSeries(options || {}); }
        series.setData(data);
        indicatorSeries[name] = series;
        writeDebug('IND', 'Pridano: ' + name + ' (' + type + ')');
    }

    function removeIndicator(name) {
        if (indicatorSeries[name] && chart) {
            chart.removeSeries(indicatorSeries[name]);
            delete indicatorSeries[name];
            writeDebug('IND', 'Odebrano: ' + name);
        }
    }

    // Public API
    window.lwcManager = {
        loadData:        loadData,
        testChart:       testChart,
        setTickEnabled:  setTickEnabled,
        addIndicator:    addIndicator,
        removeIndicator: removeIndicator
    };

    writeDebug('INIT', '=== LWC Manager ' + VERSION + ' nacteny, spoustim initChart ===');
    setTimeout(initChart, 300);

}());

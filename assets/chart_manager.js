/**
 * IB Trading Platform - Lightweight Charts Manager v2.0.4
 * =========================================================
 * v2.0.4 - In-page debug panel support, testChart() for fake data testing
 * v2.0.3 - Visible placeholder, heavy console.log
 * v2.0.2 - offsetWidth fix, retry until width>0, chart.resize()
 */
(function () {
    'use strict';

    var VERSION         = 'v2.0.4';
    var TICK_POLL_MS    = 1000;
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
    var currentSymbol   = null;
    var lastBarTime     = null;
    var lastBarOpen     = null;
    var lastBarClose    = null;
    var indicatorSeries = {};
    var container       = null;
    var initAttempts    = 0;

    // =================================================================
    // Debug logger - pise do konzole I do #debug-log-area na strance
    // =================================================================
    function writeDebug(type, msg) {
        var ts   = new Date().toLocaleTimeString('cs-CZ');
        var line = '[' + ts + '] [' + type + '] ' + msg + '\n';
        // 1. Browser console
        if (type === 'ERR') {
            console.error('[LWC] ' + msg);
        } else if (type === 'WARN') {
            console.warn('[LWC] ' + msg);
        } else {
            console.log('[LWC] ' + msg);
        }
        // 2. In-page debug panel (ak existuje)
        var area = document.getElementById('debug-log-area');
        if (area) {
            area.value = line + area.value;  // nejnovejsi nahore
        }
    }

    // =================================================================
    // Zobraz placeholder v kontejneru grafu
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
            writeDebug('INIT', 'Pokus ' + initAttempts + ': div #lwc-container nenalezen, cekam...');
            setTimeout(initChart, 200);
            return;
        }

        var w = container.offsetWidth;
        if (w === 0) {
            writeDebug('INIT', 'Pokus ' + initAttempts + ': div existuje ale sirka=0, cekam...');
            showPlaceholder('Cekam na vykreslovani... (pokus ' + initAttempts + ')');
            setTimeout(initChart, 200);
            return;
        }

        if (typeof LightweightCharts === 'undefined') {
            writeDebug('ERR', 'LightweightCharts knihovna NENI NACTENA! Zkontroluj CDN v app.py');
            showPlaceholder('CHYBA: Lightweight Charts CDN se nenactlo!');
            return;
        }

        writeDebug('INIT', 'Zacinam vytvorit graf. Sirka=' + w + 'px, Vyska=' + CHART_HEIGHT + 'px');
        showPlaceholder('Inicializuji graf...');

        try {
            container.innerHTML = '';

            chart = LightweightCharts.createChart(container, {
                width:  w,
                height: CHART_HEIGHT,
                layout: {
                    background: { color: CHART_BG },
                    textColor:  TEXT_COLOR
                },
                grid: {
                    vertLines: { color: GRID_COLOR },
                    horzLines: { color: GRID_COLOR }
                },
                crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
                rightPriceScale: { borderColor: GRID_COLOR },
                timeScale: {
                    borderColor:    GRID_COLOR,
                    timeVisible:    true,
                    secondsVisible: false
                }
            });

            candleSeries = chart.addCandlestickSeries({
                upColor:       UP_COLOR,
                downColor:     DOWN_COLOR,
                borderVisible: false,
                wickUpColor:   UP_COLOR,
                wickDownColor: DOWN_COLOR
            });

            volumeSeries = chart.addHistogramSeries({
                color:        '#667eea',
                priceFormat:  { type: 'volume' },
                priceScaleId: 'volume',
                scaleMargins: { top: 0.85, bottom: 0 }
            });

            window.addEventListener('resize', function () {
                if (chart && container) {
                    chart.resize(container.offsetWidth, CHART_HEIGHT);
                    writeDebug('RESIZE', 'Graf zmenen na ' + container.offsetWidth + 'px');
                }
            });

            writeDebug('INIT', 'HOTOVO! Graf inicializovan. Klikni Load Chart nebo Test Chart.');

        } catch (e) {
            writeDebug('ERR', 'createChart selhal: ' + e.message);
            showPlaceholder('CHYBA pri tvorbe grafu: ' + e.message);
        }
    }

    // =================================================================
    // 2. loadData
    // =================================================================
    function loadData(storeData) {
        writeDebug('DATA', 'loadData() zavolano. symbol=' + (storeData && storeData.symbol) +
                   ' baru=' + (storeData && storeData.bars ? storeData.bars.length : 0));

        if (!chart || !candleSeries) {
            writeDebug('DATA', 'Graf jeste neni ready, zkusim znovu za 300ms...');
            setTimeout(function () { loadData(storeData); }, 300);
            return;
        }

        var bars   = storeData.bars   || [];
        var symbol = storeData.symbol || '?';

        if (bars.length === 0) {
            writeDebug('WARN', 'Zadne bary pro ' + symbol + ' - trh zavreny nebo IB timeout');
            showPlaceholder('Zadna data pro ' + symbol + '. Trh je mozna zavreny.');
            return;
        }

        bars.sort(function (a, b) { return a.time - b.time; });

        writeDebug('DATA', 'Prvni bar: time=' + bars[0].time +
                   ' open=' + bars[0].open + ' close=' + bars[0].close);
        writeDebug('DATA', 'Posledni: time=' + bars[bars.length-1].time +
                   ' close=' + bars[bars.length-1].close);

        try {
            candleSeries.setData(bars.map(function (b) {
                return { time: b.time, open: b.open,
                         high: b.high, low: b.low, close: b.close };
            }));
            volumeSeries.setData(bars.map(function (b) {
                return {
                    time:  b.time,
                    value: b.volume,
                    color: b.close >= b.open ? UP_COLOR + '88' : DOWN_COLOR + '88'
                };
            }));

            var last     = bars[bars.length - 1];
            lastBarTime  = last.time;
            lastBarOpen  = last.open;
            lastBarClose = last.close;
            currentSymbol = symbol;

            chart.timeScale().fitContent();
            writeDebug('DATA', 'OK! Vykresleno ' + bars.length + ' svicek pro ' + symbol);
            startTickPolling(symbol);

        } catch (e) {
            writeDebug('ERR', 'setData selhal: ' + e.message);
        }
    }

    // =================================================================
    // 3. testChart - 100 vymyslenych svicek (test LWC bez IB)
    // Pokud toto funguje -> LWC OK, problem je v Python->Dash->JS pipeline
    // Pokud toto NEFUNGUJE -> problem je v LWC nebo kontejneru
    // =================================================================
    function testChart() {
        writeDebug('TEST', '--- Spoustim TEST CHART s 100 vymyslenymi svickami ---');
        var bars  = [];
        var now   = Math.floor(Date.now() / 1000);
        var price = 200;
        for (var i = 99; i >= 0; i--) {
            var t      = now - i * 300;           // 5-minutove svicky
            var change = (Math.random() - 0.47) * 3;
            var open   = price;
            price      = Math.max(10, price + change);
            var close  = price;
            var high   = Math.max(open, close) + Math.random() * 1.5;
            var low    = Math.min(open, close) - Math.random() * 1.5;
            bars.push({
                time: t, open: open, high: high,
                low: low, close: close,
                volume: Math.floor(Math.random() * 500000 + 50000)
            });
        }
        loadData({ symbol: 'TEST-DATA', timeframe: '5 mins (FAKE)', bars: bars });
    }

    // =================================================================
    // 4. Live tick polling
    // =================================================================
    function startTickPolling(symbol) {
        if (tickTimer) { clearInterval(tickTimer); }
        writeDebug('TICK', 'Zacina polling pro ' + symbol + ' kazdych ' + TICK_POLL_MS + 'ms');
        tickTimer = setInterval(function () { pollTick(symbol); }, TICK_POLL_MS);
    }

    function pollTick(symbol) {
        if (!symbol || !candleSeries || lastBarTime === null) { return; }
        fetch('/api/tick/' + encodeURIComponent(symbol))
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (!data || !data.price || data.price <= 0) { return; }
                candleSeries.update({
                    time:  lastBarTime,
                    open:  lastBarOpen,
                    high:  Math.max(lastBarOpen, data.price),
                    low:   Math.min(lastBarOpen, data.price),
                    close: data.price
                });
                lastBarClose = data.price;
            })
            .catch(function () {});
    }

    // =================================================================
    // 5 + 6. Indicator API
    // =================================================================
    function addIndicator(name, type, data, options) {
        if (!chart) { writeDebug('WARN', 'Graf neni ready pro indikator: ' + name); return; }
        if (indicatorSeries[name]) { chart.removeSeries(indicatorSeries[name]); }
        var series;
        if (type === 'histogram') {
            series = chart.addHistogramSeries(options || {});
        } else if (type === 'area') {
            series = chart.addAreaSeries(options || {});
        } else {
            series = chart.addLineSeries(options || {});
        }
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
        addIndicator:    addIndicator,
        removeIndicator: removeIndicator
    };

    writeDebug('INIT', 'Script nacteny ' + VERSION + ', spoustim initChart smycku...');
    setTimeout(initChart, 300);

}());

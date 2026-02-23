/**
 * IB Trading Platform - Lightweight Charts Manager v2.0.3
 * =========================================================
 * Changelog:
 *  v2.0.3 - Added visible placeholder, more console.log for debugging
 *  v2.0.2 - offsetWidth fix, retry until width>0, chart.resize()
 *  v2.0.1 - qualifyContracts, LWC v4 pin
 *  v2.0.0 - Initial LWC integration
 */
(function () {
    'use strict';

    var VERSION          = 'v2.0.3';
    var TICK_POLL_MS     = 1000;
    var CHART_BG         = '#1e1e2e';
    var GRID_COLOR       = '#3d3d4a';
    var TEXT_COLOR       = '#d1d4dc';
    var UP_COLOR         = '#26a69a';
    var DOWN_COLOR       = '#ef5350';
    var CHART_HEIGHT     = 500;

    var chart            = null;
    var candleSeries     = null;
    var volumeSeries     = null;
    var tickTimer        = null;
    var currentSymbol    = null;
    var lastBarTime      = null;
    var lastBarOpen      = null;
    var lastBarClose     = null;
    var indicatorSeries  = {};
    var container        = null;
    var initAttempts     = 0;

    // =================================================================
    // Pomocna funkce - vypise zpravu do konzole s prefixem [LWC]
    // Otevri DevTools (F12) -> Console a uvidis vsechny kroky
    // =================================================================
    function log(msg) {
        console.log('[LWC ' + VERSION + '] ' + msg);
    }
    function warn(msg) {
        console.warn('[LWC ' + VERSION + '] ' + msg);
    }
    function err(msg) {
        console.error('[LWC ' + VERSION + '] ' + msg);
    }

    // =================================================================
    // Zobraz placeholder text v kontejneru
    // (dokazuje ze kontejner existuje a JS bezi)
    // =================================================================
    function showPlaceholder(msg) {
        var c = document.getElementById('lwc-container');
        if (!c) { return; }
        c.innerHTML = '<div style="color:#667eea;font-size:14px;padding:20px;' +
            'font-family:monospace;background:#1e1e2e;height:100%;' +
            'display:flex;align-items:center;justify-content:center;">' +
            '\u23f3 ' + msg + '</div>';
    }

    // =================================================================
    // 1. initChart - vola se opakovane dokud kontejner nema sirku > 0
    // =================================================================
    function initChart() {
        initAttempts++;
        container = document.getElementById('lwc-container');

        if (!container) {
            log('Attempt ' + initAttempts + ': container not in DOM yet, retrying...');
            showPlaceholder('Cekam na DOM... (' + initAttempts + ')');
            setTimeout(initChart, 200);
            return;
        }

        var w = container.offsetWidth;
        if (w === 0) {
            log('Attempt ' + initAttempts + ': container exists but width=0, retrying...');
            showPlaceholder('Cekam na vykreslovani... (' + initAttempts + ')');
            setTimeout(initChart, 200);
            return;
        }

        // Zkontroluj ze LWC knihovna je nactena
        if (typeof LightweightCharts === 'undefined') {
            err('LightweightCharts library NOT LOADED! Check CDN in app.py index_string');
            showPlaceholder('CHYBA: Lightweight Charts knihovna se nenactla!');
            return;
        }

        log('Initializing chart. Container width=' + w + 'px, height=' + CHART_HEIGHT + 'px');
        showPlaceholder('Inicializuji graf...');

        try {
            // Vycisti kontejner pred vytvorenim grafu
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
                crosshair: {
                    mode: LightweightCharts.CrosshairMode.Normal
                },
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
                    log('Chart resized to ' + container.offsetWidth + 'px');
                }
            });

            log('Chart ready! Waiting for data (click Load Chart button)...');

        } catch (e) {
            err('createChart failed: ' + e.message);
            showPlaceholder('CHYBA pri vytvareni grafu: ' + e.message);
        }
    }

    // =================================================================
    // 2. loadData - vola se z Dash clientside_callback
    // =================================================================
    function loadData(storeData) {
        log('loadData() called. symbol=' + (storeData && storeData.symbol));

        if (!chart || !candleSeries) {
            warn('Chart not ready yet, retrying loadData in 300ms...');
            setTimeout(function () { loadData(storeData); }, 300);
            return;
        }

        var bars   = storeData.bars   || [];
        var symbol = storeData.symbol || '?';

        if (bars.length === 0) {
            warn('No bars received for ' + symbol + ' - trh mozna zavreny?');
            showPlaceholder('Zadna data pro ' + symbol + ' (trh zavreny nebo IB timeout)');
            return;
        }

        log('Loading ' + bars.length + ' bars for ' + symbol + ' (' + storeData.timeframe + ')');

        // Seradime bary vzestupne podle casu (pojistka)
        bars.sort(function (a, b) { return a.time - b.time; });

        // Prvni a posledni bar pro debug
        log('First bar: time=' + bars[0].time + ' open=' + bars[0].open + ' close=' + bars[0].close);
        log('Last bar:  time=' + bars[bars.length-1].time + ' close=' + bars[bars.length-1].close);

        try {
            candleSeries.setData(bars.map(function (b) {
                return { time: b.time, open: b.open, high: b.high,
                         low: b.low, close: b.close };
            }));

            volumeSeries.setData(bars.map(function (b) {
                return {
                    time:  b.time,
                    value: b.volume,
                    color: b.close >= b.open
                        ? UP_COLOR + '88'
                        : DOWN_COLOR + '88'
                };
            }));

            var last    = bars[bars.length - 1];
            lastBarTime  = last.time;
            lastBarOpen  = last.open;
            lastBarClose = last.close;
            currentSymbol = symbol;

            chart.timeScale().fitContent();

            log('SUCCESS: Chart rendered ' + bars.length + ' bars for ' + symbol);
            startTickPolling(symbol);

        } catch (e) {
            err('setData failed: ' + e.message);
        }
    }

    // =================================================================
    // 3. Live tick polling
    // =================================================================
    function startTickPolling(symbol) {
        if (tickTimer) {
            clearInterval(tickTimer);
            log('Stopped previous tick polling');
        }
        log('Starting tick polling for ' + symbol + ' every ' + TICK_POLL_MS + 'ms');
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
            .catch(function () { /* IB not connected - ignore */ });
    }

    // =================================================================
    // 4 + 5. Indicator API
    // =================================================================
    function addIndicator(name, type, data, options) {
        if (!chart) { warn('Chart not ready for indicator: ' + name); return; }
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
        log('Indicator added: ' + name + ' (' + type + ')');
    }

    function removeIndicator(name) {
        if (indicatorSeries[name] && chart) {
            chart.removeSeries(indicatorSeries[name]);
            delete indicatorSeries[name];
            log('Indicator removed: ' + name);
        }
    }

    // Public API
    window.lwcManager = {
        loadData:        loadData,
        addIndicator:    addIndicator,
        removeIndicator: removeIndicator
    };

    log('Script loaded ' + VERSION + ', starting initChart loop...');
    setTimeout(initChart, 300);

}());

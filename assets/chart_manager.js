/**
 * IB Trading Platform - Lightweight Charts Manager v2.2.0
 * =========================================================
 * v2.2.0:
 *   - setIndicators(data): prijima JSON z /api/indicators
 *   - SMA + EMA: LineSeries overlay na hlavnim grafu
 *   - RSI: samostatny sub-panel (dynamicky div pod grafem)
 *   - MACD: samostatny sub-panel (histogram + MACD + Signal)
 *   - clearSubCharts(): cisty cleanup vsech sub-panelu
 *   - Sync timeScale mezi hlavnim grafem a sub-charty
 */
(function () {
    'use strict';

    var VERSION         = 'v2.2.0';
    var TICK_POLL_MS    = 5000;
    var CHART_BG        = '#1e1e2e';
    var GRID_COLOR      = '#3d3d4a';
    var TEXT_COLOR      = '#d1d4dc';
    var UP_COLOR        = '#26a69a';
    var DOWN_COLOR      = '#ef5350';
    var CHART_HEIGHT    = 500;
    var RSI_HEIGHT      = 160;
    var MACD_HEIGHT     = 160;

    var chart           = null;
    var candleSeries    = null;
    var volumeSeries    = null;
    var tickTimer       = null;
    var tickEnabled     = false;
    var currentSymbol   = null;
    var lastBarTime     = null;
    var lastBarOpen     = null;
    var lastBarHigh     = null;
    var lastBarLow      = null;
    var lastBarClose    = null;
    var indicatorSeries = {};
    var subCharts       = {};     // { rsi: LWC instance, macd: LWC instance }
    var container       = null;
    var initAttempts    = 0;
    var syncingRange    = false;  // zabrani rekurzi pri sync time scale

    // =================================================================
    // Debug logger
    // =================================================================
    function writeDebug(type, msg) {
        var ts   = new Date().toLocaleTimeString('cs-CZ');
        var line = '[' + ts + '] [' + type + '] ' + msg + '\n';
        if (type === 'ERR')       { console.error('[LWC] ' + msg); }
        else if (type === 'WARN') { console.warn('[LWC] ' + msg); }
        else                      { console.log('[LWC] ' + msg); }
        var area = document.getElementById('debug-log-area');
        if (area) { area.value = line + area.value; }
    }
    window.lwcDebug = writeDebug;

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
            setTimeout(initChart, 200);
            return;
        }
        var w = container.offsetWidth;
        if (w === 0) {
            showPlaceholder('Cekam na vykreslovani... (' + initAttempts + ')');
            setTimeout(initChart, 200);
            return;
        }
        if (typeof LightweightCharts === 'undefined') {
            writeDebug('ERR', 'LightweightCharts NENI NACTENA!');
            showPlaceholder('CHYBA: CDN se nenactlo!');
            return;
        }

        writeDebug('INIT', 'Vytvarim graf ' + w + 'x' + CHART_HEIGHT + 'px ' + VERSION);
        showPlaceholder('Inicializuji graf...');
        try {
            container.innerHTML = '';
            chart = LightweightCharts.createChart(container, {
                width:  w, height: CHART_HEIGHT,
                layout: { background: { color: CHART_BG }, textColor: TEXT_COLOR },
                grid:   { vertLines: { color: GRID_COLOR }, horzLines: { color: GRID_COLOR } },
                crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
                rightPriceScale: { borderColor: GRID_COLOR },
                timeScale: { borderColor: GRID_COLOR, timeVisible: true, secondsVisible: false }
            });
            candleSeries = chart.addCandlestickSeries({
                upColor: UP_COLOR, downColor: DOWN_COLOR, borderVisible: false,
                wickUpColor: UP_COLOR, wickDownColor: DOWN_COLOR
            });
            volumeSeries = chart.addHistogramSeries({
                color: '#667eea', priceFormat: { type: 'volume' },
                priceScaleId: 'volume', scaleMargins: { top: 0.85, bottom: 0 }
            });
            window.addEventListener('resize', onResize);
            writeDebug('INIT', 'Graf HOTOV ' + VERSION + '. Klikni Load Chart.');
        } catch (e) {
            writeDebug('ERR', 'createChart selhal: ' + e.message);
            showPlaceholder('CHYBA: ' + e.message);
        }
    }

    function onResize() {
        if (chart && container) chart.resize(container.offsetWidth, CHART_HEIGHT);
        Object.keys(subCharts).forEach(function(k) {
            var sc = subCharts[k];
            var el = document.getElementById('lwc-' + k + '-container');
            if (sc && el) sc.resize(el.offsetWidth, k === 'rsi' ? RSI_HEIGHT : MACD_HEIGHT);
        });
    }

    // =================================================================
    // 2. loadData
    // =================================================================
    function loadData(storeData) {
        writeDebug('DATA', 'loadData() zavolano. symbol=' +
            (storeData && storeData.symbol) +
            ' | baru=' + (storeData && storeData.bars ? storeData.bars.length : 'N/A'));

        if (!chart || !candleSeries) {
            setTimeout(function () { loadData(storeData); }, 300);
            return;
        }

        var bars   = storeData.bars   || [];
        var symbol = storeData.symbol || '?';

        if (bars.length === 0) {
            writeDebug('WARN', 'ZADNE BARY pro ' + symbol);
            showPlaceholder('Zadna data pro ' + symbol);
            return;
        }

        bars.sort(function (a, b) { return a.time - b.time; });

        var b0 = bars[0];
        writeDebug('DATA', 'Prvni bar: time=' + b0.time + ' open=' + b0.open +
            ' close=' + b0.close + ' | Posledni: close=' + bars[bars.length-1].close);

        if (typeof b0.time !== 'number') {
            writeDebug('ERR', 'PROBLEM: time je ' + typeof b0.time + ' misto number!');
        }

        try {
            candleSeries.setData(bars.map(function (b) {
                return { time: b.time, open: b.open, high: b.high, low: b.low, close: b.close };
            }));
            volumeSeries.setData(bars.map(function (b) {
                return {
                    time:  b.time, value: b.volume || 0,
                    color: b.close >= b.open ? UP_COLOR + '88' : DOWN_COLOR + '88'
                };
            }));

            var last    = bars[bars.length - 1];
            lastBarTime  = last.time;
            lastBarOpen  = last.open;
            lastBarHigh  = last.high;
            lastBarLow   = last.low;
            lastBarClose = last.close;
            currentSymbol = symbol;

            chart.timeScale().fitContent();
            writeDebug('DATA', 'USPECH: Vykresleno ' + bars.length + ' svicek pro ' + symbol);

            if (tickEnabled) {
                startTickPolling(symbol);
            } else {
                if (tickTimer) { clearInterval(tickTimer); tickTimer = null; }
            }
        } catch (e) {
            writeDebug('ERR', 'setData selhal: ' + e.message);
        }
    }

    // =================================================================
    // 3. testChart
    // =================================================================
    function testChart() {
        writeDebug('TEST', '=== TEST CHART - 100 fake svicek ===');
        var bars = [], now = Math.floor(Date.now() / 1000), price = 200;
        for (var i = 99; i >= 0; i--) {
            var t = now - i * 300;
            var change = (Math.random() - 0.47) * 3;
            var open = price;
            price = Math.max(10, price + change);
            var high = Math.max(open, price) + Math.random() * 1.5;
            var low  = Math.min(open, price) - Math.random() * 1.5;
            bars.push({ time: t, open: open, high: high, low: low, close: price,
                        volume: Math.floor(Math.random() * 500000 + 50000) });
        }
        loadData({ symbol: 'TEST-DATA', timeframe: '5 mins (FAKE)', bars: bars });
    }

    // =================================================================
    // 4. Tick polling
    // =================================================================
    function startTickPolling(symbol) {
        if (tickTimer) { clearInterval(tickTimer); tickTimer = null; }
        if (!tickEnabled) { return; }
        writeDebug('TICK', 'Polling pro ' + symbol + ' kazdych ' + TICK_POLL_MS + 'ms');
        tickTimer = setInterval(function () { pollTick(symbol); }, TICK_POLL_MS);
    }

    function pollTick(symbol) {
        if (!tickEnabled || !symbol || !candleSeries || lastBarTime === null) { return; }
        fetch('/api/tick/' + encodeURIComponent(symbol))
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (!data || data.price === undefined) return;
                var price = parseFloat(data.price);
                if (price <= 0) return;
                var prevClose = lastBarClose || price;
                var changed   = Math.abs(price - prevClose) > 0.001;
                lastBarHigh  = Math.max(lastBarHigh, price);
                lastBarLow   = Math.min(lastBarLow, price);
                lastBarClose = price;
                writeDebug('TICK',
                    symbol + ' \u2192 ' + price.toFixed(2)
                    + (changed ? ' \u2bc8 ZMENA z ' + prevClose.toFixed(2)
                        + ' (\u0394' + (price - prevClose > 0 ? '+' : '')
                        + (price - prevClose).toFixed(2) + ')' : ' \u2014 stejne')
                    + ' | H=' + lastBarHigh.toFixed(2) + ' L=' + lastBarLow.toFixed(2));
                candleSeries.update({
                    time: lastBarTime, open: lastBarOpen,
                    high: lastBarHigh, low: lastBarLow, close: lastBarClose
                });
            })
            .catch(function (e) { writeDebug('TICK', 'FETCH ERROR: ' + e); });
    }

    // =================================================================
    // 5. setTickEnabled
    // =================================================================
    function setTickEnabled(enabled) {
        tickEnabled = !!enabled;
        if (tickEnabled) {
            if (currentSymbol) startTickPolling(currentSymbol);
            else writeDebug('TICK', 'Tick ON - nejdrive nacti graf');
        } else {
            if (tickTimer) { clearInterval(tickTimer); tickTimer = null; }
        }
    }

    // =================================================================
    // 6. Sub-chart helpers
    // =================================================================

    /**
     * Vytvori nebo vrati existujici div pro sub-chart.
     * Vlozi ho IHNED za #lwc-container nebo za posledni sub-chart.
     */
    function getOrCreateSubContainer(id, height, label) {
        var existing = document.getElementById(id);
        if (existing) return existing;

        // Najdi posledni existujici sub-container nebo hlavni container
        var anchor = document.getElementById('lwc-macd-container') ||
                     document.getElementById('lwc-rsi-container')  ||
                     document.getElementById('lwc-container');
        if (!anchor) { writeDebug('ERR', 'Nelze najit anchor pro ' + id); return null; }

        var wrapper = document.createElement('div');
        wrapper.style.cssText = 'position:relative;';

        var titleBar = document.createElement('div');
        titleBar.style.cssText =
            'background:#1a1a2e;color:#888;font-size:11px;padding:2px 8px;' +
            'border-top:1px solid #3d3d4a;font-family:monospace;';
        titleBar.textContent = label || id;

        var div = document.createElement('div');
        div.id             = id;
        div.style.cssText  = 'width:100%;height:' + height + 'px;background:' + CHART_BG + ';';

        wrapper.appendChild(titleBar);
        wrapper.appendChild(div);
        anchor.parentNode.insertBefore(wrapper, anchor.nextSibling);
        return div;
    }

    function removeSubContainer(id) {
        var el = document.getElementById(id);
        if (el && el.parentNode) {
            var wrapper = el.parentNode;
            // Wrapper je div bez id, odstranime cely wrapper
            if (wrapper && wrapper.parentNode && !wrapper.id) {
                wrapper.parentNode.removeChild(wrapper);
            } else if (el.parentNode) {
                el.parentNode.removeChild(el);
            }
        }
    }

    function clearSubCharts() {
        if (subCharts.rsi)  { subCharts.rsi.remove();  delete subCharts.rsi;  }
        if (subCharts.macd) { subCharts.macd.remove(); delete subCharts.macd; }
        removeSubContainer('lwc-rsi-container');
        removeSubContainer('lwc-macd-container');
    }

    function syncTimeScales(sourceChart, targetCharts) {
        sourceChart.timeScale().subscribeVisibleTimeRangeChange(function(range) {
            if (syncingRange || !range) return;
            syncingRange = true;
            targetCharts.forEach(function(tc) {
                try { tc.timeScale().setVisibleRange(range); } catch(e) {}
            });
            syncingRange = false;
        });
    }

    // =================================================================
    // 7. RSI sub-chart
    // =================================================================
    function createRsiChart(rsiData, period) {
        var el = getOrCreateSubContainer('lwc-rsi-container', RSI_HEIGHT,
            '\u2219 RSI (' + period + ')');
        if (!el) return;

        var w = el.offsetWidth || (container ? container.offsetWidth : 800);
        var rsiChart = LightweightCharts.createChart(el, {
            width:  w, height: RSI_HEIGHT,
            layout: { background: { color: CHART_BG }, textColor: TEXT_COLOR },
            grid:   { vertLines: { color: GRID_COLOR + '44' }, horzLines: { color: GRID_COLOR + '44' } },
            crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
            rightPriceScale: { borderColor: GRID_COLOR, scaleMargins: { top: 0.05, bottom: 0.05 } },
            timeScale: { borderColor: GRID_COLOR, timeVisible: true, secondsVisible: false }
        });

        // Overbought / Oversold reference lines (70 / 30)
        var ob70 = rsiChart.addLineSeries({
            color: '#ef535044', lineWidth: 1, lineStyle: 2,  // dashed
            priceScaleId: 'right', lastValueVisible: false, priceLineVisible: false
        });
        var os30 = rsiChart.addLineSeries({
            color: '#26a69a44', lineWidth: 1, lineStyle: 2,
            priceScaleId: 'right', lastValueVisible: false, priceLineVisible: false
        });

        // RSI line
        var rsiLine = rsiChart.addLineSeries({
            color: '#ce93d8', lineWidth: 2,
            priceScaleId: 'right',
            title: 'RSI' + period,
            lastValueVisible: true, priceLineVisible: false
        });

        var validData = rsiData.filter(function(d) { return d.value !== null && d.value !== undefined; });
        if (validData.length === 0) {
            writeDebug('IND', 'RSI: zadna platna data');
            return;
        }

        // Reference linky pres cely casovy rozsah
        var times = validData.map(function(d) { return d.time; });
        var tMin  = times[0], tMax = times[times.length - 1];
        ob70.setData([{ time: tMin, value: 70 }, { time: tMax, value: 70 }]);
        os30.setData([{ time: tMin, value: 30 }, { time: tMax, value: 30 }]);

        rsiLine.setData(validData.map(function(d) { return { time: d.time, value: d.value }; }));
        rsiChart.timeScale().fitContent();

        subCharts.rsi = rsiChart;

        // Sync s hlavnim grafem
        if (chart) syncTimeScales(chart, [rsiChart]);
        syncTimeScales(rsiChart, chart ? [chart] : []);

        writeDebug('IND', 'RSI sub-chart OK: ' + validData.length + ' bodu');
    }

    // =================================================================
    // 8. MACD sub-chart
    // =================================================================
    function createMacdChart(macdData) {
        var el = getOrCreateSubContainer('lwc-macd-container', MACD_HEIGHT,
            '\u2219 MACD (12 / 26 / 9)');
        if (!el) return;

        var w = el.offsetWidth || (container ? container.offsetWidth : 800);
        var macdChart = LightweightCharts.createChart(el, {
            width:  w, height: MACD_HEIGHT,
            layout: { background: { color: CHART_BG }, textColor: TEXT_COLOR },
            grid:   { vertLines: { color: GRID_COLOR + '44' }, horzLines: { color: GRID_COLOR + '44' } },
            crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
            rightPriceScale: { borderColor: GRID_COLOR, scaleMargins: { top: 0.1, bottom: 0.1 } },
            timeScale: { borderColor: GRID_COLOR, timeVisible: true, secondsVisible: false }
        });

        // Histogram
        var histSeries = macdChart.addHistogramSeries({
            priceScaleId: 'right', priceLineVisible: false,
            lastValueVisible: false
        });
        // MACD line
        var macdLine = macdChart.addLineSeries({
            color: '#42a5f5', lineWidth: 2,
            priceScaleId: 'right', title: 'MACD',
            lastValueVisible: true, priceLineVisible: false
        });
        // Signal line
        var signalLine = macdChart.addLineSeries({
            color: '#ff9800', lineWidth: 1,
            priceScaleId: 'right', title: 'Signal',
            lastValueVisible: true, priceLineVisible: false
        });

        var validMacd   = macdData.filter(function(d) { return d.macd   !== null && d.macd   !== undefined; });
        var validSignal = macdData.filter(function(d) { return d.signal !== null && d.signal !== undefined; });
        var validHist   = macdData.filter(function(d) { return d.histogram !== null && d.histogram !== undefined; });

        if (validMacd.length === 0) {
            writeDebug('IND', 'MACD: zadna platna data');
            return;
        }

        histSeries.setData(validHist.map(function(d) {
            return {
                time:  d.time,
                value: d.histogram,
                color: d.histogram >= 0 ? UP_COLOR + 'aa' : DOWN_COLOR + 'aa'
            };
        }));
        macdLine.setData(validMacd.map(function(d) {
            return { time: d.time, value: d.macd };
        }));
        signalLine.setData(validSignal.map(function(d) {
            return { time: d.time, value: d.signal };
        }));
        macdChart.timeScale().fitContent();

        subCharts.macd = macdChart;

        // Sync s hlavnim grafem a RSI
        var toSync = [macdChart];
        if (subCharts.rsi) toSync.push(subCharts.rsi);
        if (chart) syncTimeScales(chart, toSync);
        syncTimeScales(macdChart, chart ? [chart] : []);

        writeDebug('IND', 'MACD sub-chart OK: ' + validMacd.length + ' bodu');
    }

    // =================================================================
    // 9. Existing indicator overlay (SMA / EMA na hlavni chart)
    // =================================================================
    function addIndicator(name, type, data, options) {
        if (!chart) { writeDebug('WARN', 'Graf neni ready: ' + name); return; }
        if (indicatorSeries[name]) { chart.removeSeries(indicatorSeries[name]); }
        var series;
        if (type === 'histogram') series = chart.addHistogramSeries(options || {});
        else if (type === 'area') series = chart.addAreaSeries(options || {});
        else                      series = chart.addLineSeries(options || {});
        series.setData(data);
        indicatorSeries[name] = series;
        writeDebug('IND', 'Overlay: ' + name + ' (' + type + ') | ' + data.length + ' bodu');
    }

    function removeIndicator(name) {
        if (indicatorSeries[name] && chart) {
            try { chart.removeSeries(indicatorSeries[name]); } catch(e) {}
            delete indicatorSeries[name];
            writeDebug('IND', 'Odebrano overlay: ' + name);
        }
    }

    // =================================================================
    // 10. setIndicators  <-- HLAVNI VSTUPNI BOD
    //     Vola se z Dash clientside callbacku s daty z /api/indicators
    // =================================================================
    function setIndicators(data) {
        if (!chart || !candleSeries) {
            writeDebug('IND', 'setIndicators: chart neni ready, zkousim za 500ms');
            setTimeout(function() { setIndicators(data); }, 500);
            return;
        }

        writeDebug('IND', '=== setIndicators() | ok=' + data.ok +
            ' | baru=' + (data.bars || 0) +
            ' | sma=' + !!data.sma + ' ema=' + !!data.ema +
            ' rsi=' + !!data.rsi + ' macd=' + !!data.macd + ' ===');

        // -- SMA overlay --
        if (data.sma) {
            var smaData = data.sma
                .filter(function(d) { return d.value !== null && d.value !== undefined; })
                .map(function(d) { return { time: d.time, value: d.value }; });
            if (smaData.length > 0) {
                addIndicator('sma', 'line', smaData, {
                    color: '#ff9800', lineWidth: 1,
                    priceScaleId: 'right',
                    title: 'SMA' + (data.sma_period || 20),
                    lastValueVisible: true, priceLineVisible: false
                });
            }
        } else {
            removeIndicator('sma');
        }

        // -- EMA overlay --
        if (data.ema) {
            var emaData = data.ema
                .filter(function(d) { return d.value !== null && d.value !== undefined; })
                .map(function(d) { return { time: d.time, value: d.value }; });
            if (emaData.length > 0) {
                addIndicator('ema', 'line', emaData, {
                    color: '#42a5f5', lineWidth: 1,
                    priceScaleId: 'right',
                    title: 'EMA' + (data.ema_period || 20),
                    lastValueVisible: true, priceLineVisible: false
                });
            }
        } else {
            removeIndicator('ema');
        }

        // -- RSI sub-chart --
        if (subCharts.rsi)  { subCharts.rsi.remove();  delete subCharts.rsi;  }
        removeSubContainer('lwc-rsi-container');
        if (data.rsi) {
            createRsiChart(data.rsi, data.rsi_period || 14);
        }

        // -- MACD sub-chart --
        if (subCharts.macd) { subCharts.macd.remove(); delete subCharts.macd; }
        removeSubContainer('lwc-macd-container');
        if (data.macd) {
            createMacdChart(data.macd);
        }
    }

    // =================================================================
    // Public API
    // =================================================================
    window.lwcManager = {
        loadData:        loadData,
        testChart:       testChart,
        setTickEnabled:  setTickEnabled,
        addIndicator:    addIndicator,
        removeIndicator: removeIndicator,
        setIndicators:   setIndicators,  // NEW v2.2.0
        clearSubCharts:  clearSubCharts
    };

    writeDebug('INIT', '=== LWC Manager ' + VERSION + ' nacteny ===');
    setTimeout(initChart, 300);

}());

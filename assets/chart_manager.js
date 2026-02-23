/**
 * IB Trading Platform - Lightweight Charts Manager v2.0.2
 * =========================================================
 * Fixes in this version:
 *  - Use offsetWidth (not clientWidth) to get real rendered width
 *  - Retry initChart until offsetWidth > 0 (React may render after DOMContentLoaded)
 *  - Use chart.resize() in window resize handler
 *  - Retry loadData if chart not ready yet
 *
 * Responsibilities:
 *  1. initChart()       - Creates LWC chart once the container has real dimensions
 *  2. loadData()        - Loads OHLCV bars from dcc.Store into the chart
 *  3. pollTick()        - Polls /api/tick/<symbol> every 1s for live price updates
 *  4. addIndicator()    - Public API for future indicators (MA, EMA, RSI, MACD...)
 *  5. removeIndicator() - Removes a named indicator series
 */
(function () {
    'use strict';

    // --- Configuration ---
    var TICK_POLL_MS  = 1000;
    var CHART_BG      = '#1e1e2e';
    var GRID_COLOR    = '#3d3d4a';
    var TEXT_COLOR    = '#d1d4dc';
    var UP_COLOR      = '#26a69a';
    var DOWN_COLOR    = '#ef5350';
    var CHART_HEIGHT  = 500;

    // --- State ---
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

    // =================================================================
    // 1. initChart
    // Called repeatedly until the container div has real pixel dimensions.
    // Dash/React renders the DOM asynchronously, so the div may exist but
    // have zero width until layout is calculated.
    // =================================================================
    function initChart() {
        container = document.getElementById('lwc-container');

        if (!container) {
            setTimeout(initChart, 200);
            return;
        }

        // offsetWidth reflects the real rendered width.
        // If it is 0, React has not finished laying out the page yet.
        var w = container.offsetWidth;
        if (w === 0) {
            setTimeout(initChart, 200);
            return;
        }

        // --- Create the LWC chart ---
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
            rightPriceScale: {
                borderColor: GRID_COLOR
            },
            timeScale: {
                borderColor:    GRID_COLOR,
                timeVisible:    true,
                secondsVisible: false
            }
        });

        // Candlestick series
        candleSeries = chart.addCandlestickSeries({
            upColor:       UP_COLOR,
            downColor:     DOWN_COLOR,
            borderVisible: false,
            wickUpColor:   UP_COLOR,
            wickDownColor: DOWN_COLOR
        });

        // Volume histogram at bottom 15% of chart
        volumeSeries = chart.addHistogramSeries({
            color:        '#667eea',
            priceFormat:  { type: 'volume' },
            priceScaleId: 'volume',
            scaleMargins: { top: 0.85, bottom: 0 }
        });

        // Responsive resize
        window.addEventListener('resize', function () {
            if (chart && container) {
                chart.resize(container.offsetWidth, CHART_HEIGHT);
            }
        });

        console.log('[LWC] Chart ready. Width=' + w + 'px');
    }

    // =================================================================
    // 2. loadData
    // Called by Dash clientside_callback when dcc.Store changes.
    // storeData = { symbol, timeframe, bars: [{time, open, high, low, close, volume}] }
    // =================================================================
    function loadData(storeData) {
        // If chart is not initialised yet, retry in 300ms
        if (!chart || !candleSeries) {
            setTimeout(function () { loadData(storeData); }, 300);
            return;
        }

        var bars   = storeData.bars   || [];
        var symbol = storeData.symbol || '?';

        if (bars.length === 0) {
            console.warn('[LWC] No bars received for ' + symbol);
            return;
        }

        // Sort bars ascending by time (safety guard)
        bars.sort(function (a, b) { return a.time - b.time; });

        // Load OHLC candles
        candleSeries.setData(bars.map(function (b) {
            return { time: b.time, open: b.open, high: b.high,
                     low: b.low, close: b.close };
        }));

        // Load volume (colour matches candle direction)
        volumeSeries.setData(bars.map(function (b) {
            return {
                time:  b.time,
                value: b.volume,
                color: b.close >= b.open
                    ? UP_COLOR + '88'
                    : DOWN_COLOR + '88'
            };
        }));

        // Remember last bar so live tick can continue the candle
        var last    = bars[bars.length - 1];
        lastBarTime  = last.time;
        lastBarOpen  = last.open;
        lastBarClose = last.close;
        currentSymbol = symbol;

        chart.timeScale().fitContent();

        console.log('[LWC] Loaded ' + bars.length + ' bars for '
                    + symbol + ' (' + storeData.timeframe + ')');

        startTickPolling(symbol);
    }

    // =================================================================
    // 3. Real-time tick polling
    // Calls /api/tick/<symbol> every TICK_POLL_MS milliseconds.
    // Updates the LAST candle in real time (open price stays fixed,
    // high/low/close change as new prices arrive).
    // =================================================================
    function startTickPolling(symbol) {
        if (tickTimer) { clearInterval(tickTimer); }
        tickTimer = setInterval(function () { pollTick(symbol); }, TICK_POLL_MS);
    }

    function pollTick(symbol) {
        if (!symbol || !candleSeries || lastBarTime === null) { return; }

        fetch('/api/tick/' + encodeURIComponent(symbol))
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (!data || !data.price || data.price <= 0) { return; }

                // Update the current candle with the latest price.
                // open stays as it was when the candle opened,
                // high/low expand as price moves, close = latest price.
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
    // 4. Indicator API  (used by future MA / RSI / MACD callbacks)
    //
    // Example:
    //   window.lwcManager.addIndicator(
    //     'MA20', 'line',
    //     [{time: 1700000000, value: 182.5}, ...],
    //     { color: '#FFD700', lineWidth: 2 }
    //   );
    // =================================================================
    function addIndicator(name, type, data, options) {
        if (!chart) {
            console.warn('[LWC] Chart not ready for indicator: ' + name);
            return;
        }
        if (indicatorSeries[name]) {
            chart.removeSeries(indicatorSeries[name]);
        }
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
        console.log('[LWC] Indicator added: ' + name + ' (' + type + ')');
    }

    // =================================================================
    // 5. removeIndicator
    // =================================================================
    function removeIndicator(name) {
        if (indicatorSeries[name] && chart) {
            chart.removeSeries(indicatorSeries[name]);
            delete indicatorSeries[name];
            console.log('[LWC] Indicator removed: ' + name);
        }
    }

    // --- Public API ---
    window.lwcManager = {
        loadData:        loadData,
        addIndicator:    addIndicator,
        removeIndicator: removeIndicator
    };

    // Start init loop - will keep retrying every 200ms until
    // the container exists AND has a non-zero width
    setTimeout(initChart, 200);

}());

/**
 * IB Trading Platform - Lightweight Charts Manager
 * ================================================
 *
 * Responsibilities:
 *  1. initChart()       - Creates the LWC chart once on page load
 *  2. loadData()        - Loads historical OHLCV bars from dcc.Store (via clientside_callback)
 *  3. pollTick()        - Polls /api/tick/<symbol> every 1 s for live price updates
 *  4. addIndicator()    - Public API for future indicators (MA, RSI, MACD, ...)
 *  5. removeIndicator() - Removes a named indicator series
 *
 * Data flow:
 *   Python (ib_connector) --> dcc.Store (JSON) --> clientside_callback
 *      --> window.lwcManager.loadData() --> candleSeries.setData()
 *   setInterval 1s --> /api/tick/SYMBOL --> candleSeries.update()
 */
(function () {
    'use strict';

    // ── Configuration ──────────────────────────────────────────────
    var TICK_POLL_INTERVAL_MS = 1000;
    var CHART_BG     = '#1e1e2e';
    var PANEL_BG     = '#2d2d3a';
    var UP_COLOR     = '#26a69a';
    var DOWN_COLOR   = '#ef5350';
    var GRID_COLOR   = '#3d3d4a';
    var TEXT_COLOR   = '#d1d4dc';
    var VOLUME_UP    = '#26a69a88';  // semi-transparent
    var VOLUME_DOWN  = '#ef535088';

    // ── Internal state ─────────────────────────────────────────────
    var chart           = null;
    var candleSeries    = null;
    var volumeSeries    = null;
    var tickTimer       = null;
    var currentSymbol   = null;
    var lastBarTime     = null;   // Unix timestamp of most recent historical bar
    var lastBarOpen     = null;   // Open price of last bar (for live tick candle)
    var lastBarClose    = null;   // Close price of last bar
    var indicatorSeries = {};     // { name: LWC series } - used by addIndicator()

    // ── 1. initChart ───────────────────────────────────────────────
    function initChart() {
        var container = document.getElementById('lwc-container');
        if (!container) {
            // Dash may not have rendered the div yet - retry shortly
            setTimeout(initChart, 200);
            return;
        }

        chart = LightweightCharts.createChart(container, {
            width:  container.clientWidth,
            height: 500,
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

        // ── Candlestick series (main OHLC chart) ──────────────────
        candleSeries = chart.addCandlestickSeries({
            upColor:       UP_COLOR,
            downColor:     DOWN_COLOR,
            borderVisible: false,
            wickUpColor:   UP_COLOR,
            wickDownColor: DOWN_COLOR
        });

        // ── Volume histogram (bottom 15% of chart area) ───────────
        volumeSeries = chart.addHistogramSeries({
            color:       '#667eea',
            priceFormat: { type: 'volume' },
            priceScaleId: 'volume',
            scaleMargins: { top: 0.85, bottom: 0 }
        });

        // Responsive resize on window change
        window.addEventListener('resize', function () {
            if (chart && container) {
                chart.applyOptions({ width: container.clientWidth });
            }
        });

        console.log('[LWC] Chart initialized');
    }

    // ── 2. loadData ────────────────────────────────────────────────
    /**
     * Called by Dash clientside_callback whenever dcc.Store changes.
     * storeData = { symbol, timeframe, bars: [{time, open, high, low, close, volume}] }
     */
    function loadData(storeData) {
        if (!chart || !candleSeries) {
            // Chart not ready yet - wait and retry
            setTimeout(function () { loadData(storeData); }, 300);
            return;
        }

        var bars   = storeData.bars   || [];
        var symbol = storeData.symbol || '?';

        if (bars.length === 0) {
            console.warn('[LWC] No bars for', symbol);
            return;
        }

        // Safety: sort ascending by time
        bars.sort(function (a, b) { return a.time - b.time; });

        // Feed OHLC data to candle series
        candleSeries.setData(bars.map(function (b) {
            return { time: b.time, open: b.open, high: b.high,
                     low: b.low, close: b.close };
        }));

        // Feed volume data (colour matches candle direction)
        volumeSeries.setData(bars.map(function (b) {
            return {
                time:  b.time,
                value: b.volume,
                color: b.close >= b.open ? VOLUME_UP : VOLUME_DOWN
            };
        }));

        // Remember last bar so live tick updates can continue the candle
        var last     = bars[bars.length - 1];
        lastBarTime  = last.time;
        lastBarOpen  = last.open;
        lastBarClose = last.close;
        currentSymbol = symbol;

        // Fit all bars into view
        chart.timeScale().fitContent();

        console.log('[LWC] Loaded', bars.length, 'bars for', symbol,
                    '(' + storeData.timeframe + ')');

        // Restart live tick polling for the new symbol
        startTickPolling(symbol);
    }

    // ── 3. pollTick ────────────────────────────────────────────────
    function startTickPolling(symbol) {
        if (tickTimer) { clearInterval(tickTimer); }
        tickTimer = setInterval(function () { pollTick(symbol); },
                                TICK_POLL_INTERVAL_MS);
    }

    function pollTick(symbol) {
        if (!symbol || !candleSeries || lastBarTime === null) { return; }

        fetch('/api/tick/' + encodeURIComponent(symbol))
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (!data || !data.price || data.price <= 0) { return; }

                // Update the most recent candle with the new price.
                // This keeps the last candle "alive" in real time
                // until a new historical bar arrives on next loadData() call.
                candleSeries.update({
                    time:  lastBarTime,
                    open:  lastBarOpen,
                    high:  Math.max(lastBarOpen, data.price),
                    low:   Math.min(lastBarOpen, data.price),
                    close: data.price
                });

                lastBarClose = data.price;
            })
            .catch(function () {
                // Silently ignore network errors (IB might not be connected)
            });
    }

    // ── 4. addIndicator ────────────────────────────────────────────
    /**
     * Add a named indicator series to the chart.
     * Future indicators (MA, EMA, Bollinger, RSI pane, MACD) will call this.
     *
     * @param {string} name    - Unique identifier, e.g. 'MA20', 'EMA50', 'RSI'
     * @param {string} type    - 'line' | 'histogram' | 'area'
     * @param {Array}  data    - [{time: unixInt, value: number}, ...]
     * @param {Object} options - LWC series options (color, lineWidth, priceScaleId, ...)
     *
     * Example:
     *   window.lwcManager.addIndicator('MA20', 'line',
     *       [{time: 1700000000, value: 182.5}, ...],
     *       { color: '#FFD700', lineWidth: 2 });
     */
    function addIndicator(name, type, data, options) {
        if (!chart) {
            console.warn('[LWC] Chart not ready for indicator:', name);
            return;
        }

        // Remove previous series with same name (idempotent update)
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
        console.log('[LWC] Indicator added:', name, '(' + type + ')');
    }

    // ── 5. removeIndicator ─────────────────────────────────────────
    function removeIndicator(name) {
        if (indicatorSeries[name] && chart) {
            chart.removeSeries(indicatorSeries[name]);
            delete indicatorSeries[name];
            console.log('[LWC] Indicator removed:', name);
        }
    }

    // ── Public API exposed on window ───────────────────────────────
    window.lwcManager = {
        loadData:        loadData,
        addIndicator:    addIndicator,
        removeIndicator: removeIndicator
    };

    // Init: wait for DOM if needed
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initChart);
    } else {
        initChart();
    }

}());

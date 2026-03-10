/**
 * IB Trading Platform - Lightweight Charts Manager v2.4.0
 * =========================================================
 * v2.4.0:
 *   - NEW: prependData() for loading older bars (incremental history)
 *   - NEW: currentTf + tfSeconds for new bar detection in tick polling
 *   - FIX: pollTick() detects new bar creation and handles it correctly
 *   - FIX: Efficient tick update - only updates last 2-3 bars, not full chart
 */
(function () {
  "use strict";

  var VERSION = "v2.4.0";
  var TICK_POLL_MS = 5000;
  var CHART_BG = "#1e1e2e";
  var GRID_COLOR = "#3d3d4a";
  var TEXT_COLOR = "#d1d4dc";
  var UP_COLOR = "#26a69a";
  var DOWN_COLOR = "#ef5350";
  var CHART_HEIGHT = 500;
  var VOLUME_HEIGHT = 80;
  var RSI_HEIGHT = 160;
  var MACD_HEIGHT = 160;

  var chart = null;
  var candleSeries = null;
  var volumeChart = null;
  var volumeSeries = null;
  var tickTimer = null;
  var tickEnabled = false;
  var currentSymbol = null;
  var currentAssetType = "STOCK";
  var currentTf = "5 mins";
  var tfSeconds = 300; // Default 5 mins
  var lastBarTime = null;
  var lastBarOpen = null;
  var lastBarHigh = null;
  var lastBarLow = null;
  var lastBarClose = null;
  var allBars = []; // Store all bars for prepend operation
  var indicatorSeries = {};
  var subCharts = {};
  var container = null;
  var initAttempts = 0;
  var syncingRange = false;

  // Timeframe to seconds mapping
  var TF_TO_SECONDS = {
    "1 min": 60,
    "5 mins": 300,
    "15 mins": 900,
    "30 mins": 1800,
    "1 hour": 3600,
    "1 day": 86400,
  };

  // =================================================================
  // Debug logger
  // =================================================================
  function writeDebug(type, msg) {
    var ts = new Date().toLocaleTimeString("cs-CZ");
    var line = "[" + ts + "] [" + type + "] " + msg + "\n";
    if (type === "ERR") {
      console.error("[LWC] " + msg);
    } else if (type === "WARN") {
      console.warn("[LWC] " + msg);
    } else {
      console.log("[LWC] " + msg);
    }
    var area = document.getElementById("debug-log-area");
    if (area) {
      area.value = line + area.value;
    }
  }
  window.lwcDebug = writeDebug;

  function showPlaceholder(msg) {
    var c = document.getElementById("lwc-container");
    if (!c) {
      return;
    }
    c.innerHTML =
      '<div style="color:#667eea;font-size:14px;padding:20px;' +
      "font-family:monospace;background:#1e1e2e;height:100%;box-sizing:border-box;" +
      'display:flex;align-items:center;justify-content:center;">' +
      "\u23f3 " +
      msg +
      "</div>";
  }

  // =================================================================
  // 1. initChart + initVolumeChart
  // =================================================================
  function initChart() {
    initAttempts++;
    container = document.getElementById("lwc-container");
    if (!container) {
      setTimeout(initChart, 200);
      return;
    }
    var w = container.offsetWidth;
    if (w === 0) {
      showPlaceholder("Cekam na vykreslovani... (" + initAttempts + ")");
      setTimeout(initChart, 200);
      return;
    }
    if (typeof LightweightCharts === "undefined") {
      writeDebug("ERR", "LightweightCharts NENI NACTENA!");
      showPlaceholder("CHYBA: CDN se nenactlo!");
      return;
    }

    writeDebug(
      "INIT",
      "Vytvarim graf " + w + "x" + CHART_HEIGHT + "px " + VERSION,
    );
    showPlaceholder("Inicializuji graf...");
    try {
      container.innerHTML = "";
      chart = LightweightCharts.createChart(container, {
        width: w,
        height: CHART_HEIGHT,
        layout: { background: { color: CHART_BG }, textColor: TEXT_COLOR },
        grid: { vertLines: { visible: false }, horzLines: { visible: false } },
        crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
        rightPriceScale: { borderColor: GRID_COLOR },
        timeScale: {
          borderColor: GRID_COLOR,
          timeVisible: true,
          secondsVisible: false,
        },
      });
      candleSeries = chart.addCandlestickSeries({
        upColor: UP_COLOR,
        downColor: DOWN_COLOR,
        borderVisible: false,
        wickUpColor: UP_COLOR,
        wickDownColor: DOWN_COLOR,
      });
      window.addEventListener("resize", onResize);
      writeDebug("INIT", "Hlavni graf OK. Vytvarim volume sub-panel...");
      initVolumeChart();
      writeDebug("INIT", VERSION + " ready. Klikni Load Chart.");
    } catch (e) {
      writeDebug("ERR", "createChart selhal: " + e.message);
      showPlaceholder("CHYBA: " + e.message);
    }
  }

  function initVolumeChart() {
    if (!container) return;
    var w = container.offsetWidth;

    var wrapper = document.createElement("div");
    wrapper.id = "lwc-volume-wrapper";
    wrapper.style.cssText = "position:relative;";

    var titleBar = document.createElement("div");
    titleBar.style.cssText =
      "background:#1a1a2e;color:#555;font-size:11px;padding:2px 8px;" +
      "border-top:1px solid #2a2a3a;font-family:monospace;letter-spacing:0.5px;";
    titleBar.textContent = "\u2219 Volume";

    var div = document.createElement("div");
    div.id = "lwc-volume-container";
    div.style.cssText =
      "width:100%;height:" + VOLUME_HEIGHT + "px;background:" + CHART_BG + ";";

    wrapper.appendChild(titleBar);
    wrapper.appendChild(div);
    container.parentNode.insertBefore(wrapper, container.nextSibling);

    volumeChart = LightweightCharts.createChart(div, {
      width: w,
      height: VOLUME_HEIGHT,
      layout: { background: { color: CHART_BG }, textColor: TEXT_COLOR },
      grid: { vertLines: { visible: false }, horzLines: { visible: false } },
      crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
      rightPriceScale: {
        borderColor: GRID_COLOR,
        scaleMargins: { top: 0.05, bottom: 0 },
        minimumWidth: 60,
      },
      timeScale: {
        borderColor: GRID_COLOR,
        timeVisible: false,
        secondsVisible: false,
        visible: false,
      },
      handleScroll: false,
      handleScale: false,
    });
    volumeSeries = volumeChart.addHistogramSeries({
      color: "#667eea88",
      priceFormat: { type: "volume" },
      priceScaleId: "right",
      priceLineVisible: false,
      lastValueVisible: false,
    });

    // Sync logical range: hlavni chart -> volume (jednostranny, volume nema scroll)
    syncTimeScales(chart, [volumeChart]);
    writeDebug("INIT", "Volume sub-panel OK (" + VOLUME_HEIGHT + "px)");
  }

  function onResize() {
    var w = container ? container.offsetWidth : 0;
    if (w === 0) return;
    if (chart) chart.resize(w, CHART_HEIGHT);
    if (volumeChart) volumeChart.resize(w, VOLUME_HEIGHT);
    Object.keys(subCharts).forEach(function (k) {
      var sc = subCharts[k];
      var el = document.getElementById("lwc-" + k + "-container");
      if (sc && el) sc.resize(w, k === "rsi" ? RSI_HEIGHT : MACD_HEIGHT);
    });
  }

  // =================================================================
  // 2. loadData
  // =================================================================
  function loadData(storeData) {
    writeDebug(
      "DATA",
      "loadData() symbol=" +
        (storeData && storeData.symbol) +
        " | baru=" +
        (storeData && storeData.bars ? storeData.bars.length : "N/A"),
    );

    if (!chart || !candleSeries) {
      setTimeout(function () {
        loadData(storeData);
      }, 300);
      return;
    }

    var bars = storeData.bars || [];
    var symbol = storeData.symbol || "?";

    if (bars.length === 0) {
      writeDebug("WARN", "ZADNE BARY pro " + symbol);
      showPlaceholder("Zadna data pro " + symbol);
      return;
    }

    bars.sort(function (a, b) {
      return a.time - b.time;
    });

    // Store all bars for prepend operation
    allBars = bars.slice();

    // Set timeframe for tick polling
    currentTf = storeData.timeframe || "5 mins";
    tfSeconds = TF_TO_SECONDS[currentTf] || 300;
    writeDebug("DATA", "TF=" + currentTf + " -> " + tfSeconds + "s per bar");

    var b0 = bars[0];
    writeDebug(
      "DATA",
      "Prvni: t=" +
        b0.time +
        " o=" +
        b0.open +
        " c=" +
        b0.close +
        " | Posledni: c=" +
        bars[bars.length - 1].close,
    );

    try {
      candleSeries.setData(
        bars.map(function (b) {
          return {
            time: b.time,
            open: b.open,
            high: b.high,
            low: b.low,
            close: b.close,
          };
        }),
      );

      if (volumeSeries) {
        volumeSeries.setData(
          bars.map(function (b) {
            return {
              time: b.time,
              value: b.volume || 0,
              color: b.close >= b.open ? UP_COLOR + "77" : DOWN_COLOR + "77",
            };
          }),
        );
        // POZOR: fitContent() na volumeChart NEVOLAME
        // Sync logical range ze hlavniho chartu to zaridi automaticky
      }

      var last = bars[bars.length - 1];
      lastBarTime = last.time;
      lastBarOpen = last.open;
      lastBarHigh = last.high;
      lastBarLow = last.low;
      lastBarClose = last.close;
      currentSymbol = symbol;
      currentAssetType = storeData.asset_type || "STOCK";

      // fitContent na hlavnim chartu spusti logicalRangeChange -> sync vsechno
      chart.timeScale().fitContent();
      writeDebug(
        "DATA",
        "USPECH: " +
          bars.length +
          " svicek | " +
          symbol +
          " | " +
          currentAssetType +
          " | TF=" +
          currentTf,
      );

      if (tickEnabled) startTickPolling(symbol, currentAssetType);
      else if (tickTimer) {
        clearInterval(tickTimer);
        tickTimer = null;
      }
    } catch (e) {
      writeDebug("ERR", "setData selhal: " + e.message);
    }
  }

  // =================================================================
  // 2.5 prependData - load older bars (incremental history)
  // =================================================================
  function prependData(storeData) {
    writeDebug(
      "DATA",
      "prependData() symbol=" +
        (storeData && storeData.symbol) +
        " | baru=" +
        (storeData && storeData.bars ? storeData.bars.length : "N/A"),
    );

    if (!chart || !candleSeries) {
      setTimeout(function () {
        prependData(storeData);
      }, 300);
      return;
    }

    var olderBars = storeData.bars || [];
    if (olderBars.length === 0) {
      writeDebug("WARN", "prependData: zadne starsi bary");
      return;
    }

    // Sort older bars
    olderBars.sort(function (a, b) {
      return a.time - b.time;
    });

    // Save current visible range
    var visibleRange = null;
    try {
      visibleRange = chart.timeScale().getVisibleLogicalRange();
    } catch (e) {}

    // Merge: olderBars + allBars (olderBars are already before allBars[0].time)
    var newOldestTime = olderBars[0].time;
    var currentOldestTime = allBars.length > 0 ? allBars[0].time : null;

    if (currentOldestTime && newOldestTime >= currentOldestTime) {
      writeDebug(
        "WARN",
        "prependData: older bars nejsou starsi nez soucasne - ignoruji",
      );
      return;
    }

    // Combine all bars
    allBars = olderBars.concat(allBars);
    writeDebug(
      "DATA",
      "prependData: celkem " +
        allBars.length +
        " svicek (+" +
        olderBars.length +
        " starsich)",
    );

    // Re-set all data (LWC doesn't have prepend API)
    try {
      candleSeries.setData(
        allBars.map(function (b) {
          return {
            time: b.time,
            open: b.open,
            high: b.high,
            low: b.low,
            close: b.close,
          };
        }),
      );

      if (volumeSeries) {
        volumeSeries.setData(
          allBars.map(function (b) {
            return {
              time: b.time,
              value: b.volume || 0,
              color: b.close >= b.open ? UP_COLOR + "77" : DOWN_COLOR + "77",
            };
          }),
        );
      }

      // Restore visible range (user stays at same position)
      if (visibleRange) {
        // Shift the range by the number of new bars added
        var shiftedRange = {
          from: visibleRange.from + olderBars.length,
          to: visibleRange.to + olderBars.length,
        };
        chart.timeScale().setVisibleLogicalRange(shiftedRange);
      }

      writeDebug(
        "DATA",
        "prependData OK: celkem " + allBars.length + " svicek",
      );
    } catch (e) {
      writeDebug("ERR", "prependData selhal: " + e.message);
    }
  }

  // =================================================================
  // 3. testChart
  // =================================================================
  function testChart() {
    writeDebug("TEST", "=== TEST CHART - 100 fake svicek ===");
    var bars = [],
      now = Math.floor(Date.now() / 1000),
      price = 200;
    for (var i = 99; i >= 0; i--) {
      var t = now - i * 300;
      var change = (Math.random() - 0.47) * 3;
      var open = price;
      price = Math.max(10, price + change);
      var high = Math.max(open, price) + Math.random() * 1.5;
      var low = Math.min(open, price) - Math.random() * 1.5;
      bars.push({
        time: t,
        open: open,
        high: high,
        low: low,
        close: price,
        volume: Math.floor(Math.random() * 500000 + 50000),
      });
    }
    loadData({
      symbol: "TEST-DATA",
      timeframe: "5 mins (FAKE)",
      asset_type: "STOCK",
      bars: bars,
    });
  }

  // =================================================================
  // 4. Tick polling
  // =================================================================
  function startTickPolling(symbol, assetType) {
    if (tickTimer) {
      clearInterval(tickTimer);
      tickTimer = null;
    }
    if (!tickEnabled) return;
    writeDebug(
      "TICK",
      "Polling pro " +
        symbol +
        " (" +
        (assetType || "STOCK") +
        ") kazdych " +
        TICK_POLL_MS +
        "ms | TF=" +
        currentTf +
        " (" +
        tfSeconds +
        "s)",
    );
    tickTimer = setInterval(function () {
      pollTick(symbol, assetType || "STOCK");
    }, TICK_POLL_MS);
  }

  function pollTick(symbol, assetType) {
    if (!tickEnabled || !symbol || !candleSeries || lastBarTime === null)
      return;
    fetch(
      "/api/tick/" +
        encodeURIComponent(symbol) +
        "?asset_type=" +
        encodeURIComponent(assetType || "STOCK"),
    )
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        if (!data || data.price === undefined) return;
        var price = parseFloat(data.price);
        var serverTime = data.time || Math.floor(Date.now() / 1000);
        if (price <= 0) return;

        // Calculate expected next bar time
        var nextBarTime = lastBarTime + tfSeconds;
        var isNewBar = serverTime >= nextBarTime;

        if (isNewBar && lastBarClose !== null) {
          // === NEW BAR: finalize current and create new ===
          writeDebug(
            "TICK",
            "NOVA SVICKA! serverTime=" +
              serverTime +
              " >= nextBarTime=" +
              nextBarTime +
              " | old close=" +
              lastBarClose.toFixed(2),
          );

          // Finalize current bar
          candleSeries.update({
            time: lastBarTime,
            open: lastBarOpen,
            high: lastBarHigh,
            low: lastBarLow,
            close: lastBarClose,
          });

          // Add to allBars
          allBars.push({
            time: lastBarTime,
            open: lastBarOpen,
            high: lastBarHigh,
            low: lastBarLow,
            close: lastBarClose,
            volume: 0,
          });

          // Create new bar
          lastBarTime = nextBarTime;
          lastBarOpen = price;
          lastBarHigh = price;
          lastBarLow = price;
          lastBarClose = price;

          candleSeries.update({
            time: lastBarTime,
            open: price,
            high: price,
            low: price,
            close: price,
          });

          writeDebug(
            "TICK",
            "NOVA SVICKA vytvorena: t=" +
              lastBarTime +
              " o=h=l=c=" +
              price.toFixed(2),
          );
        } else {
          // === UPDATE CURRENT BAR ===
          var prevClose = lastBarClose || price;
          var changed = Math.abs(price - prevClose) > 0.001;
          lastBarHigh = Math.max(lastBarHigh, price);
          lastBarLow = Math.min(lastBarLow, price);
          lastBarClose = price;

          if (changed) {
            writeDebug(
              "TICK",
              symbol +
                " \u2192 " +
                price.toFixed(2) +
                " (\u0394" +
                (price - prevClose > 0 ? "+" : "") +
                (price - prevClose).toFixed(2) +
                ") | H=" +
                lastBarHigh.toFixed(2) +
                " L=" +
                lastBarLow.toFixed(2),
            );
          }

          // Update only the last bar (efficient)
          candleSeries.update({
            time: lastBarTime,
            open: lastBarOpen,
            high: lastBarHigh,
            low: lastBarLow,
            close: lastBarClose,
          });

          // Update in allBars
          if (allBars.length > 0) {
            var lastBar = allBars[allBars.length - 1];
            if (lastBar.time === lastBarTime) {
              lastBar.high = lastBarHigh;
              lastBar.low = lastBarLow;
              lastBar.close = lastBarClose;
            }
          }
        }
      })
      .catch(function (e) {
        writeDebug("TICK", "FETCH ERROR: " + e);
      });
  }

  // =================================================================
  // 5. setTickEnabled
  // =================================================================
  function setTickEnabled(enabled) {
    tickEnabled = !!enabled;
    if (tickEnabled) {
      if (currentSymbol) startTickPolling(currentSymbol, currentAssetType);
      else writeDebug("TICK", "Tick ON - nejdrive nacti graf");
    } else {
      if (tickTimer) {
        clearInterval(tickTimer);
        tickTimer = null;
      }
    }
  }

  // =================================================================
  // 6. syncTimeScales  *** KLIC FIX: logical range misto time range ***
  //
  //  subscribeVisibleLogicalRangeChange + setVisibleLogicalRange
  //  zarucuje pixel-perfect sync bez posunu pri zoumu/scrollu
  // =================================================================
  function syncTimeScales(sourceChart, targetCharts) {
    sourceChart
      .timeScale()
      .subscribeVisibleLogicalRangeChange(function (range) {
        if (syncingRange || !range) return;
        syncingRange = true;
        targetCharts.forEach(function (tc) {
          try {
            tc.timeScale().setVisibleLogicalRange(range);
          } catch (e) {}
        });
        syncingRange = false;
      });
  }

  // =================================================================
  // 7. Sub-chart helpers
  // =================================================================
  function getOrCreateSubContainer(id, height, label) {
    var existing = document.getElementById(id);
    if (existing) return existing;

    var anchor =
      document.getElementById("lwc-macd-container") ||
      document.getElementById("lwc-rsi-container") ||
      document.getElementById("lwc-volume-container") ||
      document.getElementById("lwc-container");

    var anchorWrapper =
      anchor && anchor.parentNode && !anchor.parentNode.id
        ? anchor.parentNode
        : anchor;
    if (!anchorWrapper) {
      writeDebug("ERR", "Nelze najit anchor pro " + id);
      return null;
    }

    var wrapper = document.createElement("div");
    wrapper.style.cssText = "position:relative;";

    var titleBar = document.createElement("div");
    titleBar.style.cssText =
      "background:#1a1a2e;color:#555;font-size:11px;padding:2px 8px;" +
      "border-top:1px solid #2a2a3a;font-family:monospace;letter-spacing:0.5px;";
    titleBar.textContent = label || id;

    var div = document.createElement("div");
    div.id = id;
    div.style.cssText =
      "width:100%;height:" + height + "px;background:" + CHART_BG + ";";

    wrapper.appendChild(titleBar);
    wrapper.appendChild(div);
    anchorWrapper.parentNode.insertBefore(wrapper, anchorWrapper.nextSibling);
    return div;
  }

  function removeSubContainer(id) {
    var el = document.getElementById(id);
    if (!el) return;
    var wrapper = el.parentNode;
    if (wrapper && wrapper.parentNode && !wrapper.id) {
      wrapper.parentNode.removeChild(wrapper);
    } else if (el.parentNode) {
      el.parentNode.removeChild(el);
    }
  }

  function clearSubCharts() {
    if (subCharts.rsi) {
      subCharts.rsi.remove();
      delete subCharts.rsi;
    }
    if (subCharts.macd) {
      subCharts.macd.remove();
      delete subCharts.macd;
    }
    removeSubContainer("lwc-rsi-container");
    removeSubContainer("lwc-macd-container");
  }

  // =================================================================
  // 8. RSI sub-chart
  // =================================================================
  function createRsiChart(rsiData, period) {
    var el = getOrCreateSubContainer(
      "lwc-rsi-container",
      RSI_HEIGHT,
      "\u2219 RSI (" + period + ")",
    );
    if (!el) return;

    var w = el.offsetWidth || (container ? container.offsetWidth : 800);
    var rsiChart = LightweightCharts.createChart(el, {
      width: w,
      height: RSI_HEIGHT,
      layout: { background: { color: CHART_BG }, textColor: TEXT_COLOR },
      grid: { vertLines: { visible: false }, horzLines: { visible: false } },
      crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
      rightPriceScale: {
        borderColor: GRID_COLOR,
        scaleMargins: { top: 0.05, bottom: 0.05 },
      },
      timeScale: {
        borderColor: GRID_COLOR,
        timeVisible: false,
        secondsVisible: false,
        visible: false,
      },
      handleScroll: false,
      handleScale: false,
    });

    var ob70 = rsiChart.addLineSeries({
      color: "#ef535044",
      lineWidth: 1,
      lineStyle: 2,
      priceScaleId: "right",
      lastValueVisible: false,
      priceLineVisible: false,
    });
    var os30 = rsiChart.addLineSeries({
      color: "#26a69a44",
      lineWidth: 1,
      lineStyle: 2,
      priceScaleId: "right",
      lastValueVisible: false,
      priceLineVisible: false,
    });
    var rsiLine = rsiChart.addLineSeries({
      color: "#ce93d8",
      lineWidth: 2,
      priceScaleId: "right",
      title: "RSI" + period,
      lastValueVisible: true,
      priceLineVisible: false,
    });

    var validData = rsiData.filter(function (d) {
      return d.value !== null && d.value !== undefined;
    });
    if (validData.length === 0) {
      writeDebug("IND", "RSI: zadna platna data");
      return;
    }

    var times = validData.map(function (d) {
      return d.time;
    });
    var tMin = times[0],
      tMax = times[times.length - 1];
    ob70.setData([
      { time: tMin, value: 70 },
      { time: tMax, value: 70 },
    ]);
    os30.setData([
      { time: tMin, value: 30 },
      { time: tMax, value: 30 },
    ]);
    rsiLine.setData(
      validData.map(function (d) {
        return { time: d.time, value: d.value };
      }),
    );

    subCharts.rsi = rsiChart;

    // Sync z hlavniho chartu (jednosmerny - RSI nema scroll)
    var allPassive = [rsiChart];
    if (volumeChart) allPassive.push(volumeChart);
    if (subCharts.macd) allPassive.push(subCharts.macd);
    syncTimeScales(chart, allPassive);

    // Aplikuj aktualni logical range hned po nacteni
    try {
      var curRange = chart.timeScale().getVisibleLogicalRange();
      if (curRange) rsiChart.timeScale().setVisibleLogicalRange(curRange);
    } catch (e) {}

    writeDebug("IND", "RSI sub-chart OK: " + validData.length + " bodu");
  }

  // =================================================================
  // 9. MACD sub-chart
  // =================================================================
  function createMacdChart(macdData) {
    var el = getOrCreateSubContainer(
      "lwc-macd-container",
      MACD_HEIGHT,
      "\u2219 MACD (12 / 26 / 9)",
    );
    if (!el) return;

    var w = el.offsetWidth || (container ? container.offsetWidth : 800);
    var macdChart = LightweightCharts.createChart(el, {
      width: w,
      height: MACD_HEIGHT,
      layout: { background: { color: CHART_BG }, textColor: TEXT_COLOR },
      grid: { vertLines: { visible: false }, horzLines: { visible: false } },
      crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
      rightPriceScale: {
        borderColor: GRID_COLOR,
        scaleMargins: { top: 0.1, bottom: 0.1 },
      },
      timeScale: {
        borderColor: GRID_COLOR,
        timeVisible: true,
        secondsVisible: false,
      },
      handleScroll: false,
      handleScale: false,
    });

    var histSeries = macdChart.addHistogramSeries({
      priceScaleId: "right",
      priceLineVisible: false,
      lastValueVisible: false,
    });
    var macdLine = macdChart.addLineSeries({
      color: "#42a5f5",
      lineWidth: 2,
      priceScaleId: "right",
      title: "MACD",
      lastValueVisible: true,
      priceLineVisible: false,
    });
    var signalLine = macdChart.addLineSeries({
      color: "#ff9800",
      lineWidth: 1,
      priceScaleId: "right",
      title: "Signal",
      lastValueVisible: true,
      priceLineVisible: false,
    });

    var validMacd = macdData.filter(function (d) {
      return d.macd !== null && d.macd !== undefined;
    });
    var validSignal = macdData.filter(function (d) {
      return d.signal !== null && d.signal !== undefined;
    });
    var validHist = macdData.filter(function (d) {
      return d.histogram !== null && d.histogram !== undefined;
    });

    if (validMacd.length === 0) {
      writeDebug("IND", "MACD: zadna platna data");
      return;
    }

    histSeries.setData(
      validHist.map(function (d) {
        return {
          time: d.time,
          value: d.histogram,
          color: d.histogram >= 0 ? UP_COLOR + "aa" : DOWN_COLOR + "aa",
        };
      }),
    );
    macdLine.setData(
      validMacd.map(function (d) {
        return { time: d.time, value: d.macd };
      }),
    );
    signalLine.setData(
      validSignal.map(function (d) {
        return { time: d.time, value: d.signal };
      }),
    );

    subCharts.macd = macdChart;

    var allPassive = [macdChart];
    if (volumeChart) allPassive.push(volumeChart);
    if (subCharts.rsi) allPassive.push(subCharts.rsi);
    syncTimeScales(chart, allPassive);

    // Aplikuj aktualni logical range hned
    try {
      var curRange = chart.timeScale().getVisibleLogicalRange();
      if (curRange) macdChart.timeScale().setVisibleLogicalRange(curRange);
    } catch (e) {}

    writeDebug("IND", "MACD sub-chart OK: " + validMacd.length + " bodu");
  }

  // =================================================================
  // 10. Indicator overlays (SMA / EMA)
  // =================================================================
  function addIndicator(name, type, data, options) {
    if (!chart) {
      writeDebug("WARN", "Graf neni ready: " + name);
      return;
    }
    if (indicatorSeries[name]) {
      try {
        chart.removeSeries(indicatorSeries[name]);
      } catch (e) {}
    }
    var series;
    if (type === "histogram") series = chart.addHistogramSeries(options || {});
    else if (type === "area") series = chart.addAreaSeries(options || {});
    else series = chart.addLineSeries(options || {});
    series.setData(data);
    indicatorSeries[name] = series;
    writeDebug(
      "IND",
      "Overlay: " + name + " (" + type + ") | " + data.length + " bodu",
    );
  }

  function removeIndicator(name) {
    if (indicatorSeries[name] && chart) {
      try {
        chart.removeSeries(indicatorSeries[name]);
      } catch (e) {}
      delete indicatorSeries[name];
      writeDebug("IND", "Odebrano overlay: " + name);
    }
  }

  // =================================================================
  // 11. setIndicators
  // =================================================================
  function setIndicators(data) {
    if (!chart || !candleSeries) {
      writeDebug("IND", "setIndicators: chart neni ready, zkousim za 500ms");
      setTimeout(function () {
        setIndicators(data);
      }, 500);
      return;
    }
    writeDebug(
      "IND",
      "=== setIndicators() ok=" +
        data.ok +
        " bars=" +
        (data.bars || 0) +
        " sma=" +
        !!data.sma +
        " ema=" +
        !!data.ema +
        " rsi=" +
        !!data.rsi +
        " macd=" +
        !!data.macd +
        " ===",
    );

    if (data.sma) {
      var smaData = data.sma
        .filter(function (d) {
          return d.value !== null && d.value !== undefined;
        })
        .map(function (d) {
          return { time: d.time, value: d.value };
        });
      if (smaData.length > 0) {
        addIndicator("sma", "line", smaData, {
          color: "#ff9800",
          lineWidth: 1,
          priceScaleId: "right",
          title: "SMA" + (data.sma_period || 20),
          lastValueVisible: true,
          priceLineVisible: false,
        });
      }
    } else {
      removeIndicator("sma");
    }

    if (data.ema) {
      var emaData = data.ema
        .filter(function (d) {
          return d.value !== null && d.value !== undefined;
        })
        .map(function (d) {
          return { time: d.time, value: d.value };
        });
      if (emaData.length > 0) {
        addIndicator("ema", "line", emaData, {
          color: "#42a5f5",
          lineWidth: 1,
          priceScaleId: "right",
          title: "EMA" + (data.ema_period || 20),
          lastValueVisible: true,
          priceLineVisible: false,
        });
      }
    } else {
      removeIndicator("ema");
    }

    if (subCharts.rsi) {
      subCharts.rsi.remove();
      delete subCharts.rsi;
    }
    removeSubContainer("lwc-rsi-container");
    if (data.rsi) createRsiChart(data.rsi, data.rsi_period || 14);

    if (subCharts.macd) {
      subCharts.macd.remove();
      delete subCharts.macd;
    }
    removeSubContainer("lwc-macd-container");
    if (data.macd) createMacdChart(data.macd);
  }

  // =================================================================
  // Public API
  // =================================================================
  window.lwcManager = {
    loadData: loadData,
    prependData: prependData,
    testChart: testChart,
    setTickEnabled: setTickEnabled,
    addIndicator: addIndicator,
    removeIndicator: removeIndicator,
    setIndicators: setIndicators,
    getCandleSeries: function () {
      return candleSeries;
    },
    clearSubCharts: clearSubCharts,
    getAllBars: function () {
      return allBars;
    },
  };

  writeDebug("INIT", "=== LWC Manager " + VERSION + " nacteny ===");
  setTimeout(initChart, 300);
})();

/**
 * IB Trading Platform - Lightweight Charts Manager v2.5.0 (Factory)
 * ================================================================
 * v2.5.0:
 *   - REFACTORED: Factory pattern - createChartInstance(containerId)
 *   - Each chart instance has independent state (chart, candleSeries, etc.)
 *   - Two instances: window.lwcManager (main), window.lwcManager2 (context)
 *   - lwcManager2: plain candlestick + volume only (no tick, indicators, trade lines)
 *   - Constants shared: VERSION, TICK_POLL_MS, CHART_BG, GRID_COLOR, TEXT_COLOR, etc.
 */
(function () {
  "use strict";

  // =================================================================
  // SHARED CONSTANTS (module-level, truly shared)
  // =================================================================
  var VERSION = "v2.5.0";
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
  // Debug logger (shared global)
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

  // =================================================================
  // Factory: createChartInstance(containerId)
  // Returns public API object (same shape as old window.lwcManager)
  // =================================================================
  function createChartInstance(containerId) {

    // --- Instance-local state ---
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
    var volumePaddingLeft = 0;
    var tickPollCount = 0; // counts poll cycles for indicator refresh
    var INDICATOR_REFRESH_EVERY = 12; // refresh indicators every ~60s (12 * 5s)
    var activeIndicatorSettings = null; // last known indicator settings

    // --- Instance-local resize handler ---
    function onResize() {
      var w = container ? container.offsetWidth : 0;
      if (w === 0) return;
      if (chart) chart.resize(w, CHART_HEIGHT);
      if (volumeChart) volumeChart.resize(w, VOLUME_HEIGHT);
      Object.keys(subCharts).forEach(function (k) {
        var sc = subCharts[k];
        var el = document.getElementById(containerId + "-" + k + "-container");
        if (sc && el) sc.resize(w, k === "rsi" ? RSI_HEIGHT : MACD_HEIGHT);
      });
    }

    // =================================================================
    // showPlaceholder (instance-local)
    // =================================================================
    function showPlaceholder(msg) {
      var c = document.getElementById(containerId);
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
      writeDebug("INIT", "[" + containerId + "] initChart() attempt #" + initAttempts);
      container = document.getElementById(containerId);
      if (!container) {
        writeDebug("ERR", "[" + containerId + "] Container NOT FOUND! Retrying in 200ms");
        setTimeout(initChart, 200);
        return;
      }
      writeDebug("INIT", "[" + containerId + "] Container found, offsetWidth=" + container.offsetWidth);
      var w = container.offsetWidth;
      if (w === 0) {
        writeDebug("WARN", "[" + containerId + "] Container width=0, retrying in 200ms (#" + initAttempts + ")");
        showPlaceholder("Cekam na vykreslovani... (" + initAttempts + ")");
        setTimeout(initChart, 200);
        return;
      }
      writeDebug("INIT", "[" + containerId + "] Container width=" + w + "px, creating chart...");
      if (typeof LightweightCharts === "undefined") {
        writeDebug("ERR", "LightweightCharts NENI NACTENA!");
        showPlaceholder("CHYBA: CDN se nenactlo!");
        return;
      }

      writeDebug(
        "INIT",
        "Vytvarim graf " + containerId + " " + w + "x" + CHART_HEIGHT + "px " + VERSION,
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

      // Unique IDs per instance
      var wrapperId = containerId + "-volume-wrapper";
      var volContainerId = containerId + "-volume-container";

      var wrapper = document.createElement("div");
      wrapper.id = wrapperId;
      wrapper.style.cssText = "position:relative;";

      var titleBar = document.createElement("div");
      titleBar.style.cssText =
        "background:#1a1a2e;color:#555;font-size:11px;padding:2px 8px;" +
        "border-top:1px solid #2a2a3a;font-family:monospace;letter-spacing:0.5px;";
      titleBar.textContent = "\u2219 Volume";

      var div = document.createElement("div");
      div.id = volContainerId;
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

    // =================================================================
    // 2. loadData
    // =================================================================
    function loadData(storeData) {
      writeDebug(
        "DATA",
        "[" + containerId + "] loadData() symbol=" +
          (storeData && storeData.symbol) +
          " | baru=" +
          (storeData && storeData.bars ? storeData.bars.length : "N/A"),
      );

      if (!chart || !candleSeries) {
        writeDebug("WARN", "[" + containerId + "] chart/candleSeries not ready, retrying in 300ms");
        setTimeout(function () {
          loadData(storeData);
        }, 300);
        return;
      }
      writeDebug("DATA", "[" + containerId + "] chart ready, processing " + (storeData.bars ? storeData.bars.length : 0) + " bars");

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
      tickPollCount = 0; // reset indicator refresh counter on new load
      volumePaddingLeft = 0; // reset padding offset - bude nastaveno po nacteni indikatoru
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

        // Update price precision based on asset type
        var isForex = currentAssetType === "FOREX";
        candleSeries.applyOptions({
          priceFormat: {
            type: "price",
            precision: isForex ? 4 : 2,
            minMove: isForex ? 0.0001 : 0.01,
          },
        });

        // fitContent na hlavnim chartu spusti timeRangeChange -> sync volume (time-based)
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

        // Only enable tick polling if this instance supports it
        // (lwcManager2 does NOT get tick polling per Phase 3 requirements)
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
          // Volume chart se synchronizuje automaticky pres subscribeVisibleTimeRangeChange
        }

        writeDebug(
          "DATA",
          "prependData OK: celkem " + allBars.length + " svicek",
        );
        // Obnov indikatoru po pridani starsich baru (EMA/SMA potřebuje nová data)
        if (activeIndicatorSettings) {
          refreshIndicatorsIfNeeded();
        }
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

    function refreshIndicatorsIfNeeded() {
      if (!activeIndicatorSettings || !currentSymbol || !currentTf) return;
      var settings = activeIndicatorSettings;
      var active = [];
      if (settings.sma) active.push("sma");
      if (settings.ema) active.push("ema");
      if (settings.rsi) active.push("rsi");
      if (settings.macd) active.push("macd");
      if (active.length === 0) return;
      var tf = currentTf.replace(/ /g, "_");
      var url =
        "/api/indicators/" +
        currentSymbol +
        "/" +
        tf +
        "?active=" +
        active.join(",") +
        "&asset_type=" +
        encodeURIComponent(currentAssetType);
      fetch(url)
        .then(function (r) {
          return r.json();
        })
        .then(function (data) {
          if (!data.ok) return;
          // Use THIS instance's setIndicators
          setIndicators(data);
        })
        .catch(function (e) {
          writeDebug("IND", "Auto-refresh error: " + e);
        });
    }

    function pollTick(symbol, assetType) {
      if (!tickEnabled || !symbol || !candleSeries || lastBarTime === null)
        return;
      tickPollCount++;
      if (tickPollCount % INDICATOR_REFRESH_EVERY === 0) {
        refreshIndicatorsIfNeeded();
      }
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
          if (price <= 0) return;

          // Use tick's own timestamp to determine which bar it belongs to.
          // This correctly handles demo account ~15min delay: the tick's timestamp
          // reflects the actual market time, not the current system clock.
          var tickTime = data.time
            ? parseInt(data.time)
            : Math.floor(Date.now() / 1000);

          // Align tick timestamp to the bar it belongs to (floor to TF boundary)
          var tickBarTime = Math.floor(tickTime / tfSeconds) * tfSeconds;

          // Determine if this tick belongs to last known bar, a past bar, or a new bar
          if (tickBarTime < lastBarTime) {
            // === DELAYED TICK: belongs to a previous bar - update that bar in allBars ===
            writeDebug(
              "TICK",
              "DELAYED TICK: tickBarTime=" +
                tickBarTime +
                " < lastBarTime=" +
                lastBarTime +
                " | Updating past bar with price=" +
                price.toFixed(2),
            );
            // Find and update the matching bar in allBars
            for (var i = allBars.length - 1; i >= 0; i--) {
              if (allBars[i].time === tickBarTime) {
                allBars[i].high = Math.max(allBars[i].high, price);
                allBars[i].low = Math.min(allBars[i].low, price);
                allBars[i].close = price;
                candleSeries.update({
                  time: allBars[i].time,
                  open: allBars[i].open,
                  high: allBars[i].high,
                  low: allBars[i].low,
                  close: allBars[i].close,
                });
                break;
              }
            }
            return;
          }

          if (tickBarTime > lastBarTime && lastBarClose !== null) {
            // === NEW BAR: tick belongs to a bar after the current one ===
            writeDebug(
              "TICK",
              "NOVA SVICKA! tickBarTime=" +
                tickBarTime +
                " > lastBarTime=" +
                lastBarTime +
                " | old close=" +
                lastBarClose.toFixed(2),
            );

            // Finalize current bar in allBars
            if (
              allBars.length > 0 &&
              allBars[allBars.length - 1].time === lastBarTime
            ) {
              allBars[allBars.length - 1].high = lastBarHigh;
              allBars[allBars.length - 1].low = lastBarLow;
              allBars[allBars.length - 1].close = lastBarClose;
            }

            // Create new bar at the correct tick bar time
            lastBarTime = tickBarTime;
            lastBarOpen = price;
            lastBarHigh = price;
            lastBarLow = price;
            lastBarClose = price;

            allBars.push({
              time: lastBarTime,
              open: lastBarOpen,
              high: lastBarHigh,
              low: lastBarLow,
              close: lastBarClose,
              volume: 0,
            });

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
            // === UPDATE CURRENT BAR (tickBarTime === lastBarTime) ===
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
    // 6. syncTimeScales  - time range sync pro volume chart
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
      // id is now just the sub-chart type (e.g., "rsi", "macd")
      // Full ID becomes containerId + "-" + id + "-container"
      var fullId = containerId + "-" + id + "-container";
      var existing = document.getElementById(fullId);
      if (existing) return existing;

      // Find anchor: look for existing sub-containers in THIS instance
      var anchor =
        document.getElementById(containerId + "-macd-container") ||
        document.getElementById(containerId + "-rsi-container") ||
        document.getElementById(containerId + "-volume-container") ||
        document.getElementById(containerId);

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
      div.id = fullId;
      div.style.cssText =
        "width:100%;height:" + height + "px;background:" + CHART_BG + ";";

      wrapper.appendChild(titleBar);
      wrapper.appendChild(div);
      anchorWrapper.parentNode.insertBefore(wrapper, anchorWrapper.nextSibling);
      return div;
    }

    function removeSubContainer(id) {
      var fullId = containerId + "-" + id + "-container";
      var el = document.getElementById(fullId);
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
      removeSubContainer("rsi");
      removeSubContainer("macd");
    }

    // =================================================================
    // 8. RSI sub-chart
    // =================================================================
    function createRsiChart(rsiData, period) {
      var el = getOrCreateSubContainer(
        "rsi",
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
        "macd",
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
    function setIndicators(data, settingsOverride) {
      if (!chart || !candleSeries) {
        writeDebug("IND", "setIndicators: chart neni ready, zkousim za 500ms");
        setTimeout(function () {
          setIndicators(data, settingsOverride);
        }, 500);
        return;
      }
      // Store settings for auto-refresh during tick polling
      if (settingsOverride) activeIndicatorSettings = settingsOverride;
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
        // Omez SMA data na timestamps ktere existuji v OHLCV barech (allBars).
        var ohlcvTimesForSma = {};
        allBars.forEach(function (b) {
          ohlcvTimesForSma[b.time] = true;
        });
        var smaData = data.sma
          .filter(function (d) {
            return (
              d.value !== null &&
              d.value !== undefined &&
              ohlcvTimesForSma[d.time]
            );
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
        // Omez EMA data na timestamps ktere existuji v OHLCV barech (allBars).
        var ohlcvTimes = {};
        allBars.forEach(function (b) {
          ohlcvTimes[b.time] = true;
        });
        var emaData = data.ema
          .filter(function (d) {
            return (
              d.value !== null && d.value !== undefined && ohlcvTimes[d.time]
            );
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
      removeSubContainer("rsi");
      if (data.rsi) createRsiChart(data.rsi, data.rsi_period || 14);

      if (subCharts.macd) {
        subCharts.macd.remove();
        delete subCharts.macd;
      }
      removeSubContainer("macd");
      if (data.macd) createMacdChart(data.macd);

      // Pridat padding bary do volumeSeries pro timestamps EMA/SMA (historicke body pred prvni svickou).
      // Resync volume chartu s hlavnim chartem (EMA/SMA maj uz stejne timestamps jako OHLCV)
      if (volumeChart) {
        setTimeout(function () {
          try {
            var curRange = chart.timeScale().getVisibleLogicalRange();
            if (curRange)
              volumeChart.timeScale().setVisibleLogicalRange(curRange);
          } catch (e) {}
        }, 50);
      }
    }

    // =================================================================
    // Public API for this instance
    // =================================================================
    return {
      initChart: initChart,
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
  }

  // =================================================================
  // Create two chart instances
  // =================================================================
  // Main chart: lwcManager gets full functionality (tick, indicators, trade lines)
  window.lwcManager = createChartInstance("lwc-container");

  // Context chart: lwcManager2 is plain candlestick + volume only
  // Per Phase 3: NO tick polling, NO indicators, NO trade lines
  window.lwcManager2 = createChartInstance("lwc-container-2");

  writeDebug("INIT", "=== LWC Manager " + VERSION + " factory loaded ===");
  writeDebug("INIT", "=== lwcManager (main): full features ===");
  writeDebug("INIT", "=== lwcManager2 (context): candlestick + volume only ===");

  // Auto-init main chart after DOM is ready
  setTimeout(function () {
    if (window.lwcManager && window.lwcManager.loadData) {
      writeDebug("INIT", "lwcManager auto-init starting");
      if (window.lwcManager.initChart) {
        window.lwcManager.initChart();
      }
      if (window.lwcManager2 && window.lwcManager2.initChart) {
        window.lwcManager2.initChart();
      }
    }
  }, 300);
})();

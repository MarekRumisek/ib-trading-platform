"""IB API Connector using ib_async

Version: 2.9.5 - ghost subscription cleanup + invalid contract guard

HIERARCHIE FALLBACKU:
  1. STREAMING   reqMktData(snapshot=False)  -> okamzity update
  2. SNAPSHOT    reqTickersAsync()           -> kazdych 15s
  3. HIST_POLL   reqHistoricalDataAsync()    -> kazdych 30s, mdt=4, useRTH=True

Error 10089 -> okamzity skok na hist_poll.

CHANGELOG:
v2.9.1  place_order: PendingSubmit je platny stav -> success=True
v2.9.2  get_positions: cache aktualizovana pres positionEvent
v2.9.3  pridano: _ib_sleep_lock + _positions_bg_loop
        BUG: bg thread volal self.ib.sleep() -> pouzil jiny asyncio loop
             -> IB events se vubec nezpracovaly -> cache vzdy prazdna
v2.9.4  OPRAVA: _positions_bg_loop ma vlastni IB() instanci (clientId+3)
         -> thread vlastni svoji IB instanci -> ib_poll.sleep() funguje spravne
         -> reqPositions() + sleep(1) kazdych 3s = vzdy aktualni data
         -> odstranen _ib_sleep_lock a _ib_sleep_safe() (uz nepotrebne)
v2.9.5  OPRAVA: tick subscriber odmita kontrakty s conId=0,
         nezkousi je donekonecna znovu a umi odhlasit puvodni symbol pri zmene
"""

from ib_async import IB, MarketOrder, LimitOrder
from datetime import datetime, timedelta
from contract_utils import (
    asset_type_from_contract,
    create_contract,
    get_display_symbol_from_contract,
    get_cache_symbol,
    get_contract_key,
    get_history_what_to_show,
    normalize_asset_type,
    sanitize_symbol,
    use_regular_trading_hours,
)
from modules.data_store import data_store
import config
import time
import threading
import queue
import asyncio


# ================================================================
# _TickSubscriber
# ================================================================

class _TickSubscriber:

    def __init__(self, host, port, client_id):
        self._host         = host
        self._port         = port
        self._client_id    = client_id
        self._latest: dict      = {}
        self._tickers: dict     = {}
        self._pending: set      = set()
        self._unsubscribe_pending: set = set()
        self._failed_keys: set  = set()
        self._last_errors: list = []
        self._lock             = threading.Lock()
        self._connected: bool  = False
        self._iterations: int  = 0
        self._mdt: int         = 0
        self._mode: str        = 'init'
        self._next_hist_poll: int = 0
        self._primary_key: str | None = None

        self._thread = threading.Thread(
            target=self._run, daemon=True,
            name=f'IB-TickSub-cid{client_id}'
        )
        self._thread.start()
        print(f"[TICK-SUB] Worker spusten (clientId={client_id})")

    def get_price(self, symbol: str, asset_type: str = 'STOCK') -> float:
        key = get_contract_key(symbol, asset_type)
        return float(self._latest.get(key, {}).get('price', 0.0))

    def get_ticker_data(self, symbol: str, asset_type: str = 'STOCK'):
        key = get_contract_key(symbol, asset_type)
        info = self._latest.get(key)
        if not info or info.get('price', 0) <= 0:
            return None
        return info.copy()

    def get_raw_data(self, symbol: str, asset_type: str = 'STOCK') -> dict:
        key    = get_contract_key(symbol, asset_type)
        ticker = self._tickers.get(key)
        if not ticker:
            return {'error': 'not_subscribed',
                    'subscribed': list(self._tickers.keys()),
                    'pending':    list(self._pending)}
        def safe(v):
            try:
                if v is None: return None
                if isinstance(v, float) and v != v: return 'NaN'
                return v
            except Exception: return str(v)
        fields = {
            'last':     safe(ticker.last),
            'lastSize': safe(ticker.lastSize),
            'close':    safe(ticker.close),
            'bid':      safe(ticker.bid),
            'ask':      safe(ticker.ask),
            'bidSize':  safe(ticker.bidSize),
            'askSize':  safe(ticker.askSize),
            'open':     safe(ticker.open),
            'high':     safe(ticker.high),
            'low':      safe(ticker.low),
            'volume':   safe(ticker.volume),
            'halted':   safe(getattr(ticker, 'halted', None)),
        }
        try:
            b, a = ticker.bid, ticker.ask
            fields['_midpoint'] = (round((b + a) / 2, 4)
                                   if b and a and b == b and a == a and b > 0 and a > 0 else 0)
        except Exception:
            fields['_midpoint'] = 0
        return fields

    def get_last_errors(self) -> list:
        return list(self._last_errors)

    def subscribe(self, symbol: str, asset_type: str = 'STOCK'):
        key = get_contract_key(symbol, asset_type)
        with self._lock:
            if key in self._failed_keys:
                return
            self._unsubscribe_pending.discard(key)
            self._pending.add(key)

    def unsubscribe(self, symbol: str, asset_type: str = 'STOCK'):
        key = get_contract_key(symbol, asset_type)
        with self._lock:
            self._pending.discard(key)
            self._unsubscribe_pending.add(key)
            self._latest.pop(key, None)
            if self._primary_key == key:
                self._primary_key = None

    def set_primary_subscription(self, symbol: str, asset_type: str = 'STOCK'):
        key = get_contract_key(symbol, asset_type)
        with self._lock:
            if key in self._failed_keys:
                return
            prev_key = self._primary_key
            self._primary_key = key
            self._unsubscribe_pending.discard(key)
            self._pending.add(key)
            if prev_key and prev_key != key:
                self._pending.discard(prev_key)
                self._unsubscribe_pending.add(prev_key)
                self._latest.pop(prev_key, None)

    @property
    def is_connected(self) -> bool: return self._connected
    @property
    def iterations(self) -> int: return self._iterations
    @property
    def subscribed_symbols(self) -> list: return list(self._tickers.keys())
    @property
    def mode(self) -> str: return self._mode

    def _mark_failed(self, key: str, reason: str):
        with self._lock:
            already_failed = key in self._failed_keys
            self._failed_keys.add(key)
            self._pending.discard(key)
            self._unsubscribe_pending.discard(key)
            self._latest.pop(key, None)
            if self._primary_key == key:
                self._primary_key = None
        if not already_failed:
            print(f"[TICK-SUB] INVALID {key}: {reason} -> subscription stopped")

    @staticmethod
    def _extract_price(t) -> float:
        for attr in ('last', 'close', 'bid', 'ask'):
            v = getattr(t, attr, None)
            if v is not None and v == v and v > 0:
                return float(v)
        try:
            b, a = t.bid, t.ask
            if b == b and a == a and b > 0 and a > 0:
                return (b + a) / 2.0
        except Exception:
            pass
        return 0.0

    def _make_latest(self, t, price, mode=None) -> dict:
        return {
            'price':  price,
            'last':   float(t.last)  if t.last  == t.last  and t.last  else 0.0,
            'close':  float(t.close) if t.close == t.close and t.close else 0.0,
            'bid':    float(t.bid)   if t.bid   == t.bid   and t.bid   else 0.0,
            'ask':    float(t.ask)   if t.ask   == t.ask   and t.ask   else 0.0,
            'volume': (int(t.volume) if t.volume == t.volume and t.volume else 0),
            'mdt':    self._mdt, 'mode': mode or self._mode,
            'iterations': self._iterations, 'ts': time.time()
        }

    def _has_error(self, code: int) -> bool:
        return any(f'[{code}]' in e for e in self._last_errors[-10:])

    def _run(self):
        asyncio.run(self._async_run())

    async def _async_run(self):
        while True:
            try:
                await self._connect_and_stream()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"[TICK-SUB] Outer error: {e}")
            self._connected = False
            self._tickers   = {}
            self._mode      = 'init'
            print("[TICK-SUB] Reconnecting in 10s...")
            await asyncio.sleep(10)

    async def _connect_and_stream(self):
        ib = IB()
        def on_ib_error(reqId, errorCode, errorString, contract):
            msg = f"[{errorCode}] reqId={reqId}: {errorString}"
            self._last_errors = (self._last_errors + [msg])[-20:]
            if errorCode not in (2104, 2106, 2107, 2108, 2158, 2119):
                print(f"[TICK-SUB] IB_ERR [{errorCode}] reqId={reqId}: {errorString}")
        ib.errorEvent += on_ib_error
        try:
            connected = False
            for offset in range(10):
                cid = self._client_id + offset
                try:
                    print(f"[TICK-SUB] connectAsync clientId={cid}...")
                    await ib.connectAsync(self._host, self._port, clientId=cid)
                    if offset > 0:
                        print(f"[TICK-SUB] Pripojeno s fallback clientId={cid} (base={self._client_id})")
                    else:
                        print(f"[TICK-SUB] Pripojeno! clientId={cid}")
                    connected = True
                    break
                except Exception as e:
                    err_str = str(e)
                    is_conflict = 'TimeoutError' in type(e).__name__ or 'TimeoutError' in err_str or '326' in err_str
                    if is_conflict:
                        print(f"[TICK-SUB] clientId={cid} in use (Error 326), trying cid={cid+1}...")
                        try: ib.disconnect()
                        except: pass
                        await asyncio.sleep(0.5)
                        continue
                    raise
            if not connected:
                raise RuntimeError(f"[TICK-SUB] Could not connect: all clientIds {self._client_id}–{self._client_id+9} in use")
            ib.reqMarketDataType(3)
            self._mdt       = 3
            self._connected = True
            self._mode      = 'streaming'
            contracts_local: dict = {}
            tickers_local: dict   = {}
            self._tickers         = tickers_local
            self._next_hist_poll  = 0
            while ib.isConnected():
                with self._lock:
                    removed_keys = list(self._unsubscribe_pending)
                    self._unsubscribe_pending.clear()
                    new_syms = list(
                        self._pending
                        - set(contracts_local.keys())
                        - self._failed_keys
                    )
                    self._pending.clear()
                for key in removed_keys:
                    ticker = tickers_local.pop(key, None)
                    contracts_local.pop(key, None)
                    self._latest.pop(key, None)
                    if ticker is not None:
                        try:
                            ib.cancelMktData(ticker)
                        except Exception:
                            pass
                    print(f"[TICK-SUB] UNSUB {key}")
                for key in new_syms:
                    try:
                        asset_type, sym = key.split(':', 1)
                        contract = create_contract(sym, asset_type)
                        await ib.qualifyContractsAsync(contract)
                        if int(getattr(contract, 'conId', 0) or 0) <= 0:
                            self._mark_failed(key, 'qualified contract has conId=0')
                            continue
                        contracts_local[key] = contract
                        print(f"[TICK-SUB] Contract OK: {sym} ({asset_type}) conId={contract.conId}")
                        if self._mode == 'streaming':
                            ticker = ib.reqMktData(contract, '', False, False)
                            tickers_local[key] = ticker
                            def make_handler(contract_key):
                                def on_ticker(t):
                                    p = self._extract_price(t)
                                    if p > 0:
                                        self._latest[contract_key] = self._make_latest(t, p)
                                return on_ticker
                            ticker.updateEvent += make_handler(key)
                            print(f"[TICK-SUB] STREAM {sym} ({asset_type})")
                        elif self._mode == 'hist_poll':
                            self._next_hist_poll = self._iterations
                            print(f"[TICK-SUB] HIST_POLL {sym} ({asset_type}) (zadna mkt sub potreba)")
                    except ValueError as e:
                        self._mark_failed(key, str(e))
                    except Exception as e:
                        print(f"[TICK-SUB] Subscribe error {key}: {e}")
                        with self._lock:
                            if key not in self._failed_keys and key not in self._unsubscribe_pending:
                                self._pending.add(key)
                await asyncio.sleep(1.0)
                self._iterations += 1
                if self._mode != 'hist_poll' and self._has_error(10089):
                    print("[TICK-SUB] Error 10089 -> HIST_POLL rezim")
                    for t in list(tickers_local.values()):
                        try: ib.cancelMktData(t)
                        except Exception: pass
                    tickers_local.clear()
                    self._mode           = 'hist_poll'
                    self._mdt            = 99
                    self._next_hist_poll = self._iterations
                elif self._mode == 'streaming':
                    for key, t in list(tickers_local.items()):
                        if self._latest.get(key, {}).get('price', 0) <= 0:
                            p = self._extract_price(t)
                            if p > 0:
                                self._latest[key] = self._make_latest(t, p)
                    if self._iterations == 15 and contracts_local:
                        no_data = all(
                            self._latest.get(s, {}).get('price', 0) <= 0
                            for s in contracts_local
                        )
                        if no_data:
                            print("[TICK-SUB] 15s bez dat -> SNAPSHOT")
                            for t in list(tickers_local.values()):
                                try: ib.cancelMktData(t)
                                except Exception: pass
                            tickers_local.clear()
                            self._mode = 'snapshot'
                            self._mdt  = 40
                elif self._mode == 'snapshot' and self._iterations % 15 == 0:
                    for key, contract in list(contracts_local.items()):
                        try:
                            snaps = await ib.reqTickersAsync(contract)
                            if snaps:
                                t = snaps[0]
                                p = self._extract_price(t)
                                if p > 0:
                                    self._latest[key] = self._make_latest(t, p)
                                    print(f"[TICK-SUB] SNAP {key}: p={p}")
                        except Exception as e:
                            print(f"[TICK-SUB] Snapshot err {key}: {e}")
                    if self._has_error(10089):
                        print("[TICK-SUB] Snapshot 10089 -> HIST_POLL")
                        self._mode           = 'hist_poll'
                        self._mdt            = 99
                        self._next_hist_poll = self._iterations
                elif self._mode == 'hist_poll' and self._iterations >= self._next_hist_poll:
                    self._next_hist_poll = self._iterations + 30
                    ib.reqMarketDataType(4)
                    for key, contract in list(contracts_local.items()):
                        try:
                            asset_type, sym = key.split(':', 1)
                            bars = await ib.reqHistoricalDataAsync(
                                contract, endDateTime='',
                                durationStr='1 D', barSizeSetting='1 min',
                                whatToShow=get_history_what_to_show(asset_type),
                                useRTH=use_regular_trading_hours(asset_type), formatDate=1, timeout=60
                            )
                            if bars:
                                price = float(bars[-1].close)
                                bar_t = bars[-1].date
                                self._latest[key] = {
                                    'price':  price, 'last': price,
                                    'close':  float(bars[-2].close) if len(bars) > 1 else price,
                                    'bid':    0.0, 'ask': 0.0,
                                    'volume': int(bars[-1].volume) if bars[-1].volume else 0,
                                    'mdt': 99, 'mode': 'hist_poll', 'asset_type': asset_type,
                                    'bar_time': str(bar_t),
                                    'iterations': self._iterations, 'ts': time.time()
                                }
                                print(f"[TICK-SUB] HIST_POLL {sym} ({asset_type}): close={price:.2f}  bar={bar_t}  ({len(bars)} bars)")
                            else:
                                print(f"[TICK-SUB] HIST_POLL {sym} ({asset_type}): stale prazdne, retry za 5s")
                                self._next_hist_poll = self._iterations + 5
                        except Exception as e:
                            print(f"[TICK-SUB] HIST_POLL err {key}: {e}")
                            self._next_hist_poll = self._iterations + 5
        finally:
            self._connected = False
            self._tickers   = {}
            self._mode      = 'init'
            try:
                if ib.isConnected(): ib.disconnect()
            except Exception:
                pass


# ================================================================
# _HistWorker
# ================================================================

class _HistWorker:
    def __init__(self, host, port, client_id):
        self._host      = host
        self._port      = port
        self._client_id = client_id
        self._queue     = queue.Queue()
        self._thread    = threading.Thread(
            target=self._run, daemon=True,
            name=f'IB-Hist-Worker-cid{client_id}'
        )
        self._thread.start()
        print(f"[HIST] Worker thread spusten (clientId={client_id})")
        self._deep_load_status = {}

    def get_deep_load_status(self):
        return self._deep_load_status.copy()

    def start_deep_load(self, symbol, timeframe, asset_type='STOCK'):
        asset_type = normalize_asset_type(asset_type)
        symbol = sanitize_symbol(symbol, asset_type)
        key = f"{asset_type}:{symbol}_{timeframe}"
        if self._deep_load_status.get(key, {}).get('status') == 'running':
            return False
        self._deep_load_status[key] = {'progress': '0%', 'status': 'running', 'msg': 'Inicializace...'}
        self._queue.put(('deep_load', symbol, timeframe, key, asset_type, None, None))
        return True

    def fetch(self, symbol, duration='1 D', bar_size='5 mins', asset_type='STOCK', timeout=15):
        result, done = [], threading.Event()
        self._queue.put(('fetch', symbol, duration, bar_size, asset_type, result, done))
        done.wait(timeout=timeout)
        return result

    def stop(self):
        self._queue.put(None)

    def _run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        while True:
            item = self._queue.get()
            if item is None: break
            cmd = item[0]
            if cmd == 'fetch':
                _, symbol, duration, bar_size, asset_type, result, done = item
                try:
                    bars = self._fetch_fresh(symbol, duration, bar_size, asset_type)
                    result.extend(bars)
                except Exception as e:
                    print(f"[HIST] Chyba pro {symbol}: {e}")
                finally:
                    done.set()
            elif cmd == 'fetch_n':
                _, symbol, n, bar_size, asset_type, end_time, result, done = item
                try:
                    bars = self._fetch_n_bars_fresh(symbol, n, bar_size, asset_type, end_time)
                    result.extend(bars)
                except Exception as e:
                    print(f"[HIST] fetch_n_bars chyba pro {symbol}: {e}")
                finally:
                    done.set()
            elif cmd == 'deep_load':
                _, symbol, timeframe, key, asset_type, _, _ = item
                try:
                    self._run_deep_load(symbol, timeframe, key, asset_type)
                except Exception as e:
                    self._deep_load_status[key] = {'progress': 'ERROR', 'status': 'error', 'msg': str(e)}

    def _run_deep_load(self, symbol, timeframe, key, asset_type='STOCK'):
        CHUNKS = {
            '1 min':  {'duration': '5 D',  'steps': 6},
            '5 mins': {'duration': '10 D', 'steps': 6},
            '15 mins':{'duration': '1 M',  'steps': 6},
            '30 mins':{'duration': '2 M',  'steps': 6},
            '1 hour': {'duration': '3 M',  'steps': 4},
            '1 day':  {'duration': '5 Y',  'steps': 1}
        }
        cfg          = CHUNKS.get(timeframe, {'duration': '10 D', 'steps': 3})
        duration_str = cfg['duration']
        steps        = cfg['steps']
        ib = IB()
        try:
            ib.connect(self._host, self._port, clientId=self._client_id + 10, timeout=10)
            ib.reqMarketDataType(4)
            contract = create_contract(symbol, asset_type)
            ib.qualifyContracts(contract)
            end_date = ''
            for i in range(steps):
                self._deep_load_status[key] = {
                    'progress': f"{int(i/steps*100)}%",
                    'status': 'running',
                    'msg': f'Krok {i+1}/{steps}'
                }
                print(f"[DEEP LOAD] {symbol} {timeframe} - Krok {i+1}/{steps}")
                bars = ib.reqHistoricalData(
                    contract, endDateTime=end_date, durationStr=duration_str,
                    barSizeSetting=timeframe,
                    whatToShow=get_history_what_to_show(asset_type),
                    useRTH=use_regular_trading_hours(asset_type), formatDate=1, timeout=30
                )
                if not bars:
                    print(f"[DEEP LOAD] Zadne dalsi data z IB pro {symbol}.")
                    break
                result = [{
                    'time':   _bar_date_to_unix(b.date),
                    'open':   b.open, 'high': b.high,
                    'low':    b.low,  'close': b.close,
                    'volume': b.volume
                } for b in bars]
                data_store.append_bars(get_cache_symbol(symbol, asset_type), timeframe, result)
                first_bar_time = bars[0].date
                if hasattr(first_bar_time, 'timestamp'):
                    end_date = first_bar_time - timedelta(seconds=1)
                else:
                    break
                if i < steps - 1:
                    time.sleep(2.0)
            self._deep_load_status[key] = {'progress': '100%', 'status': 'done', 'msg': 'Dokonceno'}
            print(f"[DEEP LOAD] {symbol} {timeframe} Dokoncen uspesne.")
        finally:
            try: ib.disconnect()
            except: pass

    def _connect_with_retry(self, ib, max_retries=10):
        """Connect to IB with clientId bump on Error 326.

        TWS refuses a clientId that it still considers active (e.g. previous
        process didn't fully disconnect yet).  Instead of waiting, we try the
        next clientId offset (base, base+1, … base+9).  Each attempt gets its
        own fresh IB() — the caller must pass a NEW ib instance each time or
        we reassign self._active_client_id so the caller knows which one won.
        """
        last_exc = None
        for offset in range(max_retries):
            cid = self._client_id + offset
            try:
                ib.connect(self._host, self._port, clientId=cid, timeout=10)
                if offset > 0:
                    print(f"[HIST] Connected with fallback clientId={cid} (base={self._client_id})")
                return True
            except Exception as e:
                last_exc = e
                err_str = str(e)
                # TimeoutError is what ib_async raises when TWS sends Error 326
                is_conflict = 'TimeoutError' in type(e).__name__ or 'TimeoutError' in err_str or '326' in err_str
                if is_conflict:
                    print(f"[HIST] clientId={cid} in use (Error 326), trying cid={cid+1}...")
                    try: ib.disconnect()
                    except: pass
                    time.sleep(0.5)
                    continue
                raise
        raise last_exc

    def _fetch_fresh(self, symbol, duration, bar_size, asset_type='STOCK'):
        ib = IB()
        try:
            print(f"[HIST-DIAG] _fetch_fresh START: {symbol} ({asset_type}) duration={duration} bar_size={bar_size}")
            self._connect_with_retry(ib)
            print(f"[HIST-DIAG] Connected OK, isConnected={ib.isConnected()}")
            ib.reqMarketDataType(4)
            contract = create_contract(symbol, asset_type)
            print(f"[HIST-DIAG] Contract before qualify: {contract}")
            ib.qualifyContracts(contract)
            print(f"[HIST-DIAG] Contract after qualify: conId={contract.conId}, {contract}")
            use_rth = use_regular_trading_hours(asset_type)
            print(f"[HIST-DIAG] Calling reqHistoricalData timeout=30, useRTH={use_rth}...")
            bars = ib.reqHistoricalData(
                contract, endDateTime='', durationStr=duration,
                barSizeSetting=bar_size,
                whatToShow=get_history_what_to_show(asset_type),
                useRTH=use_rth, formatDate=1, timeout=30
            )
            print(f"[HIST-DIAG] reqHistoricalData returned {len(bars) if bars else 0} bars")
            result = [{
                'time':   _bar_date_to_unix(b.date),
                'open':   b.open, 'high': b.high,
                'low':    b.low,  'close': b.close,
                'volume': b.volume
            } for b in bars]
            print(f"[HIST] OK: {len(result)} baru pro {symbol} ({normalize_asset_type(asset_type)})")
            return result
        finally:
            try: ib.disconnect()
            except Exception: pass

    # ------------------------------------------------------------------
    # N-bar fetch with optional end_time (for offset-based loading)
    # ------------------------------------------------------------------

    def fetch_n_bars(self, symbol, n, bar_size, asset_type='STOCK', end_time=None, timeout=20):
        """
        Fetch approximately N bars. If end_time is provided (Unix timestamp),
        fetch bars ending at that time (for loading older history).
        Returns list of bars sorted oldest-first, max N items.
        """
        result, done = [], threading.Event()
        self._queue.put(('fetch_n', symbol, n, bar_size, asset_type, end_time, result, done))
        done.wait(timeout=timeout)
        return result

    def _fetch_n_bars_fresh(self, symbol, n, bar_size, asset_type='STOCK', end_time=None):
        """
        Internal: fetch N bars from IB with optional endDateTime offset.
        """
        # Map TF to seconds per bar
        TF_SECONDS = {
            '1 min': 60, '5 mins': 300, '15 mins': 900,
            '30 mins': 1800, '1 hour': 3600, '1 day': 86400
        }
        secs_per_bar = TF_SECONDS.get(bar_size, 300)
        # Calculate duration with 2x buffer for gaps/weekends
        total_secs = n * secs_per_bar * 2
        if total_secs < 86400:
            duration_str = f"{int(total_secs)} S"
        else:
            duration_str = f"{int(total_secs / 86400) + 1} D"

        ib = IB()
        try:
            print(f"[HIST-N] _fetch_n_bars_fresh START: {symbol} ({asset_type}) n={n} bar_size={bar_size} duration={duration_str}")
            self._connect_with_retry(ib)
            ib.reqMarketDataType(4)
            contract = create_contract(symbol, asset_type)
            ib.qualifyContracts(contract)
            print(f"[HIST-N] Contract OK: conId={contract.conId}")

            # Build endDateTime string for IB
            if end_time:
                end_dt = datetime.fromtimestamp(end_time)
                end_dt_str = end_dt.strftime('%Y%m%d %H:%M:%S')
            else:
                end_dt_str = ''

            use_rth = use_regular_trading_hours(asset_type)
            print(f"[HIST-N] Calling reqHistoricalData timeout=30 useRTH={use_rth}...")
            bars = ib.reqHistoricalData(
                contract, endDateTime=end_dt_str, durationStr=duration_str,
                barSizeSetting=bar_size,
                whatToShow=get_history_what_to_show(asset_type),
                useRTH=use_rth, formatDate=1, timeout=30
            )
            print(f"[HIST-N] reqHistoricalData returned {len(bars) if bars else 0} bars")
            # Convert and sort by time
            result = [{
                'time':   _bar_date_to_unix(b.date),
                'open':   b.open, 'high': b.high,
                'low':    b.low,  'close': b.close,
                'volume': b.volume
            } for b in bars]
            result.sort(key=lambda x: x['time'])
            # Return exactly N bars (or less if not available)
            if len(result) > n:
                result = result[-n:]
            print(f"[HIST] fetch_n_bars: {len(result)} bars for {symbol} ({asset_type}) | end_time={end_time} | duration={duration_str}")
            
            # Save to data_store so indicators can use it
            if result:
                from modules.data_store import data_store
                cache_symbol = get_cache_symbol(symbol, asset_type)
                data_store.append_bars(cache_symbol, bar_size, result)
                
            return result
        finally:
            try: ib.disconnect()
            except Exception: pass


def _bar_date_to_unix(bar_date):
    if hasattr(bar_date, 'timestamp'):
        return int(bar_date.timestamp())
    if isinstance(bar_date, str):
        clean = bar_date.split(' US/')[0].split(' America/')[0].strip()
        fmt   = '%Y%m%d' if len(clean) == 8 else '%Y%m%d %H:%M:%S'
        return int(datetime.strptime(clean, fmt).timestamp())
    return int(datetime.now().timestamp())


# ================================================================
# IBConnector
# ================================================================

_ORDER_SUCCESS_STATUSES = frozenset({
    'Submitted', 'Filled', 'PreSubmitted', 'PendingSubmit'
})
_ORDER_TERMINAL_STATUSES = frozenset({
    'Submitted', 'Filled', 'PreSubmitted', 'PendingSubmit',
    'Cancelled', 'Inactive', 'ApiCancelled'
})


class IBConnector:
    def __init__(self):
        self.ib         = IB()
        self.connected  = False
        self.account_id = None
        self.tickers    = {}
        self.contracts  = {}
        self.executions = []

        # Thread-safe positions cache
        # Aktualizovana _positions_bg_loop (vlastni IB instance, clientId+3)
        self._positions_cache: list = []
        self._positions_lock        = threading.Lock()

        self._hist_worker = _HistWorker(
            host=config.IB_HOST, port=config.IB_PORT,
            client_id=config.IB_CLIENT_ID + 1
        )
        self._tick_sub = _TickSubscriber(
            host=config.IB_HOST, port=config.IB_PORT,
            client_id=config.IB_CLIENT_ID + 2
        )

    # ------------------------------------------------------------------
    # Background position polling — KLIC v2.9.4
    # ------------------------------------------------------------------

    def _positions_bg_loop(self):
        """
        Background thread s VLASTNI IB() instanci (clientId+3).

        Proc separatni instance?
          ib_async pouziva asyncio event loop. Kazde volani ib.sleep() musi
          beznout v threadu ktery loop vlastni (= thread kde bylo volano
          ib.connect()). Pokud bg thread pouziva self.ib.sleep(), spousti
          JINY loop -> IB zpravy se nezpracuji -> positions zustavaji prazdne.

          Reseni: bg thread ma svoji IB instanci kterou sam pripoji.
          ib_poll.sleep() pak korektne pumpuje JEJI loop -> reqPositions()
          vraci spravna data.
        """
        poll_cid = config.IB_CLIENT_ID + 3
        print(f"[POS-BG] Position poll thread started (clientId={poll_cid}, interval=3s)")
        ib_poll = IB()

        while True:
            time.sleep(3)

            if not self.connected:
                if ib_poll.isConnected():
                    try: ib_poll.disconnect()
                    except Exception: pass
                continue

            try:
                # Pripoj poll instanci kdyz je odpojena
                if not ib_poll.isConnected():
                    connected_bg = False
                    for offset in range(10):
                        cid_try = poll_cid + offset
                        try:
                            print(f"[POS-BG] Connecting poll IB (clientId={cid_try})...")
                            ib_poll.connect(
                                config.IB_HOST, config.IB_PORT,
                                clientId=cid_try, timeout=5
                            )
                            print(f"[POS-BG] Poll IB connected (clientId={cid_try})")
                            connected_bg = True
                            break
                        except Exception as e:
                            err_str = str(e)
                            is_conflict = 'TimeoutError' in type(e).__name__ or 'TimeoutError' in err_str or '326' in err_str
                            if is_conflict:
                                print(f"[POS-BG] clientId={cid_try} in use, trying {cid_try+1}...")
                                try: ib_poll.disconnect()
                                except: pass
                                time.sleep(0.3)
                                continue
                            raise
                    if not connected_bg:
                        continue

                # Pozadej aktualni pozice + pumpni JEJI event loop pro odpoved
                ib_poll.reqPositions()   # posli zadost na IB server
                ib_poll.sleep(1.0)       # zpracuj odpoved (OK: tento thread vlastni ib_poll)

                raw    = ib_poll.positions()
                result = []
                for pos in raw:
                    if pos.position == 0:
                        continue
                    sym        = get_display_symbol_from_contract(pos.contract)
                    asset_type = asset_type_from_contract(pos.contract)
                    cp         = self._tick_sub.get_price(sym, asset_type) or pos.avgCost
                    mv   = pos.position * cp
                    cb   = pos.position * pos.avgCost
                    upnl = mv - cb
                    result.append({
                        'symbol':             sym,
                        'asset_type':         asset_type,
                        'position':           pos.position,
                        'avg_cost':           pos.avgCost,
                        'market_price':       cp,
                        'market_value':       mv,
                        'unrealized_pnl':     upnl,
                        'unrealized_pnl_pct': (upnl / abs(cb) * 100) if cb else 0
                    })

                prev_syms = {p['symbol'] for p in self._positions_cache}
                new_syms  = {p['symbol'] for p in result}
                with self._positions_lock:
                    self._positions_cache = result

                if prev_syms != new_syms:
                    print(f"[POS-BG] \U0001f4ca Cache ZMENENA: {prev_syms} -> {new_syms} | {len(result)} pozic")

            except Exception as e:
                print(f"[POS-BG] Error: {e}")
                try: ib_poll.disconnect()
                except Exception: pass

    # ------------------------------------------------------------------
    # Connect / disconnect
    # ------------------------------------------------------------------

    def connect(self):
        try:
            if config.DEBUG_CONNECTION:
                print("=" * 60)
                print(f"\U0001f4e1 CONNECTING | {config.CONNECTION_LABEL}")
                print(f"Host={config.IB_HOST} Port={config.IB_PORT} ClientId={config.IB_CLIENT_ID}")
                print("=" * 60)
            base_cid = config.IB_CLIENT_ID
            connected_main = False
            for offset in range(10):
                cid_try = base_cid + offset
                try:
                    self.ib.connect(
                        config.IB_HOST, config.IB_PORT,
                        clientId=cid_try, timeout=20
                    )
                    if offset > 0:
                        print(f"[CONN] Connected with fallback clientId={cid_try} (base={base_cid})")
                    connected_main = True
                    break
                except Exception as e:
                    err_str = str(e)
                    is_conflict = 'TimeoutError' in type(e).__name__ or 'TimeoutError' in err_str or '326' in err_str
                    if is_conflict:
                        print(f"[CONN] clientId={cid_try} in use (Error 326), trying {cid_try+1}...")
                        try: self.ib.disconnect()
                        except: pass
                        time.sleep(0.5)
                        continue
                    raise
            if not connected_main:
                raise RuntimeError(f"Cannot connect to IB: all clientIds {base_cid}–{base_cid+9} in use")
            self.connected  = True
            accounts        = self.ib.managedAccounts()
            self.account_id = accounts[0] if accounts else None
            self.ib.reqMarketDataType(4)

            # Nacti existujici pozice hned po spojeni (sync, OK: jsme v main threadu)
            self._refresh_positions_from_main()

            # Spust background poll thread (vlastni IB instance)
            threading.Thread(
                target=self._positions_bg_loop,
                daemon=True,
                name='IB-PosBG'
            ).start()

            try:
                self.executions = self.ib.reqExecutions()
            except Exception as e:
                print(f"\u26a0\ufe0f Executions: {e}")
            print(f"\u2705 Connected | Account: {self.account_id}")
            return True
        except Exception as e:
            print(f"\u274c Connection failed: {e}")
            self.connected = False
            return False

    def _refresh_positions_from_main(self):
        """
        Sync refresh z main threadu (pri connect).
        Muze pouzivat self.ib.sleep() protoze main thread vlastni self.ib.
        """
        try:
            self.ib.reqPositions()
            self.ib.sleep(1.0)
            raw    = self.ib.positions()
            result = []
            for pos in raw:
                if pos.position == 0:
                    continue
                sym        = get_display_symbol_from_contract(pos.contract)
                asset_type = asset_type_from_contract(pos.contract)
                cp         = self._tick_sub.get_price(sym, asset_type) or pos.avgCost
                mv   = pos.position * cp
                cb   = pos.position * pos.avgCost
                upnl = mv - cb
                result.append({
                    'symbol':             sym,
                    'asset_type':         asset_type,
                    'position':           pos.position,
                    'avg_cost':           pos.avgCost,
                    'market_price':       cp,
                    'market_value':       mv,
                    'unrealized_pnl':     upnl,
                    'unrealized_pnl_pct': (upnl / abs(cb) * 100) if cb else 0
                })
            with self._positions_lock:
                self._positions_cache = result
            print(f"[POS] Initial load: {len(result)} pozic | {[p['symbol'] for p in result]}")
        except Exception as e:
            print(f"\u26a0\ufe0f _refresh_positions_from_main: {e}")

    def disconnect(self):
        if self.connected:
            self.ib.disconnect()
            self.connected = False

    def is_connected(self):
        return self.connected and self.ib.isConnected()

    # ------------------------------------------------------------------
    # Ticker / price
    # ------------------------------------------------------------------

    def get_ticker(self, symbol, asset_type='STOCK'):
        if not self.is_connected(): return None
        asset_type = normalize_asset_type(asset_type)
        sym = sanitize_symbol(symbol, asset_type)
        self._tick_sub.subscribe(sym, asset_type)
        data = self._tick_sub.get_ticker_data(sym, asset_type)
        if data: return data
        return {'price': 0, 'last': 0, 'bid': 0, 'ask': 0, 'close': 0, 'volume': 0, 'asset_type': asset_type}

    def get_latest_price(self, symbol, asset_type='STOCK'):
        if not self.is_connected(): return 0.0
        asset_type = normalize_asset_type(asset_type)
        sym = sanitize_symbol(symbol, asset_type)
        self._tick_sub.set_primary_subscription(sym, asset_type)
        return self._tick_sub.get_price(sym, asset_type)

    # ------------------------------------------------------------------
    # Historical data
    # ------------------------------------------------------------------

    def get_historical_data(self, symbol, duration='1 D', bar_size='5 mins', asset_type='STOCK'):
        if not self.is_connected(): return []
        asset_type = normalize_asset_type(asset_type)
        sym = sanitize_symbol(symbol, asset_type)
        cache_symbol = get_cache_symbol(sym, asset_type)
        self._tick_sub.set_primary_subscription(sym, asset_type)
        status = data_store.get_cache_status(cache_symbol, bar_size)
        if status['cached'] and status['is_fresh']:
            print(f"[CACHE] HIT: {sym} ({asset_type}) | {bar_size} | {status['total_bars']} bars | FRESH")
            return data_store.get_bars(cache_symbol, bar_size)
        fetch_duration = duration
        if status['cached'] and status['age_seconds'] < 86400 * 7:
            missing_sec    = status['age_seconds']
            fetch_duration = f"{int(missing_sec + 3600)} S"
            print(f"[CACHE] INCR: {sym} ({asset_type}) | {bar_size} | {status['total_bars']} bars existuji | Dotahuji chybejicich {fetch_duration}")
        else:
            print(f"[CACHE] MISS/STALE: {sym} ({asset_type}) | {bar_size} | Stahuji celou defaultni delku: {duration}")
        new_bars = self._hist_worker.fetch(sym, fetch_duration, bar_size, asset_type)
        if new_bars:
            data_store.append_bars(cache_symbol, bar_size, new_bars)
        return data_store.get_bars(cache_symbol, bar_size)

    def get_deep_load_status(self, symbol, timeframe, asset_type='STOCK'):
        asset_type = normalize_asset_type(asset_type)
        sym = sanitize_symbol(symbol, asset_type)
        return self._hist_worker.get_deep_load_status().get(f"{asset_type}:{sym}_{timeframe}", {'status': 'idle'})

    def start_deep_load(self, symbol, timeframe, asset_type='STOCK'):
        return self._hist_worker.start_deep_load(symbol, timeframe, asset_type)

    def get_n_bars(self, symbol, n, bar_size='5 mins', asset_type='STOCK', end_time=None):
        """
        Fetch exactly N bars from IB (bypassing cache).
        If end_time is provided (Unix timestamp), fetch bars ending at that time.
        Used for incremental chart loading.
        """
        if not self.is_connected(): return []
        asset_type = normalize_asset_type(asset_type)
        sym = sanitize_symbol(symbol, asset_type)
        self._tick_sub.set_primary_subscription(sym, asset_type)
        return self._hist_worker.fetch_n_bars(sym, n, bar_size, asset_type, end_time)

    # ------------------------------------------------------------------
    # Account
    # ------------------------------------------------------------------

    def get_account_info(self):
        if not self.is_connected(): return {}
        try:
            info = {'account_id': self.account_id,
                    'net_liquidation': 0, 'buying_power': 0, 'cash_balance': 0}
            for av in self.ib.accountValues():
                if av.tag == 'NetLiquidation' and av.currency == 'USD':
                    info['net_liquidation'] = float(av.value)
                elif av.tag == 'BuyingPower' and av.currency == 'USD':
                    info['buying_power'] = float(av.value)
                elif av.tag == 'CashBalance' and av.currency == 'USD':
                    info['cash_balance'] = float(av.value)
            return info
        except Exception as e:
            print(f"\u274c account info: {e}"); return {}

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    def place_order(self, symbol, action, quantity, order_type='MARKET',
                    limit_price=None, timeout=None, asset_type='STOCK'):
        """
        Odesle order. self.ib.sleep() je OK protoze place_order() bezi
        v main/Flask threadu ktery vlastni self.ib.
        (bg thread pouziva ib_poll -> zadny konflikt)
        """
        if not self.is_connected():
            return {'success': False, 'error': 'Not connected to IB'}
        if timeout is None:
            timeout = config.ORDER_TIMEOUT
        try:
            asset_type = normalize_asset_type(asset_type)
            contract = create_contract(symbol, asset_type)
            qualified = self.ib.qualifyContracts(contract)
            if qualified:
                contract = qualified[0]
            print(f"  [ORDER] Contract: {sanitize_symbol(symbol, asset_type)} ({asset_type})")
            order    = (LimitOrder(action, quantity, limit_price)
                        if order_type == 'LIMIT' else MarketOrder(action, quantity))
            order.transmit   = True
            order.outsideRth = True
            trade = self.ib.placeOrder(contract, order)

            start       = time.time()
            last_status = None
            while time.time() - start < timeout:
                self.ib.sleep(1)
                cs = trade.orderStatus.status
                if cs != last_status:
                    print(f"  [ORDER] {symbol} {action} {quantity} -> {cs}")
                    last_status = cs
                if cs in _ORDER_TERMINAL_STATUSES:
                    break

            fs  = trade.orderStatus.status
            oid = trade.order.orderId if trade.order else None
            print(f"  [ORDER] Final status: {fs} | orderId={oid}")

            if fs in _ORDER_SUCCESS_STATUSES:
                fill_price = trade.orderStatus.avgFillPrice or 0.0
                return {
                    'success':    True,
                    'order_id':   oid,
                    'status':     fs,
                    'filled':     trade.orderStatus.filled,
                    'remaining':  trade.orderStatus.remaining,
                    'fill_price': fill_price,
                    'error':      None
                }

            msgs = [
                f"Error {e.errorCode}: {e.message}"
                for e in (trade.log or [])
                if e.errorCode and e.errorCode < 2000
            ]
            return {
                'success':  False,
                'order_id': oid,
                'status':   fs,
                'error':    f"Order failed: {fs}" + (
                    "\n" + "\n".join(msgs) if msgs else ''
                )
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def place_market_order(self, symbol, action, quantity):
        return self.place_order(symbol, action, quantity, 'MARKET')

    # ------------------------------------------------------------------
    # Positions
    # ------------------------------------------------------------------

    def get_positions(self):
        """
        Thread-safe cteni z cache.
        Cache je aktualizovana _positions_bg_loop kazdych ~4s
        (3s sleep + 1s ib_poll.sleep pro zpracovani IB odpovedi).
        """
        with self._positions_lock:
            return list(self._positions_cache)

    # ------------------------------------------------------------------
    # Avg cost from executions (fill_price + commission/shares)
    # ------------------------------------------------------------------

    def get_fill_avg_cost(self, symbol: str, asset_type: str = 'STOCK'):
        """Return (avg_cost, commission) for the most recent fill of symbol.

        Uses fresh reqExecutions() so the result is always up-to-date.
        avg_cost = fill.execution.price + commission / shares  (IB convention)
        Returns (None, None) when no fill is found or connector is not connected.
        """
        if not self.is_connected():
            return None, None
        try:
            fills = self.ib.reqExecutions()
            asset_type = normalize_asset_type(asset_type)
            # Walk in reverse so we get the *latest* fill first
            for fill in reversed(fills):
                sym = get_display_symbol_from_contract(fill.contract)
                at  = asset_type_from_contract(fill.contract)
                if sym == symbol and at == asset_type:
                    ed         = fill.execution
                    commission = getattr(fill.commissionReport, 'commission', 0.0) or 0.0
                    shares     = ed.shares or 1
                    avg_cost   = round(ed.price + commission / shares, 6)
                    print(f'[FILL] avg_cost for {sym}: fill_price={ed.price}'
                          f' commission={commission} shares={shares} avg_cost={avg_cost}')
                    return avg_cost, commission
        except Exception as e:
            print(f'[FILL] get_fill_avg_cost error: {e}')
        return None, None

    # ------------------------------------------------------------------
    # Recent orders
    # ------------------------------------------------------------------

    def get_recent_orders(self, limit=10):
        if not self.is_connected(): return []
        try:
            print('[ORDERS] get_recent_orders — calling reqExecutions to refresh fills')
            self.executions = self.ib.reqExecutions()
            result = []
            for fill in self.executions[-limit:]:
                ed = fill.execution
                contract = fill.contract
                result.append({
                    'time':     (ed.time.strftime('%H:%M')
                                 if hasattr(ed.time, 'strftime') else str(ed.time)[:5]),
                    'symbol':   get_display_symbol_from_contract(contract),
                    'asset_type': asset_type_from_contract(contract),
                    'action':   ed.side,
                    'quantity': ed.shares,
                    'price':    f"${ed.price:.2f}",
                    'status':   'Filled'
                })
            for trade in self.ib.trades():
                if trade.orderStatus.status == 'Filled': continue
                o = trade.order; s = trade.orderStatus
                contract = trade.contract
                result.append({
                    'time':     datetime.now().strftime('%H:%M'),
                    'symbol':   get_display_symbol_from_contract(contract),
                    'asset_type': asset_type_from_contract(contract),
                    'action':   o.action,
                    'quantity': o.totalQuantity,
                    'price':    'Market' if o.orderType == 'MKT' else f"Limit ${o.lmtPrice:.2f}",
                    'status':   s.status
                })
            return result[::-1][-limit:]
        except Exception as e:
            print(f"\u274c orders: {e}"); return []

    def __del__(self):
        self.disconnect()

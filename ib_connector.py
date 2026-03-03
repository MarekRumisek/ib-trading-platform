"""IB API Connector using ib_async

Version: 2.9.2 - thread-safe positions

HIERARCHIE FALLBACKU:
  1. STREAMING   reqMktData(snapshot=False)  -> okamzity update
  2. SNAPSHOT    reqTickersAsync()           -> kazdych 15s
  3. HIST_POLL   reqHistoricalDataAsync()    -> kazdych 30s, mdt=4, useRTH=True

Error 10089 -> okamzity skok na hist_poll.
Error 162   -> bylo zpusobeno useRTH=False + 300S (prilis kratka doba).
               Fixnuto: mdt=4 pred hist dotazem, useRTH=True, duration 3600S.

v2.9.1 zmeny:
  - place_order: PendingSubmit je platny stav -> success=True
v2.9.2 zmeny:
  - get_positions: odstranen reqPositions()+sleep() - NENI thread-safe v Flask threadech
    ib.positions() vraci IB-managed cache, ktera se automaticky aktualizuje pri fillovani
  - _positions_cache: background thread pravidelne refreshuje pozice pres IB event loop
"""

from ib_async import IB, Stock, MarketOrder, LimitOrder
from datetime import datetime, timedelta
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
        self._last_errors: list = []
        self._lock             = threading.Lock()
        self._connected: bool  = False
        self._iterations: int  = 0
        self._mdt: int         = 0
        self._mode: str        = 'init'
        self._next_hist_poll: int = 0

        self._thread = threading.Thread(
            target=self._run, daemon=True,
            name=f'IB-TickSub-cid{client_id}'
        )
        self._thread.start()
        print(f"[TICK-SUB] Worker spusten (clientId={client_id})")

    # --- verejne API ---

    def get_price(self, symbol: str) -> float:
        return float(self._latest.get(symbol.upper(), {}).get('price', 0.0))

    def get_ticker_data(self, symbol: str):
        info = self._latest.get(symbol.upper())
        if not info or info.get('price', 0) <= 0:
            return None
        return info.copy()

    def get_raw_data(self, symbol: str) -> dict:
        sym    = symbol.upper()
        ticker = self._tickers.get(sym)
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

    def subscribe(self, symbol: str):
        with self._lock:
            self._pending.add(symbol.upper())

    @property
    def is_connected(self) -> bool: return self._connected
    @property
    def iterations(self) -> int: return self._iterations
    @property
    def subscribed_symbols(self) -> list: return list(self._tickers.keys())
    @property
    def mode(self) -> str: return self._mode

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
            print(f"[TICK-SUB] connectAsync clientId={self._client_id}...")
            await ib.connectAsync(self._host, self._port, clientId=self._client_id)
            print(f"[TICK-SUB] Pripojeno! clientId={self._client_id}")

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
                    new_syms = list(self._pending - set(contracts_local.keys()))
                    self._pending.clear()

                for sym in new_syms:
                    try:
                        contract = Stock(sym, 'SMART', 'USD')
                        await ib.qualifyContractsAsync(contract)
                        contracts_local[sym] = contract
                        print(f"[TICK-SUB] Contract OK: {sym} conId={contract.conId}")

                        if self._mode == 'streaming':
                            ticker = ib.reqMktData(contract, '', False, False)
                            tickers_local[sym] = ticker

                            def make_handler(s):
                                def on_ticker(t):
                                    p = self._extract_price(t)
                                    if p > 0:
                                        self._latest[s] = self._make_latest(t, p)
                                return on_ticker
                            ticker.updateEvent += make_handler(sym)
                            print(f"[TICK-SUB] STREAM {sym}")

                        elif self._mode == 'hist_poll':
                            self._next_hist_poll = self._iterations
                            print(f"[TICK-SUB] HIST_POLL {sym} (zadna mkt sub potreba)")

                    except Exception as e:
                        print(f"[TICK-SUB] Subscribe error {sym}: {e}")
                        with self._lock:
                            self._pending.add(sym)

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
                    for sym, t in list(tickers_local.items()):
                        if self._latest.get(sym, {}).get('price', 0) <= 0:
                            p = self._extract_price(t)
                            if p > 0:
                                self._latest[sym] = self._make_latest(t, p)

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
                    for sym, contract in list(contracts_local.items()):
                        try:
                            snaps = await ib.reqTickersAsync(contract)
                            if snaps:
                                t = snaps[0]
                                p = self._extract_price(t)
                                if p > 0:
                                    self._latest[sym] = self._make_latest(t, p)
                                    print(f"[TICK-SUB] SNAP {sym}: p={p}")
                        except Exception as e:
                            print(f"[TICK-SUB] Snapshot err {sym}: {e}")

                    if self._has_error(10089):
                        print("[TICK-SUB] Snapshot 10089 -> HIST_POLL")
                        self._mode           = 'hist_poll'
                        self._mdt            = 99
                        self._next_hist_poll = self._iterations

                elif self._mode == 'hist_poll' and self._iterations >= self._next_hist_poll:
                    self._next_hist_poll = self._iterations + 30
                    ib.reqMarketDataType(4)

                    for sym, contract in list(contracts_local.items()):
                        try:
                            bars = await ib.reqHistoricalDataAsync(
                                contract,
                                endDateTime='',
                                durationStr='3600 S',
                                barSizeSetting='1 min',
                                whatToShow='TRADES',
                                useRTH=True,
                                formatDate=1
                            )
                            if bars:
                                price = float(bars[-1].close)
                                bar_t = bars[-1].date
                                self._latest[sym] = {
                                    'price':  price,
                                    'last':   price,
                                    'close':  float(bars[-2].close) if len(bars) > 1 else price,
                                    'bid':    0.0,
                                    'ask':    0.0,
                                    'volume': int(bars[-1].volume) if bars[-1].volume else 0,
                                    'mdt':    99,
                                    'mode':   'hist_poll',
                                    'bar_time': str(bar_t),
                                    'iterations': self._iterations,
                                    'ts': time.time()
                                }
                                print(
                                    f"[TICK-SUB] HIST_POLL {sym}: "
                                    f"close={price:.2f}  bar={bar_t}  "
                                    f"({len(bars)} bars)"
                                )
                            else:
                                print(f"[TICK-SUB] HIST_POLL {sym}: stale prazdne, retry za 5s")
                                self._next_hist_poll = self._iterations + 5
                        except Exception as e:
                            print(f"[TICK-SUB] HIST_POLL err {sym}: {e}")
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

    def start_deep_load(self, symbol, timeframe):
        key = f"{symbol}_{timeframe}"
        if self._deep_load_status.get(key, {}).get('status') == 'running':
            return False
        self._deep_load_status[key] = {'progress': '0%', 'status': 'running', 'msg': 'Inicializace...'}
        self._queue.put(('deep_load', symbol, timeframe, key, None, None))
        return True

    def fetch(self, symbol, duration='1 D', bar_size='5 mins', timeout=15):
        result, done = [], threading.Event()
        self._queue.put(('fetch', symbol, duration, bar_size, result, done))
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
                _, symbol, duration, bar_size, result, done = item
                try:
                    bars = self._fetch_fresh(symbol, duration, bar_size)
                    result.extend(bars)
                except Exception as e:
                    print(f"[HIST] Chyba pro {symbol}: {e}")
                finally:
                    done.set()
            elif cmd == 'deep_load':
                _, symbol, timeframe, key, _, _ = item
                try:
                    self._run_deep_load(symbol, timeframe, key)
                except Exception as e:
                    self._deep_load_status[key] = {'progress': 'ERROR', 'status': 'error', 'msg': str(e)}

    def _run_deep_load(self, symbol, timeframe, key):
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
            contract = Stock(symbol, 'SMART', 'USD')
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
                    barSizeSetting=timeframe, whatToShow='TRADES',
                    useRTH=True, formatDate=1, timeout=30
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
                data_store.append_bars(symbol, timeframe, result)
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

    def _fetch_fresh(self, symbol, duration, bar_size):
        ib = IB()
        try:
            ib.connect(self._host, self._port,
                       clientId=self._client_id, timeout=10)
            ib.reqMarketDataType(4)
            contract = Stock(symbol, 'SMART', 'USD')
            ib.qualifyContracts(contract)
            bars = ib.reqHistoricalData(
                contract, endDateTime='', durationStr=duration,
                barSizeSetting=bar_size, whatToShow='TRADES',
                useRTH=True, formatDate=1, timeout=12
            )
            result = [{
                'time':   _bar_date_to_unix(b.date),
                'open':   b.open, 'high': b.high,
                'low':    b.low,  'close': b.close,
                'volume': b.volume
            } for b in bars]
            print(f"[HIST] OK: {len(result)} baru pro {symbol}")
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

# Stavy orderu IB ktere znamenaji uspesne odeslani
_ORDER_SUCCESS_STATUSES = frozenset({
    'Submitted', 'Filled', 'PreSubmitted', 'PendingSubmit'
})
# Stavy ktere ukonci cekani v place_order loop
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

        # Thread-safe positions cache — aktualizovana z IB event-loop threadu
        self._positions_cache: list  = []
        self._positions_lock         = threading.Lock()

        self._hist_worker = _HistWorker(
            host=config.IB_HOST, port=config.IB_PORT,
            client_id=config.IB_CLIENT_ID + 1
        )
        self._tick_sub = _TickSubscriber(
            host=config.IB_HOST, port=config.IB_PORT,
            client_id=config.IB_CLIENT_ID + 2
        )

    def connect(self):
        try:
            if config.DEBUG_CONNECTION:
                print("=" * 60)
                print(f"📡 CONNECTING | {config.CONNECTION_LABEL}")
                print(f"Host={config.IB_HOST} Port={config.IB_PORT} ClientId={config.IB_CLIENT_ID}")
                print("=" * 60)
            self.ib.connect(
                config.IB_HOST, config.IB_PORT,
                clientId=config.IB_CLIENT_ID, timeout=20
            )
            self.connected  = True
            accounts        = self.ib.managedAccounts()
            self.account_id = accounts[0] if accounts else None
            self.ib.reqMarketDataType(4)

            # Registruj position event handler — aktualizuje cache kdykoli IB posle update
            self.ib.positionEvent += self._on_position_event

            # Nacti existujici pozice hned po spojeni (bezpecne - jsme v IB threadu)
            self._refresh_positions_cache()

            try:
                self.executions = self.ib.reqExecutions()
            except Exception as e:
                print(f"⚠️ Executions: {e}")
            print(f"✅ Connected | Account: {self.account_id}")
            return True
        except Exception as e:
            print(f"❌ Connection failed: {e}")
            self.connected = False
            return False

    def _refresh_positions_cache(self):
        """Vola se POUZE z IB event loop threadu (connect, positionEvent)."""
        try:
            raw = self.ib.positions()
            result = []
            for pos in raw:
                if pos.position == 0:
                    continue
                sym  = pos.contract.symbol
                cp   = self._tick_sub.get_price(sym) or pos.avgCost
                mv   = pos.position * cp
                cb   = pos.position * pos.avgCost
                upnl = mv - cb
                result.append({
                    'symbol':             sym,
                    'position':           pos.position,
                    'avg_cost':           pos.avgCost,
                    'market_price':       cp,
                    'market_value':       mv,
                    'unrealized_pnl':     upnl,
                    'unrealized_pnl_pct': (upnl / abs(cb) * 100) if cb else 0
                })
            with self._positions_lock:
                self._positions_cache = result
            print(f"[POS] Cache refresh: {len(result)} pozic")
        except Exception as e:
            print(f"⚠️ _refresh_positions_cache: {e}")

    def _on_position_event(self, account, contract, position, avgCost):
        """Callback z IB event loop — aktualizuje cache po kazde zmene pozice."""
        self._refresh_positions_cache()

    def disconnect(self):
        if self.connected:
            self.ib.disconnect()
            self.connected = False

    def is_connected(self):
        return self.connected and self.ib.isConnected()

    def get_ticker(self, symbol):
        if not self.is_connected(): return None
        sym = symbol.upper()
        self._tick_sub.subscribe(sym)
        data = self._tick_sub.get_ticker_data(sym)
        if data: return data
        return {'price': 0, 'last': 0, 'bid': 0, 'ask': 0, 'close': 0, 'volume': 0}

    def get_latest_price(self, symbol):
        if not self.is_connected(): return 0.0
        sym = symbol.upper()
        self._tick_sub.subscribe(sym)
        return self._tick_sub.get_price(sym)

    def get_historical_data(self, symbol, duration='1 D', bar_size='5 mins'):
        if not self.is_connected(): return []
        sym = symbol.upper()
        self._tick_sub.subscribe(sym)

        status = data_store.get_cache_status(sym, bar_size)

        if status['cached'] and status['is_fresh']:
            print(f"[CACHE] HIT: {sym} | {bar_size} | {status['total_bars']} bars | FRESH")
            return data_store.get_bars(sym, bar_size)

        fetch_duration = duration
        if status['cached'] and status['age_seconds'] < 86400 * 7:
            missing_sec    = status['age_seconds']
            fetch_duration = f"{int(missing_sec + 3600)} S"
            print(f"[CACHE] INCR: {sym} | {bar_size} | {status['total_bars']} bars existuji | Dotahuji chybejicich {fetch_duration}")
        else:
            print(f"[CACHE] MISS/STALE: {sym} | {bar_size} | Stahuji celou defaultni delku: {duration}")

        new_bars = self._hist_worker.fetch(sym, fetch_duration, bar_size)
        if new_bars:
            data_store.append_bars(sym, bar_size, new_bars)
        return data_store.get_bars(sym, bar_size)

    def get_deep_load_status(self, symbol, timeframe):
        return self._hist_worker.get_deep_load_status().get(f"{symbol}_{timeframe}", {'status': 'idle'})

    def start_deep_load(self, symbol, timeframe):
        return self._hist_worker.start_deep_load(symbol, timeframe)

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
            print(f"❌ account info: {e}"); return {}

    def place_order(self, symbol, action, quantity, order_type='MARKET',
                    limit_price=None, timeout=None):
        """
        Odesle order do IB a ceka na potvrzeni.

        Stavy IB orderu:
          PendingSubmit  -> TWS prijal order, posilaji na exchange
          PreSubmitted   -> ceka na potvrzeni odeslani
          Submitted      -> exchange potvrdila prijeti
          Filled         -> zaplneno

        FIX v2.9.1: PendingSubmit je platny stav = order byl uspesne oddan do IB.
        """
        if not self.is_connected():
            return {'success': False, 'error': 'Not connected to IB'}
        if timeout is None:
            timeout = config.ORDER_TIMEOUT
        try:
            contract = Stock(symbol, 'SMART', 'USD')
            order    = (LimitOrder(action, quantity, limit_price)
                        if order_type == 'LIMIT' else MarketOrder(action, quantity))
            order.transmit     = True
            order.outsideRth   = True
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

    def get_positions(self):
        """
        Thread-safe cteni pozic z cache.
        Cache je aktualizovana z IB event loop threadu (positionEvent + connect).
        Zadne async volani zde -> bezpecne z Flask request threadu.
        """
        with self._positions_lock:
            return list(self._positions_cache)

    def get_recent_orders(self, limit=10):
        if not self.is_connected(): return []
        try:
            result = []
            for fill in self.executions[-limit:]:
                ed = fill.execution
                result.append({
                    'time':     (ed.time.strftime('%H:%M')
                                 if hasattr(ed.time, 'strftime') else str(ed.time)[:5]),
                    'symbol':   fill.contract.symbol,
                    'action':   ed.side,
                    'quantity': ed.shares,
                    'price':    f"${ed.price:.2f}",
                    'status':   'Filled'
                })
            for trade in self.ib.trades():
                if trade.orderStatus.status == 'Filled': continue
                o = trade.order; s = trade.orderStatus
                result.append({
                    'time':     datetime.now().strftime('%H:%M'),
                    'symbol':   trade.contract.symbol,
                    'action':   o.action,
                    'quantity': o.totalQuantity,
                    'price':    'Market' if o.orderType == 'MKT' else f"Limit ${o.lmtPrice:.2f}",
                    'status':   s.status
                })
            return result[::-1][-limit:]
        except Exception as e:
            print(f"❌ orders: {e}"); return []

    def __del__(self):
        self.disconnect()

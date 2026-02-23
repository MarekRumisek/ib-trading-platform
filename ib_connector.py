"""IB API Connector using ib_async

Version: 2.4.0 - _TickSubscriber diagnostics + bid/ask price fallback

ARCHITEKTURA:
  self.ib          (clientId=1) -- hlavni spojeni: orders, account, positions
  _HistWorker      (clientId=2) -- hist. data, fresh conn per request
  _TickSubscriber  (clientId=3) -- streaming tick data, bezi porad

PRICE EXTRACTION ORDER:
  1. ticker.last   (posledni obchod)
  2. ticker.close  (predchozi close)
  3. ticker.bid    (aktualni nabidka)
  4. ticker.ask    (aktualni pozadavek)
  -> midpoint bid/ask jako posledni moznost
"""

from ib_async import IB, Stock, MarketOrder, LimitOrder
from datetime import datetime
import config
import time
import threading
import queue
import asyncio


# ================================================================
# _TickSubscriber - Streaming delayed market data (clientId=3)
# ================================================================

class _TickSubscriber:
    """Dedikované vlakno pro STREAMING market data.

    reqMarketDataType(3) = Delayed streaming.
    Price fallback: last -> close -> bid -> ask -> midpoint.
    Diagnostika: get_raw_data(symbol) vrati vsechna pole z IB tickeru.
    """

    def __init__(self, host, port, client_id):
        self._host        = host
        self._port        = port
        self._client_id   = client_id
        self._latest: dict    = {}     # sym -> {price, last, close, bid, ask, volume, ts}
        self._tickers: dict   = {}     # sym -> raw ib_async Ticker (pro diagnostiku)
        self._pending: set    = set()  # symboly cekajici na subscribe
        self._lock            = threading.Lock()
        self._connected: bool = False
        self._iterations: int = 0      # pocet dokoncených sleep(1.0) cyklu
        self._mdt: int        = 0      # aktual. reqMarketDataType

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
        """Diagnostika - vsechna surova pole z ib_async Tickeru."""
        sym = symbol.upper()
        ticker = self._tickers.get(sym)
        if not ticker:
            return {
                'error': 'not_subscribed',
                'subscribed': list(self._tickers.keys()),
                'pending': list(self._pending)
            }

        def safe(v):
            if v is None: return None
            try:
                if isinstance(v, float) and v != v: return 'NaN'
                return v
            except Exception:
                return str(v)

        fields = {
            'last':       safe(ticker.last),
            'lastSize':   safe(ticker.lastSize),
            'prevLast':   safe(getattr(ticker, 'prevLast', None)),
            'close':      safe(ticker.close),
            'bid':        safe(ticker.bid),
            'ask':        safe(ticker.ask),
            'bidSize':    safe(ticker.bidSize),
            'askSize':    safe(ticker.askSize),
            'open':       safe(ticker.open),
            'high':       safe(ticker.high),
            'low':        safe(ticker.low),
            'volume':     safe(ticker.volume),
            'vwap':       safe(getattr(ticker, 'vwap', None)),
            'halted':     safe(getattr(ticker, 'halted', None)),
            'rtTime':     safe(getattr(ticker, 'rtTime', None)),
        }

        # Vypocitana midpoint hodnota
        try:
            b = ticker.bid
            a = ticker.ask
            if b and a and b == b and a == a and b > 0 and a > 0:
                fields['_midpoint'] = round((b + a) / 2, 4)
            else:
                fields['_midpoint'] = 0
        except Exception:
            fields['_midpoint'] = 0

        return fields

    def subscribe(self, symbol: str):
        with self._lock:
            self._pending.add(symbol.upper())

    # --- diagnosticke gettery ---
    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def iterations(self) -> int:
        return self._iterations

    @property
    def subscribed_symbols(self) -> list:
        return list(self._tickers.keys())

    # --- privatni ---

    @staticmethod
    def _extract_price(t) -> float:
        """Zkusi last -> close -> bid -> ask -> midpoint."""
        nan = float('nan')
        candidates = [
            getattr(t, 'last',  nan),
            getattr(t, 'close', nan),
            getattr(t, 'bid',   nan),
            getattr(t, 'ask',   nan),
        ]
        for c in candidates:
            if c is not None and c == c and c > 0:
                return float(c)
        # midpoint
        try:
            b, a = t.bid, t.ask
            if b == b and a == a and b > 0 and a > 0:
                return (b + a) / 2.0
        except Exception:
            pass
        return 0.0

    def _run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        while True:
            ib = None
            self._connected = False
            try:
                ib = IB()
                print(f"[TICK-SUB] Connecting clientId={self._client_id}...")
                ib.connect(self._host, self._port,
                           clientId=self._client_id, timeout=10)

                # Zkus type 3 (streaming), fallback na type 4 pri chybe
                try:
                    ib.reqMarketDataType(3)
                    self._mdt = 3
                    print("[TICK-SUB] OK - reqMarketDataType(3) = Delayed STREAMING")
                except Exception as e:
                    ib.reqMarketDataType(4)
                    self._mdt = 4
                    print(f"[TICK-SUB] WARN: type 3 selhal ({e}), pouzivam type 4")

                self._connected = True
                tickers_local: dict = {}  # sym -> ib_async Ticker
                self._tickers = tickers_local  # sdileny odkaz

                while ib.isConnected():
                    # Zpracuj nove pending subscriptions
                    with self._lock:
                        new_syms = list(self._pending - set(tickers_local.keys()))
                        self._pending.clear()

                    for sym in new_syms:
                        try:
                            contract = Stock(sym, 'SMART', 'USD')
                            ib.qualifyContracts(contract)
                            ticker = ib.reqMktData(contract, '', False, False)
                            tickers_local[sym] = ticker
                            print(f"[TICK-SUB] Subscribed: {sym}")
                        except Exception as e:
                            print(f"[TICK-SUB] Subscribe error {sym}: {e}")
                            with self._lock:
                                self._pending.add(sym)

                    # Event loop - zpracuje prichozi streaming data
                    ib.sleep(1.0)
                    self._iterations += 1

                    # Uloz hodnoty - prioritni poradi: last, close, bid, ask, mid
                    for sym, t in tickers_local.items():
                        nan = float('nan')
                        last   = t.last   if t.last   == t.last   else 0.0
                        close  = t.close  if t.close  == t.close  else 0.0
                        bid    = t.bid    if t.bid    == t.bid    else 0.0
                        ask    = t.ask    if t.ask    == t.ask    else 0.0
                        vol    = t.volume if t.volume == t.volume else 0
                        price  = self._extract_price(t)

                        self._latest[sym] = {
                            'price':      price,
                            'last':       last,
                            'close':      close,
                            'bid':        bid,
                            'ask':        ask,
                            'volume':     int(vol) if vol else 0,
                            'mdt':        self._mdt,
                            'iterations': self._iterations,
                            'ts':         time.time()
                        }

            except Exception as e:
                print(f"[TICK-SUB] Chyba: {e}")
            finally:
                self._connected = False
                self._tickers   = {}
                try:
                    if ib and ib.isConnected():
                        ib.disconnect()
                except Exception:
                    pass
                print("[TICK-SUB] Reconnecting in 10s...")
                time.sleep(10)


# ================================================================
# _HistWorker - fresh connection per request (clientId=2)
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

    def fetch(self, symbol, duration='1 D', bar_size='5 mins', timeout=15):
        result, done = [], threading.Event()
        self._queue.put((symbol, duration, bar_size, result, done))
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
            latest = item
            while not self._queue.empty():
                try:
                    newer = self._queue.get_nowait()
                    if newer is None:
                        _, _, _, _, d = latest; d.set(); return
                    _, _, _, _, skip_done = latest; skip_done.set()
                    latest = newer
                except queue.Empty:
                    break
            symbol, duration, bar_size, result, done = latest
            try:
                bars = self._fetch_fresh(symbol, duration, bar_size)
                result.extend(bars)
            except Exception as e:
                print(f"[HIST] Chyba pro {symbol}: {e}")
            finally:
                done.set()

    def _fetch_fresh(self, symbol, duration, bar_size):
        ib = IB()
        try:
            print(f"[HIST] Connecting clientId={self._client_id}...")
            ib.connect(self._host, self._port,
                       clientId=self._client_id, timeout=10)
            ib.reqMarketDataType(4)
            contract = Stock(symbol, 'SMART', 'USD')
            ib.qualifyContracts(contract)
            print(f"[HIST] reqHistoricalData {symbol} | {duration} | {bar_size}")
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

class IBConnector:
    def __init__(self):
        self.ib         = IB()
        self.connected  = False
        self.account_id = None
        self.tickers    = {}
        self.contracts  = {}
        self.executions = []

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
                print(f"\U0001f4e1 CONNECTING | {config.CONNECTION_LABEL}")
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

    def disconnect(self):
        if self.connected:
            self.ib.disconnect()
            self.connected = False

    def is_connected(self):
        return self.connected and self.ib.isConnected()

    def _get_qualified_contract(self, symbol):
        if symbol not in self.contracts:
            contract = Stock(symbol, 'SMART', 'USD')
            self.ib.qualifyContracts(contract)
            self.contracts[symbol] = contract
        return self.contracts[symbol]

    # ----------------------------------------------------------------
    # TICKER - pres _TickSubscriber
    # ----------------------------------------------------------------

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

    # ----------------------------------------------------------------
    # HISTORICKA DATA
    # ----------------------------------------------------------------

    def get_historical_data(self, symbol, duration='1 D', bar_size='5 mins'):
        if not self.is_connected(): return []
        self._tick_sub.subscribe(symbol.upper())
        return self._hist_worker.fetch(symbol, duration, bar_size)

    # ----------------------------------------------------------------
    # ACCOUNT
    # ----------------------------------------------------------------

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
            print(f"\u274c account info: {e}")
            return {}

    # ----------------------------------------------------------------
    # ORDERS
    # ----------------------------------------------------------------

    def place_order(self, symbol, action, quantity, order_type='MARKET',
                    limit_price=None, timeout=None):
        if not self.is_connected():
            return {'success': False, 'error': 'Not connected to IB'}
        if timeout is None: timeout = config.ORDER_TIMEOUT
        try:
            print(f"\U0001f4e4 Order: {action} {quantity} {symbol} @ {order_type}")
            contract = Stock(symbol, 'SMART', 'USD')
            order    = (LimitOrder(action, quantity, limit_price)
                        if order_type == 'LIMIT' else MarketOrder(action, quantity))
            order.transmit = order.outsideRth = True
            trade = self.ib.placeOrder(contract, order)
            start = time.time(); last_status = None
            while time.time() - start < timeout:
                self.ib.sleep(1)
                cs = trade.orderStatus.status
                if cs != last_status:
                    print(f"  -> {cs}"); last_status = cs
                if cs in ('Submitted', 'Filled', 'PreSubmitted',
                          'Cancelled', 'Inactive', 'ApiCancelled'):
                    break
            fs = trade.orderStatus.status
            oid = trade.order.orderId if trade.order else None
            if fs in ('Submitted', 'Filled', 'PreSubmitted'):
                return {'success': True, 'order_id': oid, 'status': fs,
                        'filled': trade.orderStatus.filled,
                        'remaining': trade.orderStatus.remaining, 'error': None}
            msgs = [f"Error {e.errorCode}: {e.message}"
                    for e in (trade.log or []) if e.errorCode and e.errorCode < 2000]
            return {'success': False, 'order_id': oid, 'status': fs,
                    'error': f"Order failed: {fs}" + ("\n" + "\n".join(msgs) if msgs else '')}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def place_market_order(self, symbol, action, quantity):
        return self.place_order(symbol, action, quantity, 'MARKET')

    # ----------------------------------------------------------------
    # POSITIONS
    # ----------------------------------------------------------------

    def get_positions(self):
        if not self.is_connected(): return []
        try:
            result = []
            for pos in self.ib.positions():
                cp   = self._tick_sub.get_price(pos.contract.symbol) or pos.avgCost
                mv   = pos.position * cp
                cb   = pos.position * pos.avgCost
                upnl = mv - cb
                result.append({
                    'symbol':             pos.contract.symbol,
                    'position':           pos.position,
                    'avg_cost':           pos.avgCost,
                    'market_price':       cp,
                    'market_value':       mv,
                    'unrealized_pnl':     upnl,
                    'unrealized_pnl_pct': (upnl / abs(cb) * 100) if cb else 0
                })
            return result
        except Exception as e:
            print(f"\u274c positions: {e}"); return []

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
            print(f"\u274c orders: {e}"); return []

    def __del__(self):
        self.disconnect()

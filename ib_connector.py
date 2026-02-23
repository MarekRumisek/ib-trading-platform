"""IB API Connector using ib_async

Version: 2.3.0 - _TickSubscriber pro streaming delayed data

ARCHITEKTURA:
  self.ib          (clientId=1) -- hlavni spojeni: orders, account, positions
  _HistWorker      (clientId=2) -- hist. data, fresh conn per request
  _TickSubscriber  (clientId=3) -- streaming tick data, bezi porad

PROC _TickSubscriber:
  reqMarketDataType(4) = Delayed FROZEN = snapshot, nereaguje na pohyb ceny
  reqMarketDataType(3) = Delayed STREAMING = aktualizuje se v realnem case
                         (s 15-20min zpozdenim na paper accountu)

  _TickSubscriber bezi v dedicovanem threadu, vola ib.sleep(1.0) v loop
  -> event loop zpracovava prichozi streaming data z IB Gateway.
  Flask workery jen CTOU z _latest dict (thread-safe Python dict read).
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
    Bezi v dedicovanem threadu se svym event loopu.
    Data cte libovolny thread pres get_price() / get_ticker_data() -
    ciste cteni Python dict, thread-safe.
    """

    def __init__(self, host, port, client_id):
        self._host      = host
        self._port      = port
        self._client_id = client_id
        self._latest: dict  = {}    # sym -> {price, last, close, bid, ask, volume, ts}
        self._pending: set  = set() # symboly cekajici na subscribe
        self._lock          = threading.Lock()

        self._thread = threading.Thread(
            target=self._run, daemon=True,
            name=f'IB-TickSub-cid{client_id}'
        )
        self._thread.start()
        print(f"[TICK-SUB] Worker spusten (clientId={client_id})")

    # --- verejne API (thread-safe cist z libovolneho threadu) ---

    def get_price(self, symbol: str) -> float:
        """Vraci posledni znamou cenu nebo 0.0."""
        return float(self._latest.get(symbol.upper(), {}).get('price', 0.0))

    def get_ticker_data(self, symbol: str):
        """Vraci plna data tickeru nebo None."""
        info = self._latest.get(symbol.upper())
        if not info or info.get('price', 0) <= 0:
            return None
        return info.copy()

    def subscribe(self, symbol: str):
        """Pozadej streaming subscription (zpracuje se v _run loop)."""
        with self._lock:
            self._pending.add(symbol.upper())

    # --- privatni ---

    def _run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        while True:
            ib = None
            try:
                ib = IB()
                print(f"[TICK-SUB] Connecting clientId={self._client_id}...")
                ib.connect(self._host, self._port,
                           clientId=self._client_id, timeout=10)
                # KLICOVE: typ 3 = Delayed STREAMING (ne frozen!)
                ib.reqMarketDataType(3)
                print(f"[TICK-SUB] OK - streaming delayed data (15min delay na demo)")

                tickers: dict = {}  # sym -> ib_async Ticker

                while ib.isConnected():
                    # Zpracuj nove pending subscriptions
                    with self._lock:
                        new_syms = list(self._pending - set(tickers.keys()))
                        self._pending.clear()

                    for sym in new_syms:
                        try:
                            contract = Stock(sym, 'SMART', 'USD')
                            ib.qualifyContracts(contract)
                            ticker = ib.reqMktData(contract, '', False, False)
                            tickers[sym] = ticker
                            print(f"[TICK-SUB] Subscribed: {sym}")
                        except Exception as e:
                            print(f"[TICK-SUB] Subscribe error {sym}: {e}")
                            with self._lock:
                                self._pending.add(sym)  # retry

                    # Beh event loopu - zpracuje prichozi streaming data z IB
                    ib.sleep(1.0)

                    # Uloz aktualni hodnoty do sdileneho dict
                    for sym, t in tickers.items():
                        nan = float('nan')
                        last  = t.last   if t.last   == t.last   else 0.0
                        close = t.close  if t.close  == t.close  else 0.0
                        bid   = t.bid    if t.bid    == t.bid    else 0.0
                        ask   = t.ask    if t.ask    == t.ask    else 0.0
                        vol   = t.volume if t.volume == t.volume else 0
                        price = last if last > 0 else close
                        self._latest[sym] = {
                            'price':  price,
                            'last':   last,
                            'close':  close,
                            'bid':    bid,
                            'ask':    ask,
                            'volume': int(vol) if vol else 0,
                            'ts':     time.time()
                        }

            except Exception as e:
                print(f"[TICK-SUB] Chyba: {e}")
            finally:
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
    """Dedikované vlakno, fresh IB() na kazdy request.
    Drain queue = zpracuje jen posledni klik.
    """

    def __init__(self, host, port, client_id):
        self._host      = host
        self._port      = port
        self._client_id = client_id
        self._queue     = queue.Queue()

        self._thread = threading.Thread(
            target=self._run, daemon=True,
            name=f'IB-Hist-Worker-cid{client_id}'
        )
        self._thread.start()
        print(f"[HIST] Worker thread spusten (clientId={client_id})")

    def fetch(self, symbol, duration='1 D', bar_size='5 mins', timeout=15):
        result = []
        done   = threading.Event()
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
            if item is None:
                break

            # Drain - zpracuj jen nejnovejsi request
            latest = item
            while not self._queue.empty():
                try:
                    newer = self._queue.get_nowait()
                    if newer is None:
                        _, _, _, _, d = latest
                        d.set()
                        return
                    _, _, _, _, skip_done = latest
                    skip_done.set()
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
            ib.reqMarketDataType(4)  # Frozen OK pro hist. data

            contract = Stock(symbol, 'SMART', 'USD')
            ib.qualifyContracts(contract)
            print(f"[HIST] Qualified {symbol}")

            print(f"[HIST] reqHistoricalData {symbol} | {duration} | {bar_size}")
            bars = ib.reqHistoricalData(
                contract, endDateTime='', durationStr=duration,
                barSizeSetting=bar_size, whatToShow='TRADES',
                useRTH=True, formatDate=1, timeout=12
            )

            result = [{
                'time':   _bar_date_to_unix(b.date),
                'open':   b.open,  'high': b.high,
                'low':    b.low,   'close': b.close,
                'volume': b.volume
            } for b in bars]

            print(f"[HIST] OK: {len(result)} baru pro {symbol}")
            return result
        finally:
            try:
                ib.disconnect()
                print(f"[HIST] Disconnected clientId={self._client_id}")
            except Exception:
                pass


def _bar_date_to_unix(bar_date):
    if hasattr(bar_date, 'timestamp'):
        return int(bar_date.timestamp())
    if isinstance(bar_date, str):
        clean = bar_date.split(' US/')[0].split(' America/')[0].strip()
        if len(clean) == 8:
            dt = datetime.strptime(clean, '%Y%m%d')
        else:
            dt = datetime.strptime(clean, '%Y%m%d %H:%M:%S')
        return int(dt.timestamp())
    return int(datetime.now().timestamp())


# ================================================================
# IBConnector
# ================================================================

class IBConnector:
    """Interactive Brokers API connector.

    self.ib          (clientId=IB_CLIENT_ID)   -- orders / account / positions
    _hist_worker     (clientId=IB_CLIENT_ID+1) -- hist. data (fresh conn per req)
    _tick_sub        (clientId=IB_CLIENT_ID+2) -- streaming tick data
    """

    def __init__(self):
        self.ib         = IB()
        self.connected  = False
        self.account_id = None
        self.tickers    = {}   # legacy cache (nepouzívá se aktivně)
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

    # ================================================================
    # CONNECT / DISCONNECT
    # ================================================================

    def connect(self):
        try:
            if config.DEBUG_CONNECTION:
                print("=" * 60)
                print("\U0001f4e1 CONNECTING TO IB")
                print("=" * 60)
                print(f"Mode: {config.CONNECTION_LABEL}")
                print(f"Host: {config.IB_HOST}")
                print(f"Port: {config.IB_PORT}")
                print(f"Client ID: {config.IB_CLIENT_ID}")
                if config.is_live_trading():
                    print("\n\u26a0\ufe0f" * 20)
                    print("\u26a0\ufe0f  LIVE TRADING MODE - REAL MONEY!")
                    print("\u26a0\ufe0f" * 20 + "\n")

            self.ib.connect(
                config.IB_HOST, config.IB_PORT,
                clientId=config.IB_CLIENT_ID, timeout=20
            )
            self.connected = True

            accounts = self.ib.managedAccounts()
            if accounts:
                self.account_id = accounts[0]

            # Hlavni spojeni pouziva type 4 pro historicka data (fallback)
            # Tick data jsou pres _tick_sub (type 3)
            self.ib.reqMarketDataType(4)

            try:
                fills = self.ib.reqExecutions()
                self.executions = fills
            except Exception as e:
                print(f"\u26a0\ufe0f Executions: {e}")

            if config.DEBUG_CONNECTION:
                print(f"\n\u2705 Connected!")
                print(f"\U0001f4bc Account: {self.account_id}")
                print("=" * 60 + "\n")
            else:
                print(f"\u2705 Connected to IB ({config.CONNECTION_LABEL})")
                print(f"\U0001f4bc Account: {self.account_id}")
            return True

        except Exception as e:
            print(f"\u274c Connection failed: {e}")
            self.connected = False
            return False

    def disconnect(self):
        if self.connected:
            self.ib.disconnect()
            self.connected = False
            print("\U0001f50c Disconnected from IB")

    def is_connected(self):
        return self.connected and self.ib.isConnected()

    def _get_qualified_contract(self, symbol):
        if symbol not in self.contracts:
            contract = Stock(symbol, 'SMART', 'USD')
            self.ib.qualifyContracts(contract)
            self.contracts[symbol] = contract
        return self.contracts[symbol]

    # ================================================================
    # TICKER - pres _TickSubscriber (type 3 = streaming delayed)
    # ================================================================

    def get_ticker(self, symbol):
        """Streaming delayed cena pres _TickSubscriber.
        Thread-safe - Flask workery mohou volat z libovolneho threadu.
        """
        if not self.is_connected():
            return None
        sym = symbol.upper()
        self._tick_sub.subscribe(sym)  # idempotent
        data = self._tick_sub.get_ticker_data(sym)
        if data:
            return data
        # Data jeste neprisla (prvni subscribe) - vrat nuly
        return {'price': 0, 'last': 0, 'bid': 0, 'ask': 0, 'close': 0, 'volume': 0}

    def get_latest_price(self, symbol):
        """Rychle cteni ceny pro /api/tick endpoint."""
        if not self.is_connected():
            return 0.0
        sym = symbol.upper()
        self._tick_sub.subscribe(sym)
        return self._tick_sub.get_price(sym)

    # ================================================================
    # HISTORICKA DATA
    # ================================================================

    def get_historical_data(self, symbol, duration='1 D', bar_size='5 mins'):
        """Pres _HistWorker + automaticky spusti tick subscription."""
        if not self.is_connected():
            return []
        # Spust tick stream pro tento symbol (asynchronne v _tick_sub threadu)
        self._tick_sub.subscribe(symbol.upper())
        return self._hist_worker.fetch(symbol, duration, bar_size)

    # ================================================================
    # ACCOUNT INFO
    # ================================================================

    def get_account_info(self):
        if not self.is_connected():
            return {}
        try:
            account_values = self.ib.accountValues()
            info = {'account_id': self.account_id,
                    'net_liquidation': 0, 'buying_power': 0, 'cash_balance': 0}
            for av in account_values:
                if av.tag == 'NetLiquidation' and av.currency == 'USD':
                    info['net_liquidation'] = float(av.value)
                elif av.tag == 'BuyingPower' and av.currency == 'USD':
                    info['buying_power'] = float(av.value)
                elif av.tag == 'CashBalance' and av.currency == 'USD':
                    info['cash_balance'] = float(av.value)
            return info
        except Exception as e:
            print(f"\u274c Error account info: {e}")
            return {}

    # ================================================================
    # OBJEDNAVKY
    # ================================================================

    def place_order(self, symbol, action, quantity, order_type='MARKET',
                    limit_price=None, timeout=None):
        if not self.is_connected():
            return {'success': False, 'error': 'Not connected to IB'}
        if timeout is None:
            timeout = config.ORDER_TIMEOUT
        try:
            if config.DEBUG_ORDERS:
                print("\n" + "=" * 60)
                print("\U0001f680 PLACING ORDER")
                print("=" * 60)
            print(f"\U0001f4e4 Order: {action} {quantity} {symbol} @ {order_type}")
            contract = Stock(symbol, 'SMART', 'USD')
            if order_type == 'LIMIT':
                if not limit_price:
                    return {'success': False, 'error': 'Limit price required'}
                order = LimitOrder(action, quantity, limit_price)
            else:
                order = MarketOrder(action, quantity)
            order.transmit    = True
            order.outsideRth  = True
            trade = self.ib.placeOrder(contract, order)
            start_time  = time.time()
            last_status = None
            iteration   = 0
            while time.time() - start_time < timeout:
                self.ib.sleep(1)
                iteration += 1
                current_status = trade.orderStatus.status
                if current_status != last_status:
                    if config.DEBUG_ORDERS:
                        print(f"[{iteration:2d}s] {last_status or 'None'} -> {current_status}")
                    last_status = current_status
                if trade.log and config.DEBUG_ORDERS:
                    for entry in trade.log:
                        if entry.message and entry.message.strip():
                            if entry.errorCode and entry.errorCode != 0:
                                if entry.errorCode >= 2000:
                                    print(f"       \u26a0\ufe0f {entry.errorCode}: {entry.message}")
                                else:
                                    print(f"       \u274c {entry.errorCode}: {entry.message}")
                if current_status in ['Submitted', 'Filled', 'PreSubmitted']:
                    break
                if current_status in ['Cancelled', 'Inactive', 'ApiCancelled']:
                    break
            final_status = trade.orderStatus.status
            order_id     = trade.order.orderId if trade.order else None
            if final_status in ['Submitted', 'Filled', 'PreSubmitted']:
                return {'success': True, 'order_id': order_id,
                        'status': final_status,
                        'filled': trade.orderStatus.filled,
                        'remaining': trade.orderStatus.remaining,
                        'error': None}
            else:
                msgs = []
                if trade.log:
                    for e in trade.log:
                        if e.errorCode and e.errorCode < 2000:
                            msgs.append(f"Error {e.errorCode}: {e.message}")
                err = f"Order failed: {final_status}"
                if msgs:
                    err += "\n" + "\n".join(msgs)
                return {'success': False, 'order_id': order_id,
                        'status': final_status, 'error': err}
        except Exception as e:
            print(f"\u274c Order FAILED: {e}")
            return {'success': False, 'error': str(e)}

    def place_market_order(self, symbol, action, quantity):
        return self.place_order(symbol, action, quantity, 'MARKET')

    # ================================================================
    # POZICE
    # ================================================================

    def get_positions(self):
        if not self.is_connected():
            return []
        try:
            positions = self.ib.positions()
            result = []
            for pos in positions:
                cp  = self._tick_sub.get_price(pos.contract.symbol) or pos.avgCost
                mv  = pos.position * cp
                cb  = pos.position * pos.avgCost
                upnl = mv - cb
                upnl_pct = (upnl / abs(cb) * 100) if cb != 0 else 0
                result.append({
                    'symbol':             pos.contract.symbol,
                    'position':           pos.position,
                    'avg_cost':           pos.avgCost,
                    'market_price':       cp,
                    'market_value':       mv,
                    'unrealized_pnl':     upnl,
                    'unrealized_pnl_pct': upnl_pct
                })
            return result
        except Exception as e:
            print(f"\u274c Error positions: {e}")
            return []

    def get_recent_orders(self, limit=10):
        if not self.is_connected():
            return []
        try:
            result = []
            for fill in self.executions[-limit:]:
                ed = fill.execution
                result.append({
                    'time': (ed.time.strftime('%H:%M')
                             if hasattr(ed.time, 'strftime') else str(ed.time)[:5]),
                    'symbol':   fill.contract.symbol,
                    'action':   ed.side,
                    'quantity': ed.shares,
                    'price':    f"${ed.price:.2f}",
                    'status':   'Filled'
                })
            trades = self.ib.trades()
            for trade in trades:
                o = trade.order
                s = trade.orderStatus
                if s.status == 'Filled':
                    continue
                price = ("Market" if o.orderType == 'MKT'
                         else f"Limit ${o.lmtPrice:.2f}")
                result.append({
                    'time':     datetime.now().strftime('%H:%M'),
                    'symbol':   trade.contract.symbol,
                    'action':   o.action,
                    'quantity': o.totalQuantity,
                    'price':    price,
                    'status':   s.status
                })
            return result[::-1][-limit:]
        except Exception as e:
            print(f"\u274c Error orders: {e}")
            return []

    def __del__(self):
        self.disconnect()

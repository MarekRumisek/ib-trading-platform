"""IB API Connector using ib_async

Version: 2.1.0 - _HistWorker architektura

ARCHITEKTURA:
  self.ib          (clientId=1) -- HLAVNI spojeni
                                    buy/sell, positions, ticker, account
                                    NEDOTKNOUT SE!

  _HistWorker      (clientId=2) -- DEDIKOVANÉ vlakno pro hist. data
                                    bezi v SEPARATNM threadu se svym event
                                    loop - Flask worker threadu se nikdy
                                    netka asyncio loopy hist. spojeni

PROC:
  ib_async pouziva asyncio event loop. Flask/Dash spousti callbacky
  v ruznych worker threadech. Kazdy thread ma prazdny asyncio loop.
  Kdyz Flask worker zavola ib.reqHistoricalData(), ceka na odpoved
  na spatnem loopu -> FREEZE navzdy.

  Reseni: _HistWorker bezi v dedicovanem threadu kde je jen JEDINY
  volajici. Ten thread si spravuje vlastni IB spojeni a vlastni loop.
  Flask workery jen posleji request do fronty a cekaji na vysledek.
  Hlavni self.ib pro trading NENI NIKDY zasazen.
"""

from ib_async import IB, Stock, MarketOrder, LimitOrder, util
from datetime import datetime
import config
import time
import threading
import queue


# ================================================================
# _HistWorker - ZCELA ODDELENY worker pro historicka data
# ================================================================

class _HistWorker:
    """Dedikované vlakno se svym IB spojenim POUZE pro hist. data.

    Hlavni self.ib (trading) se nikdy netka!

    Pouziti:
        worker = _HistWorker(host, port, clientId=2)
        bars = worker.fetch('AAPL', '1 D', '5 mins')  # thread-safe
    """

    def __init__(self, host, port, client_id):
        self._host = host
        self._port = port
        self._client_id = client_id
        self._queue = queue.Queue()
        self._ib = None
        self._contracts = {}

        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name=f'IB-Hist-Worker-cid{client_id}'
        )
        self._thread.start()
        print(f"[HIST] Worker thread spusten (clientId={client_id})")

    # ------ verejne API ------

    def fetch(self, symbol, duration='1 D', bar_size='5 mins', timeout=25):
        """Ziskej historicka data. Blokuje volajici thread max timeout sekund.
        Vraci list dictu nebo [] pri chybe / timeoutu.
        """
        result = []
        done = threading.Event()
        self._queue.put((symbol, duration, bar_size, result, done))
        done.wait(timeout=timeout)
        return result

    def stop(self):
        self._queue.put(None)

    # ------ privatni ------

    def _run(self):
        """Hlavni smycka worker threadu.

        Bezi v dedicovanem threadu - ib_async automaticky
        vytvori vlastni asyncio event loop pro tento thread.
        Zadny konflikt s Flask worker thready ani s hlavnim self.ib.
        """
        while True:
            item = self._queue.get()
            if item is None:
                break
            symbol, duration, bar_size, result, done = item
            try:
                self._ensure_connected()
                bars = self._do_fetch(symbol, duration, bar_size)
                result.extend(bars)
            except Exception as e:
                print(f"[HIST] Worker chyba pro {symbol}: {e}")
                self._ib = None  # vynuc reconnect pri pristim requestu
            finally:
                done.set()

    def _ensure_connected(self):
        if self._ib and self._ib.isConnected():
            return
        print(f"[HIST] Pripojuji hist. spojeni (clientId={self._client_id})...")
        self._ib = IB()
        self._ib.connect(
            self._host,
            self._port,
            clientId=self._client_id,
            timeout=10
        )
        self._ib.reqMarketDataType(4)
        self._contracts = {}
        print(f"[HIST] Hist. spojeni OK (clientId={self._client_id})")

    def _do_fetch(self, symbol, duration, bar_size):
        if symbol not in self._contracts:
            contract = Stock(symbol, 'SMART', 'USD')
            self._ib.qualifyContracts(contract)
            self._contracts[symbol] = contract
            print(f"[HIST] Qualified {symbol} (conId={contract.conId})")

        contract = self._contracts[symbol]
        print(f"[HIST] reqHistoricalData {symbol} | {duration} | {bar_size}")

        bars = self._ib.reqHistoricalData(
            contract,
            endDateTime='',
            durationStr=duration,
            barSizeSetting=bar_size,
            whatToShow='TRADES',
            useRTH=True,
            formatDate=1,
            timeout=15
        )

        result = []
        for bar in bars:
            result.append({
                'time':   _bar_date_to_unix(bar.date),
                'open':   bar.open,
                'high':   bar.high,
                'low':    bar.low,
                'close':  bar.close,
                'volume': bar.volume
            })

        print(f"[HIST] Hotovo: {len(result)} baru pro {symbol}")
        return result


def _bar_date_to_unix(bar_date):
    """Preved IB bar.date na Unix timestamp (int)."""
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

    self.ib        = hlavni spojeni (clientId=IB_CLIENT_ID)
                     buy/sell / positions / ticker / account
                     NEDOTKNOUT SE!

    _hist_worker   = separatni worker (clientId=IB_CLIENT_ID+1)
                     POUZE historicka data
    """

    def __init__(self):
        # === HLAVNI IB SPOJENI (trading) ===
        self.ib = IB()
        self.connected = False
        self.account_id = None
        self.tickers = {}
        self.contracts = {}
        self.executions = []

        # === HIST WORKER ===
        self._hist_worker = _HistWorker(
            host=config.IB_HOST,
            port=config.IB_PORT,
            client_id=config.IB_CLIENT_ID + 1
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
                config.IB_HOST,
                config.IB_PORT,
                clientId=config.IB_CLIENT_ID,
                timeout=20
            )
            self.connected = True

            accounts = self.ib.managedAccounts()
            if accounts:
                self.account_id = accounts[0]

            self.ib.reqMarketDataType(4)
            if config.DEBUG_CONNECTION:
                print("\U0001f4e1 Market data: Delayed Frozen (4)")

            try:
                fills = self.ib.reqExecutions()
                self.executions = fills
                if config.DEBUG_CONNECTION:
                    print(f"\u2705 Loaded {len(fills)} execution(s)")
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
            print(f"\u2705 Qualified {symbol} (conId={contract.conId})")
        return self.contracts[symbol]

    # ================================================================
    # HISTORICKA DATA - pres _HistWorker
    # ================================================================

    def get_historical_data(self, symbol, duration='1 D', bar_size='5 mins'):
        """Historicka data pres _HistWorker - ODDELENE od tradingu."""
        if not self.is_connected():
            print("[HIST] Hlavni spojeni neni aktivni")
            return []
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
    # TICKER
    # ================================================================

    def get_ticker(self, symbol):
        if not self.is_connected():
            return None
        try:
            if symbol in self.tickers:
                ticker = self.tickers[symbol]
            else:
                contract = self._get_qualified_contract(symbol)
                ticker = self.ib.reqMktData(contract, '', False, False)
                self.tickers[symbol] = ticker
            self.ib.sleep(0.5)
            return {
                'last':   ticker.last   if ticker.last   == ticker.last   else 0,
                'bid':    ticker.bid    if ticker.bid    == ticker.bid    else 0,
                'ask':    ticker.ask    if ticker.ask    == ticker.ask    else 0,
                'close':  ticker.close  if ticker.close  == ticker.close  else 0,
                'volume': ticker.volume if ticker.volume == ticker.volume else 0
            }
        except Exception as e:
            print(f"\u274c Error ticker {symbol}: {e}")
            return None

    def get_ticker_for_contract(self, contract):
        if not self.is_connected():
            return None
        try:
            cache_key = contract.conId
            if cache_key in self.tickers:
                ticker = self.tickers[cache_key]
            else:
                ticker = self.ib.reqMktData(contract, '', False, False)
                self.tickers[cache_key] = ticker
            self.ib.sleep(0.5)
            return {
                'last':   ticker.last   if ticker.last   == ticker.last   else 0,
                'bid':    ticker.bid    if ticker.bid    == ticker.bid    else 0,
                'ask':    ticker.ask    if ticker.ask    == ticker.ask    else 0,
                'close':  ticker.close  if ticker.close  == ticker.close  else 0,
                'volume': ticker.volume if ticker.volume == ticker.volume else 0
            }
        except Exception as e:
            print(f"\u274c Error ticker contract: {e}")
            return None

    # ================================================================
    # OBJEDNAVKY - NEZMENENO (hlavni self.ib)
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
            order.transmit = True
            order.outsideRth = True
            trade = self.ib.placeOrder(contract, order)
            start_time = time.time()
            last_status = None
            iteration = 0
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
            order_id = trade.order.orderId if trade.order else None
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
                ticker = self.get_ticker_for_contract(pos.contract)
                cp = (ticker['last'] if ticker and ticker['last'] > 0
                      else pos.avgCost)
                mv = pos.position * cp
                cb = pos.position * pos.avgCost
                upnl = mv - cb
                upnl_pct = (upnl / abs(cb) * 100) if cb != 0 else 0
                result.append({
                    'symbol': pos.contract.symbol,
                    'position': pos.position,
                    'avg_cost': pos.avgCost,
                    'market_price': cp,
                    'market_value': mv,
                    'unrealized_pnl': upnl,
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
                             if hasattr(ed.time, 'strftime')
                             else str(ed.time)[:5]),
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

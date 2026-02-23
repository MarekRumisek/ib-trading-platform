"""IB API Connector using ib_async

Wrapper for Interactive Brokers API with simplified interface
for trading platform. Handles connection, market data, orders,
positions, and account information.

Author: Perplexity AI Assistant
Version: 2.0.2 - reqMarketDataType(4) fix for paper trading
"""

from ib_async import IB, Stock, MarketOrder, LimitOrder, util
from datetime import datetime
import config
import time


class IBConnector:
    """Interactive Brokers API connector"""

    def __init__(self):
        self.ib = IB()
        self.connected = False
        self.account_id = None
        self.tickers = {}     # Cache ticker subscriptions (key = symbol or conId)
        self.contracts = {}   # Cache qualified contracts (key = symbol string)
        self.executions = []  # Store executions from IB

    def connect(self):
        """Connect to IB Gateway or TWS"""
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

            # -------------------------------------------------------
            # DULEZITE: reqMarketDataType(4) = Delayed Frozen
            #
            # Paper trading ucty nemaji predplatne live market dat.
            # Bez tohoto nastaveni IB haze Error 10089.
            #
            # Typy dat:
            #  1 = Live (placene predplatne)
            #  2 = Frozen (placene, posledni cena po zavreni burzy)
            #  3 = Delayed (zdarma, 15 min zpozdeni behem otevreni)
            #  4 = Delayed Frozen (zdarma, posledni cena i po zavreni)
            #                                    ^^^ TOTO CHCEME
            # -------------------------------------------------------
            self.ib.reqMarketDataType(4)
            if config.DEBUG_CONNECTION:
                print("\U0001f4e1 Market data type: Delayed Frozen (4) - zdarma na paper uctu")

            if config.DEBUG_CONNECTION:
                print("\U0001f4dd Loading executions from IB (last 24h)...")
            try:
                fills = self.ib.reqExecutions()
                self.executions = fills
                if config.DEBUG_CONNECTION:
                    print(f"\u2705 Loaded {len(fills)} execution(s) from IB")
            except Exception as e:
                print(f"\u26a0\ufe0f Could not load executions: {e}")

            if config.DEBUG_CONNECTION:
                print(f"\n\u2705 Connected successfully!")
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
        """Disconnect from IB"""
        if self.connected:
            self.ib.disconnect()
            self.connected = False
            print("\U0001f50c Disconnected from IB")

    def is_connected(self):
        """Check if connected to IB"""
        return self.connected and self.ib.isConnected()

    def _get_qualified_contract(self, symbol):
        """Return a qualified Stock contract (cached after first call).

        ib_async needs conId before reqMktData / reqHistoricalData.
        qualifyContracts() asks IB for the conId and fills it in.
        """
        if symbol not in self.contracts:
            contract = Stock(symbol, 'SMART', 'USD')
            self.ib.qualifyContracts(contract)
            self.contracts[symbol] = contract
            print(f"\u2705 Qualified contract for {symbol} (conId={contract.conId})")
        return self.contracts[symbol]

    def get_account_info(self):
        """Get account information"""
        if not self.is_connected():
            return {}
        try:
            account_values = self.ib.accountValues()
            info = {
                'account_id': self.account_id,
                'net_liquidation': 0,
                'buying_power': 0,
                'cash_balance': 0
            }
            for av in account_values:
                if av.tag == 'NetLiquidation' and av.currency == 'USD':
                    info['net_liquidation'] = float(av.value)
                elif av.tag == 'BuyingPower' and av.currency == 'USD':
                    info['buying_power'] = float(av.value)
                elif av.tag == 'CashBalance' and av.currency == 'USD':
                    info['cash_balance'] = float(av.value)
            return info
        except Exception as e:
            print(f"\u274c Error getting account info: {e}")
            return {}

    def get_historical_data(self, symbol, duration='1 D', bar_size='5 mins'):
        """Get historical OHLCV bars for Lightweight Charts.
        Returns list of dicts with Unix timestamp 'time' (int).
        """
        if not self.is_connected():
            return []
        try:
            contract = self._get_qualified_contract(symbol)
            bars = self.ib.reqHistoricalData(
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
                    'time':   self._bar_date_to_unix(bar.date),
                    'open':   bar.open,
                    'high':   bar.high,
                    'low':    bar.low,
                    'close':  bar.close,
                    'volume': bar.volume
                })
            print(f"\U0001f4c8 Loaded {len(result)} bars for {symbol}")
            return result
        except Exception as e:
            print(f"\u274c Error getting historical data: {e}")
            return []

    @staticmethod
    def _bar_date_to_unix(bar_date):
        """Convert IB bar.date string to Unix timestamp int."""
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

    def get_ticker(self, symbol):
        """Get real-time (or delayed) ticker data for a symbol."""
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
            print(f"\u274c Error getting ticker for {symbol}: {e}")
            return None

    def get_ticker_for_contract(self, contract):
        """Get real-time ticker for a qualified contract (from position)."""
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
            print(f"\u274c Error getting ticker for contract {contract.symbol}: {e}")
            return None

    def place_order(self, symbol, action, quantity, order_type='MARKET',
                    limit_price=None, timeout=None):
        """Place an order (MARKET or LIMIT)."""
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
                        print(f"[{iteration:2d}s] \U0001f4ca Status: {last_status or 'None'} \u2192 {current_status}")
                    last_status = current_status
                if trade.log and config.DEBUG_ORDERS:
                    for entry in trade.log:
                        if entry.message and entry.message.strip():
                            if entry.errorCode and entry.errorCode != 0:
                                if entry.errorCode >= 2000:
                                    print(f"       \u26a0\ufe0f Warning {entry.errorCode}: {entry.message}")
                                else:
                                    print(f"       \u274c Error {entry.errorCode}: {entry.message}")
                if current_status in ['Submitted', 'Filled', 'PreSubmitted']:
                    break
                if current_status in ['Cancelled', 'Inactive', 'ApiCancelled']:
                    break
            final_status = trade.orderStatus.status
            order_id = trade.order.orderId if trade.order else None
            if final_status in ['Submitted', 'Filled', 'PreSubmitted']:
                return {
                    'success': True, 'order_id': order_id,
                    'status': final_status,
                    'filled': trade.orderStatus.filled,
                    'remaining': trade.orderStatus.remaining,
                    'error': None
                }
            else:
                error_messages = []
                if trade.log:
                    for entry in trade.log:
                        if entry.errorCode and entry.errorCode < 2000:
                            error_messages.append(f"Error {entry.errorCode}: {entry.message}")
                error_msg = f"Order failed with status: {final_status}"
                if error_messages:
                    error_msg += "\n" + "\n".join(error_messages)
                return {'success': False, 'order_id': order_id,
                        'status': final_status, 'error': error_msg}
        except Exception as e:
            print(f"\u274c Order FAILED: {e}")
            return {'success': False, 'error': str(e)}

    def place_market_order(self, symbol, action, quantity):
        return self.place_order(symbol, action, quantity, 'MARKET')

    def get_positions(self):
        if not self.is_connected():
            return []
        try:
            positions = self.ib.positions()
            result = []
            for pos in positions:
                ticker = self.get_ticker_for_contract(pos.contract)
                current_price = (
                    ticker['last'] if ticker and ticker['last'] > 0 else pos.avgCost
                )
                market_value = pos.position * current_price
                cost_basis   = pos.position * pos.avgCost
                unrealized_pnl = market_value - cost_basis
                unrealized_pnl_pct = (
                    (unrealized_pnl / abs(cost_basis) * 100) if cost_basis != 0 else 0
                )
                result.append({
                    'symbol':             pos.contract.symbol,
                    'position':           pos.position,
                    'avg_cost':           pos.avgCost,
                    'market_price':       current_price,
                    'market_value':       market_value,
                    'unrealized_pnl':     unrealized_pnl,
                    'unrealized_pnl_pct': unrealized_pnl_pct
                })
            return result
        except Exception as e:
            print(f"\u274c Error getting positions: {e}")
            return []

    def get_recent_orders(self, limit=10):
        if not self.is_connected():
            return []
        try:
            result = []
            for fill in self.executions[-limit:]:
                exec_data = fill.execution
                result.append({
                    'time': (
                        exec_data.time.strftime('%H:%M')
                        if hasattr(exec_data.time, 'strftime')
                        else str(exec_data.time)[:5]
                    ),
                    'symbol':   fill.contract.symbol,
                    'action':   exec_data.side,
                    'quantity': exec_data.shares,
                    'price':    f"${exec_data.price:.2f}",
                    'status':   'Filled'
                })
            trades = self.ib.trades()
            for trade in trades:
                order  = trade.order
                status = trade.orderStatus
                if status.status == 'Filled':
                    continue
                price = (
                    "Market" if order.orderType == 'MKT'
                    else f"Limit ${order.lmtPrice:.2f}"
                )
                result.append({
                    'time':     datetime.now().strftime('%H:%M'),
                    'symbol':   trade.contract.symbol,
                    'action':   order.action,
                    'quantity': order.totalQuantity,
                    'price':    price,
                    'status':   status.status
                })
            return result[::-1][-limit:]
        except Exception as e:
            print(f"\u274c Error getting orders: {e}")
            return []

    def __del__(self):
        self.disconnect()

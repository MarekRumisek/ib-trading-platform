"""IB API Connector using ib_async

Wrapper for Interactive Brokers API with simplified interface
for trading platform. Handles connection, market data, orders,
positions, and account information.

Author: Perplexity AI Assistant  
Version: 1.5.0 - Working order placement with debug logging
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
        self.tickers = {}  # Cache for ticker objects (key = conId or symbol)
        self.executions = []  # Store executions from IB
        
    def connect(self):
        """Connect to IB Gateway or TWS"""
        try:
            if config.DEBUG_CONNECTION:
                print("="*60)
                print(f"📡 CONNECTING TO IB")
                print("="*60)
                print(f"Mode: {config.CONNECTION_LABEL}")
                print(f"Host: {config.IB_HOST}")
                print(f"Port: {config.IB_PORT}")
                print(f"Client ID: {config.IB_CLIENT_ID}")
                
                if config.is_live_trading():
                    print("\n⚠️" * 20)
                    print("⚠️  LIVE TRADING MODE - REAL MONEY!")
                    print("⚠️" * 20 + "\n")
            
            self.ib.connect(
                config.IB_HOST,
                config.IB_PORT,
                clientId=config.IB_CLIENT_ID,
                timeout=20
            )
            self.connected = True
            
            # Get account ID
            accounts = self.ib.managedAccounts()
            if accounts:
                self.account_id = accounts[0]
            
            # Load executions (fills) from last 24 hours
            if config.DEBUG_CONNECTION:
                print("📝 Loading executions from IB (last 24h)...")
            try:
                fills = self.ib.reqExecutions()
                self.executions = fills
                if config.DEBUG_CONNECTION:
                    print(f"✅ Loaded {len(fills)} execution(s) from IB")
            except Exception as e:
                print(f"⚠️ Could not load executions: {e}")
            
            if config.DEBUG_CONNECTION:
                print(f"\n✅ Connected successfully!")
                print(f"💼 Account: {self.account_id}")
                print("="*60 + "\n")
            else:
                print(f"✅ Connected to IB ({config.CONNECTION_LABEL})")
                print(f"💼 Account: {self.account_id}")
            
            return True
            
        except Exception as e:
            print(f"❌ Connection failed: {e}")
            self.connected = False
            return False
    
    def disconnect(self):
        """Disconnect from IB"""
        if self.connected:
            self.ib.disconnect()
            self.connected = False
            print("🔌 Disconnected from IB")
    
    def is_connected(self):
        """Check if connected to IB"""
        return self.connected and self.ib.isConnected()
    
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
            print(f"❌ Error getting account info: {e}")
            return {}
    
    def get_historical_data(self, symbol, duration='1 D', bar_size='5 mins'):
        """Get historical bars for charting"""
        if not self.is_connected():
            return []
        
        try:
            contract = Stock(symbol, 'SMART', 'USD')
            
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
            
            # Convert to list of dicts
            result = []
            for bar in bars:
                result.append({
                    'time': bar.date,
                    'open': bar.open,
                    'high': bar.high,
                    'low': bar.low,
                    'close': bar.close,
                    'volume': bar.volume
                })
            
            print(f"📈 Loaded {len(result)} bars for {symbol}")
            return result
            
        except Exception as e:
            print(f"❌ Error getting historical data: {e}")
            return []
    
    def get_ticker(self, symbol):
        """Get real-time ticker data for a new symbol
        
        Note: This is for standalone ticker requests.
        For positions, use get_ticker_for_contract() instead.
        """
        if not self.is_connected():
            return None
        
        try:
            # Check cache using symbol string as key
            if symbol in self.tickers:
                ticker = self.tickers[symbol]
            else:
                # Subscribe to market data
                contract = Stock(symbol, 'SMART', 'USD')
                ticker = self.ib.reqMktData(contract, '', False, False)
                self.tickers[symbol] = ticker
            
            # Wait for data
            self.ib.sleep(0.5)
            
            return {
                'last': ticker.last if ticker.last == ticker.last else 0,
                'bid': ticker.bid if ticker.bid == ticker.bid else 0,
                'ask': ticker.ask if ticker.ask == ticker.ask else 0,
                'close': ticker.close if ticker.close == ticker.close else 0,
                'volume': ticker.volume if ticker.volume == ticker.volume else 0
            }
            
        except Exception as e:
            print(f"❌ Error getting ticker for {symbol}: {e}")
            return None
    
    def get_ticker_for_contract(self, contract):
        """Get real-time ticker for a qualified contract (from position)
        
        Args:
            contract: A qualified contract with conId populated
            
        Returns:
            dict with price data or None
        """
        if not self.is_connected():
            return None
        
        try:
            # Use conId as cache key (contract is already qualified!)
            cache_key = contract.conId
            
            if cache_key in self.tickers:
                ticker = self.tickers[cache_key]
            else:
                # Contract is already qualified from position, just subscribe
                ticker = self.ib.reqMktData(contract, '', False, False)
                self.tickers[cache_key] = ticker
            
            # Wait for data
            self.ib.sleep(0.5)
            
            return {
                'last': ticker.last if ticker.last == ticker.last else 0,
                'bid': ticker.bid if ticker.bid == ticker.bid else 0,
                'ask': ticker.ask if ticker.ask == ticker.ask else 0,
                'close': ticker.close if ticker.close == ticker.close else 0,
                'volume': ticker.volume if ticker.volume == ticker.volume else 0
            }
            
        except Exception as e:
            print(f"❌ Error getting ticker for contract {contract.symbol}: {e}")
            return None
    
    def place_order(self, symbol, action, quantity, order_type='MARKET', limit_price=None, timeout=None):
        """Place an order (MARKET or LIMIT)
        
        Uses the proven approach from test_order.py that successfully worked.
        
        Args:
            symbol: Stock symbol (e.g. 'AAPL')
            action: 'BUY' or 'SELL'
            quantity: Number of shares
            order_type: 'MARKET' or 'LIMIT'
            limit_price: Limit price (required for LIMIT orders)
            timeout: Seconds to wait for order confirmation (default from config)
            
        Returns:
            dict: {'success': bool, 'order_id': int, 'status': str, 'error': str}
        """
        if not self.is_connected():
            return {'success': False, 'error': 'Not connected to IB'}
        
        if timeout is None:
            timeout = config.ORDER_TIMEOUT
        
        try:
            if config.DEBUG_ORDERS:
                print("\n" + "="*60)
                print("🚀 PLACING ORDER")
                print("="*60)
            
            print(f"📤 Order: {action} {quantity} {symbol} @ {order_type}")
            
            # Create contract
            contract = Stock(symbol, 'SMART', 'USD')
            if config.DEBUG_ORDERS:
                print(f"📝 Contract: {symbol} @ SMART/USD")
            
            # Create order based on type
            if order_type == 'LIMIT':
                if not limit_price:
                    return {'success': False, 'error': 'Limit price required for LIMIT orders'}
                order = LimitOrder(action, quantity, limit_price)
                if config.DEBUG_ORDERS:
                    print(f"📨 Limit order: {action} {quantity} @ ${limit_price:.2f}")
            else:
                order = MarketOrder(action, quantity)
                if config.DEBUG_ORDERS:
                    print(f"📨 Market order: {action} {quantity} shares")
            
            # Set order flags (proven working from test script)
            order.transmit = True
            order.outsideRth = True
            
            if config.DEBUG_ORDERS:
                print(f"⚙️ Flags: transmit=True, outsideRth=True")
                print(f"\n🚀 Submitting to IB (timeout: {timeout}s)...")
            
            # Place order (NO sleep before checking - this is what worked!)
            trade = self.ib.placeOrder(contract, order)
            
            if config.DEBUG_ORDERS:
                print(f"✅ Order submitted! Order ID: {trade.order.orderId if trade.order else 'N/A'}")
                print(f"\n⏳ Monitoring status...\n")
            
            # Monitor order status (approach from working test script)
            start_time = time.time()
            last_status = None
            iteration = 0
            
            while time.time() - start_time < timeout:
                self.ib.sleep(1)  # Check every second
                iteration += 1
                
                current_status = trade.orderStatus.status
                
                # Show status changes
                if current_status != last_status:
                    if config.DEBUG_ORDERS:
                        print(f"[{iteration:2d}s] 📊 Status: {last_status or 'None'} → {current_status}")
                    last_status = current_status
                elif config.DEBUG_ORDERS:
                    print(f"[{iteration:2d}s] Status: {current_status}")
                
                # Check for messages/errors in trade log (CRITICAL for debugging!)
                if trade.log and config.DEBUG_ORDERS:
                    for entry in trade.log:
                        if entry.message and entry.message.strip():
                            # Show warnings and errors
                            if entry.errorCode and entry.errorCode != 0:
                                if entry.errorCode >= 2000:  # Warnings
                                    print(f"       ⚠️ Warning {entry.errorCode}: {entry.message}")
                                else:  # Errors
                                    print(f"       ❌ Error {entry.errorCode}: {entry.message}")
                
                # Success states (from working test script)
                if current_status in ['Submitted', 'Filled', 'PreSubmitted']:
                    if config.DEBUG_ORDERS:
                        print(f"\n🎉 SUCCESS! Order reached: {current_status}")
                    break
                
                # Failure states
                if current_status in ['Cancelled', 'Inactive', 'ApiCancelled']:
                    if config.DEBUG_ORDERS:
                        print(f"\n❌ FAILED! Order status: {current_status}")
                    break
            
            # Final status check
            final_status = trade.orderStatus.status
            order_id = trade.order.orderId if trade.order else None
            
            if config.DEBUG_ORDERS:
                print("\n" + "="*60)
                print("📊 FINAL RESULTS")
                print("="*60)
                print(f"Final Status: {final_status}")
                print(f"Order ID: {order_id}")
                print(f"Filled: {trade.orderStatus.filled}")
                print(f"Remaining: {trade.orderStatus.remaining}")
                print("="*60 + "\n")
            
            # Determine success
            if final_status in ['Submitted', 'Filled', 'PreSubmitted']:
                return {
                    'success': True,
                    'order_id': order_id,
                    'status': final_status,
                    'filled': trade.orderStatus.filled,
                    'remaining': trade.orderStatus.remaining,
                    'error': None
                }
            else:
                # Collect error messages from log
                error_messages = []
                if trade.log:
                    for entry in trade.log:
                        if entry.errorCode and entry.errorCode < 2000:  # Actual errors
                            error_messages.append(f"Error {entry.errorCode}: {entry.message}")
                
                error_msg = f"Order failed with status: {final_status}"
                if error_messages:
                    error_msg += "\n" + "\n".join(error_messages)
                
                if config.DEBUG_ORDERS:
                    print(f"❌ {error_msg}")
                
                return {
                    'success': False,
                    'order_id': order_id,
                    'status': final_status,
                    'error': error_msg
                }
            
        except Exception as e:
            error_msg = str(e)
            print(f"❌ Order FAILED with exception: {error_msg}")
            if config.DEBUG_ORDERS:
                import traceback
                traceback.print_exc()
            return {'success': False, 'error': error_msg}
    
    # Legacy method for backward compatibility
    def place_market_order(self, symbol, action, quantity):
        """Legacy method - calls place_order with MARKET type"""
        return self.place_order(symbol, action, quantity, 'MARKET')
    
    def get_positions(self):
        """Get all open positions with P&L
        
        Uses qualified contracts from position objects to avoid conId errors
        """
        if not self.is_connected():
            return []
        
        try:
            positions = self.ib.positions()
            
            result = []
            for pos in positions:
                # Use the qualified contract from position object
                ticker = self.get_ticker_for_contract(pos.contract)
                
                # Get current price (fallback to avgCost if ticker fails)
                current_price = ticker['last'] if ticker and ticker['last'] > 0 else pos.avgCost
                
                market_value = pos.position * current_price
                cost_basis = pos.position * pos.avgCost
                unrealized_pnl = market_value - cost_basis
                unrealized_pnl_pct = (unrealized_pnl / abs(cost_basis) * 100) if cost_basis != 0 else 0
                
                result.append({
                    'symbol': pos.contract.symbol,
                    'position': pos.position,
                    'avg_cost': pos.avgCost,
                    'market_price': current_price,
                    'market_value': market_value,
                    'unrealized_pnl': unrealized_pnl,
                    'unrealized_pnl_pct': unrealized_pnl_pct
                })
            
            return result
            
        except Exception as e:
            print(f"❌ Error getting positions: {e}")
            return []
    
    def get_recent_orders(self, limit=10):
        """Get recent orders from executions (fills)
        
        Uses self.executions loaded from IB via reqExecutions()
        These persist for 24 hours in IB and survive app restarts!
        """
        if not self.is_connected():
            return []
        
        try:
            # Combine live trades with historical executions
            result = []
            
            # Add historical executions (from last 24h)
            for fill in self.executions[-limit:]:
                exec_data = fill.execution
                result.append({
                    'time': exec_data.time.strftime('%H:%M') if hasattr(exec_data.time, 'strftime') else str(exec_data.time)[:5],
                    'symbol': fill.contract.symbol,
                    'action': exec_data.side,
                    'quantity': exec_data.shares,
                    'price': f"${exec_data.price:.2f}",
                    'status': 'Filled'
                })
            
            # Add current open/pending trades
            trades = self.ib.trades()
            for trade in trades:
                order = trade.order
                status = trade.orderStatus
                
                # Skip if already filled (in executions)
                if status.status == 'Filled':
                    continue
                
                # Determine price display
                if order.orderType == 'MKT':
                    price = "Market"
                elif order.orderType == 'LMT':
                    price = f"Limit ${order.lmtPrice:.2f}"
                else:
                    price = f"${order.lmtPrice:.2f}"
                
                result.append({
                    'time': datetime.now().strftime('%H:%M'),
                    'symbol': trade.contract.symbol,
                    'action': order.action,
                    'quantity': order.totalQuantity,
                    'price': price,
                    'status': status.status
                })
            
            return result[::-1][-limit:]  # Reverse and limit
            
        except Exception as e:
            print(f"❌ Error getting orders: {e}")
            return []
    
    def __del__(self):
        """Cleanup on destruction"""
        self.disconnect()

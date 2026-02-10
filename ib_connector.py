"""IB API Connector using ib_async

Wrapper for Interactive Brokers API with simplified interface
for trading platform. Handles connection, market data, orders,
positions, and account information.

Author: Perplexity AI Assistant  
Version: 1.2.0 - Added LIMIT order support
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
        self.tickers = {}  # Cache for ticker objects
        
    def connect(self):
        """Connect to IB Gateway or TWS"""
        try:
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
                
            print(f"✅ Connected to IB Gateway")
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
            print("🔌 Disconnected from IB Gateway")
    
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
        """Get real-time ticker data"""
        if not self.is_connected():
            return None
        
        try:
            # Check cache
            if symbol in self.tickers:
                ticker = self.tickers[symbol]
            else:
                # Subscribe to market data (NO qualifyContracts needed!)
                contract = Stock(symbol, 'SMART', 'USD')
                ticker = self.ib.reqMktData(contract, '', False, False)
                self.tickers[symbol] = ticker
            
            # Wait for data
            self.ib.sleep(0.5)
            
            return {
                'last': ticker.last if ticker.last == ticker.last else 0,  # Check for NaN
                'bid': ticker.bid if ticker.bid == ticker.bid else 0,
                'ask': ticker.ask if ticker.ask == ticker.ask else 0,
                'close': ticker.close if ticker.close == ticker.close else 0,
                'volume': ticker.volume if ticker.volume == ticker.volume else 0
            }
            
        except Exception as e:
            print(f"❌ Error getting ticker: {e}")
            return None
    
    def place_order(self, symbol, action, quantity, order_type='MARKET', limit_price=None, timeout=15):
        """Place an order (MARKET or LIMIT)
        
        Args:
            symbol: Stock symbol (e.g. 'AAPL')
            action: 'BUY' or 'SELL'
            quantity: Number of shares
            order_type: 'MARKET' or 'LIMIT'
            limit_price: Limit price (required for LIMIT orders)
            timeout: Seconds to wait for order confirmation
            
        Returns:
            dict: {'success': bool, 'order_id': int, 'error': str}
        """
        if not self.is_connected():
            return {'success': False, 'error': 'Not connected to IB'}
        
        try:
            print(f"📤 Placing order: {action} {quantity} {symbol} @ {order_type}...")
            
            # Create contract (NO qualifyContracts needed for basic stocks!)
            contract = Stock(symbol, 'SMART', 'USD')
            print(f"📝 Contract created: {symbol} @ SMART/USD")
            
            # Create order based on type
            if order_type == 'LIMIT':
                if not limit_price:
                    return {'success': False, 'error': 'Limit price required for LIMIT orders'}
                order = LimitOrder(action, quantity, limit_price)
                print(f"📨 Limit order created: {action} {quantity} @ ${limit_price:.2f}")
            else:
                order = MarketOrder(action, quantity)
                print(f"📨 Market order created: {action} {quantity} shares")
            
            # Place order directly (like official examples)
            print(f"🚀 Submitting order to IB (timeout: {timeout}s)...")
            trade = self.ib.placeOrder(contract, order)
            print(f"✅ Order submitted! Trade object created.")
            
            # Wait for order to be accepted
            print(f"⏳ Waiting for order confirmation (max {timeout}s)...")
            start_time = time.time()
            last_status = None
            
            while time.time() - start_time < timeout:
                self.ib.sleep(0.5)
                
                current_status = trade.orderStatus.status
                if current_status != last_status:
                    print(f"📊 Status update: {current_status}")
                    last_status = current_status
                
                # Check if order is in a final/accepted state
                if current_status in ['Submitted', 'Filled', 'PreSubmitted']:
                    break
                    
                # Check for immediate rejection
                if current_status in ['Cancelled', 'ApiCancelled', 'Inactive']:
                    print(f"❌ Order rejected/cancelled: {current_status}")
                    break
            
            # Check final status
            final_status = trade.orderStatus.status
            
            if final_status in ['Submitted', 'Filled', 'PreSubmitted']:
                print(f"✅ Order SUCCESSFUL!")
                print(f"📋 Order ID: {trade.order.orderId}")
                print(f"📊 Final Status: {final_status}")
                
                return {
                    'success': True,
                    'order_id': trade.order.orderId,
                    'status': final_status,
                    'error': None
                }
            else:
                error_msg = f"Order not confirmed after {timeout}s. Final status: {final_status}"
                print(f"⚠️ {error_msg}")
                
                # Try to get more details about why it failed
                if hasattr(trade, 'log') and trade.log:
                    for entry in trade.log:
                        print(f"   Log: {entry}")
                
                return {'success': False, 'error': error_msg}
            
        except Exception as e:
            error_msg = str(e)
            print(f"❌ Order FAILED with exception: {error_msg}")
            import traceback
            traceback.print_exc()
            return {'success': False, 'error': error_msg}
    
    # Legacy method for backward compatibility
    def place_market_order(self, symbol, action, quantity):
        """Legacy method - calls place_order with MARKET type"""
        return self.place_order(symbol, action, quantity, 'MARKET')
    
    def get_positions(self):
        """Get all open positions with P&L"""
        if not self.is_connected():
            return []
        
        try:
            positions = self.ib.positions()
            
            result = []
            for pos in positions:
                # Get current market price
                ticker = self.get_ticker(pos.contract.symbol)
                current_price = ticker['last'] if ticker else pos.avgCost
                
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
        """Get recent orders"""
        if not self.is_connected():
            return []
        
        try:
            trades = self.ib.trades()
            
            result = []
            for trade in trades[-limit:]:
                order = trade.order
                status = trade.orderStatus
                
                # Determine price display
                if status.status == 'Filled':
                    price = f"${status.avgFillPrice:.2f}"
                elif order.orderType == 'MKT':
                    price = "Market"
                elif order.orderType == 'LMT':
                    price = f"Limit ${order.lmtPrice:.2f}"
                else:
                    price = f"${order.lmtPrice:.2f}"
                
                result.append({
                    'time': datetime.now().strftime('%H:%M'),  # Placeholder
                    'symbol': trade.contract.symbol,
                    'action': order.action,
                    'quantity': order.totalQuantity,
                    'price': price,
                    'status': status.status
                })
            
            return result[::-1]  # Reverse to show newest first
            
        except Exception as e:
            print(f"❌ Error getting orders: {e}")
            return []
    
    def __del__(self):
        """Cleanup on destruction"""
        self.disconnect()

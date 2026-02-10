"""IB API Connector using ib_async

Wrapper for Interactive Brokers API with simplified interface
for trading platform. Handles connection, market data, orders,
positions, and account information.

Author: Perplexity AI Assistant
Version: 1.0.2
"""

from ib_async import IB, Stock, MarketOrder, util
from datetime import datetime
import config
import time
import asyncio

class IBConnector:
    """Interactive Brokers API connector"""
    
    def __init__(self):
        self.ib = IB()
        self.connected = False
        self.account_id = None
        self.tickers = {}  # Cache for ticker objects
        self.qualified_contracts = {}  # Cache for qualified contracts
        
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
    
    def _qualify_contract(self, symbol, timeout=5):
        """Qualify a contract with timeout
        
        Returns:
            Qualified contract or None if failed
        """
        # Check cache
        if symbol in self.qualified_contracts:
            print(f"💾 Using cached contract for {symbol}")
            return self.qualified_contracts[symbol]
        
        try:
            print(f"🔍 Qualifying contract for {symbol}...")
            
            contract = Stock(symbol, 'SMART', 'USD')
            
            # Qualify with timeout
            qualified = self.ib.qualifyContracts(contract)
            
            if not qualified:
                print(f"❌ Failed to qualify {symbol}")
                return None
            
            # Cache it
            self.qualified_contracts[symbol] = qualified[0]
            print(f"✅ Contract qualified: {qualified[0].symbol} @ {qualified[0].primaryExchange}")
            
            return qualified[0]
            
        except asyncio.TimeoutError:
            print(f"❌ Contract qualification timed out for {symbol}")
            return None
        except Exception as e:
            print(f"❌ Error qualifying contract {symbol}: {e}")
            return None
    
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
                # Subscribe to market data
                contract = Stock(symbol, 'SMART', 'USD')
                self.ib.qualifyContracts(contract)
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
    
    def place_market_order(self, symbol, action, quantity):
        """Place a market order
        
        Args:
            symbol: Stock symbol (e.g. 'AAPL')
            action: 'BUY' or 'SELL'
            quantity: Number of shares
            
        Returns:
            dict: {'success': bool, 'order_id': int, 'error': str}
        """
        if not self.is_connected():
            return {'success': False, 'error': 'Not connected to IB'}
        
        try:
            print(f"📤 Placing order: {action} {quantity} {symbol}...")
            
            # Qualify contract first (with timeout)
            contract = self._qualify_contract(symbol, timeout=5)
            
            if not contract:
                error_msg = f"Failed to qualify contract for {symbol}"
                print(f"❌ {error_msg}")
                return {'success': False, 'error': error_msg}
            
            print(f"📝 Creating market order...")
            order = MarketOrder(action, quantity)
            
            print(f"📨 Submitting order to IB...")
            trade = self.ib.placeOrder(contract, order)
            
            print(f"⏳ Waiting for order confirmation (max 10s)...")
            
            # Wait for order to be submitted (max 10 seconds)
            start_time = time.time()
            last_status = None
            
            while time.time() - start_time < 10:
                self.ib.sleep(0.5)
                
                current_status = trade.orderStatus.status
                if current_status != last_status:
                    print(f"📊 Status update: {current_status}")
                    last_status = current_status
                
                if current_status in ['Submitted', 'Filled', 'PreSubmitted']:
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
                error_msg = f"Order not confirmed. Status: {final_status}"
                print(f"⚠️ {error_msg}")
                return {'success': False, 'error': error_msg}
            
        except asyncio.TimeoutError:
            error_msg = "Order placement timed out"
            print(f"❌ {error_msg}")
            return {'success': False, 'error': error_msg}
            
        except Exception as e:
            error_msg = str(e)
            print(f"❌ Order FAILED: {error_msg}")
            import traceback
            traceback.print_exc()
            return {'success': False, 'error': error_msg}
    
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

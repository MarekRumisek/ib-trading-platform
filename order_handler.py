"""Dedicated Order Handler for Flask Applications

This module provides a thread-safe order handler that runs in its own
thread with its own IB connection and event loop. This ensures IB API
callbacks are properly received and processed without Flask interference.

Author: Perplexity AI Assistant
Version: 2.0.0 - Own IB connection per thread
"""

import threading
import asyncio
from queue import Queue
import time
from typing import Optional, Dict, Any
from ib_async import IB, Stock, MarketOrder, LimitOrder
import config

class OrderHandler:
    """Thread-safe order handler with dedicated IB connection and event loop."""
    
    def __init__(self):
        """Initialize handler (IB connection created in thread)."""
        self.order_queue = Queue()
        self.result_queue = Queue()
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.ib: Optional[IB] = None
        
    def start(self):
        """Start the order handler thread."""
        if self.running:
            return
            
        self.running = True
        self.thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self.thread.start()
        
        # Wait for thread to initialize
        time.sleep(1)
        
        if config.DEBUG_ORDERS:
            print("✅ Order handler thread started")
    
    def stop(self):
        """Stop the order handler thread."""
        self.running = False
        
        # Disconnect IB in handler thread
        if self.ib and self.ib.isConnected():
            try:
                self.ib.disconnect()
            except:
                pass
        
        if self.thread:
            self.thread.join(timeout=2)
            
        if config.DEBUG_ORDERS:
            print("🛑 Order handler thread stopped")
    
    def _run_event_loop(self):
        """Run dedicated event loop in this thread."""
        # Create new event loop for this thread
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        # Create dedicated IB connection IN THIS THREAD
        self.ib = IB()
        
        try:
            # Connect to IB in this thread
            if config.DEBUG_ORDERS:
                print(f"\n🔄 Order handler connecting to IB...")
                print(f"   Thread: {threading.current_thread().name}")
                print(f"   Host: {config.IB_HOST}:{config.IB_PORT}")
                print(f"   Client ID: {config.IB_CLIENT_ID + 1}")
            
            self.ib.connect(
                config.IB_HOST,
                config.IB_PORT,
                clientId=config.IB_CLIENT_ID + 1  # Different clientId!
            )
            
            if config.DEBUG_ORDERS:
                print("✅ Order handler connected to IB!")
                print(f"🔄 Order handler event loop running\n")
            
            # Process orders in this thread's event loop
            while self.running and self.ib.isConnected():
                # Check for new orders
                if not self.order_queue.empty():
                    order_data = self.order_queue.get()
                    result = self._process_order(order_data)
                    self.result_queue.put(result)
                else:
                    # CRITICAL: Use ib.sleep() to keep event loop alive!
                    self.ib.sleep(0.01)
                    
        except Exception as e:
            if config.DEBUG_ORDERS:
                print(f"❌ Order handler error: {e}")
                import traceback
                traceback.print_exc()
        finally:
            if self.ib and self.ib.isConnected():
                self.ib.disconnect()
            if self.loop:
                self.loop.close()
    
    def _process_order(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process order in this thread's event loop with IB connection.
        
        Args:
            order_data: Order parameters
            
        Returns:
            Order result dictionary
        """
        symbol = order_data['symbol']
        action = order_data['action']
        quantity = order_data['quantity']
        order_type = order_data['order_type']
        limit_price = order_data.get('limit_price')
        timeout = order_data.get('timeout', 15)
        
        if config.DEBUG_ORDERS:
            print("\n" + "="*60)
            print("🚀 ORDER HANDLER: PLACING ORDER")
            print("="*60)
            print(f"📤 Order: {action} {quantity} {symbol} @ {order_type}")
            print(f"📝 Thread: {threading.current_thread().name}")
            print(f"🔗 IB Connected: {self.ib.isConnected()}")
        
        try:
            # Create contract
            contract = Stock(symbol, 'SMART', 'USD')
            
            # Create order
            if order_type == 'LIMIT' and limit_price:
                order = LimitOrder(action, quantity, limit_price)
            else:
                order = MarketOrder(action, quantity)
            
            order.transmit = True
            order.outsideRth = True
            
            if config.DEBUG_ORDERS:
                print(f"📨 Order created: {order_type}")
                print(f"⚙️ Transmit: {order.transmit}, OutsideRTH: {order.outsideRth}")
            
            # Place order
            print(f"\n🚀 Submitting to IB (timeout: {timeout}s)...")
            trade = self.ib.placeOrder(contract, order)
            
            if config.DEBUG_ORDERS:
                print(f"✅ Order submitted! Order ID: {trade.order.orderId}")
            
            # CRITICAL: Sleep workaround for paper trading!
            if config.DEBUG_ORDERS:
                print("\n⏱️ Applying sleep workaround...")
            
            self.ib.sleep(1)
            time.sleep(2)  # Extra sleep for paper trading
            self.ib.sleep(1)
            
            if config.DEBUG_ORDERS:
                print("✅ Sleep completed")
            
            # Monitor order status
            if config.DEBUG_ORDERS:
                print(f"\n⏳ Monitoring status...\n")
            
            start_time = time.time()
            last_status = None
            
            while time.time() - start_time < timeout:
                self.ib.sleep(1)
                elapsed = int(time.time() - start_time)
                
                current_status = trade.orderStatus.status
                
                # Show status changes
                if current_status != last_status:
                    if config.DEBUG_ORDERS:
                        print(f"[{elapsed:2d}s] 📊 Status: {last_status or 'None'} → {current_status}")
                    last_status = current_status
                    
                    # Check for messages/errors
                    if trade.log:
                        for entry in trade.log:
                            if entry.message and entry.message.strip():
                                if config.DEBUG_ORDERS:
                                    print(f"       💬 Message: {entry.message}")
                            if entry.errorCode and entry.errorCode != 0:
                                if config.DEBUG_ORDERS:
                                    print(f"       ⚠️ Error {entry.errorCode}: {entry.message}")
                else:
                    if config.DEBUG_ORDERS:
                        print(f"[{elapsed:2d}s] Status: {current_status}")
                
                # Success?
                if current_status in ['Submitted', 'Filled', 'PreSubmitted']:
                    if config.DEBUG_ORDERS:
                        print(f"\n🎉 SUCCESS! Order reached: {current_status}\n")
                    break
                
                # Failure?
                if current_status in ['Cancelled', 'Inactive', 'ApiCancelled']:
                    if config.DEBUG_ORDERS:
                        print(f"\n❌ FAILED! Order status: {current_status}\n")
                    break
            
            # Final status
            final_status = trade.orderStatus.status
            order_id = trade.order.orderId
            filled = trade.orderStatus.filled
            remaining = trade.orderStatus.remaining
            
            if config.DEBUG_ORDERS:
                print("="*60)
                print("📊 FINAL RESULTS")
                print("="*60)
                print(f"Final Status: {final_status}")
                print(f"Order ID: {order_id}")
                print(f"Filled: {filled}")
                print(f"Remaining: {remaining}")
                print("="*60 + "\n")
            
            # Determine success
            success = final_status in ['Submitted', 'Filled', 'PreSubmitted']
            
            return {
                'success': success,
                'order_id': order_id,
                'status': final_status,
                'filled': filled,
                'remaining': remaining,
                'error': None if success else f"Order failed with status: {final_status}"
            }
            
        except Exception as e:
            if config.DEBUG_ORDERS:
                print(f"\n❌ Exception during order placement: {e}")
                import traceback
                traceback.print_exc()
            
            return {
                'success': False,
                'error': str(e),
                'order_id': None,
                'status': 'Error'
            }
    
    def place_order_async(self, symbol: str, action: str, quantity: int,
                         order_type: str = 'MARKET', limit_price: Optional[float] = None,
                         timeout: int = 15) -> Dict[str, Any]:
        """Place order asynchronously through dedicated handler thread.
        
        This method is thread-safe and can be called from Flask routes.
        
        Args:
            symbol: Stock symbol
            action: 'BUY' or 'SELL'
            quantity: Number of shares
            order_type: 'MARKET' or 'LIMIT'
            limit_price: Price for limit orders
            timeout: Timeout in seconds
            
        Returns:
            Order result dictionary with 'success', 'order_id', 'status', etc.
        """
        if not self.running:
            return {
                'success': False,
                'error': 'Order handler not running'
            }
        
        if not self.ib or not self.ib.isConnected():
            return {
                'success': False,
                'error': 'Order handler not connected to IB'
            }
        
        # Queue the order
        order_data = {
            'symbol': symbol,
            'action': action,
            'quantity': quantity,
            'order_type': order_type,
            'limit_price': limit_price,
            'timeout': timeout
        }
        
        self.order_queue.put(order_data)
        
        # Wait for result (with timeout)
        max_wait = timeout + 10  # Extra buffer for processing
        start_time = time.time()
        
        while time.time() - start_time < max_wait:
            if not self.result_queue.empty():
                return self.result_queue.get()
            time.sleep(0.1)
        
        # Timeout
        return {
            'success': False,
            'error': f'Order handler timeout after {max_wait}s'
        }

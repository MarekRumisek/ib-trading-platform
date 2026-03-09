"""Dedicated Order Handler for Flask Applications

This module provides a thread-safe order handler that runs in its own
thread with its own IB connection and event loop. This ensures IB API
callbacks are properly received and processed without Flask interference.

⚠️ CRITICAL: DO NOT MODIFY WITHOUT READING ARCHITECTURE.md FIRST!

Why This Exists:
- Flask worker threads are ephemeral - they die after handling requests
- ib_async needs persistent event loop to receive IB API callbacks
- Sharing IB connection between Flask threads causes orders to stuck in PendingSubmit
- This handler creates OWN IB connection in OWN thread with OWN event loop

Key Design Points:
1. Dedicated thread that runs for entire app lifetime
2. Own IB connection (different clientId than main connection)
3. Own asyncio event loop (never dies, callbacks always work)
4. Sleep workarounds for paper trading validation delays

Documentation:
- Full explanation: ARCHITECTURE.md
- Test baseline: test_order.py

DO NOT:
- Share IB connection between threads
- Place orders directly in Flask routes
- Remove sleep workarounds
- Use same clientId as main connection

Author: Perplexity AI Assistant
Version: 2.0.0 - Own IB connection per thread
Last Validated: February 11, 2026 - Orders successfully filling
"""

import threading
import asyncio
from queue import Queue
import time
import uuid
from typing import Optional, Dict, Any
from ib_async import IB, MarketOrder, LimitOrder
from contract_utils import create_contract, normalize_asset_type, sanitize_symbol, ASSET_TYPE_FOREX
import config

# Base clientId for order handler; incremented on each reconnect to avoid conflicts
_ORDER_HANDLER_BASE_CLIENT_ID = config.IB_CLIENT_ID + 1
_client_id_counter_lock = threading.Lock()
_client_id_counter = _ORDER_HANDLER_BASE_CLIENT_ID


def _next_client_id() -> int:
    """Return next unique clientId for order handler connections."""
    global _client_id_counter
    with _client_id_counter_lock:
        cid = _client_id_counter
        # Cycle through range 5–8 to avoid conflicts with known clientIds (1–3, 9, 10+)
        _client_id_counter = cid + 1 if cid < 8 else _ORDER_HANDLER_BASE_CLIENT_ID
        return cid


class OrderHandler:
    """Thread-safe order handler with dedicated IB connection and event loop.
    
    ⚠️ READ ARCHITECTURE.md BEFORE MODIFYING!
    
    This class solves the Flask + ib_async threading incompatibility by:
    1. Running in dedicated long-lived thread (not Flask worker)
    2. Creating own IB connection in that thread
    3. Maintaining own asyncio event loop for callbacks
    4. Processing orders via queue (thread-safe communication)
    """
    
    def __init__(self):
        """Initialize handler (IB connection created in thread)."""
        self.order_queue = Queue()
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.ib: Optional[IB] = None
        self._client_id: Optional[int] = None
        self._pending: Dict[str, Dict[str, Any]] = {}
        self._pending_lock = threading.Lock()
        
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
        """Run dedicated event loop in this thread.
        
        CRITICAL: This creates a NEW IB connection in THIS thread.
        Do not share connections from other threads!
        """
        # Create new event loop for this thread
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        # Create dedicated IB connection IN THIS THREAD
        self.ib = IB()
        
        try:
            # Connect to IB in this thread with clientId retry to avoid 326 collisions
            last_error = None
            for attempt in range(4):
                self._client_id = _next_client_id()

                if config.DEBUG_ORDERS:
                    print(f"\n🔄 Order handler connecting to IB...")
                    print(f"   Thread: {threading.current_thread().name}")
                    print(f"   Host: {config.IB_HOST}:{config.IB_PORT}")
                    print(f"   Client ID: {self._client_id}")

                try:
                    self.ib.connect(
                        config.IB_HOST,
                        config.IB_PORT,
                        clientId=self._client_id  # Unique clientId per connection attempt
                    )
                    break
                except Exception as e:
                    last_error = e
                    if config.DEBUG_ORDERS:
                        print(f"❌ Order handler connect attempt {attempt + 1}/4 failed: {e}")
                    time.sleep(0.5)
            else:
                raise last_error or RuntimeError('Order handler failed to connect to IB')
            
            if config.DEBUG_ORDERS:
                print("✅ Order handler connected to IB!")
                print(f"🔄 Order handler event loop running\n")

            self.ib.reqOpenOrders()
            
            # Process orders in this thread's event loop
            while self.running and self.ib.isConnected():
                # Check for new orders
                if not self.order_queue.empty():
                    order_data = self.order_queue.get()
                    self._process_order(order_data)
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
        correlation_id = order_data.get('correlation_id')
        symbol = order_data['symbol']
        asset_type = normalize_asset_type(order_data.get('asset_type'))
        action = order_data['action']
        quantity = order_data['quantity']
        order_type = order_data['order_type']
        limit_price = order_data.get('limit_price')
        timeout = order_data.get('timeout', 15)
        result = None
        
        if config.DEBUG_ORDERS:
            print("\n" + "="*60)
            print("🚀 ORDER HANDLER: PLACING ORDER")
            print("="*60)
            print(f"📤 Order: {action} {quantity} {symbol} ({asset_type}) @ {order_type}")
            print(f"📝 Thread: {threading.current_thread().name}")
            print(f"🔗 IB Connected: {self.ib.isConnected()}")
        
        try:
            # BUG 4 FIX: Default Forex quantity to 20000 (IDEALPRO minimum)
            is_forex = (asset_type == ASSET_TYPE_FOREX)
            if is_forex and quantity < 20000:
                if config.DEBUG_ORDERS:
                    print(f"⚠️ Forex quantity {quantity} below IDEALPRO minimum — adjusting to 20000")
                quantity = 20000

            # Create contract
            contract = create_contract(symbol, asset_type)
            qualified = self.ib.qualifyContracts(contract)
            if qualified:
                contract = qualified[0]
            print(f"📄 Contract: {sanitize_symbol(symbol, asset_type)} ({asset_type}) conId={getattr(contract, 'conId', None)}")
            
            # Create order
            if order_type == 'LIMIT' and limit_price:
                order = LimitOrder(action, quantity, limit_price)
            else:
                order = MarketOrder(action, quantity)
            
            order.transmit = True
            # BUG 3 FIX: Always use GTC to prevent TWS preset from forcing TIF=DAY
            # and cancelling the order (error 10349).
            # Forex trades 24/5 — outsideRth is irrelevant and triggers warning 2109.
            order.tif = 'GTC'
            if not is_forex:
                order.outsideRth = True
            
            if config.DEBUG_ORDERS:
                print(f"📨 Order created: {order_type}")
                print(f"⚙️ Transmit: {order.transmit}, TIF: {order.tif}, OutsideRTH: {getattr(order, 'outsideRth', False)}")
            
            # Place order
            print(f"\n🚀 Submitting to IB (timeout: {timeout}s)...")
            trade = self.ib.placeOrder(contract, order)
            
            if config.DEBUG_ORDERS:
                print(f"✅ Order submitted! Order ID: {trade.order.orderId}")
            
            # CRITICAL: Sleep workaround for paper trading!
            # DO NOT REMOVE - See ARCHITECTURE.md for explanation
            if config.DEBUG_ORDERS:
                print("\n⏱️ Applying sleep workaround...")
            
            self.ib.sleep(1)        # Process ib_async events
            time.sleep(2)           # Give TWS time to validate
            self.ib.sleep(1)        # Process any pending callbacks
            
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
            
            result = {
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
            
            result = {
                'success': False,
                'error': str(e),
                'order_id': None,
                'status': 'Error'
            }

        finally:
            if correlation_id:
                with self._pending_lock:
                    pending = self._pending.get(correlation_id)
                    if pending is not None:
                        pending['result'] = result
                        pending['event'].set()

        return result
    
    def place_order_async(self, symbol: str, action: str, quantity: int,
                         order_type: str = 'MARKET', limit_price: Optional[float] = None,
                         timeout: int = 15, asset_type: str = 'STOCK') -> Dict[str, Any]:
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

        correlation_id = str(uuid.uuid4())
        event = threading.Event()

        with self._pending_lock:
            self._pending[correlation_id] = {
                'event': event,
                'result': None
            }
        
        # Queue the order
        order_data = {
            'correlation_id': correlation_id,
            'symbol': symbol,
            'asset_type': asset_type,
            'action': action,
            'quantity': quantity,
            'order_type': order_type,
            'limit_price': limit_price,
            'timeout': timeout
        }
        
        self.order_queue.put(order_data)
        
        # Wait for result (with timeout)
        max_wait = timeout + 10  # Extra buffer for processing
        completed = event.wait(timeout=max_wait)

        with self._pending_lock:
            pending = self._pending.pop(correlation_id, None)

        if completed and pending and pending['result'] is not None:
            return pending['result']

        return {
            'success': False,
            'error': f'Order handler timeout after {max_wait}s'
        }

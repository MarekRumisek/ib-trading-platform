"""Dedicated Order Handler for Flask Applications

This module provides a thread-safe order handler that runs in its own
event loop, isolated from Flask's worker threads. This ensures IB API
callbacks are properly received and processed.

Author: Perplexity AI Assistant
Version: 1.0.0
"""

import threading
import asyncio
from queue import Queue
import time
from typing import Optional, Dict, Any
from ib_connector import IBConnector
import config

class OrderHandler:
    """Thread-safe order handler with dedicated event loop."""
    
    def __init__(self, ib_connector: IBConnector):
        """Initialize handler with IB connector.
        
        Args:
            ib_connector: Connected IBConnector instance
        """
        self.ib = ib_connector
        self.order_queue = Queue()
        self.result_queue = Queue()
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        
    def start(self):
        """Start the order handler thread."""
        if self.running:
            return
            
        self.running = True
        self.thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self.thread.start()
        
        if config.DEBUG_ORDERS:
            print("✅ Order handler thread started")
    
    def stop(self):
        """Stop the order handler thread."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)
            
        if config.DEBUG_ORDERS:
            print("🛑 Order handler thread stopped")
    
    def _run_event_loop(self):
        """Run dedicated event loop in this thread."""
        # Create new event loop for this thread
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        if config.DEBUG_ORDERS:
            print(f"🔄 Order handler event loop started (thread: {threading.current_thread().name})")
        
        try:
            while self.running:
                # Check for new orders
                if not self.order_queue.empty():
                    order_data = self.order_queue.get()
                    result = self._process_order(order_data)
                    self.result_queue.put(result)
                else:
                    time.sleep(0.01)  # Small sleep to avoid busy waiting
        finally:
            self.loop.close()
    
    def _process_order(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process order in this thread's event loop.
        
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
            print(f"\n🔧 Processing order in handler thread: {action} {quantity} {symbol}")
        
        # Place order using IB connector
        # This runs in our dedicated event loop, not Flask's
        result = self.ib.place_order(
            symbol=symbol,
            action=action,
            quantity=quantity,
            order_type=order_type,
            limit_price=limit_price,
            timeout=timeout
        )
        
        return result
    
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
        max_wait = timeout + 5  # Extra buffer
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

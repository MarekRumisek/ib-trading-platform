"""Sync Module - Synchronizes IB positions with local trades.json

This module provides:
- Initial sync on app startup
- Periodic background sync every 30 seconds
- Detection of externally closed trades (closed in TWS)
- Updating entry_price/avg_cost from IB positions

The sync ensures that:
1. Local trades.json reflects the true state from IB Gateway
2. Externally closed trades (via TWS or SL/TP) are marked as closed
3. entry_price and avg_cost are populated from IB positions
"""

import threading
import time
import logging
from typing import Optional

import ib_gateway
from modules.trade_tracker import trade_tracker
from contract_utils import normalize_asset_type

logger = logging.getLogger('sync')
_D = '[SYNC]'


class SyncState:
    """Thread-safe state for sync operations."""
    
    def __init__(self):
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_sync_time: Optional[float] = None
        self._last_positions_count: int = 0
        self._last_externally_closed: int = 0
    
    @property
    def running(self) -> bool:
        with self._lock:
            return self._running
    
    @running.setter
    def running(self, value: bool):
        with self._lock:
            self._running = value
    
    @property
    def last_sync_time(self) -> Optional[float]:
        with self._lock:
            return self._last_sync_time
    
    @last_sync_time.setter
    def last_sync_time(self, value: float):
        with self._lock:
            self._last_sync_time = value
    
    @property
    def last_positions_count(self) -> int:
        with self._lock:
            return self._last_positions_count
    
    @last_positions_count.setter
    def last_positions_count(self, value: int):
        with self._lock:
            self._last_positions_count = value
    
    @property
    def last_externally_closed(self) -> int:
        with self._lock:
            return self._last_externally_closed
    
    @last_externally_closed.setter
    def last_externally_closed(self, value: int):
        with self._lock:
            self._last_externally_closed = value


# Global sync state
_sync_state = SyncState()


def sync_ib_positions() -> dict:
    """
    Synchronize IB positions with local trades.json.
    
    This function:
    1. Gets all IB positions via ib_gateway.get_positions()
    2. Gets all local open trades via trade_tracker.get_open_trades()
    3. For each local open trade:
       a. Finds corresponding IB position by symbol + asset_type
       b. If IB position exists: updates avg_cost from IB, sets entry_price if null
       c. If IB position does NOT exist but local trade is "open": 
          closes the trade as "closed_externally"
    
    Returns:
        dict with sync results: {
            'positions_synced': int,
            'externally_closed': int,
            'errors': list
        }
    """
    result = {
        'positions_synced': 0,
        'externally_closed': 0,
        'imported': 0,
        'errors': []
    }
    
    # Check IB connection
    if not ib_gateway.is_connected():
        logger.warning(f"{_D} IB not connected, skipping sync")
        result['errors'].append('IB not connected')
        return result
    
    try:
        # Get IB positions
        ib_positions = ib_gateway.get_positions()
        if ib_positions is None:
            ib_positions = []
        
        # Build lookup dict for IB positions by symbol+asset_type
        ib_pos_by_key = {}
        for pos in ib_positions:
            sym = pos.get('symbol', '').upper()
            asset_type = normalize_asset_type(pos.get('asset_type', 'STOCK'))
            key = f"{sym}_{asset_type}"
            ib_pos_by_key[key] = pos
        
        logger.info(f"{_D} IB has {len(ib_positions)} position(s), looking for {len(ib_pos_by_key)} unique")
        
        # Get local open trades
        local_trades = trade_tracker.get_open_trades()
        logger.info(f"{_D} Local open trades: {len(local_trades)}")
        
        externally_closed = []
        matched_ib_keys = set()  # Track IB positions that were matched to local trades
        
        for trade in local_trades:
            sym = trade.get('symbol', '').upper()
            asset_type = normalize_asset_type(trade.get('asset_type', 'STOCK'))
            trade_id = trade.get('id')
            key = f"{sym}_{asset_type}"
            
            ib_pos = ib_pos_by_key.get(key)
            
            if ib_pos:
                # IB position exists - update local trade
                # Note: IB positions use avg_cost, market_price (underscores)
                avg_cost = ib_pos.get('avg_cost')
                market_price = ib_pos.get('market_price')
                
                updates = {}
                
                # Update avg_cost from IB if available
                if avg_cost and avg_cost > 0:
                    updates['avg_cost'] = avg_cost
                    
                    # If entry_price is null or 0, set from IB avg_cost
                    if not trade.get('entry_price') or trade.get('entry_price') == 0:
                        updates['entry_price'] = avg_cost
                        logger.info(f"{_D} Setting entry_price={avg_cost} for {sym} from IB avg_cost")
                
                if updates:
                    try:
                        trade_tracker.update_trade(trade_id, **updates)
                        result['positions_synced'] += 1
                    except Exception as e:
                        err = f"Failed to update trade {trade_id}: {e}"
                        logger.error(f"{_D} {err}")
                        result['errors'].append(err)
                
                # Track this IB position as matched
                matched_ib_keys.add(key)
            else:
                # IB position does NOT exist - trade was closed externally
                # Use market price from IB portfolio if available, otherwise null
                exit_price = None
                
                # Try to get last known price for the symbol
                try:
                    ticker = ib_gateway.get_tick(sym, asset_type)
                    if ticker:
                        exit_price = ticker.get('price') or ticker.get('last')
                except Exception:
                    pass
                
                logger.info(f"{_D} Trade {trade_id} ({sym}) not in IB - marking as closed_externally @ {exit_price}")
                
                try:
                    # Close the trade with exit_price (may be None if not available)
                    trade_tracker.close_trade(trade_id, exit_price=exit_price)
                    
                    # Mark as closed_externally
                    trade_tracker.patch_trade(trade_id, {
                        'status': 'closed_externally',
                        'notes': f"Closed externally. IB position not found."
                    })
                    
                    externally_closed.append(trade_id)
                    result['externally_closed'] += 1
                except Exception as e:
                    err = f"Failed to close trade {trade_id}: {e}"
                    logger.error(f"{_D} {err}")
                    result['errors'].append(err)
        
        # Branch C: Import new IB positions that don't have local trades
        for key, ib_pos in ib_pos_by_key.items():
            if key in matched_ib_keys:
                continue  # Already matched with a local trade
            
            # This IB position has no corresponding local trade - import it
            sym = ib_pos.get('symbol', '').upper()
            asset_type = normalize_asset_type(ib_pos.get('asset_type', 'STOCK'))
            position = ib_pos.get('position', 0)
            avg_cost = ib_pos.get('avg_cost')
            
            if position == 0:
                continue  # Skip zero positions
            
            side = 'BUY' if position > 0 else 'SELL'
            
            try:
                trade_tracker.open_trade(
                    symbol=sym,
                    side=side,
                    qty=abs(position),
                    entry_price=avg_cost,
                    asset_type=asset_type,
                    note='imported_from_ib',
                    avg_cost=avg_cost
                )
                logger.info(f"{_D} IB Sync: IMPORTED {sym} from IB (not in trades.json)")
                result['imported'] += 1
            except Exception as e:
                err = f"Failed to import IB position {sym}: {e}"
                logger.error(f"{_D} {err}")
                result['errors'].append(err)
        
        # Log summary
        logger.info(
            f"{_D} Sync complete: {result['positions_synced']} positions synced, "
            f"{result['externally_closed']} externally closed, "
            f"{result['imported']} imported, "
            f"{len(result['errors'])} errors"
        )
        
        _sync_state.last_positions_count = len(ib_positions)
        _sync_state.last_externally_closed = result['externally_closed']
        _sync_state.last_sync_time = time.time()
        
    except Exception as e:
        err = f"Sync failed: {e}"
        logger.error(f"{_D} {err}")
        result['errors'].append(err)
    
    return result


def _sync_loop(interval: float = 30.0):
    """
    Background loop that runs sync_ib_positions() every `interval` seconds.
    
    Args:
        interval: Seconds between syncs (default 30)
    """
    logger.info(f"{_D} Sync loop started (interval={interval}s)")
    
    # Initial sync on startup
    logger.info(f"{_D} Running initial sync...")
    sync_result = sync_ib_positions()
    logger.info(f"{_D} Initial sync result: {sync_result}")
    
    while _sync_state.running:
        time.sleep(interval)
        
        if not _sync_state.running:
            break
        
        try:
            sync_ib_positions()
        except Exception as e:
            logger.error(f"{_D} Sync loop error: {e}")
    
    logger.info(f"{_D} Sync loop stopped")


def start_sync_thread(interval: float = 30.0):
    """
    Start the background sync thread.
    
    Should be called after ib_gateway.connect() succeeds.
    
    Args:
        interval: Seconds between syncs (default 30)
    """
    global _sync_state
    
    if _sync_state.running:
        logger.warning(f"{_D} Sync thread already running")
        return
    
    _sync_state.running = True
    _sync_state.thread = threading.Thread(
        target=_sync_loop,
        args=(interval,),
        daemon=True,
        name="IB-Sync-Thread"
    )
    _sync_state.thread.start()
    logger.info(f"{_D} Sync thread started")


def stop_sync_thread():
    """Stop the background sync thread."""
    global _sync_state
    
    if not _sync_state.running:
        return
    
    _sync_state.running = False
    
    if _sync_state.thread and _sync_state.thread.is_alive():
        _sync_state.thread.join(timeout=5)
    
    logger.info(f"{_D} Sync thread stopped")


def get_sync_status() -> dict:
    """Get current sync status."""
    return {
        'running': _sync_state.running,
        'last_sync_time': _sync_state.last_sync_time,
        'last_positions_count': _sync_state.last_positions_count,
        'last_externally_closed': _sync_state.last_externally_closed
    }

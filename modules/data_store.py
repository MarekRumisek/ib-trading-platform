"""Thread-safe in-memory OHLCV cache with TTL per bar size.

Prevents hitting IB pacing limit (60 historical requests / 10 min)
by caching bars per (symbol, bar_size) key with configurable TTL.

Usage:
    from modules.data_store import ohlcv_cache
    bars = ohlcv_cache.get('AAPL', '5 mins')  # None if miss/expired
    ohlcv_cache.set('AAPL', '5 mins', bars)
"""

import threading
import time

# TTL in seconds per bar size - kratsi bar = kratsi cache
_TTL = {
    '1 min':   60,
    '5 mins':  120,
    '15 mins': 300,
    '30 mins': 600,
    '1 hour':  1800,
    '1 day':   3600,
}
_DEFAULT_TTL = 120


class OHLCVCache:
    """Thread-safe in-memory cache for OHLCV bar data."""

    def __init__(self):
        # key: (symbol_upper, bar_size) -> {'bars': [...], 'ts': float}
        self._cache: dict = {}
        self._lock = threading.Lock()

    def get(self, symbol: str, bar_size: str):
        """Return cached bars if still within TTL, else None."""
        key = (symbol.upper(), bar_size)
        with self._lock:
            entry = self._cache.get(key)
            if not entry:
                return None
            ttl = _TTL.get(bar_size, _DEFAULT_TTL)
            if time.time() - entry['ts'] > ttl:
                del self._cache[key]
                return None
            return entry['bars']

    def set(self, symbol: str, bar_size: str, bars: list):
        """Store bars in cache with current timestamp."""
        if not bars:
            return
        key = (symbol.upper(), bar_size)
        with self._lock:
            self._cache[key] = {'bars': bars, 'ts': time.time()}

    def invalidate(self, symbol: str = None, bar_size: str = None):
        """Invalidate cache entries.
        - No args: clear everything
        - symbol only: clear all bar sizes for that symbol
        - bar_size only: clear that bar size for all symbols
        - both: clear specific entry
        """
        with self._lock:
            if symbol is None and bar_size is None:
                self._cache.clear()
                return
            to_del = [
                k for k in self._cache
                if (symbol is None or k[0] == symbol.upper())
                and (bar_size is None or k[1] == bar_size)
            ]
            for k in to_del:
                del self._cache[k]

    def stats(self) -> dict:
        """Return current cache stats (for debug)."""
        now = time.time()
        with self._lock:
            entries = []
            for (sym, bs), entry in self._cache.items():
                ttl    = _TTL.get(bs, _DEFAULT_TTL)
                age    = now - entry['ts']
                entries.append({
                    'symbol':   sym,
                    'bar_size': bs,
                    'bars':     len(entry['bars']),
                    'age_s':    round(age, 1),
                    'ttl_s':    ttl,
                    'valid':    age <= ttl
                })
        return {'count': len(entries), 'entries': entries}


# Singleton - importuj vsude jako: from modules.data_store import ohlcv_cache
ohlcv_cache = OHLCVCache()

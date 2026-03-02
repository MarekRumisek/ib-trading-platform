"""Thread-safe in-memory OHLCV cache with TTL per bar size,
plus Parquet-based incremental cache for long-term storage and Deep Load.

Prevents hitting IB pacing limit.
"""

import threading
import time
import os
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

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
        if not bars:
            return
        key = (symbol.upper(), bar_size)
        with self._lock:
            self._cache[key] = {'bars': bars, 'ts': time.time()}

    def invalidate(self, symbol: str = None, bar_size: str = None):
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

# Parquet Store
class ParquetDataStore:
    def __init__(self, data_dir='data/ohlcv'):
        self.data_dir = data_dir
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir, exist_ok=True)
        self._lock = threading.Lock()

    def _get_filename(self, symbol, timeframe):
        tf_clean = timeframe.replace(' ', '_')
        return os.path.join(self.data_dir, f"{symbol}_{tf_clean}.parquet")

    def get_cache_status(self, symbol, timeframe):
        filename = self._get_filename(symbol, timeframe)
        if not os.path.exists(filename):
            return {'cached': False, 'total_bars': 0, 'age_seconds': 999999999, 'is_fresh': False}
        
        try:
            mtime = os.path.getmtime(filename)
            age = time.time() - mtime
            fresh_threshold = _TTL.get(timeframe, _DEFAULT_TTL)
            
            pq_file = pq.ParquetFile(filename)
            return {
                'cached': True, 
                'total_bars': pq_file.metadata.num_rows, 
                'age_seconds': age, 
                'is_fresh': age < fresh_threshold
            }
        except Exception:
            return {'cached': False, 'total_bars': 0, 'age_seconds': 999999999, 'is_fresh': False}

    def get_bars(self, symbol, timeframe):
        filename = self._get_filename(symbol, timeframe)
        if not os.path.exists(filename):
            return []
        with self._lock:
            try:
                table = pq.read_table(filename)
                df = table.to_pandas()
                df = df.sort_values('time').drop_duplicates(subset=['time'], keep='last')
                return df.to_dict('records')
            except Exception as e:
                print(f"[PARQUET] Error reading {filename}: {e}")
                return []

    def append_bars(self, symbol, timeframe, new_bars):
        if not new_bars: return
        filename = self._get_filename(symbol, timeframe)
        new_df = pd.DataFrame(new_bars)
        
        with self._lock:
            try:
                if os.path.exists(filename):
                    old_df = pq.read_table(filename).to_pandas()
                    combined_df = pd.concat([old_df, new_df])
                else:
                    combined_df = new_df
                    
                combined_df = combined_df.sort_values('time').drop_duplicates(subset=['time'], keep='last')
                table = pa.Table.from_pandas(combined_df)
                pq.write_table(table, filename)
            except Exception as e:
                print(f"[PARQUET] Error writing {filename}: {e}")

ohlcv_cache = OHLCVCache()
data_store = ParquetDataStore()
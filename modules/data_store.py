"""Thread-safe in-memory OHLCV cache with TTL per bar size,
plus Parquet-based incremental cache for long-term storage and Deep Load.

Prevents hitting IB pacing limit.

Fixes v1.1:
  - Atomicky zapis Parquet (write temp -> rename) -> zadna korupce pri crashu
  - pa.Table.from_pandas(..., preserve_index=False) -> zadny __index_level_0__ sloupec
  - get_bars() vraci time jako Python int -> bezpecna JSON serializace
"""

import os
import threading
import time

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

# TTL in seconds per bar size
_TTL = {
    '1 min':   60,
    '5 mins':  120,
    '15 mins': 300,
    '30 mins': 600,
    '1 hour':  1800,
    '1 day':   3600,
}
_DEFAULT_TTL = 120

# Parquet schema - explicitni typy, zadne surprisy
_SCHEMA = pa.schema([
    pa.field('time',   pa.int64()),
    pa.field('open',   pa.float64()),
    pa.field('high',   pa.float64()),
    pa.field('low',    pa.float64()),
    pa.field('close',  pa.float64()),
    pa.field('volume', pa.float64()),
])


# ======================================================
# In-memory cache (krátkodobá, TTL per bar size)
# ======================================================
class OHLCVCache:
    """Thread-safe in-memory cache for OHLCV bar data."""

    def __init__(self):
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
                ttl = _TTL.get(bs, _DEFAULT_TTL)
                age = now - entry['ts']
                entries.append({
                    'symbol':   sym,
                    'bar_size': bs,
                    'bars':     len(entry['bars']),
                    'age_s':    round(age, 1),
                    'ttl_s':    ttl,
                    'valid':    age <= ttl
                })
        return {'count': len(entries), 'entries': entries}


# ======================================================
# Parquet Store (dlouhodobá cache na disku)
# ======================================================
class ParquetDataStore:
    def __init__(self, data_dir: str = 'data/ohlcv'):
        self.data_dir = data_dir
        os.makedirs(self.data_dir, exist_ok=True)
        self._lock = threading.Lock()

    # --------------------------------------------------
    # Helpers
    # --------------------------------------------------
    def _get_filename(self, symbol: str, timeframe: str) -> str:
        tf_clean = timeframe.replace(' ', '_')
        return os.path.join(self.data_dir, f"{symbol.upper()}_{tf_clean}.parquet")

    def _df_to_table(self, df: pd.DataFrame) -> pa.Table:
        """Převod DataFrame na PyArrow Table se správným schematem.
        preserve_index=False zabraňuje zápisu pandas indexu jako extra sloupce.
        """
        # Zajisti spravne sloupce a typy
        for col in ['open', 'high', 'low', 'close', 'volume']:
            if col in df.columns:
                df[col] = df[col].astype(float)
        df['time'] = df['time'].astype('int64')
        return pa.Table.from_pandas(df[list(_SCHEMA.names)],
                                    schema=_SCHEMA,
                                    preserve_index=False)

    def _write_atomic(self, table: pa.Table, filename: str):
        """Atomický zápis: write -> temp soubor -> os.replace().
        Pokud proces spadne uprostřed zápisu, cílový soubor zůstane neporušen.
        """
        tmp = filename + '.tmp'
        try:
            pq.write_table(table, tmp,
                           compression='snappy',
                           write_statistics=False)
            os.replace(tmp, filename)   # atomická operace na všech OS
        except Exception:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            raise

    # --------------------------------------------------
    # Public API
    # --------------------------------------------------
    def get_cache_status(self, symbol: str, timeframe: str) -> dict:
        filename = self._get_filename(symbol, timeframe)
        if not os.path.exists(filename):
            return {'cached': False, 'total_bars': 0,
                    'age_seconds': 999_999_999, 'is_fresh': False}
        try:
            mtime = os.path.getmtime(filename)
            age   = time.time() - mtime
            fresh_threshold = _TTL.get(timeframe, _DEFAULT_TTL)
            pq_file = pq.ParquetFile(filename)
            return {
                'cached':     True,
                'total_bars': pq_file.metadata.num_rows,
                'age_seconds': age,
                'is_fresh':   age < fresh_threshold
            }
        except Exception:
            return {'cached': False, 'total_bars': 0,
                    'age_seconds': 999_999_999, 'is_fresh': False}

    def get_bars(self, symbol: str, timeframe: str) -> list:
        """Načte bary z Parquet a vrátí jako list diktů.
        'time' je vždy Python int (bezpečné pro JSON serializaci).
        """
        filename = self._get_filename(symbol, timeframe)
        if not os.path.exists(filename):
            return []
        with self._lock:
            try:
                df = pq.read_table(filename).to_pandas()
                df = (df.sort_values('time')
                        .drop_duplicates(subset=['time'], keep='last')
                        .reset_index(drop=True))
                # Explicitni konverze: numpy int64 -> Python int
                # Flask jsonify bez problemu, JS dostane cislo (ne stringy)
                df['time'] = df['time'].astype('int64')
                records = df.to_dict('records')
                for r in records:
                    r['time'] = int(r['time'])
                return records
            except Exception as e:
                print(f"[PARQUET] Error reading {filename}: {e}")
                return []

    def append_bars(self, symbol: str, timeframe: str, new_bars: list):
        """Přidá nové bary do Parquet souboru (merge + dedup + atomický zápis)."""
        if not new_bars:
            return
        filename = self._get_filename(symbol, timeframe)
        new_df   = pd.DataFrame(new_bars)

        with self._lock:
            try:
                if os.path.exists(filename):
                    old_df = pq.read_table(filename).to_pandas()
                    combined_df = pd.concat([old_df, new_df], ignore_index=True)
                else:
                    combined_df = new_df.copy()

                combined_df = (combined_df
                               .sort_values('time')
                               .drop_duplicates(subset=['time'], keep='last')
                               .reset_index(drop=True))

                table = self._df_to_table(combined_df)
                self._write_atomic(table, filename)
            except Exception as e:
                print(f"[PARQUET] Error writing {filename}: {e}")


# Globální instance
ohlcv_cache = OHLCVCache()
data_store  = ParquetDataStore()

"""Persistent JSON configuration store for IB Trading Platform.

Thread-safe read/write of user preferences to data/config.json.
Uses atomic write (tmp + os.replace) to prevent corruption.
"""

import json
import os
import tempfile
import threading

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'config.json')

_DEFAULTS = {
    'default_symbol': 'AAPL',
    'default_quantity': 1,
    'default_timeframe': '5 mins',
    'default_asset_type': 'STOCK',
    'default_exchange': 'SMART',
    'favorite_symbols': ['AAPL', 'EURUSD'],
    'openrouter_api_key': '',
    'llm_model': 'minimax/minimax-m2.5:free',
    'strategy_text': '',
    'mm_rules_text': '',
    'ai_max_bars_per_chart': 100,
}


class ConfigStore:
    """Thread-safe persistent config backed by a JSON file."""

    def __init__(self, path: str = _CONFIG_PATH):
        self._path = path
        self._lock = threading.Lock()
        self._data: dict = {}
        self.load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, key: str, default=None):
        """Return config value for *key*, falling back to *default*."""
        with self._lock:
            return self._data.get(key, _DEFAULTS.get(key, default))

    def set(self, key: str, value) -> None:
        """Set a single config value and persist to disk."""
        with self._lock:
            self._data[key] = value
        self.save()

    def get_all(self) -> dict:
        """Return a shallow copy of the full config (defaults merged)."""
        with self._lock:
            merged = dict(_DEFAULTS)
            merged.update(self._data)
            return merged

    def load(self) -> None:
        """Load config from disk.  Missing file → use defaults."""
        with self._lock:
            if os.path.isfile(self._path):
                try:
                    with open(self._path, 'r', encoding='utf-8') as f:
                        self._data = json.load(f)
                except (json.JSONDecodeError, OSError):
                    self._data = {}
            else:
                self._data = {}

    def save(self) -> None:
        """Persist current config to disk (atomic write)."""
        with self._lock:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            # Write to temp file, then atomic replace
            fd, tmp_path = tempfile.mkstemp(
                dir=os.path.dirname(self._path), suffix='.tmp'
            )
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    json.dump(self._data, f, indent=2, ensure_ascii=False)
                os.replace(tmp_path, self._path)
            except Exception:
                # Clean up temp file on failure
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise


# Module-level singleton
config_store = ConfigStore()

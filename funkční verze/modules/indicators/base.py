"""Base class for all indicator plugins."""
from abc import ABC, abstractmethod


class BaseIndicator(ABC):
    """Abstract base class for all technical indicators.

    Každý indikátor přijme seznam OHLCV barů a vrátí seznam diktů
    s klíčem 'time' a jednou nebo více hodnotami indikátoru.

    Bars format: [{'time': str, 'open': float, 'high': float,
                   'low': float, 'close': float, 'volume': float}, ...]
    """

    name: str = ""

    def __init__(self, **params):
        self.params = params

    @abstractmethod
    def calculate(self, bars: list) -> list:
        """Vypočítá hodnoty indikátoru ze seznamu OHLCV barů.

        Args:
            bars: List diktů s klíči time, open, high, low, close, volume.

        Returns:
            List diktů s 'time' a hodnotami indikátoru (None = nedostatek dat).
        """
        pass

    def _closes(self, bars: list) -> list:
        return [float(b['close']) for b in bars]

    def _times(self, bars: list) -> list:
        return [b['time'] for b in bars]

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.params})"

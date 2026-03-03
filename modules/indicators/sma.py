"""Simple Moving Average (SMA) indicator."""
from .base import BaseIndicator


class SMA(BaseIndicator):
    """Jednoduchý klouzavý průměr.

    Args:
        period: Počet period pro výpočet průměru (default 20).
    """

    name = "SMA"

    def __init__(self, period: int = 20):
        super().__init__(period=period)
        self.period = period

    def calculate(self, bars: list) -> list:
        closes = self._closes(bars)
        times = self._times(bars)
        result = []
        for i in range(len(closes)):
            if i < self.period - 1:
                result.append({'time': times[i], 'value': None})
            else:
                avg = sum(closes[i - self.period + 1:i + 1]) / self.period
                result.append({'time': times[i], 'value': round(avg, 4)})
        return result

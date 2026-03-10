"""Exponential Moving Average (EMA) indicator."""
from .base import BaseIndicator


class EMA(BaseIndicator):
    """Exponenciální klouzavý průměr.

    Args:
        period: Počet period (default 20).
    """

    name = "EMA"

    def __init__(self, period: int = 20):
        super().__init__(period=period)
        self.period = period

    def calculate(self, bars: list) -> list:
        closes = self._closes(bars)
        times = self._times(bars)
        k = 2 / (self.period + 1)
        ema = None
        result = []
        for i, (t, c) in enumerate(zip(times, closes)):
            if i < self.period - 1:
                result.append({'time': t, 'value': None})
            elif i == self.period - 1:
                ema = sum(closes[:self.period]) / self.period
                result.append({'time': t, 'value': round(ema, 4)})
            else:
                ema = c * k + ema * (1 - k)
                result.append({'time': t, 'value': round(ema, 4)})
        return result

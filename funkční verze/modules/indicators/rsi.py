"""Relative Strength Index (RSI) indicator."""
from .base import BaseIndicator


class RSI(BaseIndicator):
    """Index relativní síly.

    Args:
        period: Počet period (default 14).
    """

    name = "RSI"

    def __init__(self, period: int = 14):
        super().__init__(period=period)
        self.period = period

    def calculate(self, bars: list) -> list:
        closes = self._closes(bars)
        times = self._times(bars)

        if len(closes) < self.period + 1:
            return [{'time': t, 'value': None} for t in times]

        deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        gains  = [d if d > 0 else 0.0 for d in deltas]
        losses = [-d if d < 0 else 0.0 for d in deltas]

        avg_gain = sum(gains[:self.period]) / self.period
        avg_loss = sum(losses[:self.period]) / self.period

        result = [{'time': times[i], 'value': None} for i in range(self.period)]

        for i in range(self.period, len(closes)):
            avg_gain = (avg_gain * (self.period - 1) + gains[i - 1]) / self.period
            avg_loss = (avg_loss * (self.period - 1) + losses[i - 1]) / self.period
            if avg_loss == 0:
                rsi = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi = 100.0 - (100.0 / (1 + rs))
            result.append({'time': times[i], 'value': round(rsi, 2)})

        return result

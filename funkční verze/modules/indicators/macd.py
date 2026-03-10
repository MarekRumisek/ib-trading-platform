"""MACD - Moving Average Convergence Divergence indicator."""
from .base import BaseIndicator
from .ema import EMA


class MACD(BaseIndicator):
    """MACD indikátor: MACD linka, signal linka a histogram.

    Args:
        fast:   Perioda rychlé EMA (default 12).
        slow:   Perioda pomalé EMA (default 26).
        signal: Perioda signal linky EMA(MACD) (default 9).

    Vrací dikt s klíči: time, macd, signal, histogram
    """

    name = "MACD"

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9):
        super().__init__(fast=fast, slow=slow, signal=signal)
        self.fast   = fast
        self.slow   = slow
        self.signal = signal

    def calculate(self, bars: list) -> list:
        times    = self._times(bars)
        fast_ema = EMA(self.fast).calculate(bars)
        slow_ema = EMA(self.slow).calculate(bars)

        macd_line   = []
        signal_bars = []

        for i, t in enumerate(times):
            fv = fast_ema[i]['value']
            sv = slow_ema[i]['value']
            if fv is None or sv is None:
                macd_line.append({'time': t, 'value': None})
                signal_bars.append({'time': t, 'close': 0.0, 'open': 0.0,
                                    'high': 0.0, 'low': 0.0, 'volume': 0})
            else:
                val = round(fv - sv, 6)
                macd_line.append({'time': t, 'value': val})
                signal_bars.append({'time': t, 'close': val, 'open': val,
                                    'high': val, 'low': val, 'volume': 0})

        first_valid = next(
            (i for i, x in enumerate(macd_line) if x['value'] is not None), None
        )
        if first_valid is None:
            return [{'time': t, 'macd': None, 'signal': None, 'histogram': None}
                    for t in times]

        sig_values = EMA(self.signal).calculate(signal_bars[first_valid:])

        result = [
            {'time': times[i], 'macd': None, 'signal': None, 'histogram': None}
            for i in range(first_valid)
        ]
        for i, sv in enumerate(sig_values):
            m   = macd_line[first_valid + i]['value']
            s   = sv['value']
            h   = round(m - s, 6) if (m is not None and s is not None) else None
            result.append({
                'time':      times[first_valid + i],
                'macd':      m,
                'signal':    s,
                'histogram': h,
            })
        return result

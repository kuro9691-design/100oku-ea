from __future__ import annotations

from datetime import datetime
from typing import Sequence

from oku100.indicators import sma
from oku100.models import Bar
from stock.models import StockParams


def _index_at_or_before(bars: Sequence[Bar], cutoff: datetime) -> int:
    lo, hi = 0, len(bars)
    while lo < hi:
        mid = (lo + hi) // 2
        if bars[mid].timestamp <= cutoff:
            lo = mid + 1
        else:
            hi = mid
    return lo - 1


class IndexFilter:
    def __init__(self, index_bars: list[Bar], params: StockParams):
        self._bars = index_bars
        self._period = params.index_ma_period

    def is_favorable(self, as_of: datetime, direction: int) -> bool:
        index = _index_at_or_before(self._bars, as_of)
        if index < self._period - 1:
            return False
        ma = sma(self._bars, index, self._period)
        close = self._bars[index].close
        return close > ma if direction > 0 else close < ma

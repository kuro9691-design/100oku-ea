from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from oku100.indicators import atr, confirmed_pivots, slope, sma, trend_direction
from oku100.leak import AccessAudit, CausalSeries
from oku100.models import Bar, Direction
from stock.market_filter import IndexFilter, _index_at_or_before
from stock.models import StockParams


@dataclass
class StockSignal:
    timestamp: datetime
    direction: Direction
    signal_price: float
    atr_value: float
    actionable: bool
    reason: str


class StockPipeline:
    def __init__(self, params: StockParams, index_filter: IndexFilter | None = None):
        self.params = params
        self.index_filter = index_filter

    def evaluate(self, bars: list[Bar], as_of: datetime) -> StockSignal:
        index = _index_at_or_before(bars, as_of)
        if index < 0:
            raise ValueError(f"no bar at or before {as_of.isoformat()}")

        audit = AccessAudit(index)
        causal = CausalSeries(bars, index, audit)

        pivots = confirmed_pivots(causal, index, self.params.N_d1)
        trend = trend_direction(pivots)
        atr_val = atr(causal, index, self.params.atr_period)
        ma = sma(causal, index, self.params.trend_ma_period)
        ma_slope = slope(causal, index, self.params.trend_ma_period, 5)

        bar = causal[index]
        close = bar.close

        direction = Direction.NONE
        if trend == 1 and ma_slope > 0 and "long" in self.params.allowed_directions:
            direction = Direction.LONG
        elif trend == -1 and ma_slope < 0 and "short" in self.params.allowed_directions:
            direction = Direction.SHORT

        if direction is Direction.NONE:
            audit.assert_clean()
            return StockSignal(bar.timestamp, Direction.NONE, close, atr_val, False, "no_trend")

        dir_sign = 1 if direction is Direction.LONG else -1

        # B: price within sl_atr * ATR of trend MA (pullback zone)
        ma_dist = (close - ma) * dir_sign
        if ma_dist > self.params.sl_atr * max(atr_val, 1e-9):
            audit.assert_clean()
            return StockSignal(bar.timestamp, Direction.NONE, close, atr_val, False, "price_far_from_ma")

        # D: breakout beyond most recent confirmed pivot
        kind = "high" if direction is Direction.LONG else "low"
        pivot_candidates = [p for p in pivots if p.kind == kind]
        if not pivot_candidates:
            audit.assert_clean()
            return StockSignal(bar.timestamp, Direction.NONE, close, atr_val, False, "no_pivot")

        pivot = pivot_candidates[-1]
        breakout = (
            (direction is Direction.LONG and close > pivot.price)
            or (direction is Direction.SHORT and close < pivot.price)
        )
        if not breakout:
            audit.assert_clean()
            return StockSignal(bar.timestamp, Direction.NONE, close, atr_val, False, "no_breakout")

        # G: market filter via index
        if self.index_filter is not None and not self.index_filter.is_favorable(bar.timestamp, dir_sign):
            audit.assert_clean()
            return StockSignal(bar.timestamp, Direction.NONE, close, atr_val, False, "market_filter")

        audit.assert_clean()
        return StockSignal(bar.timestamp, direction, close, atr_val, True, "")

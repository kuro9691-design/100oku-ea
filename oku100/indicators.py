from __future__ import annotations

from bisect import bisect_left, bisect_right, insort
from statistics import fmean
from typing import Sequence

from .models import Bar, Pivot

_PIVOT_CACHE: dict[tuple[int, int], tuple[int, list[int], list[Pivot]]] = {}
_LINE_TOUCH_CACHE: dict[tuple[int, float, float], tuple[int, int, bool]] = {}
_PIVOT_PRICE_CACHE: dict[int, tuple[int, list[float]]] = {}
_SMA_CACHE: dict[tuple[int, int, int], float] = {}
_ATR_CACHE: dict[tuple[int, int, int], float] = {}


def true_range(bars: Sequence[Bar], index: int) -> float:
    bar = bars[index]
    if index == 0:
        return bar.high - bar.low
    previous = bars[index - 1].close
    return max(bar.high - bar.low, abs(bar.high - previous), abs(bar.low - previous))


def atr(bars: Sequence[Bar], index: int, period: int) -> float:
    source = getattr(bars, "_values", bars)
    if isinstance(source, list):
        key = (id(source), index, period)
        cached = _ATR_CACHE.get(key)
        if cached is None:
            start = max(0, index - period + 1)
            values = [true_range(source, i) for i in range(start, index + 1)]
            cached = fmean(values) if values else 0.0
            _ATR_CACHE[key] = cached
        return cached
    start = max(0, index - period + 1)
    values = [true_range(bars, i) for i in range(start, index + 1)]
    return fmean(values) if values else 0.0


def sma(bars: Sequence[Bar], index: int, period: int) -> float:
    source = getattr(bars, "_values", bars)
    if isinstance(source, list):
        key = (id(source), index, period)
        cached = _SMA_CACHE.get(key)
        if cached is None:
            start = max(0, index - period + 1)
            cached = fmean(bar.close for bar in source[start : index + 1])
            _SMA_CACHE[key] = cached
        return cached
    start = max(0, index - period + 1)
    return fmean(bar.close for bar in bars[start : index + 1])


def slope(bars: Sequence[Bar], index: int, period: int, window: int) -> float:
    previous = max(0, index - window)
    divisor = max(1, index - previous)
    return (sma(bars, index, period) - sma(bars, previous, period)) / divisor


def confirmed_pivots(bars: Sequence[Bar], end_index: int, width: int) -> list[Pivot]:
    source = getattr(bars, "_values", bars)
    key = (id(source), width)
    cached_end, confirmed_indexes, cached = _PIVOT_CACHE.get(
        key, (width * 2 - 1, [], [])
    )
    # Sequential scans only inspect newly confirmable pivot candidates.
    if end_index >= cached_end:
        start_candidate = max(width, cached_end - width + 1)
        stop_candidate = end_index - width
        for index in range(start_candidate, stop_candidate + 1):
            window = bars[index - width : index + width + 1]
            bar = bars[index]
            if bar.high == max(item.high for item in window) and sum(
                item.high == bar.high for item in window
            ) == 1:
                confirmed_indexes.append(index + width)
                cached.append(Pivot(index, bar.timestamp, bar.high, "high"))
            if bar.low == min(item.low for item in window) and sum(
                item.low == bar.low for item in window
            ) == 1:
                confirmed_indexes.append(index + width)
                cached.append(Pivot(index, bar.timestamp, bar.low, "low"))
        paired = sorted(zip(confirmed_indexes, cached), key=lambda item: item[1].index)
        confirmed_indexes[:] = [item[0] for item in paired]
        cached[:] = [item[1] for item in paired]
        _PIVOT_CACHE[key] = (end_index, confirmed_indexes, cached)
    if end_index >= cached_end:
        return cached
    usable = bisect_right(confirmed_indexes, end_index)
    return cached[:usable]


def trend_direction(pivots: Sequence[Pivot]) -> int:
    highs: list[Pivot] = []
    lows: list[Pivot] = []
    for pivot in reversed(pivots):
        target = highs if pivot.kind == "high" else lows
        if len(target) < 2:
            target.append(pivot)
        if len(highs) == 2 and len(lows) == 2:
            break
    if len(highs) < 2 or len(lows) < 2:
        return 0
    higher = highs[0].price >= highs[1].price and lows[0].price > lows[1].price
    lower = highs[0].price < highs[1].price and lows[0].price <= lows[1].price
    return 1 if higher else -1 if lower else 0


def recent_range(bars: Sequence[Bar], index: int, count: int) -> float:
    start = max(0, index - count + 1)
    sample = bars[start : index + 1]
    return max(bar.high for bar in sample) - min(bar.low for bar in sample)


def nearest_pivot_target(
    pivots: Sequence[Pivot], price: float, direction: int
) -> float | None:
    key = id(pivots)
    cached_length, prices = _PIVOT_PRICE_CACHE.get(key, (0, []))
    if cached_length > len(pivots):
        cached_length, prices = 0, []
    for pivot in pivots[cached_length:]:
        insort(prices, pivot.price)
    _PIVOT_PRICE_CACHE[key] = (len(pivots), prices)
    if direction > 0:
        index = bisect_right(prices, price)
        return prices[index] if index < len(prices) else None
    index = bisect_left(prices, price) - 1
    return prices[index] if index >= 0 else None


def line_touch_count(
    bars: Sequence[Bar],
    end_index: int,
    line: float,
    tolerance: float,
    limit: int | None = None,
) -> int:
    source = getattr(bars, "_values", bars)
    key = (id(source), round(line, 8), round(tolerance, 8))
    cached_end, count, touching = _LINE_TOUCH_CACHE.get(key, (-1, 0, False))
    if end_index < cached_end:
        cached_end, count, touching = -1, 0, False
    for index in range(cached_end + 1, end_index + 1):
        bar = bars[index]
        hit = bar.low - tolerance <= line <= bar.high + tolerance
        if hit and not touching:
            count += 1
            if limit is not None and count >= limit:
                return count
        touching = hit
    _LINE_TOUCH_CACHE[key] = (end_index, count, touching)
    return count

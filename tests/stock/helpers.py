from __future__ import annotations

from datetime import datetime, timedelta, timezone

from oku100.models import Bar


_BASE = datetime(2024, 1, 1, tzinfo=timezone.utc)


def make_bar(
    day: int,
    open_: float,
    high: float,
    low: float,
    close: float,
) -> Bar:
    return Bar(
        timestamp=_BASE + timedelta(days=day),
        open=open_,
        high=high,
        low=low,
        close=close,
    )


def flat_bar(day: int, price: float, spread: float = 0.5) -> Bar:
    return make_bar(day, price, price + spread, price - spread, price)


def trending_bars(count: int, start_price: float = 100.0, step: float = 1.0) -> list[Bar]:
    """単調上昇バー列。ダウ転換・ピボット生成テスト用。"""
    result = []
    for i in range(count):
        center = start_price + i * step
        result.append(
            Bar(
                timestamp=_BASE + timedelta(days=i),
                open=center - 0.3,
                high=center + 1.0,
                low=center - 1.0,
                close=center + 0.3,
            )
        )
    return result

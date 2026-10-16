from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import sin

from oku100.models import Bar


def bars(count: int, hours: int, phase: float = 0.0) -> list[Bar]:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    result = []
    for index in range(count):
        center = 100 + index * 0.08 + sin(index / 5 + phase) * 3
        result.append(
            Bar(
                timestamp=start + timedelta(hours=index * hours),
                open=center - 0.2,
                high=center + 0.8,
                low=center - 0.8,
                close=center + 0.2,
            )
        )
    return result

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from .models import Bar


def read_bars(path: str | Path) -> list[Bar]:
    rows: list[Bar] = []
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            rows.append(
                Bar(
                    timestamp=datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00")),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                )
            )
    validate_bars(rows)
    return rows


def validate_bars(bars: list[Bar]) -> None:
    if not bars:
        raise ValueError("OHLC series is empty")
    timestamps = [bar.timestamp for bar in bars]
    if timestamps != sorted(timestamps) or len(timestamps) != len(set(timestamps)):
        raise ValueError("timestamps must be strictly increasing")

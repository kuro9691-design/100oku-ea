from __future__ import annotations

from dataclasses import dataclass

from oku100.models import Direction


@dataclass(frozen=True)
class StockParams:
    symbol: str = "unknown"
    N_d1: int = 3
    atr_period: int = 14
    sl_atr: float = 2.0
    tp_atr: float = 4.0
    index_ma_period: int = 200
    trend_ma_period: int = 20
    max_hold_bars: int = 20
    allowed_directions: tuple[str, ...] = ("long", "short")
    exclude_slipped_from_metrics: bool = False


@dataclass(frozen=True)
class StockTrade:
    direction: Direction
    signal_index: int
    entry_index: int
    exit_index: int
    signal_price: float
    fill_price: float
    stop: float
    target: float
    exit_price: float
    pnl_r: float
    reason: str  # "stop" / "target" / "time_exit" / "end_of_data"
    slipped: bool

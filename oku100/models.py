from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class Direction(str, Enum):
    LONG = "long"
    SHORT = "short"
    NONE = "none"


@dataclass(frozen=True)
class Bar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float

    def __post_init__(self) -> None:
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError(f"invalid OHLC at {self.timestamp.isoformat()}")
        if self.low > self.high:
            raise ValueError(f"low exceeds high at {self.timestamp.isoformat()}")


@dataclass(frozen=True)
class Pivot:
    index: int
    timestamp: datetime
    price: float
    kind: str


@dataclass(frozen=True)
class Params:
    N_h1: int = 3
    N_h4: int = 3
    N_d1: int = 3
    k1: float = 0.6
    k2: float = 0.4
    k3: float = 3.0
    k4: float = 2.0
    m: int = 5
    slope_win: int = 5
    slope_flat: float = 0.05
    MinRR: float = 1.5
    line_touch_min: int = 2
    strong_line_touch_min: int = 3
    strong_pivot_reaction_atr: float = 1.0
    conf_thr: float = 60.0
    # Crypto profile: H1 20/80/720, H4 20/180, D1 30/140.
    h1_fast_ma_period: int = 20
    h1_slow_ma_period: int = 80
    h1_direction_ma_period: int = 720
    h4_fast_ma_period: int = 20
    h4_direction_ma_period: int = 180
    d1_fast_ma_period: int = 30
    d1_direction_ma_period: int = 140
    IS_CRYPTO: bool = True
    weekend_filter_enabled: bool = True
    economic_event_filter_enabled: bool = True
    atr_period: int = 14
    # Split take-profit (docs/execution_spec.md 7). 80 = 原典「4時間足80MA」;
    # zone reuses PH-06 (0.5%); buffer 0 = 原典「直下」 (7-4).
    # Off until T1 matches the source (1:1.8-1:3); see 報告_20261016_分割利確の実装.md 4.
    split_targets: bool = False
    # SL = latest H1 pivot confirmed by the bar before the fill (execution_spec 5-1).
    sl_at_fill: bool = True
    # Move a pending stop order to a newer, nearer H1 pivot (execution_spec 4-2).
    order_follow: bool = True
    h4_tp_ma_period: int = 80
    tp_zone_pct: float = 0.005
    tp_buffer_pct: float = 0.0

    @property
    def use_weekend_filter(self) -> bool:
        return self.weekend_filter_enabled and not self.IS_CRYPTO

    @property
    def use_economic_event_filter(self) -> bool:
        return self.economic_event_filter_enabled and not self.IS_CRYPTO


@dataclass
class Criterion:
    name: str
    passed: bool
    score: float
    evidence: str


@dataclass
class Decision:
    timestamp: datetime
    direction: Direction
    pattern: str
    confidence: float
    criteria: dict[str, Criterion]
    pass_reasons: list[str]
    warning_flags: list[str]
    entry: float | None
    stop: float | None
    target: float | None
    rr: float | None
    metadata: dict[str, Any] = field(default_factory=dict)
    # Split take-profit orders [(price, fraction)], nearest first (execution_spec 7).
    targets: list[tuple[float, float]] = field(default_factory=list)

    @property
    def actionable(self) -> bool:
        return self.direction is not Direction.NONE and not self.pass_reasons

    @property
    def clean_candidate(self) -> bool:
        return not self.warning_flags

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["timestamp"] = self.timestamp.isoformat()
        value["direction"] = self.direction.value
        return value


@dataclass(frozen=True)
class Trade:
    direction: Direction
    entry_index: int
    exit_index: int
    entry: float
    exit: float
    pnl_r: float
    reason: str
    # Partial exits [(exit_index, price, fraction, reason)] (execution_spec 7-2).
    legs: tuple = ()

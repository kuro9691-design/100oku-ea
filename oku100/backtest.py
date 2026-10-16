from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Mapping, Sequence

from .distribution import CANDIDATE_GATES, candidate_ready
from .models import Bar, Direction, Params, Trade
from .pipeline import DecisionPipeline, group_m15_by_hour  # noqa: F401 (re-exported)


@dataclass(frozen=True)
class Metrics:
    trades: int
    wins: int
    win_rate: float
    profit_factor: float | None
    total_r: float
    max_drawdown_r: float
    ambiguous: int = 0


@dataclass
class BacktestResult:
    in_sample: Metrics
    out_of_sample: Metrics
    split_timestamp: datetime
    params: Params
    trades: list[Trade]

    def to_dict(self) -> dict:
        return {
            "in_sample": asdict(self.in_sample),
            "out_of_sample": asdict(self.out_of_sample),
            "split_timestamp": self.split_timestamp.isoformat(),
            "params": asdict(self.params),
            "trades": [
                {**asdict(trade), "direction": trade.direction.value} for trade in self.trades
            ],
        }


def _find_index_at_or_after(bars: Sequence[Bar], date: datetime) -> int:
    """Binary search: first index where bars[i].timestamp >= date."""
    lo, hi = 0, len(bars)
    while lo < hi:
        mid = (lo + hi) // 2
        if bars[mid].timestamp < date:
            lo = mid + 1
        else:
            hi = mid
    return lo


def run_backtest(
    d1: Sequence[Bar],
    h4: Sequence[Bar],
    h1: Sequence[Bar],
    params: Params | None = None,
    *,
    split_ratio: float = 0.7,
    warmup: int = 100,
    eval_start: datetime | None = None,
    split_date: datetime | None = None,
    eval_end: datetime | None = None,
    m15: Sequence[Bar] | None = None,
    gate: str = "strict",
) -> BacktestResult:
    if not 0.5 <= split_ratio <= 0.9:
        raise ValueError("split_ratio must be between 0.5 and 0.9")
    if gate not in CANDIDATE_GATES:
        raise ValueError(f"unknown candidate gate: {gate!r}")
    pipeline = DecisionPipeline(params, m15=m15)
    m15_by_hour = pipeline._m15_by_hour
    trades: list[Trade] = []
    default_start = min(
        max(warmup, pipeline.params.h1_direction_ma_period + pipeline.params.N_h1 * 2),
        len(h1) - 1,
    )
    if eval_start is not None:
        start = max(default_start, _find_index_at_or_after(h1, eval_start))
    else:
        start = default_start
    if split_date is not None:
        split_index = _find_index_at_or_after(h1, split_date)
    else:
        split_index = int(len(h1) * split_ratio)
    split_timestamp = h1[min(split_index, len(h1) - 1)].timestamp
    index = start
    while index < len(h1) - 1:
        if eval_end is not None and h1[index].timestamp >= eval_end:
            break
        decision = pipeline.evaluate(d1, h4, h1, as_of=h1[index].timestamp)
        if not candidate_ready(decision, gate) or decision.stop is None or decision.target is None:
            index += 1
            continue
        trade = _resolve_trade(
            h1, index + 1, decision.direction, decision.entry, decision.stop, decision.target,
            m15_by_hour=m15_by_hour,
            # No H4 structure -> single target (execution_spec 7-1).
            targets=decision.targets or None,
        )
        if trade:
            trades.append(trade)
            index = trade.exit_index + 1
        else:
            index += 1
    is_trades = [trade for trade in trades if trade.entry_index < split_index]
    oos_trades = [trade for trade in trades if trade.entry_index >= split_index]
    return BacktestResult(
        in_sample=metrics(is_trades),
        out_of_sample=metrics(oos_trades),
        split_timestamp=split_timestamp,
        params=pipeline.params,
        trades=trades,
    )


def _targets_reached(bar: Bar, long: bool, remaining: Sequence[tuple[float, float]]) -> int:
    """Leading remaining targets (nearest first) reached by the bar."""
    count = 0
    for price, _ in remaining:
        if (bar.high >= price) if long else (bar.low <= price):
            count += 1
        else:
            break
    return count


def _bar_exit(
    bar: Bar, long: bool, stop: float, remaining: Sequence[tuple[float, float]], filled_at_open: bool,
) -> tuple[int, bool, bool]:
    """Exit on the bar where the stop order filled (docs/execution_spec.md 3-1, 7-2).

    Returns (targets_hit, stopped, needs_order). needs_order=True means OHLC
    alone cannot tell whether the stop came after the fill or before a target.
    """
    stop_hit = bar.low <= stop if long else bar.high >= stop
    hits = _targets_reached(bar, long, remaining)
    if not stop_hit and not hits:
        return 0, False, False
    if filled_at_open:
        if stop_hit and hits:
            return 0, True, True
        return hits, stop_hit, False
    # Filled mid-bar: targets lie beyond the fill, so reaching them is
    # necessarily after the fill. A stop touch may predate the fill.
    if hits and not stop_hit:
        return hits, False, False
    return 0, True, True


def _fill_bar_exit(
    bar: Bar, long: bool, entry: float, stop: float, remaining: Sequence[tuple[float, float]],
    m15_bars: Sequence[Bar] | None,
) -> tuple[int, bool, bool]:
    """Returns (targets_hit, stopped, ambiguous). Ambiguous remainders are conservatively stopped."""
    reaches = (lambda b: b.high >= entry) if long else (lambda b: b.low <= entry)
    at_open = (lambda b: b.open >= entry) if long else (lambda b: b.open <= entry)
    hits, stopped, needs_order = _bar_exit(bar, long, stop, remaining, at_open(bar))
    if not needs_order:
        return hits, stopped, False
    if m15_bars is None or len(m15_bars) != 4:
        return 0, True, True
    total = 0
    filled = False
    for sub in m15_bars:
        if not filled:
            if not reaches(sub):
                continue
            filled = True
            hits, stopped, needs_order = _bar_exit(sub, long, stop, remaining[total:], at_open(sub))
        else:
            hits, stopped, needs_order = _bar_exit(sub, long, stop, remaining[total:], True)
        if needs_order:
            return total, True, True
        total += hits
        if stopped:
            return total, True, False
        if total == len(remaining):
            return total, False, False
    if not filled:
        # M15 does not show the fill the H1 bar implies: treat as missing.
        return 0, True, True
    return total, False, False


def _resolve_trade(
    bars: Sequence[Bar],
    start_index: int,
    direction: Direction,
    entry: float | None,
    stop: float,
    target: float,
    *,
    m15_by_hour: Mapping[datetime, Sequence[Bar]] | None = None,
    targets: Sequence[tuple[float, float]] | None = None,
) -> Trade | None:
    """start_index is the bar after the fill bar; the fill bar is start_index - 1.

    Exits are examined from the fill bar itself (docs/execution_spec.md 3).
    `targets` [(price, fraction)] splits the exit (execution_spec 7-2); without
    it the whole position exits at `target`.
    """
    if entry is None:
        return None
    risk = abs(entry - stop)
    if risk == 0:
        return None
    long = direction is Direction.LONG
    remaining = list(targets) if targets else [(target, 1.0)]
    legs: list[tuple[int, float, float, str]] = []
    ambiguous = False
    fill_index = start_index - 1
    entry_index = max(fill_index, 0)
    exit_index = None
    if fill_index >= 0:
        fill_bar = bars[fill_index]
        m15_bars = m15_by_hour.get(fill_bar.timestamp) if m15_by_hour is not None else None
        hits, stopped, ambiguous = _fill_bar_exit(fill_bar, long, entry, stop, remaining, m15_bars)
        legs += [(fill_index, price, fraction, "target") for price, fraction in remaining[:hits]]
        remaining = remaining[hits:]
        if stopped:
            legs += [(fill_index, stop, fraction, "stop") for _, fraction in remaining]
            remaining = []
        if not remaining:
            exit_index = fill_index
    if exit_index is None:
        for index in range(start_index, len(bars)):
            bar = bars[index]
            # Same-bar ambiguity after the fill bar is resolved conservatively: stop first.
            if bar.low <= stop if long else bar.high >= stop:
                legs += [(index, stop, fraction, "stop") for _, fraction in remaining]
                remaining = []
            else:
                hits = _targets_reached(bar, long, remaining)
                legs += [(index, price, fraction, "target") for price, fraction in remaining[:hits]]
                remaining = remaining[hits:]
            if not remaining:
                exit_index = index
                break
    if exit_index is None:
        final = bars[-1].close
        legs += [(len(bars) - 1, final, fraction, "end_of_data") for _, fraction in remaining]
        exit_index = len(bars) - 1
    weight = sum(leg[2] for leg in legs)
    sign = 1 if long else -1
    pnl = sum(fraction * sign * (price - entry) / risk for _, price, fraction, _ in legs)
    exit_price = sum(price * fraction for _, price, fraction, _ in legs) / weight
    kinds = {leg[3] for leg in legs}
    if "end_of_data" in kinds:
        reason = "end_of_data"
    elif "stop" in kinds:
        reason = "stop_ambiguous" if ambiguous else ("partial_stop" if "target" in kinds else "stop")
    else:
        reason = "target"
    return Trade(direction, entry_index, exit_index, entry, exit_price, pnl, reason, tuple(legs))


def metrics(trades: Sequence[Trade]) -> Metrics:
    wins = sum(trade.pnl_r > 0 for trade in trades)
    gross_profit = sum(max(0.0, trade.pnl_r) for trade in trades)
    gross_loss = abs(sum(min(0.0, trade.pnl_r) for trade in trades))
    pf = gross_profit / gross_loss if gross_loss else None
    equity = 0.0
    peak = 0.0
    drawdown = 0.0
    for trade in trades:
        equity += trade.pnl_r
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return Metrics(
        trades=len(trades),
        wins=wins,
        win_rate=(wins / len(trades) * 100) if trades else 0.0,
        profit_factor=pf,
        total_r=sum(trade.pnl_r for trade in trades),
        max_drawdown_r=drawdown,
        ambiguous=sum(trade.reason == "stop_ambiguous" for trade in trades),
    )

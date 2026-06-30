from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Sequence

from oku100.backtest import Metrics, metrics
from oku100.models import Bar, Direction, Trade
from stock.market_filter import IndexFilter
from stock.models import StockParams, StockTrade
from stock.pipeline import StockPipeline


@dataclass
class StockBacktestResult:
    in_sample: Metrics
    out_of_sample: Metrics
    split_timestamp: datetime
    params: StockParams
    trades: list[StockTrade]

    def to_dict(self) -> dict:
        def trade_dict(t: StockTrade) -> dict:
            return {
                "direction": t.direction.value,
                "signal_index": t.signal_index,
                "entry_index": t.entry_index,
                "exit_index": t.exit_index,
                "signal_price": t.signal_price,
                "fill_price": t.fill_price,
                "stop": t.stop,
                "target": t.target,
                "exit_price": t.exit_price,
                "pnl_r": t.pnl_r,
                "reason": t.reason,
                "slipped": t.slipped,
            }

        return {
            "in_sample": asdict(self.in_sample),
            "out_of_sample": asdict(self.out_of_sample),
            "split_timestamp": self.split_timestamp.isoformat(),
            "params": asdict(self.params),
            "trades": [trade_dict(t) for t in self.trades],
            "slipped_count": sum(1 for t in self.trades if t.slipped),
        }


def _resolve_stock_trade(
    bars: list[Bar],
    signal_index: int,
    direction: Direction,
    atr_value: float,
    params: StockParams,
) -> StockTrade | None:
    if signal_index + 1 >= len(bars):
        return None

    entry_bar = bars[signal_index + 1]
    fill_price = entry_bar.open
    signal_price = bars[signal_index].close

    dir_sign = 1 if direction is Direction.LONG else -1
    risk = params.sl_atr * atr_value
    if risk <= 0:
        return None

    stop = fill_price - dir_sign * risk
    target = fill_price + dir_sign * params.tp_atr * atr_value

    max_exit = min(signal_index + 1 + params.max_hold_bars, len(bars))

    for index in range(signal_index + 1, max_exit):
        bar = bars[index]

        # Gap check: only for bars after the entry bar.
        # On the entry bar itself, fill_price == bar.open so stop/target
        # are always on opposite sides of open by construction.
        if index > signal_index + 1:
            open_past_stop = (
                bar.open <= stop if direction is Direction.LONG else bar.open >= stop
            )
            open_past_target = (
                bar.open >= target if direction is Direction.LONG else bar.open <= target
            )

            if open_past_stop and open_past_target:
                # Extreme gap through both — conservative: treat as stop
                pnl_r = (bar.open - fill_price) * dir_sign / risk
                return StockTrade(
                    direction=direction,
                    signal_index=signal_index,
                    entry_index=signal_index + 1,
                    exit_index=index,
                    signal_price=signal_price,
                    fill_price=fill_price,
                    stop=stop,
                    target=target,
                    exit_price=bar.open,
                    pnl_r=pnl_r,
                    reason="stop",
                    slipped=True,
                )

            if open_past_stop:
                pnl_r = (bar.open - fill_price) * dir_sign / risk
                return StockTrade(
                    direction=direction,
                    signal_index=signal_index,
                    entry_index=signal_index + 1,
                    exit_index=index,
                    signal_price=signal_price,
                    fill_price=fill_price,
                    stop=stop,
                    target=target,
                    exit_price=bar.open,
                    pnl_r=pnl_r,
                    reason="stop",
                    slipped=True,
                )

            if open_past_target:
                pnl_r = (bar.open - fill_price) * dir_sign / risk
                return StockTrade(
                    direction=direction,
                    signal_index=signal_index,
                    entry_index=signal_index + 1,
                    exit_index=index,
                    signal_price=signal_price,
                    fill_price=fill_price,
                    stop=stop,
                    target=target,
                    exit_price=bar.open,
                    pnl_r=pnl_r,
                    reason="target",
                    slipped=True,
                )

        # Normal intrabar SL/TP check
        stop_hit = bar.low <= stop if direction is Direction.LONG else bar.high >= stop
        target_hit = bar.high >= target if direction is Direction.LONG else bar.low <= target

        if stop_hit and target_hit:
            # Same-bar ambiguity: conservative → stop first
            return StockTrade(
                direction=direction,
                signal_index=signal_index,
                entry_index=signal_index + 1,
                exit_index=index,
                signal_price=signal_price,
                fill_price=fill_price,
                stop=stop,
                target=target,
                exit_price=stop,
                pnl_r=-1.0,
                reason="stop",
                slipped=False,
            )
        if stop_hit:
            return StockTrade(
                direction=direction,
                signal_index=signal_index,
                entry_index=signal_index + 1,
                exit_index=index,
                signal_price=signal_price,
                fill_price=fill_price,
                stop=stop,
                target=target,
                exit_price=stop,
                pnl_r=-1.0,
                reason="stop",
                slipped=False,
            )
        if target_hit:
            pnl_r = params.tp_atr / params.sl_atr
            return StockTrade(
                direction=direction,
                signal_index=signal_index,
                entry_index=signal_index + 1,
                exit_index=index,
                signal_price=signal_price,
                fill_price=fill_price,
                stop=stop,
                target=target,
                exit_price=target,
                pnl_r=pnl_r,
                reason="target",
                slipped=False,
            )

    # Time exit or end of data
    last_index = max_exit - 1
    final = bars[last_index]
    exit_price = final.close
    pnl_r = (exit_price - fill_price) * dir_sign / risk
    reason = (
        "time_exit"
        if signal_index + 1 + params.max_hold_bars <= len(bars)
        else "end_of_data"
    )
    return StockTrade(
        direction=direction,
        signal_index=signal_index,
        entry_index=signal_index + 1,
        exit_index=last_index,
        signal_price=signal_price,
        fill_price=fill_price,
        stop=stop,
        target=target,
        exit_price=exit_price,
        pnl_r=pnl_r,
        reason=reason,
        slipped=False,
    )


def _to_oku100_trade(trade: StockTrade) -> Trade:
    return Trade(
        direction=trade.direction,
        entry_index=trade.entry_index,
        exit_index=trade.exit_index,
        entry=trade.fill_price,
        exit=trade.exit_price,
        pnl_r=trade.pnl_r,
        reason=trade.reason,
    )


def _find_index_at_or_after(bars: Sequence[Bar], date: datetime) -> int:
    lo, hi = 0, len(bars)
    while lo < hi:
        mid = (lo + hi) // 2
        if bars[mid].timestamp < date:
            lo = mid + 1
        else:
            hi = mid
    return lo


def run_stock_backtest(
    bars: list[Bar],
    index_bars: list[Bar] | None = None,
    params: StockParams | None = None,
    *,
    split_date: datetime | None = None,
    split_ratio: float = 0.7,
    eval_start: datetime | None = None,
) -> StockBacktestResult:
    if not 0.5 <= split_ratio <= 0.9:
        raise ValueError("split_ratio must be between 0.5 and 0.9")

    params = params or StockParams()
    index_filter = IndexFilter(index_bars, params) if index_bars else None
    pipeline = StockPipeline(params, index_filter)

    warmup = max(params.N_d1 * 2 + params.atr_period, params.trend_ma_period)

    if eval_start is not None:
        start = max(warmup, _find_index_at_or_after(bars, eval_start))
    else:
        start = warmup

    if split_date is not None:
        split_index = _find_index_at_or_after(bars, split_date)
    else:
        split_index = int(len(bars) * split_ratio)

    split_timestamp = bars[min(split_index, len(bars) - 1)].timestamp

    trades: list[StockTrade] = []
    index = start
    while index < len(bars) - 1:
        signal = pipeline.evaluate(bars, bars[index].timestamp)
        if not signal.actionable:
            index += 1
            continue
        trade = _resolve_stock_trade(bars, index, signal.direction, signal.atr_value, params)
        if trade is not None:
            trades.append(trade)
            index = trade.exit_index + 1
        else:
            index += 1

    is_trades = [t for t in trades if t.entry_index < split_index]
    oos_trades = [t for t in trades if t.entry_index >= split_index]

    def _metrics(trade_list: list[StockTrade]) -> Metrics:
        if params.exclude_slipped_from_metrics:
            trade_list = [t for t in trade_list if not t.slipped]
        return metrics([_to_oku100_trade(t) for t in trade_list])

    return StockBacktestResult(
        in_sample=_metrics(is_trades),
        out_of_sample=_metrics(oos_trades),
        split_timestamp=split_timestamp,
        params=params,
        trades=trades,
    )

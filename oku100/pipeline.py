from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Sequence

from .indicators import (
    atr,
    confirmed_pivots,
    line_touch_count,
    recent_range,
    slope,
    sma,
    trend_direction,
)
from .leak import AccessAudit, CausalSeries
from .models import Bar, Criterion, Decision, Direction, Params, Pivot

_UNSET = object()


@dataclass
class TimeframeState:
    bars: Sequence[Bar]
    index: int
    pivots: list[Pivot]
    trend: int
    atr: float
    fast_ma: float
    fast_ma_slope: float
    slow_ma: float
    direction_ma: float
    direction_slope: float


def _nearest_qualifying_pivot(
    pivots: Sequence[Pivot], entry: float, direction: int, min_dist: float
) -> float | None:
    """Return the nearest pivot satisfying the minimum distance from entry."""
    best: float | None = None
    for pivot in pivots:
        dist = (pivot.price - entry) if direction > 0 else (entry - pivot.price)
        ok = dist >= min_dist if min_dist > 0 else dist > 0
        if ok:
            if best is None or (direction > 0 and pivot.price < best) or (direction < 0 and pivot.price > best):
                best = pivot.price
    return best


def group_m15_by_hour(m15: Sequence[Bar]) -> dict[datetime, list[Bar]]:
    """M15 bars keyed by the H1 bar (start time) that contains them."""
    grouped: dict[datetime, list[Bar]] = defaultdict(list)
    for bar in m15:
        grouped[bar.timestamp.replace(minute=0, second=0, microsecond=0)].append(bar)
    return dict(grouped)


def _latest_pivot_beyond(pivots: Sequence[Pivot], entry: float, direction: int) -> float | None:
    """Latest pivot low below entry (long) / pivot high above entry (short)."""
    kind = "low" if direction > 0 else "high"
    for pivot in reversed(pivots):
        if pivot.kind == kind and (
            (direction > 0 and pivot.price < entry)
            or (direction < 0 and pivot.price > entry)
        ):
            return pivot.price
    return None


class DecisionPipeline:
    def __init__(self, params: Params | None = None, *, m15: Sequence[Bar] | None = None):
        self.params = params or Params()
        self._d_setup_cache: dict[tuple[datetime, int], bool] = {}
        self._stop_order_cache: dict[tuple[int, int], dict] = {}
        self._reaction_cache: dict[tuple[int, int, str], float] = {}
        self._m15_by_hour = group_m15_by_hour(m15) if m15 is not None else None
        # docs/execution_spec.md 4-1: counts of pending-order cancellations.
        self.cancel_stats = {"cancelled": 0, "same_bar_resolved": 0, "same_bar_ambiguous": 0}

    def evaluate(
        self,
        d1: Sequence[Bar],
        h4: Sequence[Bar],
        h1: Sequence[Bar],
        *,
        as_of: datetime | None = None,
        vision_bonus: float = 0.0,
    ) -> Decision:
        cutoff = as_of or h1[-1].timestamp
        indexes = self._resolve_indexes(d1, h4, h1, cutoff)
        audits = [AccessAudit(index) for index in indexes]
        causal = [
            CausalSeries(series, index, audit) for series, index, audit in zip((d1, h4, h1), indexes, audits)
        ]
        d1s, h4s, h1s = self._states(causal, indexes)
        decision = self._decide(d1s, h4s, h1s, vision_bonus)
        for audit in audits:
            audit.assert_clean()
        decision.metadata["access_audit"] = {
            "D1": audits[0].max_accessed,
            "H4": audits[1].max_accessed,
            "H1": audits[2].max_accessed,
        }
        return decision

    @staticmethod
    def _resolve_indexes(
        d1: Sequence[Bar], h4: Sequence[Bar], h1: Sequence[Bar], cutoff: datetime
    ) -> list[int]:
        """[D1index, H4index, H1index] を返す。cutoffはH1足の開始時刻(例: 07:00は
        07:00-08:00を表す)。その終値が実際に確定するのは1時間後であり、D1・H4は
        この「確定時刻」を基準に当日/当該バケットの境界を判定しないと、境界をまたぐ
        足で未確定の日足・4時間足を参照してしまう(cutoffそのものを使うと、当日/現在
        バケットの未確定足を_index_at_or_beforeが拾ってしまう=先読みになる)。H1は
        自分自身の粒度なのでcutoffのまま扱う。leak_checkの横断チェック対象。"""
        confirmed_at = cutoff + timedelta(hours=1)
        d1_boundary = confirmed_at.replace(hour=0, minute=0, second=0, microsecond=0)
        h4_boundary = confirmed_at.replace(
            hour=(confirmed_at.hour // 4) * 4, minute=0, second=0, microsecond=0
        )
        return [
            DecisionPipeline._index_before(d1, d1_boundary),
            DecisionPipeline._index_before(h4, h4_boundary),
            DecisionPipeline._index_at_or_before(h1, cutoff),
        ]

    @staticmethod
    def _index_at_or_before(bars: Sequence[Bar], cutoff: datetime) -> int:
        low, high = 0, len(bars)
        while low < high:
            middle = (low + high) // 2
            if bars[middle].timestamp <= cutoff:
                low = middle + 1
            else:
                high = middle
        if low == 0:
            raise ValueError(f"no completed bar at {cutoff.isoformat()}")
        return low - 1

    @staticmethod
    def _index_before(bars: Sequence[Bar], boundary: datetime) -> int:
        """boundary(上位足の現在バケット開始時刻)より厳密に前の、最後に確定した足の
        indexを返す。_index_at_or_before と違い boundary 自体と一致する足(=まだ確定
        していない当日/現在バケットの足)は含めない。D1・H4の参照専用。"""
        low, high = 0, len(bars)
        while low < high:
            middle = (low + high) // 2
            if bars[middle].timestamp < boundary:
                low = middle + 1
            else:
                high = middle
        if low == 0:
            raise ValueError(f"no confirmed bar strictly before {boundary.isoformat()}")
        return low - 1

    def _states(
        self, series: Sequence[Sequence[Bar]], indexes: Sequence[int]
    ) -> tuple[TimeframeState, TimeframeState, TimeframeState]:
        """D1/H4/H1 states at the given (already causal) indexes."""
        p = self.params
        return (
            self._state(series[0], indexes[0], p.N_d1, p.d1_fast_ma_period, p.d1_direction_ma_period, p.d1_direction_ma_period),
            self._state(series[1], indexes[1], p.N_h4, p.h4_fast_ma_period, p.h4_direction_ma_period, p.h4_direction_ma_period),
            self._state(series[2], indexes[2], p.N_h1, p.h1_fast_ma_period, p.h1_slow_ma_period, p.h1_direction_ma_period),
        )

    def _state(
        self,
        bars: Sequence[Bar],
        index: int,
        width: int,
        fast_period: int,
        slow_period: int,
        direction_period: int,
    ) -> TimeframeState:
        pivots = confirmed_pivots(bars, index, width)
        return TimeframeState(
            bars=bars,
            index=index,
            pivots=pivots,
            trend=trend_direction(pivots),
            atr=atr(bars, index, self.params.atr_period),
            fast_ma=sma(bars, index, fast_period),
            fast_ma_slope=slope(bars, index, fast_period, self.params.slope_win),
            slow_ma=sma(bars, index, slow_period),
            direction_ma=sma(bars, index, direction_period),
            direction_slope=slope(bars, index, direction_period, self.params.slope_win),
        )

    def _decide(
        self, d1: TimeframeState, h4: TimeframeState, h1: TimeframeState, vision_bonus: float
    ) -> Decision:
        long_result = self._score_at_order_time(1, d1, h4, h1, vision_bonus)
        short_result = self._score_at_order_time(-1, d1, h4, h1, vision_bonus)
        chosen = long_result if long_result["confidence"] >= short_result["confidence"] else short_result
        direction = Direction.LONG if chosen["direction"] > 0 else Direction.SHORT
        warning_flags = chosen["warning_flags"]
        pass_reasons = []
        if chosen["confidence"] < self.params.conf_thr or not chosen["criteria"]["D"].passed:
            direction = Direction.NONE
            if chosen["confidence"] < self.params.conf_thr:
                pass_reasons.append("confidence_below_threshold")
            if not chosen["criteria"]["D"].passed:
                pass_reasons.append("trigger_D_not_confirmed")
        return Decision(
            timestamp=h1.bars[h1.index].timestamp,
            direction=direction,
            pattern=chosen["pattern"] if direction is not Direction.NONE else "該当なし",
            confidence=round(chosen["confidence"], 2),
            criteria=chosen["criteria"],
            pass_reasons=sorted(set(pass_reasons)),
            warning_flags=warning_flags,
            entry=chosen["entry"] if direction is not Direction.NONE else None,
            stop=chosen["stop"] if direction is not Direction.NONE else None,
            target=chosen["target"] if direction is not Direction.NONE else None,
            rr=chosen["rr"] if direction is not Direction.NONE else None,
            metadata={
                "candidate_direction": "long" if chosen["direction"] > 0 else "short",
                "all_direction_aligned": chosen["alignment"]["passed"],
                "alignment": chosen["alignment"],
                "clean_candidate": not warning_flags,
                "scored_at": chosen["scored_at"].isoformat(),
            },
        )

    def _score_at_order_time(
        self, direction: int, d1: TimeframeState, h4: TimeframeState, h1: TimeframeState, vision_bonus: float
    ) -> dict:
        """docs/execution_spec.md 5: on a fill bar only the fill itself is judged
        from that bar's open/high/low. Every criterion, the score, and the SL/TP
        structure come from the confirmed bars at the order's placement
        (placed_at), never from the fill bar's close or indicators."""
        fill = self._stop_entry_fill(h1, direction)
        if fill is None:
            result = self._score_direction(direction, d1, h4, h1, vision_bonus, stop_entry=None)
            result["scored_at"] = h1.bars[h1.index].timestamp
            return result
        placed_at = self._fill_placed_at(h1, direction)
        if placed_at is None:
            # Fill supplied without an order record (patched diagnostics).
            result = self._score_direction(direction, d1, h4, h1, vision_bonus, stop_entry=fill)
            result["scored_at"] = h1.bars[h1.index].timestamp
            return result
        try:
            cutoff = h1.bars[placed_at].timestamp
            indexes = self._resolve_indexes(d1.bars, h4.bars, h1.bars, cutoff)
            order_states = self._states((d1.bars, h4.bars, h1.bars), indexes)
        except ValueError:
            result = self._score_direction(direction, d1, h4, h1, vision_bonus, stop_entry=None)
            d = result["criteria"]["D"]
            d.evidence += ", order_time_state_unavailable"
            result["scored_at"] = h1.bars[h1.index].timestamp
            return result
        result = self._score_direction(direction, *order_states, vision_bonus, stop_entry=fill)
        result["scored_at"] = cutoff
        return result

    def _fill_placed_at(self, state: TimeframeState, direction: int) -> int | None:
        source = getattr(state.bars, "_values", state.bars)
        order = self._stop_order_cache.get((id(source), direction))
        if order is None:
            return None
        return order["fill_placed_at"].get(state.index)

    def _score_direction(
        self, direction: int, d1: TimeframeState, h4: TimeframeState, h1: TimeframeState, vision_bonus: float,
        *, stop_entry=_UNSET,
    ) -> dict:
        p = self.params
        close = h1.bars[h1.index].close
        criteria: dict[str, Criterion] = {}

        alignment = self._alignment(d1, h4, h1, direction)
        all_direction_aligned = alignment["passed"]
        a_pass = all_direction_aligned
        criteria["A"] = Criterion(
            "A",
            a_pass,
            15 if a_pass else 0,
            (
                f"D1={alignment['d1_matches']}, H4={alignment['h4_matches']}, "
                f"H1_turn={alignment['h1_matches']}, D1_MA_room={alignment['d1_ma_room']}, "
                f"D1_exception={alignment['d1_exception']}"
            ),
        )

        convergence = self._h1_convergence(h1)
        b_pass = convergence["contracted"] and convergence["near"]
        criteria["B"] = Criterion(
            "B",
            b_pass,
            12 if b_pass else 0,
            (
                f"H1_20_80_contracted={convergence['contracted']}, "
                f"min_distance_atr={convergence['min_distance_atr']:.4f}, "
                f"limit={p.k1}"
            ),
        )

        dev = abs(h4.direction_ma - d1.direction_ma)
        b2_direction = -1 if h4.direction_ma > d1.direction_ma else 1
        b2_pass = dev >= p.k4 * max(h4.atr, 1e-12) and direction == b2_direction
        criteria["B-2"] = Criterion("B-2", b2_pass, 12 if b2_pass else 0, f"dev_atr={dev / max(h4.atr, 1e-12):.2f}")

        structural = self._structural_line(h4, close, direction)
        c_pass = structural["touches"] >= p.line_touch_min and structural["near"]
        criteria["C"] = Criterion("C", c_pass, 12 if c_pass else 0, f"touches={structural['touches']}, near={structural['near']}")

        h1_ma = h1.fast_ma
        h4_ma_on_h1 = h1.slow_ma
        previous_index = max(0, h1.index - 1)
        band_now = abs(h1_ma - h4_ma_on_h1)
        band_prev = abs(
            sma(h1.bars, previous_index, p.h1_fast_ma_period)
            - sma(h1.bars, previous_index, p.h1_slow_ma_period)
        )
        if stop_entry is _UNSET:
            stop_entry = self._stop_entry_fill(h1, direction)
        breakout = stop_entry is not None
        ma720_slope_ok = h1.direction_slope * direction > 0
        d_pass = breakout and ma720_slope_ok
        criteria["D"] = Criterion(
            "D",
            d_pass,
            25 if d_pass else 0,
            (
                f"H1 trend={h1.trend}, expansion={band_now > band_prev}, "
                f"stop_entry_fill={breakout}, fill_price={stop_entry.price if stop_entry else None}, "
                f"ma720_slope={h1.direction_slope:.6f}"
            ),
        )

        h4_flow_matches = self._higher_timeframe_direction(h4, direction)
        e_pass = h4_flow_matches and h1.trend == direction and self._nested(h4, h1)
        criteria["E"] = Criterion(
            "E",
            e_pass,
            10 if e_pass else 0,
            f"H4_flow={h4_flow_matches}, H4/H1_dow={h4.trend}/{h1.trend}, nested={self._nested(h4, h1)}",
        )

        entry = stop_entry.price if stop_entry is not None else close
        stop = self._stop(h1, entry, direction)
        target = self._target(d1, h4, entry, direction, b2_pass, stop=stop, min_rr=p.MinRR)
        rr = self._rr(entry, stop, target)
        f_pass = rr is not None and rr >= p.MinRR
        criteria["F"] = Criterion("F", f_pass, 14 if f_pass else 0, f"RR={rr}")

        rapid = recent_range(h1.bars, h1.index, p.m) >= p.k3 * max(h1.atr, 1e-12)
        line_ahead = (
            structural["ahead"]
            and structural["near"]
            and structural["touches"] >= p.strong_line_touch_min
        )
        war = d1.trend not in (0, direction)
        war_exception = c_pass and b2_pass and d_pass and e_pass and f_pass
        h4_slope_norm = h4.direction_slope / h4.atr if h4.atr else 0
        immature = abs(h4_slope_norm) > p.slope_flat and not b_pass
        warning_flags = []
        if rapid:
            warning_flags.append("rapid_move")
        if line_ahead:
            warning_flags.append("strong_line_ahead")
        if war and not war_exception:
            warning_flags.append("war_state_without_exception")
        if immature:
            warning_flags.append("range_not_mature")
        g_pass = not warning_flags
        criteria["G"] = Criterion("G", g_pass, 0, ", ".join(warning_flags) or "clear")

        base = sum(item.score for item in criteria.values())
        confidence = min(100.0, base + max(0.0, min(vision_bonus, 10.0)))
        pattern = "乖離埋め" if b2_pass and war else "転換後の初押し/初戻し"
        return {
            "direction": direction,
            "criteria": criteria,
            "confidence": confidence,
            "warning_flags": warning_flags,
            "pattern": pattern,
            "entry": entry,
            "stop": stop,
            "target": target,
            "rr": rr,
            "alignment": alignment,
        }

    def _structural_line(self, state: TimeframeState, price: float, direction: int) -> dict:
        tolerance = self.params.k2 * max(state.atr, 1e-12)
        kind = "high" if direction > 0 else "low"
        strong = [
            pivot
            for pivot in state.pivots
            if pivot.kind == kind and self._pivot_reaction_atr(state, pivot) >= self.params.strong_pivot_reaction_atr
        ]
        candidates = [
            pivot.price
            for pivot in strong
            if (direction > 0 and pivot.price > price) or (direction < 0 and pivot.price < price)
        ]
        if not candidates:
            return {"line": None, "touches": 0, "near": False, "ahead": False}
        target = min(candidates) if direction > 0 else max(candidates)
        return {
            "line": target,
            "touches": sum(abs(pivot.price - target) <= tolerance for pivot in strong),
            "near": abs(target - price) <= tolerance,
            "ahead": (direction > 0 and target > price) or (direction < 0 and target < price),
        }

    def _pivot_reaction_atr(self, state: TimeframeState, pivot: Pivot) -> float:
        # A confirmed H4 pivot is a line candidate only when price clearly
        # rejected it during its causal confirmation window.
        end = min(state.index, pivot.index + self.params.N_h4)
        if end <= pivot.index:
            return 0.0
        raw_bars = getattr(state.bars, "_values", state.bars)
        stable = state.index >= pivot.index + self.params.N_h4
        reaction_key = (id(raw_bars), pivot.index, pivot.kind)
        if stable:
            cached = self._reaction_cache.get(reaction_key)
            if cached is not None:
                return cached
        pivot_atr = atr(state.bars, pivot.index, self.params.atr_period)
        if pivot_atr <= 0:
            if stable:
                self._reaction_cache[reaction_key] = 0.0
            return 0.0
        following = raw_bars[pivot.index + 1 : end + 1]
        reaction = (
            pivot.price - min(bar.low for bar in following)
            if pivot.kind == "high"
            else max(bar.high for bar in following) - pivot.price
        )
        result = reaction / pivot_atr
        if stable:
            self._reaction_cache[reaction_key] = result
        return result

    def _stop_entry_fill(self, state: TimeframeState, direction: int) -> Pivot | None:
        """Return a pending stop order filled by the current bar.

        A stop order becomes active after a completed H1 bar satisfies D's
        trend, expansion, and MA-order setup. A touch consumes the order, but
        a later completed setup may place a fresh order at the same
        still-valid pivot. Only the current bar is used for the fill check.
        The returned Pivot retains the source pivot's identity, but its price
        is the execution price: an opening gap cannot fill at a better level.
        An unfilled order is cancelled once price breaks the order-time stop
        level (docs/execution_spec.md 4-1).
        """
        source = getattr(state.bars, "_values", state.bars)
        key = (id(source), direction)
        order = self._stop_order_cache.setdefault(
            key,
            {
                "processed": -1,
                "active": None,
                "placed_at": -1,
                "previous_setup_ready": False,
                "fills": {},
                "fill_placed_at": {},
                "cancel_level": None,
            },
        )
        kind = "high" if direction > 0 else "low"
        for index in range(order["processed"] + 1, state.index + 1):
            bar = state.bars[index]
            active = order["active"]
            if active is not None and index > order["placed_at"]:
                reached = bar.high >= active.price if direction > 0 else bar.low <= active.price
                level = order["cancel_level"]
                broke = level is not None and (bar.low < level if direction > 0 else bar.high > level)
                filled = reached and (
                    not broke or self._fill_before_break(bar, active.price, level, direction)
                )
                if filled:
                    fill_price = (
                        max(active.price, bar.open)
                        if direction > 0 else min(active.price, bar.open)
                    )
                    order["fills"][index] = replace(active, price=fill_price)
                    order["fill_placed_at"][index] = order["placed_at"]
                    order["active"] = None
                elif broke:
                    order["active"] = None
                    self.cancel_stats["cancelled"] += 1
            setup_ready = self._d_setup_ready_at(state.bars, index, direction)
            if setup_ready and not order["previous_setup_ready"]:
                pivots = confirmed_pivots(state.bars, index, self.params.N_h1)
                pivot = next((item for item in reversed(pivots) if item.kind == kind), None)
                if pivot is not None:
                    line_ahead = pivot.price > bar.close if direction > 0 else pivot.price < bar.close
                    if line_ahead:
                        order["active"] = pivot
                        order["placed_at"] = index
                        order["cancel_level"] = _latest_pivot_beyond(pivots, pivot.price, direction)
            order["previous_setup_ready"] = setup_ready
            order["processed"] = index
        return order["fills"].get(state.index)

    def _fill_before_break(self, bar: Bar, price: float, level: float, direction: int) -> bool:
        """Order of fill vs. stop-level break within one H1 bar (execution_spec 4-1).

        Unresolvable cases count as ambiguous and are treated as filled: the
        fill bar then also reaches the stop, which section 3 scores as a loss.
        """
        long = direction > 0

        def reaches(b: Bar) -> bool:
            return b.high >= price if long else b.low <= price

        def breaks(b: Bar) -> bool:
            return b.low < level if long else b.high > level

        def opens_filled(b: Bar) -> bool:
            return b.open >= price if long else b.open <= price

        def opens_broken(b: Bar) -> bool:
            return b.open < level if long else b.open > level

        if opens_filled(bar) or opens_broken(bar):
            self.cancel_stats["same_bar_resolved"] += 1
            return opens_filled(bar)
        subs = self._m15_by_hour.get(bar.timestamp) if self._m15_by_hour is not None else None
        if subs is not None and len(subs) == 4:
            for sub in subs:
                sub_reach, sub_break = reaches(sub), breaks(sub)
                if sub_reach and sub_break:
                    if opens_filled(sub) or opens_broken(sub):
                        self.cancel_stats["same_bar_resolved"] += 1
                        return opens_filled(sub)
                    break
                if sub_reach or sub_break:
                    self.cancel_stats["same_bar_resolved"] += 1
                    return sub_reach
        self.cancel_stats["same_bar_ambiguous"] += 1
        return True

    def _d_setup_ready_at(self, bars: Sequence[Bar], index: int, direction: int) -> bool:
        if index <= 0:
            return False
        key = (bars[index].timestamp, direction)
        cached = self._d_setup_cache.get(key)
        if cached is not None:
            return cached
        p = self.params
        pivots = confirmed_pivots(bars, index, p.N_h1)
        trend = trend_direction(pivots)
        fast = sma(bars, index, p.h1_fast_ma_period)
        slow = sma(bars, index, p.h1_slow_ma_period)
        previous_band = abs(
            sma(bars, index - 1, p.h1_fast_ma_period)
            - sma(bars, index - 1, p.h1_slow_ma_period)
        )
        band = abs(fast - slow)
        ma_ordered = (direction > 0 and fast > slow) or (direction < 0 and fast < slow)
        ready = trend == direction and band > previous_band and ma_ordered
        self._d_setup_cache[key] = ready
        return ready

    def _breakout(self, state: TimeframeState, close: float, direction: int) -> bool:
        # Compatibility helper for diagnostics; breakout is now a causal
        # pending-stop fill rather than a close beyond the pivot.
        return self._stop_entry_fill(state, direction) is not None

    @staticmethod
    def _nested(h4: TimeframeState, h1: TimeframeState) -> bool:
        if not h4.pivots or not h1.pivots:
            return False
        h4_start = h4.pivots[-2].timestamp if len(h4.pivots) > 1 else h4.pivots[-1].timestamp
        return bool(h1.pivots and h1.pivots[-1].timestamp >= h4_start)

    @staticmethod
    def _stop(state: TimeframeState, entry: float, direction: int) -> float | None:
        return _latest_pivot_beyond(state.pivots, entry, direction)

    @staticmethod
    def _target(
        d1: TimeframeState, h4: TimeframeState,
        entry: float, direction: int, divergence: bool,
        stop: float | None = None, min_rr: float = 0.0,
    ) -> float | None:
        risk = abs(entry - stop) if stop is not None else 0.0
        min_dist = risk * min_rr if risk > 0 else 0.0
        if divergence:
            target = d1.direction_ma
            dist = (target - entry) if direction > 0 else (entry - target)
            if dist > 0 and (min_dist <= 0 or dist >= min_dist):
                return target
        candidates = [
            _nearest_qualifying_pivot(d1.pivots, entry, direction, min_dist),
            _nearest_qualifying_pivot(h4.pivots, entry, direction, min_dist),
        ]
        valid = [v for v in candidates if v is not None]
        if not valid:
            return None
        return min(valid) if direction > 0 else max(valid)

    @staticmethod
    def _ma_direction(state: TimeframeState, direction: int) -> bool:
        close = state.bars[state.index].close
        price_side = close >= state.direction_ma if direction > 0 else close <= state.direction_ma
        slope_side = state.direction_slope >= 0 if direction > 0 else state.direction_slope <= 0
        return price_side and slope_side

    @staticmethod
    def _higher_timeframe_direction(state: TimeframeState, direction: int) -> bool:
        # 原典は上位足の方向をダウ理論と短期MA傾きで把握する。
        # 両方の完全一致は要求せず、いずれかが方向を示せばよい。
        return state.trend == direction or state.fast_ma_slope * direction > 0

    @staticmethod
    def _h1_has_turned(state: TimeframeState, direction: int) -> bool:
        # 小さな流れが上位足方向へ転換した瞬間は、H1ダウ転換で確認する。
        return state.trend == direction

    def _h1_convergence(self, h1: TimeframeState) -> dict[str, float | bool]:
        """原典B: H1 20SMAがH1 80SMA（H4 MA相当）へ収束したか。"""
        start = max(0, h1.index - self.params.slope_win)
        distances = [
            abs(
                sma(h1.bars, index, self.params.h1_fast_ma_period)
                - sma(h1.bars, index, self.params.h1_slow_ma_period)
            )
            for index in range(start, h1.index + 1)
        ]
        minimum = min(distances)
        minimum_atr = minimum / max(h1.atr, 1e-12)
        return {
            "contracted": minimum < distances[0],
            "near": minimum_atr <= self.params.k1,
            "min_distance": minimum,
            "min_distance_atr": minimum_atr,
        }

    def _alignment(
        self, d1: TimeframeState, h4: TimeframeState, h1: TimeframeState, direction: int
    ) -> dict[str, bool]:
        """原典1-1〜1-3: D1/H4の流れへH1が転換して合致する。"""
        d1_matches = self._higher_timeframe_direction(d1, direction)
        h4_matches = self._higher_timeframe_direction(h4, direction)
        h1_matches = self._h1_has_turned(h1, direction)
        close = h1.bars[h1.index].close
        d1_ma_room = (
            (direction > 0 and d1.fast_ma > close)
            or (direction < 0 and d1.fast_ma < close)
        )
        d1_exception = not d1_matches and d1_ma_room
        return {
            "passed": h4_matches and h1_matches and (d1_matches or d1_exception),
            "d1_matches": d1_matches,
            "h4_matches": h4_matches,
            "h1_matches": h1_matches,
            "d1_ma_room": d1_ma_room,
            "d1_exception": d1_exception,
        }

    @staticmethod
    def _rr(entry: float, stop: float | None, target: float | None) -> float | None:
        if stop is None or target is None or entry == stop:
            return None
        return abs(target - entry) / abs(entry - stop)

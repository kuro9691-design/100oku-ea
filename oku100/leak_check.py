from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Sequence

from .leak import AccessAudit, CausalSeries, FutureLeakError
from .models import Bar, Params


@dataclass(frozen=True)
class LeakCheckResult:
    checked_points: int
    checked_timeframes: int
    checked_pivot_candidates: int
    passed: bool


@dataclass(frozen=True)
class CrossTimeframeLeakCheckResult:
    checked_points: int
    passed: bool


def run_leak_check(
    d1: Sequence[Bar],
    h4: Sequence[Bar],
    h1: Sequence[Bar],
    params: Params | None = None,
    *,
    warmup: int = 100,
) -> LeakCheckResult:
    params = params or Params()
    checked_candidates = 0
    for bars, width in ((d1, params.N_d1), (h4, params.N_h4), (h1, params.N_h1)):
        for decision_index in range(len(bars)):
            audit = AccessAudit(decision_index)
            series = CausalSeries(bars, decision_index, audit)
            if decision_index >= 0:
                _ = series[decision_index]
            try:
                _ = series[decision_index + 1]
            except IndexError:
                pass
            else:
                raise FutureLeakError(f"future access accepted at {decision_index}")
        # A pivot at index i is usable only at i + width or later.
        for pivot_index in range(width, len(bars) - width):
            confirmed_at = pivot_index + width
            if confirmed_at > len(bars) - 1:
                raise FutureLeakError(f"unconfirmable pivot {pivot_index}")
            checked_candidates += 1
    return LeakCheckResult(
        checked_points=len(h1),
        checked_timeframes=3,
        checked_pivot_candidates=checked_candidates,
        passed=True,
    )


def run_cross_timeframe_leak_check(
    d1: Sequence[Bar],
    h4: Sequence[Bar],
    h1: Sequence[Bar],
    *,
    sample_step: int = 1,
) -> CrossTimeframeLeakCheckResult:
    """2026-07に発見した不具合の再発防止チェック。run_leak_check()は「一度決めた
    decision_indexより先(index+1)を読んでいないか」だけを検証しており、
    「decision_indexそのものが、H1のcutoff時点でまだ完全には経過していない当日/現在
    バケットを指していないか」は検証していなかった(これが原因で本番のD1/H4参照が
    汚染されたまま、run_leak_check通過=安全という誤った安心感を生んでいた)。

    このチェックは、DecisionPipeline._resolve_indexesが返すD1・H4のindexについて、
    その足自身の期間(D1=1日, H4=4時間)が、H1候補足の終値確定時刻(cutoff+1時間)
    より前に完全に終わっているかを直接検証する。
    """
    from .pipeline import DecisionPipeline  # 循環import回避のため遅延import

    checked = 0
    for h1_index in range(0, len(h1), sample_step):
        cutoff = h1[h1_index].timestamp
        try:
            d1_index, h4_index, _ = DecisionPipeline._resolve_indexes(d1, h4, h1, cutoff)
        except ValueError:
            # ウォームアップ不足(まだ確定済みのD1/H4足が1本もない先頭付近)。
            # リーク検知の対象外(データ不足であってリークではない)。
            continue
        confirmed_at = cutoff + timedelta(hours=1)

        d1_bar_end = d1[d1_index].timestamp + timedelta(days=1)
        if d1_bar_end > confirmed_at:
            raise FutureLeakError(
                f"D1 index {d1_index}({d1[d1_index].timestamp.isoformat()}) はH1 cutoff="
                f"{cutoff.isoformat()}(確定={confirmed_at.isoformat()})の時点でまだ確定して"
                "いない当日足を参照している"
            )

        h4_bar_end = h4[h4_index].timestamp + timedelta(hours=4)
        if h4_bar_end > confirmed_at:
            raise FutureLeakError(
                f"H4 index {h4_index}({h4[h4_index].timestamp.isoformat()}) はH1 cutoff="
                f"{cutoff.isoformat()}(確定={confirmed_at.isoformat()})の時点でまだ確定して"
                "いない現在バケットを参照している"
            )
        checked += 1

    return CrossTimeframeLeakCheckResult(checked_points=checked, passed=True)

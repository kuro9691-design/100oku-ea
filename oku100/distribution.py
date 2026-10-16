from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from statistics import fmean
from typing import Sequence

from .leak import AccessAudit, CausalSeries
from .models import Bar, Decision, Params
from .pipeline import DecisionPipeline


@dataclass(frozen=True)
class SignalDistribution:
    evaluated_points: int
    categories: dict[str, int]
    entry_confidence_min: float | None
    entry_confidence_max: float | None
    entry_confidence_mean: float | None
    entry_above_threshold: int
    direction_aligned_count: int
    direction_aligned_percent: float
    confidence_threshold: float

    def to_dict(self) -> dict:
        return self.__dict__.copy()


CANDIDATE_GATES = ("strict", "actionable")


def candidate_ready(decision: Decision, gate: str = "strict") -> bool:
    """Single candidate judgement shared by scan_distribution and run_backtest
    (docs/execution_spec.md 6). strict is the adopted gate (2026-10-16);
    actionable is kept for reference only.

    strict:     A AND (B OR B-2) AND C/D/E/F (distribution's entry candidate)
    actionable: score >= conf_thr and D (run_backtest's historical entry)
    """
    if gate == "strict":
        return entry_candidate_ready(decision)
    if gate == "actionable":
        return decision.actionable
    raise ValueError(f"unknown candidate gate: {gate!r} (expected one of {CANDIDATE_GATES})")


def classify(decision: Decision, gate: str = "strict") -> str:
    criteria = decision.criteria
    if candidate_ready(decision, gate):
        return "entry_candidate"
    if criteria["D"].passed:
        return "trend_reversal"
    if criteria["A"].passed:
        return "pullback_wait"
    return "pass"


def entry_candidate_ready(decision: Decision) -> bool:
    criteria = decision.criteria
    return (
        decision.metadata.get("all_direction_aligned", False)
        and criteria["A"].passed
        and (criteria["B"].passed or criteria["B-2"].passed)
        and all(criteria[name].passed for name in ("C", "D", "E", "F"))
    )


def scan_distribution(
    d1: Sequence[Bar],
    h4: Sequence[Bar],
    h1: Sequence[Bar],
    params: Params | None = None,
    *,
    gate: str = "strict",
) -> SignalDistribution:
    if gate not in CANDIDATE_GATES:
        raise ValueError(f"unknown candidate gate: {gate!r}")
    pipeline = DecisionPipeline(params)
    warmup = pipeline.params.h1_direction_ma_period
    counts: Counter[str] = Counter()
    confidences: list[float] = []
    aligned = 0
    evaluated = 0
    for index in range(warmup, len(h1)):
        cutoff = h1[index].timestamp
        # Same confirmed-bar resolution as evaluate(): no unfinished D1/H4 bar.
        indexes = pipeline._resolve_indexes(d1, h4, h1, cutoff)
        causal = [
            CausalSeries(series, point, AccessAudit(point))
            for series, point in zip((d1, h4, h1), indexes)
        ]
        d1s, h4s, h1s = pipeline._states(causal, indexes)
        a_passes = []
        d_passes = []
        for direction in (1, -1):
            direction_aligned = pipeline._alignment(d1s, h4s, h1s, direction)["passed"]
            a_passes.append(direction_aligned)
            d_passes.append(pipeline._breakout(h1s, h1s.bars[h1s.index].close, direction))
            if direction_aligned:
                aligned += 1
                break
        if any(d_passes) or any(a_passes):
            decision = pipeline._decide(d1s, h4s, h1s, 0.0)
            category = classify(decision, gate)
        else:
            decision = None
            category = "pass"
        counts[category] += 1
        if category == "entry_candidate":
            assert decision is not None
            confidences.append(decision.confidence)
        evaluated += 1
    return SignalDistribution(
        evaluated_points=evaluated,
        categories={
            "entry_candidate": counts["entry_candidate"],
            "pullback_wait": counts["pullback_wait"],
            "trend_reversal": counts["trend_reversal"],
            "pass": counts["pass"],
        },
        entry_confidence_min=min(confidences) if confidences else None,
        entry_confidence_max=max(confidences) if confidences else None,
        entry_confidence_mean=fmean(confidences) if confidences else None,
        entry_above_threshold=sum(value >= pipeline.params.conf_thr for value in confidences),
        direction_aligned_count=aligned,
        direction_aligned_percent=(aligned / evaluated * 100) if evaluated else 0.0,
        confidence_threshold=pipeline.params.conf_thr,
    )

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Iterable, Sequence

from .backtest import BacktestResult, run_backtest
from .models import Bar, Params


@dataclass(frozen=True)
class OptimizationResult:
    params: Params
    backtest: BacktestResult
    robust_score: float

    def to_dict(self) -> dict:
        return {
            "params": self.backtest.to_dict()["params"],
            "robust_score": self.robust_score,
            "backtest": self.backtest.to_dict(),
        }


def compact_grid(base: Params | None = None) -> Iterable[Params]:
    base = base or Params()
    for n_h1, n_h4, n_d1, k1, k2, k3, k4, min_rr in product(
        (2, 3, 4),
        (2, 3, 4),
        (2, 3),
        (0.4, 0.6, 0.8),
        (0.3, 0.5),
        (2.5, 3.5),
        (1.5, 2.5, 3.5),
        (1.25, 1.5, 2.0),
    ):
        yield Params(
            **{
                **base.__dict__,
                "N_h1": n_h1,
                "N_h4": n_h4,
                "N_d1": n_d1,
                "k1": k1,
                "k2": k2,
                "k3": k3,
                "k4": k4,
                "MinRR": min_rr,
            }
        )


def optimize(
    d1: Sequence[Bar],
    h4: Sequence[Bar],
    h1: Sequence[Bar],
    candidates: Iterable[Params],
    *,
    top_k: int = 10,
) -> list[OptimizationResult]:
    results: list[OptimizationResult] = []
    for params in candidates:
        backtest = run_backtest(d1, h4, h1, params)
        is_m = backtest.in_sample
        oos_m = backtest.out_of_sample
        if is_m.trades < 3 or oos_m.trades < 2 or oos_m.total_r <= 0:
            continue
        stability = min(is_m.total_r, oos_m.total_r) - abs(is_m.win_rate - oos_m.win_rate) / 20
        results.append(OptimizationResult(params, backtest, round(stability, 4)))
    return sorted(results, key=lambda item: item.robust_score, reverse=True)[:top_k]

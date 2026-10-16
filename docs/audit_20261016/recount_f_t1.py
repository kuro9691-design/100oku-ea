"""Full-period recount after judging F by RR to T1 with a 1:1 minimum (execution_spec 7-5).

Read-only: loads data/*.csv, prints and writes counts comparable with
recount_follow.json (F on _target with MinRR 1.5). Performance numbers are for
reference only and are not used to adopt or tune the rule.
"""
import json
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from oku100.backtest import run_backtest  # noqa: E402
from oku100.distribution import candidate_ready  # noqa: E402
from oku100.io import read_bars  # noqa: E402
from oku100.models import Direction, Params  # noqa: E402
from oku100.pipeline import DecisionPipeline  # noqa: E402


def load():
    return [read_bars(ROOT / "data" / f"{name}.csv") for name in ("d1", "h4", "h1", "m15")]


def scan():
    d1, h4, h1, m15 = load()
    pipeline = DecisionPipeline(Params(split_targets=True), m15=m15)
    p = pipeline.params
    start = min(max(100, p.h1_direction_ma_period + p.N_h1 * 2), len(h1) - 1)
    strict = {"long": 0, "short": 0}
    target_counts = Counter()
    first_rr = []
    for index in range(start, len(h1) - 1):
        decision = pipeline.evaluate(d1, h4, h1, as_of=h1[index].timestamp)
        if not candidate_ready(decision, "strict"):
            continue
        strict["long" if decision.direction is Direction.LONG else "short"] += 1
        target_counts[len(decision.targets)] += 1
        evidence = decision.criteria["F"].evidence
        if evidence.startswith("RR_T1="):
            value = evidence.split(",")[0].split("=")[1]
            first_rr.append(None if value == "None" else float(value))
    rr = sorted(v for v in first_rr if v is not None)
    return {
        "strict": strict,
        "strict_total": sum(strict.values()),
        "targets_per_candidate": {str(k): v for k, v in sorted(target_counts.items())},
        "fallback_single_target": target_counts[0],
        "t1_rr": {
            "n": len(rr),
            "median": rr[len(rr) // 2] if rr else None,
            "below_1": sum(v < 1 for v in rr),
            "below_1_5": sum(v < 1.5 for v in rr),
            "from_1_to_1_8": sum(1 <= v < 1.8 for v in rr),
            "from_1_8_to_3": sum(1.8 <= v <= 3 for v in rr),
            "above_3": sum(v > 3 for v in rr),
            "quartiles": [rr[len(rr) // 4], rr[len(rr) // 2], rr[3 * len(rr) // 4]] if rr else None,
        },
        "cancel_stats": pipeline.cancel_stats,
    }


def backtest(gate, split):
    d1, h4, h1, m15 = load()
    result = run_backtest(d1, h4, h1, Params(split_targets=split), m15=m15, gate=gate)
    trades = result.trades
    wins = sum(1 for t in trades if t.pnl_r > 0)
    return {
        "gate": gate,
        "split_targets": split,
        "trades": len(trades),
        "reasons": dict(Counter(t.reason for t in trades)),
        "legs_per_trade": dict(Counter(len(t.legs) for t in trades)),
        "ambiguous": sum(1 for t in trades if t.reason == "stop_ambiguous"),
        "win_rate": wins / len(trades) if trades else None,
        "avg_r": sum(t.pnl_r for t in trades) / len(trades) if trades else None,
        "total_r": sum(t.pnl_r for t in trades),
        "max_drawdown_r": _drawdown(trades),
    }


def _drawdown(trades):
    equity = peak = drawdown = 0.0
    for trade in trades:
        equity += trade.pnl_r
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return drawdown


def main():
    began = time.time()
    with ProcessPoolExecutor(max_workers=4) as pool:
        scan_job = pool.submit(scan)
        bt_jobs = [
            pool.submit(backtest, gate, split)
            for gate, split in (("strict", False), ("strict", True), ("actionable", False))
        ]
        out = {"scan": scan_job.result(), "backtests": [job.result() for job in bt_jobs]}
    before = Path(__file__).with_name("recount_follow.json")
    out["before_f_t1"] = json.loads(before.read_text(encoding="utf-8"))
    out["elapsed_sec"] = round(time.time() - began)
    path = Path(__file__).with_name("recount_f_t1.json")
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

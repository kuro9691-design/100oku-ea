"""Full-period recount after the pending-order cancel rule (execution_spec 4-1).

Read-only: loads data/*.csv, prints and writes counts comparable with
100億j_share/報告_20261008_執行仕様と執行修正.md section 1.
"""
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from oku100.backtest import run_backtest  # noqa: E402
from oku100.distribution import candidate_ready  # noqa: E402
from oku100.io import read_bars  # noqa: E402
from oku100.models import Direction  # noqa: E402
from oku100.pipeline import DecisionPipeline  # noqa: E402


def load():
    return [read_bars(ROOT / "data" / f"{name}.csv") for name in ("d1", "h4", "h1", "m15")]


def scan():
    d1, h4, h1, m15 = load()
    pipeline = DecisionPipeline(m15=m15)
    p = pipeline.params
    start = min(max(100, p.h1_direction_ma_period + p.N_h1 * 2), len(h1) - 1)
    strict = {"long": 0, "short": 0}
    actionable = actionable_sltp = 0
    for index in range(start, len(h1) - 1):
        decision = pipeline.evaluate(d1, h4, h1, as_of=h1[index].timestamp)
        if candidate_ready(decision, "strict"):
            strict["long" if decision.direction is Direction.LONG else "short"] += 1
        if candidate_ready(decision, "actionable"):
            actionable += 1
            if decision.stop is not None and decision.target is not None:
                actionable_sltp += 1
    return {
        "strict": strict,
        "strict_total": sum(strict.values()),
        "actionable": actionable,
        "actionable_with_sl_tp": actionable_sltp,
        "cancel_stats": pipeline.cancel_stats,
    }


def backtest(gate):
    d1, h4, h1, m15 = load()
    result = run_backtest(d1, h4, h1, m15=m15, gate=gate)
    trades = result.trades
    wins = sum(1 for t in trades if t.pnl_r > 0)
    return {
        "gate": gate,
        "trades": len(trades),
        "ambiguous": sum(1 for t in trades if t.reason == "stop_ambiguous"),
        "win_rate": wins / len(trades) if trades else None,
        "avg_r": sum(t.pnl_r for t in trades) / len(trades) if trades else None,
    }


def main():
    began = time.time()
    with ProcessPoolExecutor(max_workers=3) as pool:
        scan_job = pool.submit(scan)
        bt_jobs = [pool.submit(backtest, gate) for gate in ("actionable", "strict")]
        out = {"scan": scan_job.result(), "backtests": [job.result() for job in bt_jobs]}
    out["elapsed_sec"] = round(time.time() - began)
    path = Path(__file__).with_name("recount_cancel_rule.json")
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

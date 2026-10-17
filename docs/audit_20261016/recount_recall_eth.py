"""Source recall on BTC and the same definition on ETH (definitions frozen).

Read-only: loads data/*.csv. Two jobs in parallel:
- BTC: full-period strict candidates with timestamps and criteria, so they
  can be matched against the source BTC trades (realtrade_btc.csv).
- ETH: the same scan and backtests on data/eth_{d1,h4,h1}.csv. ETH has no
  M15 data, so fill-bar ordering falls back to the conservative rules of
  execution_spec 3-3 / 4-1 (ambiguous = stop / filled).
Performance numbers are for reference only.
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

SETS = {
    "BTC": ("d1", "h4", "h1", "m15"),
    "ETH": ("eth_d1", "eth_h4", "eth_h1", None),
}


def load(symbol):
    names = SETS[symbol]
    bars = [read_bars(ROOT / "data" / f"{name}.csv") for name in names[:3]]
    m15 = read_bars(ROOT / "data" / f"{names[3]}.csv") if names[3] else None
    return bars, m15


def t1_rr(decision):
    evidence = decision.criteria["F"].evidence
    if not evidence.startswith("RR_T1="):
        return None
    value = evidence.split(",")[0].split("=")[1]
    return None if value == "None" else float(value)


def scan(symbol):
    (d1, h4, h1), m15 = load(symbol)
    pipeline = DecisionPipeline(Params(split_targets=True), m15=m15)
    p = pipeline.params
    start = min(max(100, p.h1_direction_ma_period + p.N_h1 * 2), len(h1) - 1)
    candidates = []
    for index in range(start, len(h1) - 1):
        decision = pipeline.evaluate(d1, h4, h1, as_of=h1[index].timestamp)
        if not candidate_ready(decision, "strict"):
            continue
        candidates.append({
            "timestamp": h1[index].timestamp.isoformat(),
            "direction": "long" if decision.direction is Direction.LONG else "short",
            "entry": decision.entry,
            "stop": decision.stop,
            "t1_rr": t1_rr(decision),
            "targets": len(decision.targets),
        })
    rr = sorted(c["t1_rr"] for c in candidates if c["t1_rr"] is not None)
    return {
        "symbol": symbol,
        "m15": m15 is not None,
        "period": [h1[start].timestamp.isoformat(), h1[-1].timestamp.isoformat()],
        "strict_total": len(candidates),
        "strict": dict(Counter(c["direction"] for c in candidates)),
        "t1_rr": {
            "n": len(rr),
            "median": rr[len(rr) // 2] if rr else None,
            "below_1": sum(v < 1 for v in rr),
            "from_1_to_1_8": sum(1 <= v < 1.8 for v in rr),
            "from_1_8_to_3": sum(1.8 <= v <= 3 for v in rr),
            "above_3": sum(v > 3 for v in rr),
        },
        "candidates": candidates,
        "cancel_stats": pipeline.cancel_stats,
    }


def backtest(symbol, split):
    (d1, h4, h1), m15 = load(symbol)
    result = run_backtest(d1, h4, h1, Params(split_targets=split), m15=m15, gate="strict")
    trades = result.trades
    wins = sum(1 for t in trades if t.pnl_r > 0)
    return {
        "symbol": symbol,
        "split_targets": split,
        "trades": len(trades),
        "reasons": dict(Counter(t.reason for t in trades)),
        "win_rate": wins / len(trades) if trades else None,
        "avg_r": sum(t.pnl_r for t in trades) / len(trades) if trades else None,
        "total_r": sum(t.pnl_r for t in trades),
    }


def main():
    began = time.time()
    with ProcessPoolExecutor(max_workers=4) as pool:
        scans = {symbol: pool.submit(scan, symbol) for symbol in ("BTC", "ETH")}
        bts = [pool.submit(backtest, "ETH", split) for split in (False, True)]
        out = {
            "scans": {symbol: job.result() for symbol, job in scans.items()},
            "eth_backtests": [job.result() for job in bts],
        }
    out["elapsed_sec"] = round(time.time() - began)
    path = Path(__file__).with_name("recount_recall_eth.json")
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {s: {k: v for k, v in r.items() if k != "candidates"} for s, r in out["scans"].items()}
    print(json.dumps({"scans": summary, "eth_backtests": out["eth_backtests"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

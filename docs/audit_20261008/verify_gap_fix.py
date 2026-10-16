"""Compare pre-fix/new stop fills and frozen candidate counts, without PnL."""
import csv
import hashlib
import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
from oku100.io import read_bars
from oku100.pipeline import DecisionPipeline, TimeframeState
from scripts.collect_candidates import evaluate as buy
from scripts.collect_candidates_sell import evaluate as sell

snapshot = Path(__file__).with_name("pipeline_before_gap_fix.py.txt")
module = types.ModuleType("oku100._gap_fix_snapshot")
module.__package__ = "oku100"
sys.modules[module.__name__] = module
exec(compile(snapshot.read_text(encoding="utf-8"), str(snapshot), "exec"), module.__dict__)
h1 = read_bars(ROOT / "data/h1.csv")
state = TimeframeState(h1, len(h1)-1, [], 0, 1, 100, 0, 100, 100, 0)
old, new = module.DecisionPipeline(), DecisionPipeline()
result = {"directions": {}, "candidate_regression": {}, "protected_input_mismatches": []}
for direction in (1, -1):
    old._stop_entry_fill(state, direction)
    new._stop_entry_fill(state, direction)
    before = old._stop_order_cache[(id(h1), direction)]["fills"]
    after = new._stop_order_cache[(id(h1), direction)]["fills"]
    same_bars = before.keys() == after.keys()
    discrepancies = []
    gaps = []
    for index, fill in before.items():
        expected = max(fill.price, h1[index].open) if direction == 1 else min(fill.price, h1[index].open)
        actual = after.get(index)
        if actual is None or actual.price != expected or actual.index != fill.index or actual.timestamp != fill.timestamp:
            discrepancies.append(index)
        if expected != fill.price:
            gaps.append({"index": index, "timestamp": h1[index].timestamp.isoformat(), "before": fill.price, "after": actual.price})
    result["directions"][str(direction)] = {"fills": len(before), "same_fill_bars": same_bars, "price_mismatches": discrepancies, "gap_changes": gaps}

with (ROOT / "btc_candidate_indicators.csv").open(encoding="utf-8-sig", newline="") as handle:
    table = list(csv.DictReader(handle))
for label, name, evaluate in [("buy", "btc_pullback_candidates_summary.json", buy), ("sell", "btc_rally_candidates_summary.json", sell)]:
    baseline = json.loads((ROOT / name).read_text(encoding="utf-8-sig"))
    rows = [r for r in table if baseline["date_range"]["first"] <= r["timestamp"] <= baseline["date_range"]["last"]]
    params = baseline["params"]
    count = sum(evaluate(r, params["wick_ratio_min"], params["ma_proximity_pct"])[-1] for r in rows)
    result["candidate_regression"][label] = {"rows": len(rows), "expected": baseline["candidates_found"], "actual": count, "matches": count == baseline["candidates_found"]}

record = json.loads(Path(__file__).with_name("audit_v1.json").read_text(encoding="utf-8"))
for name, checksum in record["input_sha256"].items():
    if name.replace("\\", "/") in ("oku100/pipeline.py", "scripts/audit_fidelity_20261008.py"):
        continue
    if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != checksum:
        result["protected_input_mismatches"].append(name)
result["pipeline_before_sha256"] = hashlib.sha256(snapshot.read_bytes()).hexdigest()
result["pipeline_after_sha256"] = hashlib.sha256((ROOT / "oku100/pipeline.py").read_bytes()).hexdigest()
result["passed"] = (all(r["same_fill_bars"] and not r["price_mismatches"] for r in result["directions"].values())
                    and all(r["matches"] for r in result["candidate_regression"].values())
                    and not result["protected_input_mismatches"])
with Path(__file__).with_name("gap_fix_verification.json").open("x", encoding="utf-8") as handle:
    json.dump(result, handle, ensure_ascii=False, indent=2)
print(json.dumps(result, ensure_ascii=False, indent=2))
if not result["passed"]:
    raise SystemExit(1)

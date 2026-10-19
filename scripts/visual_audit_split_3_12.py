"""Create the fixed development/final split for visual-audit loop 3-12.

The 28 existing samples are split 14/14 with seven positives and seven
controls in each half.  Within each half, symbol and coarse pattern counts are
balanced as closely as the small strata permit.  A fixed seed breaks ties.
"""
from __future__ import annotations

import argparse
import itertools
import json
import random
from collections import Counter
from pathlib import Path


SEED = 20261019


def pattern_group(sample: dict) -> str:
    if sample["kind"] == "negative":
        return "control"
    pattern = sample.get("pattern") or ""
    if "押し目・戻り目" in pattern or "初押し" in pattern:
        return "pullback"
    if "乖離埋め" in pattern:
        return "mean_reversion"
    if "史上最高値" in pattern:
        return "all_time_high"
    if "トレンド転換" in pattern:
        return "trend_reversal"
    return "other"


def feature_counts(samples: list[dict]) -> Counter:
    counts: Counter = Counter()
    for sample in samples:
        counts[("symbol", sample["symbol"])] += 1
        counts[("pattern", pattern_group(sample))] += 1
        counts[("joint", sample["symbol"], pattern_group(sample))] += 1
    return counts


def balanced_half(samples: list[dict], size: int, rng: random.Random) -> list[dict]:
    total = feature_counts(samples)
    combos = list(itertools.combinations(range(len(samples)), size))
    rng.shuffle(combos)
    best_score = None
    best = None
    for combo in combos:
        chosen = [samples[i] for i in combo]
        counts = feature_counts(chosen)
        score = sum(abs(2 * counts[key] - value) for key, value in total.items())
        if best_score is None or score < best_score:
            best_score = score
            best = chosen
    assert best is not None
    return best


def build_split(manifest: dict) -> dict:
    samples = manifest["samples"]
    positives = [s for s in samples if s["kind"] == "positive"]
    controls = [s for s in samples if s["kind"] == "negative"]
    if len(positives) != 14 or len(controls) != 14:
        raise ValueError("expected exactly 14 positives and 14 controls")
    rng = random.Random(SEED)
    final = balanced_half(positives, 7, rng) + balanced_half(controls, 7, rng)
    final_ids = {s["id"] for s in final}
    development = [s for s in samples if s["id"] not in final_ids]

    def public_row(sample: dict) -> dict:
        return {
            "id": sample["id"],
            "symbol": sample["symbol"],
            "kind": sample["kind"],
            "pattern_stratum": pattern_group(sample),
        }

    return {
        "seed": SEED,
        "source_manifest": "docs/visual_audit_20261017/manifest_ground_truth.json",
        "method": "fixed 14/14 split; each half has 7 positives and 7 controls; exhaustive minimum-imbalance split over symbol, coarse pattern, and their joint counts; seeded tie-break",
        "training_group": {
            "source": "docs/audit_20261017/fx_ma_convergence_quotes.json",
            "count": 30,
        },
        "development_group": sorted((public_row(s) for s in development), key=lambda x: x["id"]),
        "final_test_group_sealed": sorted((public_row(s) for s in final), key=lambda x: x["id"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="docs/visual_audit_20261017/manifest_ground_truth.json")
    parser.add_argument("--output", default="docs/visual_audit_3_12/fixed_split.json")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / args.manifest).read_text(encoding="utf-8"))
    split = build_split(manifest)
    output = root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(split, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()

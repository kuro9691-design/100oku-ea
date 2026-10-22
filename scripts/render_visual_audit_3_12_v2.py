"""Render the corrected development images for visual-audit loop 3-12.

Development positives use the independently established v2 judgment times.
Development controls retain the original manifest timestamps.  Final-test IDs
are always rejected, and this script never opens either sealed final-test file.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from oku100.io import read_bars
from oku100.models import Bar
from scripts.visual_audit_render_3_12 import (
    DATA_FILES,
    load_manifest_projection,
    prepare_panels,
    reject_final_ids,
    render_panel,
)

def load_v2_development_times(path: Path) -> dict[str, str]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {
        item["id"]: item["judgment_ts"]
        for item in raw["samples"]
        if item["identified"]
    }


def load_split(path: Path) -> tuple[dict[str, str], set[str]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    development = {item["id"]: item["kind"] for item in raw["development_group"]}
    final_ids = {item["id"] for item in raw["final_test_group_sealed"]}
    return development, final_ids


def choose_development_samples(
    manifest_samples: list[dict[str, str]],
    development: dict[str, str],
    final_ids: set[str],
    v2_times: dict[str, str],
) -> list[dict[str, str]]:
    by_id = {sample["id"]: sample for sample in manifest_samples}
    unknown = sorted(set(development) - set(by_id))
    if unknown:
        raise ValueError(f"development IDs missing from manifest: {','.join(unknown)}")
    reject_final_ids(set(development), final_ids, False)

    positive_ids = {sample_id for sample_id, kind in development.items() if kind == "positive"}
    control_ids = {sample_id for sample_id, kind in development.items() if kind == "negative"}
    unexpected = sorted(set(v2_times) - positive_ids)
    if unexpected:
        raise ValueError(f"v2 timestamps are not development positives: {','.join(unexpected)}")

    selected: list[dict[str, str]] = []
    for sample_id in sorted(set(v2_times) | control_ids):
        sample = dict(by_id[sample_id])
        if sample_id in v2_times:
            sample["judgment_ts"] = v2_times[sample_id]
            sample["ts_source"] = "v2"
        selected.append(sample)
    reject_final_ids({sample["id"] for sample in selected}, final_ids, False)
    return selected


def render_samples(samples: list[dict[str, str]], out_dir: Path) -> None:
    cache: dict[str, dict[str, list[Bar]]] = {}
    for sample in samples:
        sample_id = sample["id"]
        symbol = sample["symbol"]
        if symbol not in DATA_FILES:
            raise ValueError(f"{sample_id}: unsupported symbol {symbol}")
        if symbol not in cache:
            cache[symbol] = {
                timeframe: read_bars(ROOT / path)
                for timeframe, path in DATA_FILES[symbol].items()
            }
        judgment_ts = datetime.fromisoformat(sample["judgment_ts"].replace("Z", "+00:00"))
        panels = prepare_panels(cache[symbol], judgment_ts)
        for timeframe, panel in panels.items():
            out_path = out_dir / f"{sample_id}_{timeframe}.png"
            render_panel(panel, timeframe, out_path)
            print(f"saved {out_path.relative_to(ROOT)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="docs/visual_audit_20261017/manifest_ground_truth.json")
    parser.add_argument("--fixed-split", default="docs/visual_audit_3_12/fixed_split.json")
    parser.add_argument("--v2-times", default="docs/visual_audit_3_12/judgment_ts_v2_dev.json")
    parser.add_argument("--out-dir", default="docs/visual_audit_3_12/charts_v2")
    args = parser.parse_args()

    manifest_samples = load_manifest_projection(ROOT / args.manifest)
    development, final_ids = load_split(ROOT / args.fixed_split)
    v2_times = load_v2_development_times(ROOT / args.v2_times)
    samples = choose_development_samples(manifest_samples, development, final_ids, v2_times)
    render_samples(samples, ROOT / args.out_dir)


if __name__ == "__main__":
    main()

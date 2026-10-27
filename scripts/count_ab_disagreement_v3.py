"""Count v3 A/B judgment-time disagreement types without leaking sealed records.

Development output contains a per-sample audit table. Final-test output is
aggregate-only: it never serializes IDs, timestamps, evidence text, or reasons.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
AUDIT_DIR = ROOT / "docs" / "visual_audit_3_12"

GROUP_FILES = {
    "dev": {
        "a_times": AUDIT_DIR / "judgment_ts_v3_A_dev.json",
        "a_evidence": AUDIT_DIR / "judgment_ts_v3_A_dev_evidence.json",
        "b_times": AUDIT_DIR / "judgment_ts_v3_B_dev.json",
        "b_evidence": AUDIT_DIR / "judgment_ts_v3_B_dev_evidence.json",
    },
    "final": {
        "a_times": AUDIT_DIR / "judgment_ts_v3_A_final_ts_sealed.json",
        "a_evidence": AUDIT_DIR / "judgment_ts_v3_A_final_evidence_sealed.json",
        "b_times": AUDIT_DIR / "judgment_ts_v3_B_final_ts_sealed.json",
        "b_evidence": AUDIT_DIR / "judgment_ts_v3_B_final_evidence_sealed.json",
    },
}

BAR_SECONDS = {"m15": 15 * 60, "h1": 60 * 60}


def load_samples(path: Path) -> dict[str, dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    samples = payload.get("samples")
    if not isinstance(samples, list):
        raise ValueError(f"samples list is missing: {path.name}")
    result: dict[str, dict[str, Any]] = {}
    for sample in samples:
        sample_id = sample.get("id")
        if not isinstance(sample_id, str) or sample_id in result:
            raise ValueError(f"invalid or duplicate sample id: {path.name}")
        result[sample_id] = sample
    return result


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def normalized_tf(value: Any) -> str:
    return str(value or "unknown").lower()


def reason_kind(sample: dict[str, Any]) -> str:
    text = " ".join(
        str(sample.get(key) or "") for key in ("reason_type", "reason", "comparison")
    )
    lowered = text.lower()
    if "事後" in text or "実際の遅れた約定足" in text or "post" in lowered:
        return "事後キャプチャのみ"
    if "複数" in text or "2つ以上" in text or "multiple" in lowered or "ambiguous" in lowered:
        return "候補が複数"
    if "図と合わない" in text or "図と不一致" in text or "chart mismatch" in lowered:
        return "図と合わない"
    if "候補" in text and ("0" in text or "ない" in text):
        return "候補なし"
    candidate_count = sample.get("candidate_count")
    if isinstance(candidate_count, int):
        if candidate_count == 0:
            return "候補なし"
        if candidate_count > 1:
            return "候補が複数"
    candidates = sample.get("candidates_jst")
    if isinstance(candidates, list):
        if not candidates:
            return "候補なし"
        if len(candidates) > 1:
            return "候補が複数"
    return "その他"


def evidence_signature(field: str, value: Any) -> str:
    if value is None or not str(value).strip():
        return "missing"
    text = str(value)
    if "図で判別できない" in text:
        return "chart_indeterminate"

    if field == "a":
        if "成行" in text:
            return "market"
        direction = "up" if re.search(r"上抜|超え", text) else "down" if re.search(r"下抜|割れ", text) else "unknown"
        targets: list[str] = []
        if "ネック" in text:
            targets.append("neckline")
        if direction == "up" and re.search(r"高値|山", text):
            targets.append("high")
        if direction == "down" and re.search(r"安値|谷", text):
            targets.append("low")
        if "MA" in text and re.search(r"上抜|下抜|超え|割れ", text):
            targets.append("ma")
        return direction + ":" + "+".join(sorted(set(targets)) or ["unspecified"])

    if field == "b":
        if re.search(r"より上|上側", text):
            return "above"
        if re.search(r"より下|下側", text):
            return "below"
        if re.search(r"付近|近辺|触れ", text):
            return "near"
        return "unknown"

    if field == "c":
        if re.search(r"上回|より上|上側|上端", text):
            return "above"
        if re.search(r"下回|より下|下側|下抜", text):
            return "below"
        return "unknown"

    raise ValueError(f"unsupported evidence field: {field}")


def counter_dict(counter: Counter[str]) -> dict[str, int]:
    return dict(sorted(counter.items()))


def compare_group(group: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    files = GROUP_FILES[group]
    a_times = load_samples(files["a_times"])
    b_times = load_samples(files["b_times"])
    a_evidence = load_samples(files["a_evidence"])
    b_evidence = load_samples(files["b_evidence"])

    id_sets = [set(x) for x in (a_times, b_times, a_evidence, b_evidence)]
    if any(ids != id_sets[0] for ids in id_sets[1:]):
        raise ValueError(f"sample sets do not match for {group}")

    counts: Counter[str] = Counter()
    tf_pairs: Counter[str] = Counter()
    time_relation: Counter[str] = Counter()
    bar_offsets: Counter[str] = Counter()
    unavailable_reasons: Counter[str] = Counter()
    evidence_differences: Counter[str] = Counter()
    evidence_missing_one_side: Counter[str] = Counter()
    chart_indeterminate: Counter[str] = Counter()
    rows: list[dict[str, Any]] = []

    for sample_id in sorted(id_sets[0]):
        at = a_times[sample_id]
        bt = b_times[sample_id]
        ae = a_evidence[sample_id]
        be = b_evidence[sample_id]
        a_identified = bool(at.get("identified"))
        b_identified = bool(bt.get("identified"))
        row: dict[str, Any] = {
            "id": sample_id,
            "a_identified": a_identified,
            "b_identified": b_identified,
        }
        counts["target"] += 1

        if a_identified and b_identified:
            counts["both_identified"] += 1
            a_tf = normalized_tf(at.get("timeframe"))
            b_tf = normalized_tf(bt.get("timeframe"))
            a_ts = parse_ts(str(at.get("judgment_ts")))
            b_ts = parse_ts(str(bt.get("judgment_ts")))
            row.update(
                {
                    "a_timeframe": a_tf,
                    "b_timeframe": b_tf,
                    "a_judgment_ts": a_ts.isoformat(),
                    "b_judgment_ts": b_ts.isoformat(),
                }
            )
            if a_tf != b_tf:
                counts["timeframe_different"] += 1
                tf_pairs[f"A={a_tf},B={b_tf}"] += 1
                row["time_result"] = "timeframe_different"
            elif a_ts == b_ts:
                counts["time_and_timeframe_same"] += 1
                row["time_result"] = "same"
            else:
                counts["same_timeframe_time_different"] += 1
                relation = "B_before_A" if b_ts < a_ts else "B_after_A"
                seconds = int((b_ts - a_ts).total_seconds())
                if a_tf not in BAR_SECONDS or seconds % BAR_SECONDS[a_tf] != 0:
                    raise ValueError(f"non-integral bar offset in {group}")
                bars = seconds // BAR_SECONDS[a_tf]
                time_relation[relation] += 1
                bar_offsets[f"{a_tf}:{bars:+d}"] += 1
                row.update({"time_result": "different", "b_relative_to_a": relation, "bar_offset": bars})
        elif a_identified:
            counts["only_A_identified"] += 1
            reason = reason_kind(be)
            unavailable_reasons[f"B:{reason}"] += 1
            row.update({"time_result": "only_A_identified", "unavailable_reason": f"B:{reason}"})
        elif b_identified:
            counts["only_B_identified"] += 1
            reason = reason_kind(ae)
            unavailable_reasons[f"A:{reason}"] += 1
            row.update({"time_result": "only_B_identified", "unavailable_reason": f"A:{reason}"})
        else:
            counts["both_unidentified"] += 1
            a_reason = reason_kind(ae)
            b_reason = reason_kind(be)
            reason = a_reason if a_reason == b_reason else f"A:{a_reason}|B:{b_reason}"
            unavailable_reasons[f"both:{reason}"] += 1
            row.update({"time_result": "both_unidentified", "unavailable_reason": reason})

        evidence_row: dict[str, Any] = {}
        for field in ("a", "b", "c"):
            a_sig = evidence_signature(field, ae.get(field))
            b_sig = evidence_signature(field, be.get(field))
            if a_sig == "chart_indeterminate":
                chart_indeterminate[f"A:{field}"] += 1
            if b_sig == "chart_indeterminate":
                chart_indeterminate[f"B:{field}"] += 1
            if "missing" in (a_sig, b_sig) and a_sig != b_sig:
                evidence_missing_one_side[field] += 1
            elif a_sig != b_sig:
                evidence_differences[field] += 1
            evidence_row[field] = {"A": a_sig, "B": b_sig, "same": a_sig == b_sig}
        row["evidence_signatures"] = evidence_row
        rows.append(row)

    summary = {
        "group": group,
        "identification_and_time": counter_dict(counts),
        "timeframe_pairs": counter_dict(tf_pairs),
        "same_timeframe_time_difference": {
            "B_relative_to_A": counter_dict(time_relation),
            "signed_bar_offsets_B_minus_A": counter_dict(bar_offsets),
        },
        "unavailable_reason_types": counter_dict(unavailable_reasons),
        "abc_semantic_difference_counts": counter_dict(evidence_differences),
        "abc_missing_on_one_side_counts": counter_dict(evidence_missing_one_side),
        "chart_indeterminate_counts": counter_dict(chart_indeterminate),
    }
    return summary, rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", choices=("dev", "final"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    summary, rows = compare_group(args.group)
    payload: dict[str, Any] = {"summary": summary}
    if args.group == "dev":
        payload["samples"] = rows
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    # Stdout is aggregate-only for both groups. Sealed records are never emitted.
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()

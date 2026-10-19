"""PH-53: measure the preregistered two-event future-MA path once.

Only bars confirmed before each fixed judgment timestamp are used.  The two
synthetic closes are the existing H1 stop-entry trigger E and existing T1 T.
Actual rows at or after the judgment timestamp never enter the calculation.
"""
from __future__ import annotations

import csv
import json
import random
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from oku100.indicators import atr, confirmed_pivots, sma
from oku100.io import read_bars
from oku100.models import Bar, Pivot
from oku100.pipeline import DecisionPipeline
from scripts.render_future_scenario import _last_confirmed

SEED = 20261018
OUT_DIR = ROOT / "docs" / "ph53_future_ma_20261019"

# Fixed in docs/pending_hypotheses.md at commits d1f4cd9 and 2eae77a.
POSITIVES = [
    ("2024-06-04", "2024-06-03T04:00:00+00:00", "buy"),
    ("2024-07-28", "2024-07-27T12:00:00+00:00", "buy"),
    ("2025-02-23", "2025-02-23T10:00:00+00:00", "sell"),
    ("2025-03-09", "2025-03-08T17:00:00+00:00", "sell"),
    ("2025-03-28", "2025-03-28T06:00:00+00:00", "sell"),
    ("2026-01-13", "2026-01-13T09:00:00+00:00", "buy"),
]

CONTROLS = [
    "2026-01-09T14:00:00+00:00", "2024-11-19T20:00:00+00:00",
    "2025-02-15T17:00:00+00:00", "2026-01-08T04:00:00+00:00",
    "2024-08-12T03:00:00+00:00", "2025-06-01T04:00:00+00:00",
    "2025-07-01T22:00:00+00:00", "2025-07-31T01:00:00+00:00",
    "2024-09-16T13:00:00+00:00", "2024-12-03T11:00:00+00:00",
    "2024-08-06T20:00:00+00:00", "2025-09-18T12:00:00+00:00",
    "2025-01-07T22:00:00+00:00", "2024-12-27T16:00:00+00:00",
    "2025-08-21T01:00:00+00:00", "2024-11-09T11:00:00+00:00",
    "2025-12-05T11:00:00+00:00", "2025-07-27T10:00:00+00:00",
]


@dataclass(frozen=True)
class DirectionMeasurement:
    direction: str
    path_status: str
    trigger_pivot_timestamp: str | None
    p0: float
    trigger_e: float | None
    target_t: float | None
    atr0: float
    ma20_0: float
    ma80_0: float
    ma20_1: float | None
    ma80_1: float | None
    ma20_2: float | None
    ma80_2: float | None
    d0: float
    d1: float | None
    d2: float | None
    g0: float
    g1: float | None
    g2: float | None
    convergence_c: float
    expansion_a: float
    directional_expansion_r: float
    q: float
    crossed: bool
    outgoing_c_t_minus_19: float
    outgoing_c_t_minus_18: float
    outgoing_c_t_minus_79: float
    outgoing_c_t_minus_78: float
    formula_max_abs_error: float


def _trigger(pivots: list[Pivot], p0: float, direction: int) -> Pivot | None:
    kind = "high" if direction > 0 else "low"
    return next(
        (
            pivot for pivot in reversed(pivots)
            if pivot.kind == kind and (pivot.price - p0) * direction > 0
        ),
        None,
    )


def _crossed(values: tuple[float, float, float]) -> bool:
    return any(a == 0 or b == 0 or (a < 0 < b) or (b < 0 < a) for a, b in zip(values, values[1:]))


def measure_direction(
    d1: list[Bar], h4: list[Bar], h1: list[Bar], timestamp: str, direction_name: str,
) -> DirectionMeasurement:
    direction = 1 if direction_name == "buy" else -1
    judgment = datetime.fromisoformat(timestamp)
    end_idx = _last_confirmed(h1, judgment, timedelta(hours=1))
    history = [bar.close for bar in h1[:end_idx + 1]]
    if len(history) < 80:
        raise ValueError(f"MA80 not warmed at {timestamp}")

    p0 = history[-1]
    atr0 = atr(h1, end_idx, 14)
    ma20_0 = sma(h1, end_idx, 20)
    ma80_0 = sma(h1, end_idx, 80)
    d0 = ma20_0 - ma80_0
    g0 = abs(d0) / atr0
    outgoing = (history[-20], history[-19], history[-80], history[-79])
    pivots = confirmed_pivots(h1, end_idx, 3)
    trigger = _trigger(pivots, p0, direction)

    base = dict(
        direction=direction_name, p0=p0, atr0=atr0, ma20_0=ma20_0,
        ma80_0=ma80_0, d0=d0, g0=g0,
        outgoing_c_t_minus_19=outgoing[0], outgoing_c_t_minus_18=outgoing[1],
        outgoing_c_t_minus_79=outgoing[2], outgoing_c_t_minus_78=outgoing[3],
    )
    if trigger is None:
        return DirectionMeasurement(
            path_status="missing_trigger", trigger_pivot_timestamp=None,
            trigger_e=None, target_t=None, ma20_1=None, ma80_1=None,
            ma20_2=None, ma80_2=None, d1=None, d2=None, g1=None, g2=None,
            convergence_c=0.0, expansion_a=0.0, directional_expansion_r=0.0,
            q=0.0, crossed=False, formula_max_abs_error=0.0, **base,
        )

    pipeline = DecisionPipeline()
    indexes = pipeline._resolve_indexes(d1, h4, h1, h1[end_idx].timestamp)
    d1_state, h4_state, _ = pipeline._states((d1, h4, h1), indexes)
    target = pipeline._first_target(d1_state, h4_state, trigger.price, direction)
    status = "valid"
    if target is None:
        status = "missing_t1"
    elif not (p0 < trigger.price < target if direction > 0 else p0 > trigger.price > target):
        status = "invalid_order"

    if status != "valid":
        return DirectionMeasurement(
            path_status=status, trigger_pivot_timestamp=h1[trigger.index].timestamp.isoformat(),
            trigger_e=trigger.price, target_t=target, ma20_1=None, ma80_1=None,
            ma20_2=None, ma80_2=None, d1=None, d2=None, g1=None, g2=None,
            convergence_c=0.0, expansion_a=0.0, directional_expansion_r=0.0,
            q=0.0, crossed=False, formula_max_abs_error=0.0, **base,
        )

    e = trigger.price
    t = float(target)
    ma20_1 = ma20_0 + (e - history[-20]) / 20
    ma80_1 = ma80_0 + (e - history[-80]) / 80
    ma20_2 = ma20_1 + (t - history[-19]) / 20
    ma80_2 = ma80_1 + (t - history[-79]) / 80
    d1_gap = ma20_1 - ma80_1
    d2_gap = ma20_2 - ma80_2
    g1 = abs(d1_gap) / atr0
    g2 = abs(d2_gap) / atr0
    convergence = g0 - g1
    expansion = g2 - g1
    directional = direction * (d2_gap - d1_gap) / atr0
    q = max(0.0, min(convergence, expansion, directional))

    direct_ma20_1 = sum(history[-19:] + [e]) / 20
    direct_ma80_1 = sum(history[-79:] + [e]) / 80
    direct_ma20_2 = sum(history[-18:] + [e, t]) / 20
    direct_ma80_2 = sum(history[-78:] + [e, t]) / 80
    formula_error = max(
        abs(ma20_1 - direct_ma20_1), abs(ma80_1 - direct_ma80_1),
        abs(ma20_2 - direct_ma20_2), abs(ma80_2 - direct_ma80_2),
    )
    return DirectionMeasurement(
        path_status=status, trigger_pivot_timestamp=h1[trigger.index].timestamp.isoformat(),
        trigger_e=e, target_t=t, ma20_1=ma20_1, ma80_1=ma80_1,
        ma20_2=ma20_2, ma80_2=ma80_2, d1=d1_gap, d2=d2_gap,
        g1=g1, g2=g2, convergence_c=convergence, expansion_a=expansion,
        directional_expansion_r=directional, q=q,
        crossed=_crossed((d0, d1_gap, d2_gap)),
        formula_max_abs_error=formula_error, **base,
    )


def measure_case(
    d1: list[Bar], h4: list[Bar], h1: list[Bar], timestamp: str,
    fixed_direction: str | None,
) -> dict:
    if fixed_direction is not None:
        result = measure_direction(d1, h4, h1, timestamp, fixed_direction)
        return {"selected_direction": fixed_direction, "q_primary": result.q, "directions": [asdict(result)]}
    buy = measure_direction(d1, h4, h1, timestamp, "buy")
    sell = measure_direction(d1, h4, h1, timestamp, "sell")
    selected = buy if buy.q >= sell.q else sell
    return {
        "selected_direction": selected.direction,
        "q_primary": max(buy.q, sell.q),
        "directions": [asdict(buy), asdict(sell)],
    }


def _case_rows() -> list[dict]:
    cases = [
        {"group": "positive", "article_date": date, "timestamp": ts, "fixed_direction": direction}
        for date, ts, direction in POSITIVES
    ] + [
        {"group": "control", "article_date": None, "timestamp": ts, "fixed_direction": None}
        for ts in CONTROLS
    ]
    order = list(range(len(cases)))
    random.Random(SEED).shuffle(order)
    for number, index in enumerate(order, 1):
        cases[index]["case_id"] = f"M{number:02d}"
    return sorted(cases, key=lambda item: item["case_id"])


def _ph52_reference() -> dict[str, float]:
    path = ROOT / "docs" / "future_ma_20261018" / "main_flat.csv"
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return {row["timestamp"]: float(row["pair1_min_gap"]) for row in csv.DictReader(handle)}


def run_measurement(d1: list[Bar], h4: list[Bar], h1: list[Bar]) -> tuple[list[dict], dict]:
    ph52 = _ph52_reference()
    rows: list[dict] = []
    for case in _case_rows():
        measured = measure_case(d1, h4, h1, case["timestamp"], case["fixed_direction"])
        rows.append({**case, **measured, "ph52_pair1_min_gap_reference": ph52[case["timestamp"]]})

    positive_q = [row["q_primary"] for row in rows if row["group"] == "positive"]
    control_q = [row["q_primary"] for row in rows if row["group"] == "control"]
    control_median = float(median(control_q))
    direction_results = [item for row in rows for item in row["directions"]]
    valid = [item for item in direction_results if item["path_status"] == "valid"]
    q_positive = [item for item in valid if item["q"] > 0]
    summary = {
        "primary": {
            "positive_above_control_median": sum(value > control_median for value in positive_q),
            "positive_count": len(positive_q),
            "control_median": control_median,
        },
        "seed": SEED,
        "fixed_commits": {"controls": "d1f4cd9", "ph53_preregistration": "2eae77a"},
        "case_counts": {"positive": len(positive_q), "control": len(control_q)},
        "path_status_counts": {
            status: sum(item["path_status"] == status for item in direction_results)
            for status in ("valid", "missing_trigger", "missing_t1", "invalid_order")
        },
        "measurement_validity": {
            "max_formula_abs_error": max(item["formula_max_abs_error"] for item in direction_results),
            "q_positive_direction_paths": len(q_positive),
            "q_positive_without_crossing": sum(not item["crossed"] for item in q_positive),
            "q_positive_with_crossing": sum(item["crossed"] for item in q_positive),
            "distinct_positive_q_rounded_12dp": len({round(item["q"], 12) for item in q_positive}),
            "valid_paths_with_distinct_event_prices": sum(
                item["trigger_e"] != item["target_t"] for item in valid
            ),
            "valid_paths_with_nonconstant_outgoing_closes": sum(
                len({
                    item["outgoing_c_t_minus_19"], item["outgoing_c_t_minus_18"],
                    item["outgoing_c_t_minus_79"], item["outgoing_c_t_minus_78"],
                }) > 1 for item in valid
            ),
        },
        "ph52_reference_only": True,
    }
    return rows, summary


def main() -> None:
    d1 = read_bars(str(ROOT / "data" / "d1.csv"))
    h4 = read_bars(str(ROOT / "data" / "h4.csv"))
    h1 = read_bars(str(ROOT / "data" / "h1.csv"))
    rows, summary = run_measurement(d1, h4, h1)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"summary": summary, "cases": rows}
    (OUT_DIR / "results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    flat_rows = []
    for row in rows:
        flat_rows.append({
            "case_id": row["case_id"], "group": row["group"],
            "article_date": row["article_date"], "timestamp": row["timestamp"],
            "fixed_direction": row["fixed_direction"],
            "selected_direction": row["selected_direction"], "q_primary": row["q_primary"],
            "ph52_pair1_min_gap_reference": row["ph52_pair1_min_gap_reference"],
        })
    with (OUT_DIR / "main.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(flat_rows[0]))
        writer.writeheader()
        writer.writerows(flat_rows)
    (OUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

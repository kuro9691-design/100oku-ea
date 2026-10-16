from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .backtest import run_backtest
from .distribution import scan_distribution
from .io import read_bars
from .leak_check import run_leak_check
from .optimize import compact_grid, optimize
from .pipeline import DecisionPipeline


def _parse_date(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def main() -> None:
    parser = argparse.ArgumentParser(prog="oku100")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("evaluate", "backtest", "leak-check", "optimize", "distribution"):
        command = subparsers.add_parser(name)
        command.add_argument("--d1", required=True)
        command.add_argument("--h4", required=True)
        command.add_argument("--h1", required=True)
        command.add_argument("--output")
        if name == "backtest":
            command.add_argument(
                "--eval-start",
                metavar="DATE",
                help="ISO date to begin evaluation, e.g. 2021-06-01 (skip MA warmup before this)",
            )
            command.add_argument(
                "--split-date",
                metavar="DATE",
                help="ISO date for IS/OOS boundary, e.g. 2025-01-01",
            )
            command.add_argument(
                "--eval-end",
                metavar="DATE",
                help="ISO date to stop entering trades (exclusive), e.g. 2025-01-01 for IS-only",
            )
            command.add_argument(
                "--m15",
                help="M15 CSV to order fills/exits inside one H1 bar (docs/execution_spec.md 3-2, 4-1)",
            )
    args = parser.parse_args()
    d1, h4, h1 = (read_bars(path) for path in (args.d1, args.h4, args.h1))
    if args.command == "evaluate":
        payload = DecisionPipeline().evaluate(d1, h4, h1).to_dict()
    elif args.command == "backtest":
        eval_start = _parse_date(args.eval_start) if args.eval_start else None
        split_date = _parse_date(args.split_date) if args.split_date else None
        eval_end = _parse_date(args.eval_end) if args.eval_end else None
        payload = run_backtest(
            d1, h4, h1,
            eval_start=eval_start,
            split_date=split_date,
            eval_end=eval_end,
            m15=read_bars(args.m15) if args.m15 else None,
        ).to_dict()
    elif args.command == "optimize":
        payload = [result.to_dict() for result in optimize(d1, h4, h1, compact_grid())]
    elif args.command == "distribution":
        payload = scan_distribution(d1, h4, h1).to_dict()
    else:
        payload = asdict(run_leak_check(d1, h4, h1))
    text = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()

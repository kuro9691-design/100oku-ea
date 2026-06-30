from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from oku100.io import read_bars
from stock.backtest import run_stock_backtest
from stock.models import StockParams
from stock.pipeline import StockPipeline


def _parse_date(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def main() -> None:
    parser = argparse.ArgumentParser(prog="stock")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in ("evaluate", "backtest"):
        cmd = subparsers.add_parser(name)
        cmd.add_argument("--bars", required=True, help="銘柄 D1 CSV")
        cmd.add_argument("--index", help="指数 D1 CSV（地合いフィルター用）")
        cmd.add_argument("--symbol", default="unknown")
        cmd.add_argument("--output")
        if name == "backtest":
            cmd.add_argument("--split-date", metavar="DATE")
            cmd.add_argument("--eval-start", metavar="DATE")

    args = parser.parse_args()
    bars = read_bars(args.bars)
    index_bars = read_bars(args.index) if args.index else None
    params = StockParams(symbol=args.symbol)

    if args.command == "evaluate":
        pipeline = StockPipeline(params)
        if index_bars:
            from stock.market_filter import IndexFilter
            pipeline = StockPipeline(params, IndexFilter(index_bars, params))
        signal = pipeline.evaluate(bars, bars[-1].timestamp)
        payload = {
            "timestamp": signal.timestamp.isoformat(),
            "direction": signal.direction.value,
            "actionable": signal.actionable,
            "reason": signal.reason,
            "atr": signal.atr_value,
            "signal_price": signal.signal_price,
        }
    else:
        split_date = _parse_date(args.split_date) if args.split_date else None
        eval_start = _parse_date(args.eval_start) if args.eval_start else None
        result = run_stock_backtest(
            bars, index_bars, params,
            split_date=split_date,
            eval_start=eval_start,
        )
        payload = result.to_dict()

    text = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()

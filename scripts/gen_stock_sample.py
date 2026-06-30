"""東証向け合成サンプルデータを生成する。

出力先:
  data/stock/7203_d1.csv   Toyota(7203) D1 合成データ 300本
  data/stock/topix_d1.csv  TOPIX D1 合成データ 300本

特徴:
  - 5% 確率でギャップ（前日比 ±3〜8% の寄り窓）を挿入
  - 上昇ドリフト付きサイン波で自然なトレンド転換を生成
  - timestamp は東証の寄り時刻 09:00 JST（+09:00）
  - oku100.io.read_bars でそのまま読める CSV 形式

Usage:
    python scripts/gen_stock_sample.py
    python scripts/gen_stock_sample.py --rows 500 --seed 42
"""
from __future__ import annotations

import argparse
import csv
import math
import random
from datetime import date, timedelta
from pathlib import Path


def _trading_dates(start: date, count: int) -> list[date]:
    """weekday のみ count 本分の日付を返す。"""
    result: list[date] = []
    d = start
    while len(result) < count:
        if d.weekday() < 5:
            result.append(d)
        d += timedelta(days=1)
    return result


def _gen_bars(
    dates: list[date],
    start_price: float,
    drift: float,
    amplitude: float,
    daily_vol: float,
    gap_prob: float,
    gap_range: tuple[float, float],
    seed: int,
) -> list[dict]:
    """
    Parameters
    ----------
    drift       : 1本あたりの上昇期待値（円）
    amplitude   : サイン波の振れ幅（円）
    daily_vol   : 高値-安値の基本幅（ATR相当、円）
    gap_prob    : 窓が入る確率 (0〜1)
    gap_range   : 窓の前日終値比率の範囲 (例: (0.03, 0.08) → +3〜+8%)
    """
    rng = random.Random(seed)
    rows: list[dict] = []
    prev_close = start_price

    for i, d in enumerate(dates):
        center = start_price + i * drift + math.sin(i / 12) * amplitude

        # ギャップ: gap_prob の確率で前日終値から大きく乖離した始値
        gap_factor = 1.0
        if i > 0 and rng.random() < gap_prob:
            mag = rng.uniform(*gap_range)
            gap_factor = 1 + mag if rng.random() < 0.5 else 1 - mag

        open_price = round(prev_close * gap_factor, 1)
        spread = daily_vol * rng.uniform(0.6, 1.4)
        noise = rng.gauss(0, daily_vol * 0.15)

        close_price = round(open_price + noise + drift * 0.5, 1)
        high = round(max(open_price, close_price) + spread * rng.uniform(0.3, 0.7), 1)
        low = round(min(open_price, close_price) - spread * rng.uniform(0.3, 0.7), 1)

        # OHLC 整合性を保証
        high = max(high, open_price, close_price)
        low = min(low, open_price, close_price)

        ts = f"{d.isoformat()}T09:00:00+09:00"
        rows.append({
            "timestamp": ts,
            "open": open_price,
            "high": high,
            "low": low,
            "close": close_price,
        })
        prev_close = close_price

    return rows


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp", "open", "high", "low", "close"])
        writer.writeheader()
        writer.writerows(rows)
    gaps = sum(
        1 for i in range(1, len(rows))
        if abs(rows[i]["open"] - rows[i - 1]["close"]) / rows[i - 1]["close"] > 0.02
    )
    print(f"{path}: {len(rows)} rows, gap days (>2%): {gaps}")


def main() -> None:
    parser = argparse.ArgumentParser(description="東証向け合成サンプルデータ生成")
    parser.add_argument("--rows", type=int, default=300, help="生成本数（既定 300）")
    parser.add_argument("--seed", type=int, default=0, help="乱数シード（既定 0）")
    args = parser.parse_args()

    start = date(2020, 1, 6)
    dates = _trading_dates(start, args.rows)

    toyota_rows = _gen_bars(
        dates,
        start_price=2000.0,
        drift=1.8,
        amplitude=120.0,
        daily_vol=60.0,
        gap_prob=0.05,
        gap_range=(0.03, 0.07),
        seed=args.seed,
    )

    topix_rows = _gen_bars(
        dates,
        start_price=2500.0,
        drift=0.7,
        amplitude=40.0,
        daily_vol=20.0,
        gap_prob=0.03,
        gap_range=(0.02, 0.05),
        seed=args.seed + 1,
    )

    _write_csv(Path("data/stock/7203_d1.csv"), toyota_rows)
    _write_csv(Path("data/stock/topix_d1.csv"), topix_rows)


if __name__ == "__main__":
    main()

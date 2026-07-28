from __future__ import annotations

import argparse
import csv
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


BASE_URL = "https://api.binance.com/api/v3/klines"
INTERVAL_MS = {
    "15m": 15 * 60 * 1000, "1h": 60 * 60 * 1000, "4h": 4 * 60 * 60 * 1000, "1d": 24 * 60 * 60 * 1000,
}


def timestamp_ms(value: str) -> int:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)


def download(symbol: str, interval: str, start_ms: int, end_ms: int) -> list[list]:
    rows: list[list] = []
    cursor = start_ms
    while cursor < end_ms:
        query = urllib.parse.urlencode(
            {
                "symbol": symbol,
                "interval": interval,
                "startTime": cursor,
                "endTime": end_ms,
                "limit": 1000,
            }
        )
        with urllib.request.urlopen(f"{BASE_URL}?{query}", timeout=30) as response:
            batch = json.loads(response.read())
        if not batch:
            break
        rows.extend(batch)
        cursor = batch[-1][0] + INTERVAL_MS[interval]
        time.sleep(0.08)
    return [row for row in rows if row[6] <= end_ms]


def read_existing(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def rows_to_dicts(rows: list[list]) -> dict[str, list]:
    return {
        datetime.fromtimestamp(row[0] / 1000, timezone.utc).isoformat(): row
        for row in rows
    }


def write_csv(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["timestamp", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        writer.writerows(records)


def update_one(symbol: str, interval: str, path: Path, default_start: str) -> tuple[int, int]:
    """既存CSVの最終タイムスタンプ以降だけをBinanceから取得し追記する。全件再取得はしない。
    最終行は前回取得時点でまだ確定していなかった可能性があるため、そこから取得し直して置き換える。
    """
    existing = read_existing(path)
    end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    if not existing:
        start_ms = timestamp_ms(default_start)
        new_rows = download(symbol, interval, start_ms, end_ms)
        merged = [
            {"timestamp": ts, "open": r[1], "high": r[2], "low": r[3], "close": r[4], "volume": r[5]}
            for ts, r in sorted(rows_to_dicts(new_rows).items())
        ]
        write_csv(path, merged)
        return 0, len(merged)

    last_ts = existing[-1]["timestamp"]
    start_ms = timestamp_ms(last_ts)
    new_rows = download(symbol, interval, start_ms, end_ms)
    new_by_ts = rows_to_dicts(new_rows)

    kept = [row for row in existing if row["timestamp"] < last_ts]
    merged = kept + [
        {"timestamp": ts, "open": r[1], "high": r[2], "low": r[3], "close": r[4], "volume": r[5]}
        for ts, r in sorted(new_by_ts.items())
    ]
    write_csv(path, merged)
    return len(existing), len(merged)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--start", default="2021-01-01T00:00:00+00:00",
                         help="出力ファイルが存在しない場合のみ使う初回取得開始日")
    parser.add_argument("--output", default="data")
    args = parser.parse_args()
    output = Path(args.output)
    for interval, filename in (("1d", "d1.csv"), ("4h", "h4.csv"), ("1h", "h1.csv"), ("15m", "m15.csv")):
        before, after = update_one(args.symbol, interval, output / filename, args.start)
        print(f"{filename}: {before} -> {after} rows (+{after - before})")


if __name__ == "__main__":
    main()

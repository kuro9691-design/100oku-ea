from __future__ import annotations

import csv
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from crawl_realtrade import HEADERS, _throttled_urlopen, entry_text, fetch, infer_direction, parse_title


SEARCH_TERMS = ("BTC", "ビットコイン", "BTC/USD", "BTCUSD")


def wp_search(term: str) -> list[dict]:
    url = (
        "https://multimillionaire-trade.com/wp-json/wp/v2/search"
        "?per_page=100&subtype=post&search=" + urllib.parse.quote(term)
    )
    request = urllib.request.Request(url, headers=HEADERS)
    with _throttled_urlopen(request, timeout=45) as response:
        return json.loads(response.read())


def category(source: str) -> str:
    matches = re.findall(r'class="entry-category[^"]*"[^>]*>(.*?)</', source, re.S | re.I)
    values = [re.sub(r"<[^>]+>", "", value).strip() for value in matches]
    return values[0] if values else "不明"


def published_date(source: str) -> str:
    match = re.search(r'article:published_time" content="(20\d{2}-\d{2}-\d{2})', source)
    return match.group(1) if match else ""


def main() -> None:
    found: dict[int, dict] = {}
    for term in SEARCH_TERMS:
        for result in wp_search(term):
            found[result["id"]] = result

    rows: list[dict[str, str]] = []
    for result in found.values():
        title = result["title"]
        url = result["url"]
        source = fetch(url)
        trade_date, symbol, pattern = parse_title(title)
        realtrade = "リアルトレード解説" in title
        rows.append(
            {
                "date": trade_date or published_date(source),
                "symbol": symbol or "BTC関連",
                "direction": infer_direction(title, entry_text(source)) if realtrade else "対象外",
                "pattern_or_topic": pattern or title,
                "category": category(source),
                "article_type": "リアルトレード" if realtrade else "BTC言及・関連解説",
                "url": url,
                "title": title,
            }
        )
    rows.sort(key=lambda row: row["date"], reverse=True)
    fields = ["date", "symbol", "direction", "pattern_or_topic", "category", "article_type", "url", "title"]
    out_path = Path(__file__).resolve().parents[1] / "data" / "btc_all_articles.csv"
    with out_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"btc_related_articles={len(rows)} realtrades={sum(row['article_type'] == 'リアルトレード' for row in rows)}")


if __name__ == "__main__":
    main()

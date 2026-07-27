from __future__ import annotations

import csv
import html
import re
import time
import urllib.request
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path


BASE = "https://multimillionaire-trade.com/category/realtrade/"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; research-crawler/1.0)"}
CACHE = Path("data/realtrade_cache")

# Facts supplied by the user. These override only fields the user explicitly gave.
KNOWN_BTC: dict[str, dict[str, str]] = {
    "2024-06-04": {"direction": "買い", "pattern": "4時間足レベルの押し目"},
    "2024-07-06": {"direction": "買い", "pattern": "4時間足レベルの戻り目形成のための上昇（短期）"},
    "2025-03-09": {"direction": "売り", "pattern": "4時間足レベルの戻り売り"},
    "2026-03-04": {"direction": "買い", "pattern": "4時間足レベルのトレンド転換後の初押し"},
}


class TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


class EntryContentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.depth = 0
        self.active = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = dict(attrs).get("class") or ""
        if not self.active and tag == "div" and "entry-content" in classes.split():
            self.active = True
            self.depth = 1
        elif self.active and tag == "div":
            self.depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self.active and tag == "div":
            self.depth -= 1
            if self.depth == 0:
                self.active = False

    def handle_data(self, data: str) -> None:
        if self.active:
            self.parts.append(data)


MIN_REQUEST_INTERVAL_SEC = 2.0  # 相手サーバーへの負荷を避けるための最低間隔
MAX_RETRIES = 5
_last_request_at: float = 0.0


def _throttled_urlopen(request: urllib.request.Request, timeout: int = 45):
    """最低MIN_REQUEST_INTERVAL_SEC秒間隔を空け、失敗時は指数バックオフで再試行する。
    キャッシュヒット時はこの関数自体を呼ばないため、遅延の影響を受けない。"""
    global _last_request_at
    for attempt in range(MAX_RETRIES):
        elapsed = time.monotonic() - _last_request_at
        if elapsed < MIN_REQUEST_INTERVAL_SEC:
            time.sleep(MIN_REQUEST_INTERVAL_SEC - elapsed)
        try:
            response = urllib.request.urlopen(request, timeout=timeout)
            _last_request_at = time.monotonic()
            return response
        except Exception:
            _last_request_at = time.monotonic()
            if attempt == MAX_RETRIES - 1:
                raise
            backoff = MIN_REQUEST_INTERVAL_SEC * (2 ** attempt)
            time.sleep(backoff)
    raise RuntimeError("unreachable")


def fetch(url: str) -> str:
    CACHE.mkdir(parents=True, exist_ok=True)
    key = re.sub(r"\W+", "_", url).strip("_") + ".html"
    cached = CACHE / key
    if cached.exists():
        return cached.read_text(encoding="utf-8")
    request = urllib.request.Request(url, headers=HEADERS)
    with _throttled_urlopen(request, timeout=45) as response:
        source = response.read().decode("utf-8", "ignore")
    cached.write_text(source, encoding="utf-8")
    return source


def plain_text(source: str) -> str:
    parser = TextParser()
    parser.feed(source)
    return normalize_text(parser.parts)


def entry_text(source: str) -> str:
    parser = EntryContentParser()
    parser.feed(source)
    return normalize_text(parser.parts)


def normalize_text(parts: list[str]) -> str:
    return re.sub(r"\s+", " ", html.unescape(" ".join(parts))).strip()


def article_links(source: str) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    for url, card in re.findall(
        r"<a[^>]+href=[\"']([^\"']+)[\"'][^>]*class=[\"'][^\"']*entry-card-wrap[^\"']*[\"'][^>]*>(.*?)</a>",
        source,
        re.S | re.I,
    ):
        title_match = re.search(r"<h2[^>]*>(.*?)</h2>", card, re.S | re.I)
        if title_match and re.fullmatch(r"https://multimillionaire-trade\.com/\d+/", url):
            results.append((plain_text(title_match.group(1)), url))
    return list(dict.fromkeys(results))


def parse_title(title: str) -> tuple[str, str, str]:
    date_match = re.search(r"[（(](20\d{2})[./年](\d{1,2})[./月](\d{1,2})日?[)）]", title)
    if not date_match:
        return "", "", title
    date = datetime(*map(int, date_match.groups())).date().isoformat()
    subject = re.sub(r"^【[^】]+】", "", title[: date_match.start()]).strip(" ・/")
    if subject == "ビットコインドル":
        subject = "BTC/USD"
    suffix = title[date_match.end() :].strip()
    pattern = re.sub(r"(を獲りにいったトレード|を狙ったトレード|トレード解説)$", "", suffix).strip()
    return date, subject, pattern


def infer_direction(title: str, text: str) -> str:
    # Strong title descriptions are less ambiguous than generic body discussion.
    if any(term in title for term in ("初押し", "押し目", "戻り目形成のための上昇")):
        return "買い"
    if any(term in title for term in ("初戻し", "戻り売り", "戻り目", "押し目形成のための下落")):
        return "売り"

    buy_terms = ("買いエントリー", "ロングエントリー", "買いでエントリー", "買いを入れ", "ロングで", "ロングを仕掛け")
    sell_terms = (
        "売りエントリー", "ショートエントリー", "売りでエントリー", "売りを入れ",
        "ショートで", "ショートしています", "ショートを仕掛け", "売り注文を仕掛け",
    )
    buy = sum(text.count(term) for term in buy_terms)
    sell = sum(text.count(term) for term in sell_terms)
    if buy > sell:
        return "買い"
    if sell > buy:
        return "売り"
    return "不明"


def main() -> None:
    collected: list[dict[str, str]] = []
    seen: set[str] = set()
    for page in range(1, 19):
        url = BASE if page == 1 else f"{BASE}page/{page}/"
        for title, article_url in article_links(fetch(url)):
            if article_url in seen:
                continue
            seen.add(article_url)
            date, symbol, pattern = parse_title(title)
            content = entry_text(fetch(article_url))
            direction = infer_direction(title, content)
            if symbol.upper() == "BTC/USD" and date in KNOWN_BTC:
                direction = KNOWN_BTC[date]["direction"]
                pattern = KNOWN_BTC[date]["pattern"]
            collected.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "direction": direction,
                    "pattern": pattern,
                    "url": article_url,
                    "title": title,
                }
            )
            time.sleep(0.05)
        print(f"page {page}: total {len(collected)}")
    collected.sort(key=lambda row: row["date"], reverse=True)
    fields = ["date", "symbol", "direction", "pattern", "url", "title"]
    with Path("realtrade_articles.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(collected)
    btc = [row for row in collected if row["symbol"].upper() == "BTC/USD"]
    with Path("realtrade_btc.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(btc)
    print(f"articles={len(collected)} btc={len(btc)}")


if __name__ == "__main__":
    main()

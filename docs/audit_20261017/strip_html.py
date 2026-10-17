"""Read-only helper: strip saved HTML trade articles down to plain article text.

Not part of the pipeline. Used once to make raw HTML readable for manual
transcription of entry/SL/TP prices and times (recall_fx_articles task).
"""
import re
import sys
from html import unescape
from pathlib import Path

SRC_DIRS = [
    Path("docs/codex_examples/EURUSD"),
    Path("docs/codex_examples/USDJPY"),
]
OUT_DIR = Path("docs/audit_20261017/article_text")


def strip_html(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|noscript|svg|header|footer|nav).*?</\1>", "", html)
    html = re.sub(r"(?is)<!--.*?-->", "", html)
    html = re.sub(r"(?is)<br\s*/?>", "\n", html)
    html = re.sub(r"(?is)</p>", "\n\n", html)
    html = re.sub(r"(?is)</(div|li|h[1-6]|tr)>", "\n", html)
    html = re.sub(r"(?is)<[^>]+>", "", html)
    html = unescape(html)
    lines = [ln.strip() for ln in html.splitlines()]
    lines = [ln for ln in lines if ln]
    out = []
    seen_blank = False
    for ln in lines:
        out.append(ln)
    return "\n".join(out)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for d in SRC_DIRS:
        sub = OUT_DIR / d.name
        sub.mkdir(parents=True, exist_ok=True)
        for f in sorted(d.glob("*.html")):
            text = strip_html(f.read_text(encoding="utf-8", errors="replace"))
            out_path = sub / (f.stem + ".txt")
            out_path.write_text(text, encoding="utf-8")
            print(out_path, len(text))


if __name__ == "__main__":
    main()

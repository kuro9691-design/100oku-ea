"""Extract local MHTML evidence only; no network and no source modifications."""
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[2]


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        if tag in ("p", "div", "h1", "h2", "h3", "br", "li"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
        if tag in ("p", "div", "li"):
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


result = []
for source in sorted((ROOT / "reference").glob("*.mhtml")):
    message = BytesParser(policy=policy.default).parsebytes(source.read_bytes())
    html = next(p for p in message.walk() if p.get_content_type() == "text/html")
    parser = TextParser()
    parser.feed(html.get_payload(decode=True).decode(html.get_content_charset() or "utf-8",errors="replace"))
    lines = [line.strip() for line in "".join(parser.parts).splitlines() if line.strip()]
    keys = ("15分足レベル", "キャンセル", "成行", "成り行き", "買い注文", "売り注文", "リスクリワード", "損切りライン", "ネックライン", "直近高値を", "直近安値を")
    positions = [i for i,line in enumerate(lines) if any(k in line for k in keys)]
    excerpts = [{"text_line":i+1,"text":"\n".join(lines[max(0,i-1):min(len(lines),i+2)])} for i in positions]
    item = {"source":str(source.relative_to(ROOT)),"sha256":hashlib.sha256(source.read_bytes()).hexdigest(),
            "html_location":html.get("Content-Location"),"excerpts":excerpts}
    result.append(item)
out = Path(__file__).with_name("source_evidence.json")
with out.open("x",encoding="utf-8") as handle:
    json.dump(result,handle,ensure_ascii=False,indent=2)
for item in result:
    print(item["source"])
    for excerpt in item["excerpts"]:
        print(f"line {excerpt['text_line']}: {excerpt['text']}")

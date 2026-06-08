"""
notify.py — Content Flywheel: Telegram Daily Briefing
Reads data/news.json (or data/briefs.json if available),
sends formatted daily briefing to Telegram.

Usage:
    python notify.py           # send briefing
    python notify.py --dry-run # preview without sending
"""

import os
import sys
import re
import json
import time
import argparse
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MYT = timezone(timedelta(hours=8))

BRAND_EMOJI = {"KiraAI": "💳", "Coaching": "🎯", "AI_Agency": "🤖", "Interest": "💡"}
BRAND_LABEL = {"KiraAI": "KiraAI", "Coaching": "Coaching", "AI_Agency": "AI Agency", "Interest": "Interest"}


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def clean_summary(raw: str) -> str:
    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    lines = [l for l in lines if not l.startswith("#") and l not in
             ("Search", "More", "Share", "Menu", "Skip to main content", "View")]
    text = " ".join(lines)
    return re.sub(r"\s{2,}", " ", text)[:200]


def send_message(token: str, chat_id: str, text: str, dry_run: bool = False) -> bool:
    if dry_run:
        print(f"\n{'─'*55}\n{text}\n")
        return True
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode({
        "chat_id": chat_id, "text": text,
        "parse_mode": "HTML", "disable_web_page_preview": "true",
    }).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=payload), timeout=10) as r:
            return json.loads(r.read()).get("ok", False)
    except Exception as exc:
        print(f"  [Telegram error] {exc}")
        return False


def build_summary(items: list[dict], date_str: str) -> str:
    counts: dict[str, int] = {}
    for item in items:
        b = item.get("brand", "?")
        counts[b] = counts.get(b, 0) + 1
    lines = [
        f"🗞 <b>每日内容简报</b> {date_str}",
        f"",
        f"📊 今日共 <b>{len(items)}</b> 条新闻",
    ]
    for brand in ["KiraAI", "Coaching", "AI_Agency", "Interest"]:
        if counts.get(brand):
            lines.append(f"{BRAND_EMOJI[brand]} {BRAND_LABEL[brand]}: {counts[brand]}条")
    return "\n".join(lines)


def trunc_chars(text: str, n: int) -> str:
    """Truncate to n characters, append … if cut."""
    text = text.strip()
    return text if len(text) <= n else text[:n].rstrip() + "…"


def trunc_words(text: str, n: int) -> str:
    """Truncate to n words, append … if cut."""
    words = text.split()
    return " ".join(words) if len(words) <= n else " ".join(words[:n]) + "…"


def build_message(item: dict, use_brief: bool = False) -> str:
    brand = item.get("brand", "?")
    angle = item.get("suggested_angle", "")
    emoji = BRAND_EMOJI.get(brand, "📰")
    label = BRAND_LABEL.get(brand, brand)

    if use_brief:
        raw_title   = item.get("source_title", "") or item.get("title_suggestion", "")
        raw_summary = item.get("ig_caption", "") or ""
        url         = item.get("source_url", "")
        date        = item.get("published_date", "")
    else:
        raw_title   = item.get("title", "")
        raw_summary = clean_summary(item.get("summary", ""))
        url         = item.get("url", "")
        date        = item.get("published_date", "")

    title_cn   = esc(trunc_chars(raw_title,   20))
    title_en   = esc(trunc_words(raw_title,   20))
    summary_cn = esc(trunc_chars(raw_summary, 30))
    summary_en = esc(trunc_words(raw_summary, 30))

    lines = [
        f"{emoji} <b>[{label}]</b> | {angle}", "",
        f"<b>标题CN：</b>{title_cn}",
        f"<b>标题EN：</b>{title_en}",
        f"<b>摘要CN：</b>{summary_cn}",
        f"<b>摘要EN：</b>{summary_en}",
    ]
    if date:
        lines.append(f"<b>日期：</b>{date}")
    if url:
        lines.append(f'<a href="{url}">🔗 来源</a>')
    return "\n".join(lines)


def load_items() -> tuple[list[dict], bool]:
    """Return (items, use_brief). Prefers briefs.json over news.json."""
    if os.path.exists("data/briefs.json"):
        with open("data/briefs.json", encoding="utf-8") as f:
            return json.load(f), True
    if os.path.exists("data/news.json"):
        with open("data/news.json", encoding="utf-8") as f:
            return json.load(f), False
    raise FileNotFoundError("No data found. Run fetch_news.py first.")


def run(token: str, chat_id: str, dry_run: bool = False) -> int:
    items, use_brief = load_items()
    source = "briefs.json" if use_brief else "news.json"
    date_str = datetime.now(MYT).strftime("%Y-%m-%d")

    print(f"Source: {source} ({len(items)} items) — sending to Telegram ...")

    send_message(token, chat_id, build_summary(items, date_str), dry_run)
    time.sleep(1)

    sent = 0
    brand_order = ["KiraAI", "Coaching", "AI_Agency", "Interest"]
    total = len(items)
    for brand in brand_order:
        for item in [i for i in items if i.get("brand") == brand]:
            msg = build_message(item, use_brief)
            ok  = send_message(token, chat_id, msg, dry_run)
            print(f"  {'OK' if ok else 'FAIL'} [{brand}] {item.get('title', item.get('source_title',''))[:50]}")
            sent += 1
            if sent < total:
                time.sleep(1)

    print(f"\nDone: {sent} messages sent.")
    return sent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    token   = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not args.dry_run:
        if not token:  raise EnvironmentError("TELEGRAM_BOT_TOKEN not set")
        if not chat_id: raise EnvironmentError("TELEGRAM_CHAT_ID not set")

    run(token, chat_id, dry_run=args.dry_run)


if __name__ == "__main__":
    main()

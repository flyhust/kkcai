"""
notify.py — Content Flywheel: Telegram Daily Briefing
Reads data/news.json (or data/briefs.json if available),
translates titles and summaries to Chinese via OpenRouter (DeepSeek),
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

BRAND_EMOJI  = {"KiraAI": "💳", "Coaching": "🎯", "AI_Agency": "🤖", "Interest": "💡"}
BRAND_LABEL  = {"KiraAI": "KiraAI", "Coaching": "Coaching", "AI_Agency": "AI Agency", "Interest": "Interest"}

OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEEPSEEK_MODEL = "deepseek/deepseek-chat"


# ---------------------------------------------------------------------------
# Translation via OpenRouter / DeepSeek
# ---------------------------------------------------------------------------

def translate_to_chinese(text: str) -> str:
    """Translate text to Chinese using DeepSeek via OpenRouter. Returns original on failure."""
    if not text.strip() or not OPENROUTER_KEY:
        return text
    payload = json.dumps({
        "model": DEEPSEEK_MODEL,
        "messages": [
            {
                "role": "system",
                "content": "你是专业翻译。将用户输入翻译成简体中文，只输出翻译结果，不加任何解释。"
            },
            {
                "role": "user",
                "content": text
            }
        ],
        "max_tokens": 300,
        "temperature": 0.3,
    }).encode("utf-8")
    req = urllib.request.Request(
        OPENROUTER_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPENROUTER_KEY}",
            "HTTP-Referer": "https://github.com/flyhust/kkcai",
            "X-Title": "Content Flywheel",
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            result = json.loads(r.read())
            return result["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        print(f"  [Translation error] {exc}")
        return text  # fallback to original


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def clean_summary(raw: str) -> str:
    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    lines = [l for l in lines if not l.startswith("#") and l not in
             ("Search", "More", "Share", "Menu", "Skip to main content", "View")]
    text = " ".join(lines)
    return re.sub(r"\s{2,}", " ", text)[:400]


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
        "",
        f"📊 今日共 <b>{len(items)}</b> 条新闻",
    ]
    for brand in ["KiraAI", "Coaching", "AI_Agency", "Interest"]:
        if counts.get(brand):
            lines.append(f"{BRAND_EMOJI[brand]} {BRAND_LABEL[brand]}: {counts[brand]}条")
    return "\n".join(lines)


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

    # Translate to Chinese
    print(f"    翻译标题: {raw_title[:50]}")
    title_cn   = translate_to_chinese(raw_title)
    print(f"    翻译摘要...")
    summary_cn = translate_to_chinese(raw_summary)

    lines = [
        f"{emoji} <b>[{label}]</b> | {angle}",
        "",
        f"<b>标题：</b>{esc(title_cn)}",
        f"<b>摘要：</b>{esc(summary_cn)}",
    ]
    if date:
        lines.append(f"<b>日期：</b>{date}")
    if url:
        lines.append(f'<a href="{url}">🔗 来源</a>')
    return "\n".join(lines)


def load_items() -> tuple[list[dict], bool]:
    if os.path.exists("data/briefs.json"):
        with open("data/briefs.json", encoding="utf-8") as f:
            return json.load(f), True
    if os.path.exists("data/news.json"):
        with open("data/news.json", encoding="utf-8") as f:
            return json.load(f), False
    raise FileNotFoundError("No data found. Run fetch_news.py first.")


def run(token: str, chat_id: str, dry_run: bool = False) -> int:
    items, use_brief = load_items()
    source   = "briefs.json" if use_brief else "news.json"
    date_str = datetime.now(MYT).strftime("%Y-%m-%d")

    print(f"Source: {source} ({len(items)} items) — sending to Telegram ...")

    send_message(token, chat_id, build_summary(items, date_str), dry_run)
    time.sleep(1)

    sent  = 0
    total = len(items)
    for brand in ["KiraAI", "Coaching", "AI_Agency", "Interest"]:
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
        if not token:   raise EnvironmentError("TELEGRAM_BOT_TOKEN not set")
        if not chat_id: raise EnvironmentError("TELEGRAM_CHAT_ID not set")

    run(token, chat_id, dry_run=args.dry_run)


if __name__ == "__main__":
    main()

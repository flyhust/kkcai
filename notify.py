"""
notify.py — Content Flywheel: Telegram Daily Briefing
Groups news.json by category; translates English titles in batch per group;
sends one Telegram message per non-empty category group.

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

OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEEPSEEK_MODEL = "deepseek/deepseek-chat"

CATEGORY_DISPLAY: dict[str, tuple[str, str]] = {
    "KiraAI_Local":        ("📊", "KiraAI 本地"),
    "KiraAI_Global":       ("📊", "KiraAI 国际"),
    "Coaching_Local":      ("👔", "Coaching 本地"),
    "Coaching_Global":     ("👔", "Coaching 国际"),
    "AIAgency_Local":      ("🤖", "AI Agency 本地"),
    "AIAgency_Global":     ("🤖", "AI Agency 国际"),
    "Interest_Psychology": ("💡", "Interest 心理学"),
    "Interest_Philosophy": ("💡", "Interest 哲学"),
    "Interest_History":    ("💡", "Interest 历史经济"),
    "Interest_Tech":       ("💡", "Interest 科技"),
}
CATEGORY_ORDER = list(CATEGORY_DISPLAY.keys())

# Legacy support (briefs.json)
BRAND_EMOJI = {"KiraAI": "💳", "Coaching": "🎯", "AI_Agency": "🤖", "Interest": "💡"}
BRAND_LABEL = {"KiraAI": "KiraAI", "Coaching": "Coaching", "AI_Agency": "AI Agency", "Interest": "Interest"}


# ---------------------------------------------------------------------------
# Translation
# ---------------------------------------------------------------------------

def is_english(text: str) -> bool:
    """True if ≥70% of alphabetic characters are ASCII (Latin)."""
    alpha = [c for c in text if c.isalpha()]
    return bool(alpha) and sum(1 for c in alpha if c.isascii()) / len(alpha) > 0.7


def translate_batch(titles: list[str]) -> list[str]:
    """Translate all English titles in one API call. Returns same-length list."""
    if not OPENROUTER_KEY:
        return titles
    indices = [i for i, t in enumerate(titles) if is_english(t)]
    if not indices:
        return titles

    src      = [titles[i] for i in indices]
    numbered = "\n".join(f"{j + 1}. {t}" for j, t in enumerate(src))
    payload  = json.dumps({
        "model": DEEPSEEK_MODEL,
        "messages": [
            {
                "role": "system",
                "content": "你是专业翻译。将用户提供的编号标题逐条翻译成简体中文，保持相同编号格式输出，不加任何解释。",
            },
            {"role": "user", "content": numbered},
        ],
        "max_tokens": 600,
        "temperature": 0.3,
    }).encode("utf-8")
    req = urllib.request.Request(
        OPENROUTER_URL, data=payload,
        headers={
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {OPENROUTER_KEY}",
            "HTTP-Referer":  "https://github.com/flyhust/kkcai",
            "X-Title":       "Content Flywheel",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            resp       = json.loads(r.read())
            translated = resp["choices"][0]["message"]["content"].strip()
        parsed: dict[int, str] = {}
        for line in translated.splitlines():
            m = re.match(r"^(\d+)[.)]\s*(.+)", line.strip())
            if m:
                parsed[int(m.group(1))] = m.group(2).strip()
        result = list(titles)
        for j, idx in enumerate(indices):
            if (j + 1) in parsed:
                result[idx] = parsed[j + 1]
        return result
    except Exception as exc:
        print(f"  [Translation error] {exc}")
        return titles


def translate_to_chinese(text: str) -> str:
    """Single-item translation used by the legacy briefs.json path."""
    if not text.strip() or not OPENROUTER_KEY:
        return text
    payload = json.dumps({
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": "你是专业翻译。将用户输入翻译成简体中文，只输出翻译结果，不加任何解释。"},
            {"role": "user", "content": text},
        ],
        "max_tokens": 300,
        "temperature": 0.3,
    }).encode("utf-8")
    req = urllib.request.Request(
        OPENROUTER_URL, data=payload,
        headers={
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {OPENROUTER_KEY}",
            "HTTP-Referer":  "https://github.com/flyhust/kkcai",
            "X-Title":       "Content Flywheel",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            result = json.loads(r.read())
            return result["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        print(f"  [Translation error] {exc}")
        return text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def stars(score) -> str:
    try:
        return "⭐" * max(1, min(5, int(score)))
    except (TypeError, ValueError):
        return ""


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def esc_url(url: str) -> str:
    return url.replace("&", "&amp;")


def send_message(token: str, chat_id: str, text: str, dry_run: bool = False) -> bool:
    if dry_run:
        print(f"\n{'─' * 55}\n{text}\n")
        return True
    url     = f"https://api.telegram.org/bot{token}/sendMessage"
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


# ---------------------------------------------------------------------------
# New grouped format (news.json with category field)
# ---------------------------------------------------------------------------

def build_header(items: list[dict], date_str: str) -> str:
    cat_counts: dict[str, int] = {}
    for item in items:
        c = item.get("category", item.get("brand", "?"))
        cat_counts[c] = cat_counts.get(c, 0) + 1
    return (
        f"🗞 <b>每日内容简报</b> {date_str}\n"
        f"📊 共 <b>{len(items)}</b> 条新闻 · {len(cat_counts)} 个分类"
    )


def build_group_message(category: str, items: list[dict], translated_titles: list[str]) -> str:
    emoji, label = CATEGORY_DISPLAY.get(category, ("📰", category))
    sep   = "━" * 18
    lines = [sep, f"{emoji} <b>{label}</b> ({len(items)}条)", ""]
    for i, (item, title) in enumerate(zip(items, translated_titles), 1):
        url   = item.get("url", "")
        angle = item.get("suggested_angle", "")
        date  = item.get("published_date", "")
        score = item.get("score")
        star  = (stars(score) + " ") if score is not None else ""
        link  = f'<a href="{esc_url(url)}">{esc(title)}</a>' if url else esc(title)
        meta  = " · ".join(filter(None, [angle, date]))
        lines.append(f"{star}{i}. {link}" + (f" — {meta}" if meta else ""))
    lines.append(sep)
    return "\n".join(lines)


def run_grouped(token: str, chat_id: str, items: list[dict], dry_run: bool) -> int:
    date_str = datetime.now(MYT).strftime("%Y-%m-%d")
    groups: dict[str, list[dict]] = {}
    for item in items:
        groups.setdefault(item.get("category", ""), []).append(item)

    send_message(token, chat_id, build_header(items, date_str), dry_run)
    time.sleep(1)

    sent = 0
    for category in CATEGORY_ORDER:
        group = groups.get(category, [])
        # sort by score desc, drop 1-star articles
        group = sorted(group, key=lambda x: int(x.get("score", 0)), reverse=True)
        group = [item for item in group if int(item.get("score", 0)) > 1]
        if not group:
            continue
        raw_titles = [item.get("title", "") for item in group]
        print(f"  Translating [{category}] ({len(group)} titles) ...")
        translated = translate_batch(raw_titles)
        msg = build_group_message(category, group, translated)
        ok  = send_message(token, chat_id, msg, dry_run)
        print(f"  {'OK' if ok else 'FAIL'} [{category}] {len(group)} articles")
        sent += 1
        time.sleep(1)

    print(f"\nDone: {sent} group messages sent.")
    return sent


# ---------------------------------------------------------------------------
# Legacy format (briefs.json)
# ---------------------------------------------------------------------------

def clean_summary(raw: str) -> str:
    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    lines = [l for l in lines if not l.startswith("#") and l not in
             ("Search", "More", "Share", "Menu", "Skip to main content", "View")]
    text = " ".join(lines)
    return re.sub(r"\s{2,}", " ", text)[:400]


def build_legacy_message(item: dict, use_brief: bool = False) -> str:
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

    print(f"    翻译标题: {raw_title[:50]}")
    title_cn   = translate_to_chinese(raw_title)
    print(f"    翻译摘要...")
    summary_cn = translate_to_chinese(raw_summary)

    lines = [
        f"{emoji} <b>[{label}]</b> | {angle}", "",
        f"<b>标题：</b>{esc(title_cn)}",
        f"<b>摘要：</b>{esc(summary_cn)}",
    ]
    if date: lines.append(f"<b>日期：</b>{date}")
    if url:  lines.append(f'<a href="{esc_url(url)}">🔗 来源</a>')
    return "\n".join(lines)


def run_legacy(token: str, chat_id: str, items: list[dict], use_brief: bool, dry_run: bool) -> int:
    date_str = datetime.now(MYT).strftime("%Y-%m-%d")
    counts   = {b: sum(1 for i in items if i.get("brand") == b)
                for b in ["KiraAI", "Coaching", "AI_Agency", "Interest"]}
    header   = [f"🗞 <b>每日内容简报</b> {date_str}", "", f"📊 今日共 <b>{len(items)}</b> 条新闻"]
    for brand in ["KiraAI", "Coaching", "AI_Agency", "Interest"]:
        if counts.get(brand):
            header.append(f"{BRAND_EMOJI[brand]} {BRAND_LABEL[brand]}: {counts[brand]}条")
    send_message(token, chat_id, "\n".join(header), dry_run)
    time.sleep(1)

    sent  = 0
    total = len(items)
    for brand in ["KiraAI", "Coaching", "AI_Agency", "Interest"]:
        for item in [i for i in items if i.get("brand") == brand]:
            msg = build_legacy_message(item, use_brief)
            ok  = send_message(token, chat_id, msg, dry_run)
            print(f"  {'OK' if ok else 'FAIL'} [{brand}] {item.get('title', item.get('source_title', ''))[:50]}")
            sent += 1
            if sent < total:
                time.sleep(1)

    print(f"\nDone: {sent} messages sent.")
    return sent


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(token: str, chat_id: str, dry_run: bool = False) -> int:
    if os.path.exists("data/news.json"):
        with open("data/news.json", encoding="utf-8") as f:
            items = json.load(f)
        source    = "news.json"
        use_brief = False
    elif os.path.exists("data/briefs.json"):
        with open("data/briefs.json", encoding="utf-8") as f:
            items = json.load(f)
        source    = "briefs.json"
        use_brief = True
    else:
        raise FileNotFoundError("No data found. Run fetch_news.py first.")

    print(f"Source: {source} ({len(items)} items) — sending to Telegram ...")

    if items and "category" in items[0]:
        return run_grouped(token, chat_id, items, dry_run)
    return run_legacy(token, chat_id, items, use_brief, dry_run)


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

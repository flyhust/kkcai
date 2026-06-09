"""
bot_listener.py — Content Flywheel: Telegram Command Bot
Listens for Telegram commands via long-polling and executes pipeline scripts.

Commands:
    /update     — fetch fresh news + send briefing
    /send       — send existing news.json briefing (no fetch)
    /list       — show today's news with global numbers + star ratings
    /pick 1     — generate content draft for item #1
    /pick 1,3,7 — generate drafts for items 1, 3, 7
    /pick 1-5   — generate drafts for items 1 through 5
    /help       — list commands

Usage:
    python bot_listener.py                  # run until Ctrl+C
    python bot_listener.py --timeout 3300   # exit after N seconds (CI use)
"""

import os
import sys
import re
import json
import time
import argparse
import subprocess
import urllib.request
import urllib.parse
import requests
from bs4 import BeautifulSoup
from youtube_transcript_api import YouTubeTranscriptApi
from dotenv import load_dotenv

load_dotenv()

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TOKEN          = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID        = os.getenv("TELEGRAM_CHAT_ID", "")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DRAFT_MODEL    = "anthropic/claude-haiku-4-5"

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

BRAND_VOICE: dict[str, str] = {
    "KiraAI":    "简洁专业，带 Fintech 感，用马来西亚华人口吻",
    "Coaching":  "温暖有力，站在 SME 老板角度",
    "AI_Agency": "实用派，避免技术词汇，帮 SME 省时省人力",
    "Interest":  "思想性强，用知识角度切入商业话题",
}

HELP_TEXT = (
    "🤖 <b>Content Flywheel Bot</b>\n\n"
    "/update      — 抓最新新闻并推送简报\n"
    "/send        — 重发今天简报\n"
    "/pick 1      — 生成第1条内容草稿 + AI解说\n"
    "/pick 1,3,7  — 同时生成多条\n"
    "/pick 1-5    — 生成范围内所有草稿\n"
    "/help        — 显示此说明"
)


# ---------------------------------------------------------------------------
# Telegram helpers
# ---------------------------------------------------------------------------

def api(method: str, **params) -> dict:
    url  = f"https://api.telegram.org/bot{TOKEN}/{method}"
    data = urllib.parse.urlencode(params).encode()
    try:
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except Exception as exc:
        print(f"  [API error] {method}: {exc}")
        return {"ok": False}


def send(chat_id: str | int, text: str) -> None:
    api("sendMessage", chat_id=chat_id, text=text,
        parse_mode="HTML", disable_web_page_preview="true")


def send_long(chat_id: str | int, text: str) -> None:
    """Split at newlines and send in ≤4000-char chunks."""
    MAX = 4000
    if len(text) <= MAX:
        send(chat_id, text)
        return
    chunk = ""
    for line in text.split("\n"):
        candidate = chunk + "\n" + line if chunk else line
        if len(candidate) > MAX:
            send(chat_id, chunk)
            time.sleep(0.4)
            chunk = line
        else:
            chunk = candidate
    if chunk:
        send(chat_id, chunk)


def get_updates(offset: int | None, poll_timeout: int = 30) -> list[dict]:
    params: dict = {"timeout": poll_timeout, "allowed_updates": "message"}
    if offset is not None:
        params["offset"] = offset
    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=poll_timeout + 10) as r:
            return json.loads(r.read()).get("result", [])
    except Exception as exc:
        print(f"  [getUpdates error] {exc}")
        return []


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def load_news_ordered() -> list[dict]:
    """Return news matching notify.py exactly: category order → score desc, 1-star dropped."""
    if not os.path.exists("data/news.json"):
        return []
    with open("data/news.json", encoding="utf-8") as f:
        raw = json.load(f)

    groups: dict[str, list[dict]] = {}
    for item in raw:
        groups.setdefault(item.get("category", ""), []).append(item)

    ordered: list[dict] = []
    for cat in CATEGORY_ORDER:
        grp = sorted(groups.get(cat, []), key=lambda x: int(x.get("score", 0)), reverse=True)
        grp = [item for item in grp if int(item.get("score", 0)) > 1]
        ordered.extend(grp)
    for cat, grp in groups.items():
        if cat not in CATEGORY_ORDER:
            grp = sorted(grp, key=lambda x: int(x.get("score", 0)), reverse=True)
            grp = [item for item in grp if int(item.get("score", 0)) > 1]
            ordered.extend(grp)
    return ordered


def stars(score) -> str:
    try:
        return "⭐" * max(1, min(5, int(score)))
    except (TypeError, ValueError):
        return ""


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def esc_url(url: str) -> str:
    return url.replace("&", "&amp;")


def parse_pick_args(args: str) -> list[int]:
    """Parse '1', '1,3,7', or '1-5' into a list of ints."""
    args = args.strip()
    try:
        if "," in args:
            return [int(x.strip()) for x in args.split(",") if x.strip()]
        if "-" in args:
            a, b = args.split("-", 1)
            return list(range(int(a.strip()), int(b.strip()) + 1))
        return [int(args)]
    except ValueError:
        return []


# ---------------------------------------------------------------------------
# Content fetching
# ---------------------------------------------------------------------------

def _brand(item: dict) -> str:
    cat = item.get("category", item.get("brand", ""))
    if cat.startswith("KiraAI"):   return "KiraAI"
    if cat.startswith("Coaching"): return "Coaching"
    if cat.startswith("AIAgency"): return "AI_Agency"
    if cat.startswith("Interest"): return "Interest"
    return item.get("brand", "KiraAI")


def fetch_full_content(url: str, summary: str) -> tuple[str, str]:
    if "youtube.com" in url or "youtu.be" in url:
        try:
            m = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})", url)
            if m:
                vid_id     = m.group(1)
                transcript = YouTubeTranscriptApi().fetch(
                    vid_id, languages=["zh-Hans", "zh-TW", "zh", "en"]
                )
                text = " ".join(snippet.text for snippet in transcript)
                return text, "youtube"
        except Exception as exc:
            print(f"  [YouTube transcript error] {exc}")
        return summary, "summary_only"

    try:
        resp = requests.get(url, timeout=10,
                            headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(resp.text, "html.parser")
        paras = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
        text  = "\n".join(p for p in paras if len(p) > 50)
        if len(text) > 500:
            return text, "webpage"
    except Exception as exc:
        print(f"  [Web fetch error] {exc}")
    return summary, "summary_only"


# ---------------------------------------------------------------------------
# OpenRouter draft generation
# ---------------------------------------------------------------------------

INTEL_SYSTEM = (
    "你是我的内容研究助理，专门服务马来西亚华人 SME。\n"
    "帮我快速理解文章价值，不是帮我写发布稿。\n"
    "说话直接，point form，像在帮老板做 briefing。\n"
    "不要用 markdown **粗体**，用 emoji 代替强调。"
)


def call_openrouter(messages: list[dict]) -> str:
    payload = json.dumps({
        "model": DRAFT_MODEL,
        "messages": messages,
        "max_tokens": 1800,
        "temperature": 0.7,
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
    with urllib.request.urlopen(req, timeout=60) as r:
        resp = json.loads(r.read())
        return resp["choices"][0]["message"]["content"].strip()


def build_intel_messages(item: dict, full_content: str, source_type: str) -> list[dict]:
    brand       = _brand(item)
    brand_voice = BRAND_VOICE.get(brand, "")
    angle       = item.get("suggested_angle", "")
    url         = item.get("url", "")

    if source_type != "summary_only":
        user = (
            f"品牌：{brand}\n"
            f"品牌风格：{brand_voice}\n"
            f"内容角度：{angle}\n"
            f"文章类型：{source_type}\n"
            f"原文内容：{full_content[:3000]}\n\n"
            "帮我做内容情报：\n\n"
            "1️⃣ 核心信息（原文说了几个列几个，不合并不删减）\n"
            "2️⃣ 对马来西亚 SME 最有用的洞察（1句话）\n"
            f"3️⃣ 用「{angle}」角度可以怎么切入（2-3个方向，每个一句话）\n"
            f"4️⃣ 3个标题选项（口语化，适合{brand}风格）\n"
            "5️⃣ 值不值得做内容？（值得/普通/不值得，一句理由）"
        )
    else:
        user = (
            f"品牌：{brand}\n"
            f"品牌风格：{brand_voice}\n"
            f"内容角度：{angle}\n"
            f"摘要：{full_content}\n\n"
            "⚠️ 只有摘要，不要编造细节。\n\n"
            "1️⃣ 摘要说了什么（point form）\n"
            f"2️⃣ 用「{angle}」可以怎么切入（1-2个方向）\n"
            "3️⃣ 2个标题选项\n"
            f"4️⃣ 值不值得读原文？（值得/不值得，一句理由）\n"
            f"⚠️ 建议读原文：{url}"
        )

    return [
        {"role": "system", "content": INTEL_SYSTEM},
        {"role": "user",   "content": user},
    ]


def generate_draft(item: dict) -> str:
    num   = item.get("_num", "?")
    brand = _brand(item)
    angle = item.get("suggested_angle", "")
    url   = item.get("url", "")
    title = item.get("title", "")
    summary = (item.get("summary", "") or "")[:400]
    sep   = "━" * 18

    print(f"    Fetching content for #{num}: {url[:60]}")
    full_content, source_type = fetch_full_content(url, summary)
    print(f"    Source type: {source_type} ({len(full_content)} chars)")

    header = (
        f"{sep}\n"
        f"📝 #{num} {brand} | {angle}\n"
        f'原文：<a href="{esc_url(url)}">{esc(title)}</a>\n'
        f"来源：{source_type}\n"
    )
    try:
        messages = build_intel_messages(item, full_content, source_type)
        content  = call_openrouter(messages)
    except Exception as exc:
        content = f"❌ 生成失败：{exc}"

    full_msg = f"{header}\n{content}\n{sep}"
    return full_msg


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def run_script(script: str, chat_id: str) -> bool:
    result = subprocess.run(
        [sys.executable, script],
        capture_output=True, text=True, timeout=180,
        env={**os.environ},
    )
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "unknown error")[:300]
        send(chat_id, f"❌ {script} 失败：\n<code>{err}</code>")
        return False
    return True


def handle_update_cmd(chat_id: str) -> None:
    send(chat_id, "⏳ 处理中... 正在抓取最新新闻")
    if not run_script("fetch_news.py", chat_id):
        return
    send(chat_id, "⏳ 正在打分...")
    if not run_script("scorer.py", chat_id):
        return
    send(chat_id, "⏳ 正在推送简报...")
    if not run_script("notify.py", chat_id):
        return
    send(chat_id, "✅ 完成！新闻已抓取、打分并推送。")


def handle_send_cmd(chat_id: str) -> None:
    send(chat_id, "⏳ 处理中... 正在推送现有简报")
    if not run_script("notify.py", chat_id):
        return
    send(chat_id, "✅ 完成！简报已推送。")


def handle_help_cmd(chat_id: str) -> None:
    send(chat_id, HELP_TEXT)



def handle_pick_cmd(chat_id: str, args: str) -> None:
    if not args:
        send(chat_id, "❓ 用法：/pick 1 或 /pick 1,3,7 或 /pick 1-5")
        return

    nums = parse_pick_args(args)
    if not nums:
        send(chat_id, f"❓ 无法解析编号：<code>{esc(args)}</code>")
        return

    items   = load_news_ordered()
    num_map = {i: item for i, item in enumerate(items, 1)}  # ← 与 /list 相同顺序

    valid   = [n for n in nums if n in num_map]
    invalid = [n for n in nums if n not in num_map]

    if not valid:
        send(chat_id, f"❌ 编号不存在：{nums}（共 {len(items)} 条新闻）")
        return
    if invalid:
        send(chat_id, f"⚠️ 以下编号不存在，已跳过：{invalid}")

    send(chat_id, f"⏳ 正在生成草稿...（共 {len(valid)} 条）")

    for n in valid:
        item  = {**num_map[n], "_num": n}
        draft = generate_draft(item)
        # split into ≤1500-char messages at line boundaries
        if len(draft) > 1500:
            lines, chunk = draft.split("\n"), ""
            for line in lines:
                candidate = chunk + "\n" + line if chunk else line
                if len(candidate) > 1500:
                    send(chat_id, chunk)
                    time.sleep(0.4)
                    chunk = line
                else:
                    chunk = candidate
            if chunk:
                send(chat_id, chunk)
        else:
            send(chat_id, draft)
        time.sleep(0.5)

    send(chat_id, f"✅ 草稿已生成，共 {len(valid)} 条")


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

HANDLERS: dict = {
    "/update": handle_update_cmd,
    "/send":   handle_send_cmd,
    "/help":   handle_help_cmd,
}

ARG_HANDLERS: dict = {
    "/pick": handle_pick_cmd,
}


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=int, default=0,
                        help="Exit after N seconds (0 = run forever)")
    args = parser.parse_args()

    if not TOKEN:
        raise EnvironmentError("TELEGRAM_BOT_TOKEN not set in .env")

    start  = time.time()
    offset = None
    print(f"Bot listener started. Authorised chat: {CHAT_ID or '(any)'}")
    print("Commands: /update  /send  /list  /pick  /help   — Ctrl+C to stop\n")

    while True:
        if args.timeout and (time.time() - start) > args.timeout:
            print("Max runtime reached — exiting.")
            break

        updates = get_updates(offset)
        for upd in updates:
            offset  = upd["update_id"] + 1
            msg     = upd.get("message", {})
            text    = msg.get("text", "").strip()
            chat_id = str(msg.get("chat", {}).get("id", ""))

            if not text.startswith("/"):
                continue
            if CHAT_ID and chat_id != CHAT_ID:
                print(f"  Ignored message from unauthorised chat {chat_id}")
                continue

            parts   = text.split(None, 1)
            command = parts[0].lower()
            cmdargs = parts[1] if len(parts) > 1 else ""
            print(f"[{time.strftime('%H:%M:%S')}] {command!r} {cmdargs!r} from {chat_id}")

            if command in ARG_HANDLERS:
                ARG_HANDLERS[command](chat_id, cmdargs)
            elif command in HANDLERS:
                HANDLERS[command](chat_id)
            else:
                send(chat_id, f"❓ 未知指令：{command}\n输入 /help 查看可用指令。")


if __name__ == "__main__":
    main()

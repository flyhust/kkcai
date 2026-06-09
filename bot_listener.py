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
import json
import time
import argparse
import subprocess
import urllib.request
import urllib.parse
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

BRAND_STYLE: dict[str, str] = {
    "KiraAI":    "简洁专业，Fintech 感，马来西亚华人口吻，读者是有账本烦恼的 SME 老板",
    "Coaching":  "温暖有力，启发性，SME 老板视角，让人有共鸣感",
    "AI_Agency": "实用派，帮 SME 解决实际流程问题，不卖弄技术词汇",
    "Interest":  "思想性强，用有趣知识角度切入商业话题，引发分享欲",
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
# OpenRouter draft generation
# ---------------------------------------------------------------------------

def call_openrouter(prompt: str) -> str:
    payload = json.dumps({
        "model": DRAFT_MODEL,
        "messages": [{"role": "user", "content": prompt}],
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


def build_draft_prompt(item: dict) -> str:
    brand   = item.get("brand", "KiraAI")
    angle   = item.get("suggested_angle", "")
    title   = item.get("title", "")
    summary = (item.get("summary", "") or "")[:400]
    style   = BRAND_STYLE.get(brand, "")
    return (
        f"你是马来西亚华人内容营销专家，为 {brand} 账号分析新闻并撰写内容草稿。\n\n"
        f"品牌：{brand}\n"
        f"品牌风格：{style}\n"
        f"兴趣角度：{angle}\n"
        f"新闻标题：{title}\n"
        f"新闻摘要：{summary}\n\n"
        "输出要求：全部用中文，专有名词（品牌名、产品名、英文缩写）保留英文。\n"
        "保留所有 emoji 标签，用实际内容替换括号内的描述，不加多余说明。\n\n"
        "🧠 AI 解说：\n"
        "📌 新闻：（1句话说这条新闻讲什么）\n"
        "🎯 品牌关联：（为什么跟这个品牌相关，1句话）\n"
        "😤 读者痛点：（目标读者的痛点，1句话）\n"
        "💡 内容角度：（建议用什么角度切入，1句话）\n"
        "⭐ 内容机会：（时效性 + 值不值得做，1句话）\n\n"
        "💡 建议标题：\n"
        "（针对 Malaysia 华人 SME，15-25字，有好奇心驱动力）\n\n"
        "📱 IG草稿：\n"
        "（150字以内，口语化，最后3个hashtag）\n\n"
        "👥 FB草稿：\n"
        "（200字以内，附一句链接推荐语）\n\n"
        "📝 Blog开头：\n"
        "（300字，第一句必须抓住注意力）\n\n"
        f"适合账号：（{brand} 的 IG/FB）"
    )


def generate_draft(item: dict) -> str:
    num   = item.get("_num", "?")
    brand = item.get("brand", "")
    angle = item.get("suggested_angle", "")
    url   = item.get("url", "")
    title = item.get("title", "")
    sep   = "━" * 18

    header = (
        f"{sep}\n"
        f"📝 #{num} {brand} | {angle}\n"
        f'原文：<a href="{esc_url(url)}">{esc(title)}</a>\n'
    )
    try:
        content = call_openrouter(build_draft_prompt(item))
    except Exception as exc:
        content = f"❌ 生成失败：{exc}"

    return f"{header}\n{content}\n{sep}"


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
        item = {**num_map[n], "_num": n}
        draft = generate_draft(item)
        send_long(chat_id, draft)
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

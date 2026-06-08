"""
bot_listener.py — Content Flywheel: Telegram Command Bot
Listens for Telegram commands via long-polling and executes pipeline scripts.

Commands:
    /update  — fetch fresh news + send briefing
    /send    — send existing news.json briefing (no fetch)
    /help    — list commands

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

TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")   # authorised chat only

HELP_TEXT = (
    "🤖 <b>Content Flywheel Bot</b>\n\n"
    "/update — 抓取最新新闻并推送简报\n"
    "/send   — 推送现有简报（不重新抓取）\n"
    "/help   — 显示此说明"
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


def get_updates(offset: int | None, poll_timeout: int = 30) -> list[dict]:
    params: dict = {"timeout": poll_timeout, "allowed_updates": "message"}
    if offset is not None:
        params["offset"] = offset
    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=poll_timeout + 10) as r:
            result = json.loads(r.read())
            return result.get("result", [])
    except Exception as exc:
        print(f"  [getUpdates error] {exc}")
        return []


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def run_script(script: str, chat_id: str) -> bool:
    """Run a Python script as subprocess; return True on success."""
    result = subprocess.run(
        [sys.executable, script],
        capture_output=True, text=True, timeout=180,
        env={**os.environ},   # inherit all env vars (keys flow through)
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
    send(chat_id, "⏳ 新闻已抓取，正在推送简报...")
    if not run_script("notify.py", chat_id):
        return
    send(chat_id, "✅ 完成！新闻已抓取并推送。")


def handle_send_cmd(chat_id: str) -> None:
    send(chat_id, "⏳ 处理中... 正在推送现有简报")
    if not run_script("notify.py", chat_id):
        return
    send(chat_id, "✅ 完成！简报已推送。")


def handle_help_cmd(chat_id: str) -> None:
    send(chat_id, HELP_TEXT)


HANDLERS = {
    "/update": handle_update_cmd,
    "/send":   handle_send_cmd,
    "/help":   handle_help_cmd,
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

    start   = time.time()
    offset  = None
    print(f"Bot listener started. Authorised chat: {CHAT_ID or '(any)'}")
    print("Commands: /update  /send  /help   — Ctrl+C to stop\n")

    while True:
        # Honour max-runtime (used by GitHub Actions to exit cleanly)
        if args.timeout and (time.time() - start) > args.timeout:
            print("Max runtime reached — exiting.")
            break

        updates = get_updates(offset)
        for upd in updates:
            offset = upd["update_id"] + 1
            msg     = upd.get("message", {})
            text    = msg.get("text", "").strip()
            chat_id = str(msg.get("chat", {}).get("id", ""))

            if not text.startswith("/"):
                continue

            # Security: only respond to the authorised chat
            if CHAT_ID and chat_id != CHAT_ID:
                print(f"  Ignored message from unauthorised chat {chat_id}")
                continue

            command = text.split()[0].lower()
            print(f"[{time.strftime('%H:%M:%S')}] Command: {command} from {chat_id}")

            handler = HANDLERS.get(command)
            if handler:
                handler(chat_id)
            else:
                send(chat_id, f"❓ 未知指令：{command}\n输入 /help 查看可用指令。")


if __name__ == "__main__":
    main()

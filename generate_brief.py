"""
generate_brief.py — Content Flywheel: Brief Generator
Reads data/news.json, sends each item to Claude API,
outputs a content brief per article to data/briefs.json

Usage:
    python generate_brief.py           # process all items
    python generate_brief.py --limit 5 # test with first 5 items
    python generate_brief.py --resume  # skip already-processed URLs
"""

import os
import sys
import json
import time
import argparse
from dotenv import load_dotenv

load_dotenv()

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MODEL = "claude-haiku-4-5-20251001"

# ---------------------------------------------------------------------------
# Brand voice definitions — injected into every prompt
# ---------------------------------------------------------------------------
BRAND_VOICE: dict[str, str] = {
    "KiraAI": (
        "简洁专业，带 Fintech 感，用马来西亚华人的口吻写作。"
        "读者是有账本、财务管理烦恼的 SME 老板，他们务实、重结果。"
    ),
    "Coaching": (
        "温暖有力，有启发性，站在 SME 老板的角度写。"
        "让人看完有「对，我也有这个问题」的共鸣感。"
    ),
    "AI_Agency": (
        "实用派，帮 SME 解决实际流程问题，避免卖弄技术词汇。"
        "读者是不懂 AI 但想省时间、省人力的老板。"
    ),
    "Interest": (
        "思想性强，用有趣的知识角度切入商业话题。"
        "让人觉得「原来可以这样想」，引发分享欲。"
    ),
}

SYSTEM_PROMPT = (
    "你是专门服务 Malaysia 华人 SME 市场的内容策略师。"
    "根据新闻资讯为指定品牌生成内容简报。"
    "只输出合法 JSON，不加任何说明文字或 markdown 代码块。"
)


def build_prompt(item: dict) -> str:
    brand = item["brand"]
    voice = BRAND_VOICE.get(brand, BRAND_VOICE["Interest"])
    angle = item["suggested_angle"]

    # Build prompt without nested f-string braces conflict
    lines = [
        f"新闻标题：{item['title']}",
        f"新闻摘要：{item['summary'][:300]}",
        f"品牌：{brand}",
        f"内容角度：{angle}",
        f"品牌风格：{voice}",
        "",
        "请生成以下结构的 JSON（直接输出，不要 markdown）：",
        "{",
        f'  "title_suggestion": "针对 Malaysia 华人 SME 的吸引标题，15-25字，要有好奇心驱动力",',
        f'  "angle_explanation": "一句话说明为什么用「{angle}」角度切入这条新闻",',
        '  "draft_300": "300字中文内容草稿，口语化，适合 blog 或公众号开头，第一句必须抓住读者注意力",',
        '  "ig_caption": "IG 版本：150字以内正文 + 换行 + 3个相关 hashtag（用 # 开头）",',
        '  "fb_caption": "FB 版本：200字以内正文 + 换行 + 链接预览推荐语（一句话，吸引点击）",',
        '  "platform_fit": ["blog", "ig", "fb"] 中选出适合的平台组合（数组）,',
        f'  "brand": "{brand}"',
        "}",
    ]
    return "\n".join(lines)


def call_claude(client, item: dict) -> dict | None:
    """Call Claude and return parsed JSON brief, or None on failure."""
    prompt = build_prompt(item)
    try:
        message = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()

        # Strip accidental markdown code fences if model adds them
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.rsplit("```", 1)[0].strip()

        brief = json.loads(raw)

        # Attach source metadata
        brief["source_title"]  = item["title"]
        brief["source_url"]    = item["url"]
        brief["published_date"] = item["published_date"]
        brief["suggested_angle"] = item["suggested_angle"]

        return brief

    except json.JSONDecodeError as exc:
        print(f"  [JSON error] {exc} — raw: {raw[:120]}")
        return None
    except Exception as exc:
        print(f"  [API error] {exc}")
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate content briefs from news.json")
    parser.add_argument("--limit", type=int, default=None, help="Process only first N items")
    parser.add_argument("--resume", action="store_true", help="Skip URLs already in briefs.json")
    args = parser.parse_args()

    # Validate API key
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "ANTHROPIC_API_KEY not set.\n"
            "Add it to .env: ANTHROPIC_API_KEY=sk-ant-..."
        )

    try:
        import anthropic
    except ImportError:
        raise ImportError("anthropic not installed. Run: pip install -r requirements.txt")

    client = anthropic.Anthropic(api_key=api_key)

    # Load news items
    news_path = "data/news.json"
    if not os.path.exists(news_path):
        raise FileNotFoundError(f"{news_path} not found. Run fetch_news.py first.")

    with open(news_path, encoding="utf-8") as f:
        news_items: list[dict] = json.load(f)

    # Resume: skip already-processed URLs
    existing_briefs: list[dict] = []
    briefs_path = "data/briefs.json"
    done_urls: set[str] = set()

    if args.resume and os.path.exists(briefs_path):
        with open(briefs_path, encoding="utf-8") as f:
            existing_briefs = json.load(f)
        done_urls = {b["source_url"] for b in existing_briefs}
        print(f"Resuming — {len(done_urls)} already done, skipping.")

    # Apply filters
    items_to_process = [i for i in news_items if i["url"] not in done_urls]
    if args.limit:
        items_to_process = items_to_process[: args.limit]

    total = len(items_to_process)
    print(f"Generating briefs for {total} articles via {MODEL} ...\n")

    briefs: list[dict] = list(existing_briefs)
    success = 0

    for idx, item in enumerate(items_to_process, start=1):
        title_short = item["title"][:60]
        print(f"[{idx}/{total}] [{item['brand']}] {title_short}")

        brief = call_claude(client, item)
        if brief:
            briefs.append(brief)
            success += 1
            print(f"  OK  angle={item['suggested_angle']}")
        else:
            print(f"  SKIP (error)")

        # Save after every item so partial results are never lost
        with open(briefs_path, "w", encoding="utf-8") as f:
            json.dump(briefs, f, ensure_ascii=False, indent=2)

        if idx < total:
            time.sleep(1)

    print(f"\nDone: {success} briefs generated -> {briefs_path}")


if __name__ == "__main__":
    main()

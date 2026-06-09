"""
scorer.py — Content Flywheel: Article Scorer
Reads data/news.json, scores each article 1-5 via OpenRouter Claude Haiku,
writes score field back to news.json.

Scoring: 10 articles per API call to minimise latency and token cost.
"""

import os
import sys
import json
import time
import urllib.request
from dotenv import load_dotenv

load_dotenv()

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
SCORE_MODEL    = "anthropic/claude-haiku-4-5"
BATCH_SIZE     = 10

BRAND_CONTEXT: dict[str, str] = {
    "KiraAI":    "Fintech，Bank Statement Scanner，Malaysia SME 财务工具",
    "Coaching":  "HR，Business Leadership，Malaysia SME 老板成长",
    "AI_Agency": "AI 自动化，帮 Malaysia SME 解决流程问题",
    "Interest":  "思想类内容，心理学/哲学/历史/科技，切入商业话题",
}

SCORING_CRITERIA = (
    "5 = 内容可做性强 + 品牌高度相关 + 时效性强（今天/昨天）\n"
    "4 = 内容不错 + 相关 + 近期新闻\n"
    "3 = 普通资讯，可以用\n"
    "2 = 相关性低，参考用\n"
    "1 = 不太相关，可跳过"
)


def score_batch(articles: list[dict]) -> dict[int, int]:
    """Score up to BATCH_SIZE articles in one call. Returns {1-based-index: score}."""
    lines = []
    for i, art in enumerate(articles, 1):
        brand   = art.get("brand", "")
        title   = art.get("title", "")
        summary = (art.get("summary", "") or "")[:120]
        ctx     = BRAND_CONTEXT.get(brand, brand)
        lines.append(f"{i}. [{brand}] {title}\n   品牌：{ctx}\n   摘要：{summary}")

    prompt = (
        "你是内容营销专家。为以下新闻各打 1-5 分：\n"
        f"{SCORING_CRITERIA}\n\n"
        + "\n\n".join(lines)
        + "\n\n只输出编号和分数，每行一条，格式：1:5\n不加解释。"
    )

    payload = json.dumps({
        "model": SCORE_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 80,
        "temperature": 0.1,
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
    with urllib.request.urlopen(req, timeout=30) as r:
        resp = json.loads(r.read())
        text = resp["choices"][0]["message"]["content"].strip()

    scores: dict[int, int] = {}
    for line in text.splitlines():
        line = line.strip()
        if ":" in line:
            try:
                idx_s, score_s = line.split(":", 1)
                scores[int(idx_s.strip())] = max(1, min(5, int(score_s.strip())))
            except ValueError:
                pass
    return scores


def main() -> None:
    if not OPENROUTER_KEY:
        raise EnvironmentError("OPENROUTER_API_KEY not set.")

    path = "data/news.json"
    if not os.path.exists(path):
        raise FileNotFoundError(f"{path} not found — run fetch_news.py first.")

    with open(path, encoding="utf-8") as f:
        articles = json.load(f)

    print(f"Scoring {len(articles)} articles via {SCORE_MODEL} ...")

    for start in range(0, len(articles), BATCH_SIZE):
        batch = articles[start : start + BATCH_SIZE]
        end   = start + len(batch)
        print(f"  Batch {start + 1}–{end} ...")
        try:
            scores = score_batch(batch)
            for i, art in enumerate(batch, 1):
                art["score"] = scores.get(i, 3)
        except Exception as exc:
            print(f"  [Warning] Batch failed: {exc} — defaulting score=3")
            for art in batch:
                art["score"] = art.get("score", 3)
        time.sleep(0.5)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)

    print(f"\nDone — {len(articles)} articles scored and saved to {path}")

    dist: dict[int, int] = {}
    for art in articles:
        s = int(art.get("score", 0))
        dist[s] = dist.get(s, 0) + 1
    print("\nScore distribution:")
    for s in sorted(dist.keys(), reverse=True):
        bar = "⭐" * s
        print(f"  {bar:<10} {dist[s]:>3} 条")


if __name__ == "__main__":
    main()

"""
fetch_news.py — Content Flywheel: News Fetcher
Fetches recent news via Exa API across brand pillars and assigns a
suggested interest-domain angle for content ideation.

Brands:  KiraAI | Coaching | AI_Agency | Interest
Output:  data/news.json
Max:     20 articles total
"""

import os
import sys
import json
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()

INTEREST_ANGLES: dict[str, list[str]] = {
    "心理学":   ["psychology", "cognitive", "bias", "behavior", "mindset", "emotional", "subconscious"],
    "自然科学": ["science", "research", "experiment", "evidence", "biology", "physics", "chemistry"],
    "金融学":   ["finance", "banking", "fintech", "investment", "capital", "funding", "loan", "bank", "credit"],
    "家庭亲子": ["family", "parenting", "work-life", "balance", "children", "home", "parent"],
    "经济学":   ["economy", "economic", "gdp", "market", "trade", "inflation", "growth", "recession", "supply"],
    "法律":     ["law", "legal", "regulation", "compliance", "policy", "court", "rights", "contract"],
    "政治学":   ["politics", "government", "policy", "regulatory", "election", "parliament", "governance"],
    "管理学":   ["management", "leadership", "organization", "strategy", "team", "operations", "executive"],
    "自我提升": ["productivity", "growth", "skill", "learning", "development", "habit", "discipline", "self"],
    "医学与健康": ["health", "wellness", "medical", "stress", "burnout", "wellbeing", "mental health"],
    "职场":     ["workplace", "career", "hr", "hiring", "employee", "talent", "workforce", "recruitment"],
    "历史":     ["history", "historical", "evolution", "origin", "traditional", "legacy", "century", "era"],
    "中国历史": ["chinese", "china", "dynasty", "ancient", "heritage", "qing", "ming", "tang", "confucius"],
    "社会学":   ["society", "social", "community", "culture", "demographic", "inequality", "class"],
    "哲学":     ["philosophy", "principle", "framework", "thinking", "wisdom", "ethics", "stoic", "meaning"],
    "科技":     ["technology", "ai", "automation", "digital", "innovation", "software", "saas", "tech", "llm"],
    "科幻":     ["future", "sci-fi", "vision", "possibility", "singularity", "robot", "dystopia"],
    "艺术":     ["art", "creative", "design", "aesthetic", "visual", "craft", "gallery"],
    "文学":     ["story", "narrative", "writing", "communication", "language", "metaphor", "novel"],
    "互联网":   ["internet", "platform", "digital", "online", "app", "e-commerce", "social media", "saas"],
    "品牌营销": ["marketing", "brand", "content", "campaign", "advertising", "audience", "viral", "seo"],
    "商业":     ["business", "sme", "entrepreneur", "company", "corporate", "b2b", "revenue", "profit"],
    "创业":     ["startup", "founder", "venture", "entrepreneur", "build", "mvp", "fundraise", "bootstrapping"],
}

BRAND_QUERIES: dict[str, list[str]] = {
    "KiraAI": [
        "fintech Malaysia SME",
        "bank statement AI scanner",
        "SME finance tools Malaysia",
    ],
    "Coaching": [
        "Malaysia SME coaching business",
        "business leadership Malaysia",
        "HR trends Malaysia 2025",
    ],
    "AI_Agency": [
        "AI automation SME Malaysia",
        "workflow automation small business",
        "business AI tools productivity",
    ],
    "Interest": [
        "psychology business leadership behavior",
        "philosophy leadership decision making",
        "history economics financial",
    ],
}

DEFAULT_ANGLES: dict[str, str] = {
    "KiraAI":    "金融学",
    "Coaching":  "管理学",
    "AI_Agency": "科技",
    "Interest":  "哲学",
}

MAX_ARTICLES = 20  # total cap


def score_angle(text: str) -> str | None:
    text_lower = text.lower()
    scores: dict[str, int] = {}
    for domain, keywords in INTEREST_ANGLES.items():
        hits = sum(1 for kw in keywords if kw in text_lower)
        if hits:
            scores[domain] = hits
    return max(scores, key=scores.get) if scores else None


def fetch_brand_news(exa, brand: str, queries: list[str],
                     days_back: int = 7, results_per_query: int = 3) -> list[dict]:
    """Fetch and deduplicate news items for one brand pillar (max 3 per query)."""
    results: list[dict] = []
    seen_urls: set[str] = set()
    cutoff = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%dT%H:%M:%SZ")

    for query in queries:
        try:
            from exa_py.api import ContentsOptions, TextContentsOptions
            response = exa.search(
                query,
                type="auto",
                num_results=results_per_query,
                start_published_date=cutoff,
                contents=ContentsOptions(text=TextContentsOptions(max_characters=600)),
            )
            for item in response.results:
                if item.url in seen_urls:
                    continue
                seen_urls.add(item.url)
                combined_text = f"{item.title or ''} {item.text or ''}"
                angle = score_angle(combined_text) or DEFAULT_ANGLES[brand]
                results.append({
                    "title":           item.title or "",
                    "summary":         (item.text or "").strip()[:350],
                    "url":             item.url,
                    "brand":           brand,
                    "suggested_angle": angle,
                    "published_date":  (item.published_date or "")[:10],
                    "query_used":      query,
                })
            time.sleep(0.4)
        except Exception as exc:
            print(f"  [Warning] Query '{query}' failed: {exc}")

    return results


def main() -> None:
    api_key = os.getenv("EXA_API_KEY")
    if not api_key:
        raise EnvironmentError("EXA_API_KEY not set.")

    try:
        from exa_py import Exa
    except ImportError:
        raise ImportError("exa-py not installed. Run: pip install -r requirements.txt")

    exa = Exa(api_key=api_key)

    all_news: list[dict] = []
    for brand, queries in BRAND_QUERIES.items():
        print(f"\nFetching [{brand}] ...")
        items = fetch_brand_news(exa, brand, queries)
        print(f"  -> {len(items)} articles")
        all_news.extend(items)

    # Sort by date descending, cap at MAX_ARTICLES
    all_news.sort(key=lambda x: x["published_date"], reverse=True)
    all_news = all_news[:MAX_ARTICLES]

    os.makedirs("data", exist_ok=True)
    output_path = "data/news.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_news, f, ensure_ascii=False, indent=2)

    print(f"\nDone - {len(all_news)} articles saved to {output_path}")

    print("\nAngle distribution:")
    angle_counts: dict[str, int] = {}
    for item in all_news:
        a = item["suggested_angle"]
        angle_counts[a] = angle_counts.get(a, 0) + 1
    for angle, count in sorted(angle_counts.items(), key=lambda x: -x[1]):
        print(f"  {angle:<10} {count}")


if __name__ == "__main__":
    main()

"""
fetch_news.py — Content Flywheel: News Fetcher (Dual-Engine)
Exa  = Malaysia local news  (KiraAI_Local, Coaching_Local, AIAgency_Local)
AnySearch = global + Interest (everything else)

Output: data/news.json  (≤5 per category, global URL dedup)
"""

import os
import sys
import json
import time
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()

INTEREST_ANGLES: dict[str, list[str]] = {
    "心理学":    ["psychology", "cognitive", "bias", "behavior", "mindset", "emotional", "subconscious"],
    "自然科学":  ["science", "research", "experiment", "evidence", "biology", "physics", "chemistry"],
    "金融学":    ["finance", "banking", "fintech", "investment", "capital", "funding", "loan", "bank", "credit"],
    "家庭亲子":  ["family", "parenting", "work-life", "balance", "children", "home", "parent"],
    "经济学":    ["economy", "economic", "gdp", "market", "trade", "inflation", "growth", "recession", "supply"],
    "法律":      ["law", "legal", "regulation", "compliance", "policy", "court", "rights", "contract"],
    "政治学":    ["politics", "government", "policy", "regulatory", "election", "parliament", "governance"],
    "管理学":    ["management", "leadership", "organization", "strategy", "team", "operations", "executive"],
    "自我提升":  ["productivity", "growth", "skill", "learning", "development", "habit", "discipline", "self"],
    "医学与健康": ["health", "wellness", "medical", "stress", "burnout", "wellbeing", "mental health"],
    "职场":      ["workplace", "career", "hr", "hiring", "employee", "talent", "workforce", "recruitment"],
    "历史":      ["history", "historical", "evolution", "origin", "traditional", "legacy", "century", "era"],
    "中国历史":  ["chinese", "china", "dynasty", "ancient", "heritage", "qing", "ming", "tang", "confucius"],
    "社会学":    ["society", "social", "community", "culture", "demographic", "inequality", "class"],
    "哲学":      ["philosophy", "principle", "framework", "thinking", "wisdom", "ethics", "stoic", "meaning"],
    "科技":      ["technology", "ai", "automation", "digital", "innovation", "software", "saas", "tech", "llm"],
    "科幻":      ["future", "sci-fi", "vision", "possibility", "singularity", "robot", "dystopia"],
    "艺术":      ["art", "creative", "design", "aesthetic", "visual", "craft", "gallery"],
    "文学":      ["story", "narrative", "writing", "communication", "language", "metaphor", "novel"],
    "互联网":    ["internet", "platform", "digital", "online", "app", "e-commerce", "social media", "saas"],
    "品牌营销":  ["marketing", "brand", "content", "campaign", "advertising", "audience", "viral", "seo"],
    "商业":      ["business", "sme", "entrepreneur", "company", "corporate", "b2b", "revenue", "profit"],
    "创业":      ["startup", "founder", "venture", "entrepreneur", "build", "mvp", "fundraise", "bootstrapping"],
}

# (engine, brand, default_angle)
CATEGORY_CONFIG: dict[str, tuple[str, str, str]] = {
    "KiraAI_Local":        ("exa",       "KiraAI",    "金融学"),
    "Coaching_Local":      ("exa",       "Coaching",  "管理学"),
    "AIAgency_Local":      ("exa",       "AI_Agency", "科技"),
    "KiraAI_Global":       ("anysearch", "KiraAI",    "金融学"),
    "Coaching_Global":     ("anysearch", "Coaching",  "管理学"),
    "AIAgency_Global":     ("anysearch", "AI_Agency", "科技"),
    "Interest_Psychology": ("anysearch", "Interest",  "心理学"),
    "Interest_Philosophy": ("anysearch", "Interest",  "哲学"),
    "Interest_History":    ("anysearch", "Interest",  "历史"),
    "Interest_Tech":       ("anysearch", "Interest",  "科技"),
}

CATEGORY_QUERIES: dict[str, list[str]] = {
    "KiraAI_Local":        ["fintech Malaysia SME 2026", "bank statement Malaysia", "e-invoice Malaysia SME"],
    "Coaching_Local":      ["Malaysia SME coaching 2026", "HR trends Malaysia", "business leadership Malaysia"],
    "AIAgency_Local":      ["AI automation Malaysia SME", "digital transformation Malaysia 2026"],
    "KiraAI_Global":       ["AI bank statement scanner global", "fintech automation international 2026"],
    "Coaching_Global":     ["business leadership research 2026", "HR management trends global"],
    "AIAgency_Global":     ["AI workflow automation 2026", "agentic AI business tools"],
    "Interest_Psychology": ["psychology business behavior research 2026"],
    "Interest_Philosophy": ["philosophy leadership decision stoic"],
    "Interest_History":    ["history economics financial crisis 2026"],
    "Interest_Tech":       ["AI research breakthrough 2026"],
}

EXA_URL       = "https://api.exa.ai/search"
ANYSEARCH_URL = "https://api.anysearch.com/v1/search"
MAX_PER_CATEGORY = 5


def score_angle(text: str) -> str | None:
    text_lower = text.lower()
    scores: dict[str, int] = {}
    for domain, keywords in INTEREST_ANGLES.items():
        hits = sum(1 for kw in keywords if kw in text_lower)
        if hits:
            scores[domain] = hits
    return max(scores, key=scores.get) if scores else None


def fetch_exa_category(
    api_key: str, category: str, queries: list[str],
    brand: str, default_angle: str, seen_urls: set[str],
) -> list[dict]:
    results: list[dict] = []
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    cutoff  = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")

    for query in queries:
        if len(results) >= MAX_PER_CATEGORY:
            break
        try:
            payload = {
                "query": query,
                "type": "auto",
                "numResults": MAX_PER_CATEGORY,
                "startPublishedDate": cutoff,
                "contents": {"text": {"maxCharacters": 600}},
            }
            resp = requests.post(EXA_URL, headers=headers, json=payload, timeout=20)
            resp.raise_for_status()
            for item in (resp.json().get("results") or []):
                if len(results) >= MAX_PER_CATEGORY:
                    break
                url = item.get("url", "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                title = item.get("title", "")
                text  = item.get("text", "") or ""
                angle = score_angle(f"{title} {text}") or default_angle
                results.append({
                    "title":           title,
                    "summary":         text.strip()[:350],
                    "url":             url,
                    "brand":           brand,
                    "category":        category,
                    "suggested_angle": angle,
                    "published_date":  (item.get("publishedDate") or "")[:10],
                    "query_used":      query,
                })
            time.sleep(0.4)
        except Exception as exc:
            print(f"  [Warning] Exa '{query}': {exc}")

    return results


def fetch_anysearch_category(
    api_key: str, category: str, queries: list[str],
    brand: str, default_angle: str, seen_urls: set[str],
) -> list[dict]:
    results: list[dict] = []
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    for query in queries:
        if len(results) >= MAX_PER_CATEGORY:
            break
        try:
            payload = {"query": query, "max_results": MAX_PER_CATEGORY, "content_types": ["news"]}
            resp = requests.post(ANYSEARCH_URL, headers=headers, json=payload, timeout=20)
            resp.raise_for_status()
            for item in (resp.json().get("data", {}).get("results") or []):
                if len(results) >= MAX_PER_CATEGORY:
                    break
                url = item.get("url", "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                title        = item.get("title", "")
                snippet      = item.get("snippet", "") or ""
                content      = item.get("content", "") or ""
                summary_text = content if content else snippet
                angle = score_angle(f"{title} {summary_text}") or default_angle
                results.append({
                    "title":           title,
                    "summary":         summary_text.strip()[:350],
                    "url":             url,
                    "brand":           brand,
                    "category":        category,
                    "suggested_angle": angle,
                    "published_date":  (item.get("published_date") or "")[:10],
                    "query_used":      query,
                })
            time.sleep(0.4)
        except Exception as exc:
            print(f"  [Warning] AnySearch '{query}': {exc}")

    return results


def main() -> None:
    exa_key       = os.getenv("EXA_API_KEY")
    anysearch_key = os.getenv("ANYSEARCH_API_KEY")
    if not exa_key:
        raise EnvironmentError("EXA_API_KEY not set.")
    if not anysearch_key:
        raise EnvironmentError("ANYSEARCH_API_KEY not set.")

    all_news:  list[dict] = []
    seen_urls: set[str]   = set()

    for category, (engine, brand, default_angle) in CATEGORY_CONFIG.items():
        queries = CATEGORY_QUERIES[category]
        print(f"\nFetching [{category}] via {engine.upper()} ...")
        if engine == "exa":
            items = fetch_exa_category(exa_key, category, queries, brand, default_angle, seen_urls)
        else:
            items = fetch_anysearch_category(anysearch_key, category, queries, brand, default_angle, seen_urls)
        print(f"  -> {len(items)} articles")
        all_news.extend(items)

    os.makedirs("data", exist_ok=True)
    output_path = "data/news.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_news, f, ensure_ascii=False, indent=2)

    print(f"\nDone — {len(all_news)} articles saved to {output_path}")

    print("\nCategory breakdown:")
    cat_counts: dict[str, int] = {}
    for item in all_news:
        c = item["category"]
        cat_counts[c] = cat_counts.get(c, 0) + 1
    for cat, count in cat_counts.items():
        print(f"  {cat:<25} {count}")


if __name__ == "__main__":
    main()

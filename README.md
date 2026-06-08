# Content Flywheel — News Fetcher

为 **KiraAI Malaysia · HR & Business Coaching · AI Automation Agency** 打造的内容飞轮工具。

第一步：从 Exa API 抓取最新行业新闻，并自动为每篇文章匹配一个「兴趣领域切入角度」，用于内容创作灵感。

---

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 API Key

```bash
# Windows
copy .env.example .env

# macOS / Linux
cp .env.example .env
```

然后用文本编辑器打开 `.env`，填入你的 Exa API Key：

```
EXA_API_KEY=your_real_key_here
```

> 在 [exa.ai](https://exa.ai) 注册即可获得免费额度。

### 3. 运行

```bash
python fetch_news.py
```

结果保存到 `data/news.json`。

---

## 输出格式

```json
[
  {
    "title":           "Why Malaysian SMEs Are Slow to Adopt AI",
    "summary":         "A new report highlights that...",
    "url":             "https://example.com/article",
    "brand":           "AI_Agency",
    "suggested_angle": "心理学",
    "published_date":  "2025-06-08",
    "query_used":      "AI automation SME Malaysia"
  }
]
```

| 字段 | 说明 |
|---|---|
| `title` | 文章标题 |
| `summary` | 摘要（最多 350 字符） |
| `url` | 原文链接 |
| `brand` | 品牌分类：`KiraAI` / `Coaching` / `AI_Agency` / `Interest` |
| `suggested_angle` | 推荐内容切入角度（23 个兴趣领域之一） |
| `published_date` | 发布日期 |
| `query_used` | 用于搜索的关键词 |

---

## 品牌 × 搜索关键词

| 品牌 | 搜索词 | 默认角度 |
|---|---|---|
| KiraAI | fintech Malaysia、bank statement AI、SME finance tools | 金融学 |
| Coaching | Malaysia SME coaching、business leadership、HR trends | 管理学 |
| AI_Agency | AI automation SME、workflow automation、business AI tools | 科技 |
| Interest | psychology business、philosophy leadership、history economics | 哲学 |

---

## 内容角度（23 个兴趣领域）

心理学 · 自然科学 · 金融学 · 家庭亲子 · 经济学 · 法律 · 政治学 · 管理学 · 自我提升 · 医学与健康 · 职场 · 历史 · 中国历史 · 社会学 · 哲学 · 科技 · 科幻 · 艺术 · 文学 · 互联网 · 品牌营销 · 商业 · 创业

**内容策略示例：**
- AI 新闻 + 心理学 → *"为什么 SME 老板抗拒 AI？认知偏见的真相"*
- Fintech 新闻 + 历史 → *"从古代钱庄到 KiraAI，华人生意人的账本进化史"*
- HR 趋势 + 管理学 → *"2025 年留住人才的关键：管理学告诉你的 3 件事"*

---

## 项目结构

```
kkcai/
├── fetch_news.py
├── generate_brief.py
├── notify.py
├── bot_listener.py
├── requirements.txt
├── .env.example
├── .env               # 真实 key（不提交 git）
├── .gitignore
├── data/
│   └── news.json
└── .github/
    └── workflows/
        ├── daily_news.yml
        └── bot_listener.yml
```

---

## 下一步（Roadmap）

- [ ] `generate_brief.py` — 用 Claude API 把新闻 + 角度生成内容简报
- [ ] `publish.py` — 推送到 Notion / Google Sheets 内容日历
- [ ] 定时自动抓取（每日 cron）

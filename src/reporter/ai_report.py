"""
AI 深度日报 HTML 生成器

板块：🧠 模型权重 | 🔧 Agent工具链 | 📊 数据评测 | ⚡ 爆发 | ⚠️ 风险关注 | 📈 趋势
"""
import os
from collections import Counter
from datetime import datetime, timezone

from config import REPORTS_DIR
from src.utils.html_safe import esc, safe_href, safe_text_br


def _repo_card(repo: dict, idx: int, section: str,
                readme_cache: dict = None, llm_analyses: dict = None) -> str:
    """AI 垂类项目卡片 — 多维度展示"""
    stars = repo.get("stars", 0)
    inc = repo.get("stars_in_period", 0) or 0
    forks = repo.get("forks", 0)
    lang = repo.get("language", "Unknown")
    eco = repo.get("ai_eco_tags", [])
    tags = repo.get("tags", [])
    extra = repo.get("_extra", {}) or {}
    llm_analyses = llm_analyses or {}
    readme_cache = readme_cache or {}

    score_key = {
        "model": "ai_model_score", "agent": "ai_agent_score",
        "data": "ai_data_score", "warning": "ai_warning_score",
    }.get(section, "")

    score_val = repo.get(score_key, 0) if score_key else 0
    score_html = f' <span class="ai-score">{(score_val*100):.0f}分</span>' if score_val > 0 else ""

    # 多维评分徽章
    score_badges = []
    for label, key, icon in [
        ("爆发", "burst_score", "🧨"),
        ("质量", "quality_score", "🏆"),
        ("AI雷达", "ai_radar_score", "🤖"),
    ]:
        val = repo.get(key, 0)
        if val > 0:
            score_badges.append(f'<span class="badge badge-info">{icon} {label} {val:.0%}</span>')
    scores_html = " ".join(score_badges) if score_badges else ""

    eco_html = " · ".join(f'<span class="eco-tag">{esc(t)}</span>' for t in eco) if eco else ""
    tags_html = " · ".join(f'<span class="tag-item">{esc(t)}</span>' for t in tags) if tags else ""

    # 描述：优先 LLM 分析的「一句话定位」，其次原始描述
    llm = llm_analyses.get(repo["full_name"], "")
    if llm:
        # 提取 🚀 一句话定位
        for line in llm.split("\n"):
            if "🚀" in line or "一句话定位" in line:
                parts = line.split("：", 1) if "：" in line else line.split(":", 1)
                if len(parts) > 1:
                    desc_html = parts[1].replace("**", "").strip()[:200]
                else:
                    desc_html = line.replace("**", "").strip()[:200]
                break
        else:
            desc_html = (repo.get("description", "") or "")[:200]
    else:
        from src.processor.describe_cn import generate_cn_intro_with_readme
        readme = readme_cache.get(repo["full_name"], "")
        desc_html = generate_cn_intro_with_readme(repo, readme)
        # 取 🚀 一句话定位 行
        for line in desc_html.split("\n"):
            if "🚀" in line or "一句话定位" in line:
                parts = line.split("：", 1) if "：" in line else line.split(":", 1)
                desc_html = parts[1].replace("**", "").strip()[:200] if len(parts) > 1 else line.replace("**", "").strip()[:200]
                break
        else:
            desc_html = desc_html[:200]

    # 健康度摘要
    health_parts = []
    if extra.get("contributors", 0) >= 10:
        health_parts.append(f'👥 {extra["contributors"]}人')
    if extra.get("open_issues", 0):
        health_parts.append(f'🐛 {extra["open_issues"]} issues')
    if extra.get("last_push_days", 999) <= 7:
        health_parts.append('🟢 活跃')
    elif extra.get("last_push_days", 999) <= 90:
        health_parts.append('🟡 较活跃')
    health_html = ' <span class="health-meta">' + " · ".join(health_parts) + '</span>' if health_parts else ""

    warning_html = ""
    if section == "warning":
        risks = []
        if extra.get("last_push_days", 0) > 365:
            risks.append("⏸ 停更超1年")
        elif extra.get("last_push_days", 0) > 180:
            risks.append("⏸ 半年未更新")
        if extra.get("contributors", 0) <= 1 and stars > 1000:
            risks.append("👤 单人维护")
        if extra.get("open_issues", 0) > 50:
            risks.append(f"🐛 {extra['open_issues']}个开放Issue")
        if risks:
            warning_html = '<div class="risk-list">' + " · ".join(risks) + '</div>'

    return f"""<div class="repo-card{' trap-card' if section == 'warning' else ''}">
<div class="repo-header">
<span class="repo-rank">#{idx}</span>
<a href="{safe_href(repo.get('url', ''))}" target="_blank" class="repo-name">{esc(repo.get('full_name', ''))}</a>{score_html}
</div>
<div class="repo-desc">{esc(desc_html)}</div>
<div class="repo-stats">
<span>⭐ {stars:,}</span>
{"<span>📈 +" + f"{inc:,}</span>" if inc else ""}
<span>🍴 {forks:,}</span>
<span>🗣 {lang}</span>
{health_html}
</div>
{scores_html and f'<div class="repo-scores">{scores_html}</div>'}
{eco_html and f'<div class="eco-bar">{eco_html}</div>'}
{tags_html and f'<div class="tag-bar">{tags_html}</div>'}
{warning_html}
</div>"""


def generate_ai_report(focus_repos: list[dict], sections: dict, date_str: str,
                       readme_cache: dict = None, llm_analyses: dict = None) -> str:
    """生成 AI 深度日报 HTML"""
    from src.processor.ai_scoring import get_ai_section_repos

    readme_cache = readme_cache or {}
    llm_analyses = llm_analyses or {}

    now = datetime.strptime(date_str, "%Y-%m-%d") if date_str else datetime.now(timezone.utc)
    date_display = now.strftime("%Y年%m月%d日")
    sec_repos = sections or get_ai_section_repos(focus_repos)

    # 趋势统计
    total_ai = len(focus_repos)
    eco_counter = Counter()
    tag_counter = Counter()
    lang_counter = Counter()
    for r in focus_repos:
        for e in r.get("ai_eco_tags", []):
            eco_counter[e] += 1
        for t in r.get("tags", []):
            tag_counter[t] += 1
        lang_counter[r.get("language", "Unknown")] += 1

    top_ecos = eco_counter.most_common(8)
    top_tags = tag_counter.most_common(8)
    top_langs = lang_counter.most_common(6)

    sections_def = [
        ("🧠", "模型 & 权重", "model", "权重已开源、支持多框架的 AI 模型项目", sec_repos.get("model", [])),
        ("🔧", "Agent & 工具链", "agent", "MCP/RAG/Agent 编排等 AI 开发工具", sec_repos.get("agent", [])),
        ("📊", "数据 & 评测", "data", "数据集、benchmark、学术评测项目", sec_repos.get("data", [])),
        ("⚡", "AI 爆发信号", "burst", "AI 领域今日增长最快的项目", sec_repos.get("burst", [])),
        ("⚠️", "风险关注", "warning", "高热度但需关注风险的 AI 项目", sec_repos.get("warning", [])),
    ]

    sections_html = []
    for icon, title, key, subtitle, repos in sections_def:
        sections_html.append(f'<h2><span class="icon">{icon}</span>{title}</h2>')
        sections_html.append(f'<div class="subtitle">{subtitle}</div>')
        if repos:
            for i, r in enumerate(repos, 1):
                sections_html.append(_repo_card(r, i, key, readme_cache, llm_analyses))
        else:
            sections_html.append('<div class="repo-card"><p style="color:var(--text-dim)">暂无项目入榜</p></div>')

    # 趋势看板
    eco_html = " · ".join(
        f'<span class="eco-tag">{esc(e)} <small>{c}</small></span>' for e, c in top_ecos
    )
    tag_html = " · ".join(
        f'<span class="eco-tag">{esc(t)} <small>{c}</small></span>' for t, c in top_tags
    )
    lang_html = " · ".join(
        f'<span class="eco-tag">{esc(l)} <small>{c}</small></span>' for l, c in top_langs
    )

    return f"""<div class="container">
<h1>🤖 AI 深度分析 <span class="date">— {date_display}</span></h1>
<div class="summary-bar">
    <div class="summary-item"><span class="num">{total_ai}</span><span class="label">AI 项目</span></div>
    <div class="summary-item"><span class="num">{len(sec_repos.get('model', []))}</span><span class="label">模型权重</span></div>
    <div class="summary-item"><span class="num">{len(sec_repos.get('agent', []))}</span><span class="label">Agent工具</span></div>
    <div class="summary-item"><span class="num">{len(sec_repos.get('warning', []))}</span><span class="label">风险关注</span></div>
</div>

{"".join(sections_html)}

<h2>📈 AI 趋势看板</h2>
<div class="trend-block">
<p><strong>🏢 生态分布</strong></p>
<p>{eco_html}</p>
</div>
<div class="trend-block">
<p><strong>🏷️ 热门领域</strong></p>
<p>{tag_html}</p>
</div>
<div class="trend-block">
<p><strong>🗣 编程语言</strong></p>
<p>{lang_html}</p>
</div>

<footer>📬 AI 深度报告由 GitHub Trending Daily Bot 自动生成 — {now.strftime('%Y-%m-%d %H:%M')} UTC</footer>
</div>"""


def save_ai_report(html: str, date_str: str) -> str:
    os.makedirs(REPORTS_DIR, exist_ok=True)
    path = os.path.join(REPORTS_DIR, f"ai-{date_str}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path

"""
自定义日报 HTML 生成器
根据用户查询动态生成板块
"""
import os
from collections import Counter
from datetime import datetime

from config import REPORTS_DIR


def _match_repo(repo: dict, keywords: list[str], exclude: list[str],
                language: str = None, min_stars: int = 30) -> bool:
    """检查仓库是否匹配关键词"""
    text = (
        f"{repo.get('name', '')} "
        f"{repo.get('description', '') or ''} "
        f"{' '.join(repo.get('topics', []))}"
    ).lower()

    # 排除词
    for ex in exclude:
        if ex.lower() in text:
            return False

    # 语言过滤
    if language and repo.get("language", "").lower() != language.lower():
        return False

    # 最低星数
    if repo.get("stars", 0) < min_stars:
        return False

    # 关键词匹配
    return any(kw.lower() in text for kw in keywords)


def _card(repo: dict, idx: int) -> str:
    stars = repo.get("stars", 0)
    inc = repo.get("stars_in_period", 0) or 0
    lang = repo.get("language", "Unknown")
    desc = (repo.get("description", "") or "")[:200]
    tags = " · ".join(f'<span class="eco-tag">{t}</span>' for t in repo.get("tags", [])[:3])

    return f"""<div class="repo-card">
<div class="repo-header">
<span class="repo-rank">#{idx}</span>
<a href="{repo['url']}" target="_blank" class="repo-name">{repo['full_name']}</a>
</div>
<div class="repo-desc">{desc}</div>
<div class="repo-stats">
<span>⭐ {stars:,}</span>
{"<span>📈 +" + f"{inc:,}</span>" if inc else ""}
<span>🗣 {lang}</span>
</div>
{tags and f'<div class="tag-bar">{tags}</div>'}
</div>"""


def generate_custom_report(
    repos: list[dict],
    query: str,
    parsed: dict,
    sections: dict,
    readme_cache: dict = None,
    basic_repos: list[dict] = None,
    min_threshold: int = 5,
) -> str:
    """生成自定义日报 HTML

    Args:
        repos: 全量仓库（用于自定义匹配）
        query: 用户原始查询
        parsed: parse_query 返回的结构化条件
        sections: generate_sections 返回的板块定义
        readme_cache: README 缓存
        basic_repos: 基础模块热门项目，当自定义板块项目不足时补充（去重）
        min_threshold: 板块项目少于此数时触发补充
    """
    keywords = parsed.get("keywords", [])
    exclude = parsed.get("exclude", [])
    language = parsed.get("language")
    min_stars = parsed.get("min_stars", 30)
    topic = parsed.get("topic", query[:20])
    sec_defs = sections.get("sections", [])

    # 匹配仓库
    matched = [r for r in repos if _match_repo(r, keywords, exclude, language, min_stars)]

    # 语言分布
    lang_counter = Counter(r.get("language", "Unknown") for r in matched)

    # 基础模块补充源（按热度降序）
    basic_pool = sorted(basic_repos or [], key=lambda r: r.get("hot_score", 0), reverse=True)

    # 按板块分组
    sec_repos = {}
    used_full_names = set()  # 全局去重：所有板块已用过的项目
    for sec in sec_defs:
        sort_by = sec.get("sort_by", "hot_score")
        limit = sec.get("limit", 10)
        filter_new = sec.get("filter_new", False)

        items = list(matched)
        if filter_new:
            items = [r for r in items if r.get("_extra", {}).get("created_days", 999) <= 90]

        if sort_by == "dashboard":
            sec_repos[sec["title"]] = []
            continue
        elif sort_by == "quality_score":
            items = sorted(items, key=lambda r: r.get("quality_score", 0), reverse=True)
        elif sort_by == "stars":
            items = sorted(items, key=lambda r: r.get("stars", 0), reverse=True)
        else:
            items = sorted(items, key=lambda r: r.get("hot_score", 0), reverse=True)

        # 取前 limit 个，记录已用
        picked = []
        for r in items:
            if len(picked) >= limit:
                break
            picked.append(r)
            used_full_names.add(r["full_name"])

        # 项目不足时从基础模块补充（去重）
        if len(picked) < min_threshold and basic_pool:
            for r in basic_pool:
                if len(picked) >= min_threshold:
                    break
                if r["full_name"] not in used_full_names:
                    picked.append(r)
                    used_full_names.add(r["full_name"])

        sec_repos[sec["title"]] = picked

    # 生成 HTML
    sections_html = []
    for sec in sec_defs:
        title = sec.get("title", "")
        icon = sec.get("icon", "📌")
        desc = sec.get("desc", "")

        if sec.get("sort_by") == "dashboard":
            # 数据看板
            top_langs = lang_counter.most_common(6)
            lang_html = " · ".join(
                f'<span class="eco-tag">{l} <small>{c}</small></span>'
                for l, c in top_langs
            )
            sections_html.append(f'<h2><span class="icon">{icon}</span>{title}</h2>')
            sections_html.append(f'<div class="subtitle">{desc}</div>')
            sections_html.append(
                f'<div class="trend-block">'
                f'<p><strong>匹配项目</strong>：{len(matched)} 个</p>'
                f'<p><strong>编程语言</strong>：{lang_html}</p>'
                f'<p><strong>查询话题</strong>：{topic}（关键词：{", ".join(keywords[:5])}）</p>'
                f'</div>'
            )
            continue

        items = sec_repos.get(title, [])
        sections_html.append(f'<h2><span class="icon">{icon}</span>{title}</h2>')
        sections_html.append(f'<div class="subtitle">{desc}</div>')
        if items:
            for i, r in enumerate(items, 1):
                sections_html.append(_card(r, i))
        else:
            sections_html.append(
                '<div class="repo-card"><p style="color:var(--text-dim)">暂无匹配项目</p></div>'
            )

    # 统计补充数量
    total_custom = len(matched)
    total_shown = sum(len(v) for v in sec_repos.values())
    supplemented = max(0, total_shown - total_custom) if total_custom < total_shown else 0

    supplement_note = ""
    if supplemented > 0:
        supplement_note = f'<div class="summary-item"><span class="num">{supplemented}</span><span class="label">基础补充</span></div>'

    return f"""<div class="container">
<h1>🔧 自定义日报 <span class="date">— {topic}</span></h1>
<div class="summary-bar">
    <div class="summary-item"><span class="num">{len(matched)}</span><span class="label">匹配项目</span></div>
    <div class="summary-item"><span class="num">{total_shown}</span><span class="label">展示项目</span></div>
    {supplement_note}
</div>

{"".join(sections_html)}

<footer>📬 自定义报告由 GitHub Trending Daily Bot 生成{('（部分板块由基础日报补充）' if supplemented > 0 else '')}</footer>
</div>"""


def save_custom_report(html: str, topic: str) -> str:
    os.makedirs(REPORTS_DIR, exist_ok=True)
    slug = topic.replace(" ", "-")[:30]
    path = os.path.join(REPORTS_DIR, f"custom-{slug}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path

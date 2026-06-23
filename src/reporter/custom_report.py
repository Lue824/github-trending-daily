"""
自定义日报 HTML 生成器
根据用户查询动态生成板块，含多维度项目解读 + 三级降级补充
"""
import logging
import os
from collections import Counter
from datetime import datetime

from config import REPORTS_DIR

logger = logging.getLogger(__name__)


def _match_repo(repo: dict, keywords: list[str], exclude: list[str],
                language: str = None, min_stars: int = 30) -> bool:
    """检查仓库是否匹配关键词"""
    text = (
        f"{repo.get('name', '')} "
        f"{repo.get('description', '') or ''} "
        f"{' '.join(repo.get('topics', []))}"
    ).lower()

    for ex in exclude:
        if ex.lower() in text:
            return False
    if language and repo.get("language", "").lower() != language.lower():
        return False
    if repo.get("stars", 0) < min_stars:
        return False
    return any(kw.lower() in text for kw in keywords)


def _format_num(n: int) -> str:
    """格式化数字：1234 → 1.2k"""
    if n >= 1000:
        return f"{n/1000:.1f}k"
    return str(n)


def _get_extra(repo: dict) -> dict:
    """安全获取 extra 数据"""
    return repo.get("_extra", {}) or {}


def _gen_dimensions(repo: dict) -> list[dict]:
    """生成多维度解读卡片数据

    5 个维度（与基础日报对齐）：
    - 它是什么：项目定位
    - 谁在用：目标用户
    - 解决什么问题：核心价值
    - 怎么用：上手方式
    - 健康度：维护状态
    """
    extra = _get_extra(repo)
    desc = (repo.get("description", "") or "").strip()
    name = repo.get("full_name", "")
    topics = repo.get("topics", []) or []
    lang = repo.get("language", "Unknown")
    stars = repo.get("stars", 0)
    forks = repo.get("forks", 0)
    issues = extra.get("open_issues", repo.get("issues", 0))
    prs = extra.get("open_prs", 0)
    contribs = extra.get("contributors", 0)
    releases = extra.get("releases", 0)
    last_commit = extra.get("last_commit", "")
    created_days = extra.get("created_days", 0)
    updated_days = extra.get("updated_days", 0)

    # 维度1：它是什么
    what_is = desc if desc else f"{name} 是一个 {lang} 开源项目"
    if len(what_is) > 150:
        what_is = what_is[:147] + "..."

    # 维度2：谁在用（基于 topics 和语言推断）
    audience_hints = {
        "ai": "AI/ML 研究者与工程师",
        "ml": "AI/ML 研究者与工程师",
        "llm": "大模型应用开发者",
        "agent": "AI Agent 开发者",
        "game": "游戏开发者",
        "engine": "游戏/图形开发者",
        "web": "Web 前端开发者",
        "frontend": "前端开发者",
        "backend": "后端开发者",
        "api": "API 开发者",
        "database": "数据库工程师",
        "devops": "DevOps 工程师",
        "security": "安全研究员",
        "blockchain": "Web3 开发者",
        "mobile": "移动端开发者",
        "cli": "命令行工具爱好者",
        "tutorial": "技术学习者",
        "education": "技术学习者",
    }
    audience = "开源技术爱好者"
    topics_str = " ".join(topics).lower() + " " + desc.lower()
    for key, val in audience_hints.items():
        if key in topics_str:
            audience = val
            break

    # 维度3：解决什么问题
    if desc:
        problem = desc
        if len(problem) > 120:
            problem = problem[:117] + "..."
    else:
        problem = f"提供 {lang} 生态下的开源解决方案"

    # 维度4：怎么用
    if "cli" in topics_str or "command-line" in topics_str:
        usage = "命令行安装后直接使用"
    elif "library" in topics_str or "sdk" in topics_str:
        usage = f"作为依赖库引入到 {lang} 项目中"
    elif "api" in topics_str:
        usage = "通过 HTTP API 调用"
    elif "framework" in topics_str:
        usage = f"基于此框架开发 {lang} 应用"
    elif "docker" in topics_str:
        usage = "通过 Docker 容器化部署"
    elif "web" in topics_str or "frontend" in topics_str:
        usage = "克隆仓库后本地运行或部署到 Web 服务器"
    else:
        usage = f"克隆仓库后按 README 文档使用"

    # 维度5：健康度
    health_parts = []
    if updated_days >= 0:
        if updated_days <= 7:
            health_parts.append(f"近期活跃（{updated_days} 天前更新）")
        elif updated_days <= 30:
            health_parts.append(f"维护中（{updated_days} 天前更新）")
        elif updated_days <= 180:
            health_parts.append(f"低频更新（{updated_days} 天前更新）")
        else:
            health_parts.append(f"⚠️ 长期未更新（{updated_days} 天前）")
    if contribs:
        health_parts.append(f"{contribs} 位贡献者")
    if releases:
        health_parts.append(f"{releases} 个版本")
    if prs:
        health_parts.append(f"{prs} 个待处理 PR")
    health = " · ".join(health_parts) if health_parts else "数据待补充"

    return [
        {"icon": "📦", "label": "它是什么", "text": what_is},
        {"icon": "👥", "label": "谁在用", "text": audience},
        {"icon": "💡", "label": "解决什么", "text": problem},
        {"icon": "🚀", "label": "怎么用", "text": usage},
        {"icon": "❤️", "label": "健康度", "text": health},
    ]


def _card(repo: dict, idx: int) -> str:
    """生成项目卡片（含多维度解读 + 来源标注）"""
    stars = repo.get("stars", 0)
    inc = repo.get("stars_in_period", 0) or 0
    lang = repo.get("language", "Unknown")
    desc = (repo.get("description", "") or "")[:200]
    tags = " · ".join(f'<span class="eco-tag">{t}</span>' for t in repo.get("tags", [])[:3])
    extra = _get_extra(repo)
    quality = repo.get("quality_score", 0)
    hot = repo.get("hot_score", 0)
    source_note = repo.get("_source_note", "")

    # 来源标注横幅
    source_banner = ""
    if source_note == "high_value":
        source_banner = (
            '<div class="source-banner source-high-value">'
            '💎 长期价值项目 · 这不是近期热门，而是具有长期价值的高价值项目'
            '</div>'
        )
    elif source_note == "basic_top":
        source_banner = (
            '<div class="source-banner source-basic-top">'
            '📌 基础模块高排名 · 此项目来源于基础模块领域的高排名项目'
            '</div>'
        )

    # 多维度解读
    dims = _gen_dimensions(repo)
    dims_html = "".join(
        f'<div class="dim-item"><span class="dim-icon">{d["icon"]}</span>'
        f'<span class="dim-label">{d["label"]}</span>'
        f'<span class="dim-text">{d["text"]}</span></div>'
        for d in dims
    )

    # 评分徽章
    score_badge = ""
    if quality or hot:
        badge_parts = []
        if quality:
            badge_parts.append('<span class="badge badge-quality">🏆 质量 ' + str(quality) + '</span>')
        if hot:
            badge_parts.append('<span class="badge badge-hot">🔥 热度 ' + str(hot) + '</span>')
        score_badge = '<div class="score-badges">' + "".join(badge_parts) + '</div>'

    # 健康度指标
    health_metrics = []
    if extra.get("contributors"):
        health_metrics.append(f"👥 {extra['contributors']}")
    if extra.get("releases"):
        health_metrics.append(f"🏷 {extra['releases']}")
    if extra.get("open_prs") is not None:
        health_metrics.append(f"🔀 {extra['open_prs']}")
    if extra.get("open_issues") is not None:
        health_metrics.append(f"⚠️ {extra['open_issues']}")
    health_html = (
        f'<div class="health-bar">{" · ".join(health_metrics)}</div>'
        if health_metrics else ""
    )

    return f"""<div class="repo-card custom-card">
{source_banner}
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
{score_badge}
{health_html}
{tags and f'<div class="tag-bar">{tags}</div>'}
<div class="dimensions">
<div class="dim-title">🔍 多维度解读</div>
{dims_html}
</div>
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
    """生成自定义日报 HTML（含多维度解读 + 优化 UI）"""
    keywords = parsed.get("keywords", [])
    exclude = parsed.get("exclude", [])
    language = parsed.get("language")
    min_stars = parsed.get("min_stars", 30)
    topic = parsed.get("topic", query[:20])
    sec_defs = sections.get("sections", [])
    source = parsed.get("source", "rule")

    matched = [r for r in repos if _match_repo(r, keywords, exclude, language, min_stars)]
    lang_counter = Counter(r.get("language", "Unknown") for r in matched)
    basic_pool = sorted(basic_repos or [], key=lambda r: r.get("hot_score", 0), reverse=True)

    # === 三级降级补充池 ===
    # 当今日 Trending 中匹配项目不足时，依次尝试：
    # 1. GitHub Search API 搜索高 Star 长期价值项目
    # 2. 基础模块高排名项目
    high_value_pool = []
    if len(matched) < min_threshold:
        try:
            from src.fetcher.search_api import search_high_value_repos
            logger.info(f"Custom match insufficient ({len(matched)}), searching high-value repos...")
            high_value_pool = search_high_value_repos(keywords, per_page=15)
            for r in high_value_pool:
                r["_source_note"] = "high_value"
            logger.info(f"High-value repos found: {len(high_value_pool)}")
        except Exception as e:
            logger.warning(f"High-value search failed: {e}")

    # 为基础模块补充池标注来源
    for r in basic_pool:
        if not r.get("_source_note"):
            r["_source_note"] = "basic_top"

    sec_repos = {}
    used_full_names = set()
    for sec in sec_defs:
        sort_by = sec.get("sort_by", "hot_score")
        limit = sec.get("limit", 10)
        filter_new = sec.get("filter_new", False)

        items = list(matched)
        if filter_new:
            items = [r for r in items if _get_extra(r).get("created_days", 999) <= 90]

        if sort_by == "dashboard":
            sec_repos[sec["title"]] = []
            continue
        elif sort_by == "quality_score":
            items = sorted(items, key=lambda r: r.get("quality_score", 0), reverse=True)
        elif sort_by == "stars":
            items = sorted(items, key=lambda r: r.get("stars", 0), reverse=True)
        else:
            items = sorted(items, key=lambda r: r.get("hot_score", 0), reverse=True)

        picked = []
        for r in items:
            if len(picked) >= limit:
                break
            picked.append(r)
            used_full_names.add(r["full_name"])

        # 三级降级补充
        if len(picked) < min_threshold:
            # 第一级：高价值长期项目
            for r in high_value_pool:
                if len(picked) >= min_threshold:
                    break
                if r["full_name"] not in used_full_names:
                    picked.append(r)
                    used_full_names.add(r["full_name"])

        # 第二级：基础模块高排名项目
        if len(picked) < min_threshold and basic_pool:
            for r in basic_pool:
                if len(picked) >= min_threshold:
                    break
                if r["full_name"] not in used_full_names:
                    picked.append(r)
                    used_full_names.add(r["full_name"])

        sec_repos[sec["title"]] = picked

    # 生成板块 HTML
    sections_html = []
    for sec in sec_defs:
        title = sec.get("title", "")
        icon = sec.get("icon", "📌")
        desc = sec.get("desc", "")

        if sec.get("sort_by") == "dashboard":
            top_langs = lang_counter.most_common(6)
            lang_html = " · ".join(
                f'<span class="eco-tag">{l} <small>{c}</small></span>'
                for l, c in top_langs
            )
            # 语言分布条形图
            max_count = top_langs[0][1] if top_langs else 1
            lang_bars = "".join(
                f'<div class="lang-bar-item">'
                f'<span class="lang-name">{l}</span>'
                f'<div class="lang-bar-bg"><div class="lang-bar-fill" style="width:{c/max_count*100:.0f}%"></div></div>'
                f'<span class="lang-count">{c}</span>'
                f'</div>'
                for l, c in top_langs
            )

            sections_html.append(f'<section class="report-section">')
            sections_html.append(f'<h2><span class="icon">{icon}</span>{title}</h2>')
            sections_html.append(f'<div class="subtitle">{desc}</div>')
            sections_html.append(
                f'<div class="trend-block dashboard-block">'
                f'<div class="dashboard-grid">'
                f'<div class="dashboard-item"><div class="dash-num">{len(matched)}</div><div class="dash-label">匹配项目</div></div>'
                f'<div class="dashboard-item"><div class="dash-num">{len(lang_counter)}</div><div class="dash-label">编程语言</div></div>'
                f'<div class="dashboard-item"><div class="dash-num">{sum(r.get("stars",0) for r in matched)}</div><div class="dash-label">总 Stars</div></div>'
                f'<div class="dashboard-item"><div class="dash-num">{sum(_get_extra(r).get("contributors",0) for r in matched)}</div><div class="dash-label">总贡献者</div></div>'
                f'</div>'
                f'<div class="lang-distribution"><h3>语言分布</h3>{lang_bars}</div>'
                f'<div class="query-info"><strong>查询话题</strong>：{topic}'
                f'<br><strong>关键词</strong>：{", ".join(keywords[:5])}'
                f'<br><strong>解析来源</strong>：{source}</div>'
                f'</div>'
            )
            sections_html.append('</section>')
            continue

        items = sec_repos.get(title, [])
        sections_html.append(f'<section class="report-section">')
        sections_html.append(f'<h2><span class="icon">{icon}</span>{title}</h2>')
        sections_html.append(f'<div class="subtitle">{desc}</div>')
        if items:
            for i, r in enumerate(items, 1):
                sections_html.append(_card(r, i))
        else:
            sections_html.append(
                '<div class="repo-card"><p style="color:var(--text-dim)">暂无匹配项目</p></div>'
            )
        sections_html.append('</section>')

    total_custom = len(matched)
    total_shown = sum(len(v) for v in sec_repos.values())
    supplemented = max(0, total_shown - total_custom) if total_custom < total_shown else 0
    high_value_count = sum(1 for v in sec_repos.values() for r in v if r.get("_source_note") == "high_value")
    basic_top_count = sum(1 for v in sec_repos.values() for r in v if r.get("_source_note") == "basic_top")

    supplement_note = ""
    if supplemented > 0:
        supplement_parts = [f'<span class="num">{supplemented}</span><span class="label">补充项目</span>']
        if high_value_count:
            supplement_parts.append(f'<span class="num">{high_value_count}</span><span class="label">💎 高价值</span>')
        if basic_top_count:
            supplement_parts.append(f'<span class="num">{basic_top_count}</span><span class="label">📌 基础高排名</span>')
        supplement_note = "".join(f'<div class="summary-item">{p}</div>' for p in supplement_parts)

    # 降级提示横幅
    fallback_banner = ""
    if supplemented > 0:
        banner_parts = []
        if high_value_count:
            banner_parts.append(f"💎 {high_value_count} 个长期价值高 Star 项目（非近期热门）")
        if basic_top_count:
            banner_parts.append(f"📌 {basic_top_count} 个基础模块高排名项目")
        fallback_banner = (
            f'<div class="fallback-banner">'
            f'ℹ️ 今日 Trending 中匹配项目不足，已为你补充：{" · ".join(banner_parts)}'
            f'</div>'
        )

    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    return f"""<div class="container custom-container">
<div class="report-header">
<h1>🔧 自定义日报 <span class="date">— {topic}</span></h1>
<div class="report-meta">生成时间 {now} · 解析来源 {source}</div>
</div>
{fallback_banner}
<div class="summary-bar">
<div class="summary-item"><span class="num">{len(matched)}</span><span class="label">匹配项目</span></div>
<div class="summary-item"><span class="num">{total_shown}</span><span class="label">展示项目</span></div>
<div class="summary-item"><span class="num">{len(sec_defs)}</span><span class="label">板块数</span></div>
{supplement_note}
</div>

{"".join(sections_html)}

<footer>📬 自定义报告由 GitHub Trending Daily Bot 生成{('（含补充项目）' if supplemented > 0 else '')}</footer>
</div>"""


def save_custom_report(html: str, topic: str) -> str:
    os.makedirs(REPORTS_DIR, exist_ok=True)
    slug = topic.replace(" ", "-")[:30]
    path = os.path.join(REPORTS_DIR, f"custom-{slug}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path

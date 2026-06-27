"""
自定义日报 HTML 生成器
根据用户查询动态生成板块，含多维度项目解读 + 三级搜索流程

三级搜索流程：
1. 先搜索基础模块数据库（今日 Trending repos）
2. 若无匹配 → 直接搜索 GitHub 全库，按基础模块相同方法排序
3. 若 GitHub 也无结果 → 使用基础模块高排名项目作为替代，并明确告知用户
"""
import logging
import os
import re
from collections import Counter
from datetime import datetime

from config import REPORTS_DIR
from src.processor.describe_cn import generate_dimensions
from src.processor.categorize import classify_repos, compute_hot_score
from src.processor.scoring import compute_all_scores
from src.utils.html_safe import esc, safe_href, safe_text_br, safe_url_path

logger = logging.getLogger(__name__)


def _compute_scores_for_github_repos(repos: list[dict]) -> list[dict]:
    """为 GitHub 搜索结果计算与基础模块一致的评分

    使 GitHub 搜索结果可以使用相同的排序逻辑（hot_score, quality_score 等）。
    不调用 fetch_extra_batch（太慢），仅用基础字段计算，quality 等评分为基础值。
    """
    if not repos:
        return repos

    # 1. 补充 sources 字段（compute_hot_score 依赖它计算多源加分）
    for r in repos:
        if not r.get("sources"):
            r["sources"] = ["api/github-search"]

    # 2. 分类打标签（与基础模块一致）
    repos = classify_repos(repos)

    # 3. 计算 hot_score（与基础模块一致）
    for r in repos:
        r["hot_score"] = compute_hot_score(r)

    # 4. 计算多维评分（无 extra 数据时使用默认值）
    extra_cache = {r["full_name"]: {} for r in repos}
    repos = compute_all_scores(repos, extra_cache)

    # 5. 挂载 _extra 字段（与基础模块格式对齐）
    for r in repos:
        r["_extra"] = extra_cache.get(r["full_name"], {})

    return repos


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
    # 短关键词（≤3字符且纯字母）用词边界匹配，避免 "dsp" 匹配 "handsfree"
    for kw in keywords:
        kw_lower = kw.lower()
        if len(kw_lower) <= 3 and kw_lower.isalpha():
            if re.search(r'\b' + re.escape(kw_lower) + r'\b', text):
                return True
        else:
            if kw_lower in text:
                return True
    return False


def _get_extra(repo: dict) -> dict:
    """安全获取 extra 数据"""
    return repo.get("_extra", {}) or {}


def _gen_cn_intro(repo: dict) -> str:
    """调用 LLM 生成中文介绍（与基础模块一致）"""
    try:
        from src.processor.describe_cn import generate_cn_detail, generate_cn_intro_with_readme
        # 优先用 LLM 生成
        readme = repo.get("_readme", "")
        if readme:
            return generate_cn_intro_with_readme(repo, readme)
        return generate_cn_detail(repo)
    except Exception as e:
        logger.warning(f"CN intro generation failed: {e}")
        return (repo.get("description", "") or "")[:200]


def _gen_dimensions(repo: dict, cn_intro: str = "",
                     api_key: str = "", provider: str = "") -> list[dict]:
    """生成多维度解读卡片数据 — 复用 describe_cn.generate_dimensions

    api_key 非空时用用户自己的 key 调用 LLM 生成深度解读
    """
    return generate_dimensions(repo, readme=repo.get("_readme", ""), llm_text="",
                                api_key=api_key, provider=provider)


def _card(repo: dict, idx: int, api_key: str = "", provider: str = "") -> str:
    """生成项目卡片（与基础模块风格统一 + 多维度解读 + 来源标注）"""
    stars = repo.get("stars", 0)
    inc = repo.get("stars_in_period", 0) or 0
    forks = repo.get("forks", 0)
    lang = repo.get("language", "Unknown")
    extra = _get_extra(repo)
    quality = repo.get("quality_score", 0)
    hot = repo.get("hot_score", 0)
    burst = repo.get("burst_score", 0)
    ai_score = repo.get("ai_radar_score", 0)
    source_note = repo.get("_source_note", "")

    # 来源标注改为行内胶囊
    source_tag = ""
    if source_note == "github_search":
        source_tag = '<span class="tag-capsule tag-github-search">🔍 GitHub 搜索</span>'
    elif source_note == "substitute":
        source_tag = '<span class="tag-capsule tag-substitute">⚠️ 基础模块替代</span>'
    elif source_note == "high_value":
        source_tag = '<span class="tag-capsule tag-longterm">💎 高星高价值（非当前热门）</span>'
    elif source_note == "basic_top":
        source_tag = '<span class="tag-capsule tag-focus">📌 基础高排名</span>'

    # 调用 LLM 生成中文介绍（与基础模块一致）
    cn_intro = _gen_cn_intro(repo)

    # 多维度解读
    dims = _gen_dimensions(repo, cn_intro, api_key=api_key, provider=provider)
    dims_html = "".join(
        f'<div class="dim-item"><span class="dim-icon">{d["icon"]}</span>'
        f'<span class="dim-label">{d["label"]}</span>'
        f'<span class="dim-text">{d["text"]}</span></div>'
        for d in dims
    )

    # 统一评分徽章（与基础模块一致）
    scores = []
    if burst and burst > 0:
        scores.append('🧨 爆发 ' + format(burst, '.2f'))
    if quality and quality > 0.4:
        scores.append('🏆 质量 ' + format(quality, '.2f'))
    if ai_score and ai_score > 0:
        scores.append('🤖 AI ' + format(ai_score, '.2f'))
    scores_html = '<div class="repo-scores">' + "".join(
        f'<span class="score-badge {"score-burst" if "爆发" in s else "score-quality" if "质量" in s else "score-ai"}">{s}</span>'
        for s in scores
    ) + '</div>' if scores else ""

    # 统一活跃度标识（无 extra 数据时不显示）
    last_push = extra.get("last_push_days")
    if last_push is None:
        status_html = ''
    elif last_push <= 7:
        status_html = '<span class="status-indicator status-active"><span class="dot"></span>高活跃</span>'
    elif last_push <= 30:
        status_html = '<span class="status-indicator status-moderate"><span class="dot"></span>中等活跃</span>'
    elif last_push <= 180:
        status_html = '<span class="status-indicator status-inactive"><span class="dot"></span>低活跃</span>'
    else:
        status_html = '<span class="status-indicator status-archived"><span class="dot"></span>长期静态</span>'

    # 统一标签为胶囊样式
    tags = repo.get("tags", []) or []
    tags_html = (
        '<div class="repo-tags">' + "".join(
            f'<span class="tag-capsule tag-focus">{esc(t)}</span>' for t in tags[:4]
        ) + '</div>'
        if tags else ""
    )

    # 描述：优先用 LLM 中文介绍（转义后保留换行）
    desc_html = safe_text_br(cn_intro) if cn_intro else esc(repo.get("description") or "")

    # 安全的 URL 和项目名
    safe_url = safe_href(repo.get("url"))
    safe_name = esc(repo.get("full_name") or "")

    # 统一指标行布局，指标行末尾放状态标识
    stats_html = f'''<div class="metric-row">
<span class="metric-item">⭐ {format(stars, ',')}</span>
{"<span class='metric-item'>📈 +" + format(inc, ',') + "</span>" if inc else ""}
<span class="metric-item">🍴 {format(forks, ',')}</span>
<span class="metric-item">💻 {esc(lang)}</span>
<span class="status-indicator-wrap" style="margin-left:auto">{status_html}</span>
</div>'''

    # 健康度进度条
    updated_days = extra.get("updated_days", -1)
    if updated_days >= 0:
        if updated_days <= 7:
            progress_class = "active"
            progress_pct = 90
            progress_label = f"持续维护（{updated_days}天前更新）"
        elif updated_days <= 30:
            progress_class = "active"
            progress_pct = 70
            progress_label = f"维护中（{updated_days}天前更新）"
        elif updated_days <= 180:
            progress_class = "moderate"
            progress_pct = 40
            progress_label = f"低频更新（{updated_days}天前更新）"
        else:
            progress_class = "inactive"
            progress_pct = 15
            progress_label = f"长期未更新（{updated_days}天前）"
        health_progress_html = f'''<div class="health-progress">
<div class="health-progress-label">{progress_label}</div>
<div class="health-progress-bar"><div class="health-progress-fill {progress_class}" style="width:{progress_pct}%"></div></div>
</div>'''
    else:
        health_progress_html = ""

    return f'''<div class="repo-card custom-card">
<div class="repo-header">
<span class="repo-rank">#{idx}</span>
<a href="{safe_url}" target="_blank" class="repo-name">{safe_name}</a>
{source_tag}
</div>
<div class="repo-desc">{desc_html}</div>
{stats_html}
{scores_html}
{tags_html}
{health_progress_html}
<div class="dimensions">
<div class="dim-title">🔍 多维度解读</div>
{dims_html}
</div>
</div>'''


def generate_custom_report(
    repos: list[dict],
    query: str,
    parsed: dict,
    sections: dict,
    readme_cache: dict = None,
    basic_repos: list[dict] = None,
    min_threshold: int = 5,
    api_key: str = "",
    provider: str = "",
) -> str:
    """生成自定义日报 HTML（含多维度解读 + 三级搜索流程）

    三级搜索流程：
    1. 先搜索基础模块数据库（今日 Trending repos）
    2. 若无匹配 → 直接搜索 GitHub 全库，按基础模块相同方法排序
    3. 若 GitHub 也无结果 → 使用基础模块高排名项目作为替代，并明确告知用户

    api_key/provider 非空时，项目深度分析用用户自己的 LLM key
    """
    keywords = parsed.get("keywords", [])
    exclude = parsed.get("exclude", [])
    language = parsed.get("language")
    min_stars = parsed.get("min_stars", 30)
    topic = parsed.get("topic", query[:20])
    sec_defs = sections.get("sections", [])
    source = parsed.get("source", "rule")

    # === Step 1: 搜索基础模块数据库 ===
    matched = [r for r in repos if _match_repo(r, keywords, exclude, language, min_stars)]
    for r in matched:
        if not r.get("_source_note"):
            r["_source_note"] = "foundation_db"

    lang_counter = Counter(r.get("language", "Unknown") for r in matched)
    basic_pool = sorted(basic_repos or [], key=lambda r: r.get("hot_score", 0), reverse=True)

    # 计算所有板块的总需求（dashboard 板块不展示项目，不计入）
    total_demand = sum(s.get("limit", 10) for s in sec_defs if s.get("sort_by") != "dashboard")

    using_github_as_primary = False
    using_substitutes = False

    # === Step 2: 若基础模块无匹配 → 直接搜索 GitHub ===
    if not matched:
        try:
            from src.fetcher.search_api import search_high_value_repos
            logger.info(f"Foundation DB has no matches for '{query}', searching GitHub directly...")
            github_results = search_high_value_repos(keywords, per_page=30)
            if github_results:
                github_results = _compute_scores_for_github_repos(github_results)
                for r in github_results:
                    r["_source_note"] = "github_search"
                matched = github_results
                using_github_as_primary = True
                lang_counter = Counter(r.get("language", "Unknown") for r in matched)
                logger.info(f"GitHub search found {len(matched)} repos for '{query}'")
        except Exception as e:
            logger.warning(f"GitHub direct search failed: {e}")

    # === Step 3: 若 GitHub 也无结果 → 使用基础模块替代项目 ===
    if not matched:
        substitutes = sorted(basic_repos or [], key=lambda r: r.get("hot_score", 0), reverse=True)[:10]
        for r in substitutes:
            r["_source_note"] = "substitute"
        matched = substitutes
        using_substitutes = True
        lang_counter = Counter(r.get("language", "Unknown") for r in matched)
        logger.info(f"No GitHub results, using {len(matched)} foundation substitutes for '{query}'")

    # === 补充池：基础模块有部分匹配但不足以填满板块时 ===
    high_value_pool = []
    if matched and not using_github_as_primary and not using_substitutes and len(matched) < total_demand:
        try:
            from src.fetcher.search_api import search_high_value_repos
            logger.info(f"Partial match ({len(matched)}/{total_demand} needed), supplementing with high-value repos...")
            high_value_pool = search_high_value_repos(keywords, per_page=30)
            for r in high_value_pool:
                r["_source_note"] = "high_value"
            logger.info(f"High-value repos found: {len(high_value_pool)}")
        except Exception as e:
            logger.warning(f"High-value search failed: {e}")

    # 基础模块池仅在 高价值搜索失败 时作为最后兜底（与话题无关，不优先使用）
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

        # 补充：仅当基础模块有部分匹配时（非 GitHub 为主、非替代项目）
        if not using_github_as_primary and not using_substitutes:
            # 第一级补充：高价值长期项目
            if len(picked) < limit and high_value_pool:
                for r in high_value_pool:
                    if len(picked) >= limit:
                        break
                    if r["full_name"] not in used_full_names:
                        picked.append(r)
                        used_full_names.add(r["full_name"])

            # 第二级补充：基础模块高排名项目（仅当高价值池为空时）
            if len(picked) < min_threshold and not high_value_pool and basic_pool and matched:
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
            max_count = top_langs[0][1] if top_langs else 1
            lang_bars = "".join(
                f'<div class="lang-bar-item">'
                f'<span class="lang-name">{esc(l)}</span>'
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
                f'<div class="query-info"><strong>查询话题</strong>：{esc(topic)}'
                f'<br><strong>关键词</strong>：{esc(", ".join(keywords[:5]))}'
                f'<br><strong>解析来源</strong>：{esc(source)}</div>'
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
                sections_html.append(_card(r, i, api_key=api_key, provider=provider))
        else:
            sections_html.append(
                '<div class="empty-state">📋 暂无匹配项目</div>'
            )
        sections_html.append('</section>')

    total_custom = len(matched)
    total_shown = sum(len(v) for v in sec_repos.values())
    supplemented = max(0, total_shown - total_custom) if total_custom < total_shown else 0
    high_value_count = sum(1 for v in sec_repos.values() for r in v if r.get("_source_note") == "high_value")
    basic_top_count = sum(1 for v in sec_repos.values() for r in v if r.get("_source_note") == "basic_top")
    github_search_count = sum(1 for v in sec_repos.values() for r in v if r.get("_source_note") == "github_search")
    substitute_count = sum(1 for v in sec_repos.values() for r in v if r.get("_source_note") == "substitute")

    # 摘要栏统计
    summary_parts = [
        f'<div class="summary-item"><span class="num">{len(matched)}</span><span class="label">匹配项目</span></div>',
        f'<div class="summary-item"><span class="num">{total_shown}</span><span class="label">展示项目</span></div>',
        f'<div class="summary-item"><span class="num">{len(sec_defs)}</span><span class="label">板块数</span></div>',
    ]
    if supplemented > 0:
        summary_parts.append(f'<div class="summary-item"><span class="num">{supplemented}</span><span class="label">补充项目</span></div>')
        if high_value_count:
            summary_parts.append(f'<div class="summary-item"><span class="num">{high_value_count}</span><span class="label">💎 高价值</span></div>')
        if basic_top_count:
            summary_parts.append(f'<div class="summary-item"><span class="num">{basic_top_count}</span><span class="label">📌 基础高排名</span></div>')
    if using_github_as_primary:
        summary_parts.append(f'<div class="summary-item"><span class="num">{github_search_count}</span><span class="label">🔍 GitHub 搜索</span></div>')
    if using_substitutes:
        summary_parts.append(f'<div class="summary-item"><span class="num">{substitute_count}</span><span class="label">⚠️ 替代项目</span></div>')
    summary_note = "".join(summary_parts)

    # 来源提示横幅
    source_banner = ""
    if using_substitutes:
        source_banner = (
            f'<div class="fallback-banner" style="background:#fff3cd;border-color:#ffc107;color:#856404;">'
            f'⚠️ 未在今日 Trending 和 GitHub 搜索中找到与「{esc(topic)}」直接匹配的项目。'
            f'以下为基础模块高排名替代项目，仅供参考。'
            f'</div>'
        )
    elif using_github_as_primary:
        source_banner = (
            f'<div class="fallback-banner" style="background:#d1ecf1;border-color:#17a2b8;color:#0c5460;">'
            f'🔍 今日 Trending 中无匹配项目，以下来自 GitHub 全库搜索（已按基础模块相同方法排序）。'
            f'</div>'
        )
    elif supplemented > 0:
        banner_parts = []
        if high_value_count:
            banner_parts.append(f"💎 {high_value_count} 个高星高价值项目（来自 GitHub 全库搜索，非当前 Trending 热门）")
        if basic_top_count:
            banner_parts.append(f"📌 {basic_top_count} 个基础模块高排名项目")
        source_banner = (
            f'<div class="fallback-banner">'
            f'ℹ️ 今日 Trending 中匹配项目不足，已为你补充：{" · ".join(banner_parts)}'
            f'</div>'
        )

    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    footer_note = ""
    if using_substitutes:
        footer_note = "（基础模块替代项目）"
    elif using_github_as_primary:
        footer_note = "（GitHub 搜索结果）"
    elif supplemented > 0:
        footer_note = "（含补充项目）"

    return f"""<div class="container custom-container">
<div class="report-header">
<h1>🔧 自定义日报 <span class="date">— {esc(topic)}</span></h1>
<div class="report-meta">生成时间 {now} · 解析来源 {esc(source)}</div>
</div>
{source_banner}
<div class="summary-bar">
{summary_note}
</div>

{"".join(sections_html)}

<footer>📬 自定义报告由 GitHub Trending Daily Bot 生成{footer_note}</footer>
</div>"""


def save_custom_report(html: str, topic: str) -> str:
    os.makedirs(REPORTS_DIR, exist_ok=True)
    # 严格清洗 slug，防止路径遍历
    slug = safe_url_path(topic)
    path = os.path.join(REPORTS_DIR, f"custom-{slug}.html")
    # 校验最终路径在 REPORTS_DIR 内
    if not os.path.abspath(path).startswith(os.path.abspath(REPORTS_DIR)):
        raise ValueError("Invalid path: path traversal detected")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path

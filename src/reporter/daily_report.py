"""
6板块日报生成器 — CSS 类名版（与自定义模块统一风格）

板块：
① 正在爆发 — 增长加速度最大
② 质量标杆 — 健康度极高 + 社区活跃
③ 潜力新星 — 创建<90天 + 势头好
④ 热度陷阱 — 星多但 issue 堆积/停更
⑤ AI/ML雷达 — AI领域综合评分
⑥ 数据看板 — 统计摘要
"""
import os
from collections import Counter
from datetime import datetime

from config import REPORTS_DIR
from src.processor.describe_cn import generate_dimensions, generate_cn_description
from src.reporter._shared import rank_badge, section_anchor_id
from src.utils.html_safe import esc, safe_href, safe_text_br


def _repo_card(repo: dict, idx: int, section: str, yesterday_ranks: dict,
               readme_cache: dict, llm_analyses: dict) -> str:
    """单个项目卡片 — 与自定义模块风格统一"""
    from src.processor.describe_cn import generate_cn_intro_with_readme, generate_cn_detail

    stars = repo.get("stars", 0)
    inc = repo.get("stars_in_period", 0) or 0
    forks = repo.get("forks", 0)
    lang = repo.get("language", "Unknown")
    extra = repo.get("_extra", {}) or {}
    badge_text = rank_badge(repo, section, idx, yesterday_ranks)
    is_trap = repo.get("is_trap", False)
    trap_signals = repo.get("trap_signals", 0)

    # 项目类型背景色
    card_type_class = ""
    if section == "正在爆发":
        card_type_class = "card-burst"
    elif section == "质量标杆":
        card_type_class = "card-longterm"

    # 陷阱/排名徽章
    trap_html = ""
    if is_trap:
        trap_html = f'<span class="tag-capsule tag-trap">⚠️ 陷阱×{trap_signals}</span>'

    badge_html = f'<span class="tag-capsule tag-new">{esc(badge_text)}</span>'

    # 排名锚点
    anchor = section_anchor_id(section, idx)

    # 多维度解读（与自定义模块统一）
    full_name = repo.get("full_name", "")
    llm = llm_analyses.get(full_name, "")
    readme = readme_cache.get(full_name, "")
    dims = generate_dimensions(repo, readme=readme, llm_text=llm)
    dims_html = "".join(
        f'<div class="dim-item"><span class="dim-icon">{d["icon"]}</span>'
        f'<span class="dim-label">{d["label"]}</span>'
        f'<span class="dim-text">{d["text"]}</span></div>'
        for d in dims
    )
    dimensions_html = ""
    if dims:
        dimensions_html = (
            '<div class="dimensions">'
            '<div class="dim-title">🔍 多维度解读</div>'
            f'{dims_html}'
            '</div>'
        )

    # 描述：有 LLM 分析或多维度解读时只显示简短一句话，否则显示完整分析
    if llm or dims:
        desc_html = esc(generate_cn_description(repo))
    else:
        if readme:
            desc_html = generate_cn_intro_with_readme(repo, readme)
        else:
            desc_html = generate_cn_detail(repo)

    # 统一指标行（与自定义模块一致）
    stat_parts = [f'<span class="metric-item">⭐ {stars:,}</span>']
    if inc:
        stat_parts.append(f'<span class="metric-item">📈 +{inc:,}</span>')
    stat_parts.append(f'<span class="metric-item">🍴 {forks:,}</span>')
    stat_parts.append(f'<span class="metric-item">💻 {esc(lang)}</span>')

    # 健康度补充
    if extra:
        health = []
        if extra.get("contributors"):
            health.append(f'<span class="metric-item">👥 {extra["contributors"]}</span>')
        if extra.get("open_issues"):
            health.append(f'<span class="metric-item">🐛 {extra["open_issues"]} issues</span>')
        if health:
            stat_parts.extend(health)

    # 统一活跃度标识（与自定义模块一致，无 extra 数据时不显示）
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

    stats_html = (
        f'<div class="metric-row">{"".join(stat_parts)}'
        f'<span class="status-indicator-wrap" style="margin-left:auto">{status_html}</span></div>'
    )

    # 统一评分徽章（与自定义模块一致）
    scores = []
    for icon, key, threshold, css_class in [
        ("🧨", "burst_score", 0, "score-burst"),
        ("🏆", "quality_score", 0.4, "score-quality"),
        ("🤖", "ai_radar_score", 0, "score-ai"),
    ]:
        val = repo.get(key, 0)
        if val > threshold:
            scores.append(f'<span class="score-badge {css_class}">{icon} {val:.2f}</span>')
    scores_html = f'<div class="repo-scores">{"".join(scores)}</div>' if scores else ""

    # 统一标签胶囊（与自定义模块一致）
    tags_list = repo.get("tags", [])
    tags_html = ""
    if tags_list:
        tags_html = (
            '<div class="repo-tags">'
            + "".join(f'<span class="tag-capsule tag-focus">{esc(t)}</span>' for t in tags_list[:4])
            + '</div>'
        )

    # 健康度进度条（与自定义模块一致）
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
        health_progress_html = (
            f'<div class="health-progress">'
            f'<div class="health-progress-label">{progress_label}</div>'
            f'<div class="health-progress-bar"><div class="health-progress-fill {progress_class}" style="width:{progress_pct}%"></div></div>'
            f'</div>'
        )
    else:
        health_progress_html = ""

    # 陷阱详情
    trap_detail = ""
    if is_trap:
        signals = []
        if extra.get("open_issues", 0) > 10:
            signals.append(f'🐛 开放 Issues: {extra["open_issues"]}')
        if extra.get("last_push_days", 0) > 180:
            signals.append(f'⏸ 最后推送: {extra["last_push_days"]}天前')
        if extra.get("releases", 0) == 0:
            signals.append('📦 无 Release')
        if extra.get("contributors", 0) <= 1:
            signals.append('👤 单人维护')
        if signals:
            trap_detail = f'<div style="margin-top:-4px;margin-bottom:8px;margin-left:12px;font-size:0.78em;color:var(--accent-orange)">{" · ".join(signals)}</div>'

    safe_url = safe_href(repo.get("url", ""))
    safe_name = esc(repo.get("full_name", ""))

    return f'''<div id="{anchor}" class="repo-card custom-card {card_type_class}">
<div class="repo-header">
<span class="repo-rank">#{idx}</span>
<a href="{safe_url}" target="_blank" class="repo-name">{safe_name}</a>
{trap_html} {badge_html}
</div>
<div class="repo-desc">{desc_html}</div>
{dimensions_html}
{stats_html}
{scores_html}
{tags_html}
{health_progress_html}
{trap_detail}
</div>'''


def generate_6section_report(
    repos: list[dict],
    date_str: str,
    readme_cache: dict = None,
    llm_analyses: dict = None,
    trend_analysis: str = "",
    yesterday_ranks: dict = None,
    yesterday_date: str = "",
) -> str:
    """生成6板块日报 HTML — CSS 类名版（与自定义模块统一风格）"""
    readme_cache = readme_cache or {}
    llm_analyses = llm_analyses or {}
    yesterday_ranks = yesterday_ranks or {}
    now = datetime.strptime(date_str, "%Y-%m-%d")
    date_display = now.strftime("%Y年%m月%d日")

    # ── 板块分组 ──
    burst = sorted(
        [r for r in repos if r.get("burst_score", 0) > 0],
        key=lambda r: r["burst_score"], reverse=True
    )[:10]
    quality = sorted(
        [r for r in repos if r.get("quality_score", 0) >= 0.3],
        key=lambda r: r["quality_score"], reverse=True
    )[:10]
    potential = sorted(
        [r for r in repos if r.get("potential_score", 0) > 0],
        key=lambda r: r["potential_score"], reverse=True
    )[:10]
    traps = sorted(
        [r for r in repos if r.get("is_trap")],
        key=lambda r: r.get("hot_score", 0), reverse=True
    )[:5]
    ai_radar = sorted(
        [r for r in repos if r.get("ai_radar_score", 0) > 0],
        key=lambda r: r["ai_radar_score"], reverse=True
    )[:15]

    lang_counter = Counter(r.get("language", "Unknown") for r in repos)
    top_langs = lang_counter.most_common(8)
    max_lang = max(c for _, c in top_langs) if top_langs else 1

    total = len(repos)
    focus_cnt = sum(1 for r in repos if r.get("is_focus"))
    streak_cnt = sum(1 for r in repos if r.get("streak_days", 0) >= 2)
    streaks = sorted(
        [r for r in repos if r.get("streak_days", 0) >= 2],
        key=lambda r: r["streak_days"], reverse=True
    )[:10]

    # ── 头部 ──
    header = f'''<div class="custom-container">
<div class="report-header">
<h1>🚀 GitHub 每日热点 <span class="date">— {date_display}</span></h1>
<div class="report-meta">📊 6板块多维评价 · {now.strftime("%Y-%m-%d %H:%M")} UTC</div>
</div>

<div class="summary-bar">
<div class="summary-item"><span class="num">{total}</span><span class="label">📦 收录项目</span></div>
<div class="summary-item"><span class="num">{focus_cnt}</span><span class="label">🤖 AI项目</span></div>
<div class="summary-item"><span class="num">{len(burst)}</span><span class="label">🧨 爆发项目</span></div>
<div class="summary-item"><span class="num">{len(traps)}</span><span class="label">⚠️ 陷阱项目</span></div>
<div class="summary-item"><span class="num">{streak_cnt}</span><span class="label">🔥 连续在榜</span></div>
</div>
'''

    sections = [
        ("🧨", "正在爆发", "增长加速度最大的项目（日增量≥100）", burst, "今日暂无爆发项目"),
        ("🏆", "质量标杆", "健康度极高 + 社区活跃的高质量项目", quality, "今日暂缺高质量标杆项目"),
        ("🌱", "潜力新星", "创建不超过90天、势头良好的新兴项目", potential, "今日暂无新星项目入榜"),
        ("⚠️", "热度陷阱", "热度高但存在 issues 堆积/停更/单人维护等隐患", traps, "今日未检测到热度陷阱"),
        ("🤖", "AI / ML 雷达", "AI领域综合评分最高的项目", ai_radar, "今日暂无AI项目入榜"),
    ]

    sections_html = []
    for icon, title, sub, repos_list, empty_text in sections:
        is_trap_section = (title == "热度陷阱")
        sections_html.append(
            f'<section class="report-section">'
            f'<h2><span class="icon">{icon}</span>{esc(title)}</h2>'
            f'<div class="subtitle">{esc(sub)}</div>'
        )
        if repos_list:
            for i, r in enumerate(repos_list, 1):
                card = _repo_card(r, i, title.lower().replace(" ", "_") if not is_trap_section else "trap",
                                  yesterday_ranks, readme_cache, llm_analyses)
                sections_html.append(card)
        else:
            sections_html.append(f'<div class="empty-state">📋 {esc(empty_text)}</div>')
        sections_html.append('</section>')

    # ── 数据看板 ──
    dashboard_parts = [
        f'<section class="report-section">',
        f'<h2><span class="icon">📊</span>今日数据看板</h2>',
    ]

    # 语言分布条形图（与自定义模块一致）
    if top_langs:
        lang_bars = "".join(
            f'<div class="lang-bar-item">'
            f'<span class="lang-name">{esc(l)}</span>'
            f'<div class="lang-bar-bg"><div class="lang-bar-fill" style="width:{c/max_lang*100:.0f}%"></div></div>'
            f'<span class="lang-count">{c}</span>'
            f'</div>'
            for l, c in top_langs
        )
        dashboard_parts.append(f'<div class="lang-distribution"><h3>编程语言分布</h3>{lang_bars}</div>')

    # 连续在榜表格
    if streaks:
        streak_rows = ""
        for r in streaks:
            t = "、".join(r.get("tags", [])[:2]) or "-"
            streak_rows += (
                f'<tr style="border-bottom:1px solid var(--border)">'
                f'<td style="padding:6px 10px"><a href="{safe_href(r.get("url", ""))}" target="_blank" style="color:var(--accent);text-decoration:none">{esc(r.get("full_name", ""))}</a></td>'
                f'<td style="padding:6px 10px">{r.get("streak_days", 0)}天</td>'
                f'<td style="padding:6px 10px">{r.get("stars", 0):,}</td>'
                f'<td style="padding:6px 10px">{esc(t)}</td></tr>'
            )
        dashboard_parts.append(
            f'<div style="margin-top:16px;padding-top:16px;border-top:1px dashed var(--border)">'
            f'<h3 style="font-size:0.95em;color:var(--text);margin-bottom:12px">连续在榜项目</h3>'
            f'<table style="width:100%;border-collapse:collapse;font-size:0.82em">'
            f'<tr style="border-bottom:2px solid var(--border);color:var(--text-dim)">'
            f'<th style="text-align:left;padding:6px 10px">项目</th>'
            f'<th style="text-align:left;padding:6px 10px">连续</th>'
            f'<th style="text-align:left;padding:6px 10px">⭐</th>'
            f'<th style="text-align:left;padding:6px 10px">领域</th></tr>'
            f'{streak_rows}</table></div>'
        )

    # 趋势分析
    if trend_analysis:
        dashboard_parts.append(
            f'<div class="trend-block" style="margin-top:16px;padding:16px;background:var(--bg);border:1px solid var(--border);border-radius:8px;line-height:1.6">'
            f'<h3 style="font-size:0.95em;color:var(--text-dim);margin-bottom:8px">趋势分析</h3>'
            f'{safe_text_br(trend_analysis)}</div>'
        )

    dashboard_parts.append('</section>')

    footer = f'''<footer>📬 本报告由 GitHub Trending Daily Bot 自动生成 — {now.strftime("%Y-%m-%d %H:%M")} UTC</footer>
</div>'''

    return header + "".join(sections_html) + "".join(dashboard_parts) + footer


def save_6section_report(html_content: str, date_str: str) -> str:
    """保存6板块日报到文件"""
    os.makedirs(REPORTS_DIR, exist_ok=True)
    filename = f"daily-6s-{date_str}.html"
    filepath = os.path.join(REPORTS_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html_content)
    return filepath

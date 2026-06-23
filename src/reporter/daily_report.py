"""
6板块日报生成器

板块：
① 正在爆发 — 增长加速度最大
② 质量标杆 — 健康度极高 + 社区活跃
③ 潜力新星 — 创建<90天 + 势头好
④ 热度陷阱 — 星多但 issue 堆积/停更
⑤ AI/ML雷达 — AI领域综合评分
⑥ 数据看板 — 统计摘要
"""
import json
import os
from collections import Counter
from datetime import datetime

from config import REPORTS_DIR
from src.reporter._shared import rank_badge, tags_cn, section_anchor_id


def _repo_card(repo: dict, idx: int, section: str, yesterday_ranks: dict,
               readme_cache: dict, llm_analyses: dict, is_dup: bool = False,
               yesterday_rank: int = 0, yesterday_date: str = "") -> str:
    """生成单个项目卡片 HTML"""
    from src.processor.describe_cn import generate_cn_intro_with_readme, generate_cn_detail

    anchor = section_anchor_id(section, idx)
    stars = repo.get("stars", 0)
    inc = repo.get("stars_in_period", 0) or 0
    forks = repo.get("forks", 0)
    lang = repo.get("language", "Unknown")
    tags = tags_cn(repo)
    extra = repo.get("_extra", {}) or {}

    badge_text = rank_badge(repo, section, idx, yesterday_ranks)

    lines = [f'<div class="repo-card" id="{anchor}">']

    # 标题行
    trap_badge = ""
    if repo.get("is_trap"):
        trap_signals = repo.get("trap_signals", 0)
        trap_badge = (
            f' <span class="badge badge-warning" title="{trap_signals}个陷阱信号">'
            f'⚠️ 陷阱信号×{trap_signals}</span>'
        )
    lines.append(
        f'<div class="repo-header">'
        f'<span class="repo-rank">#{idx}</span>'
        f'<a href="{repo["url"]}" target="_blank" class="repo-name">'
        f'{repo["full_name"]}</a>'
        f'{trap_badge}'
        f' <span class="badge badge-info">{badge_text}</span>'
        f'</div>'
    )

    # 描述
    llm = llm_analyses.get(repo["full_name"], "")
    if llm:
        desc = llm.replace("\n", "<br>")
    else:
        readme = readme_cache.get(repo["full_name"], "")
        if readme:
            desc = generate_cn_intro_with_readme(repo, readme)
        else:
            desc = generate_cn_detail(repo)

    lines.append(f'<div class="repo-desc">{desc}</div>')

    # 数据行
    lines.append('<div class="repo-stats">')
    lines.append(f'<span>⭐ {stars:,}</span>')
    if inc:
        lines.append(f'<span>📈 +{inc:,}</span>')
    lines.append(f'<span>🍴 {forks:,}</span>')
    lines.append(f'<span>🗣 {lang}</span>')

    # 额外健康度指标
    if extra:
        health_items = []
        if extra.get("contributors"):
            health_items.append(f'👥 {extra["contributors"]}')
        if extra.get("open_issues"):
            health_items.append(f'🐛 {extra["open_issues"]} issues')
        if extra.get("last_push_days", 999) <= 7:
            health_items.append('🟢 活跃')
        elif extra.get("last_push_days", 999) <= 90:
            health_items.append('🟡 较活跃')
        if health_items:
            lines.append('<span class="health-meta">' + " · ".join(health_items) + '</span>')

    lines.append('</div>')

    # 评分标签
    scores = []
    if repo.get("burst_score", 0) > 0:
        scores.append(f'🧨 爆发 {repo["burst_score"]:.2f}')
    if repo.get("quality_score", 0) > 0.4:
        scores.append(f'🏆 质量 {repo["quality_score"]:.2f}')
    if repo.get("ai_radar_score", 0) > 0:
        scores.append(f'🤖 AI {repo["ai_radar_score"]:.2f}')
    if scores:
        lines.append(
            '<div class="repo-scores">'
            + " · ".join(scores)
            + '</div>'
        )

    if tags:
        lines.append(f'<div class="repo-tags">{tags}</div>')

    lines.append('</div>')
    return "\n".join(lines)


def generate_6section_report(
    repos: list[dict],
    date_str: str,
    readme_cache: dict = None,
    llm_analyses: dict = None,
    trend_analysis: str = "",
    yesterday_ranks: dict = None,
    yesterday_date: str = "",
) -> str:
    """生成6板块日报 HTML"""
    readme_cache = readme_cache or {}
    llm_analyses = llm_analyses or {}
    yesterday_ranks = yesterday_ranks or {}
    now = datetime.strptime(date_str, "%Y-%m-%d")
    date_display = now.strftime("%Y年%m月%d日")

    # ── 板块分组 ──────────────────────────────────────
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

    # 语言分布
    lang_counter = Counter(r.get("language", "Unknown") for r in repos)
    top_langs = lang_counter.most_common(8)
    max_lang = max(c for _, c in top_langs) if top_langs else 1

    # 统计
    total = len(repos)
    focus_cnt = sum(1 for r in repos if r.get("is_focus"))
    streak_cnt = sum(1 for r in repos if r.get("streak_days", 0) >= 2)

    # ════════════════════════════════════════════════════════
    # HTML 生成
    # ════════════════════════════════════════════════════════
    html = []

    # Header
    html.append(f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>GitHub 每日热点 — {date_display}</title>
<style>
:root {{
    --bg: #0d1117;
    --bg-card: #161b22;
    --border: #30363d;
    --text: #c9d1d9;
    --text-dim: #8b949e;
    --accent: #58a6ff;
    --accent-green: #3fb950;
    --accent-orange: #d2991d;
    --accent-red: #f85149;
    --accent-purple: #a371f7;
    --code-bg: #1c2128;
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    padding: 20px;
}}
.container {{ max-width: 960px; margin: 0 auto; }}
h1 {{ font-size: 1.6em; margin-bottom: 4px; }}
h1 .date {{ color: var(--text-dim); font-size: 0.9em; }}
h2 {{
    font-size: 1.3em;
    margin: 28px 0 12px;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--border);
}}
h2 .icon {{ margin-right: 6px; }}
.subtitle {{
    color: var(--text-dim);
    font-size: 0.85em;
    margin-bottom: 12px;
}}
.summary-bar {{
    display: flex;
    gap: 16px;
    flex-wrap: wrap;
    margin: 12px 0 20px;
    padding: 12px 16px;
    background: var(--bg-card);
    border-radius: 8px;
    border: 1px solid var(--border);
}}
.summary-item {{
    display: flex;
    flex-direction: column;
}}
.summary-item .num {{
    font-size: 1.4em;
    font-weight: 700;
    color: var(--accent);
}}
.summary-item .label {{
    font-size: 0.75em;
    color: var(--text-dim);
}}
.repo-card {{
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 14px 16px;
    margin-bottom: 10px;
    transition: border-color 0.2s;
}}
.repo-card:hover {{ border-color: var(--accent); }}
.repo-header {{
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
    margin-bottom: 8px;
}}
.repo-rank {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    border-radius: 6px;
    background: var(--accent);
    color: #fff;
    font-weight: 700;
    font-size: 0.8em;
    flex-shrink: 0;
}}
.repo-name {{
    color: var(--accent);
    font-weight: 600;
    font-size: 1.05em;
    text-decoration: none;
}}
.repo-name:hover {{ text-decoration: underline; }}
.badge {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 12px;
    font-size: 0.72em;
    font-weight: 600;
}}
.badge-info {{ background: #1f6feb22; color: var(--accent); }}
.badge-warning {{ background: #d2991d22; color: var(--accent-orange); }}
.repo-desc {{
    color: var(--text-dim);
    font-size: 0.88em;
    margin-bottom: 8px;
}}
.repo-stats {{
    display: flex;
    gap: 14px;
    flex-wrap: wrap;
    font-size: 0.82em;
    color: var(--text-dim);
}}
.repo-stats span {{
    display: inline-flex;
    align-items: center;
    gap: 2px;
}}
.health-meta {{ color: var(--accent-green); font-size: 0.8em; }}
.repo-scores {{
    margin-top: 6px;
    font-size: 0.78em;
    color: var(--accent-purple);
}}
.repo-tags {{
    margin-top: 4px;
    font-size: 0.76em;
    color: var(--text-dim);
}}
.lang-bar {{
    display: flex;
    gap: 6px;
    margin: 8px 0;
    flex-wrap: wrap;
}}
.lang-item {{
    display: flex;
    align-items: center;
    gap: 4px;
    font-size: 0.82em;
    padding: 4px 10px;
    background: var(--code-bg);
    border-radius: 4px;
}}
.lang-fill {{
    height: 8px;
    border-radius: 2px;
    background: var(--accent-green);
}}
.mark {{ color: var(--accent); }}
.trap-card {{ border-color: var(--accent-orange); }}
.trap-card:hover {{ border-color: var(--accent-red); }}
.streaks-table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.85em;
    margin: 8px 0;
}}
.streaks-table th {{
    text-align: left;
    padding: 6px 10px;
    border-bottom: 2px solid var(--border);
    color: var(--text-dim);
}}
.streaks-table td {{
    padding: 6px 10px;
    border-bottom: 1px solid var(--border);
}}
.streaks-table a {{ color: var(--accent); text-decoration: none; }}
.trend-block {{
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
    margin-bottom: 10px;
}}
.trend-block p {{ margin: 4px 0; }}
footer {{
    text-align: center;
    color: var(--text-dim);
    font-size: 0.75em;
    margin-top: 40px;
    padding: 20px 0;
    border-top: 1px solid var(--border);
}}
</style>
</head>
<body>
<div class="container">
<h1>🚀 GitHub 每日热点 <span class="date">— {date_display}</span></h1>
<div class="summary-bar">
    <div class="summary-item"><span class="num">{total}</span><span class="label">收录项目</span></div>
    <div class="summary-item"><span class="num">{focus_cnt}</span><span class="label">AI/ML/具身智能</span></div>
    <div class="summary-item"><span class="num">{len(burst)}</span><span class="label">正在爆发</span></div>
    <div class="summary-item"><span class="num">{len(traps)}</span><span class="label">热度陷阱</span></div>
    <div class="summary-item"><span class="num">{streak_cnt}</span><span class="label">连续在榜</span></div>
</div>
''')

    # ── 板块 ①：正在爆发 ──────────────────────────────
    html.append(f'<h2><span class="icon">🧨</span>正在爆发</h2>')
    html.append(f'<div class="subtitle">增长加速度最大的项目（日增量≥100）</div>')
    if burst:
        for i, r in enumerate(burst, 1):
            html.append(_repo_card(r, i, "burst", yesterday_ranks,
                                   readme_cache, llm_analyses))
    else:
        html.append('<div class="repo-card"><p style="color:var(--text-dim)">今日暂无爆发项目</p></div>')

    # ── 板块 ②：质量标杆 ──────────────────────────────
    html.append(f'<h2><span class="icon">🏆</span>质量标杆</h2>')
    html.append(f'<div class="subtitle">健康度极高 + 社区活跃的高质量项目</div>')
    if quality:
        for i, r in enumerate(quality, 1):
            html.append(_repo_card(r, i, "quality", yesterday_ranks,
                                   readme_cache, llm_analyses))
    else:
        html.append('<div class="repo-card"><p style="color:var(--text-dim)">今日暂缺高质量标杆项目</p></div>')

    # ── 板块 ③：潜力新星 ──────────────────────────────
    html.append(f'<h2><span class="icon">🌱</span>潜力新星</h2>')
    html.append(f'<div class="subtitle">创建不超过90天、势头良好的新兴项目</div>')
    if potential:
        for i, r in enumerate(potential, 1):
            html.append(_repo_card(r, i, "potential", yesterday_ranks,
                                   readme_cache, llm_analyses))
    else:
        html.append('<div class="repo-card"><p style="color:var(--text-dim)">今日暂无新星项目入榜</p></div>')

    # ── 板块 ④：热度陷阱 ──────────────────────────────
    html.append(f'<h2><span class="icon">⚠️</span>热度陷阱</h2>')
    html.append(f'<div class="subtitle">热度高但存在 issues 堆积/停更/单人维护等隐患</div>')
    if traps:
        for i, r in enumerate(traps, 1):
            card = _repo_card(r, i, "trap", yesterday_ranks, readme_cache, llm_analyses)
            card = card.replace('class="repo-card"', 'class="repo-card trap-card"')
            html.append(card)

            # 陷阱详情
            signals_text = []
            extra = r.get("_extra", {}) or {}
            if extra.get("open_issues", 0) > 10:
                signals_text.append(f'🐛 开放 Issues: {extra["open_issues"]}')
            if extra.get("last_push_days", 0) > 180:
                signals_text.append(f'⏸ 最后推送: {extra["last_push_days"]}天前')
            if extra.get("releases", 0) == 0:
                signals_text.append('📦 无 Release')
            if extra.get("contributors", 0) <= 1:
                signals_text.append('👤 单人维护')
            if signals_text:
                html.append(
                    '<div style="margin:-6px 0 10px 16px;font-size:0.8em;color:var(--accent-orange)">'
                    + " · ".join(signals_text) + '</div>'
                )
    else:
        html.append('<div class="repo-card"><p style="color:var(--text-dim)">今日未检测到热度陷阱</p></div>')

    # ── 板块 ⑤：AI/ML雷达 ─────────────────────────────
    html.append(f'<h2><span class="icon">🤖</span>AI / ML 雷达</h2>')
    html.append(f'<div class="subtitle">AI领域综合评分最高的项目</div>')
    if ai_radar:
        for i, r in enumerate(ai_radar, 1):
            html.append(_repo_card(r, i, "ai_radar", yesterday_ranks,
                                   readme_cache, llm_analyses))
    else:
        html.append('<div class="repo-card"><p style="color:var(--text-dim)">今日暂无AI项目入榜</p></div>')

    # ── 板块 ⑥：数据看板 ──────────────────────────────
    html.append(f'<h2><span class="icon">📊</span>今日数据看板</h2>')

    # 语言分布
    html.append('<h3 style="font-size:1em;margin:16px 0 8px;">编程语言分布</h3>')
    html.append('<div class="lang-bar">')
    for lang, cnt in top_langs:
        pct = cnt / total * 100 if total else 0
        html.append(
            f'<div class="lang-item">'
            f'<span class="lang-fill" style="width:{max(4, int(cnt / max_lang * 80))}px"></span>'
            f'{lang} {pct:.1f}% ({cnt})'
            f'</div>'
        )
    html.append('</div>')

    # 连续在榜
    streaks = sorted(
        [r for r in repos if r.get("streak_days", 0) >= 2],
        key=lambda r: r["streak_days"], reverse=True
    )[:10]
    if streaks:
        html.append('<h3 style="font-size:1em;margin:16px 0 8px;">连续在榜项目</h3>')
        html.append('<table class="streaks-table">'
                    '<tr><th>项目</th><th>连续</th><th>⭐</th><th>领域</th></tr>')
        for r in streaks:
            tags = "、".join(r.get("tags", [])[:2]) or "-"
            html.append(
                f'<tr>'
                f'<td><a href="{r["url"]}" target="_blank">{r["full_name"]}</a></td>'
                f'<td>{r["streak_days"]}天</td>'
                f'<td>{r["stars"]:,}</td>'
                f'<td>{tags}</td>'
                f'</tr>'
            )
        html.append('</table>')

    # 趋势分析
    if trend_analysis:
        html.append('<h3 style="font-size:1em;margin:16px 0 8px;">趋势分析</h3>')
        html.append(f'<div class="trend-block">{trend_analysis.replace(chr(10), "<br>")}</div>')

    # Footer
    html.append(f'''
<footer>
    📬 本报告由 GitHub Trending Daily Bot 自动生成 — {now.strftime("%Y-%m-%d %H:%M")} UTC
</footer>
</div>
</body>
</html>''')

    return "\n".join(html)


def save_6section_report(html_content: str, date_str: str) -> str:
    """保存6板块日报到文件"""
    os.makedirs(REPORTS_DIR, exist_ok=True)
    filename = f"daily-6s-{date_str}.html"
    filepath = os.path.join(REPORTS_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html_content)
    return filepath

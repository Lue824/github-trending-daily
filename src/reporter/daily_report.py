"""
6板块日报生成器 — Tailwind CSS 版

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
from src.reporter._shared import rank_badge, section_anchor_id
from src.utils.html_safe import esc

# ── Tailwind 暗色主题配色（GitHub Dark） ──────────────────────
TW = {
    "bg": "#0d1117",
    "card": "#161b22",
    "border": "#30363d",
    "text": "#c9d1d9",
    "dim": "#8b949e",
    "accent": "#58a6ff",
    "green": "#3fb950",
    "orange": "#d2991d",
    "red": "#f85149",
    "purple": "#a371f7",
    "code": "#1c2128",
}

# ── Tailwind CDN 配置 ──────────────────────────────────────
TAILWIND_CDN_SCRIPT = '<script src="https://cdn.tailwindcss.com"></script>'


def _repo_card(repo: dict, idx: int, section: str, yesterday_ranks: dict,
               readme_cache: dict, llm_analyses: dict) -> str:
    """单个项目卡片 — Tailwind 版"""
    from src.processor.describe_cn import generate_cn_intro_with_readme, generate_cn_detail

    stars = repo.get("stars", 0)
    inc = repo.get("stars_in_period", 0) or 0
    forks = repo.get("forks", 0)
    lang = repo.get("language", "Unknown")
    extra = repo.get("_extra", {}) or {}
    badge_text = rank_badge(repo, section, idx, yesterday_ranks)
    is_trap = repo.get("is_trap", False)
    trap_signals = repo.get("trap_signals", 0)

    # 陷阱边框
    border_class = f"border-[{TW['orange']}]" if is_trap else f"border-[{TW['border']}]"
    hover_class = f"hover:border-[{TW['red']}]" if is_trap else f"hover:border-[{TW['accent']}]"

    # 项目类型背景
    bg_class = ""
    if section == "正在爆发":
        bg_class = f"bg-[{TW['orange']}]/[0.03]"
    elif section == "质量标杆":
        bg_class = f"bg-[{TW['green']}]/[0.03]"

    # 陷阱徽章
    trap_html = ""
    if is_trap:
        trap_html = (
            f'<span class="inline-block px-2 py-0.5 rounded-full text-[11px] font-semibold '
            f'bg-[{TW["orange"]}]/15 text-[{TW["orange"]}]" '
            f'title="{trap_signals}个陷阱信号">⚠️ 陷阱×{trap_signals}</span>'
        )

    # 排名变化徽章
    badge_html = (
        f'<span class="inline-block px-2 py-0.5 rounded-full text-[11px] font-semibold '
        f'bg-[{TW["accent"]}]/15 text-[{TW["accent"]}]">{badge_text}</span>'
    )

    # 排名数字
    anchor = section_anchor_id(section, idx)
    parts = [
        f'<div id="{anchor}" class="bg-[{TW["card"]}] {bg_class} border {border_class} rounded-xl p-4 mb-3 transition-all duration-200 {hover_class}">',

        # ── 标题行 ──
        f'<div class="flex items-center gap-2 flex-wrap mb-2">'
        f'<span class="inline-flex items-center justify-center w-7 h-7 rounded-md '
        f'bg-[{TW["accent"]}] text-white font-bold text-xs flex-shrink-0">#{idx}</span>'
        f'<a href="{repo["url"]}" target="_blank" '
        f'class="text-[{TW["accent"]}] font-semibold no-underline hover:underline">'
        f'{repo["full_name"]}</a>'
        f'{trap_html} {badge_html}'
        f'</div>',

        # ── 描述 ──
        f'<div class="text-[{TW["dim"]}] text-sm mb-2 leading-relaxed">',
    ]

    llm = llm_analyses.get(repo["full_name"], "")
    if llm:
        parts.append(llm.replace("\n", "<br>"))
    else:
        readme = readme_cache.get(repo["full_name"], "")
        if readme:
            parts.append(generate_cn_intro_with_readme(repo, readme))
        else:
            parts.append(generate_cn_detail(repo))
    parts.append('</div>')

    # ── 数据行 ──
    stat_parts = [f'<span>⭐ {stars:,}</span>']
    if inc:
        stat_parts.append(f'<span>📈 +{inc:,}</span>')
    stat_parts.append(f'<span>🍴 {forks:,}</span>')
    stat_parts.append(f'<span>\U0001F4BB {esc(lang)}</span>')

    # 健康度
    if extra:
        health = []
        if extra.get("contributors"):
            health.append(f'👥 {extra["contributors"]}')
        if extra.get("open_issues"):
            health.append(f'🐛 {extra["open_issues"]} issues')
        # 统一活跃度标识
        last_push = extra.get("last_push_days", 999)
        if last_push <= 7:
            health.append(f'<span class="inline-block px-2 py-0.5 rounded-full text-[11px] bg-[{TW["green"]}]/12 text-[{TW["green"]}]">● 高活跃</span>')
        elif last_push <= 30:
            health.append(f'<span class="inline-block px-2 py-0.5 rounded-full text-[11px] bg-[{TW["orange"]}]/12 text-[{TW["orange"]}]">● 中等活跃</span>')
        elif last_push <= 180:
            health.append(f'<span class="inline-block px-2 py-0.5 rounded-full text-[11px] bg-[{TW["red"]}]/12 text-[{TW["red"]}]">● 低活跃</span>')
        else:
            health.append(f'<span class="inline-block px-2 py-0.5 rounded-full text-[11px] bg-[{TW["dim"]}]/12 text-[{TW["dim"]}]">● 长期静态</span>')
        if health:
            stat_parts.append(
                f'<span class="text-xs">{" · ".join(health)}</span>'
            )

    parts.append(
        f'<div class="flex gap-3.5 flex-wrap text-[13px] text-[{TW["dim"]}]">'
        + "".join(stat_parts) +
        '</div>'
    )

    # ── 评分徽章 ──
    scores = []
    for icon, key, threshold, color in [
        ("🧨", "burst_score", 0, TW["orange"]),
        ("🏆", "quality_score", 0.4, TW["green"]),
        ("🤖", "ai_radar_score", 0, TW["purple"]),
    ]:
        val = repo.get(key, 0)
        if val > threshold:
            scores.append(
                f'<span class="inline-block px-2 py-0.5 rounded text-[11px] font-semibold '
                f'bg-white/5 text-[{color}]">{icon} {val:.2f}</span>'
            )
    if scores:
        parts.append(
            f'<div class="mt-1.5 flex gap-1.5 flex-wrap">{"".join(scores)}</div>'
        )

    # ── 标签 ──
    tags_list = repo.get("tags", [])
    if tags_list:
        tag_capsules = "".join(
            f'<span class="inline-block px-2.5 py-0.5 rounded-full text-[11px] font-medium '
            f'bg-[{TW["accent"]}]/10 text-[{TW["accent"]}] border border-[{TW["accent"]}]/20">{esc(t)}</span>'
            for t in tags_list
        )
        parts.append(f'<div class="mt-1.5 flex gap-1.5 flex-wrap">{tag_capsules}</div>')

    parts.append('</div>')
    return "\n".join(parts)


def generate_6section_report(
    repos: list[dict],
    date_str: str,
    readme_cache: dict = None,
    llm_analyses: dict = None,
    trend_analysis: str = "",
    yesterday_ranks: dict = None,
    yesterday_date: str = "",
) -> str:
    """生成6板块日报 HTML — Tailwind CSS 版"""
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
    A, B, C, D, T, DI = TW["accent"], TW["border"], TW["bg"], TW["dim"], TW["text"], TW["code"]
    G, O, P = TW["green"], TW["orange"], TW["purple"]

    header = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>GitHub 每日热点 — {date_display}</title>
{TAILWIND_CDN_SCRIPT}
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans SC", sans-serif; }}
</style>
</head>
<body class="bg-[{C}] text-[{T}] leading-relaxed p-5">
<div class="max-w-[960px] mx-auto">

<h1 class="text-2xl font-bold mb-1">
  🚀 GitHub 每日热点 <span class="text-[{DI}] font-normal text-lg">— {date_display}</span>
</h1>

<div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-3 my-3 mb-5">
  <div class="p-3 rounded-lg border border-[{B}] bg-[{TW["card"]}] hover:border-[{A}] transition-colors cursor-default text-center">
    <div class="text-2xl font-bold text-[{A}]">{total}</div>
    <div class="text-xs text-[{DI}] mt-1">📦 收录项目</div>
  </div>
  <div class="p-3 rounded-lg border border-[{B}] bg-[{TW["card"]}] hover:border-[{A}] transition-colors cursor-default text-center">
    <div class="text-2xl font-bold text-[{A}]">{focus_cnt}</div>
    <div class="text-xs text-[{DI}] mt-1">🤖 AI项目</div>
  </div>
  <div class="p-3 rounded-lg border border-[{B}] bg-[{TW["card"]}] hover:border-[{A}] transition-colors cursor-default text-center">
    <div class="text-2xl font-bold text-[{A}]">{len(burst)}</div>
    <div class="text-xs text-[{DI}] mt-1">🧨 爆发项目</div>
  </div>
  <div class="p-3 rounded-lg border border-[{B}] bg-[{TW["card"]}] hover:border-[{A}] transition-colors cursor-default text-center">
    <div class="text-2xl font-bold text-[{O}]">{len(traps)}</div>
    <div class="text-xs text-[{DI}] mt-1">⚠️ 陷阱项目</div>
  </div>
  <div class="p-3 rounded-lg border border-[{B}] bg-[{TW["card"]}] hover:border-[{A}] transition-colors cursor-default text-center">
    <div class="text-2xl font-bold text-[{A}]">{streak_cnt}</div>
    <div class="text-xs text-[{DI}] mt-1">🔥 连续在榜</div>
  </div>
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
            f'<h2 class="text-xl font-semibold mt-7 mb-1 pb-2 border-b border-[{B}]">'
            f'<span class="mr-1.5">{icon}</span>{title}</h2>'
        )
        sections_html.append(f'<p class="text-sm text-[{DI}] mb-3">{sub}</p>')
        if repos_list:
            for i, r in enumerate(repos_list, 1):
                card = _repo_card(r, i, title.lower().replace(" ", "_") if not is_trap_section else "trap",
                                  yesterday_ranks, readme_cache, llm_analyses)
                sections_html.append(card)

                # 陷阱详情
                if is_trap_section:
                    extra = r.get("_extra", {}) or {}
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
                        sections_html.append(
                            f'<div class="-mt-2 mb-2.5 ml-4 text-xs text-[{O}]">'
                            + " · ".join(signals) + '</div>'
                        )
        else:
            sections_html.append(
                f'<div class="border border-dashed border-[{B}] rounded-xl p-4 mb-3 text-center">'
                f'<p class="text-sm text-[{DI}]">📋 {empty_text}</p></div>'
            )

    # ── 数据看板 ──
    lang_items = []
    for lang, cnt in top_langs:
        pct = cnt / total * 100 if total else 0
        bar_w = max(16, int(cnt / max_lang * 80))
        lang_items.append(
            f'<div class="flex items-center gap-1.5 text-[13px] px-2.5 py-1 '
            f'bg-[{DI}] rounded">'
            f'<span class="h-2 rounded-sm bg-[{G}]" style="width:{bar_w}px"></span>'
            f'{lang} {pct:.1f}% ({cnt})'
            f'</div>'
        )

    streak_rows = ""
    if streaks:
        for r in streaks:
            t = "、".join(r.get("tags", [])[:2]) or "-"
            streak_rows += (
                f'<tr class="border-b border-[{B}]">'
                f'<td class="py-1.5 px-2.5"><a href="{r["url"]}" target="_blank" class="text-[{A}] no-underline">{r["full_name"]}</a></td>'
                f'<td class="py-1.5 px-2.5">{r["streak_days"]}天</td>'
                f'<td class="py-1.5 px-2.5">{r["stars"]:,}</td>'
                f'<td class="py-1.5 px-2.5">{t}</td></tr>'
            )

    trend_block = ""
    trend_block = ""
    if trend_analysis:
        trend_block = (
            f'<h3 class="text-base font-semibold mt-5 mb-2 text-[{DI}]">趋势分析</h3>'
            f'<div class="bg-[{C}] border border-[{B}] rounded-xl p-4 mb-2.5 leading-relaxed">'
            f'{trend_analysis.replace(chr(10), "<br>")}</div>'
        )

    # ── 数据看板 ──
    dashboard = []
    dashboard.append(f'<h2 class="text-xl font-semibold mt-7 mb-1 pb-2 border-b border-[{B}]"><span class="mr-1.5">📊</span>今日数据看板</h2>')
    dashboard.append(f'<h3 class="text-base font-semibold mt-5 mb-2 text-[{DI}]">编程语言分布</h3>')
    dashboard.append(f'<div class="flex gap-1.5 flex-wrap my-2">{"".join(lang_items)}</div>')

    if streaks:
        dashboard.append(f'<h3 class="text-base font-semibold mt-5 mb-2 text-[{DI}]">连续在榜项目</h3>')
        dashboard.append(f'<table class="w-full border-collapse text-[13px] my-2">')
        dashboard.append(f'<tr class="border-b-2 border-[{B}] text-[{DI}]">'
                         '<th class="text-left py-1.5 px-2.5">项目</th>'
                         '<th class="text-left py-1.5 px-2.5">连续</th>'
                         '<th class="text-left py-1.5 px-2.5">⭐</th>'
                         '<th class="text-left py-1.5 px-2.5">领域</th></tr>')
        dashboard.append(streak_rows)
        dashboard.append('</table>')

    if trend_block:
        dashboard.append(trend_block)

    dashboard_html = "\n".join(dashboard)

    footer = f'''<footer class="text-center text-xs mt-10 pt-5 pb-0 border-t border-[{B}] text-[{DI}]">
📬 本报告由 GitHub Trending Daily Bot 自动生成 — {now.strftime("%Y-%m-%d %H:%M")} UTC
</footer>
</div>
</body>
</html>'''

    return header + "".join(sections_html) + dashboard_html + footer


def save_6section_report(html_content: str, date_str: str) -> str:
    """保存6板块日报到文件"""
    os.makedirs(REPORTS_DIR, exist_ok=True)
    filename = f"daily-6s-{date_str}.html"
    filepath = os.path.join(REPORTS_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html_content)
    return filepath

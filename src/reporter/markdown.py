"""Markdown 日报生成（中文介绍版）"""
import json
import os
from collections import Counter
from datetime import datetime

from config import REPORTS_DIR


def _streak_icon(repo: dict) -> str:
    days = repo.get("streak_days", 0)
    if days >= 7:
        return "🔥🔥🔥"
    if days >= 5:
        return "🔥🔥"
    if days >= 3:
        return "🔥"
    if repo.get("on_list_yesterday"):
        return "📌"
    return ""


def _tags_cn(repo: dict) -> str:
    tags = repo.get("tags", [])
    return " · ".join(f"`{t}`" for t in tags) if tags else ""


def generate_daily_report(
    repos: list[dict],
    date_str: str,
    readme_cache: dict = None,
    llm_analyses: dict = None,
    trend_analysis: str = "",
) -> str:
    now = datetime.strptime(date_str, "%Y-%m-%d")
    date_display = now.strftime("%Y年%m月%d日")

    from src.processor.describe_cn import (
        generate_cn_description, generate_cn_detail, generate_cn_intro_with_readme,
    )
    readme_cache = readme_cache or {}
    llm_analyses = llm_analyses or {}

    # ── 数据分组 ──────────────────────────────────────────
    trending = sorted(
        [r for r in repos if any("trending" in s for s in r.get("sources", []))],
        key=lambda r: r.get("hot_score", 0), reverse=True
    )[:15]
    new_stars = sorted(
        [r for r in repos if any("new-stars" in s for s in r.get("sources", []))],
        key=lambda r: r.get("stars", 0), reverse=True
    )[:10]
    focus_all = sorted(
        [r for r in repos if r.get("is_focus")],
        key=lambda r: r.get("hot_score", 0), reverse=True
    )[:15]

    lang_counter = Counter(r.get("language", "Unknown") for r in repos)
    top_langs = lang_counter.most_common(8)

    # ── 报告头部 ──────────────────────────────────────────
    lines = []
    lines.append(f"# 🚀 GitHub 每日热点 — {date_display}")
    lines.append("")
    lines.append(
        f"> 📅 统计日期：**{date_display}** | "
        f"收录项目：**{len(repos)}** 个 | "
        f"AI/ML/具身智能：**{sum(1 for r in repos if r.get('is_focus'))}** 个 | "
        f"数据来源：GitHub Trending + Search API"
    )
    lines.append("")

    lines.append("---")
    lines.append("")

    # ════════════════════════════════════════════════════════
    # 第 1 部分：今日 Trending TOP 10（详细中文介绍）
    # ════════════════════════════════════════════════════════
    lines.append("## 🔥 今日 Trending 榜单 TOP 10")
    lines.append("")
    lines.append("> 以下为 GitHub Trending 今日综合热度最高的 10 个项目，按 Star 增速和综合影响力排序。")
    lines.append("")

    for i, r in enumerate(trending[:10], 1):
        streak = _streak_icon(r)
        tags_cn = _tags_cn(r)

        # 优先用 LLM 深度分析，其次 README，最后基础介绍
        llm_analysis = llm_analyses.get(r["full_name"], "")
        if llm_analysis:
            cn_desc = llm_analysis
        else:
            readme = readme_cache.get(r["full_name"], "")
            if readme:
                cn_desc = generate_cn_intro_with_readme(r, readme)
            else:
                cn_desc = f"> {generate_cn_detail(r)}"

        stars_total = r.get("stars", 0)
        stars_today = r.get("stars_in_period", 0)
        forks = r.get("forks", 0)
        language = r.get("language", "Unknown")

        lines.append(f"### {i}. [{r['full_name']}]({r['url']}) {streak}")
        lines.append(f"**{r['owner']}/{r['name']}** — {language}")
        lines.append("")
        lines.append(cn_desc)
        lines.append("")
        lines.append(
            f"⭐ **{stars_total:,}** Stars &nbsp;|&nbsp; "
            f"📈 今日 **+{stars_today:,}** &nbsp;|&nbsp; "
            f"🍴 **{forks:,}** Forks"
        )
        if tags_cn:
            lines.append(f"<br>🏷️ {tags_cn}")
        lines.append("")

    # ════════════════════════════════════════════════════════
    # 第 2 部分：新星项目
    # ════════════════════════════════════════════════════════
    lines.append("---")
    lines.append("")
    lines.append("## ⭐ 本月新星项目（30天内创建）")
    lines.append("")
    lines.append("> 这些是近 30 天内新发布就迅速获得大量关注的项目，代表了最新的技术趋势。")
    lines.append("")

    if new_stars:
        for i, r in enumerate(new_stars, 1):
            cn_desc = generate_cn_description(r)
            stars_total = r.get("stars", 0)
            language = r.get("language", "Unknown")

            lines.append(f"### {i}. [{r['full_name']}]({r['url']})")
            lines.append(f"**{r['owner']}/{r['name']}** — {language} &nbsp;|&nbsp; ⭐ **{stars_total:,}**")
            lines.append("")
            lines.append(f"> {cn_desc}")
            lines.append("")
    else:
        lines.append("> ⚠️ 本次未获取到新星项目数据")
        lines.append("")

    # ════════════════════════════════════════════════════════
    # 第 3 部分：AI/ML/具身智能 重点关注
    # ════════════════════════════════════════════════════════
    lines.append("---")
    lines.append("")
    lines.append("## 🤖 AI / 机器学习 / 具身智能 重点关注")
    lines.append("")
    lines.append(
        "> 以下是从所有收录项目中筛选出的 AI 相关热门项目，"
        "涵盖**大模型/AI Agent**、**机器学习**、**深度学习**、**具身智能/机器人**四大领域。"
    )
    lines.append("")

    if focus_all:
        for i, r in enumerate(focus_all, 1):
            streak = _streak_icon(r)
            tags = r.get("tags", [])
            tags_str = " · ".join(tags) if tags else ""
            cn_desc = generate_cn_detail(r)
            stars_total = r.get("stars", 0)
            stars_today = r.get("stars_in_period", 0) or 0
            language = r.get("language", "Unknown")

            lines.append(f"### {i}. [{r['full_name']}]({r['url']}) {streak}")
            lines.append(f"**领域：{tags_str}** &nbsp;|&nbsp; {language} &nbsp;|&nbsp; ⭐ **{stars_total:,}**")
            lines.append("")
            lines.append(f"> {cn_desc}")
            if stars_today:
                lines.append(f"<br>📈 今日新增 **+{stars_today:,}** Stars")
            lines.append("")
    else:
        lines.append("> 今日暂无重点关注项目入榜")
        lines.append("")

    # ════════════════════════════════════════════════════════
    # 第 4 部分：语言分布
    # ════════════════════════════════════════════════════════
    lines.append("---")
    lines.append("")
    lines.append("## 📊 编程语言分布")
    lines.append("")
    max_lang_cnt = max(c for _, c in top_langs) if top_langs else 1
    for lang, cnt in top_langs:
        bar_len = max(1, int(cnt / max_lang_cnt * 20))
        bar = "█" * bar_len + "░" * (20 - bar_len)
        pct = cnt / len(repos) * 100 if repos else 0
        lines.append(f"```\n{lang:>15}  {bar}  {pct:.1f}% ({cnt})\n```")
    lines.append("")

    # ════════════════════════════════════════════════════════
    # 第 5 部分：连续在榜
    # ════════════════════════════════════════════════════════
    lines.append("---")
    lines.append("")
    lines.append("## 🏷️ 连续在榜项目")
    lines.append("")
    streaks = sorted(
        [r for r in repos if r.get("streak_days", 0) >= 2],
        key=lambda r: r["streak_days"], reverse=True
    )[:10]
    if streaks:
        lines.append("| 项目 | 连续上榜 | ⭐ Stars | 简介 |")
        lines.append("|------|----------|----------|------|")
        for r in streaks:
            tags_str = " · ".join(r.get("tags", [])) if r.get("tags") else "-"
            cn_desc = generate_cn_description(r)[:60]
            lines.append(
                f"| [{r['full_name']}]({r['url']}) | {r['streak_days']} 天 | "
                f"{r.get('stars', 0):,} | {cn_desc} |"
            )
        lines.append("")

        # 说明
        lines.append("")
        lines.append("| 标记 | 含义 |")
        lines.append("|------|------|")
        lines.append("| 🔥🔥🔥 | 连续 7 天以上在榜 |")
        lines.append("| 🔥🔥 | 连续 5-6 天在榜 |")
        lines.append("| 🔥 | 连续 3-4 天在榜 |")
        lines.append("| 📌 | 昨日也在榜 |")
    else:
        lines.append("> 暂无连续在榜项目（今天是首次运行，连续标记从明天开始出现）")
    lines.append("")

    # ════════════════════════════════════════════════════════
    # 第 6 部分：趋势分析（LLM 生成）
    # ════════════════════════════════════════════════════════
    if trend_analysis:
        lines.append("---")
        lines.append("")
        lines.append("## 🔍 今日趋势分析")
        lines.append("")
        lines.append(trend_analysis)
        lines.append("")

    # ════════════════════════════════════════════════════════
    # 第 7 部分：统计摘要
    # ════════════════════════════════════════════════════════
    lines.append("---")
    lines.append("")
    lines.append("## 📈 今日统计摘要")
    lines.append("")
    lines.append(f"| 指标 | 数值 |")
    lines.append(f"|------|------|")
    lines.append(f"| 📦 总收录项目 | **{len(repos)}** 个 |")
    lines.append(f"| 🔥 Trending 入榜 | **{len(trending)}** 个 |")
    lines.append(f"| ⭐ 本月新星项目 | **{len(new_stars)}** 个 |")
    lines.append(f"| 🤖 AI/ML/具身智能 | **{sum(1 for r in repos if r.get('is_focus'))}** 个 |")
    lines.append(f"| 🔄 连续在榜 (≥2天) | **{len(streaks)}** 个 |")
    lines.append("")
    lines.append(
        f"---\n"
        f"*📬 本报告由 GitHub Trending Daily Bot 自动生成 — {now.strftime('%Y-%m-%d %H:%M')} UTC*\n"
        f"*📧 订阅邮箱：{os.getenv('RECEIVER_EMAIL', '')}*"
    )
    lines.append("")

    return "\n".join(lines)


def generate_monthly_report(stats: dict, year: int, month: int) -> str:
    """生成月度趋势分析报告"""
    lines = []
    lines.append(f"# 📊 GitHub 月度趋势分析 — {year}年{month:02d}月")
    lines.append("")
    lines.append("> 基于过去 30 天的每日追踪数据，分析本月 GitHub 开源热点趋势")
    lines.append("")

    lines.append("---")
    lines.append("")

    # ── 持续热门 ──────────────────────────────────────
    lines.append("## 🏆 月度持续热门项目（上榜天数最多）")
    lines.append("")
    lines.append("> 这些项目在 30 天内多次出现在每日榜单中，是本月最受持续关注的开源项目。")
    lines.append("")
    persistent = stats.get("persistent_hot", [])[:10]
    if persistent:
        lines.append("| 项目 | 语言 | ⭐ 最高Star | 📅 上榜天数 | 领域 |")
        lines.append("|------|------|-------------|------------|------|")
        for r in persistent:
            tags_raw = r.get("all_tags", "") or ""
            tags = "、".join(set(tags_raw.split(","))) if tags_raw else "-"
            lines.append(
                f"| [{r['full_name']}](https://github.com/{r['full_name']}) | "
                f"{r.get('language', '?')} | {r.get('max_stars', 0):,} | "
                f"{r.get('days_on_list', 0)} 天 | {tags[:60]} |"
            )
    else:
        lines.append("> 暂无数据")
    lines.append("")

    lines.append("---")
    lines.append("")

    # ── 增速最快 ──────────────────────────────────────
    lines.append("## 🚀 月度增速最快项目")
    lines.append("")
    lines.append("> 本月 Star 数量增长最快的项目，反映技术热点的快速迁移。")
    lines.append("")
    growth = stats.get("fastest_growing", [])[:10]
    if growth:
        lines.append("| 项目 | ⭐ 当前Star | 📈 月度增长 | 📅 追踪天数 |")
        lines.append("|------|-------------|------------|----------|")
        for r in growth:
            lines.append(
                f"| [{r['full_name']}](https://github.com/{r['full_name']}) | "
                f"{r.get('current_stars', 0):,} | "
                f"**+{r.get('star_growth', 0):,}** | "
                f"{r.get('days_tracked', 0)} 天 |"
            )
    else:
        lines.append("> 暂无数据")
    lines.append("")

    lines.append("---")
    lines.append("")

    # ── 语言热度 ──────────────────────────────────────
    lines.append("## 🌐 最热门编程语言 (Top 10)")
    lines.append("")
    top_langs = stats.get("top_languages", [])[:10]
    if top_langs:
        lines.append("| 语言 | 收录次数 | 平均 ⭐ Star |")
        lines.append("|------|----------|-------------|")
        for lang in top_langs:
            lines.append(f"| {lang['language']} | {lang['cnt']} 次 | {lang.get('avg_stars', 0):,.0f} |")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("*📬 本报告由 GitHub Trending Daily Bot 自动生成*")
    lines.append("")

    return "\n".join(lines)


def save_report(content: str, filename: str) -> str:
    os.makedirs(REPORTS_DIR, exist_ok=True)
    filepath = os.path.join(REPORTS_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    return filepath

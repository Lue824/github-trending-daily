"""月报 Markdown 生成"""
import os

from config import REPORTS_DIR


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

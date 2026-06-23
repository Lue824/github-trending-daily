"""日报生成共享工具函数"""
import re
from collections import Counter


def streak_icon(repo: dict) -> str:
    """连续在榜火焰标记"""
    days = repo.get("streak_days", 0)
    if days >= 7:
        return "🔥🔥🔥"
    if days >= 5:
        return "🔥🔥"
    if days >= 3:
        return "🔥"
    return ""


def rank_badge(repo: dict, section: str, today_rank: int,
               yesterday_ranks: dict) -> str:
    """生成排名变化标注"""
    if not repo.get("on_list_yesterday"):
        return "🆕 新上榜"

    badge = "📌 昨日也上榜"
    if yesterday_ranks:
        section_ranks = yesterday_ranks.get(repo["full_name"], {})
        yesterday_rank = section_ranks.get(section)
        if yesterday_rank is not None:
            diff = yesterday_rank - today_rank
            if diff > 0:
                badge += f"（↑{diff}）"
            elif diff < 0:
                badge += f"（↓{abs(diff)}）"
            else:
                badge += "（-）"
    return badge


def tags_cn(repo: dict) -> str:
    """中文标签行内展示"""
    tags = repo.get("tags", [])
    return " · ".join(f"`{t}`" for t in tags) if tags else ""


def section_anchor_id(section: str, rank: int) -> str:
    """生成报告内跳转锚点 ID"""
    prefixes = {
        "trending": "t", "new_stars": "n", "focus": "f",
        "burst": "b", "quality": "q", "potential": "p",
        "trap": "t", "ai_radar": "a",
    }
    return f"{prefixes.get(section, 'x')}-r{rank}"


def brief_one_liner(repo: dict, llm_analyses: dict) -> str:
    """从 LLM 多维度分析中提取一句话要点摘要"""
    llm = llm_analyses.get(repo["full_name"], "")
    if llm:
        # 去掉可能的开场白
        llm = re.sub(r'好的[,，].*?\n', '', llm)
        # 提取 🚀 一句话定位 行的内容
        for line in llm.split("\n"):
            line = line.strip()
            markers = ["🚀", "一句话定位", "**一句话定位**"]
            if any(m in line for m in markers):
                # 提取冒号后面的内容
                parts = line.split("：", 1) if "：" in line else line.split(":", 1)
                content = parts[1].strip() if len(parts) > 1 else line
                content = content.replace("**", "").strip()
                if len(content) > 10:
                    return f"💡 {content}"
                break
        # 回退：取第一行非空且有意义的句子
        for line in llm.replace("\n", " ").split("。"):
            line = line.strip()
            line = re.sub(r'\*\*[^*]+\*\*[:：]?\s*', '', line).strip()
            if len(line) > 15:
                return f"💡 {line}。"
                break
    from src.processor.describe_cn import generate_cn_description
    desc = generate_cn_description(repo)
    return f"💡 {desc}"


def build_section_data(repos: list[dict]) -> dict:
    """
    从 repos 中构建报告所需的三大区域分组数据

    Returns:
        dict with keys: trending_sorted, new_stars_sorted, focus_sorted,
        lang_counter, top_langs, streaks
    """
    trending_sorted = sorted(
        [r for r in repos if any("trending" in s for s in r.get("sources", []))],
        key=lambda r: r.get("hot_score", 0), reverse=True
    )
    new_stars_sorted = sorted(
        [r for r in repos if any("new-stars" in s for s in r.get("sources", []))],
        key=lambda r: r.get("stars", 0), reverse=True
    )
    focus_sorted = sorted(
        [r for r in repos if r.get("is_focus")],
        key=lambda r: r.get("hot_score", 0), reverse=True
    )

    lang_counter = Counter(r.get("language", "Unknown") for r in repos)
    top_langs = lang_counter.most_common(8)

    streaks = sorted(
        [r for r in repos if r.get("streak_days", 0) >= 2],
        key=lambda r: r["streak_days"], reverse=True
    )[:10]

    return {
        "trending_sorted": trending_sorted,
        "new_stars_sorted": new_stars_sorted,
        "focus_sorted": focus_sorted,
        "lang_counter": lang_counter,
        "top_langs": top_langs,
        "streaks": streaks,
    }


def count_section_dups(section_repos: list[dict], top_n: int,
                       yesterday_ranks: dict, section_key: str) -> int:
    """统计 top_n 中有多少个昨日在榜"""
    cnt = 0
    for r in section_repos[:top_n]:
        if section_key in yesterday_ranks.get(r["full_name"], {}):
            cnt += 1
    return cnt


def yesterday_jump_url(yesterday_date: str, section: str = "",
                       rank: int = 0) -> str:
    """生成跳转到昨日报告的 URL"""
    base = (
        f"https://github.com/Lue824/github-trending-daily"
        f"/blob/master/data/reports/daily-{yesterday_date}.md"
    )
    if section and rank:
        anchor = section_anchor_id(section, rank)
        return f"{base}#{anchor}"
    return base

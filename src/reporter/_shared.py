"""日报生成共享工具函数"""


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


def section_anchor_id(section: str, rank: int) -> str:
    """生成报告内跳转锚点 ID"""
    prefixes = {
        "trending": "t", "new_stars": "n", "focus": "f",
        "burst": "b", "quality": "q", "potential": "p",
        "trap": "t", "ai_radar": "a",
    }
    return f"{prefixes.get(section, 'x')}-r{rank}"

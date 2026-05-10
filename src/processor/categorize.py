"""按领域分类并标记重点项目"""
from config import FOCUS_KEYWORDS


def classify_repos(repos: list[dict]) -> list[dict]:
    """
    为每个仓库打上领域标签

    Returns:
        repos 中每个 item 新增 tags 字段: ["机器学习", "具身智能", ...]
    """
    for repo in repos:
        tags = _match_focus_areas(repo)
        repo["tags"] = tags
        repo["is_focus"] = len(tags) > 0
    return repos


def _match_focus_areas(repo: dict) -> list[str]:
    """检查仓库是否属于重点关注的领域"""
    # 构建搜索文本：名称 + 描述 + topics
    text = f"{repo.get('name', '')} {repo.get('description', '')} {' '.join(repo.get('topics', []))}".lower()
    matched = []
    for area, keywords in FOCUS_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in text:
                matched.append(area)
                break  # 每个领域只记一次
    return matched


def compute_hot_score(repo: dict) -> float:
    """
    综合热度评分，用于跨源排序

    公式：stars * 0.3 + stars_in_period * 0.5 + forks * 0.2 + focus_bonus
    """
    stars = repo.get("stars", 0)
    stars_period = repo.get("stars_in_period", 0) or 0
    forks = repo.get("forks", 0)
    is_focus = 1 if repo.get("is_focus") else 0
    source_bonus = 0
    sources = repo.get("sources", [])
    if len(sources) >= 2:
        source_bonus = 1.5  # 多源验证加分

    # 对数缩放避免头部项目分差过大
    import math
    score = math.log(stars + 1) * 0.3 + stars_period * 0.5 + math.log(forks + 1) * 0.2
    score += is_focus * 2.0 + source_bonus * 1.0
    return round(score, 2)


def sort_by_hotness(repos: list[dict]) -> list[dict]:
    """按综合热度降序排列"""
    return sorted(repos, key=compute_hot_score, reverse=True)

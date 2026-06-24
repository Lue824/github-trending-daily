"""
多维评分系统

基于决策文档的6板块设计：
① 正在爆发 — 增长加速度最大
② 质量标杆 — 星多 + 健康度极高 + 社区活跃
③ 潜力新星 — 创建<90天 + 势头好
④ 热度陷阱 — 星多但 issue 堆积/停更/单人维护
⑤ AI雷达 — AI领域综合评分
⑥ 数据看板 — 统计摘要（在 reporter 中处理）

每个维度 0~1 归一化
"""
import math


def _sigmoid(x: float, k: float = 0.1) -> float:
    """Sigmoid 归一化，将输入映射到 (-1, 1)"""
    return 2 / (1 + math.exp(-k * x)) - 1


def _log_norm(x: float, base: float = 100, scale: float = 2.0) -> float:
    """对数归一化"""
    if x <= 0:
        return 0.0
    return min(1.0, math.log(x + 1, base) / scale)


def _ratio_norm(a: float, b: float) -> float:
    """比率归一化，当 b 为 0 时返回 0"""
    if b == 0:
        return 0.0
    ratio = a / b
    return min(1.0, _sigmoid(ratio * 10, k=0.3))


# ════════════════════════════════════════════════════════════
# 子维度计算
# ════════════════════════════════════════════════════════════

def _growth_score(repo: dict) -> float:
    """增长势头得分：基于日增量"""
    inc = repo.get("stars_in_period", 0) or 0
    if inc >= 5000:
        return 1.0
    if inc >= 2000:
        return 0.85
    if inc >= 1000:
        return 0.7
    if inc >= 500:
        return 0.5
    if inc >= 200:
        return 0.3
    if inc >= 100:
        return 0.2
    return 0.1


def _acceleration_score(repo: dict, extra: dict) -> float:
    """增长加速度得分"""
    inc = repo.get("stars_in_period", 0) or 0
    stars = repo.get("stars", 1)
    # 日增量 / 总星数 = 增长率
    daily_rate = inc / stars if stars > 0 else 0
    # 对数缩放
    if daily_rate >= 1.0:
        return 1.0
    if daily_rate >= 0.5:
        return 0.9
    if daily_rate >= 0.2:
        return 0.75
    if daily_rate >= 0.1:
        return 0.6
    if daily_rate >= 0.05:
        return 0.4
    if daily_rate >= 0.01:
        return 0.2
    return 0.1


def _community_response_score(extra: dict) -> float:
    """社区响应速度得分：基于 issue/PR 处理"""
    if not extra:
        return 0.5
    open_issues = extra.get("open_issues", 0)
    open_prs = extra.get("open_prs", 0)
    # issue 少 = 处理及时
    issues_score = max(0, 1.0 - _log_norm(open_issues, base=50, scale=2))
    prs_score = max(0, 1.0 - _log_norm(open_prs, base=20, scale=2))
    return issues_score * 0.5 + prs_score * 0.5


def _maintenance_activity_score(extra: dict) -> float:
    """维护活跃度得分"""
    if not extra:
        return 0.3
    last_push = extra.get("last_push_days", 999)
    commits = extra.get("commits_12w", 0)

    # 最近推送
    if last_push <= 1:
        push_score = 1.0
    elif last_push <= 7:
        push_score = 0.8
    elif last_push <= 30:
        push_score = 0.5
    elif last_push <= 90:
        push_score = 0.2
    else:
        push_score = 0.0

    # 提交频率
    commit_score = _log_norm(commits, base=50, scale=2)

    return push_score * 0.4 + commit_score * 0.6


def _engineering_maturity_score(repo: dict, extra: dict) -> float:
    """工程成熟度得分"""
    if not extra:
        return 0.3
    releases = extra.get("releases", 0)
    contributors = extra.get("contributors", 0)
    created_days = extra.get("created_days", 365)

    # Release 稳定性
    release_score = _log_norm(releases, base=5, scale=1.5)

    # 贡献者多样性
    contrib_score = _log_norm(contributors, base=10, scale=1.5)

    # 项目年龄加分（老项目更成熟）
    age_score = _log_norm(created_days, base=100, scale=3)

    return release_score * 0.3 + contrib_score * 0.4 + age_score * 0.3


def _community_participation_score(repo: dict, extra: dict) -> float:
    """社区参与度得分"""
    stars = repo.get("stars", 1)
    forks = repo.get("forks", 0)
    if not extra:
        contributors = 0
    else:
        contributors = extra.get("contributors", 0)

    # Fork/Star 比（社区参与）
    fork_ratio = forks / stars if stars > 0 else 0
    fork_score = min(1.0, fork_ratio * 20)  # 5% 即可满分

    # 贡献者活跃度
    contrib_score = _log_norm(contributors, base=5, scale=1.5)

    return fork_score * 0.5 + contrib_score * 0.5


def _trap_signals(repo: dict, extra: dict) -> int:
    """
    检测热度陷阱信号数量

    信号：
    1. Issue/Star 比过高 (open_issues / stars > 0.01)
    2. 长期未推送 (last_push > 180 天)
    3. 无 Release 且创建超过 180 天
    4. 单人维护且 Star > 5000
    5. 今日增量巨大但 Fork 极少 (funnel)
    """
    signals = 0
    stars = repo.get("stars") or 1

    if extra:
        open_issues = extra.get("open_issues") or 0
        if stars > 0 and open_issues / stars > 0.01 and open_issues > 10:
            signals += 1

        last_push = extra.get("last_push_days", 0)
        if last_push > 180:
            signals += 1

        releases = extra.get("releases", 0)
        created_days = extra.get("created_days", 0)
        if releases == 0 and created_days > 180 and stars > 1000:
            signals += 1

        contributors = extra.get("contributors", 0)
        if contributors <= 1 and stars > 5000:
            signals += 1

    # Fork 漏斗检测
    forks = repo.get("forks", 0)
    inc = repo.get("stars_in_period", 0) or 0
    if inc > 1000 and forks < 50:
        signals += 1

    return signals


def _ai_eco_match_score(repo: dict) -> float:
    """AI 生态匹配度得分"""
    topics = [t.lower() for t in repo.get("topics", [])]
    tags = repo.get("tags", [])
    name = repo.get("name", "").lower()
    desc = (repo.get("description", "") or "").lower()

    score = 0.0

    # 核心 AI 关键词（高权重）
    core_ai = {
        "llm": 0.3, "large-language-model": 0.3, "transformer": 0.25,
        "gpt": 0.25, "agent": 0.25, "rag": 0.2, "langchain": 0.2,
        "machine-learning": 0.15, "deep-learning": 0.15, "neural-network": 0.15,
        "reinforcement-learning": 0.15, "robotics": 0.15,
        "diffusion": 0.15, "fine-tuning": 0.2, "embedding": 0.15,
        "prompt-engineering": 0.15, "vector-database": 0.15,
    }

    for kw, weight in core_ai.items():
        if kw in desc or kw in name or kw in " ".join(topics):
            score += weight

    # 领域标签加分
    if "大模型/AI" in tags:
        score += 0.2
    if "深度学习" in tags:
        score += 0.15
    if "机器学习" in tags:
        score += 0.1
    if "具身智能" in tags:
        score += 0.15

    return min(1.0, score)


# ════════════════════════════════════════════════════════════
# 六大板块评分
# ════════════════════════════════════════════════════════════

def score_burst(repo: dict, extra: dict) -> float:
    """
    ① 正在爆发
    Formula: 加速度 × 0.6 + 增速 × 0.4
    Threshold: 日增量 >= 100
    """
    inc = repo.get("stars_in_period", 0) or 0
    if inc < 100:
        return 0.0
    return _acceleration_score(repo, extra) * 0.6 + _growth_score(repo) * 0.4


def score_quality(repo: dict, extra: dict) -> float:
    """
    ② 质量标杆
    Formula: 社区响应×0.25 + 维护活跃×0.25 + 工程成熟×0.25 + 社区参与×0.25
    Threshold: >= 0.6
    """
    return (
        _community_response_score(extra) * 0.25
        + _maintenance_activity_score(extra) * 0.25
        + _engineering_maturity_score(repo, extra) * 0.25
        + _community_participation_score(repo, extra) * 0.25
    )


def score_potential(repo: dict, extra: dict) -> float:
    """
    ③ 潜力新星
    Formula: 增长势头×0.5 + 初生质量×0.3 + 赛道热度×0.2
    Threshold: 创建 <= 90 天
    """
    created_days = extra.get("created_days", 999) if extra else 999
    if created_days > 90:
        return 0.0
    growth = _growth_score(repo)
    quality = score_quality(repo, extra)
    # 赛道热度：如果是 AI 类项目加分
    ai_score = _ai_eco_match_score(repo)
    return growth * 0.5 + quality * 0.3 + ai_score * 0.2


def score_trap(repo: dict, extra: dict, all_scores: dict = None) -> tuple[bool, int]:
    """
    ④ 热度陷阱
    条件：热度 top 30% AND 健康度 bottom 30%
    返回 (is_trap, signal_count)
    """
    signals = _trap_signals(repo, extra)
    # 热度：用 hot_score 判断
    hot_score = repo.get("hot_score", 0)
    if all_scores and "hot_scores" in all_scores:
        hot_scores = all_scores["hot_scores"]
        pct_rank = sum(1 for s in hot_scores if s > hot_score) / max(len(hot_scores), 1)
        is_hot = pct_rank <= 0.3
    else:
        is_hot = hot_score > 5.0  # 简化判断

    # 健康度
    quality = score_quality(repo, extra)
    if all_scores and "quality_scores" in all_scores:
        q_scores = all_scores["quality_scores"]
        q_rank = sum(1 for s in q_scores if s > quality) / max(len(q_scores), 1)
        is_unhealthy = q_rank >= 0.7
    else:
        is_unhealthy = quality < 0.3

    is_trap = is_hot and is_unhealthy and signals >= 2
    return is_trap, signals


def score_ai_radar(repo: dict, extra: dict) -> float:
    """
    ⑤ AI雷达
    Formula: 热度×0.3 + 健康度×0.3 + AI生态匹配×0.4
    """
    if not repo.get("is_focus"):
        return 0.0
    hot = _growth_score(repo)
    health = score_quality(repo, extra)
    ai_match = _ai_eco_match_score(repo)
    return hot * 0.3 + health * 0.3 + ai_match * 0.4


# ════════════════════════════════════════════════════════════
# 批量评分
# ════════════════════════════════════════════════════════════

def compute_all_scores(repos: list[dict], extra_cache: dict[str, dict]) -> list[dict]:
    """
    为所有仓库计算各板块评分

    Returns:
        repos 中每个 item 新增:
        - burst_score, quality_score, potential_score
        - is_trap, trap_signals
        - ai_radar_score
    """
    # 收集所有分数用于百分位计算
    all_hot = []
    all_quality = []

    # 先计算一轮
    for r in repos:
        extra = extra_cache.get(r["full_name"], {})
        r["burst_score"] = score_burst(r, extra)
        r["quality_score"] = score_quality(r, extra)
        r["potential_score"] = score_potential(r, extra)
        r["ai_radar_score"] = score_ai_radar(r, extra)
        all_hot.append(r.get("hot_score", 0))
        all_quality.append(r["quality_score"])

    # 第二轮：陷阱评分需要全局百分位
    all_context = {"hot_scores": all_hot, "quality_scores": all_quality}
    for r in repos:
        extra = extra_cache.get(r["full_name"], {})
        is_trap, trap_signals = score_trap(r, extra, all_context)
        r["is_trap"] = is_trap
        r["trap_signals"] = trap_signals

    return repos


# ════════════════════════════════════════════════════════════
# 趋势分析辅助
# ════════════════════════════════════════════════════════════

def get_section_labels() -> dict:
    """板块中文标注"""
    return {
        "burst": {"icon": "🧨", "label": "正在爆发", "desc": "增长加速度最大"},
        "quality": {"icon": "🏆", "label": "质量标杆", "desc": "星多+健康度极高+社区活跃"},
        "potential": {"icon": "🌱", "label": "潜力新星", "desc": "创建<90天+势头好"},
        "trap": {"icon": "⚠️", "label": "热度陷阱", "desc": "星多但issue堆积/停更/单人维护"},
        "ai_radar": {"icon": "🤖", "label": "AI/ML雷达", "desc": "AI领域综合评分"},
    }

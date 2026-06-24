"""
统一数据流水线
抓取 → 去重 → 分类 → 评分 → 存储 → LLM分析
供 CLI (src/main.py) 和 Web (web/app.py) 共用
"""
import logging
import os
from datetime import datetime, timedelta, timezone

from src.fetcher.trending import fetch_all_trending
from src.fetcher.search_api import fetch_all_api, fetch_readme
from src.fetcher.extra_api import fetch_extra_batch
from src.processor.dedup import deduplicate
from src.processor.categorize import classify_repos, sort_by_hotness, compute_hot_score
from src.processor.scoring import compute_all_scores
from src.storage.db import (
    init_db, save_daily_repos, mark_consecutive_streak,
    get_yesterday_section_ranks,
)

logger = logging.getLogger("pipeline")


def run_pipeline(date_str: str = None) -> dict | None:
    """
    运行完整数据流水线

    Args:
        date_str: YYYY-MM-DD 格式日期，默认今天 UTC

    Returns:
        dict: repos, readme_cache, llm_analyses, trend_analysis,
              yesterday_ranks, extra_cache, today, yesterday
        无数据时返回 None
    """
    today = date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

    # 1. 初始化数据库
    init_db()

    # 2. 抓取多源数据
    logger.info("Step 1: Fetching data...")
    trending_repos = fetch_all_trending()
    api_repos = fetch_all_api()
    all_raw = trending_repos + api_repos
    logger.info(f"Fetched {len(trending_repos)} from trending, {len(api_repos)} from API ({len(all_raw)} total)")

    if not all_raw:
        logger.warning("No data fetched, aborting")
        return None

    # 3. 去重
    logger.info("Step 2: Deduplicating...")
    repos = deduplicate(all_raw)
    logger.info(f"After dedup: {len(repos)} unique repos")

    # 4. 分类和热度评分
    logger.info("Step 3: Classifying and hot scoring...")
    repos = classify_repos(repos)
    for r in repos:
        r["hot_score"] = compute_hot_score(r)
    repos = sort_by_hotness(repos)

    # 5. 历史对比（连续在榜）
    logger.info("Step 4: Marking streaks...")
    repos = mark_consecutive_streak(repos, today, yesterday)

    # 6. 获取额外健康度数据
    logger.info("Step 5: Fetching extra health data...")
    extra_cache = fetch_extra_batch(repos)

    # 7. 计算多维板块评分
    logger.info("Step 6: Computing multi-dimensional scores...")
    repos = compute_all_scores(repos, extra_cache)

    # 将 extra 数据挂到 repo 上
    for r in repos:
        r["_extra"] = extra_cache.get(r["full_name"], {})

    # 8. 为报告区域抓取 README
    yesterday_ranks = get_yesterday_section_ranks(yesterday)
    logger.info(f"Yesterday rankings: {len(yesterday_ranks)} repos")

    logger.info("Step 7: Fetching READMEs for report repos...")
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

    def _count_dups(section_repos, top_n, yr, section_key):
        cnt = 0
        for r in section_repos[:top_n]:
            if section_key in yr.get(r["full_name"], {}):
                cnt += 1
        return cnt

    trending_dup = _count_dups(trending_sorted, 10, yesterday_ranks, "trending")
    new_stars_dup = _count_dups(new_stars_sorted, 10, yesterday_ranks, "new_stars")
    focus_dup = _count_dups(focus_sorted, 15, yesterday_ranks, "focus")

    trending_top = trending_sorted[:10 + trending_dup]
    new_stars_top = new_stars_sorted[:10 + new_stars_dup]
    focus_top = focus_sorted[:15 + focus_dup]

    report_repos = {}
    for r in trending_top + new_stars_top + focus_top:
        report_repos[r["full_name"]] = r

    # 加上爆发和质量项目
    for r in repos:
        if r.get("burst_score", 0) > 0.5 or r.get("quality_score", 0) >= 0.6:
            report_repos.setdefault(r["full_name"], r)

    readme_cache = {}
    for r in list(report_repos.values())[:30]:
        readme = fetch_readme(r["owner"], r["name"])
        if readme:
            readme_cache[r["full_name"]] = readme
    logger.info(f"Fetched {len(readme_cache)} READMEs for {len(report_repos)} report repos")

    # 9. 存储到数据库
    logger.info("Step 8: Saving to database...")
    save_daily_repos(repos, today)

    # 10. LLM 深度分析
    llm_analyses = {}
    trend_analysis = ""
    deepseek_key = os.getenv("DEEPSEEK_API_KEY", "")
    try:
        from src.processor.llm_summarize import summarize_project, analyze_trends
        if deepseek_key and deepseek_key not in ("sk-xxxxxxxxxxxx", "") and readme_cache:
            logger.info(f"Running LLM deep analysis on {len(report_repos)} repos...")
            for full_name, r in report_repos.items():
                readme = readme_cache.get(full_name, "")
                if readme:
                    analysis = summarize_project(r, readme)
                    if analysis:
                        llm_analyses[full_name] = analysis
            if llm_analyses:
                trend_analysis = analyze_trends(repos, readme_cache) or ""
            logger.info(f"LLM analyzed {len(llm_analyses)} projects")
    except Exception as e:
        logger.warning(f"LLM analysis failed: {e}", exc_info=True)

    return {
        "repos": repos,
        "readme_cache": readme_cache,
        "llm_analyses": llm_analyses,
        "trend_analysis": trend_analysis,
        "yesterday_ranks": yesterday_ranks,
        "extra_cache": extra_cache,
        "today": today,
        "yesterday": yesterday,
    }

"""
GitHub Trending Daily — 主入口
编排数据抓取 → 处理 → 存储 → 报告 → 推送全流程
"""
import logging
import sys
import os
from datetime import datetime, timedelta

# 确保 src 目录在路径中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.fetcher.trending import fetch_all_trending
from src.fetcher.search_api import fetch_all_api, fetch_readme
from src.processor.dedup import deduplicate
from src.processor.categorize import classify_repos, sort_by_hotness, compute_hot_score
from src.storage.db import (
    init_db, save_daily_repos, save_daily_summary,
    mark_consecutive_streak, cleanup_old_data, get_monthly_stats,
)
from src.reporter.markdown import (
    generate_daily_report, generate_monthly_report, save_report,
)
from src.notifier.email_sender import send_email, markdown_to_html

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")

TODAY = datetime.utcnow().strftime("%Y-%m-%d")
YESTERDAY = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")


def run_daily():
    """每日主流程"""
    logger.info(f"=== Starting daily run: {TODAY} ===")

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
        return

    # 3. 去重
    logger.info("Step 2: Deduplicating...")
    repos = deduplicate(all_raw)
    logger.info(f"After dedup: {len(repos)} unique repos")

    # 4. 分类和评分
    logger.info("Step 3: Classifying and scoring...")
    repos = classify_repos(repos)
    for r in repos:
        r["hot_score"] = compute_hot_score(r)
    repos = sort_by_hotness(repos)

    # 5. 历史对比（连续在榜）
    logger.info("Step 4: Marking streaks...")
    repos = mark_consecutive_streak(repos, TODAY, YESTERDAY)

    # 6. 为报告各区域需要的项目抓取 README
    logger.info("Step 5: Fetching READMEs for report repos...")
    trending_top = sorted(
        [r for r in repos if any("trending" in s for s in r.get("sources", []))],
        key=lambda r: r.get("hot_score", 0), reverse=True
    )[:10]
    new_stars_top = sorted(
        [r for r in repos if any("new-stars" in s for s in r.get("sources", []))],
        key=lambda r: r.get("stars", 0), reverse=True
    )[:10]
    focus_top = sorted(
        [r for r in repos if r.get("is_focus")],
        key=lambda r: r.get("hot_score", 0), reverse=True
    )[:15]
      # 合并去重，三个区域的项目都覆盖
    report_repos = {}
    for r in trending_top + new_stars_top + focus_top:
        report_repos[r["full_name"]] = r
    readme_cache = {}
    for r in report_repos.values():
        readme = fetch_readme(r["owner"], r["name"])
        if readme:
            readme_cache[r["full_name"]] = readme
    logger.info(f"Fetched {len(readme_cache)} READMEs for {len(report_repos)} report repos")

    # 7. 存储到数据库
    logger.info("Step 6: Saving to database...")
    save_daily_repos(repos, TODAY)

    # 8. 可选：LLM 深度分析（覆盖报告所有区域的项目）
    llm_analyses = {}
    trend_analysis = ""
    deepseek_key = os.getenv("DEEPSEEK_API_KEY", "")
    logger.info(f"Step 7: DEEPSEEK_API_KEY configured: {bool(deepseek_key)}, READMEs cached: {len(readme_cache)}")
    try:
        from src.processor.llm_summarize import summarize_project, analyze_trends
        if not deepseek_key:
            logger.info("LLM skipped: DEEPSEEK_API_KEY not configured in GitHub Secrets")
        elif not readme_cache:
            logger.warning("LLM skipped: no README content fetched (check GitHub API token)")
        else:
            logger.info(f"Running LLM deep analysis on {len(report_repos)} repos...")
            for full_name, r in report_repos.items():
                readme = readme_cache.get(full_name, "")
                if readme:
                    analysis = summarize_project(r, readme)
                    if analysis:
                        llm_analyses[full_name] = analysis
                    else:
                        logger.warning(f"LLM returned empty for {full_name}")
            if llm_analyses:
                trend_analysis = analyze_trends(repos, readme_cache) or ""
            logger.info(f"LLM analyzed {len(llm_analyses)} projects, trend_analysis: {bool(trend_analysis)}")
    except Exception as e:
        logger.warning(f"LLM analysis failed: {e}", exc_info=True)

    # 9. 生成 Markdown 日报
    logger.info("Step 8: Generating daily report...")
    md_content = generate_daily_report(repos, TODAY, readme_cache, llm_analyses, trend_analysis)
    daily_filename = f"daily-{TODAY}.md"
    report_path = save_report(md_content, daily_filename)
    logger.info(f"Daily report saved: {report_path}")

    # 10. 保存摘要
    save_daily_summary(TODAY, repos, report_path)

    # 11. 发送邮件
    logger.info("Step 9: Sending email...")
    html_content = markdown_to_html(md_content)
    subject = f"🚀 GitHub 每日热点 — {TODAY}"
    success = send_email(subject, html_content)
    if success:
        logger.info("Email sent successfully")
    else:
        logger.warning("Email sending failed (check .env config)")

    # 12. 如果是月初，生成月度报告
    if datetime.utcnow().day == 1:
        run_monthly()

    # 13. 清理旧数据
    logger.info("Step 10: Cleaning up old data...")
    cleanup_old_data()

    logger.info(f"=== Daily run complete: {TODAY} ===")


def run_monthly():
    """生成月度趋势分析报告"""
    logger.info("--- Generating monthly trend report ---")
    stats = get_monthly_stats()
    now = datetime.utcnow()
    # 上个月
    if now.month == 1:
        year, month = now.year - 1, 12
    else:
        year, month = now.year, now.month - 1

    md_content = generate_monthly_report(stats, year, month)
    monthly_filename = f"monthly-{year}-{month:02d}.md"
    report_path = save_report(md_content, monthly_filename)
    logger.info(f"Monthly report saved: {report_path}")

    # 推送月度邮件
    html_content = markdown_to_html(md_content)
    subject = f"📊 GitHub 月度趋势分析 — {year}年{month:02d}月"
    send_email(subject, html_content)


if __name__ == "__main__":
    run_daily()

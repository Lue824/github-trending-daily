"""
GitHub Trending Daily — 主入口
编排数据抓取 → 处理 → 存储 → 报告 → 推送全流程

支持两种运行模式：
- python src/main.py           → 传统日报（Markdown + 邮件推送）
- python src/main.py --web     → 启动 Flask Web 服务
"""
import logging
import sys
import os
from datetime import datetime, timedelta

# 确保 src 目录在路径中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.fetcher.trending import fetch_all_trending
from src.fetcher.search_api import fetch_all_api, fetch_readme
from src.fetcher.extra_api import fetch_extra_batch
from src.processor.dedup import deduplicate
from src.processor.categorize import classify_repos, sort_by_hotness, compute_hot_score
from src.processor.scoring import compute_all_scores
from src.storage.db import (
    init_db, save_daily_repos, save_daily_summary,
    mark_consecutive_streak, cleanup_old_data, get_monthly_stats,
    get_yesterday_section_ranks,
)
from src.reporter.markdown import (
    generate_daily_report, generate_monthly_report, save_report,
)
from src.reporter.daily_report import generate_6section_report, save_6section_report
from src.reporter.ai_report import generate_ai_report, save_ai_report
from src.reporter.custom_report import generate_custom_report
from src.processor.ai_scoring import compute_ai_scores, get_ai_section_repos
from src.processor.custom_parser import parse_query, generate_sections
from src.notifier.email_sender import send_email, markdown_to_html
from config import EMAIL_CONFIG, REPORTS_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")

TODAY = datetime.utcnow().strftime("%Y-%m-%d")
YESTERDAY = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")


def _fetch_and_process():
    """抓取和处理数据，返回处理好的 repos 和缓存"""
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
    repos = mark_consecutive_streak(repos, TODAY, YESTERDAY)

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
    yesterday_ranks = get_yesterday_section_ranks(YESTERDAY)
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
    save_daily_repos(repos, TODAY)

    # 10. LLM 深度分析
    llm_analyses = {}
    trend_analysis = ""
    deepseek_key = os.getenv("DEEPSEEK_API_KEY", "")
    try:
        from src.processor.llm_summarize import summarize_project, analyze_trends
        if deepseek_key and readme_cache:
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
    }


def _send_email_by_subscription(
    repos, readme_cache, llm_analyses, trend_analysis,
    yesterday_ranks, extra_cache,
):
    """根据 data/subscription.json 决定发送基础日报还是自定义日报

    - 无订阅文件 / type=basic → 发送基础 6 板块日报
    - type=custom → 用订阅的 topic/keywords/api_key 生成自定义日报并发送
    - 接收邮箱用订阅文件里的 email，无则用默认
    """
    import json
    sub_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "subscription.json")
    subscription = None
    if os.path.exists(sub_path):
        try:
            with open(sub_path, "r", encoding="utf-8") as f:
                subscription = json.load(f)
        except Exception as e:
            logger.warning(f"Failed to read subscription.json: {e}")

    # 确定接收邮箱
    original_receiver = EMAIL_CONFIG.get("receiver", "")
    if subscription and subscription.get("email"):
        EMAIL_CONFIG["receiver"] = subscription["email"]

    try:
        if subscription and subscription.get("type") == "custom":
            # 自定义日报
            topic = subscription.get("topic", "自定义")
            keywords = subscription.get("keywords", [])
            api_key = subscription.get("api_key", "")
            logger.info(f"Sending CUSTOM report: {topic} (keywords={keywords[:3]})")
            parsed = parse_query(topic, api_key)
            if not parsed.get("keywords"):
                parsed["keywords"] = keywords
            sections = generate_sections(parsed.get("topic", topic), parsed.get("keywords", []), api_key)
            basic_repos = sorted(repos, key=lambda r: r.get("hot_score", 0), reverse=True)[:30]
            html = generate_custom_report(repos, topic, parsed, sections, basic_repos=basic_repos)
            subject = f"🔧 GitHub 每日热点（自定义: {topic}）— {TODAY}"
        else:
            # 基础日报
            logger.info("Sending BASIC 6-section report")
            html = generate_6section_report(
                repos, TODAY, readme_cache, llm_analyses, trend_analysis,
                yesterday_ranks, YESTERDAY,
            )
            subject = f"🚀 GitHub 每日热点 — {TODAY}"

        success = send_email(subject, html)
        if success:
            logger.info(f"Email sent to {EMAIL_CONFIG['receiver']}")
        else:
            logger.warning("Email sending failed (check .env config)")
    finally:
        EMAIL_CONFIG["receiver"] = original_receiver


def run_daily():
    """每日主流程 — 生成传统日报 + 6板块日报 + 邮件推送"""
    logger.info(f"=== Starting daily run: {TODAY} ===")

    data = _fetch_and_process()
    if not data:
        return

    repos = data["repos"]
    readme_cache = data["readme_cache"]
    llm_analyses = data["llm_analyses"]
    trend_analysis = data["trend_analysis"]
    yesterday_ranks = data["yesterday_ranks"]
    extra_cache = data["extra_cache"]

    # ── 传统日报（兼容原有格式 + 邮件） ──────────────────
    logger.info("Step 9: Generating traditional Markdown report...")
    md_content = generate_daily_report(
        repos, TODAY, readme_cache, llm_analyses, trend_analysis,
        yesterday_ranks, YESTERDAY,
    )
    daily_filename = f"daily-{TODAY}.md"
    report_path = save_report(md_content, daily_filename)
    logger.info(f"Traditional report saved: {report_path}")

    # ── 6板块日报（HTML） ───────────────────────────────
    logger.info("Step 10: Generating 6-section report...")
    html_path = save_6section_report(
        generate_6section_report(
            repos, TODAY, readme_cache, llm_analyses, trend_analysis,
            yesterday_ranks, YESTERDAY,
        ),
        TODAY,
    )
    logger.info(f"6-section report saved: {html_path}")

    # ── AI 深度日报 ────────────────────────────────────
    logger.info("Step 10.5: Generating AI deep-dive report...")
    focus_repos = compute_ai_scores(repos, extra_cache)
    ai_sections = get_ai_section_repos(focus_repos)
    ai_html = generate_ai_report(focus_repos, ai_sections, TODAY)
    ai_path = save_ai_report(ai_html, TODAY)
    logger.info(f"AI report saved: {ai_path}")

    # ── 保存摘要 ───────────────────────────────────────
    save_daily_summary(TODAY, repos, report_path)

    # ── 发送邮件（根据订阅类型） ────────────────────
    logger.info("Step 11: Sending email based on subscription...")
    _send_email_by_subscription(
        repos, readme_cache, llm_analyses, trend_analysis,
        yesterday_ranks, extra_cache,
    )

    # ── 月初月报 ───────────────────────────────────────
    if datetime.utcnow().day == 1:
        run_monthly()

    # ── 清理旧数据 ─────────────────────────────────────
    logger.info("Step 12: Cleaning up old data...")
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
    if "--web" in sys.argv:
        from web.app import run_web
        port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 5000
        run_web(port=port, debug=False)
    else:
        run_daily()

"""
GitHub Trending Daily — 主入口
编排数据抓取 → 处理 → 存储 → 报告 → 推送全流程

支持三种运行模式：
- python src/main.py           → 6板块日报 + AI日报 + 邮件推送
- python src/main.py --web     → 启动 Flask Web 服务
"""
import logging
import sys
import os
from datetime import datetime, timedelta

# 确保 src 目录在路径中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.pipeline import run_pipeline
from src.storage.db import (
    save_daily_summary, cleanup_old_data, get_monthly_stats,
)
from src.reporter.markdown import generate_monthly_report, save_report
from src.reporter.daily_report import generate_6section_report, save_6section_report
from src.reporter.ai_report import generate_ai_report, save_ai_report
from src.processor.ai_scoring import compute_ai_scores, get_ai_section_repos
from src.notifier.email_sender import send_email, markdown_to_html

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")


def run_daily():
    """每日主流程 — 6板块日报 + AI日报 + 邮件推送"""
    logger.info("=== Starting daily run ===")

    data = run_pipeline()
    if not data:
        return

    repos = data["repos"]
    readme_cache = data["readme_cache"]
    llm_analyses = data["llm_analyses"]
    trend_analysis = data["trend_analysis"]
    yesterday_ranks = data["yesterday_ranks"]
    extra_cache = data["extra_cache"]
    TODAY = data["today"]
    YESTERDAY = data["yesterday"]

    # ── 6板块日报（HTML） ───────────────────────────────
    logger.info("Step 9: Generating 6-section report...")
    html_content = generate_6section_report(
        repos, TODAY, readme_cache, llm_analyses, trend_analysis,
        yesterday_ranks, YESTERDAY,
    )
    html_path = save_6section_report(html_content, TODAY)
    logger.info(f"6-section report saved: {html_path}")

    # ── AI 深度日报 ────────────────────────────────────
    logger.info("Step 9.5: Generating AI deep-dive report...")
    focus_repos = compute_ai_scores(repos, extra_cache)
    ai_sections = get_ai_section_repos(focus_repos)
    ai_html = generate_ai_report(focus_repos, ai_sections, TODAY,
                                 readme_cache, llm_analyses)
    ai_path = save_ai_report(ai_html, TODAY)
    logger.info(f"AI report saved: {ai_path}")

    # ── 保存摘要 ───────────────────────────────────────
    save_daily_summary(TODAY, repos, html_path)

    # ── 发送邮件 ───────────────────────────────────────
    logger.info("Step 10: Sending email...")
    subject = f"🚀 GitHub 每日热点 — {TODAY}"
    success = send_email(subject, html_content)
    if success:
        logger.info("Email sent successfully")
    else:
        logger.warning("Email sending failed (check .env config)")

    # ── 月初月报 ───────────────────────────────────────
    if datetime.utcnow().day == 1:
        run_monthly()

    # ── 清理旧数据 ──────────────────────────────────────
    logger.info("Step 11: Cleaning up old data...")
    cleanup_old_data()

    logger.info(f"=== Daily run complete: {TODAY} ===")


def run_monthly():
    """生成月度趋势分析报告"""
    logger.info("--- Generating monthly trend report ---")
    stats = get_monthly_stats()
    now = datetime.utcnow()
    if now.month == 1:
        year, month = now.year - 1, 12
    else:
        year, month = now.year, now.month - 1

    md_content = generate_monthly_report(stats, year, month)
    monthly_filename = f"monthly-{year}-{month:02d}.md"
    report_path = save_report(md_content, monthly_filename)
    logger.info(f"Monthly report saved: {report_path}")

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

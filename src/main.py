"""
GitRadar — 主入口
编排数据抓取 → 处理 → 存储 → 报告 → 推送全流程

支持三种运行模式：
- python src/main.py           → 6板块日报 + AI日报 + 邮件推送
- python src/main.py --web     → 启动 Flask Web 服务
"""
import logging
import sys
import os
from datetime import datetime, timezone

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
from src.reporter.email_template import wrap_html_for_email
from src.utils.crypto import decrypt_if_needed

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

    # ── 导出 JSON（供 HF Spaces 自定义查询用，HF 不允许二进制 db 文件） ──
    _export_repos_json(repos, TODAY)

    # ── 发送邮件 ───────────────────────────────────────
    logger.info("Step 10: Sending email...")
    subject = f"🚀 GitHub 每日热点 — {TODAY}"
    email_html = wrap_html_for_email(html_content)
    success = send_email(subject, email_html)
    if success:
        logger.info("Email sent successfully")
    else:
        logger.warning("Email sending failed (check .env config)")

    # ── 给订阅者群发 ───────────────────────────────────
    logger.info("Step 10.5: Sending subscription emails...")
    send_subscription_emails(repos, email_html, TODAY, readme_cache)

    # ── 月初月报 ───────────────────────────────────────
    if datetime.now(timezone.utc).day == 1:
        run_monthly()

    # ── 清理旧数据 ──────────────────────────────────────
    logger.info("Step 11: Cleaning up old data...")
    cleanup_old_data()

    logger.info(f"=== Daily run complete: {TODAY} ===")


def _export_repos_json(repos: list[dict], date_str: str):
    """导出仓库数据为 JSON（HF Spaces 不允许二进制 db 文件，用 JSON 替代）"""
    import json
    from config import DATA_DIR
    os.makedirs(DATA_DIR, exist_ok=True)
    json_path = os.path.join(DATA_DIR, "repos.json")
    # 序列化，去掉不可序列化的字段
    clean_repos = []
    for r in repos:
        clean = {}
        for k, v in r.items():
            if k.startswith("_") and k != "_extra":
                continue
            try:
                json.dumps(v)
                clean[k] = v
            except (TypeError, ValueError):
                clean[k] = str(v)
        clean_repos.append(clean)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"date": date_str, "repos": clean_repos}, f, ensure_ascii=False, indent=2)
    logger.info(f"Exported {len(clean_repos)} repos to {json_path}")


def send_subscription_emails(repos: list[dict], basic_html: str, date_str: str,
                              readme_cache: dict = None):
    """读取 subscription.json，给所有订阅者发送对应类型的日报邮件

    在每日 pipeline 中调用，不依赖 Web 服务在线。
    - basic 订阅：直接发送已生成的基础日报 HTML
    - custom 订阅：用存储的 topic/keywords 生成自定义日报后发送
    """
    import json
    from config import DATA_DIR

    sub_path = os.path.join(DATA_DIR, "subscription.json")
    if not os.path.exists(sub_path):
        logger.info("No subscription.json found, skipping subscription emails")
        return

    try:
        with open(sub_path, "r", encoding="utf-8") as f:
            subs = json.load(f)
    except Exception as e:
        logger.warning(f"Failed to read subscription.json: {e}")
        return

    # 兼容旧的单 dict 格式
    if isinstance(subs, dict):
        subs = [subs]
    if not isinstance(subs, list) or not subs:
        logger.info("No subscribers in subscription.json")
        return

    logger.info(f"Found {len(subs)} subscriber(s), sending emails...")
    sent, failed = 0, 0

    for sub in subs:
        email = decrypt_if_needed(sub.get("email", "")).strip()
        sub_type = sub.get("type", "basic")
        if not email:
            continue

        try:
            if sub_type == "basic":
                subject = f"🚀 GitHub 每日热点（基础日报）— {date_str}"
                html = basic_html
            else:
                # 自定义订阅：生成专属日报
                from src.processor.custom_parser import parse_query, generate_sections
                from src.reporter.custom_report import generate_custom_report
                topic = sub.get("topic", "自定义")
                keywords = sub.get("keywords", [])
                api_key = decrypt_if_needed(sub.get("api_key", ""))
                provider = sub.get("provider", "")
                parsed = parse_query(topic, api_key, provider)
                if not parsed.get("keywords"):
                    parsed["keywords"] = keywords
                sections = generate_sections(parsed.get("topic", topic),
                                             parsed.get("keywords", []),
                                             api_key, provider)
                basic_repos = sorted(repos, key=lambda r: r.get("hot_score", 0), reverse=True)[:30]
                html = generate_custom_report(repos, topic, parsed, sections,
                                              basic_repos=basic_repos,
                                              api_key=api_key, provider=provider)
                html = wrap_html_for_email(html)
                subject = f"🔧 GitHub 每日热点（自定义: {topic}）— {date_str}"

            ok = send_email(subject, html, receiver=email)
            if ok:
                sent += 1
            else:
                failed += 1
        except Exception as e:
            logger.warning(f"Subscription email failed for {email[:2]}***: {e}")
            failed += 1

    logger.info(f"Subscription emails done: {sent} sent, {failed} failed")


def run_monthly():
    """生成月度趋势分析报告"""
    logger.info("--- Generating monthly trend report ---")
    stats = get_monthly_stats()
    now = datetime.now(timezone.utc)
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
        port = 5000
        if "--port" in sys.argv:
            idx = sys.argv.index("--port")
            if idx + 1 < len(sys.argv):
                port = int(sys.argv[idx + 1])
        run_web(port=port, debug=False)
    else:
        run_daily()

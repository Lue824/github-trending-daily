"""
Flask Web 服务

提供三种模式：
- 基础日报（6板块）
- AI 深度（AI/ML垂类）
- 自定义查询（初赛后实现）
"""
import os
import sys
import logging
import json
from datetime import datetime, timedelta
from functools import lru_cache

from flask import Flask, render_template_string, request, jsonify, send_from_directory

# 确保 src 目录在路径中
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _BASE_DIR)

from src.fetcher.trending import fetch_all_trending
from src.fetcher.search_api import fetch_all_api, fetch_readme
from src.fetcher.extra_api import fetch_extra_batch
from src.processor.dedup import deduplicate
from src.processor.categorize import classify_repos, compute_hot_score, sort_by_hotness
from src.processor.scoring import compute_all_scores
from src.processor.custom_parser import parse_query, generate_sections
from src.reporter.custom_report import generate_custom_report
from src.storage.db import init_db, save_daily_repos, mark_consecutive_streak, get_yesterday_section_ranks
from src.reporter.daily_report import generate_6section_report

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("web")

app = Flask(__name__, static_folder=None)

# 绝对路径模板
_INDEX_HTML = os.path.join(os.path.dirname(__file__), "templates", "index.html")
_REPORT_DIR = os.path.join(_BASE_DIR, "data", "reports")

if not os.path.exists(_REPORT_DIR):
    os.makedirs(_REPORT_DIR)


# ════════════════════════════════════════════════════════════
# 缓存
# ════════════════════════════════════════════════════════════
_cached_report: dict = {"content": "", "date": "", "repos": [], "meta": {}}


def _run_pipeline(date_str: str = None):
    """运行完整数据流水线，返回报告 HTML"""
    global _cached_report

    today = date_str or datetime.utcnow().strftime("%Y-%m-%d")
    yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")

    # 缓存检查
    if _cached_report["date"] == today and _cached_report["content"]:
        return _cached_report

    init_db()

    # 抓取
    logger.info("Fetching data...")
    trending_repos = fetch_all_trending()
    api_repos = fetch_all_api()
    all_raw = trending_repos + api_repos
    logger.info(f"Fetched {len(all_raw)} raw repos")

    if not all_raw:
        return {"content": "<p>暂无数据，请稍后刷新</p>", "date": today, "repos": [], "meta": {}}

    # 去重 + 分类
    repos = deduplicate(all_raw)
    repos = classify_repos(repos)
    for r in repos:
        r["hot_score"] = compute_hot_score(r)
    repos = sort_by_hotness(repos)

    # 标记连续在榜
    repos = mark_consecutive_streak(repos, today, yesterday)

    # 获取额外数据（健康度）— 无 Token 则跳过，避免 API 限流导致崩溃
    extra_cache = {}
    if os.getenv("GITHUB_TOKEN", ""):
        logger.info("Fetching extra health data...")
        extra_cache = fetch_extra_batch(repos)
    else:
        logger.info("Skipping extra health data (no GITHUB_TOKEN)")

    # 计算6板块评分
    repos = compute_all_scores(repos, extra_cache)

    # 将 extra 数据挂到 repo 上
    for r in repos:
        r["_extra"] = extra_cache.get(r["full_name"], {})

    # 获取 README（仅 TOP 项目）
    report_repos = {}
    for section_repos, n in [
        ([r for r in repos if r["burst_score"] > 0], 10),
        ([r for r in repos if r["quality_score"] >= 0.3], 10),
        ([r for r in repos if r["ai_radar_score"] > 0], 10),
    ]:
        for r in section_repos[:n]:
            report_repos[r["full_name"]] = r

    readme_cache = {}
    for r in list(report_repos.values())[:20]:
        readme = fetch_readme(r["owner"], r["name"])
        if readme:
            readme_cache[r.get("full_name", f"{r['owner']}/{r['name']}")] = readme

    # 昨日排名
    yesterday_ranks = get_yesterday_section_ranks(yesterday)

    # LLM 分析
    llm_analyses = {}
    trend_analysis = ""
    try:
        from src.processor.llm_summarize import summarize_project, analyze_trends
        deepseek_key = os.getenv("DEEPSEEK_API_KEY", "")
        if deepseek_key and readme_cache:
            for full_name, r in report_repos.items():
                readme = readme_cache.get(full_name, "")
                if readme:
                    analysis = summarize_project(r, readme)
                    if analysis:
                        llm_analyses[full_name] = analysis
            if llm_analyses:
                trend_analysis = analyze_trends(repos, readme_cache) or ""
    except Exception as e:
        logger.warning(f"LLM analysis failed: {e}")

    # 保存到数据库
    save_daily_repos(repos, today)

    # 生成报告
    report_html = generate_6section_report(
        repos, today, readme_cache, llm_analyses, trend_analysis,
        yesterday_ranks, yesterday,
    )

    # 保存文件
    from src.reporter.daily_report import save_6section_report
    save_6section_report(report_html, today)

    _cached_report = {
        "content": report_html,
        "date": today,
        "repos": repos,
        "meta": {
            "total": len(repos),
            "focus": sum(1 for r in repos if r.get("is_focus")),
            "burst": sum(1 for r in repos if r.get("burst_score", 0) > 0),
            "traps": sum(1 for r in repos if r.get("is_trap")),
        },
    }

    return _cached_report


# ════════════════════════════════════════════════════════════
# Routes
# ════════════════════════════════════════════════════════════

@app.route("/")
def index():
    """主页面 — 立即返回框架，前端异步加载数据"""
    html = _render_index("basic", "")
    return html


@app.route("/api/daily")
def api_daily():
    """异步获取日报数据 — 优先读预生成文件（秒开），无则实时抓取"""
    import glob
    # 优先读取预生成的 6 板块日报（云端部署避免超时）
    report_files = sorted(glob.glob(os.path.join(_REPORT_DIR, "daily-6s-*.html")), reverse=True)
    if report_files:
        try:
            with open(report_files[0], "r", encoding="utf-8") as f:
                html = f.read()
            date_str = os.path.basename(report_files[0]).replace("daily-6s-", "").replace(".html", "")
            # 不再触发 _run_pipeline（避免每次访问都跑完整抓取导致超时）
            # 自定义查询需要 repos 时，由 /api/custom 按需触发
            return jsonify({"date": date_str, "html": html})
        except Exception as e:
            logger.warning(f"Failed to read pre-generated report: {e}, falling back to live fetch")
    # 降级：实时抓取（仅在无预生成文件时）
    try:
        report = _run_pipeline()
        return jsonify({"date": report["date"], "html": report["content"]})
    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        return jsonify({"date": datetime.utcnow().strftime("%Y-%m-%d"),
                        "html": f'<p style="color:var(--accent-red);text-align:center;padding:40px">数据加载失败：{e}<br>请检查网络连接后点击刷新按钮重试</p>'}), 500


@app.route("/api/refresh")
def api_refresh():
    """强制刷新数据"""
    global _cached_report
    _cached_report = {"content": "", "date": "", "repos": [], "meta": {}}
    report = _run_pipeline()
    return jsonify({"ok": True, "date": report["date"]})


@app.route("/api/custom", methods=["GET", "POST"])
def api_custom():
    """自定义话题日报 — 解析查询 + 匹配仓库 + 生成报告

    支持用户传入自己的 LLM API Key + provider（个人化，不消耗项目方额度）
    兼容多家厂商：deepseek/openai/anthropic/qwen/zhipu/moonshot
    """
    data = request.json or {}
    query = (data.get("query", "") or request.args.get("query", "")).strip()
    api_key = (data.get("api_key", "") or "").strip()  # 用户自己的 key（可选）
    provider = (data.get("provider", "") or "").strip()  # 厂商（可选，自动识别）
    if not query:
        return jsonify({"html": '<p style="color:var(--text-dim);text-align:center;padding:40px">'
                                '请输入话题关键词，例如：量化交易、AI Agent、游戏引擎</p>', "topic": ""})

    # 确保有数据
    global _cached_report
    if not _cached_report.get("repos"):
        try:
            _run_pipeline()
        except Exception as e:
            return jsonify({"html": f'<p style="color:var(--accent-red)">数据加载失败: {e}</p>', "topic": query}), 500

    repos = _cached_report.get("repos", [])
    if not repos:
        return jsonify({"html": '<p style="color:var(--text-dim)">暂无数据，请先刷新基础日报</p>', "topic": query})

    try:
        # 4 层防御解析（用用户自己的 key，不消耗项目方额度）
        parsed = parse_query(query, api_key, provider)
        sections = generate_sections(parsed.get("topic", query), parsed.get("keywords", []), api_key, provider)
        # 基础模块热门项目作为补充源（项目不足时去重补充）
        basic_repos = sorted(repos, key=lambda r: r.get("hot_score", 0), reverse=True)[:30]
        html = generate_custom_report(repos, query, parsed, sections, basic_repos=basic_repos)
        return jsonify({
            "html": html,
            "topic": parsed.get("topic", query),
            "keywords": parsed.get("keywords", []),
            "source": parsed.get("source", ""),
            "used_llm": parsed.get("source") == "llm",
        })
    except Exception as e:
        logger.error(f"Custom report failed: {e}", exc_info=True)
        return jsonify({"html": f'<p style="color:var(--accent-red)">生成失败: {e}</p>', "topic": query}), 500


@app.route("/api/subscribe", methods=["POST"])
def api_subscribe():
    """订阅每日推送 — 记录用户选择到 subscription.json，并立即发送一封邮件

    请求体: {
        "type": "basic" | "custom",
        "email": "user@example.com",
        "topic": "量化交易",        # type=custom 时必填
        "keywords": ["trading"],    # type=custom 时必填
        "api_key": "sk-xxx"         # type=custom 时必填（用户自己的 key）
    }
    """
    data = request.json or {}
    sub_type = data.get("type", "basic")
    email = (data.get("email", "") or "").strip()
    if not email:
        return jsonify({"ok": False, "msg": "请输入接收邮箱"}), 400

    if sub_type not in ("basic", "custom"):
        return jsonify({"ok": False, "msg": "type 必须是 basic 或 custom"}), 400

    subscription = {
        "type": sub_type,
        "email": email,
        "updated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
    }

    if sub_type == "custom":
        topic = data.get("topic", "").strip()
        keywords = data.get("keywords", [])
        api_key = (data.get("api_key", "") or "").strip()
        provider = (data.get("provider", "") or "").strip()
        if not topic or not keywords:
            return jsonify({"ok": False, "msg": "自定义订阅需要 topic 和 keywords"}), 400
        subscription["topic"] = topic
        subscription["keywords"] = keywords
        subscription["api_key"] = api_key  # 存仓库文件（用户选择）
        subscription["provider"] = provider

    # 持久化到 data/subscription.json
    sub_path = os.path.join(_BASE_DIR, "data", "subscription.json")
    try:
        with open(sub_path, "w", encoding="utf-8") as f:
            json.dump(subscription, f, ensure_ascii=False, indent=2)
        logger.info(f"Subscription saved: {sub_type} -> {email}")
    except Exception as e:
        return jsonify({"ok": False, "msg": f"保存订阅失败: {e}"}), 500

    # 立即发送一封当前类型的日报邮件
    try:
        send_subscription_email(subscription)
        return jsonify({"ok": True, "msg": f"订阅成功！已发送{('自定义' if sub_type == 'custom' else '基础')}日报到 {email}", "subscription": subscription})
    except Exception as e:
        logger.error(f"Send subscription email failed: {e}", exc_info=True)
        return jsonify({"ok": True, "msg": f"订阅已保存，但邮件发送失败: {e}（定时任务会正常推送）", "subscription": subscription})


def send_subscription_email(subscription: dict):
    """根据订阅类型发送对应日报邮件"""
    from src.notifier.email_sender import send_email
    from config import EMAIL_CONFIG

    global _cached_report
    email = subscription["email"]
    sub_type = subscription["type"]
    # 临时覆盖接收人
    original_receiver = EMAIL_CONFIG.get("receiver", "")
    EMAIL_CONFIG["receiver"] = email
    try:
        if sub_type == "basic":
            # 发送基础 6 板块日报
            if not _cached_report.get("content"):
                _run_pipeline()
            html = _cached_report.get("content", "")
            if not html:
                # 降级读预生成文件
                import glob
                files = sorted(glob.glob(os.path.join(_REPORT_DIR, "daily-6s-*.html")), reverse=True)
                if files:
                    with open(files[0], "r", encoding="utf-8") as f:
                        html = f.read()
            subject = f"🚀 GitHub 每日热点（基础日报）— {datetime.utcnow().strftime('%Y-%m-%d')}"
            send_email(subject, html)
        else:
            # 发送自定义日报
            topic = subscription.get("topic", "自定义")
            keywords = subscription.get("keywords", [])
            api_key = subscription.get("api_key", "")
            provider = subscription.get("provider", "")
            repos = _cached_report.get("repos", [])
            if not repos:
                _run_pipeline()
                repos = _cached_report.get("repos", [])
            parsed = parse_query(topic, api_key, provider)
            if not parsed.get("keywords"):
                parsed["keywords"] = keywords
            sections = generate_sections(parsed.get("topic", topic), parsed.get("keywords", []), api_key, provider)
            basic_repos = sorted(repos, key=lambda r: r.get("hot_score", 0), reverse=True)[:30]
            html = generate_custom_report(repos, topic, parsed, sections, basic_repos=basic_repos)
            subject = f"🔧 GitHub 每日热点（自定义: {topic}）— {datetime.utcnow().strftime('%Y-%m-%d')}"
            send_email(subject, html)
    finally:
        EMAIL_CONFIG["receiver"] = original_receiver


@app.route("/reports/<path:filename>")
def serve_report(filename):
    """提供历史报告文件"""
    return send_from_directory(_REPORT_DIR, filename)


def _render_index(mode: str = "basic", report_content: str = "") -> str:
    """渲染主页面"""
    tabs = [
        {"id": "basic", "label": "📊 基础日报", "desc": "6板块多维评价"},
        {"id": "custom", "label": "🔧 自定义", "desc": "输入话题生成专属日报"},
    ]
    tabs_html = ""
    for t in tabs:
        active = "active" if t["id"] == mode else ""
        tabs_html += (
            f'<button class="tab {active}" onclick="switchTab(\'{t["id"]}\')" '
            f'data-tab="{t["id"]}">'
            f'{t["label"]}<br><small>{t["desc"]}</small>'
            f'</button>'
        )

    custom_placeholder = """
    <div style="padding:30px 20px;">
        <div style="text-align:center;margin-bottom:20px;color:var(--text-dim)">
            <p style="font-size:1.1em;margin-bottom:8px">🔧 自定义话题日报</p>
            <p>输入你关注的话题，AI 将生成专属日报（支持 32 个话题模板 + LLM 动态解析）<br>
            <small style="color:var(--accent)">💡 AI/ML 相关话题（如「大模型」「AI Agent」）会调用 AI 垂类评分引擎，深度分析模型权重、Agent工具链、数据评测等维度</small></p>
        </div>
        <div style="max-width:600px;margin:0 auto 16px;">
            <details style="background:var(--bg-card);border:1px solid var(--border);border-radius:8px;padding:8px 12px;">
                <summary style="cursor:pointer;color:var(--text-dim);font-size:0.85em">🔑 LLM API Key（可选，填了可用 LLM 解析冷门话题，用你自己的额度）</summary>
                <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap;align-items:center">
                    <label style="color:var(--text-dim);font-size:0.85em;min-width:60px">厂商</label>
                    <select id="customProvider" style="padding:6px 10px;border-radius:6px;border:1px solid var(--border);background:var(--bg);color:var(--text);font-size:0.85em"
                            onchange="localStorage.setItem('llm_provider', this.value)">
                        <option value="deepseek">DeepSeek</option>
                        <option value="openai">OpenAI</option>
                        <option value="anthropic">Anthropic Claude</option>
                        <option value="qwen">通义千问</option>
                        <option value="zhipu">智谱清言</option>
                        <option value="moonshot">Moonshot Kimi</option>
                    </select>
                </div>
                <input type="password" id="customApiKey" placeholder="sk-xxxx...（留空则只用规则匹配，不消耗任何额度）"
                       style="width:100%;margin-top:8px;padding:8px 12px;border-radius:6px;border:1px solid var(--border);
                              background:var(--bg);color:var(--text);font-size:0.85em"
                       oninput="localStorage.setItem('llm_api_key', this.value)">
                <p style="color:var(--text-dim);font-size:0.75em;margin-top:6px;margin-bottom:0">
                    💡 填了 key 后浏览器会自动记住，下次访问无需重新填写。支持 DeepSeek/OpenAI/Claude/通义/智谱/Kimi。
                </p>
            </details>
        </div>
        <div style="max-width:600px;margin:0 auto;display:flex;gap:8px;flex-wrap:wrap;justify-content:center">
            <input type="text" id="customQuery" placeholder="例如：量化交易、AI Agent、游戏引擎、金融..."
                   style="flex:1;min-width:240px;padding:10px 16px;border-radius:8px;border:1px solid var(--border);
                          background:var(--bg-card);color:var(--text);font-size:0.95em"
                   onkeypress="if(event.key==='Enter')submitCustom()">
            <button onclick="submitCustom()" style="padding:10px 24px;border-radius:8px;
                           background:var(--accent);color:#fff;border:none;cursor:pointer;font-size:0.95em">
                🔍 生成日报
            </button>
        </div>
        <div style="max-width:600px;margin:16px auto 0;text-align:center">
            <small style="color:var(--text-dim)">快捷话题：</small>
            <span style="margin-left:8px">
                <a href="javascript:void(0)" onclick="quickSearch('AI Agent')" style="color:var(--accent);margin-right:8px">AI Agent</a>
                <a href="javascript:void(0)" onclick="quickSearch('量化交易')" style="color:var(--accent);margin-right:8px">量化交易</a>
                <a href="javascript:void(0)" onclick="quickSearch('大模型')" style="color:var(--accent);margin-right:8px">大模型</a>
                <a href="javascript:void(0)" onclick="quickSearch('游戏开发')" style="color:var(--accent);margin-right:8px">游戏开发</a>
                <a href="javascript:void(0)" onclick="quickSearch('Rust生态')" style="color:var(--accent)">Rust生态</a>
            </span>
        </div>
        <div id="customResult" style="margin-top:20px"></div>
    </div>
    <div id="subscribeModal" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.7);z-index:1000;justify-content:center;align-items:center">
        <div style="background:var(--bg-card);border:1px solid var(--border);border-radius:12px;padding:30px;max-width:440px;width:90%;box-shadow:0 8px 32px rgba(0,0,0,0.4)">
            <h3 style="margin:0 0 16px;color:var(--text)">📬 订阅每日推送</h3>
            <p style="color:var(--text-dim);font-size:0.9em;margin-bottom:20px">选择你想要每天接收的日报类型，立即发送一封到你的邮箱：</p>
            <div style="display:flex;gap:12px;margin-bottom:20px">
                <label style="flex:1;display:flex;align-items:center;gap:8px;padding:12px;border:1px solid var(--border);border-radius:8px;cursor:pointer" onmouseover="this.style.borderColor='var(--accent)'" onmouseout="this.style.borderColor='var(--border)'">
                    <input type="radio" name="subType" value="custom" checked style="accent-color:var(--accent)">
                    <span style="color:var(--text);font-size:0.9em">🔧 自定义日报<br><small style="color:var(--text-dim)" id="subCustomTopic">当前话题</small></span>
                </label>
                <label style="flex:1;display:flex;align-items:center;gap:8px;padding:12px;border:1px solid var(--border);border-radius:8px;cursor:pointer" onmouseover="this.style.borderColor='var(--accent)'" onmouseout="this.style.borderColor='var(--border)'">
                    <input type="radio" name="subType" value="basic" style="accent-color:var(--accent)">
                    <span style="color:var(--text);font-size:0.9em">📊 基础日报<br><small style="color:var(--text-dim)">6板块综合</small></span>
                </label>
            </div>
            <input type="email" id="subEmail" placeholder="你的接收邮箱（如 xxx@qq.com）"
                   style="width:100%;padding:10px 14px;border-radius:8px;border:1px solid var(--border);background:var(--bg);color:var(--text);font-size:0.95em;margin-bottom:16px;box-sizing:border-box">
            <div style="display:flex;gap:8px;justify-content:flex-end">
                <button onclick="closeSubscribeModal()" style="padding:8px 20px;border-radius:8px;border:1px solid var(--border);background:var(--bg);color:var(--text-dim);cursor:pointer">取消</button>
                <button onclick="confirmSubscribe()" style="padding:8px 20px;border-radius:8px;border:none;background:var(--accent);color:#fff;cursor:pointer">立即订阅</button>
            </div>
            <div id="subMsg" style="margin-top:12px;font-size:0.85em;text-align:center"></div>
        </div>
    </div>
    """

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>GitHub 每日热点</title>
<style>
:root {{
    --bg: #0d1117;
    --bg-card: #161b22;
    --border: #30363d;
    --text: #c9d1d9;
    --text-dim: #8b949e;
    --accent: #58a6ff;
    --accent-green: #3fb950;
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
}}
.top-bar {{
    background: var(--bg-card);
    border-bottom: 1px solid var(--border);
    padding: 12px 20px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 12px;
}}
.top-bar h1 {{ font-size: 1.2em; }}
.top-bar .actions {{
    display: flex;
    gap: 8px;
    align-items: center;
}}
.tab-bar {{
    display: flex;
    gap: 4px;
    padding: 12px 20px;
    background: var(--bg);
    border-bottom: 1px solid var(--border);
}}
.tab {{
    padding: 8px 16px;
    border: 1px solid var(--border);
    background: var(--bg);
    color: var(--text-dim);
    border-radius: 8px;
    cursor: pointer;
    font-size: 0.82em;
    text-align: center;
    transition: all 0.2s;
    line-height: 1.3;
}}
.tab:hover {{ border-color: var(--accent); color: var(--text); }}
.tab.active {{
    background: var(--accent);
    color: #fff;
    border-color: var(--accent);
}}
.tab small {{ font-size: 0.75em; opacity: 0.7; }}
.content-area {{
    padding: 20px;
}}
.spinner {{
    display: none;
    text-align: center;
    padding: 40px;
    color: var(--text-dim);
}}
.spinner.show {{ display: block; }}
.spinner::after {{
    content: "";
    display: inline-block;
    width: 24px;
    height: 24px;
    border: 3px solid var(--border);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
    vertical-align: middle;
    margin-right: 8px;
}}
@keyframes spin {{ to {{ transform: rotate(360deg); }} }}
.toast {{
    position: fixed;
    top: 20px;
    right: 20px;
    padding: 10px 20px;
    border-radius: 8px;
    background: var(--accent-green);
    color: #fff;
    font-size: 0.85em;
    opacity: 0;
    transition: opacity 0.3s;
    z-index: 999;
}}
.toast.show {{ opacity: 1; }}
.btn {{
    padding: 6px 14px;
    border-radius: 6px;
    border: 1px solid var(--border);
    background: var(--bg-card);
    color: var(--text);
    cursor: pointer;
    font-size: 0.85em;
    transition: all 0.2s;
}}
.btn:hover {{ border-color: var(--accent); }}
.btn-primary {{
    background: var(--accent);
    color: #fff;
    border-color: var(--accent);
}}
.btn-primary:hover {{ opacity: 0.9; }}
</style>
</head>
<body>
<div class="top-bar">
        <div style="display:flex;align-items:center;gap:12px">
            <span class="brand-icon">🚀</span>
            <h1 style="font-size:1.4em;margin:0;color:var(--text)">GitHub 每日热点</h1>
            <span style="color:var(--text-dim);font-size:0.8em">基础日报 + 自定义话题</span>
        </div>
    <div class="actions">
        <span id="reportDate" style="color:var(--text-dim);font-size:0.85em"></span>
        <button class="btn btn-primary" onclick="refreshData()">🔄 刷新数据</button>
    </div>
</div>
<div class="tab-bar">
    {tabs_html}
</div>
<div id="spinner" class="spinner">加载中...</div>
<div id="toast" class="toast">刷新成功</div>
<div id="content" class="content-area">
    {report_content}
</div>

<script>
let currentMode = 'basic';

function switchTab(mode) {{
    currentMode = mode;
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelector(`[data-tab="${{mode}}"]`).classList.add('active');

    if (mode === 'basic') {{
        showSpinner();
        fetch('/api/daily')
            .then(r => r.json())
            .then(data => {{
                document.getElementById('content').innerHTML = data.html;
                document.getElementById('reportDate').textContent = '📅 ' + data.date;
                hideSpinner();
            }})
            .catch(e => {{
                document.getElementById('content').innerHTML = '<p style="color:#f85149">加载失败: ' + e + '</p>';
                hideSpinner();
            }});
    }} else if (mode === 'custom') {{
        document.getElementById('content').innerHTML = `{custom_placeholder}`;
        var apiKeyInput = document.getElementById('customApiKey');
        var providerSelect = document.getElementById('customProvider');
        if (apiKeyInput) {{
            // 兼容旧 key 名 ds_api_key
            apiKeyInput.value = localStorage.getItem('llm_api_key') || localStorage.getItem('ds_api_key') || '';
        }}
        if (providerSelect) {{
            providerSelect.value = localStorage.getItem('llm_provider') || 'deepseek';
        }}
    }}
}}

function submitCustom() {{
    var q = document.getElementById('customQuery').value.trim();
    if (!q) {{ alert('请输入话题关键词'); return; }}
    var apiKey = localStorage.getItem('llm_api_key') || localStorage.getItem('ds_api_key') || '';
    var provider = localStorage.getItem('llm_provider') || 'deepseek';
    var resultDiv = document.getElementById('customResult');
    resultDiv.innerHTML = '<p style="text-align:center;color:var(--text-dim);padding:30px">🔍 正在解析「' + q + '」并生成日报...</p>';
    fetch('/api/custom', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{query: q, api_key: apiKey, provider: provider}})
    }})
    .then(r => r.json())
    .then(data => {{
        resultDiv.innerHTML = data.html;
        if (data.topic) {{
            document.getElementById('reportDate').textContent = '🔧 ' + data.topic;
            lastCustomTopic = data.topic;
            lastCustomKeywords = data.keywords || [];
            showSubscribeModal(data.topic);
        }}
    }})
    .catch(e => {{
        resultDiv.innerHTML = '<p style="color:#f85149">生成失败: ' + e + '</p>';
    }});
}}

function quickSearch(topic) {{
    var input = document.getElementById('customQuery');
    if (input) {{ input.value = topic; submitCustom(); }}
}}

var lastCustomTopic = '';
var lastCustomKeywords = [];

function showSubscribeModal(topic) {{
    var modal = document.getElementById('subscribeModal');
    if (!modal) return;
    var topicSpan = document.getElementById('subCustomTopic');
    if (topicSpan) topicSpan.textContent = topic || '当前话题';
    modal.style.display = 'flex';
}}

function closeSubscribeModal() {{
    var modal = document.getElementById('subscribeModal');
    if (modal) modal.style.display = 'none';
    var msg = document.getElementById('subMsg');
    if (msg) msg.innerHTML = '';
}}

function confirmSubscribe() {{
    var typeEl = document.querySelector('input[name="subType"]:checked');
    var type = typeEl ? typeEl.value : 'custom';
    var email = document.getElementById('subEmail').value.trim();
    if (!email) {{ alert('请输入接收邮箱'); return; }}
    var msg = document.getElementById('subMsg');
    msg.innerHTML = '<span style="color:var(--text-dim)">发送中...</span>';
    var body = {{ type: type, email: email }};
    if (type === 'custom') {{
        body.topic = lastCustomTopic;
        body.keywords = lastCustomKeywords;
        body.api_key = localStorage.getItem('llm_api_key') || localStorage.getItem('ds_api_key') || '';
        body.provider = localStorage.getItem('llm_provider') || 'deepseek';
    }}
    fetch('/api/subscribe', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify(body)
    }})
    .then(r => r.json())
    .then(data => {{
        if (data.ok) {{
            msg.innerHTML = '<span style="color:var(--accent-green)">✅ ' + data.msg + '</span>';
            setTimeout(closeSubscribeModal, 3000);
        }} else {{
            msg.innerHTML = '<span style="color:var(--accent-red)">❌ ' + data.msg + '</span>';
        }}
    }})
    .catch(e => {{
        msg.innerHTML = '<span style="color:var(--accent-red)">❌ 订阅失败: ' + e + '</span>';
    }});
}}

function refreshData() {{
    showSpinner();
    fetch('/api/refresh')
        .then(r => r.json())
        .then(() => fetch('/api/daily').then(r => r.json()))
        .then(data => {{
            document.getElementById('content').innerHTML = data.html;
            document.getElementById('reportDate').textContent = '📅 ' + data.date;
            hideSpinner();
            showToast();
        }})
        .catch(e => {{
            hideSpinner();
            alert('刷新失败: ' + e);
        }});
}}

function showSpinner() {{
    document.getElementById('spinner').classList.add('show');
    document.getElementById('content').style.opacity = '0.3';
}}
function hideSpinner() {{
    document.getElementById('spinner').classList.remove('show');
    document.getElementById('content').style.opacity = '1';
}}
function showToast() {{
    const t = document.getElementById('toast');
    t.classList.add('show');
    setTimeout(() => t.classList.remove('show'), 2000);
}}

// 初始化 — 自动加载数据
document.addEventListener('DOMContentLoaded', function() {{
    var dateMatch = document.title.match(/\\d{{4}}年\\d{{2}}月\\d{{2}}日/);
    if (dateMatch) document.getElementById('reportDate').textContent = '📅 ' + dateMatch[0];
    showSpinner();
    fetch('/api/daily')
        .then(function(r) {{ return r.json(); }})
        .then(function(data) {{
            document.getElementById('content').innerHTML = data.html;
            document.getElementById('reportDate').textContent = '📅 ' + data.date;
            hideSpinner();
        }})
        .catch(function(e) {{
            document.getElementById('content').innerHTML = '<p style="color:var(--accent-orange);text-align:center;padding:40px">数据加载中，请稍候或点击刷新按钮重试...</p>';
            hideSpinner();
        }});
}});
</script>
</body>
</html>"""


def run_web(host: str = "0.0.0.0", port: int = 5000, debug: bool = False):
    """启动 Web 服务（0.0.0.0 允许局域网访问）"""
    logger.info(f"Starting web server on http://{host}:{port}")
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    run_web(debug=True)

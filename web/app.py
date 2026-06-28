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
import secrets
from datetime import datetime, timezone
from flask import Flask, request, jsonify, send_from_directory

# 确保 src 目录在路径中
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BASE_DIR)

from src.processor.custom_parser import parse_query, generate_sections
from src.reporter.custom_report import generate_custom_report
from src.storage.db import get_today_repos
from src.reporter.daily_report import generate_6section_report
from src.utils.crypto import encrypt_if_needed, decrypt_if_needed
from config import REPORTS_DIR, DATA_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("web")

app = Flask(__name__, static_folder=None)

# 使用 config.REPORTS_DIR（支持环境变量配置，HF Spaces 用 /data）
_REPORT_DIR = REPORTS_DIR

if not os.path.exists(_REPORT_DIR):
    os.makedirs(_REPORT_DIR, exist_ok=True)


# ── /api/custom 缓存 + 限流（轻量内存实现，不引入新依赖）──
import threading
import time as _time

_CUSTOM_CACHE_LOCK = threading.Lock()
_CUSTOM_CACHE: dict = {}  # key: (query, has_key, provider) -> (html, payload, expire_at)
_CUSTOM_CACHE_TTL = 600  # 10 分钟
_CUSTOM_CACHE_MAXSIZE = 100

_RATE_LIMIT_LOCK = threading.Lock()
_RATE_LIMIT: dict = {}  # ip -> [timestamps...]
_RATE_LIMIT_WINDOW = 60  # 60 秒
_RATE_LIMIT_MAX = 5  # 每 IP 每分钟最多 5 次 /api/custom


def _cache_get(key):
    """从缓存读取，过期自动失效"""
    with _CUSTOM_CACHE_LOCK:
        entry = _CUSTOM_CACHE.get(key)
        if not entry:
            return None
        html, payload, expire_at = entry
        if _time.time() > expire_at:
            _CUSTOM_CACHE.pop(key, None)
            return None
        return payload


def _cache_set(key, payload):
    """写入缓存，超过 maxsize 时淘汰最旧条目"""
    with _CUSTOM_CACHE_LOCK:
        if len(_CUSTOM_CACHE) >= _CUSTOM_CACHE_MAXSIZE:
            # 淘汰最早过期的一条
            if _CUSTOM_CACHE:
                oldest_key = min(_CUSTOM_CACHE, key=lambda k: _CUSTOM_CACHE[k][2])
                _CUSTOM_CACHE.pop(oldest_key, None)
        _CUSTOM_CACHE[key] = ("", payload, _time.time() + _CUSTOM_CACHE_TTL)


def _check_rate_limit(ip: str) -> tuple[bool, int]:
    """检查 IP 速率限制，返回 (允许, 剩余次数)"""
    now = _time.time()
    with _RATE_LIMIT_LOCK:
        timestamps = _RATE_LIMIT.get(ip, [])
        # 清理过期记录
        timestamps = [t for t in timestamps if now - t < _RATE_LIMIT_WINDOW]
        if len(timestamps) >= _RATE_LIMIT_MAX:
            _RATE_LIMIT[ip] = timestamps
            return False, 0
        timestamps.append(now)
        _RATE_LIMIT[ip] = timestamps
        return True, _RATE_LIMIT_MAX - len(timestamps)


# 静态资源（首页）加 HTTP 缓存头提升重复访问体验
@app.after_request
def _add_cache_headers(resp):
    if request.path == "/" or request.path.startswith("/reports/"):
        resp.headers["Cache-Control"] = "public, max-age=60"
    elif request.path.startswith("/api/daily") or request.path.startswith("/api/history"):
        resp.headers["Cache-Control"] = "public, max-age=60"
    return resp


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
    """异步获取日报数据 — 优先读预生成文件（秒开），无则提示等待定时任务

    重要：不再触发 run_pipeline()，避免 PythonAnywhere 免费版 100 秒 CPU 超时
    """
    import glob
    # 优先读取预生成的 6 板块日报
    report_files = sorted(glob.glob(os.path.join(_REPORT_DIR, "daily-6s-*.html")), reverse=True)
    if report_files:
        try:
            with open(report_files[0], "r", encoding="utf-8") as f:
                html = f.read()
            date_str = os.path.basename(report_files[0]).replace("daily-6s-", "").replace(".html", "")
            return jsonify({"date": date_str, "html": html})
        except Exception as e:
            logger.warning(f"Failed to read pre-generated report: {e}")

    # 无预生成文件 — 返回提示（不触发 pipeline，避免超时）
    return jsonify({
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "html": '<div style="text-align:center;padding:60px 20px;color:var(--text-dim)">'
                '<p style="font-size:1.2em;margin-bottom:12px">⏳ 今日日报尚未生成</p>'
                '<p>日报由定时任务（每天 UTC 00:00）自动生成，请稍后访问</p>'
                '<p style="margin-top:16px;font-size:0.85em">如需立即生成，请在服务器执行：<code>python src/main.py</code></p>'
                '</div>'
    })


@app.route("/api/refresh")
def api_refresh():
    """刷新数据 — 清除缓存，重新读取预生成文件（不触发 pipeline，避免超时）

    注意：PythonAnywhere 免费版无法在 Web 请求中运行完整 pipeline（100秒 CPU 限制）
    数据刷新由 GitHub Actions 定时任务或服务器 cron 完成
    """
    import glob
    report_files = sorted(glob.glob(os.path.join(_REPORT_DIR, "daily-6s-*.html")), reverse=True)
    if report_files:
        try:
            with open(report_files[0], "r", encoding="utf-8") as f:
                html = f.read()
            date_str = os.path.basename(report_files[0]).replace("daily-6s-", "").replace(".html", "")
            return jsonify({"ok": True, "date": date_str, "html": html})
        except Exception as e:
            logger.warning(f"Refresh failed to read report: {e}")
    return jsonify({"ok": False, "date": "", "msg": "暂无预生成报告，请等待定时任务运行"})


@app.route("/api/custom", methods=["GET", "POST"])
def api_custom():
    """自定义话题日报 — 解析查询 + 匹配仓库 + 生成报告

    支持用户传入自己的 LLM API Key + provider（个人化，不消耗项目方额度）
    兼容多家厂商：deepseek/openai/anthropic/qwen/zhipu/moonshot

    重要：从数据库读取 repos，不触发 run_pipeline()，避免 PythonAnywhere 超时
    """
    data = request.get_json(silent=True) or {}
    query = (data.get("query", "") or request.args.get("query", "")).strip()
    api_key = (data.get("api_key", "") or "").strip()  # 用户自己的 key（可选）
    provider = (data.get("provider", "") or "").strip()  # 厂商（可选，自动识别）
    if not query:
        return jsonify({"html": '<p style="color:var(--text-dim);text-align:center;padding:40px">'
                                '请输入话题关键词，例如：量化交易、AI Agent、游戏引擎</p>', "topic": ""})

    # IP 速率限制（防止恶意调用打满 GitHub Search API 配额）
    ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.remote_addr or "unknown"
    allowed, remaining = _check_rate_limit(ip)
    if not allowed:
        logger.warning(f"Rate limit exceeded for IP: {ip}")
        return jsonify({
            "html": '<p style="color:var(--accent-orange);text-align:center;padding:40px">'
                    '请求过于频繁，请 1 分钟后再试</p>',
            "topic": "rate_limited"
        }), 429

    # 缓存命中检查（key 不含 api_key 明文，仅含是否带 key 标记，保护用户隐私）
    cache_key = (query.lower(), bool(api_key), provider.lower())
    cached = _cache_get(cache_key)
    if cached:
        logger.info(f"Cache hit for query: {query[:30]}")
        return jsonify({**cached, "cached": True, "remaining": remaining})

    # 从数据库读取当天 repos（不触发 pipeline，避免超时）
    try:
        repos = get_today_repos()
    except Exception as e:
        logger.error(f"Failed to read repos from DB: {e}", exc_info=True)
        return jsonify({"html": '<p style="color:var(--accent-red)">数据加载失败，请稍后重试</p>', "topic": "error"}), 500

    if not repos:
        return jsonify({"html": '<p style="color:var(--text-dim);text-align:center;padding:40px">'
                                '今日数据尚未生成，请先访问基础日报或等待定时任务运行后再试</p>', "topic": query})

    try:
        # 4 层防御解析（用用户自己的 key，不消耗项目方额度）
        parsed = parse_query(query, api_key, provider)
        sections = generate_sections(parsed.get("topic", query), parsed.get("keywords", []), api_key, provider)
        # 基础模块热门项目作为补充源（项目不足时去重补充）
        basic_repos = sorted(repos, key=lambda r: r.get("hot_score", 0), reverse=True)[:30]
        html = generate_custom_report(repos, query, parsed, sections, basic_repos=basic_repos,
                                       api_key=api_key, provider=provider)
        payload = {
            "html": html,
            "topic": parsed.get("topic", query),
            "keywords": parsed.get("keywords", []),
            "source": parsed.get("source", ""),
            "used_llm": parsed.get("source") == "llm",
            "remaining": remaining,
        }
        # 写入缓存（同 query 10 分钟内复用结果，降低 GitHub API 与 LLM 调用）
        _cache_set(cache_key, payload)
        return jsonify(payload)
    except Exception as e:
        logger.error(f"Custom report failed: {e}", exc_info=True)
        # 不向客户端暴露内部错误细节
        return jsonify({"html": '<p style="color:var(--accent-red)">生成失败，请稍后重试或检查 API Key 是否正确</p>', "topic": "error"}), 500


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
    data = request.get_json(silent=True) or {}
    sub_type = data.get("type", "basic")
    email = (data.get("email", "") or "").strip()
    if not email:
        return jsonify({"ok": False, "msg": "请输入接收邮箱"}), 400

    if sub_type not in ("basic", "custom"):
        return jsonify({"ok": False, "msg": "type 必须是 basic 或 custom"}), 400

    subscription = {
        "type": sub_type,
        "email": email,
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        # 生成退订 token，用于邮件链接退订，防止 IDOR
        "unsubscribe_token": secrets.token_urlsafe(32),
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
        subscription["api_key"] = api_key  # 明文，用于即时发邮件
        subscription["provider"] = provider

    # 持久化到 data/subscription.json（列表格式，支持多订阅者）
    from config import DATA_DIR
    sub_path = os.path.join(DATA_DIR, "subscription.json")
    try:
        # 读取现有订阅列表（兼容旧的单 dict 格式）
        existing = []
        if os.path.exists(sub_path):
            with open(sub_path, "r", encoding="utf-8") as f:
                old = json.load(f)
            if isinstance(old, list):
                existing = old
            elif isinstance(old, dict):
                existing = [old]

        # 去重：同邮箱同类型只保留最新（解密已有邮箱进行比对）
        existing = [s for s in existing
                    if not (decrypt_if_needed(s.get("email", "")).lower() == email.lower()
                            and s.get("type") == sub_type)]

        # 构建加密版用于持久化存储
        encrypted_sub = dict(subscription)
        encrypted_sub["email"] = encrypt_if_needed(email)
        encrypted_sub["api_key"] = encrypt_if_needed(subscription.get("api_key", ""))
        existing.append(encrypted_sub)

        with open(sub_path, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
        # 日志脱敏：不记录完整邮箱
        masked_email = email[:2] + "***" + email[email.index("@"):] if "@" in email else "***"
        logger.info(f"Subscription saved: {sub_type} -> {masked_email} (total: {len(existing)})")
    except Exception as e:
        logger.error(f"Save subscription failed: {e}", exc_info=True)
        return jsonify({"ok": False, "msg": "保存订阅失败，请稍后重试"}), 500

    # 立即发送一封当前类型的日报邮件
    try:
        send_subscription_email(subscription)
        # 响应中不返回完整 subscription（含 api_key）
        safe_response = {k: v for k, v in subscription.items() if k != "api_key"}
        return jsonify({"ok": True, "msg": f"订阅成功！已发送{('自定义' if sub_type == 'custom' else '基础')}日报", "subscription": safe_response})
    except OSError as e:
        # PythonAnywhere 免费版封锁 SMTP 端口，属正常情况
        logger.warning(f"Email sending skipped (SMTP blocked in this environment): {e}")
        safe_response = {k: v for k, v in subscription.items() if k != "api_key"}
        return jsonify({"ok": True, "msg": "订阅成功！邮件将由定时任务自动推送", "subscription": safe_response})
    except Exception as e:
        logger.error(f"Send subscription email failed: {e}", exc_info=True)
        safe_response = {k: v for k, v in subscription.items() if k != "api_key"}
        return jsonify({"ok": True, "msg": "订阅已保存，邮件发送稍后重试", "subscription": safe_response})


def send_subscription_email(subscription: dict):
    """根据订阅类型发送对应日报邮件（线程安全，不修改全局配置）

    重要：从数据库读取 repos，不触发 run_pipeline()，避免超时
    """
    from src.notifier.email_sender import send_email
    from src.reporter.email_template import wrap_html_for_email

    email = subscription.get("email", "")
    sub_type = subscription.get("type", "basic")

    if sub_type == "basic":
        # 发送基础 6 板块日报 — 读预生成文件
        import glob
        html = ""
        files = sorted(glob.glob(os.path.join(_REPORT_DIR, "daily-6s-*.html")), reverse=True)
        if files:
            try:
                with open(files[0], "r", encoding="utf-8") as f:
                    html = f.read()
            except Exception as e:
                logger.warning(f"Failed to read report for email: {e}")
        html = wrap_html_for_email(html) if html else html
        subject = f"🚀 GitHub 每日热点（基础日报）— {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
        send_email(subject, html, receiver=email)
    else:
        # 发送自定义日报 — 从数据库读取 repos（不触发 pipeline）
        topic = subscription.get("topic", "自定义")
        keywords = subscription.get("keywords", [])
        api_key = subscription.get("api_key", "")
        provider = subscription.get("provider", "")
        repos = get_today_repos()
        if not repos:
            logger.warning("No repos in DB for custom subscription email, skipping")
            return
        parsed = parse_query(topic, api_key, provider)
        if not parsed.get("keywords"):
            parsed["keywords"] = keywords
        sections = generate_sections(parsed.get("topic", topic), parsed.get("keywords", []), api_key, provider)
        basic_repos = sorted(repos, key=lambda r: r.get("hot_score", 0), reverse=True)[:30]
        html = generate_custom_report(repos, topic, parsed, sections, basic_repos=basic_repos,
                                       api_key=api_key, provider=provider)
        html = wrap_html_for_email(html)
        subject = f"🔧 GitHub 每日热点（自定义: {topic}）— {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
        send_email(subject, html, receiver=email)


@app.route("/reports/<path:filename>")
def serve_report(filename):
    """提供历史报告文件

    注：报告文件是 HTML 片段（以 <div> 开头，无完整 HTML 文档结构）。
    直接访问会触发浏览器怪异模式、无 viewport、编码猜测错误。
    本路由为兼容现有报告文件，在响应中包裹完整 HTML 文档壳。
    """
    # 安全校验：防止路径遍历
    if ".." in filename or filename.startswith("/"):
        return "Not Found", 404

    try:
        with open(os.path.join(_REPORT_DIR, filename), "r", encoding="utf-8") as f:
            fragment = f.read()
    except (FileNotFoundError, OSError):
        return "Not Found", 404

    # 从文件名提取日期用于标题
    base = os.path.basename(filename)
    title = "GitHub Trending 报告"
    if base.startswith("daily-6s-"):
        date_str = base.replace("daily-6s-", "").replace(".html", "")
        title = f"GitHub 每日热点 — {date_str}"
    elif base.startswith("ai-"):
        title = "GitHub AI 深度日报"
    elif base.startswith("custom-"):
        title = "GitHub 自定义话题日报"

    # 包裹完整 HTML 文档壳：viewport + charset + 内联基础样式
    wrapped_html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
body {{ margin: 0; padding: 0; background: #f6f8fa; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif; }}
* {{ box-sizing: border-box; }}
</style>
</head>
<body>
{fragment}
</body>
</html>"""
    from flask import Response
    return Response(wrapped_html, mimetype="text/html; charset=utf-8")


@app.route("/api/status")
def api_status():
    """系统状态 — 加密状态、订阅者数、报告数"""
    import glob
    from src.utils.crypto import is_encrypted
    from config import DATA_DIR

    # Check .env encryption
    env_sensitive = {"GITHUB_TOKEN", "QQ_EMAIL", "QQ_EMAIL_AUTH_CODE", "RECEIVER_EMAIL", "DEEPSEEK_API_KEY"}
    env_encrypted = {}
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith("#") or "=" not in s:
                    continue
                k, _, v = s.partition("=")
                k = k.strip()
                v = v.strip()
                if k in env_sensitive:
                    env_encrypted[k] = is_encrypted(v)

    # Check subscription.json encryption
    sub_path = os.path.join(DATA_DIR, "subscription.json")
    sub_encrypted = {"emails": 0, "api_keys": 0, "total": 0}
    sub_count = 0
    if os.path.exists(sub_path):
        try:
            with open(sub_path, "r", encoding="utf-8") as f:
                subs = json.load(f)
            if isinstance(subs, dict):
                subs = [subs]
            sub_count = len(subs)
            for s in subs:
                email = s.get("email", "")
                api_key = s.get("api_key", "")
                if email:
                    sub_encrypted["total"] += 1
                    if is_encrypted(email):
                        sub_encrypted["emails"] += 1
                if api_key:
                    if is_encrypted(api_key):
                        sub_encrypted["api_keys"] += 1
        except Exception:
            pass

    # Report files
    report_files = sorted(glob.glob(os.path.join(REPORTS_DIR, "daily-6s-*.html")), reverse=True)
    latest_date = ""
    if report_files:
        latest_date = os.path.basename(report_files[0]).replace("daily-6s-", "").replace(".html", "")

    # DB count
    db_count = 0
    try:
        from src.storage.db import get_today_repos
        db_count = len(get_today_repos())
    except Exception:
        pass

    # Key file
    from src.utils.crypto import _KEY_FILE
    key_exists = os.path.exists(_KEY_FILE)

    return jsonify({
        "env_encrypted": env_encrypted,
        "sub_encrypted": sub_encrypted,
        "subscriber_count": sub_count,
        "report_count": len(report_files),
        "latest_report_date": latest_date,
        "db_repo_count": db_count,
        "key_file_exists": key_exists,
    })


@app.route("/api/subscriptions")
def api_subscriptions():
    """订阅列表 — 脱敏显示（不返回真实邮箱和 API Key）"""
    from config import DATA_DIR
    sub_path = os.path.join(DATA_DIR, "subscription.json")
    if not os.path.exists(sub_path):
        return jsonify({"subscriptions": []})
    try:
        with open(sub_path, "r", encoding="utf-8") as f:
            subs = json.load(f)
        if isinstance(subs, dict):
            subs = [subs]
        masked = []
        for s in subs:
            email = decrypt_if_needed(s.get("email", ""))
            masked_email = email[:2] + "***" + email[email.index("@"):] if "@" in email else "***"
            masked.append({
                "type": s.get("type", "basic"),
                "email": masked_email,
                "topic": s.get("topic", ""),
                "updated_at": s.get("updated_at", ""),
                "provider": s.get("provider", ""),
                "has_api_key": bool(s.get("api_key", "")),
            })
        return jsonify({"subscriptions": masked})
    except Exception as e:
        logger.error(f"Failed to read subscriptions: {e}")
        return jsonify({"subscriptions": [], "error": "读取失败"}), 500


@app.route("/api/unsubscribe", methods=["POST", "GET"])
def api_unsubscribe():
    """退订 — 支持 token 直接退订，或邮箱触发确认邮件（防 IDOR）

    两种方式：
    1. POST/GET 带 token 参数 → 校验 token 直接退订（用户从邮件链接点击）
    2. POST 仅带 email → 不直接退订，发送确认邮件到该邮箱（含 token 链接）
    """
    from config import DATA_DIR
    # 兼容 GET（邮件链接直接点击）和 POST（前端表单）
    if request.method == "GET":
        token = (request.args.get("token", "") or "").strip()
        email = (request.args.get("email", "") or "").strip().lower()
    else:
        data = request.get_json(silent=True) or {}
        token = (data.get("token", "") or "").strip()
        email = (data.get("email", "") or "").strip().lower()

    sub_path = os.path.join(DATA_DIR, "subscription.json")
    if not os.path.exists(sub_path):
        return jsonify({"ok": False, "msg": "无订阅记录"}), 404

    try:
        with open(sub_path, "r", encoding="utf-8") as f:
            subs = json.load(f)
        if isinstance(subs, dict):
            subs = [subs]
    except Exception as e:
        logger.error(f"Unsubscribe read failed: {e}")
        return jsonify({"ok": False, "msg": "读取订阅失败"}), 500

    # 方式 1：带 token 直接退订
    if token:
        original_count = len(subs)
        subs = [s for s in subs if s.get("unsubscribe_token") != token]
        removed = original_count - len(subs)
        if removed == 0:
            return jsonify({"ok": False, "msg": "无效或已过期的退订链接"}), 404
        try:
            with open(sub_path, "w", encoding="utf-8") as f:
                json.dump(subs, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Unsubscribe save failed: {e}")
            return jsonify({"ok": False, "msg": "退订失败"}), 500
        return jsonify({"ok": True, "msg": f"已成功退订 {removed} 个订阅"})

    # 方式 2：仅邮箱 → 发送确认邮件（含 token 链接）
    if not email:
        return jsonify({"ok": False, "msg": "请输入邮箱或提供 token"}), 400

    # 查找该邮箱的所有订阅（含 token）
    matched_subs = [s for s in subs if decrypt_if_needed(s.get("email", "")).lower() == email]
    if not matched_subs:
        return jsonify({"ok": False, "msg": "未找到对应订阅"}), 404

    # 发送退订确认邮件（含 token 链接）
    try:
        _send_unsubscribe_confirmation(email, matched_subs)
        masked = email[:2] + "***" + email[email.index("@"):] if "@" in email else "***"
        return jsonify({"ok": True, "msg": f"已向 {masked} 发送退订确认邮件，请查收后点击链接完成退订"})
    except Exception as e:
        logger.error(f"Send unsubscribe confirmation failed: {e}", exc_info=True)
        return jsonify({"ok": False, "msg": "发送确认邮件失败，请稍后重试"}), 500


def _send_unsubscribe_confirmation(email: str, subs: list):
    """发送退订确认邮件，包含每个订阅的退订链接"""
    from src.notifier.email_sender import send_email

    # 构建退订链接列表
    base_url = request.host_url.rstrip("/")
    links_html = []
    for s in subs:
        token = s.get("unsubscribe_token", "")
        sub_type = s.get("type", "basic")
        topic = s.get("topic", "")
        type_label = f"自定义日报（{topic}）" if sub_type == "custom" and topic else "基础日报"
        if token:
            url = f"{base_url}/api/unsubscribe?token={token}"
            links_html.append(
                f'<p style="margin:12px 0;padding:10px;background:#f6f8fa;border-radius:6px;">'
                f'{type_label} <a href="{url}" style="color:#0969da;">点击退订</a>'
                f'</p>'
            )
    if not links_html:
        return

    html = f"""<html><body style="font-family:-apple-system,BlinkMacSystemFont,sans-serif;max-width:600px;margin:0 auto;padding:20px;">
<h2 style="color:#1f2328;">退订确认</h2>
<p>您好，</p>
<p>我们收到了针对您邮箱的退订请求。为防止他人恶意退订您的订阅，请点击下方链接确认退订：</p>
{"".join(links_html)}
<p style="color:#57606a;font-size:13px;margin-top:20px;">如果您没有发起退订请求，请忽略此邮件。链接有效，他人无法仅凭邮箱退订您的订阅。</p>
<hr style="margin:24px 0;border:none;border-top:1px solid #d0d7de;">
<p style="color:#57606a;font-size:12px;">此邮件由 GitRadar 自动发送，请勿回复。</p>
</body></html>"""
    send_email("退订确认 — GitRadar", html, receiver=email)


@app.route("/api/history")
def api_history():
    """历史报告列表"""
    import glob
    report_files = sorted(glob.glob(os.path.join(REPORTS_DIR, "daily-6s-*.html")), reverse=True)
    history = []
    for f in report_files[:30]:  # Latest 30
        filename = os.path.basename(f)
        date_str = filename.replace("daily-6s-", "").replace(".html", "")
        size = os.path.getsize(f)
        history.append({"date": date_str, "filename": filename, "size": size})
    return jsonify({"history": history})


@app.route("/api/tunnel_status")
def api_tunnel_status():
    """URL 隧道监控状态 — 读取 url_monitor 审计日志和当前 URL

    返回：
    - current_url: 当前隧道 URL
    - last_check: 最近一次健康检查时间
    - total_events: 审计日志总事件数
    - recoveries: 自动恢复次数
    - failures: 检测到故障次数
    - alerts: 发送告警次数
    - recent_events: 最近 10 条事件
    - uptime_status: 运行状态（healthy/recovering/down/unknown）
    """
    from config import DATA_DIR

    result = {
        "current_url": "",
        "last_check": "",
        "total_events": 0,
        "recoveries": 0,
        "failures": 0,
        "alerts": 0,
        "recent_events": [],
        "uptime_status": "unknown",
        "monitor_running": False,
    }

    # 当前隧道 URL — 兼容两种存储位置：
    #   1) DATA_DIR/current_url.txt （data/ 子目录）
    #   2) 项目根目录 current_url.txt （start_tunnel.ps1 默认存储位置）
    url_file = os.path.join(DATA_DIR, "current_url.txt")
    if not os.path.exists(url_file):
        url_file = os.path.join(_BASE_DIR, "current_url.txt")
    if os.path.exists(url_file):
        try:
            with open(url_file, "r", encoding="utf-8-sig") as f:
                result["current_url"] = f.read().strip()
        except Exception:
            pass

    # 审计日志
    audit_file = os.path.join(DATA_DIR, "logs", "url_monitor_audit.jsonl")
    if os.path.exists(audit_file):
        try:
            events = []
            with open(audit_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            events.append(json.loads(line))
                        except Exception:
                            pass
            result["total_events"] = len(events)
            for e in events:
                # 兼容 event_type / event 两种字段名
                etype = e.get("event_type", "") or e.get("event", "")
                if etype in ("recovery_success", "recovery_completed", "url_recovered"):
                    result["recoveries"] += 1
                elif etype in ("health_check_failed", "url_invalid", "url_check_failed"):
                    result["failures"] += 1
                elif etype in ("critical_alert_sent", "notification_sent"):
                    result["alerts"] += 1
            # 最近 10 条事件（倒序）
            result["recent_events"] = list(reversed(events[-10:]))
            if events:
                result["last_check"] = events[-1].get("timestamp", "")
            # 推断状态
            if result["current_url"]:
                if result["failures"] == 0:
                    result["uptime_status"] = "healthy"
                elif result["recoveries"] > 0:
                    result["uptime_status"] = "recovering"
                else:
                    result["uptime_status"] = "down"
            # 监控守护进程是否在运行（最近 5 分钟内有日志）
            if events:
                try:
                    from datetime import datetime as _dt, timezone as _tz
                    last_ts = events[-1].get("timestamp", "")
                    if last_ts:
                        last_dt = _dt.fromisoformat(last_ts.replace("Z", "+00:00"))
                        now_dt = _dt.now(_tz.utc)
                        if (now_dt - last_dt).total_seconds() < 300:
                            result["monitor_running"] = True
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"Failed to read tunnel audit log: {e}")

    return jsonify(result)


def _render_index(mode: str = "basic", report_content: str = "") -> str:
    """渲染主页面"""
    tabs = [
        {"id": "basic", "label": "📊 基础日报", "desc": "6板块多维评价"},
        {"id": "custom", "label": "🔧 自定义", "desc": "输入话题生成专属日报"},
        {"id": "dashboard", "label": "📈 数据面板", "desc": "加密/监控/系统统计"},
        {"id": "manage", "label": "📬 订阅管理", "desc": "查看与退订"},
        {"id": "arch", "label": "🏗️ 架构", "desc": "技术栈与系统设计"},
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
    """

    dashboard_placeholder = """
    <div style="padding:20px;max-width:1100px;margin:0 auto;">
        <div id="dashboardContent" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:16px;margin-bottom:24px;">
            <div class="skeleton-card" style="grid-column:1/-1;">加载中...</div>
        </div>
        <div id="tunnelCard" class="tunnel-card-dash" style="display:none;"></div>
        <div id="historyList" style="margin-top:20px;"></div>
    </div>
    """

    manage_placeholder = """
    <div style="padding:20px;max-width:800px;margin:0 auto;">
        <h2 style="color:var(--text);margin-bottom:16px;">📬 订阅管理</h2>
        <div id="subList" style="margin-bottom:24px;">加载中...</div>
        <div style="background:var(--bg-card);border:1px solid var(--border);border-radius:12px;padding:20px;">
            <h3 style="color:var(--text);margin-bottom:8px;font-size:1em;">退订</h3>
            <p style="color:var(--text-dim);font-size:0.85em;margin:0 0 12px;">输入你的订阅邮箱即可取消每日推送</p>
            <div style="display:flex;gap:8px;flex-wrap:wrap;">
                <input type="email" id="unsubEmail" placeholder="输入要退订的邮箱"
                       style="flex:1;min-width:240px;padding:10px 14px;border-radius:8px;border:1px solid var(--border);background:var(--bg);color:var(--text);">
                <button onclick="doUnsubscribe()" style="padding:10px 24px;border-radius:8px;background:var(--accent-red);color:#fff;border:none;cursor:pointer;">退订</button>
            </div>
            <div id="unsubMsg" style="margin-top:10px;font-size:0.85em;"></div>
        </div>
    </div>
    """

    arch_placeholder = """
    <div class="arch-container">
        <!-- Hero 简介 -->
        <section class="arch-hero">
            <div class="arch-hero-tag">🏆 TRAE AI 创造力大赛参赛作品</div>
            <h2 class="arch-hero-title">GitRadar</h2>
            <p class="arch-hero-subtitle">基于 TRAE IDE 全程开发的 GitRadar · GitHub 开源项目雷达</p>
            <div class="arch-hero-stats">
                <div class="hero-stat"><span class="num" id="archStatRepos">—</span><span class="lbl">已索引项目</span></div>
                <div class="hero-stat"><span class="num" id="archStatReports">—</span><span class="lbl">累计报告</span></div>
                <div class="hero-stat"><span class="num" id="archStatSubs">—</span><span class="lbl">订阅用户</span></div>
                <div class="hero-stat"><span class="num" id="archStatEnc">—</span><span class="lbl">加密字段</span></div>
            </div>
        </section>

        <!-- 三步引导 -->
        <section class="arch-section">
            <h3 class="arch-section-title"><span class="arch-num">1</span>体验路径</h3>
            <div class="arch-steps">
                <div class="arch-step" onclick="switchTab('basic')">
                    <div class="arch-step-icon">📊</div>
                    <div class="arch-step-title">浏览今日热门</div>
                    <div class="arch-step-desc">6 板块多维评分日报</div>
                </div>
                <div class="arch-step-arrow">→</div>
                <div class="arch-step" onclick="switchTab('custom')">
                    <div class="arch-step-icon">🔧</div>
                    <div class="arch-step-title">自定义话题</div>
                    <div class="arch-step-desc">AI 解析生成专属日报</div>
                </div>
                <div class="arch-step-arrow">→</div>
                <div class="arch-step" onclick="switchTab('manage')">
                    <div class="arch-step-icon">📬</div>
                    <div class="arch-step-title">订阅推送</div>
                    <div class="arch-step-desc">每日邮件直达</div>
                </div>
            </div>
        </section>

        <!-- Pipeline 流程图 -->
        <section class="arch-section">
            <h3 class="arch-section-title"><span class="arch-num">2</span>数据流水线（9 步全自动）</h3>
            <div class="arch-pipeline">
                <div class="pipe-step"><span class="pipe-icon">🌐</span><span class="pipe-name">GitHub Trending 抓取</span></div>
                <div class="pipe-arrow">→</div>
                <div class="pipe-step"><span class="pipe-icon">🗂️</span><span class="pipe-name">去重入库 SQLite</span></div>
                <div class="pipe-arrow">→</div>
                <div class="pipe-step"><span class="pipe-icon">📈</span><span class="pipe-name">6 维评分引擎</span></div>
                <div class="pipe-arrow">→</div>
                <div class="pipe-step"><span class="pipe-icon">🤖</span><span class="pipe-name">AI 深度分析</span></div>
                <div class="pipe-arrow">→</div>
                <div class="pipe-step"><span class="pipe-icon">📄</span><span class="pipe-name">HTML 报告生成</span></div>
                <div class="pipe-arrow">→</div>
                <div class="pipe-step"><span class="pipe-icon">🔒</span><span class="pipe-name">加密订阅邮箱</span></div>
                <div class="pipe-arrow">→</div>
                <div class="pipe-step"><span class="pipe-icon">📧</span><span class="pipe-name">邮件推送</span></div>
                <div class="pipe-arrow">→</div>
                <div class="pipe-step"><span class="pipe-icon">🌐</span><span class="pipe-name">Cloudflare Tunnel</span></div>
                <div class="pipe-arrow">→</div>
                <div class="pipe-step"><span class="pipe-icon">📡</span><span class="pipe-name">URL 健康监控</span></div>
            </div>
            <p class="arch-note">⏰ 每日 UTC 00:00 GitHub Actions 自动触发，全程无人工干预。</p>
        </section>

        <!-- 技术栈 -->
        <section class="arch-section">
            <h3 class="arch-section-title"><span class="arch-num">3</span>技术栈</h3>
            <div class="arch-tech-grid">
                <div class="tech-card"><div class="tech-icon">🐍</div><div class="tech-name">Python + Flask</div><div class="tech-desc">Web 服务 / pipeline 编排</div></div>
                <div class="tech-card"><div class="tech-icon">🔒</div><div class="tech-name">Fernet 加密</div><div class="tech-desc">AES-128-CBC + HMAC-SHA256</div></div>
                <div class="tech-card"><div class="tech-icon">🤖</div><div class="tech-name">6 家 LLM 接入</div><div class="tech-desc">DeepSeek/OpenAI/Claude 等 6 家</div></div>
                <div class="tech-card"><div class="tech-icon">📊</div><div class="tech-name">SQLite + 6 维评分</div><div class="tech-desc">爆发度/质量/潜力/陷阱/AI 雷达</div></div>
                <div class="tech-card"><div class="tech-icon">🌐</div><div class="tech-name">Cloudflare Tunnel</div><div class="tech-desc">本地服务公网暴露 + 自动恢复</div></div>
                <div class="tech-card"><div class="tech-icon">⚡</div><div class="tech-name">GitHub Actions</div><div class="tech-desc">每日定时全自动 pipeline</div></div>
                <div class="tech-card"><div class="tech-icon">📡</div><div class="tech-name">URL 监控守护</div><div class="tech-desc">健康检查 + 自动重建 + 告警</div></div>
                <div class="tech-card"><div class="tech-icon">📧</div><div class="tech-name">SMTP 邮件推送</div><div class="tech-desc">每日报告自动邮件分发</div></div>
            </div>
        </section>

        <!-- 加密安全 -->
        <section class="arch-section">
            <h3 class="arch-section-title"><span class="arch-num">4</span>数据安全设计</h3>
            <div class="arch-security">
                <div class="sec-card">
                    <div class="sec-header"><span class="sec-icon">🔐</span><span class="sec-title">Fernet 对称加密</span></div>
                    <p class="sec-desc">采用 <code>AES-128-CBC + HMAC-SHA256</code> 组合算法。HMAC 防篡改 + CBC 抗模式分析，密钥由 <code>Fernet.generate_key()</code> 一次性生成并落盘 <code>data/.secret_key</code>。</p>
                </div>
                <div class="sec-card">
                    <div class="sec-header"><span class="sec-icon">📧</span><span class="sec-title">敏感字段加密</span></div>
                    <p class="sec-desc">订阅者邮箱、开发者邮箱、所有 API Key（GitHub Token / DeepSeek / 6 家 LLM）写入前自动加密，前缀 <code>ENC:</code> 标识。读取时透明解密，列表展示自动脱敏 <code>xx***@domain</code>。</p>
                </div>
                <div class="sec-card">
                    <div class="sec-header"><span class="sec-icon">🔑</span><span class="sec-title">密钥管理</span></div>
                    <p class="sec-desc">单例模式保证全局唯一密钥；<code>.secret_key</code> 文件不入版本库；首次启动自动生成；密钥丢失则历史加密数据不可解密（前向安全特性）。</p>
                </div>
            </div>
        </section>

        <!-- 多 LLM 厂商 -->
        <section class="arch-section">
            <h3 class="arch-section-title"><span class="arch-num">5</span>多 LLM 厂商接入（4 层防御解析）</h3>
            <div class="arch-llm-grid">
                <div class="llm-card"><div class="llm-logo">🔮</div><div class="llm-name">DeepSeek</div><div class="llm-model">deepseek-chat</div></div>
                <div class="llm-card"><div class="llm-logo">🟢</div><div class="llm-name">OpenAI</div><div class="llm-model">gpt-4o-mini</div></div>
                <div class="llm-card"><div class="llm-logo">🟣</div><div class="llm-name">Anthropic</div><div class="llm-model">claude-3-5-haiku</div></div>
                <div class="llm-card"><div class="llm-logo">🔵</div><div class="llm-name">通义千问</div><div class="llm-model">qwen-turbo</div></div>
                <div class="llm-card"><div class="llm-logo">🟠</div><div class="llm-name">智谱清言</div><div class="llm-model">glm-4-flash</div></div>
                <div class="llm-card"><div class="llm-logo">🌙</div><div class="llm-name">Moonshot Kimi</div><div class="llm-model">moonshot-v1-8k</div></div>
            </div>
            <p class="arch-note">🛡️ 解析 4 层防御：<code>规则匹配</code> → <code>LLM 解析</code> → <code>关键词兜底</code> → <code>降级保护</code>。用户可自带 key 走个人化解析，不消耗项目方额度。</p>
        </section>

        <!-- 话题模板 -->
        <section class="arch-section">
            <h3 class="arch-section-title"><span class="arch-num">6</span>话题模板库（32 个领域）</h3>
            <div class="arch-topics">
                <span class="topic-chip">AI Agent</span><span class="topic-chip">大模型</span><span class="topic-chip">文生图</span><span class="topic-chip">语音AI</span><span class="topic-chip">具身智能</span>
                <span class="topic-chip">量化交易</span><span class="topic-chip">金融</span><span class="topic-chip">游戏开发</span><span class="topic-chip">前端框架</span><span class="topic-chip">后端框架</span>
                <span class="topic-chip">数据库</span><span class="topic-chip">DevOps</span><span class="topic-chip">CLI 工具</span><span class="topic-chip">安全工具</span><span class="topic-chip">Rust 生态</span>
                <span class="topic-chip">Python 生态</span><span class="topic-chip">Go 生态</span><span class="topic-chip">TypeScript</span><span class="topic-chip">区块链</span><span class="topic-chip">机器人</span>
                <span class="topic-chip">视频处理</span><span class="topic-chip">桌面应用</span><span class="topic-chip">移动开发</span><span class="topic-chip">云计算</span><span class="topic-chip">API 开发</span>
                <span class="topic-chip">数据科学</span><span class="topic-chip">设计工具</span><span class="topic-chip">浏览器</span><span class="topic-chip">监控运维</span><span class="topic-chip">教育教程</span>
                <span class="topic-chip">嵌入式开发</span><span class="topic-chip">电子信息</span><span class="topic-chip">物联网</span><span class="topic-chip">硬件设计</span><span class="topic-chip">信号处理</span>
                <span class="topic-chip">电力系统</span><span class="topic-chip">自动驾驶</span><span class="topic-chip">机械制造</span><span class="topic-chip">生物医学</span><span class="topic-chip">土木建筑</span>
            </div>
        </section>

        <!-- URL 监控 -->
        <section class="arch-section">
            <h3 class="arch-section-title"><span class="arch-num">7</span>URL 健康监控守护</h3>
            <div class="arch-tunnel" id="archTunnelCard">
                <div class="tunnel-row">
                    <span class="tunnel-label">📡 当前隧道</span>
                    <a href="#" id="archTunnelUrl" target="_blank" class="tunnel-url">加载中...</a>
                </div>
                <div class="tunnel-row">
                    <span class="tunnel-label">🟢 运行状态</span>
                    <span id="archTunnelStatus" class="tunnel-status">—</span>
                </div>
                <div class="tunnel-row">
                    <span class="tunnel-label">🔄 自动恢复</span>
                    <span id="archTunnelRecoveries" class="tunnel-metric">—</span>
                </div>
                <div class="tunnel-row">
                    <span class="tunnel-label">⚠️ 故障次数</span>
                    <span id="archTunnelFailures" class="tunnel-metric">—</span>
                </div>
            </div>
            <p class="arch-note">📡 监控守护进程：检测 HTTP 4xx/5xx、超时、DNS 失败 → 自动 kill+重启 cloudflared → 提取新 URL → 邮件通知订阅者与开发者。完整 JSONL 审计日志。</p>
        </section>
    </div>
    """

    # 恐龙游戏 overlay（普通字符串，避免 f-string 双花括号转义问题）
    # 当 fetchWithTimeout 等待超过 20s 时显示，给用户交互反馈；fetch 返回后隐藏
    _dino_overlay_html = """
<style>
#dinoFallback {
  display: none;
  position: fixed;
  inset: 0;
  background: rgba(13, 17, 23, 0.96);
  backdrop-filter: blur(6px);
  z-index: 9999;
  align-items: center;
  justify-content: center;
  padding: 20px;
  animation: dinoFadeIn 0.3s ease;
}
#dinoFallback.show { display: flex; }
@keyframes dinoFadeIn { from { opacity: 0; } to { opacity: 1; } }
.dino-card {
  max-width: 640px;
  width: 100%;
  background: #161b22;
  border: 1px solid #30363d;
  border-radius: 16px;
  padding: 28px 24px 20px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
  text-align: center;
}
.dino-badge {
  display: inline-block;
  padding: 4px 12px;
  background: rgba(210, 153, 29, 0.15);
  color: #d2991d;
  border-radius: 12px;
  font-size: 0.78em;
  font-weight: 600;
  margin-bottom: 12px;
  letter-spacing: 0.5px;
}
.dino-card h2 {
  margin: 0 0 6px;
  font-size: 1.25em;
  background: linear-gradient(90deg, #d2991d, #f85149);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}
.dino-sub {
  color: #8b949e;
  font-size: 0.85em;
  margin-bottom: 16px;
  line-height: 1.6;
}
.dino-game-wrap {
  position: relative;
  margin: 12px 0;
  padding: 10px;
  background: #0a0e14;
  border: 1px solid #30363d;
  border-radius: 10px;
}
#dinoCanvas {
  display: block;
  width: 100%;
  max-width: 580px;
  height: 170px;
  margin: 0 auto;
  background: #0a0e14;
  image-rendering: pixelated;
}
.dino-hint {
  color: #8b949e;
  font-size: 0.78em;
  margin-top: 8px;
  font-family: Consolas, monospace;
}
.dino-hint kbd {
  display: inline-block;
  padding: 2px 8px;
  background: #0d1117;
  border: 1px solid #30363d;
  border-radius: 4px;
  color: #58a6ff;
  margin: 0 2px;
}
.dino-score {
  color: #58a6ff;
  font-family: Consolas, monospace;
  margin-left: 8px;
}
.dino-progress {
  margin-top: 14px;
  padding: 10px 14px;
  background: rgba(88, 166, 255, 0.08);
  border: 1px solid rgba(88, 166, 255, 0.25);
  border-radius: 8px;
  color: #58a6ff;
  font-size: 0.82em;
  text-align: left;
  line-height: 1.7;
}
.dino-progress code {
  color: #3fb950;
  font-family: Consolas, monospace;
}
.dino-cancel {
  margin-top: 12px;
  padding: 8px 22px;
  background: transparent;
  border: 1px solid #30363d;
  color: #8b949e;
  border-radius: 8px;
  cursor: pointer;
  font-size: 0.88em;
}
.dino-cancel:hover { border-color: #f85149; color: #f85149; }
.dino-start-btn {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  padding: 14px 38px;
  background: linear-gradient(135deg, #58a6ff 0%, #a371f7 100%);
  color: #fff;
  border: none;
  border-radius: 12px;
  font-size: 1.05em;
  font-weight: 700;
  cursor: pointer;
  box-shadow: 0 6px 24px rgba(88, 166, 255, 0.5), 0 0 0 2px rgba(255,255,255,0.1) inset;
  transition: transform 0.2s, box-shadow 0.2s, opacity 0.3s;
  z-index: 10;
  letter-spacing: 1px;
  animation: dinoBtnPulse 2s ease-in-out infinite;
}
.dino-start-btn:hover {
  transform: translate(-50%, -50%) scale(1.06);
  box-shadow: 0 10px 32px rgba(88, 166, 255, 0.7), 0 0 0 2px rgba(255,255,255,0.2) inset;
}
.dino-start-btn.hidden {
  opacity: 0;
  pointer-events: none;
  transform: translate(-50%, -50%) scale(0.8);
  animation: none;
}
@keyframes dinoBtnPulse {
  0%, 100% { box-shadow: 0 6px 24px rgba(88, 166, 255, 0.5), 0 0 0 2px rgba(255,255,255,0.1) inset; }
  50% { box-shadow: 0 6px 32px rgba(163, 113, 247, 0.7), 0 0 0 2px rgba(255,255,255,0.2) inset; }
}
</style>

<div id="dinoFallback">
  <div class="dino-card">
    <span class="dino-badge">⏳ 后端响应较慢</span>
    <h2 id="dinoTitle">等待中... 先玩一会儿</h2>
    <p class="dino-sub" id="dinoSubTitle">请求已发出，后端仍在处理（可能涉及 LLM 调用或多轮解析）</p>
    <div class="dino-game-wrap">
      <canvas id="dinoCanvas" width="580" height="170"></canvas>
      <button id="dinoStartBtn" class="dino-start-btn">▶ 开始游戏</button>
      <div class="dino-hint">
        按 <kbd>空格</kbd> 或 <kbd>↑</kbd> 跳跃 · 避开仙人掌 · 分数<span class="dino-score" id="dinoScore">0</span> · 最高<span class="dino-score" id="dinoBest">0</span>
      </div>
    </div>
    <div class="dino-progress">
      <div>📡 请求仍在进行中，<code>fetchWithTimeout</code> 不会被打断</div>
      <div>⏱ 软超时阈值：<code>20 秒</code>（后台继续，前端有交互）</div>
      <div id="dinoElapsed">⏳ 已等待：0 秒</div>
    </div>
    <button class="dino-cancel" onclick="hideDinoFallback()">隐藏游戏（继续等待）</button>
  </div>
</div>

<script>
var _dinoGameInst = null;
var _dinoElapsedTimer = null;
var _dinoStartTime = 0;

function showDinoFallback(reason) {
  var el = document.getElementById('dinoFallback');
  if (!el) return;
  el.classList.add('show');
  var subEl = document.getElementById('dinoSubTitle');
  if (reason && subEl) subEl.textContent = reason;
  _dinoStartTime = Date.now();
  // 启动 / 恢复恐龙游戏
  if (!_dinoGameInst) {
    _dinoGameInst = new DinoGameSoft();
    // 不自动 start，等用户点击「开始游戏」按钮
  } else if (_dinoGameInst.started) {
    _dinoGameInst.resume();
  }
  // 启动已等待时间计时
  if (_dinoElapsedTimer) clearInterval(_dinoElapsedTimer);
  _dinoElapsedTimer = setInterval(function() {
    var sec = Math.floor((Date.now() - _dinoStartTime) / 1000);
    var eEl = document.getElementById('dinoElapsed');
    if (eEl) eEl.textContent = '⏳ 已等待：' + sec + ' 秒';
  }, 1000);
}

function hideDinoFallback() {
  var el = document.getElementById('dinoFallback');
  if (el) el.classList.remove('show');
  if (_dinoElapsedTimer) { clearInterval(_dinoElapsedTimer); _dinoElapsedTimer = null; }
  if (_dinoGameInst) _dinoGameInst.pause();
}

// 软超时恐龙游戏（与 GitHub Pages 跳转页的实现保持一致）
class DinoGameSoft {
  constructor() {
    this.canvas = document.getElementById('dinoCanvas');
    this.ctx = this.canvas.getContext('2d');
    this.W = this.canvas.width;
    this.H = this.canvas.height;
    this.groundY = this.H - 28;
    this.dino = { x: 50, y: this.groundY - 30, w: 28, h: 30, vy: 0, jumping: false };
    this.gravity = 0.7;
    this.jumpV = -10.5;
    this.cacti = [];
    this.clouds = [];
    this.speed = 3.5;
    this.score = 0;
    this.best = parseInt(localStorage.getItem('soft_dino_best') || '0', 10);
    var bestEl = document.getElementById('dinoBest');
    if (bestEl) bestEl.textContent = this.best;
    this.spawnTimer = 0;
    this.cloudTimer = 0;
    this.running = false;
    this.gameOver = false;
    this.started = false;       // 是否已点击开始按钮
    this.runFrame = 0;           // 跑步动画帧计数
    this.blinkTimer = 0;        // 眨眼计时器
    this.blinking = false;
    this.bindKeys();
    this.bindStartBtn();
    // 初始绘制一帧静态恐龙（按钮显示时）
    this.draw();
  }
  bindStartBtn() {
    var self = this;
    var btn = document.getElementById('dinoStartBtn');
    if (btn) {
      btn.addEventListener('click', function() {
        self.started = true;
        btn.classList.add('hidden');
        self.reset();
        self.start();
      });
    }
  }
  bindKeys() {
    var self = this;
    this._keyHandler = function(e) {
      if (e.code === 'Space' || e.code === 'ArrowUp') {
        e.preventDefault();
        // 未点击开始按钮时，键盘空格不响应
        if (!self.started) return;
        if (self.gameOver) { self.reset(); self.start(); return; }
        if (!self.dino.jumping) { self.dino.vy = self.jumpV; self.dino.jumping = true; }
      }
    };
    document.addEventListener('keydown', this._keyHandler);
    this._touchHandler = function() {
      if (!self.started) return;
      if (self.gameOver) { self.reset(); self.start(); return; }
      if (!self.dino.jumping) { self.dino.vy = self.jumpV; self.dino.jumping = true; }
    };
    if (this.canvas) {
      this.canvas.addEventListener('touchstart', function(e) { e.preventDefault(); self._touchHandler(); }, { passive: false });
      this.canvas.addEventListener('click', function() { self._touchHandler(); });
    }
  }
  reset() {
    this.dino.y = this.groundY - this.dino.h;
    this.dino.vy = 0;
    this.dino.jumping = false;
    this.cacti = [];
    this.clouds = [];
    this.score = 0;
    this.speed = 3.5;
    this.gameOver = false;
    this.spawnTimer = 0;
    this.cloudTimer = 0;
    this.runFrame = 0;
    // 清除自动重启定时器（防止手动按空格重启 + 自动重启双重触发）
    if (this._autoRestartTimer) {
      clearInterval(this._autoRestartTimer);
      this._autoRestartTimer = null;
    }
    var scEl = document.getElementById('dinoScore');
    if (scEl) scEl.textContent = '0';
  }
  start() { this.running = true; this.loop(); }
  pause() { this.running = false; }
  resume() { if (!this.running && this.started) { this.running = true; this.loop(); } }
  loop() {
    if (!this.running) return;
    this.update();
    this.draw();
    // 关键修复：gameOver 时不再调度下一帧，避免按空格重启时启动多个 RAF 循环
    if (!this.gameOver) {
      requestAnimationFrame(this.loop.bind(this));
    }
  }
  update() {
    if (this.gameOver) return;
    this.dino.y += this.dino.vy;
    this.dino.vy += this.gravity;
    if (this.dino.y >= this.groundY - this.dino.h) {
      this.dino.y = this.groundY - this.dino.h;
      this.dino.vy = 0;
      this.dino.jumping = false;
    }
    // 跑步动画帧（每 6 帧切换一次腿部姿势）
    if (!this.dino.jumping) {
      this.runFrame++;
    }
    // 眨眼计时
    this.blinkTimer++;
    if (this.blinkTimer > 180) {  // 约 3 秒眨一次
      this.blinking = true;
      if (this.blinkTimer > 186) {  // 眨眼持续 6 帧
        this.blinking = false;
        this.blinkTimer = 0;
      }
    }
    this.spawnTimer--;
    if (this.spawnTimer <= 0) {
      var minGap = Math.max(40, 90 - this.speed * 3);
      var maxGap = Math.max(80, 160 - this.speed * 3);
      this.spawnTimer = minGap + Math.floor(Math.random() * (maxGap - minGap));
      var h = 18 + Math.floor(Math.random() * 22);
      this.cacti.push({ x: this.W, y: this.groundY - h, w: 12 + Math.floor(Math.random() * 8), h: h });
    }
    this.cloudTimer--;
    if (this.cloudTimer <= 0) {
      this.cloudTimer = 80 + Math.floor(Math.random() * 80);
      this.clouds.push({ x: this.W, y: 18 + Math.floor(Math.random() * 50), w: 36 });
    }
    for (var i = 0; i < this.cacti.length; i++) this.cacti[i].x -= this.speed;
    for (var j = 0; j < this.clouds.length; j++) this.clouds[j].x -= 2;
    this.cacti = this.cacti.filter(function(c) { return c.x + c.w > 0; });
    this.clouds = this.clouds.filter(function(c) { return c.x + c.w > 0; });
    for (var k = 0; k < this.cacti.length; k++) {
      var c = this.cacti[k];
      if (this.dino.x + 4 < c.x + c.w && this.dino.x + this.dino.w - 4 > c.x &&
          this.dino.y + 4 < c.y + c.h && this.dino.y + this.dino.h > c.y) {
        this.endGame();
        return;
      }
    }
    this.score++;
    var scEl = document.getElementById('dinoScore');
    if (scEl) scEl.textContent = Math.floor(this.score / 5);
    if (this.score % 200 === 0) this.speed += 0.25;
  }
  endGame() {
    this.gameOver = true;
    var sc = Math.floor(this.score / 5);
    if (sc > this.best) {
      this.best = sc;
      localStorage.setItem('soft_dino_best', String(sc));
      var bestEl = document.getElementById('dinoBest');
      if (bestEl) bestEl.textContent = this.best;
    }
    // 死亡后 2 秒自动重开
    var self = this;
    if (this._autoRestartTimer) clearTimeout(this._autoRestartTimer);
    this._autoRestartSec = 2;
    var secEl = document.getElementById('dinoScore');
    var origText = secEl ? secEl.textContent : '';
    this._autoRestartTimer = setInterval(function() {
      self._autoRestartSec--;
      if (self._autoRestartSec <= 0) {
        clearInterval(self._autoRestartTimer);
        self._autoRestartTimer = null;
        self.reset();
        self.start();
      } else if (secEl) {
        secEl.textContent = origText + ' · ' + self._autoRestartSec + 's 后重开';
      }
    }, 1000);
  }
  // ── 改进的恐龙像素艺术绘制 ──
  // 参数：state = { jumping, dead, blinking, runFrame }
  drawDino(ctx, x, y, state) {
    var bodyColor = state.dead ? '#6e7681' : '#58a6ff';
    var detailColor = state.dead ? '#8b949e' : '#388bfd';
    var bellyColor = state.dead ? '#484f58' : '#a371f7';
    var eyeWhite = '#ffffff';
    var pupilColor = state.dead ? '#f85149' : '#0d1117';

    // ── 尾巴 ──
    ctx.fillStyle = bodyColor;
    ctx.fillRect(x - 6, y + 10, 6, 4);
    ctx.fillRect(x - 10, y + 12, 4, 3);

    // ── 身体 ──
    ctx.fillStyle = bodyColor;
    ctx.fillRect(x + 2, y + 8, 18, 14);          // 身体主体
    ctx.fillStyle = bellyColor;
    ctx.fillRect(x + 4, y + 14, 14, 6);           // 腹部（紫色肚子）
    ctx.fillStyle = detailColor;
    ctx.fillRect(x + 4, y + 9, 14, 1);            // 背部条纹
    ctx.fillRect(x + 8, y + 9, 2, 2);             // 背鳞

    // ── 头部 ──
    ctx.fillStyle = bodyColor;
    ctx.fillRect(x + 14, y - 2, 14, 12);          // 头主体
    ctx.fillRect(x + 26, y + 2, 4, 5);            // 嘴部突出
    ctx.fillRect(x + 12, y, 4, 4);                // 后脑

    // ── 眼睛 ──
    if (state.dead) {
      // X 眼（死亡）
      ctx.fillStyle = '#f85149';
      ctx.fillRect(x + 22, y + 2, 1, 1);
      ctx.fillRect(x + 24, y + 2, 1, 1);
      ctx.fillRect(x + 23, y + 3, 1, 1);
      ctx.fillRect(x + 22, y + 4, 1, 1);
      ctx.fillRect(x + 24, y + 4, 1, 1);
    } else if (state.blinking) {
      // 闭眼（眨眼）
      ctx.fillStyle = detailColor;
      ctx.fillRect(x + 21, y + 3, 5, 1);
    } else {
      // 正常睁眼
      ctx.fillStyle = eyeWhite;
      ctx.fillRect(x + 21, y + 2, 5, 3);
      ctx.fillStyle = pupilColor;
      ctx.fillRect(x + 23, y + 3, 2, 2);
    }

    // ── 嘴巴 ──
    ctx.fillStyle = state.dead ? '#f85149' : '#0d1117';
    if (state.dead) {
      // 死亡张嘴
      ctx.fillRect(x + 24, y + 6, 4, 2);
    } else {
      // 正常闭嘴
      ctx.fillRect(x + 24, y + 7, 4, 1);
    }

    // ── 腿部（动画核心）──
    ctx.fillStyle = bodyColor;
    if (state.jumping) {
      // 跳跃：双腿伸直向下
      ctx.fillRect(x + 4, y + 22, 4, 7);
      ctx.fillRect(x + 14, y + 22, 4, 7);
      // 跳跃时尾巴翘起
      ctx.fillStyle = detailColor;
      ctx.fillRect(x - 10, y + 9, 4, 3);
    } else if (state.dead) {
      // 死亡：腿趴下
      ctx.fillRect(x + 4, y + 22, 4, 3);
      ctx.fillRect(x + 14, y + 22, 4, 3);
    } else {
      // 跑步：双腿交替（每 6 帧切换）
      var step = Math.floor(state.runFrame / 6) % 2;
      if (step === 0) {
        ctx.fillRect(x + 4, y + 22, 4, 8);        // 左腿前伸
        ctx.fillRect(x + 14, y + 22, 4, 5);      // 右腿收起
      } else {
        ctx.fillRect(x + 4, y + 22, 4, 5);       // 左腿收起
        ctx.fillRect(x + 14, y + 22, 4, 8);       // 右腿前伸
      }
    }

    // ── 手臂 ──
    ctx.fillStyle = detailColor;
    if (!state.dead) {
      ctx.fillRect(x + 16, y + 12, 3, 4);        // 小前爪
    }
  }
  draw() {
    var ctx = this.ctx;
    ctx.fillStyle = '#0a0e14';
    ctx.fillRect(0, 0, this.W, this.H);
    // 地面
    ctx.strokeStyle = '#30363d';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(0, this.groundY);
    ctx.lineTo(this.W, this.groundY);
    ctx.stroke();
    // 地面虚线
    ctx.setLineDash([8, 12]);
    ctx.beginPath();
    ctx.moveTo(0, this.groundY + 8);
    ctx.lineTo(this.W, this.groundY + 8);
    ctx.stroke();
    ctx.setLineDash([]);
    // 云
    ctx.fillStyle = '#8b949e';
    for (var i = 0; i < this.clouds.length; i++) {
      var cl = this.clouds[i];
      ctx.fillRect(cl.x, cl.y, cl.w, 6);
      ctx.fillRect(cl.x + 6, cl.y - 4, cl.w - 12, 4);
      ctx.fillRect(cl.x + 12, cl.y, cl.w - 24, 4);
    }
    // 仙人掌（改进造型）
    for (var j = 0; j < this.cacti.length; j++) {
      var ca = this.cacti[j];
      ctx.fillStyle = '#3fb950';
      ctx.fillRect(ca.x, ca.y, ca.w, ca.h);
      // 仙人掌侧枝
      ctx.fillRect(ca.x - 4, ca.y + 4, 4, 8);
      ctx.fillRect(ca.x + ca.w, ca.y + 6, 4, 6);
      // 顶部小花
      ctx.fillStyle = '#f85149';
      ctx.fillRect(ca.x + Math.floor(ca.w / 2), ca.y - 2, 3, 3);
    }
    // 恐龙（改进造型 + 动画）
    var d = this.dino;
    var state = {
      jumping: d.jumping,
      dead: this.gameOver,
      blinking: this.blinking,
      runFrame: this.runFrame
    };
    this.drawDino(ctx, d.x, d.y, state);

    // 未开始时的提示
    if (!this.started && !this.gameOver) {
      ctx.fillStyle = 'rgba(0, 0, 0, 0.3)';
      ctx.fillRect(0, 0, this.W, this.H);
    }
    // GAME OVER
    if (this.gameOver) {
      ctx.fillStyle = 'rgba(0, 0, 0, 0.6)';
      ctx.fillRect(0, 0, this.W, this.H);
      ctx.fillStyle = '#f85149';
      ctx.font = 'bold 22px Consolas, monospace';
      ctx.textAlign = 'center';
      ctx.fillText('GAME OVER', this.W / 2, this.H / 2 - 10);
      ctx.fillStyle = '#c9d1d9';
      ctx.font = '13px Consolas, monospace';
      ctx.fillText('2 秒后自动重开（或按 空格 / 点击 立即开始）', this.W / 2, this.H / 2 + 16);
    }
  }
}
</script>
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
    --bg-elevated: #1c2333;
    --border: #30363d;
    --text: #c9d1d9;
    --text-dim: #8b949e;
    --accent: #58a6ff;
    --accent-cyan: #39d0d8;
    --accent-green: #3fb950;
    --accent-orange: #d2991d;
    --accent-purple: #a371f7;
    --accent-red: #f85149;
    --accent-glow: rgba(88, 166, 255, 0.4);
    --gradient-brand: linear-gradient(135deg, #58a6ff 0%, #a371f7 100%);
    --gradient-radar: linear-gradient(90deg, #39d0d8, #58a6ff);
    --shadow-glow: 0 0 20px rgba(88, 166, 255, 0.3);
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
    flex-wrap: wrap;
}}
.top-brand-title {{
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 100%;
}}
.top-brand-sub {{
    display: block;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 100%;
}}
.basic-sub-banner {{
    max-width: 1100px;
    margin: 16px auto 20px;
    padding: 14px 20px;
    background: linear-gradient(135deg, rgba(88,166,255,0.08), rgba(163,113,247,0.08));
    border: 1px solid var(--accent);
    border-radius: 12px;
    text-align: center;
}}
.basic-sub-btn {{
    padding: 8px 20px;
    border-radius: 8px;
    border: none;
    background: linear-gradient(90deg, var(--accent), var(--accent-purple));
    color: #fff;
    cursor: pointer;
    font-size: 0.9em;
    font-weight: 600;
    transition: transform 0.15s, box-shadow 0.15s;
}}
.basic-sub-btn:hover {{
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(88,166,255,0.3);
}}
@media (max-width: 640px) {{
    .top-bar {{
        flex-direction: column;
        align-items: stretch;
        gap: 8px;
        padding: 10px 14px;
    }}
    .top-bar .actions {{
        justify-content: flex-start;
    }}
    .top-brand-sub {{
        display: none;
    }}
    .scan-pulse {{
        display: none;
    }}
    .tab-bar {{
        padding: 8px 10px;
        overflow-x: auto;
        flex-wrap: nowrap;
        -webkit-overflow-scrolling: touch;
        scrollbar-width: none;
    }}
    .tab-bar::-webkit-scrollbar {{
        display: none;
    }}
    .tab {{
        padding: 6px 12px;
        font-size: 0.78em;
        white-space: nowrap;
    }}
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
    transition: opacity 0.3s ease;
}}
.fade-in {{
    animation: fadeInUp 0.4s ease;
}}
.content-area .repo-card,
.content-area .custom-card,
.content-area .section-card {{
    border: 1px solid var(--border);
    border-radius: 12px;
    transition: border-color 0.25s, box-shadow 0.25s;
}}
.content-area .repo-card:hover,
.content-area .custom-card:hover,
.content-area .section-card:hover {{
    border-color: var(--accent);
    box-shadow: 0 0 20px rgba(88, 166, 255, 0.15);
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
.dimensions {{ margin-top: 8px; }}
.dimensions.collapse .dim-body {{ display: none; }}
.dimensions .dim-title {{
    cursor: pointer;
    user-select: none;
    padding: 4px 0;
    transition: color 0.2s;
}}
.dimensions .dim-title:hover {{ color: var(--accent); }}
.dimensions .dim-toggle {{
    float: right;
    transition: transform 0.2s;
    font-size: 0.8em;
    opacity: 0.6;
}}
.dimensions:not(.collapse) .dim-toggle {{ transform: rotate(180deg); }}
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

/* === 自定义日报样式 === */
.custom-container {{ max-width: 1100px; margin: 0 auto; }}
.report-header {{
    text-align: center;
    padding: 24px 16px 16px;
    border-bottom: 1px solid var(--border);
    margin-bottom: 20px;
}}
.report-header h1 {{
    font-size: 1.6em;
    color: var(--text);
    margin-bottom: 8px;
}}
.report-header .date {{
    color: var(--accent);
    font-size: 0.7em;
    font-weight: normal;
}}
.report-meta {{
    color: var(--text-dim);
    font-size: 0.8em;
}}
.summary-bar {{
    display: flex;
    gap: 12px;
    justify-content: center;
    flex-wrap: wrap;
    margin-bottom: 24px;
}}
.summary-item {{
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 12px 20px;
    text-align: center;
    min-width: 100px;
    transition: all 0.2s ease;
    cursor: default;
}}
.summary-item:hover {{
    border-color: var(--accent);
    background: rgba(88, 166, 255, 0.04);
}}
.summary-item .num {{
    display: block;
    font-size: 1.6em;
    font-weight: 600;
    color: var(--accent);
}}
.summary-item .label {{
    display: block;
    font-size: 0.75em;
    color: var(--text-dim);
    margin-top: 4px;
}}
.report-section {{
    margin-bottom: 32px;
    padding: 20px;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 12px;
}}
.report-section h2 {{
    font-size: 1.2em;
    color: var(--text);
    margin-bottom: 6px;
    display: flex;
    align-items: center;
    gap: 8px;
}}
.report-section .icon {{ font-size: 1.1em; }}
.report-section .subtitle {{
    color: var(--text-dim);
    font-size: 0.85em;
    margin-bottom: 16px;
    padding-bottom: 12px;
    border-bottom: 1px dashed var(--border);
}}
/* === 统一状态标识 === */
.status-indicator {{
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 0.78em;
    padding: 2px 8px;
    border-radius: 10px;
    white-space: nowrap;
}}
.status-indicator .dot {{
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
}}
.status-active {{ background: rgba(63, 185, 80, 0.12); color: var(--accent-green); }}
.status-active .dot {{ background: var(--accent-green); }}
.status-moderate {{ background: rgba(210, 153, 29, 0.12); color: var(--accent-orange); }}
.status-moderate .dot {{ background: var(--accent-orange); }}
.status-inactive {{ background: rgba(248, 81, 73, 0.12); color: var(--accent-red); }}
.status-inactive .dot {{ background: var(--accent-red); }}
.status-archived {{ background: rgba(139, 148, 158, 0.12); color: var(--text-dim); }}
.status-archived .dot {{ background: var(--text-dim); }}

/* === 统一标签胶囊 === */
.tag-capsule {{
    display: inline-block;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 0.72em;
    font-weight: 500;
    line-height: 1.5;
    white-space: nowrap;
}}
.tag-new {{ background: rgba(255, 159, 28, 0.15); color: #ff9f1c; border: 1px solid rgba(255, 159, 28, 0.3); }}
.tag-focus {{ background: rgba(88, 166, 255, 0.12); color: var(--accent); border: 1px solid rgba(88, 166, 255, 0.25); }}
.tag-burst {{ background: rgba(210, 153, 29, 0.12); color: var(--accent-orange); border: 1px solid rgba(210, 153, 29, 0.25); }}
.tag-quality {{ background: rgba(63, 185, 80, 0.12); color: var(--accent-green); border: 1px solid rgba(63, 185, 80, 0.25); }}
.tag-trap {{ background: rgba(248, 81, 73, 0.12); color: var(--accent-red); border: 1px solid rgba(248, 81, 73, 0.25); }}
.tag-longterm {{ background: rgba(63, 185, 80, 0.12); color: var(--accent-green); border: 1px solid rgba(63, 185, 80, 0.25); }}

/* === 统一评分徽章 === */
.score-badge {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 6px;
    font-size: 0.75em;
    font-weight: 600;
    background: rgba(255, 255, 255, 0.04);
}}
.score-burst {{ color: var(--accent-orange); }}
.score-quality {{ color: var(--accent-green); }}
.score-ai {{ color: var(--accent-purple); }}

/* === 统一指标行 === */
.metric-row {{
    display: flex;
    gap: 14px;
    flex-wrap: wrap;
    align-items: center;
    font-size: 0.82em;
    color: var(--text-dim);
    margin-bottom: 8px;
}}
.metric-item {{
    display: inline-flex;
    align-items: center;
    gap: 4px;
}}

/* === 项目类型背景色 === */
.card-burst {{ background: rgba(210, 153, 29, 0.03); }}
.card-longterm {{ background: rgba(63, 185, 80, 0.03); }}

.custom-card {{
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 16px;
    margin-bottom: 12px;
    transition: all 0.2s ease;
}}
.custom-card:hover {{
    border-color: var(--accent);
    transform: translateY(-2px);
    box-shadow: 0 4px 16px rgba(88, 166, 255, 0.1);
}}
.custom-card .repo-header {{
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 8px;
}}
.custom-card .repo-rank {{
    background: var(--accent);
    color: #fff;
    border-radius: 6px;
    padding: 2px 8px;
    font-size: 0.8em;
    font-weight: 600;
}}
.custom-card .repo-name {{
    color: var(--accent);
    text-decoration: none;
    font-weight: 600;
    font-size: 1em;
}}
.custom-card .repo-name:hover {{ text-decoration: underline; }}
.custom-card .repo-desc {{
    color: var(--text);
    font-size: 0.88em;
    line-height: 1.5;
    margin-bottom: 10px;
}}
.custom-card .repo-stats {{
    display: flex;
    gap: 14px;
    flex-wrap: wrap;
    align-items: center;
    color: var(--text-dim);
    font-size: 0.82em;
    margin-bottom: 8px;
}}
.score-badges {{
    display: flex;
    gap: 6px;
    margin-bottom: 10px;
    flex-wrap: wrap;
}}
.badge {{
    padding: 3px 10px;
    border-radius: 12px;
    font-size: 0.75em;
    font-weight: 500;
}}
.badge-quality {{
    background: rgba(63, 185, 80, 0.15);
    color: var(--accent-green);
    border: 1px solid rgba(63, 185, 80, 0.3);
}}
.badge-hot {{
    background: rgba(255, 159, 28, 0.15);
    color: #ff9f1c;
    border: 1px solid rgba(255, 159, 28, 0.3);
}}
.health-bar {{
    color: var(--text-dim);
    font-size: 0.78em;
    padding: 6px 0;
    border-top: 1px dashed var(--border);
    margin-bottom: 10px;
}}
.tag-bar {{
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
    margin-bottom: 12px;
}}
.eco-tag {{
    background: rgba(88, 166, 255, 0.1);
    color: var(--accent);
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 0.72em;
    border: 1px solid rgba(88, 166, 255, 0.2);
}}
.repo-tags {{
    margin-top: 8px;
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
}}
.repo-scores {{
    margin-top: 8px;
    color: var(--accent);
    font-size: 0.8em;
    font-weight: 500;
}}
.health-meta {{
    color: var(--text-dim);
    font-size: 0.78em;
    margin-left: auto;
}}
.repo-stats {{
    display: flex;
    flex-wrap: wrap;
    gap: 14px;
    align-items: center;
    margin-top: 8px;
    font-size: 0.82em;
    color: var(--text-dim);
}}
.dimensions {{
    background: rgba(255, 255, 255, 0.02);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 0;
    margin-top: 10px;
    overflow: hidden;
}}
.dim-title {{
    color: var(--accent);
    font-size: 0.85em;
    font-weight: 600;
    padding: 8px 12px;
    background: rgba(88, 166, 255, 0.05);
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    gap: 6px;
}}
.dim-item {{
    display: grid;
    grid-template-columns: 24px 80px 1fr;
    gap: 8px;
    align-items: start;
    padding: 8px 12px;
    font-size: 0.82em;
    line-height: 1.5;
    border-bottom: 1px solid rgba(48, 54, 61, 0.5);
}}
.dim-item:last-child {{ border-bottom: none; }}
.dim-icon {{ font-size: 1em; }}
.dim-label {{
    color: var(--text-dim);
    font-weight: 500;
}}
.dim-text {{
    color: var(--text);
    word-break: break-word;
}}
.dashboard-block {{
    padding: 20px;
}}
.dashboard-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 12px;
    margin-bottom: 20px;
}}
.dashboard-item {{
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
    text-align: center;
}}
.dash-num {{
    font-size: 1.8em;
    font-weight: 700;
    color: var(--accent);
}}
.dash-label {{
    font-size: 0.78em;
    color: var(--text-dim);
    margin-top: 4px;
}}
.lang-distribution {{
    margin-top: 16px;
    padding-top: 16px;
    border-top: 1px dashed var(--border);
}}
.lang-distribution h3 {{
    font-size: 0.95em;
    color: var(--text);
    margin-bottom: 12px;
}}
.lang-bar-item {{
    display: grid;
    grid-template-columns: 80px 1fr 40px;
    gap: 10px;
    align-items: center;
    margin-bottom: 8px;
    font-size: 0.82em;
}}
.lang-name {{ color: var(--text); }}
.lang-bar-bg {{
    background: var(--bg);
    border-radius: 4px;
    height: 8px;
    overflow: hidden;
    border: 1px solid var(--border);
}}
.lang-bar-fill {{
    background: linear-gradient(90deg, var(--accent), #79c0ff);
    height: 100%;
    transition: width 0.5s;
}}
.lang-count {{
    color: var(--text-dim);
    text-align: right;
}}
.query-info {{
    margin-top: 16px;
    padding: 12px;
    background: var(--bg);
    border-radius: 8px;
    font-size: 0.82em;
    color: var(--text-dim);
    line-height: 1.7;
}}
.query-info strong {{ color: var(--text); }}
footer {{
    text-align: center;
    color: var(--text-dim);
    font-size: 0.78em;
    padding: 24px 16px;
    border-top: 1px solid var(--border);
    margin-top: 32px;
}}
@media (max-width: 768px) {{
    .dim-item {{ grid-template-columns: 24px 70px 1fr; gap: 6px; font-size: 0.78em; }}
    .lang-bar-item {{ grid-template-columns: 60px 1fr 30px; }}
    .summary-item {{ min-width: 80px; padding: 10px 14px; }}
    .summary-item .num {{ font-size: 1.3em; }}
}}
.health-progress {{
    margin-top: 6px;
    padding: 8px 12px;
    border-top: 1px dashed var(--border);
}}
.health-progress-bar {{
    height: 6px;
    border-radius: 3px;
    background: var(--bg);
    overflow: hidden;
    margin-top: 4px;
}}
.health-progress-fill {{
    height: 100%;
    border-radius: 3px;
    transition: width 0.5s ease;
}}
.health-progress-fill.active {{ background: var(--accent-green); }}
.health-progress-fill.moderate {{ background: var(--accent-orange); }}
.health-progress-fill.inactive {{ background: var(--accent-red); }}
.health-progress-label {{
    font-size: 0.75em;
    color: var(--text-dim);
    margin-top: 4px;
}}
.empty-state {{
    text-align: center;
    padding: 20px;
    color: var(--text-dim);
    font-size: 0.85em;
    border: 1px dashed var(--border);
    border-radius: 8px;
    margin: 8px 0;
}}
.source-banner {{
    display: inline-block;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 0.72em;
    font-weight: 500;
    margin-bottom: 8px;
}}
.source-high-value {{
    background: rgba(63, 185, 80, 0.1);
    border: 1px solid rgba(63, 185, 80, 0.3);
    color: var(--accent-green);
}}
.source-basic-top {{
    background: rgba(255, 159, 28, 0.1);
    border: 1px solid rgba(255, 159, 28, 0.3);
    color: #ff9f1c;
}}
.fallback-banner {{
    background: rgba(88, 166, 255, 0.08);
    border: 1px solid rgba(88, 166, 255, 0.25);
    color: var(--accent);
    padding: 12px 16px;
    border-radius: 8px;
    margin-bottom: 16px;
    font-size: 0.85em;
    line-height: 1.6;
}}
/* === 卡片悬停增强 === */
.custom-card, .summary-item {{
    transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
}}
.custom-card:hover {{
    transform: translateY(-2px);
    box-shadow: 0 8px 24px rgba(0,0,0,0.3);
    border-color: var(--accent);
}}
.summary-item:hover {{
    transform: translateY(-2px);
    box-shadow: 0 4px 16px rgba(88,166,255,0.15);
}}
/* === 内容区过渡 === */
.content-area {{
    transition: opacity 0.3s ease;
}}
/* === 数据面板状态卡片 === */
.status-card {{
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px;
    text-align: center;
    transition: all 0.2s ease;
}}
.status-card:hover {{
    border-color: var(--accent);
    transform: translateY(-2px);
}}
.status-card .icon {{
    font-size: 2em;
    margin-bottom: 8px;
}}
.status-card .num {{
    font-size: 1.8em;
    font-weight: 700;
    color: var(--accent);
}}
.status-card .label {{
    font-size: 0.8em;
    color: var(--text-dim);
    margin-top: 4px;
}}
.status-card .badge-ok {{
    color: var(--accent-green);
    font-size: 1.4em;
    font-weight: 700;
}}
.status-card .badge-warn {{
    color: var(--accent-orange);
    font-size: 1.4em;
    font-weight: 700;
}}
/* === 订阅条目 === */
.sub-item {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 14px 16px;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 10px;
    margin-bottom: 8px;
    transition: all 0.2s;
}}
.sub-item:hover {{
    border-color: var(--accent);
}}
.sub-item .sub-info {{
    display: flex;
    align-items: center;
    gap: 12px;
}}
.sub-item .sub-type {{
    padding: 2px 10px;
    border-radius: 20px;
    font-size: 0.75em;
    font-weight: 600;
}}
.sub-type.basic {{
    background: rgba(88,166,255,0.15);
    color: var(--accent);
}}
.sub-type.custom {{
    background: rgba(163,113,247,0.15);
    color: var(--accent-purple);
}}
/* === 历史条目 === */
.history-item {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 16px;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 10px;
    margin-bottom: 6px;
    cursor: pointer;
    transition: all 0.2s;
}}
.history-item:hover {{
    border-color: var(--accent);
    background: rgba(88,166,255,0.04);
}}
/* === 淡入动画 === */
@keyframes fadeIn {{
    from {{ opacity: 0; transform: translateY(8px); }}
    to {{ opacity: 1; transform: translateY(0); }}
}}
.fade-in {{
    animation: fadeIn 0.3s ease;
}}

/* ═══ 架构 Tab 样式 ═══ */
.arch-container {{
    padding: 24px 20px;
    max-width: 1200px;
    margin: 0 auto;
}}
.arch-hero {{
    text-align: center;
    padding: 36px 24px;
    background: linear-gradient(135deg, rgba(88,166,255,0.10) 0%, rgba(163,113,247,0.10) 50%, rgba(63,185,80,0.10) 100%);
    border: 1px solid var(--border);
    border-radius: 16px;
    margin-bottom: 28px;
    position: relative;
    overflow: hidden;
}}
.arch-hero::before {{
    content: '';
    position: absolute;
    top: -50%; left: -50%;
    width: 200%; height: 200%;
    background: radial-gradient(circle at center, rgba(88,166,255,0.08) 0%, transparent 50%);
    animation: heroGlow 8s ease-in-out infinite alternate;
    pointer-events: none;
}}
@keyframes heroGlow {{
    from {{ transform: rotate(0deg) scale(1); }}
    to {{ transform: rotate(180deg) scale(1.2); }}
}}
.arch-hero-tag {{
    display: inline-block;
    padding: 4px 12px;
    background: var(--accent);
    color: #fff;
    border-radius: 12px;
    font-size: 0.78em;
    margin-bottom: 12px;
    font-weight: 600;
    position: relative;
    z-index: 1;
}}
.arch-hero-title {{
    font-size: 2.2em;
    margin: 0 0 8px;
    background: linear-gradient(90deg, var(--accent), var(--accent-purple), var(--accent-green));
    -webkit-background-clip: text;
    background-clip: text;
    -webkit-text-fill-color: transparent;
    font-weight: 800;
    position: relative;
    z-index: 1;
}}
.arch-hero-subtitle {{
    color: var(--text-dim);
    font-size: 1.05em;
    margin: 0 0 24px;
    position: relative;
    z-index: 1;
}}
.arch-hero-stats {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 16px;
    max-width: 720px;
    margin: 0 auto;
    position: relative;
    z-index: 1;
}}
.hero-stat {{
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 14px 8px;
    transition: transform 0.2s;
}}
.hero-stat:hover {{ transform: translateY(-2px); border-color: var(--accent); }}
.hero-stat .num {{
    display: block;
    font-size: 1.6em;
    font-weight: 700;
    color: var(--accent);
}}
.hero-stat .lbl {{
    display: block;
    color: var(--text-dim);
    font-size: 0.78em;
    margin-top: 2px;
}}
.arch-section {{
    margin-bottom: 28px;
}}
.arch-section-title {{
    color: var(--text);
    font-size: 1.15em;
    margin: 0 0 16px;
    display: flex;
    align-items: center;
    gap: 10px;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--border);
}}
.arch-num {{
    display: inline-flex;
    width: 28px; height: 28px;
    align-items: center; justify-content: center;
    background: var(--accent);
    color: #fff;
    border-radius: 50%;
    font-size: 0.85em;
    font-weight: 700;
}}
.arch-steps {{
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 12px;
    flex-wrap: wrap;
}}
.arch-step {{
    flex: 1;
    min-width: 200px;
    max-width: 280px;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 18px 16px;
    text-align: center;
    cursor: pointer;
    transition: all 0.25s;
}}
.arch-step:hover {{
    transform: translateY(-3px);
    border-color: var(--accent);
    box-shadow: 0 6px 20px rgba(88,166,255,0.15);
}}
.arch-step-icon {{ font-size: 1.8em; margin-bottom: 8px; }}
.arch-step-title {{ color: var(--text); font-weight: 600; margin-bottom: 4px; }}
.arch-step-desc {{ color: var(--text-dim); font-size: 0.82em; }}
.arch-step-arrow {{
    color: var(--accent);
    font-size: 1.6em;
    font-weight: 300;
}}
.arch-pipeline {{
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 6px;
    padding: 16px;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 12px;
    justify-content: center;
}}
.pipe-step {{
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 10px 12px;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    min-width: 110px;
    transition: all 0.2s;
}}
.pipe-step:hover {{
    border-color: var(--accent);
    transform: scale(1.04);
}}
.pipe-icon {{ font-size: 1.4em; margin-bottom: 4px; }}
.pipe-name {{ font-size: 0.76em; color: var(--text); text-align: center; line-height: 1.2; }}
.pipe-arrow {{
    color: var(--accent);
    font-size: 1.2em;
}}
.arch-note {{
    color: var(--text-dim);
    font-size: 0.82em;
    margin-top: 10px;
    padding: 8px 12px;
    background: rgba(88,166,255,0.05);
    border-left: 3px solid var(--accent);
    border-radius: 4px;
}}
.arch-note code {{
    background: var(--code-bg);
    padding: 1px 6px;
    border-radius: 3px;
    color: var(--accent-green);
    font-size: 0.95em;
}}
.arch-tech-grid {{
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 12px;
}}
.tech-card {{
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px;
    display: flex;
    align-items: flex-start;
    gap: 10px;
    transition: all 0.2s;
}}
.tech-card:hover {{
    transform: translateX(2px);
    border-color: var(--accent);
}}
.tech-icon {{ font-size: 1.5em; flex-shrink: 0; }}
.tech-name {{ color: var(--text); font-weight: 600; font-size: 0.95em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.tech-desc {{ color: var(--text-dim); font-size: 0.78em; margin-top: 4px; word-break: keep-all; line-height: 1.4; }}
.arch-security {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 12px;
}}
.sec-card {{
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px;
    border-left: 3px solid var(--accent-green);
}}
.sec-header {{
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 8px;
}}
.sec-icon {{ font-size: 1.3em; }}
.sec-title {{ color: var(--text); font-weight: 600; font-size: 0.98em; }}
.sec-desc {{
    color: var(--text-dim);
    font-size: 0.82em;
    line-height: 1.6;
    margin: 0;
}}
.sec-desc code {{
    background: var(--code-bg);
    padding: 1px 6px;
    border-radius: 3px;
    color: var(--accent-green);
    font-size: 0.92em;
}}
.arch-llm-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
    gap: 10px;
}}
.llm-card {{
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px 10px;
    text-align: center;
    transition: all 0.2s;
}}
.llm-card:hover {{
    transform: translateY(-2px);
    border-color: var(--accent-purple);
    box-shadow: 0 4px 12px rgba(163,113,247,0.15);
}}
.llm-logo {{ font-size: 1.8em; margin-bottom: 6px; }}
.llm-name {{ color: var(--text); font-weight: 600; font-size: 0.92em; }}
.llm-model {{ color: var(--text-dim); font-size: 0.74em; margin-top: 2px; font-family: monospace; }}
.arch-topics {{
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
}}
.topic-chip {{
    display: inline-block;
    padding: 5px 11px;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 14px;
    color: var(--text);
    font-size: 0.82em;
    transition: all 0.2s;
    cursor: default;
}}
.topic-chip:hover {{
    border-color: var(--accent);
    color: var(--accent);
    transform: translateY(-1px);
}}
.arch-tunnel {{
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 16px 20px;
    margin-bottom: 12px;
}}
.tunnel-row {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 0;
    border-bottom: 1px solid var(--border);
    flex-wrap: wrap;
    gap: 8px;
}}
.tunnel-row:last-child {{ border-bottom: none; }}
.tunnel-label {{
    color: var(--text-dim);
    font-size: 0.88em;
}}
.tunnel-url {{
    color: var(--accent);
    font-family: monospace;
    font-size: 0.86em;
    word-break: break-all;
    text-decoration: none;
}}
.tunnel-url:hover {{ text-decoration: underline; }}
.tunnel-status {{
    padding: 3px 10px;
    border-radius: 12px;
    font-size: 0.82em;
    font-weight: 600;
}}
.tunnel-status.healthy {{ background: rgba(63,185,80,0.18); color: var(--accent-green); }}
.tunnel-status.recovering {{ background: rgba(210,153,29,0.18); color: var(--accent-orange); }}
.tunnel-status.down {{ background: rgba(248,81,73,0.18); color: var(--accent-red); }}
.tunnel-status.unknown {{ background: rgba(139,148,158,0.18); color: var(--text-dim); }}
.tunnel-metric {{
    color: var(--text);
    font-weight: 600;
    font-size: 0.95em;
}}

/* 响应式补充 */
@media (max-width: 768px) {{
    .arch-hero-title {{ font-size: 1.6em; }}
    .arch-steps {{ flex-direction: column; }}
    .arch-step-arrow {{ transform: rotate(90deg); }}
    .arch-step {{ max-width: 100%; }}
    .pipe-step {{ min-width: 90px; padding: 8px 6px; }}
    .pipe-name {{ font-size: 0.7em; }}
    .arch-tech-grid {{ grid-template-columns: repeat(2, 1fr); }}
}}
@media (max-width: 560px) {{
    .arch-tech-grid {{ grid-template-columns: 1fr; }}
}}

/* ═══ 骨架屏（加载占位） ═══ */
.skeleton-card {{
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 40px;
    text-align: center;
    color: var(--text-dim);
    position: relative;
    overflow: hidden;
}}
.skeleton-card::after {{
    content: '';
    position: absolute;
    top: 0; left: -100%;
    width: 100%; height: 100%;
    background: linear-gradient(90deg, transparent, rgba(88,166,255,0.08), transparent);
    animation: skeletonShimmer 1.5s infinite;
}}
@keyframes skeletonShimmer {{
    0% {{ left: -100%; }}
    100% {{ left: 100%; }}
}}

/* ═══ Dashboard URL 监控卡片 ═══ */
.tunnel-card-dash {{
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-left: 4px solid var(--accent-purple);
    border-radius: 12px;
    padding: 18px 20px;
    margin-bottom: 24px;
    animation: fadeInUp 0.4s ease;
}}
.tunnel-card-head {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 8px;
    margin-bottom: 14px;
    padding-bottom: 12px;
    border-bottom: 1px solid var(--border);
}}
.tunnel-card-title {{
    color: var(--text);
    font-weight: 700;
    font-size: 1.05em;
}}
.tunnel-card-body {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 14px;
    margin-bottom: 12px;
}}
.tunnel-metric {{
    display: flex;
    flex-direction: column;
    gap: 4px;
}}
.tunnel-metric-label {{
    color: var(--text-dim);
    font-size: 0.78em;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}
.tunnel-url {{
    color: var(--accent);
    text-decoration: none;
    word-break: break-all;
    font-size: 0.92em;
}}
.tunnel-url:hover {{ text-decoration: underline; }}
.tunnel-num {{
    color: var(--text);
    font-weight: 600;
    font-size: 1.05em;
}}
.tunnel-card-foot {{
    color: var(--text-dim);
    font-size: 0.8em;
    padding-top: 10px;
    border-top: 1px solid var(--border);
}}
@keyframes fadeInUp {{
    from {{ opacity: 0; transform: translateY(8px); }}
    to {{ opacity: 1; transform: translateY(0); }}
}}
.radar-sweep {{
    transform-origin: 19px 19px;
    animation: radarSweep 3s linear infinite;
}}
@keyframes radarSweep {{
    from {{ transform: rotate(0deg); }}
    to {{ transform: rotate(360deg); }}
}}
.scan-pulse {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 10px;
    border-radius: 12px;
    background: rgba(63, 185, 80, 0.1);
    border: 1px solid rgba(63, 185, 80, 0.3);
    font-size: 0.75em;
    color: var(--accent-green);
}}
.scan-pulse::before {{
    content: '';
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--accent-green);
    animation: scanPulse 1.6s ease-in-out infinite;
}}
@keyframes scanPulse {{
    0%, 100% {{ opacity: 1; transform: scale(1); box-shadow: 0 0 0 0 rgba(63, 185, 80, 0.6); }}
    50% {{ opacity: 0.7; transform: scale(1.2); box-shadow: 0 0 0 6px rgba(63, 185, 80, 0); }}
}}
.tab {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    transition: all 0.2s;
}}
.tab:hover {{
    box-shadow: 0 2px 0 0 var(--accent);
}}
.tab.active {{
    background: var(--gradient-brand);
    box-shadow: var(--shadow-glow);
}}
</style>
</head>
<body>
<div class="top-bar">
    <div style="display:flex;align-items:center;gap:12px;flex:1 1 240px;min-width:200px">
        <div style="position:relative;width:38px;height:38px;flex-shrink:0">
            <svg width="38" height="38" viewBox="0 0 38 38" fill="none" style="position:absolute;top:0;left:0">
                <circle cx="19" cy="19" r="17" stroke="#58a6ff" stroke-width="1" opacity="0.2"/>
                <circle cx="19" cy="19" r="13" stroke="#58a6ff" stroke-width="1" opacity="0.3"/>
                <circle cx="19" cy="19" r="9" stroke="#58a6ff" stroke-width="1" opacity="0.5"/>
                <line x1="19" y1="2" x2="19" y2="36" stroke="#30363d" stroke-width="0.5"/>
                <line x1="2" y1="19" x2="36" y2="19" stroke="#30363d" stroke-width="0.5"/>
                <circle cx="26" cy="12" r="1.5" fill="#3fb950"/>
                <circle cx="12" cy="25" r="1.5" fill="#a371f7"/>
                <circle cx="25" cy="26" r="1" fill="#d2991d"/>
                <circle cx="19" cy="19" r="2.5" fill="#58a6ff"/>
                <g class="radar-sweep">
                    <path d="M19 19 L19 2 A17 17 0 0 1 30 8 Z" fill="url(#scanGrad)" opacity="0.5"/>
                </g>
                <defs>
                    <linearGradient id="scanGrad" x1="0" y1="0" x2="1" y2="1">
                        <stop offset="0%" stop-color="#39d0d8" stop-opacity="0.6"/>
                        <stop offset="100%" stop-color="#39d0d8" stop-opacity="0"/>
                    </linearGradient>
                </defs>
            </svg>
        </div>
        <div style="min-width:0;flex:1">
            <h1 class="top-brand-title" style="font-size:1.4em;margin:0;color:var(--text);background:linear-gradient(90deg,var(--accent),var(--accent-purple));-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;font-weight:700">GitRadar</h1>
            <span class="top-brand-sub" style="color:var(--text-dim);font-size:0.78em">🏆 TRAE AI 创造力大赛 · GitRadar · GitHub 开源项目雷达</span>
        </div>
    </div>
    <div class="actions">
        <span id="reportDate" style="color:var(--text-dim);font-size:0.85em"></span>
        <span class="scan-pulse">实时扫描中</span>
        <button class="btn" onclick="switchTab('arch')" style="background:var(--bg-card);border:1px solid var(--accent-purple);color:var(--accent-purple)">🏗️ 架构</button>
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

<script>
let currentMode = 'basic';

// 带 AbortController 超时的 fetch 封装（PythonAnywhere 免费版 100 秒限制，设 85 秒兜底）
// 同时实现"软超时恐龙游戏"：超过 20s 后端未响应时显示恐龙游戏作为交互反馈，但 fetch 继续等
var DINO_SOFT_TIMEOUT_MS = 20000;
var _dinoSoftTimer = null;
var _dinoGameInstance = null;

function fetchWithTimeout(url, options, timeoutMs) {{
    timeoutMs = timeoutMs || 85000;
    var controller = new AbortController();
    var signal = controller.signal;
    var opts = Object.assign({{}}, options || {{}}, {{ signal: signal }});
    var timer = setTimeout(function() {{ controller.abort(); }}, timeoutMs);

    // 启动软超时定时器：20s 后显示恐龙游戏（仅当请求耗时较长时）
    _dinoSoftTimer = setTimeout(function() {{
        showDinoFallback('后端正在处理，可能涉及 LLM 调用 / 数据解析。先玩一会儿游戏吧');
    }}, DINO_SOFT_TIMEOUT_MS);

    return fetch(url, opts)
        .then(function(resp) {{
            if (_dinoSoftTimer) {{ clearTimeout(_dinoSoftTimer); _dinoSoftTimer = null; }}
            hideDinoFallback();
            return resp;
        }})
        .catch(function(err) {{
            if (_dinoSoftTimer) {{ clearTimeout(_dinoSoftTimer); _dinoSoftTimer = null; }}
            hideDinoFallback();
            throw err;
        }})
        .finally(function() {{ clearTimeout(timer); }});
}}

function isTimeoutError(e) {{
    return e && (e.name === 'AbortError' || /timeout|aborted/i.test(String(e)));
}}

function switchTab(mode) {{
    currentMode = mode;
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelector(`[data-tab="${{mode}}"]`).classList.add('active');

    if (mode === 'basic') {{
        showSpinner();
        fetchWithTimeout('/api/daily')
            .then(r => r.json())
            .then(data => {{
                var subBanner = '<div class="basic-sub-banner">'
                    + '<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;justify-content:center">'
                    + '<span style="color:var(--text);font-size:0.95em">📬 想每天自动收到这份日报？</span>'
                    + '<button onclick="quickSubscribeBasic()" class="basic-sub-btn">订阅基础日报</button>'
                    + '</div></div>';
                document.getElementById('content').innerHTML = '<div class="fade-in">' + subBanner + data.html + '</div>';
                document.getElementById('reportDate').textContent = '📅 ' + data.date;
                hideSpinner();
            }})
            .catch(e => {{
                var msg = isTimeoutError(e) ? '请求超时，请稍后重试' : '加载失败，请检查网络';
                document.getElementById('content').innerHTML = '<p style="color:#f85149;text-align:center;padding:40px">' + msg + '</p>';
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
    }} else if (mode === 'dashboard') {{
        document.getElementById('content').innerHTML = `{dashboard_placeholder}`;
        loadDashboard();
    }} else if (mode === 'manage') {{
        document.getElementById('content').innerHTML = `{manage_placeholder}`;
        loadSubscriptions();
    }} else if (mode === 'arch') {{
        document.getElementById('content').innerHTML = `{arch_placeholder}`;
        loadArchData();
        loadTunnelStatus();
    }}
}}

function submitCustom() {{
    var q = document.getElementById('customQuery').value.trim();
    if (!q) {{ alert('请输入话题关键词'); return; }}
    var apiKey = localStorage.getItem('llm_api_key') || localStorage.getItem('ds_api_key') || '';
    var provider = localStorage.getItem('llm_provider') || 'deepseek';
    var resultDiv = document.getElementById('customResult');
    resultDiv.innerHTML = '<p style="text-align:center;color:var(--text-dim);padding:30px">🔍 正在解析并生成日报...</p>';
    fetchWithTimeout('/api/custom', {{
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
        var msg;
        if (isTimeoutError(e)) {{
            msg = '⏱️ 生成超时（服务器处理时间过长）。这通常是因为今日数据尚未就绪，请先访问基础日报确认数据已生成后再试。';
        }} else if (/Failed to fetch|NetworkError/i.test(String(e))) {{
            msg = '🌐 网络连接失败，请检查网络后重试。如果反复出现，可能是服务器资源受限，请稍后再试。';
        }} else {{
            msg = '生成失败: ' + e;
        }}
        resultDiv.innerHTML = '<p style="color:#f85149;text-align:center;padding:30px">' + msg + '</p>';
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

function quickSubscribeBasic() {{
    var modal = document.getElementById('subscribeModal');
    if (!modal) return;
    var basicRadio = document.querySelector('input[name="subType"][value="basic"]');
    var customRadio = document.querySelector('input[name="subType"][value="custom"]');
    if (basicRadio) basicRadio.checked = true;
    if (customRadio) customRadio.checked = false;
    var topicSpan = document.getElementById('subCustomTopic');
    if (topicSpan) topicSpan.textContent = '6板块综合日报';
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
    fetchWithTimeout('/api/subscribe', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify(body)
    }})
    .then(r => r.json())
    .then(data => {{
        if (data.ok) {{
            msg.textContent = '✅ ' + data.msg;
            msg.style.color = 'var(--accent-green)';
            setTimeout(closeSubscribeModal, 3000);
        }} else {{
            msg.textContent = '❌ ' + data.msg;
            msg.style.color = 'var(--accent-red)';
        }}
    }})
    .catch(e => {{
        var m = isTimeoutError(e) ? '订阅请求超时，请稍后重试' : ('❌ 订阅失败: ' + e);
        msg.innerHTML = '<span style="color:var(--accent-red)">' + m + '</span>';
    }});
}}

function refreshData() {{
    var btn = event.target;
    var origText = btn.textContent;
    btn.textContent = '⏳ 刷新中...';
    btn.disabled = true;
    showSpinner();
    fetchWithTimeout('/api/refresh')
        .then(r => r.json())
        .then(data => {{
            if (data.html) {{
                document.getElementById('content').innerHTML = '<div class="fade-in">' + data.html + '</div>';
                document.getElementById('reportDate').textContent = '📅 ' + data.date;
                hideSpinner();
                showToast();
                btn.textContent = '✅ 已刷新';
                setTimeout(function() {{ btn.textContent = origText; btn.disabled = false; }}, 2000);
            }} else {{
                hideSpinner();
                btn.textContent = origText;
                btn.disabled = false;
                alert(data.msg || '刷新失败，请等待定时任务运行');
            }}
        }})
        .catch(e => {{
            hideSpinner();
            btn.textContent = origText;
            btn.disabled = false;
            alert(isTimeoutError(e) ? '刷新超时，请稍后重试' : ('刷新失败: ' + e));
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
function toggleDims(el) {{
    el.parentElement.classList.toggle('collapse');
}}

// 初始化 — 自动加载数据
document.addEventListener('DOMContentLoaded', function() {{
    var dateMatch = document.title.match(/\\d{{4}}年\\d{{2}}月\\d{{2}}日/);
    if (dateMatch) document.getElementById('reportDate').textContent = '📅 ' + dateMatch[0];
    showSpinner();
    fetchWithTimeout('/api/daily')
        .then(function(r) {{ return r.json(); }})
        .then(function(data) {{
            document.getElementById('content').innerHTML = data.html;
            document.getElementById('reportDate').textContent = '📅 ' + data.date;
            hideSpinner();
        }})
        .catch(function(e) {{
            var msg = isTimeoutError(e) ? '请求超时，请稍后重试' : '数据加载中，请稍候或点击刷新按钮重试...';
            document.getElementById('content').innerHTML = '<p style="color:var(--text-dim);text-align:center;padding:40px">' + msg + '</p>';
            hideSpinner();
        }});
}});

function loadDashboard() {{
    fetchWithTimeout('/api/status')
        .then(r => r.json())
        .then(data => {{
            var envEnc = data.env_encrypted || {{}};
            var allEnvEnc = Object.keys(envEnc).length > 0 && Object.values(envEnc).every(v => v);
            var subEnc = data.sub_encrypted || {{}};
            var allSubEnc = subEnc.total > 0 && subEnc.emails === subEnc.total;

            var html = '';
            html += '<div class="status-card fade-in"><div class="icon">🔒</div>';
            html += '<div class="' + (allEnvEnc ? 'badge-ok' : 'badge-warn') + '">' + (allEnvEnc ? '✓' : '!') + '</div>';
            html += '<div class="label">.env 加密</div></div>';

            html += '<div class="status-card fade-in"><div class="icon">📧</div>';
            html += '<div class="num">' + (data.subscriber_count || 0) + '</div>';
            html += '<div class="label">订阅者</div></div>';

            html += '<div class="status-card fade-in"><div class="icon">📄</div>';
            html += '<div class="num">' + (data.report_count || 0) + '</div>';
            html += '<div class="label">历史报告</div></div>';

            html += '<div class="status-card fade-in"><div class="icon">📦</div>';
            html += '<div class="num">' + (data.db_repo_count || 0) + '</div>';
            html += '<div class="label">今日项目</div></div>';

            html += '<div class="status-card fade-in"><div class="icon">📅</div>';
            html += '<div class="num" style="font-size:1.1em;">' + (data.latest_report_date || 'N/A') + '</div>';
            html += '<div class="label">最新报告</div></div>';

            html += '<div class="status-card fade-in"><div class="icon">🔑</div>';
            html += '<div class="' + (data.key_file_exists ? 'badge-ok' : 'badge-warn') + '">' + (data.key_file_exists ? '✓' : '✗') + '</div>';
            html += '<div class="label">密钥文件</div></div>';

            document.getElementById('dashboardContent').innerHTML = html;

            // Load tunnel status (URL 监控守护)
            loadTunnelCard();
            // Load history
            return fetchWithTimeout('/api/history');
        }})
        .then(r => r.json())
        .then(data => {{
            var histHtml = '<h3 style="color:var(--text);margin-bottom:12px;font-size:1em;">📂 历史报告</h3>';
            if (!data.history || data.history.length === 0) {{
                histHtml += '<p style="color:var(--text-dim);text-align:center;padding:20px;">暂无历史报告</p>';
            }} else {{
                data.history.forEach(function(h) {{
                    var sizeKb = Math.round(h.size / 1024);
                    histHtml += '<div class="history-item" onclick="loadHistoryReport(\\'' + h.filename + '\\')">';
                    histHtml += '<span style="color:var(--accent);">📅 ' + h.date + '</span>';
                    histHtml += '<span style="color:var(--text-dim);font-size:0.85em;">' + sizeKb + ' KB</span>';
                    histHtml += '</div>';
                }});
            }}
            document.getElementById('historyList').innerHTML = histHtml;
        }})
        .catch(e => {{
            document.getElementById('dashboardContent').innerHTML = '<p style="color:var(--accent-red);text-align:center;padding:40px;">加载失败</p>';
        }});
}}

function loadHistoryReport(filename) {{
    showSpinner();
    fetchWithTimeout('/reports/' + filename)
        .then(r => r.text())
        .then(html => {{
            document.getElementById('content').innerHTML = html;
            hideSpinner();
        }})
        .catch(e => {{
            hideSpinner();
            alert('加载失败: ' + e);
        }});
}}

function loadSubscriptions() {{
    fetchWithTimeout('/api/subscriptions')
        .then(r => r.json())
        .then(data => {{
            var subs = data.subscriptions || [];
            var totalCount = subs.length;
            var basicCount = subs.filter(function(s) {{ return s.type !== 'custom'; }}).length;
            var customCount = subs.filter(function(s) {{ return s.type === 'custom'; }}).length;
            var hasKeyCount = subs.filter(function(s) {{ return s.has_api_key; }}).length;

            var html = '<div style="background:var(--bg-card);border:1px solid var(--border);border-radius:12px;padding:24px 20px;">';
            html += '<div style="display:flex;align-items:center;justify-content:center;gap:32px;flex-wrap:wrap;margin-bottom:18px;">';
            html += '<div style="text-align:center;min-width:100px;">';
            html += '<div style="font-size:2.6em;font-weight:700;color:var(--accent);line-height:1;">' + totalCount + '</div>';
            html += '<div style="color:var(--text-dim);font-size:0.85em;margin-top:6px;">总订阅人数</div>';
            html += '</div>';
            html += '<div style="width:1px;height:50px;background:var(--border);"></div>';
            html += '<div style="text-align:center;min-width:90px;">';
            html += '<div style="font-size:1.6em;font-weight:600;color:var(--accent-green);line-height:1;">' + basicCount + '</div>';
            html += '<div style="color:var(--text-dim);font-size:0.8em;margin-top:6px;">📊 基础日报</div>';
            html += '</div>';
            html += '<div style="text-align:center;min-width:90px;">';
            html += '<div style="font-size:1.6em;font-weight:600;color:var(--accent-purple);line-height:1;">' + customCount + '</div>';
            html += '<div style="color:var(--text-dim);font-size:0.8em;margin-top:6px;">🔧 自定义话题</div>';
            html += '</div>';
            html += '<div style="text-align:center;min-width:90px;">';
            html += '<div style="font-size:1.6em;font-weight:600;color:var(--accent-orange);line-height:1;">' + hasKeyCount + '</div>';
            html += '<div style="color:var(--text-dim);font-size:0.8em;margin-top:6px;">🔑 自带 Key</div>';
            html += '</div>';
            html += '</div>';
            html += '<p style="color:var(--text-dim);font-size:0.8em;text-align:center;margin:0;">🔒 为保护订阅者隐私，仅显示统计人数，不展示订阅者列表。如需退订请在下方输入邮箱。</p>';
            html += '</div>';
            document.getElementById('subList').innerHTML = html;
        }})
        .catch(e => {{
            document.getElementById('subList').innerHTML = '<p style="color:var(--accent-red);">加载失败</p>';
        }});
}}

function doUnsubscribe() {{
    var email = document.getElementById('unsubEmail').value.trim();
    if (!email) {{ alert('请输入邮箱'); return; }}
    var msg = document.getElementById('unsubMsg');
    msg.innerHTML = '<span style="color:var(--text-dim)">处理中...</span>';
    fetchWithTimeout('/api/unsubscribe', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{email: email}})
    }})
    .then(r => r.json())
    .then(data => {{
        if (data.ok) {{
            msg.innerHTML = '<span style="color:var(--accent-green)">✅ ' + data.msg + '</span>';
            loadSubscriptions();
        }} else {{
            msg.innerHTML = '<span style="color:var(--accent-red)">❌ ' + data.msg + '</span>';
        }}
    }})
    .catch(e => {{
        msg.innerHTML = '<span style="color:var(--accent-red)">退订失败: ' + e + '</span>';
    }});
}}

// ═══ Dashboard：URL 监控守护状态卡片 ═══
function loadTunnelCard() {{
    fetchWithTimeout('/api/tunnel_status')
        .then(r => r.json())
        .then(data => {{
            var card = document.getElementById('tunnelCard');
            if (!card) return;
            var statusMap = {{
                'healthy': {{text: '🟢 健康', cls: 'healthy'}},
                'recovering': {{text: '🟡 恢复中', cls: 'recovering'}},
                'down': {{text: '🔴 故障', cls: 'down'}},
                'unknown': {{text: '⚪ 未知', cls: 'unknown'}}
            }};
            var s = statusMap[data.uptime_status] || statusMap['unknown'];
            // 前端转义 tunnel URL，防止属性注入 XSS
            function escAttr(s) {{
                return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
            }}
            function escHtml(s) {{
                return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
            }}
            var urlDisplay = data.current_url ? escHtml(data.current_url) : '未配置隧道';
            var urlHref = data.current_url ? escAttr(data.current_url) : '#';
            var runTag = data.monitor_running ? '<span style="color:var(--accent-green);font-size:0.8em">● 守护运行中</span>' : '<span style="color:var(--text-dim);font-size:0.8em">○ 守护休眠</span>';
            card.style.display = 'block';
            card.innerHTML = '<div class="tunnel-card-head"><span class="tunnel-card-title">📡 URL 健康监控守护</span>' + runTag + '</div>'
                + '<div class="tunnel-card-body">'
                + '<div class="tunnel-metric"><span class="tunnel-metric-label">隧道地址</span><a href="' + urlHref + '" target="_blank" class="tunnel-url">' + urlDisplay + '</a></div>'
                + '<div class="tunnel-metric"><span class="tunnel-metric-label">运行状态</span><span class="tunnel-status ' + s.cls + '">' + s.text + '</span></div>'
                + '<div class="tunnel-metric"><span class="tunnel-metric-label">自动恢复</span><span class="tunnel-num">' + (data.recoveries || 0) + ' 次</span></div>'
                + '<div class="tunnel-metric"><span class="tunnel-metric-label">故障次数</span><span class="tunnel-num">' + (data.failures || 0) + ' 次</span></div>'
                + '</div>'
                + '<div class="tunnel-card-foot">最近检查: ' + (data.last_check ? data.last_check.slice(0,19).replace('T',' ') : 'N/A') + ' · 事件总数 ' + (data.total_events || 0) + '</div>';
        }})
        .catch(function() {{
            var card = document.getElementById('tunnelCard');
            if (card) {{ card.style.display = 'none'; }}
        }});
}}

// ═══ 架构 Tab：加载统计数据 ═══
function loadArchData() {{
    fetchWithTimeout('/api/status')
        .then(r => r.json())
        .then(data => {{
            var envEnc = data.env_encrypted || {{}};
            var envCount = Object.keys(envEnc).length;
            var envEncryptedCount = Object.values(envEnc).filter(v => v).length;
            var encText = envCount > 0 ? (envEncryptedCount + '/' + envCount) : '0';
            var setStat = function(id, val) {{
                var el = document.getElementById(id);
                if (el) el.textContent = val;
            }};
            setStat('archStatRepos', data.db_repo_count || 0);
            setStat('archStatReports', data.report_count || 0);
            setStat('archStatSubs', data.subscriber_count || 0);
            setStat('archStatEnc', encText);
        }})
        .catch(function() {{}});
}}

// ═══ 架构 Tab：加载隧道监控状态 ═══
function loadTunnelStatus() {{
    fetchWithTimeout('/api/tunnel_status')
        .then(r => r.json())
        .then(data => {{
            var urlEl = document.getElementById('archTunnelUrl');
            var statusEl = document.getElementById('archTunnelStatus');
            var recEl = document.getElementById('archTunnelRecoveries');
            var failEl = document.getElementById('archTunnelFailures');
            if (urlEl) {{
                if (data.current_url) {{
                    urlEl.textContent = data.current_url;
                    urlEl.href = data.current_url;
                }} else {{
                    urlEl.textContent = '未配置';
                    urlEl.href = '#';
                }}
            }}
            if (statusEl) {{
                var statusMap = {{
                    'healthy': {{text: '🟢 健康', cls: 'healthy'}},
                    'recovering': {{text: '🟡 恢复中', cls: 'recovering'}},
                    'down': {{text: '🔴 故障', cls: 'down'}},
                    'unknown': {{text: '⚪ 未知', cls: 'unknown'}}
                }};
                var s = statusMap[data.uptime_status] || statusMap['unknown'];
                statusEl.textContent = s.text + (data.monitor_running ? ' · 守护运行中' : '');
                statusEl.className = 'tunnel-status ' + s.cls;
            }}
            if (recEl) recEl.textContent = data.recoveries || 0;
            if (failEl) failEl.textContent = data.failures || 0;
        }})
        .catch(function() {{
            var statusEl = document.getElementById('archTunnelStatus');
            if (statusEl) {{
                statusEl.textContent = '⚪ 加载失败';
                statusEl.className = 'tunnel-status unknown';
            }}
        }});
}}
</script>
{_dino_overlay_html}
</body>
</html>"""


def run_web(host: str = "0.0.0.0", port: int = 5000, debug: bool = False):
    """启动 Web 服务（0.0.0.0 允许局域网访问）

    使用 threaded=True 防止单个慢请求（如 /api/custom 60s）阻塞整站。
    生产环境建议改用 gunicorn（Dockerfile 已配置 --threads 4）。
    """
    logger.info(f"Starting web server on http://{host}:{port}")
    app.run(host=host, port=port, debug=debug, threaded=True)


if __name__ == "__main__":
    run_web(debug=os.getenv("FLASK_DEBUG", "0") == "1")

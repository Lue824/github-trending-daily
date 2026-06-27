"""
URL 变更通知 — 当公网 tunnel URL 更换时，给所有订阅者发邮件通知

用法：
    python -m src.notifier.notify_url_change "https://xxx-yyy-zzz.trycloudflare.com"

    或直接运行：
    python src/notifier/notify_url_change.py "https://xxx-yyy-zzz.trycloudflare.com"
"""
import json
import logging
import os
import sys
from datetime import datetime, timezone

# 确保项目根目录在 sys.path
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _BASE_DIR not in sys.path:
    sys.path.insert(0, _BASE_DIR)

from config import DATA_DIR, EMAIL_CONFIG
from src.notifier.email_sender import send_email
from src.utils.crypto import decrypt_if_needed

logger = logging.getLogger(__name__)

_SUBSCRIPTION_PATH = os.path.join(DATA_DIR, "subscription.json")

# 上次发送的 URL 记录（避免重复发送相同 URL）
_LAST_URL_FILE = os.path.join(DATA_DIR, ".last_tunnel_url")


def _load_subscribers() -> list[str]:
    """读取 subscription.json，返回去重后的真实邮箱列表"""
    if not os.path.exists(_SUBSCRIPTION_PATH):
        logger.warning(f"subscription.json not found: {_SUBSCRIPTION_PATH}")
        return []
    try:
        with open(_SUBSCRIPTION_PATH, "r", encoding="utf-8") as f:
            subs = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Failed to read subscription.json: {e}")
        return []

    # 兼容旧的单 dict 格式
    if isinstance(subs, dict):
        subs = [subs]

    emails = []
    seen = set()
    for sub in subs:
        if not isinstance(sub, dict):
            continue
        email = decrypt_if_needed(sub.get("email") or "").strip().lower()
        # 过滤测试邮箱和空值
        if not email or email in seen:
            continue
        if "example.com" in email or "test" in email:
            continue
        seen.add(email)
        emails.append(email)
    return emails


def _load_last_url() -> str:
    """读取上次发送的 URL（避免重复通知）"""
    if not os.path.exists(_LAST_URL_FILE):
        return ""
    try:
        with open(_LAST_URL_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _save_last_url(url: str):
    """保存本次发送的 URL"""
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        with open(_LAST_URL_FILE, "w", encoding="utf-8") as f:
            f.write(url)
    except OSError as e:
        logger.warning(f"Failed to save last URL: {e}")


def _build_email_html(new_url: str, old_url: str = "", reason: str = "") -> str:
    """生成通知邮件 HTML（增强版：含旧URL失效原因）"""
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # 失效原因中文映射
    reason_map = {
        "timeout": "连接超时",
        "dns_failure": "DNS 解析失败",
        "connection_refused": "连接被拒绝",
        "invalid_url": "URL 无效",
        "http_502": "服务器网关错误 (502)",
        "http_503": "服务不可用 (503)",
        "http_504": "网关超时 (504)",
        "http_404": "页面不存在 (404)",
        "http_500": "服务器内部错误 (500)",
    }
    reason_cn = reason_map.get(reason, reason) if reason else "服务重启"

    # 旧 URL 信息行（仅在提供 old_url 时显示）
    old_url_row = ""
    if old_url:
        old_url_row = f"""
<tr><td style="padding:4px 12px;color:#656d76;border-bottom:1px solid #eee;width:100px;">旧地址</td><td style="padding:4px 12px;border-bottom:1px solid #eee;color:#f85149;text-decoration:line-through;">{old_url}</td></tr>
<tr><td style="padding:4px 12px;color:#656d76;border-bottom:1px solid #eee;">失效原因</td><td style="padding:4px 12px;border-bottom:1px solid #eee;">{reason_cn}</td></tr>"""

    return f"""\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:15px;color:#1f2328;max-width:600px;margin:0 auto;padding:30px 20px;background:#fff;">
<div style="background:#f6f8fa;border-radius:10px;padding:24px;margin-bottom:20px;">
<h1 style="margin:0 0 16px;font-size:20px;color:#0969da;">🔔 公网地址已更新</h1>
<p style="margin:0 0 12px;color:#656d76;">GitHub Trending Daily 服务的公网访问地址已更换，请使用以下新地址：</p>
<p style="margin:0 0 16px;">
<a href="{new_url}" style="display:inline-block;padding:12px 24px;background:#0969da;color:#fff;text-decoration:none;border-radius:8px;font-size:16px;font-weight:bold;">{new_url}</a>
</p>
<table style="width:100%;font-size:14px;border-collapse:collapse;margin:12px 0;">
<tr><td style="padding:4px 12px;color:#656d76;border-bottom:1px solid #eee;width:100px;">新地址</td><td style="padding:4px 12px;border-bottom:1px solid #eee;color:#0969da;">{new_url}</td></tr>
<tr><td style="padding:4px 12px;color:#656d76;border-bottom:1px solid #eee;">生效时间</td><td style="padding:4px 12px;border-bottom:1px solid #eee;">{now_str}</td></tr>{old_url_row}
</table>
<p style="margin:0;color:#656d76;font-size:13px;">更新时间：{now_str}</p>
</div>
<div style="font-size:13px;color:#656d76;line-height:1.6;">
<p>📌 旧地址已失效，请收藏新地址。</p>
<p>📌 新地址在服务重启前保持有效；若再次更换，我们会另行通知。</p>
<p>📌 你订阅的每日 GitHub Trending 推送不受影响，会按计划发送到你的邮箱。</p>
<hr style="border:0;border-top:1px solid #d0d7de;margin:16px 0;">
<p style="margin:0;">此邮件由 GitHub Trending Daily Bot 自动发送，请勿回复。</p>
</div>
</body>
</html>"""


def notify_url_change(new_url: str, old_url: str = "", reason: str = "") -> int:
    """给所有订阅者发送 URL 变更通知邮件

    Args:
        new_url: 新的公网 URL
        old_url: 旧的公网 URL（可选，用于邮件中展示失效原因）
        reason: 旧 URL 失效原因（可选，如 "timeout", "dns_failure" 等）

    Returns:
        成功发送的邮件数
    """
    if not new_url or not new_url.startswith("https://"):
        logger.error(f"Invalid URL: {new_url}")
        return 0

    # 避免重复发送相同 URL
    last_url = _load_last_url()
    if new_url == last_url:
        logger.info(f"URL unchanged ({new_url}), skipping notification")
        return 0

    subscribers = _load_subscribers()

    # 添加开发者邮箱（确保开发者也收到通知）
    dev_email = (EMAIL_CONFIG.get("sender") or "").strip().lower()
    if dev_email and dev_email not in subscribers:
        subscribers.append(dev_email)
        logger.info(f"Developer email added: {dev_email[:2]}***{dev_email[dev_email.index('@'):]}")

    if not subscribers:
        logger.info("No subscribers or developer email to notify")
        return 0

    logger.info(f"Notifying {len(subscribers)} recipient(s) of URL change: {new_url}")
    if old_url:
        logger.info(f"  Old URL: {old_url} (reason: {reason})")

    subject = "🔔 GitHub Trending Daily 公网地址已更新"
    html = _build_email_html(new_url, old_url=old_url, reason=reason)

    sent = 0
    for email in subscribers:
        if send_email(subject, html, receiver=email):
            sent += 1
            logger.info(f"  ✓ Notified: {email[:2]}***{email[email.index('@'):]}")
        else:
            logger.warning(f"  ✗ Failed: {email[:2]}***{email[email.index('@'):]}")

    # 记录本次 URL，避免重复发送
    if sent > 0:
        _save_last_url(new_url)

    logger.info(f"URL change notification sent: {sent}/{len(subscribers)} (subscribers + developer)")
    return sent


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if len(sys.argv) < 2:
        print("Usage: python notify_url_change.py <new_url> [old_url] [reason]")
        sys.exit(1)

    new_url = sys.argv[1].strip()
    old_url = sys.argv[2].strip() if len(sys.argv) > 2 else ""
    reason = sys.argv[3].strip() if len(sys.argv) > 3 else ""
    count = notify_url_change(new_url, old_url=old_url, reason=reason)
    print(f"Notified {count} subscriber(s)")

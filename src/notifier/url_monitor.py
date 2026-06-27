"""
URL 健康监控守护进程 — 持续监控 tunnel URL 可用性，故障时自动重建并通知

功能：
1. 定期检测当前 tunnel URL 可用性（HTTP 请求 + 超时判断）
2. 检测到故障时，自动重启 cloudflared tunnel
3. 从日志提取新 URL
4. 同步更新 GitHub Pages 的 redirect.json（自动 push，保持永久跳转页可用）
5. 调用 notify_url_change 发送通知邮件（含旧URL失效原因）
6. 失败重试机制（URL生成 + 邮件发送）
7. 完整审计日志（JSONL 格式，含时间戳、事件类型、详情）

用法：
    python src/notifier/url_monitor.py              # 前台运行
    python src/notifier/url_monitor.py --once       # 单次检查
    python src/notifier/url_monitor.py --daemon     # 守护进程模式（不退出）
"""
import json
import logging
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

# 确保项目根目录在 sys.path
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _BASE_DIR not in sys.path:
    sys.path.insert(0, _BASE_DIR)

from config import DATA_DIR
from src.notifier.notify_url_change import notify_url_change

logger = logging.getLogger("url_monitor")

# ── 路径常量 ──────────────────────────────────────────────
_LOG_DIR = os.path.join(DATA_DIR, "logs")
_AUDIT_FILE = os.path.join(_LOG_DIR, "url_monitor_audit.jsonl")
_LOG_FILE = os.path.join(_LOG_DIR, "url_monitor.log")
_URL_FILE = os.path.join(_BASE_DIR, "current_url.txt")
_LAST_URL_FILE = os.path.join(DATA_DIR, ".last_tunnel_url")
_CF_LOG_DIR = os.path.join(os.environ.get("TEMP", "/tmp"), "github_trending")
_CF_ERR_LOG = os.path.join(_CF_LOG_DIR, "cf_err.log")

_CONFIG_FILE = os.path.join(DATA_DIR, "url_monitor_config.json")

# cloudflared 路径
_CF_PATH = os.path.join(
    os.environ.get("LOCALAPPDATA", ""),
    "Microsoft", "WinGet", "Packages",
    "Cloudflare.cloudflared_Microsoft.Winget.Source_8wekyb3d8bbwe",
    "cloudflared.exe",
)

# ── 默认配置 ──────────────────────────────────────────────
_DEFAULT_CONFIG = {
    "check_interval_seconds": 60,        # 检查间隔
    "request_timeout_seconds": 10,       # HTTP 请求超时
    "failures_before_action": 2,         # 连续失败多少次才触发恢复
    "max_retries": 3,                    # 最大重试次数
    "retry_delay_seconds": 5,            # 重试间隔
    "cf_startup_wait_seconds": 20,       # 等待 cloudflared 启动的最长时间
    "health_check_path": "/api/status",  # 健康检查路径
}


def load_config() -> dict:
    """加载配置文件，不存在则用默认值并自动创建"""
    if os.path.exists(_CONFIG_FILE):
        try:
            with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            # 合并默认值（确保新增字段有默认值）
            merged = {**_DEFAULT_CONFIG, **cfg}
            return merged
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to load config, using defaults: {e}")
    # 自动创建默认配置文件
    save_config(_DEFAULT_CONFIG)
    return _DEFAULT_CONFIG.copy()


def save_config(cfg: dict):
    """保存配置文件"""
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.error(f"Failed to save config: {e}")


# ── 审计日志 ──────────────────────────────────────────────
def _audit(event_type: str, details: dict):
    """写入结构化审计日志（JSONL 格式）"""
    os.makedirs(_LOG_DIR, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event_type,
        **details,
    }
    try:
        with open(_AUDIT_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as e:
        logger.error(f"Failed to write audit log: {e}")


# ── URL 读取 ──────────────────────────────────────────────
def read_current_url() -> str:
    """从 current_url.txt 读取当前 tunnel URL（自动处理 BOM）"""
    if not os.path.exists(_URL_FILE):
        return ""
    try:
        # utf-8-sig 自动去除 BOM（PowerShell Out-File -Encoding utf8 会加 BOM）
        with open(_URL_FILE, "r", encoding="utf-8-sig") as f:
            return f.read().strip()
    except OSError:
        return ""


def write_current_url(url: str):
    """写入当前 URL 到 current_url.txt"""
    try:
        with open(_URL_FILE, "w", encoding="utf-8") as f:
            f.write(url)
    except OSError as e:
        logger.error(f"Failed to write URL file: {e}")


# ── URL 健康检查 ───────────────────────────────────────────
def check_url_health(url: str, timeout: int = 10, path: str = "/api/status") -> tuple[bool, str]:
    """
    检查 URL 可用性

    Returns:
        (is_healthy, reason) — 健康返回 (True, "ok")，不健康返回 (False, "原因")
    """
    if not url or not url.startswith("https://"):
        return False, "invalid_url"

    check_url = url.rstrip("/") + path
    try:
        req = urllib.request.Request(check_url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                return True, "ok"
            else:
                return False, f"http_{resp.status}"
    except urllib.error.HTTPError as e:
        return False, f"http_{e.code}"
    except urllib.error.URLError as e:
        reason = str(e.reason)
        if "timed out" in reason.lower() or "timeout" in reason.lower():
            return False, "timeout"
        if "name or service not known" in reason.lower() or "getaddrinfo" in reason.lower():
            return False, "dns_failure"
        if "connection refused" in reason.lower():
            return False, "connection_refused"
        return False, f"url_error:{reason}"
    except TimeoutError:
        return False, "timeout"
    except ConnectionError as e:
        return False, f"connection_error:{e}"
    except Exception as e:
        return False, f"unknown:{type(e).__name__}"


# ── cloudflared 进程管理 ──────────────────────────────────
def find_cloudflared_pid() -> int | None:
    """查找正在运行的 cloudflared 进程 PID"""
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq cloudflared.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and "cloudflared.exe" in result.stdout:
            for line in result.stdout.strip().split("\n"):
                parts = line.strip('"').split('","')
                if len(parts) >= 2 and parts[0] == "cloudflared.exe":
                    return int(parts[1])
    except Exception:
        pass
    return None


def kill_cloudflared() -> bool:
    """停止 cloudflared 进程"""
    pid = find_cloudflared_pid()
    if not pid:
        logger.info("cloudflared not running, nothing to kill")
        return True
    try:
        subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                       capture_output=True, timeout=5)
        time.sleep(2)
        if find_cloudflared_pid() is None:
            logger.info(f"cloudflared (PID {pid}) killed")
            return True
        else:
            logger.warning(f"Failed to kill cloudflared (PID {pid})")
            return False
    except Exception as e:
        logger.error(f"Error killing cloudflared: {e}")
        return False


def start_cloudflared() -> bool:
    """启动新的 cloudflared tunnel"""
    if not os.path.exists(_CF_PATH):
        # 尝试从 PATH 查找
        logger.error(f"cloudflared not found at {_CF_PATH}")
        return False

    os.makedirs(_CF_LOG_DIR, exist_ok=True)
    # 清空旧日志
    for log_file in [_CF_ERR_LOG, os.path.join(_CF_LOG_DIR, "cf_out.log")]:
        if os.path.exists(log_file):
            try:
                os.remove(log_file)
            except OSError:
                pass

    try:
        with open(os.path.join(_CF_LOG_DIR, "cf_out.log"), "w") as stdout_f, \
             open(_CF_ERR_LOG, "w") as stderr_f:
            proc = subprocess.Popen(
                [_CF_PATH, "tunnel", "--url", "http://127.0.0.1:5000"],
                stdout=stdout_f,
                stderr=stderr_f,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
        logger.info(f"cloudflared started (PID {proc.pid})")
        return True
    except Exception as e:
        logger.error(f"Failed to start cloudflared: {e}")
        return False


def extract_url_from_logs(max_wait: int = 20) -> str:
    """从 cloudflared 日志中提取 tunnel URL"""
    pattern = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
    for _ in range(max_wait):
        time.sleep(1)
        if os.path.exists(_CF_ERR_LOG):
            try:
                with open(_CF_ERR_LOG, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                matches = pattern.findall(content)
                if matches:
                    return matches[-1]
            except OSError:
                pass
    return ""


# ── GitHub Pages 同步 ─────────────────────────────────────
def sync_redirect_json(new_url: str) -> bool:
    """同步更新 redirect.json 并 push 到 GitHub Pages

    tunnel URL 变化后，自动更新 GitHub Pages 上的跳转配置，
    确保永久跳转页 (lue824.github.io) 指向最新可用的 tunnel URL。

    失败不影响主恢复流程（URL 已生效、邮件已发）。

    Returns:
        True 同步成功，False 失败
    """
    if not new_url or not new_url.startswith("https://"):
        logger.warning(f"Skip redirect.json sync: invalid url {new_url}")
        return False

    redirect_file = os.path.join(_BASE_DIR, "redirect.json")

    # Step 1: 读取旧 URL（用于审计 + 判断是否需要同步）
    old_redirect_url = ""
    try:
        if os.path.exists(redirect_file):
            with open(redirect_file, "r", encoding="utf-8") as f:
                old_data = json.load(f)
            old_redirect_url = old_data.get("url", "")
    except (json.JSONDecodeError, OSError):
        pass

    # 如果 URL 没变化，跳过同步
    if old_redirect_url == new_url:
        logger.info("redirect.json already up-to-date, skip sync")
        return True

    # Step 2: 写入新 redirect.json
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    new_data = {
        "url": new_url,
        "updated_at": now_str,
        "status": "online",
    }
    try:
        with open(redirect_file, "w", encoding="utf-8") as f:
            json.dump(new_data, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.error(f"Failed to write redirect.json: {e}")
        _audit("redirect_sync_failed", {"step": "write_file", "error": str(e)})
        return False

    # Step 3: git add + commit + push（main 和 master 两个分支）
    try:
        # git add
        r1 = subprocess.run(
            ["git", "add", "redirect.json"],
            cwd=_BASE_DIR, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=15,
        )
        if r1.returncode != 0:
            logger.error(f"git add failed: {r1.stderr}")
            _audit("redirect_sync_failed", {"step": "git_add", "error": r1.stderr})
            return False

        # git commit（英文 message 避免 PowerShell/编码问题）
        r2 = subprocess.run(
            ["git", "commit", "-m", "auto-sync redirect url by url_monitor"],
            cwd=_BASE_DIR, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=15,
        )
        # "nothing to commit" 不算失败
        if r2.returncode != 0 and "nothing to commit" not in (r2.stdout + r2.stderr).lower():
            logger.warning(f"git commit warning: {r2.stderr}")

        # git push origin main
        r3 = subprocess.run(
            ["git", "push", "origin", "main"],
            cwd=_BASE_DIR, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30,
        )
        if r3.returncode != 0:
            logger.error(f"git push main failed: {r3.stderr}")
            _audit("redirect_sync_failed", {"step": "git_push_main", "error": r3.stderr})
            return False

        # git push origin main:master（GitHub Pages 使用的分支）
        r4 = subprocess.run(
            ["git", "push", "origin", "main:master"],
            cwd=_BASE_DIR, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30,
        )
        if r4.returncode != 0:
            logger.error(f"git push main:master failed: {r4.stderr}")
            _audit("redirect_sync_failed", {"step": "git_push_master", "error": r4.stderr})
            return False

        logger.info(f"redirect.json synced to GitHub Pages: {new_url}")
        _audit("redirect_synced", {
            "old_url": old_redirect_url,
            "new_url": new_url,
        })
        return True

    except subprocess.TimeoutExpired:
        logger.error("git operation timed out during redirect.json sync")
        _audit("redirect_sync_failed", {"step": "timeout"})
        return False
    except Exception as e:
        logger.error(f"Failed to sync redirect.json: {e}")
        _audit("redirect_sync_failed", {"step": "unknown", "error": str(e)})
        return False


# ── 恢复流程 ──────────────────────────────────────────────
def recover_tunnel(old_url: str, reason: str, cfg: dict) -> str | None:
    """
    执行完整的 tunnel 恢复流程

    流程：kill cloudflared → start cloudflared → extract URL → notify
    带重试机制

    Returns:
        新 URL（成功）或 None（失败）
    """
    max_retries = cfg.get("max_retries", 3)
    retry_delay = cfg.get("retry_delay_seconds", 5)
    cf_wait = cfg.get("cf_startup_wait_seconds", 20)

    _audit("recovery_started", {
        "old_url": old_url,
        "failure_reason": reason,
    })

    for attempt in range(1, max_retries + 1):
        logger.info(f"Recovery attempt {attempt}/{max_retries}...")
        _audit("recovery_attempt", {"attempt": attempt, "max": max_retries})

        # Step 1: Kill old cloudflared
        if not kill_cloudflared():
            logger.warning(f"Attempt {attempt}: kill cloudflared failed")
            _audit("recovery_step_failed", {"step": "kill", "attempt": attempt})
            time.sleep(retry_delay)
            continue

        # Step 2: Start new cloudflared
        if not start_cloudflared():
            logger.warning(f"Attempt {attempt}: start cloudflared failed")
            _audit("recovery_step_failed", {"step": "start", "attempt": attempt})
            time.sleep(retry_delay)
            continue

        # Step 3: Extract new URL
        new_url = extract_url_from_logs(max_wait=cf_wait)
        if not new_url:
            logger.warning(f"Attempt {attempt}: no URL found in logs")
            _audit("recovery_step_failed", {"step": "extract_url", "attempt": attempt})
            time.sleep(retry_delay)
            continue

        logger.info(f"New URL extracted: {new_url}")
        _audit("recovery_url_extracted", {
            "new_url": new_url,
            "attempt": attempt,
        })

        # Step 4: Write to current_url.txt
        write_current_url(new_url)

        # Step 4.5: Sync redirect.json to GitHub Pages (auto-update jump page)
        sync_redirect_json(new_url)

        # Step 5: Notify subscribers (with retry)
        notify_sent = False
        for notify_attempt in range(1, max_retries + 1):
            count = notify_url_change(new_url, old_url=old_url, reason=reason)
            if count > 0:
                notify_sent = True
                logger.info(f"Notification sent to {count} recipients (attempt {notify_attempt})")
                _audit("notification_sent", {
                    "new_url": new_url,
                    "recipients": count,
                    "notify_attempt": notify_attempt,
                })
                break
            else:
                logger.warning(f"Notification attempt {notify_attempt} failed")
                _audit("notification_attempt_failed", {
                    "notify_attempt": notify_attempt,
                })
                time.sleep(retry_delay)

        if not notify_sent:
            logger.error("All notification attempts failed")
            _audit("notification_all_failed", {"new_url": new_url})
            # 即使通知失败也返回新 URL（URL 已生效）

        _audit("recovery_completed", {
            "old_url": old_url,
            "new_url": new_url,
            "reason": reason,
            "attempts": attempt,
        })

        return new_url

    # 所有重试都失败
    logger.error(f"Recovery failed after {max_retries} attempts")
    _audit("recovery_failed", {
        "old_url": old_url,
        "reason": reason,
        "max_attempts": max_retries,
    })

    # 发送严重故障通知给开发者
    _send_critical_alert(old_url, reason, cfg)
    return None


def _send_critical_alert(old_url: str, reason: str, cfg: dict):
    """发送严重故障通知给开发者"""
    try:
        from config import EMAIL_CONFIG
        from src.notifier.email_sender import send_email

        dev_email = (EMAIL_CONFIG.get("sender") or "").strip()
        if not dev_email:
            return

        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        html = f"""\
<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="font-family:sans-serif;font-size:15px;color:#1f2328;max-width:600px;margin:0 auto;padding:30px 20px;">
<div style="background:#fff5f5;border:1px solid #f85149;border-radius:10px;padding:24px;margin-bottom:20px;">
<h1 style="margin:0 0 16px;font-size:20px;color:#f85149;">[严重告警] URL 恢复失败</h1>
<p style="margin:0 0 12px;color:#656d76;">GitHub Trending Daily 服务的 tunnel URL 恢复流程已耗尽所有重试次数，仍然失败。</p>
<table style="width:100%;font-size:14px;border-collapse:collapse;">
<tr><td style="padding:4px 12px;color:#656d76;border-bottom:1px solid #eee;">故障 URL</td><td style="padding:4px 12px;border-bottom:1px solid #eee;">{old_url}</td></tr>
<tr><td style="padding:4px 12px;color:#656d76;border-bottom:1px solid #eee;">失败原因</td><td style="padding:4px 12px;border-bottom:1px solid #eee;">{reason}</td></tr>
<tr><td style="padding:4px 12px;color:#656d76;border-bottom:1px solid #eee;">告警时间</td><td style="padding:4px 12px;border-bottom:1px solid #eee;">{now_str}</td></tr>
</table>
<p style="margin:16px 0 0;color:#656d76;font-size:13px;">请手动检查服务状态并运行 start_tunnel.ps1 恢复。</p>
</div>
</body></html>"""

        send_email("[严重告警] URL 恢复失败", html, receiver=dev_email)
        logger.info(f"Critical alert sent to developer")
        _audit("critical_alert_sent", {"reason": reason})
    except Exception as e:
        logger.error(f"Failed to send critical alert: {e}")
        _audit("critical_alert_failed", {"error": str(e)})


# ── 主循环 ────────────────────────────────────────────────
def run_once(cfg: dict) -> bool:
    """
    执行一次健康检查

    Returns:
        True 如果 URL 健康，False 如果触发了恢复
    """
    url = read_current_url()
    if not url:
        logger.warning("No current URL to monitor (current_url.txt is empty)")
        _audit("no_url_to_monitor", {})
        return False

    is_healthy, reason = check_url_health(
        url,
        timeout=cfg.get("request_timeout_seconds", 10),
        path=cfg.get("health_check_path", "/api/status"),
    )

    if is_healthy:
        logger.debug(f"URL healthy: {url}")
        return True
    else:
        logger.warning(f"URL check failed: {url} — reason: {reason}")
        _audit("url_check_failed", {"url": url, "reason": reason})
        return False


def run_daemon(cfg: dict):
    """守护进程模式 — 持续监控"""
    interval = cfg.get("check_interval_seconds", 60)
    threshold = cfg.get("failures_before_action", 2)

    consecutive_failures = 0
    logger.info(f"URL monitor started (interval={interval}s, threshold={threshold})")
    _audit("monitor_started", {
        "interval": interval,
        "threshold": threshold,
        "config": cfg,
    })

    while True:
        try:
            url = read_current_url()
            if not url:
                logger.warning("No URL to monitor, waiting...")
                _audit("no_url_to_monitor", {})
                time.sleep(interval)
                continue

            is_healthy, reason = check_url_health(
                url,
                timeout=cfg.get("request_timeout_seconds", 10),
                path=cfg.get("health_check_path", "/api/status"),
            )

            if is_healthy:
                if consecutive_failures > 0:
                    logger.info(f"URL recovered after {consecutive_failures} failures")
                    _audit("url_recovered", {
                        "url": url,
                        "previous_failures": consecutive_failures,
                    })
                consecutive_failures = 0
                logger.debug(f"URL healthy: {url}")
            else:
                consecutive_failures += 1
                logger.warning(
                    f"URL check failed ({consecutive_failures}/{threshold}): "
                    f"{url} — reason: {reason}"
                )
                _audit("url_check_failed", {
                    "url": url,
                    "reason": reason,
                    "consecutive_failures": consecutive_failures,
                    "threshold": threshold,
                })

                if consecutive_failures >= threshold:
                    logger.error(
                        f"Failure threshold reached ({consecutive_failures}), "
                        f"triggering recovery..."
                    )
                    _audit("recovery_triggered", {
                        "url": url,
                        "reason": reason,
                        "consecutive_failures": consecutive_failures,
                    })

                    new_url = recover_tunnel(url, reason, cfg)
                    if new_url:
                        consecutive_failures = 0
                        logger.info(f"Recovery successful, new URL: {new_url}")
                    else:
                        consecutive_failures = 0  # 重置，避免反复触发
                        logger.error("Recovery failed, will retry next cycle")

        except KeyboardInterrupt:
            logger.info("Monitor stopped by user")
            _audit("monitor_stopped", {"reason": "keyboard_interrupt"})
            break
        except Exception as e:
            logger.error(f"Unexpected error in monitor loop: {e}", exc_info=True)
            _audit("monitor_error", {"error": str(e), "type": type(e).__name__})
            time.sleep(interval)

        time.sleep(interval)


# ── 入口 ──────────────────────────────────────────────────
def setup_logging(verbose: bool = False):
    """配置日志"""
    os.makedirs(_LOG_DIR, exist_ok=True)
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"

    # 控制台 + 文件
    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(logging.Formatter(fmt))

    file_handler = logging.FileHandler(_LOG_FILE, encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(logging.Formatter(fmt))

    root = logging.getLogger()
    root.setLevel(level)
    # 避免重复添加
    root.handlers.clear()
    root.addHandler(console)
    root.addHandler(file_handler)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="URL 健康监控守护进程")
    parser.add_argument("--once", action="store_true", help="单次检查后退出")
    parser.add_argument("--daemon", action="store_true", help="守护进程模式（默认）")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细日志")
    parser.add_argument("--config", type=str, help="指定配置文件路径")
    args = parser.parse_args()

    # 修复 Windows 控制台编码
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    setup_logging(verbose=args.verbose)

    if args.config:
        _CONFIG_FILE = args.config

    cfg = load_config()
    logger.info(f"Config loaded: {cfg}")

    if args.once:
        healthy = run_once(cfg)
        sys.exit(0 if healthy else 1)
    else:
        run_daemon(cfg)

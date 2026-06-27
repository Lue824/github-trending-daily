"""
SMTP 邮件推送
使用 SMTP SSL 方式发送
"""
import html
import logging
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from config import EMAIL_CONFIG

logger = logging.getLogger(__name__)


def send_email(subject: str, html_content: str, receiver: str = None) -> bool:
    """
    通过 SMTP 发送邮件

    Args:
        subject: 邮件主题
        html_content: HTML 格式的邮件正文
        receiver: 指定收件人（不传则用配置中的默认收件人）

    Returns:
        True 如果发送成功
    """
    sender = (EMAIL_CONFIG.get("sender") or "").strip()
    password = (EMAIL_CONFIG.get("password") or "").strip()
    # 优先使用传入的 receiver，避免修改全局配置导致的竞态条件
    receiver = (receiver or EMAIL_CONFIG.get("receiver") or "").strip()

    if not sender or not password:
        logger.error("Email config missing: set QQ_EMAIL and QQ_EMAIL_AUTH_CODE in .env")
        return False

    if not receiver:
        logger.error("Email receiver is empty")
        return False

    smtp_host = EMAIL_CONFIG.get("smtp_host", "smtp.qq.com")
    smtp_port = EMAIL_CONFIG.get("smtp_port", 465)

    msg = MIMEMultipart("alternative")
    msg["From"] = sender
    msg["To"] = receiver
    msg["Subject"] = subject

    msg.attach(MIMEText(html_content, "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30) as server:
            server.login(sender, password)
            server.sendmail(sender, [receiver], msg.as_string())
        # 日志脱敏
        masked = receiver[:2] + "***" + receiver[receiver.index("@"):] if "@" in receiver else "***"
        logger.info(f"Email sent to {masked}: {subject}")
        return True
    except (smtplib.SMTPException, OSError, ConnectionError, TimeoutError) as e:
        logger.error(f"Failed to send email: {type(e).__name__}: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error sending email: {type(e).__name__}: {e}")
        return False


def markdown_to_html(md_content: str) -> str:
    """
    将 Markdown 转为适合邮件的 HTML

    用简单规则转换，避免引入额外依赖
    """
    lines = md_content.split("\n")
    html_lines = []
    in_table = False
    in_code = False

    for line in lines:
        # 代码块
        if line.startswith("```"):
            if in_code:
                html_lines.append("</pre>")
                in_code = False
            else:
                html_lines.append('<pre style="background:#f6f8fa;padding:12px;border-radius:6px;overflow-x:auto;">')
                in_code = True
            continue

        if in_code:
            html_lines.append(line)
            continue

        # 引用
        if line.startswith("> "):
            quote = line[2:]
            html_lines.append(
                f'<blockquote style="margin:8px 0;padding:4px 16px;border-left:4px solid #0969da;color:#656d76;">'
                f'{_inline_md(quote)}</blockquote>'
            )
            continue

        # 表格
        if line.startswith("|") and not in_table:
            in_table = True
            html_lines.append(
                '<table style="border-collapse:collapse;width:100%;margin:8px 0;">'
            )
        if in_table and not line.startswith("|"):
            html_lines.append("</table>")
            in_table = False

        if line.startswith("|"):
            cells = [c.strip() for c in line.split("|")[1:-1]]
            is_header = all(c.startswith("---") for c in cells)
            if is_header:
                continue  # 跳过分隔行
            # 判断是否是表头（下一行是分隔线）
            tag = "th" if in_table else "td"
            row_cells = "".join(
                f'<{tag} style="border:1px solid #d0d7de;padding:6px 12px;text-align:left;">{_inline_md(c)}</{tag}>'
                for c in cells
            )
            html_lines.append(f"<tr>{row_cells}</tr>")
            continue

        if not line.startswith("|") and in_table:
            html_lines.append("</table>")
            in_table = False

        # 标题
        if line.startswith("### "):
            html_lines.append(f'<h4 style="margin:16px 0 8px;">{_inline_md(line[4:])}</h4>')
        elif line.startswith("## "):
            html_lines.append(f'<h3 style="margin:20px 0 10px;border-bottom:1px solid #d0d7de;padding-bottom:6px;">{_inline_md(line[3:])}</h3>')
        elif line.startswith("# "):
            html_lines.append(f'<h2 style="margin:24px 0 12px;">{_inline_md(line[2:])}</h2>')
        elif line.startswith("- "):
            html_lines.append(f'<li>{_inline_md(line[2:])}</li>')
        elif line.startswith("---"):
            html_lines.append('<hr style="border:0;border-top:1px solid #d0d7de;margin:16px 0;">')
        elif line.strip():
            html_lines.append(f'<p style="margin:4px 0;">{_inline_md(line)}</p>')
        else:
            html_lines.append("<br>")

    if in_table:
        html_lines.append("</table>")
    if in_code:
        html_lines.append("</pre>")

    body = "\n".join(html_lines)

    return f"""\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:14px;color:#1f2328;max-width:800px;margin:0 auto;padding:20px;background:#fff;">
{body}
</body>
</html>"""


def _inline_md(text: str) -> str:
    """处理行内 markdown 语法：加粗、代码、链接、图片"""
    # 先转义 HTML 实体，防止注入
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # 链接 [text](url) — 校验 URL 协议，阻止 javascript: 等危险协议
    def _safe_link(m):
        link_text = m.group(1)
        url = m.group(2).strip()
        # 仅允许 http/https/mailto 协议
        if re.match(r'^https?://|^mailto:', url, re.IGNORECASE):
            # 对 URL 中的引号转义，防止属性注入
            safe_url = html.escape(url, quote=True)
            return f'<a href="{safe_url}" style="color:#0969da;">{link_text}</a>'
        # 不安全协议，仅显示文本
        return link_text
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', _safe_link, text)
    # 行内代码 `code`
    text = re.sub(
        r'`([^`]+)`',
        r'<code style="background:#f6f8fa;padding:2px 6px;border-radius:4px;font-size:13px;">\1</code>',
        text
    )
    # 加粗 **text**
    text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)
    return text

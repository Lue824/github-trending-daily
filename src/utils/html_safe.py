"""HTML 转义工具 — 防止 XSS 攻击

所有外部数据（用户输入、GitHub API、LLM 输出）插入 HTML 前必须经过转义。
"""
import html
import re


def esc(text) -> str:
    """HTML 实体转义（防止 XSS）

    Args:
        text: 任意类型输入（None/数字/字符串均安全）

    Returns:
        转义后的安全字符串
    """
    if text is None:
        return ""
    return html.escape(str(text), quote=True)


def esc_attr(text) -> str:
    """HTML 属性转义（用于 href/src/title 等属性值）"""
    if text is None:
        return ""
    # 双重转义防止单双引号逃逸
    return html.escape(str(text), quote=True).replace("'", "&#x27;")


def safe_href(url) -> str:
    """安全的 href 属性（校验协议白名单，防止 javascript: 协议）"""
    if not url:
        return "#"
    url_str = str(url).strip()
    # 只允许 http/https/mailto 协议
    if re.match(r"^(https?|mailto):", url_str, re.IGNORECASE):
        return esc_attr(url_str)
    return "#"


def safe_text_br(text) -> str:
    """转义文本但保留换行（将 \\n 转为 <br>）

    用于多行文本展示：先转义 HTML 实体，再替换换行符
    """
    if text is None:
        return ""
    return esc(str(text)).replace("\n", "<br>")


def safe_url_path(text) -> str:
    """清洗用于 URL 路径的文本（防止路径遍历）

    用于生成文件名等场景，只保留字母数字和连字符
    """
    if not text:
        return "unknown"
    return re.sub(r"[^\w\-]", "_", str(text))[:50]

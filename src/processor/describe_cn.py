"""
根据项目元数据生成中文介绍
基于 topics / tags / 名称 / 领域 综合生成
"""
import re

# ── Topic → 中文标签 ────────────────────────────────────
TOPIC_LABEL = {
    "ai": "AI",
    "agent": "AI Agent",
    "llm": "大模型",
    "rag": "RAG",
    "mcp": "MCP",
    "langchain": "LangChain",
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "claude": "Claude",
    "claude-code": "Claude Code",
    "deepseek": "DeepSeek",
    "codex": "Codex",
    "cursor": "Cursor",
    "skills": "Agent Skills",
    "skill": "Agent Skill",
    "orchestration": "编排调度",
    "workflow": "工作流",
    "browser": "浏览器自动化",
    "sandbox": "沙箱",
    "terminal": "终端工具",
    "tui": "TUI",
    "design": "UI设计",
    "ppt": "PPT生成",
    "video": "视频处理",
    "image": "图像处理",
    "diagram": "图表生成",
    "scraping": "网页抓取",
    "dashboard": "数据看板",
    "monitoring": "监控",
    "security": "安全",
    "testing": "测试",
    "database": "数据库",
    "api": "API",
    "cli": "CLI",
    "sdk": "SDK",
    "framework": "框架",
    "platform": "平台",
    "trading": "量化交易",
    "finance": "金融",
    "rust": "Rust",
    "python": "Python",
    "typescript": "TypeScript",
    "go": "Go",
    "react": "React",
    "vue": "Vue",
    "nextjs": "Next.js",
    "kubernetes": "K8s",
    "docker": "Docker",
    "wasm": "Wasm",
    "machine-learning": "ML",
    "deep-learning": "深度学习",
    "pytorch": "PyTorch",
    "tensorflow": "TF",
    "transformer": "Transformer",
    "diffusion": "扩散模型",
    "nlp": "NLP",
    "computer-vision": "CV",
    "reinforcement-learning": "强化学习",
    "robotics": "机器人",
    "dataset": "数据集",
    "fine-tuning": "微调",
    "self-hosted": "自托管",
    "open-source": "开源",
    "cross-platform": "跨平台",
    "awesome": "资源汇总",
    "tutorial": "教程",
    "book": "书籍",
}

# ── 项目名 → 领域描述模式 ──────────────────────────────
_NAME_HINTS = [
    (r"agent", "AI Agent 相关工具"),
    (r"skill", "AI Coding 技能集"),
    (r"design", "设计/UI 工具"),
    (r"ppt", "PPT 自动生成"),
    (r"video", "视频编辑"),
    (r"browser", "浏览器自动化"),
    (r"mcp", "MCP 协议工具"),
    (r"claude", "Claude 生态"),
    (r"codex", "OpenAI Codex 生态"),
    (r"cursor", "Cursor 生态"),
    (r"openai", "OpenAI 相关"),
    (r"deepseek", "DeepSeek 相关"),
    (r"sandbox", "安全沙箱"),
    (r"trading", "量化交易"),
    (r"monitor", "监控/可观测"),
    (r"scrap", "网页抓取"),
    (r"dashboard", "数据看板"),
    (r"awesome", "精选资源汇总"),
    (r"hello-", "入门教程"),
]


def _pick_cn_topics(repo: dict, max_n: int = 5) -> list[str]:
    """从 topics + tags 中提取中文标签"""
    seen = set()
    result = []
    topics = repo.get("topics", [])
    tags = repo.get("tags", [])

    for t in topics:
        key = t.lower().replace("_", "-").replace(" ", "-")
        label = TOPIC_LABEL.get(key)
        if label and label not in seen:
            result.append(label)
            seen.add(label)

    for tag in tags:
        if tag not in seen:
            result.append(tag)
            seen.add(tag)

    return result[:max_n]


def _is_mostly_chinese(text: str) -> bool:
    """判断文本是否以中文为主"""
    if not text:
        return False
    cn = sum(1 for c in text if '一' <= c <= '鿿')
    return cn > len(text.replace(" ", "")) * 0.3


def _clean_english_desc(desc: str) -> str:
    """裁剪英文描述，保留前 120 个有效字符"""
    if _is_mostly_chinese(desc):
        return desc[:120]
    # 尝试在句子边界截断
    trimmed = desc[:150].strip()
    if len(trimmed) >= 150:
        # 找最后一个完整句子
        for sep in ('. ', '! ', '? ', '\n'):
            idx = trimmed.rfind(sep)
            if idx > 30:
                return trimmed[:idx + 1]
    return trimmed


def generate_cn_description(repo: dict) -> str:
    """
    生成一句话中文介绍（纯中文，用于列表、摘要中）
    从项目元数据综合生成，不夹杂英文原文
    """
    cn_topics = _pick_cn_topics(repo)
    name = repo.get("name", "").lower()
    language = repo.get("language", "Unknown")
    desc = repo.get("description", "").strip()

    # 如果描述本身是中文，直接用
    if desc and _is_mostly_chinese(desc):
        return desc[:120]

    # 项目类型推断
    type_hint = ""
    for pat, hint in _NAME_HINTS:
        if re.search(pat, name):
            type_hint = hint
            break

    # 构建纯中文描述
    parts = []
    if cn_topics:
        parts.append("、".join(cn_topics[:3]))

    if type_hint:
        parts.append(type_hint)

    if language and language != "Unknown":
        parts.append(f"使用{language}开发")

    if not parts:
        return f"GitHub 热门开源项目（{language}）"

    return "，".join(parts) + "。"


def generate_cn_detail(repo: dict) -> str:
    """
    生成详细中文介绍（纯中文，2-3句，用于重点区域）

    结构：
    1. 定位句：领域 + 项目类型 + 语言
    2. 数据句：Star 数 + 热度说明
    不夹杂英文原文描述
    """
    cn_topics = _pick_cn_topics(repo)
    name = repo.get("name", "").lower()
    full_name = repo.get("full_name", "")
    language = repo.get("language", "Unknown")
    desc = repo.get("description", "").strip()
    stars = repo.get("stars", 0)
    stars_today = repo.get("stars_in_period", 0) or 0
    tags = repo.get("tags", [])

    # 项目类型推断
    type_hint = ""
    for pat, hint in _NAME_HINTS:
        if re.search(pat, name):
            type_hint = hint
            break

    sentences = []

    # ── 第 1 句：项目定位 ───────────────────────────────
    topic_str = "、".join(cn_topics[:3]) if cn_topics else ""
    if topic_str:
        first = f"这是一个{topic_str}领域的开源项目"
        if type_hint:
            first += f"，属于{type_hint}"
    elif type_hint:
        first = f"这是一个{type_hint}"
    else:
        first = f"这是一个GitHub热门开源项目"

    if language and language != "Unknown":
        first += f"，使用 {language} 开发"

    # 如果描述是中文，附带简短说明
    if desc and _is_mostly_chinese(desc):
        first += f"，{desc[:80]}"

    sentences.append(first + "。")

    # ── 第 2 句：数据 + 热度 ──────────────────────────────
    data_part = f"当前总星数 {stars:,}"
    if tags:
        tag_str = "、".join(tags)
        if stars_today > 5000:
            data_part += f"，作为{tag_str}方向的明星项目，今日新增 {stars_today:,} 星，增速惊人"
        elif stars_today > 1000:
            data_part += f"，属于{tag_str}方向的热门项目，今日新增 {stars_today:,} 星"
        else:
            data_part += f"，属于{tag_str}方向"
    elif stars_today > 5000:
        data_part += f"，今日新增 {stars_today:,} 星，是当前 GitHub 热度最高的项目之一"
    elif stars_today > 1000:
        data_part += f"，今日新增 {stars_today:,} 星，关注度持续攀升"

    sentences.append(data_part + "。")

    return "".join(sentences)


def _ecosystem_hint(topics: list[str]) -> str:
    """检测项目生态"""
    t = " ".join(topics).lower()
    if any(k in t for k in ("claude", "anthropic")):
        return "Claude/Anthropic"
    if any(k in t for k in ("openai", "gpt", "chatgpt", "codex")):
        return "OpenAI"
    if any(k in t for k in ("deepseek",)):
        return "DeepSeek"
    if any(k in t for k in ("llama", "meta")):
        return "Meta Llama"
    if any(k in t for k in ("cursor",)):
        return "Cursor"
    if any(k in t for k in ("langchain",)):
        return "LangChain"
    if any(k in t for k in ("pytorch", "tensorflow")):
        return "深度学习框架"
    if any(k in t for k in ("kubernetes", "k8s")):
        return "云原生/K8s"
    if any(k in t for k in ("react", "vue", "nextjs")):
        return "前端开发"
    if any(k in t for k in ("mcp",)):
        return "MCP 协议"
    return ""


def generate_cn_intro_with_readme(repo: dict, readme_text: str = "") -> str:
    """
    结合元数据生成中文项目介绍（纯中文，LLM 不可用时的备选方案）

    Returns 结构化介绍：项目定位 + 适用场景 + 技术栈 + 热度
    """
    cn_topics = _pick_cn_topics(repo)
    name = repo.get("name", "").lower()
    full_name = repo.get("full_name", "")
    language = repo.get("language", "Unknown")
    desc = repo.get("description", "").strip()
    stars = repo.get("stars", 0)
    stars_today = repo.get("stars_in_period", 0) or 0
    tags = repo.get("tags", [])
    ecosystem = _ecosystem_hint(repo.get("topics", []))

    # 项目类型
    type_hint = ""
    for pat, hint in _NAME_HINTS:
        if re.search(pat, name):
            type_hint = hint
            break

    sections = []

    # 1. 项目定位
    topic_str = "、".join(cn_topics[:3]) if cn_topics else "通用"
    loc = f"**📌 项目定位**：{full_name} 是一个{topic_str}领域的开源项目"
    if type_hint:
        loc += f"，属于{type_hint}"
    loc += "。"
    sections.append(loc)

    # 2. 项目简介（用描述或话题推断）
    if desc and _is_mostly_chinese(desc):
        sections.append(f"**💡 项目简介**：{desc[:150]}。")
    elif desc:
        # 英文描述：提取关键信息，用中文说明
        short = _clean_english_desc(desc)
        if short:
            sections.append(f"**💡 项目简介**：该项目主要涉及{f'，'.join(cn_topics[:5]) if cn_topics else topic_str}相关内容。")
    else:
        if cn_topics:
            sections.append(f"**💡 项目简介**：该项目聚焦于{'、'.join(cn_topics[:5])}等方向。")

    # 3. 用途/场景
    use_cases = _infer_use_cases(repo, readme_text)
    if use_cases:
        sections.append(f"**🎯 适用场景**：{use_cases}。")

    # 4. 技术栈
    tech_parts = [f"使用 **{language}** 开发"]
    if ecosystem:
        tech_parts.append(f"属于 **{ecosystem}** 生态")
    tech_parts.append(f"当前总星数 **{stars:,}**")
    sections.append(f"**🛠️ 技术栈**：{'，'.join(tech_parts)}。")

    # 5. 热度
    if stars_today > 5000:
        sections.append(
            f"**📈 今日热度**：新增 **{stars_today:,}** Star，增速极其迅猛，"
            f"是当前 GitHub 最受关注的项目之一。"
        )
    elif stars_today > 1000:
        sections.append(
            f"**📈 今日热度**：新增 **{stars_today:,}** Star，热度持续攀升。"
        )

    return "\n\n".join(sections)


def _extract_readme_intro(readme: str) -> str:
    """
    从 README 文本中提取项目介绍

    策略：跳过标题/徽章/目录，找到第一个有实质内容的段落
    """
    lines = readme.strip().split("\n")
    paragraphs = []
    current = []

    for line in lines:
        stripped = line.strip()

        # 空行 = 段落边界
        if not stripped:
            if current:
                para = " ".join(current).strip()
                if len(para) > 40:  # 有实质内容
                    paragraphs.append(para)
                current = []
            continue

        # 跳过的模式
        skip = False
        for pat in [
            r'^#+\s', r'^\*{3,}', r'^---+', r'^\[!\[', r'^<p',
            r'^<div', r'^<a\s', r'^</', r'^<!--', r'^-->',
            r'^!\[', r'^\s*\[', r'^\s*\|', r'^&nbsp;',
        ]:
            if re.match(pat, stripped):
                skip = True
                break

        # 跳过多语言标记行
        if re.match(r'^\[?(English|中文|日本語|한국어|Español|Français|Deutsch|Português|Русский)', stripped, re.IGNORECASE):
            skip = True
        # 跳过纯链接/标签行
        if re.match(r'^https?://', stripped):
            skip = True
        if re.match(r'^\!\[', stripped):
            skip = True
        # 跳过纯特殊字符
        if len(stripped) < 15 and re.match(r'^[\W_]+$', stripped):
            skip = True

        if not skip:
            current.append(stripped)

        # 收集到足够段落就停止
        if len(paragraphs) >= 2:
            break

    # 处理最后一个段落
    if current and len(paragraphs) < 2:
        para = " ".join(current).strip()
        if len(para) > 40:
            paragraphs.append(para)

    if not paragraphs:
        return ""

    text = " ".join(paragraphs[:2])
    if len(text) > 500:
        text = text[:500].rsplit(".", 1)[0] + "."
    return text.strip()


def _infer_use_cases(repo: dict, readme: str = "") -> str:
    """根据项目信息推断使用场景"""
    topics = [t.lower() for t in repo.get("topics", [])]
    name = repo.get("name", "").lower()
    desc = (repo.get("description", "") + " " + readme[:300]).lower()
    tags = repo.get("tags", [])

    cases = []

    # AI Agent / 编程相关
    if any(k in topics for k in ("agent", "coding-agent", "claude-code")):
        cases.append("AI 编程辅助和自动化")
    if any(k in desc for k in ("claude code", "claude desktop", "coding agent")):
        if "AI 编程辅助和自动化" not in cases:
            cases.append("AI 编程辅助")

    # 设计相关
    if any(k in topics for k in ("design", "ui", "figma")):
        cases.append("设计稿生成和 UI 开发")
    if "design" in name:
        if "设计稿生成" not in str(cases):
            cases.append("设计/原型生成")

    # 金融
    if any(k in topics for k in ("trading", "finance", "financial")):
        cases.append("金融交易和量化分析")

    # 视频
    if any(k in topics for k in ("video", "media")):
        cases.append("视频内容创作和处理")

    # 浏览器自动化
    if any(k in topics for k in ("browser", "playwright", "puppeteer", "selenium")):
        cases.append("浏览器自动化和网页操作")

    # 文档/签名 (使用更精确的匹配，避免 "esign" 误匹配 "design")
    if any(k in desc for k in ("docusign", "e-sign", "esignature", "digital signature", "document signing", "fill and sign")):
        cases.append("电子文档签署和管理")

    # RAG
    if any(k in topics for k in ("rag", "retrieval")):
        cases.append("知识检索和问答系统")

    # 工作流
    if any(k in topics for k in ("workflow", "orchestration")):
        cases.append("任务编排和工作流自动化")

    # 安全
    if any(k in topics for k in ("security", "osint")):
        cases.append("安全研究和信息收集")

    # 具身智能
    if "具身智能" in tags or "robotics" in topics:
        cases.append("机器人和具身智能研究")

    if not cases:
        # 泛化推断
        if "tool" in topics or "cli" in topics:
            cases.append("开发者日常工具使用")
        elif "framework" in topics or "library" in topics:
            cases.append("应用开发的底层支撑")
        elif "awesome" in topics:
            cases.append("技术资源查找和学习参考")
        else:
            return ""  # 推断不出就不写

    return "、".join(cases[:3])

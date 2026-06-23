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
    language = repo.get("language") or "Unknown"
    desc = (repo.get("description") or "").strip()
    stars = repo.get("stars") or 0
    stars_today = repo.get("stars_in_period") or 0
    tags = repo.get("tags") or []

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
    结合元数据 + README 生成多维度中文项目介绍（纯中文，LLM 不可用时的备选）

    Returns 格式与 LLM 输出对齐：
    🚀 一句话定位 / 💡 核心价值 / 🎯 多维解读 / 📊 数据洞察
    """
    cn_topics = _pick_cn_topics(repo)
    name = repo.get("name", "").lower()
    full_name = repo.get("full_name", "")
    language = repo.get("language") or "Unknown"
    desc = (repo.get("description") or "").strip()
    stars = repo.get("stars") or 0
    stars_today = repo.get("stars_in_period") or 0
    forks = repo.get("forks") or 0
    tags = repo.get("tags") or []
    topics = repo.get("topics", [])
    ecosystem = _ecosystem_hint(topics)
    extra = repo.get("_extra", {}) or {}

    burst = repo.get("burst_score", 0)
    quality = repo.get("quality_score", 0)
    strea = repo.get("streak_days", 0)

    contributors = extra.get("contributors", 0)
    open_issues = extra.get("open_issues", 0)
    last_push = extra.get("last_push_days", 999)
    releases = extra.get("releases", 0)

    # 项目类型
    type_hint = ""
    for pat, hint in _NAME_HINTS:
        if re.search(pat, name):
            type_hint = hint
            break

    # 生态标签
    eco_tags = []
    try:
        from src.processor.ai_scoring import get_eco_tags
        eco_tags = get_eco_tags(repo)
    except Exception:
        pass

    sections = []

    # ── 🚀 一句话定位 ──────────────────────────────────
    topic_str = "、".join(cn_topics[:3]) if cn_topics else "通用"
    loc = f"🚀 **一句话定位**：{full_name} 是一个{topic_str}领域的开源项目"
    if type_hint:
        loc += f"，属于{type_hint}"
    if desc and _is_mostly_chinese(desc):
        loc += f"——{desc[:80]}"
    loc += "。"
    sections.append(loc)

    # ── 💡 核心价值 ────────────────────────────────────
    pain_points = _infer_pain_points(repo, readme_text)
    if pain_points:
        sections.append(f"💡 **核心价值**：{pain_points}")
    else:
        value_parts = []
        if stars_today >= 1000:
            value_parts.append(f"今日新增 {stars_today:,} Star，增速惊人")
        if quality >= 0.5:
            value_parts.append("社区健康度优秀")
        if eco_tags:
            value_parts.append(f'属于 {"、".join(eco_tags[:3])} 生态')
        if value_parts:
            sections.append(f"💡 **核心价值**：{'，'.join(value_parts)}。")
        elif desc:
            sections.append(f"💡 **核心价值**：{_clean_english_desc(desc)}。")
        else:
            sections.append(f"💡 **核心价值**：该项目聚焦于{'、'.join(cn_topics[:5]) if cn_topics else topic_str}，具备较强的实用价值。")

    # ── 🎯 多维解读 ────────────────────────────────────
    multi_parts = []

    # 技术亮点
    tech_parts = []
    if language and language != "Unknown":
        tech_parts.append(f"使用 {language} 开发")
    if ecosystem:
        tech_parts.append(f"属于 {ecosystem} 生态")
    if contributors >= 10:
        tech_parts.append(f"{contributors} 人协作贡献")
    if releases >= 5:
        tech_parts.append(f"已发布 {releases} 个 Release")
    if last_push <= 7:
        tech_parts.append("维护非常活跃")
    if tech_parts:
        multi_parts.append(f"- **技术亮点**：{'，'.join(tech_parts)}")

    # 用户画像
    user_hint = _infer_user_profile(repo)
    if user_hint:
        multi_parts.append(f"- **用户画像**：{user_hint}")

    # 场景落地
    use_cases = _infer_use_cases(repo, readme_text)
    if use_cases:
        multi_parts.append(f"- **场景落地**：{use_cases}")

    if multi_parts:
        sections.append(f"🎯 **多维解读**：\n{chr(10).join(multi_parts)}")
    else:
        sections.append(f"🎯 **多维解读**：\n- 技术栈以 {language} 为主\n- 适合关注 {'、'.join(cn_topics[:3]) if cn_topics else '开源'} 的开发者关注")

    # ── 📊 数据洞察 ────────────────────────────────────
    insights = []
    if burst > 0 and quality >= 0.4:
        insights.append(f"爆发分 {burst:.2f} + 质量分 {quality:.2f}，属于双高项目，正在快速增长")
    elif burst > 0:
        insights.append(f"爆发分 {burst:.2f}，增速突出")
    elif quality >= 0.5:
        insights.append(f"质量分 {quality:.2f}，社区工程成熟度高")

    if stars_today >= 5000:
        insights.append(f"今日新增 {stars_today:,} Star，处于全网热度头部")
    elif stars_today >= 1000:
        insights.append(f"今日新增 {stars_today:,} Star，热度持续攀升")

    if strea >= 5:
        insights.append(f"连续 {strea} 天在榜，关注度稳定")

    if open_issues > 50:
        insights.append(f"开放 Issue 数量较高（{open_issues}），需关注维护压力")

    if not insights:
        insights.append(f"⭐ {stars:,} Star，{language} 生态中值得关注的项目")

    sections.append(f"📊 **数据洞察**：{'；'.join(insights)}。")

    return "\n\n".join(sections)


def _infer_pain_points(repo: dict, readme: str = "") -> str:
    """根据项目元数据推断解决的痛点"""
    topics = [t.lower() for t in repo.get("topics", [])]
    name = repo.get("name", "").lower()
    desc = (repo.get("description", "") or "").lower()

    pain = []

    if any(k in desc or k in " ".join(topics) for k in ("api", "no-api", "free")):
        pain.append("降低 API 使用门槛和成本")
    if any(k in desc or k in " ".join(topics) for k in ("browser", "scraping", "crawler")):
        pain.append("自动化浏览器操作和网页数据抓取")
    if any(k in desc or k in " ".join(topics) for k in ("agent", "automation", "autonomous")):
        pain.append("让 AI Agent 具备自主执行任务的能力")
    if any(k in desc or k in " ".join(topics) for k in ("security", "osint", "privacy")):
        pain.append("提升信息安全和隐私保护能力")
    if any(k in desc or k in " ".join(topics) for k in ("design", "ui", "figma")):
        pain.append("加速设计到代码的转换效率")
    if any(k in desc or k in " ".join(topics) for k in ("video", "media", "streaming")):
        pain.append("简化视频和媒体内容创作流程")
    if any(k in desc or k in " ".join(topics) for k in ("trading", "finance", "quant")):
        pain.append("降低量化交易策略开发门槛")
    if any(k in desc or k in " ".join(topics) for k in ("database", "sql", "storage")):
        pain.append("解决数据存储和查询的性能瓶颈")
    if any(k in desc or k in " ".join(topics) for k in ("doc", "sign", "pdf")):
        pain.append("数字化传统纸质文档签署流程")
    if any(k in desc or k in " ".join(topics) for k in ("monitoring", "observability", "logging")):
        pain.append("提升系统可观测性和故障排查效率")

    if not pain:
        # 从描述推断
        if repo.get("description"):
            return f"解决 {repo['description'][:100]} 等实际问题"
        return ""

    return "；".join(pain[:3])


def _infer_user_profile(repo: dict) -> str:
    """推断典型用户群体"""
    topics = [t.lower() for t in repo.get("topics", [])]
    desc = (repo.get("description", "") or "").lower()

    if any(k in desc or k in " ".join(topics) for k in ("agent", "claude", "llm", "ai")):
        return "AI 开发者和 Agent 构建者"
    if any(k in desc or k in " ".join(topics) for k in ("react", "vue", "frontend", "ui")):
        return "前端开发者和 UI 设计师"
    if any(k in desc or k in " ".join(topics) for k in ("rust", "cargo", "systems")):
        return "系统编程和 Rust 生态开发者"
    if any(k in desc or k in " ".join(topics) for k in ("python", "data", "ml")):
        return "数据科学家和 Python 开发者"
    if any(k in desc or k in " ".join(topics) for k in ("kubernetes", "docker", "devops")):
        return "DevOps 和云原生工程师"
    if any(k in desc or k in " ".join(topics) for k in ("mobile", "ios", "android", "flutter")):
        return "移动端开发者和跨平台团队"
    if any(k in desc or k in " ".join(topics) for k in ("security", "osint", "hacking")):
        return "安全研究人员和白帽黑客"
    if any(k in desc or k in " ".join(topics) for k in ("game", "engine", "3d")):
        return "游戏开发者和图形工程师"
    if any(k in desc or k in " ".join(topics) for k in ("finance", "trading", "quant")):
        return "量化交易和金融科技从业者"
    return "关注技术前沿的开发者"


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
    desc = ((repo.get("description") or "") + " " + (readme or "")[:300]).lower()
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

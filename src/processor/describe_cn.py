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
    # ── 嵌入式 / 硬件 / 电子 ──
    "embedded": "嵌入式开发",
    "esp32": "ESP32嵌入式",
    "esp8266": "ESP8266嵌入式",
    "stm32": "STM32微控制器",
    "arduino": "Arduino开发",
    "microcontroller": "微控制器",
    "firmware": "固件开发",
    "rtos": "RTOS",
    "freertos": "FreeRTOS",
    "zephyr": "Zephyr RTOS",
    "bare-metal": "裸机开发",
    "iot": "物联网",
    "mqtt": "MQTT通信",
    "smart-home": "智能家居",
    "home-automation": "家居自动化",
    "home-assistant": "Home Assistant",
    "zigbee": "Zigbee",
    "lora": "LoRa通信",
    "lorawan": "LoRaWAN",
    "pcb": "PCB设计",
    "kicad": "KiCad硬件设计",
    "easyeda": "EasyEDA硬件设计",
    "altium": "Altium Designer",
    "fpga": "FPGA",
    "verilog": "Verilog",
    "vhdl": "VHDL",
    "eda": "EDA工具",
    "circuit": "电路设计",
    "electronics": "电子工程",
    "hardware": "硬件开发",
    "soc": "SoC芯片",
    "semiconductor": "半导体",
    "chip-design": "芯片设计",
    "silicon": "硅芯片",
    "dsp": "数字信号处理",
    "signal-processing": "信号处理",
    "sdr": "软件无线电",
    "rfid": "RFID",
    "nfc": "NFC",
    "antenna": "天线设计",
    "power-system": "电力系统",
    "power-electronics": "电力电子",
    "scada": "SCADA工控",
    "plc": "PLC工控",
    "modbus": "Modbus通信",
    "battery": "电池管理",
    "solar": "太阳能",
    "inverter": "逆变器",
    "robotics": "机器人",
    "ros": "ROS机器人",
    "ros2": "ROS2机器人",
    "robot": "机器人",
    "autonomous-driving": "自动驾驶",
    "self-driving": "自动驾驶",
    "can-bus": "CAN总线",
    "3d-printing": "3D打印",
    "cnc": "CNC数控",
    "cad": "CAD设计",
    "freecad": "FreeCAD",
    "openscad": "OpenSCAD",
    "medical": "医疗设备",
    "bioinformatics": "生物信息",
    "bci": "脑机接口",
    "gis": "地理信息",
    "bim": "BIM建筑",
    "structural": "结构工程",
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
    # ── 嵌入式 / 硬件 ──
    (r"esp32", "ESP32 嵌入式开发"),
    (r"esp8266", "ESP8266 嵌入式开发"),
    (r"stm32", "STM32 微控制器开发"),
    (r"arduino", "Arduino 开发板项目"),
    (r"freertos", "FreeRTOS 实时操作系统"),
    (r"zephyr", "Zephyr RTOS 项目"),
    (r"kicad", "KiCad 硬件设计工具"),
    (r"pcb", "PCB 电路板设计"),
    (r"fpga", "FPGA 开发项目"),
    (r"robotic", "机器人控制项目"),
    (r"home-assistant", "Home Assistant 智能家居"),
    (r"smart-home", "智能家居项目"),
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


def _topic_in_list(keyword: str, topics: list[str]) -> bool:
    """检查 keyword 是否在 topics 列表中（精确匹配，支持 hyphen 分割）"""
    for t in topics:
        if keyword == t or keyword in t.split("-"):
            return True
    return False


def _ecosystem_hint(topics: list[str]) -> str:
    """检测项目生态（使用精确 topic 匹配，避免子串误匹配）"""
    t = [t.lower() for t in topics]
    if _topic_in_list("claude", t) or _topic_in_list("anthropic", t):
        return "Claude/Anthropic"
    if any(_topic_in_list(k, t) for k in ("openai", "gpt", "chatgpt", "codex")):
        return "OpenAI"
    if _topic_in_list("deepseek", t):
        return "DeepSeek"
    if _topic_in_list("llama", t) or _topic_in_list("meta", t):
        return "Meta Llama"
    if _topic_in_list("cursor", t):
        return "Cursor"
    if _topic_in_list("langchain", t):
        return "LangChain"
    if _topic_in_list("pytorch", t) or _topic_in_list("tensorflow", t):
        return "深度学习框架"
    if any(_topic_in_list(k, t) for k in ("kubernetes", "k8s")):
        return "云原生/K8s"
    if any(_topic_in_list(k, t) for k in ("react", "vue", "nextjs")):
        return "前端开发"
    if _topic_in_list("mcp", t):
        return "MCP 协议"
    if any(_topic_in_list(k, t) for k in ("esp32", "esp8266")):
        return "ESP32 嵌入式"
    if any(_topic_in_list(k, t) for k in ("stm32", "hal", "cube")):
        return "STM32 嵌入式"
    if _topic_in_list("arduino", t):
        return "Arduino"
    if any(_topic_in_list(k, t) for k in ("freertos", "rtos", "zephyr")):
        return "RTOS 嵌入式"
    if any(_topic_in_list(k, t) for k in ("embedded", "firmware", "bare-metal")):
        return "嵌入式开发"
    if any(_topic_in_list(k, t) for k in ("kicad", "altium", "easyeda")):
        return "EDA 硬件设计"
    if any(_topic_in_list(k, t) for k in ("fpga", "verilog", "vhdl")):
        return "FPGA 开发"
    if any(_topic_in_list(k, t) for k in ("ros", "ros2", "robotics")):
        return "ROS 机器人"
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
    streak = repo.get("streak_days", 0)

    contributors = extra.get("contributors", 0)
    open_issues = extra.get("open_issues", 0)
    last_push = extra.get("last_push_days")  # None = 无数据
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
    if last_push is not None and last_push <= 7:
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

    if streak >= 5:
        insights.append(f"连续 {streak} 天在榜，关注度稳定")

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

    if any(_topic_match(k, topics, desc) for k in ("api", "no-api", "free")):
        pain.append("降低 API 使用门槛和成本")
    if any(_topic_match(k, topics, desc) for k in ("browser", "scraping", "crawler")):
        pain.append("自动化浏览器操作和网页数据抓取")
    if any(_topic_match(k, topics, desc) for k in ("agent", "automation", "autonomous")):
        pain.append("让 AI Agent 具备自主执行任务的能力")
    if any(_topic_match(k, topics, desc) for k in ("security", "osint", "privacy")):
        pain.append("提升信息安全和隐私保护能力")
    if any(_topic_match(k, topics, desc) for k in ("design", "ui", "figma")):
        pain.append("加速设计到代码的转换效率")
    if any(_topic_match(k, topics, desc) for k in ("video", "media", "streaming")):
        pain.append("简化视频和媒体内容创作流程")
    if any(_topic_match(k, topics, desc) for k in ("trading", "finance", "quant")):
        pain.append("降低量化交易策略开发门槛")
    if any(_topic_match(k, topics, desc) for k in ("database", "sql", "storage")):
        pain.append("解决数据存储和查询的性能瓶颈")
    if any(_topic_match(k, topics, desc) for k in ("document", "docs", "documentation", "sign", "pdf")):
        pain.append("数字化传统纸质文档签署流程")
    if any(_topic_match(k, topics, desc) for k in ("monitoring", "observability", "logging")):
        pain.append("提升系统可观测性和故障排查效率")
    if any(_topic_match(k, topics, desc) for k in ("esp32", "esp8266", "stm32", "arduino", "microcontroller", "embedded", "firmware")):
        pain.append("降低嵌入式开发和固件烧录的门槛")
    if any(_topic_match(k, topics, desc) for k in ("iot", "mqtt", "smart-home", "home-automation")):
        pain.append("简化物联网设备互联和家居自动化配置")
    if any(_topic_match(k, topics, desc) for k in ("pcb", "kicad", "circuit", "hardware-design", "eda")):
        pain.append("加速硬件设计和 PCB 制板流程")
    if any(_topic_match(k, topics, desc) for k in ("fpga", "verilog", "vhdl", "dsp", "signal-processing")):
        pain.append("降低数字信号处理和硬件描述语言开发难度")
    if any(_topic_match(k, topics, desc) for k in ("robotics", "ros", "robot", "manipulator")):
        pain.append("简化机器人控制和运动学算法实现")
    if any(_topic_match(k, topics, desc) for k in ("plc", "scada", "modbus", "industrial-automation")):
        pain.append("降低工业控制和自动化系统集成成本")
    if any(_topic_match(k, topics, desc) for k in ("power-system", "power-electronics", "battery", "solar", "inverter")):
        pain.append("优化电力系统管理和能源转换效率")

    if not pain:
        # 从描述推断
        if repo.get("description"):
            return f"解决 {repo['description'][:100]} 等实际问题"
        return ""

    return "；".join(pain[:3])


def _topic_match(keyword: str, topics: list[str], desc: str) -> bool:
    """检查关键词是否匹配：短关键词用词边界，避免 ui 匹配 suite/arduino"""
    # 短关键词（≤3字符且纯字母）用词边界匹配 description
    if len(keyword) <= 3 and keyword.isalpha():
        if re.search(r'\b' + re.escape(keyword) + r'\b', desc):
            return True
    else:
        if keyword in desc:
            return True
    # topics 用精确匹配（支持 hyphen 分割）
    for t in topics:
        if keyword == t or keyword in t.split("-"):
            return True
    return False


def _infer_user_profile(repo: dict) -> str:
    """推断典型用户群体"""
    topics = [t.lower() for t in repo.get("topics", [])]
    desc = (repo.get("description", "") or "").lower()

    if any(_topic_match(k, topics, desc) for k in ("agent", "claude", "llm", "ai")):
        return "AI 开发者和 Agent 构建者"
    if any(_topic_match(k, topics, desc) for k in ("react", "vue", "frontend", "ui", "figma")):
        return "前端开发者和 UI 设计师"
    if any(_topic_match(k, topics, desc) for k in ("rust", "cargo", "systems")):
        return "系统编程和 Rust 生态开发者"
    if any(_topic_match(k, topics, desc) for k in ("python", "data", "ml")):
        return "数据科学家和 Python 开发者"
    if any(_topic_match(k, topics, desc) for k in ("kubernetes", "docker", "devops")):
        return "DevOps 和云原生工程师"
    if any(_topic_match(k, topics, desc) for k in ("mobile", "ios", "android", "flutter")):
        return "移动端开发者和跨平台团队"
    if any(_topic_match(k, topics, desc) for k in ("security", "osint", "hacking")):
        return "安全研究人员和白帽黑客"
    if any(_topic_match(k, topics, desc) for k in ("game", "engine", "3d")):
        return "游戏开发者和图形工程师"
    if any(_topic_match(k, topics, desc) for k in ("finance", "trading", "quant")):
        return "量化交易和金融科技从业者"
    if any(_topic_match(k, topics, desc) for k in ("esp32", "esp8266", "stm32", "arduino", "microcontroller", "embedded", "firmware", "rtos", "freertos")):
        return "嵌入式开发者和固件工程师"
    if any(_topic_match(k, topics, desc) for k in ("iot", "mqtt", "smart-home", "home-automation", "lorawan")):
        return "物联网开发者和智能家居集成商"
    if any(_topic_match(k, topics, desc) for k in ("pcb", "kicad", "circuit", "hardware-design", "eda", "schematic")):
        return "硬件工程师和电路设计者"
    if any(_topic_match(k, topics, desc) for k in ("fpga", "verilog", "vhdl")):
        return "FPGA 开发者和数字电路设计者"
    if any(_topic_match(k, topics, desc) for k in ("dsp", "signal-processing", "adc", "dac")):
        return "信号处理工程师和算法开发者"
    if any(_topic_match(k, topics, desc) for k in ("robotics", "ros", "ros2", "robot")):
        return "机器人开发者和自动化工程师"
    if any(_topic_match(k, topics, desc) for k in ("plc", "scada", "modbus", "industrial-automation")):
        return "工业控制和自动化工程师"
    if any(_topic_match(k, topics, desc) for k in ("power-system", "power-electronics", "battery", "solar", "inverter", "grid")):
        return "电力系统工程师和能源管理从业者"
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

    # 嵌入式 / 硬件
    if any(k in topics for k in ("esp32", "esp8266", "stm32", "arduino", "microcontroller")):
        cases.append("嵌入式设备开发和固件烧录")
    if any(k in topics for k in ("embedded", "firmware", "rtos", "freertos")):
        cases.append("嵌入式系统开发和实时操作系统")
    if any(k in topics for k in ("pcb", "kicad", "circuit", "hardware-design")):
        cases.append("PCB 电路设计和硬件原型开发")
    if any(k in topics for k in ("fpga", "verilog", "vhdl")):
        cases.append("FPGA 开发和数字电路设计")
    if any(k in topics for k in ("dsp", "signal-processing")):
        cases.append("数字信号处理和音频/视频编解码")
    if any(k in topics for k in ("plc", "scada", "modbus")):
        cases.append("工业控制和自动化系统集成")
    if any(k in topics for k in ("power-system", "power-electronics", "battery", "solar")):
        cases.append("电力系统和能源管理")

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


# ── 6 维度结构化介绍（统一基础模块与自定义模块） ──────────

def _split_llm_sections(text: str) -> dict:
    """将 LLM 文本按板块拆分为 {header: content} 字典。

    识别形如 `🚀 **一句话定位**` 的板块头，内容取到下一个板块头为止。
    """
    header_re = re.compile(r'^[^\x00-\x7f]\s*\*\*([^*]+)\*\*', re.MULTILINE)
    matches = list(header_re.finditer(text))
    sections = {}
    for i, m in enumerate(matches):
        header = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[start:end].strip()
        # 去掉开头可能残留的冒号
        content = re.sub(r'^[：:]\s*', '', content)
        sections[header] = content
    return sections


def _match_section(sections: dict, headers: list[str]) -> str:
    """按候选标题从 sections 中模糊匹配内容。"""
    for h in headers:
        for key, val in sections.items():
            if h in key:
                return val
    return ""


def _extract_subsection(multi_text: str, label: str) -> str:
    """从"多维解读"板块中提取子项（技术亮点/用户画像/场景落地）。"""
    if not multi_text:
        return ""
    pattern = (
        r'\*\*' + re.escape(label) + r'\*\*\s*[：:]\s*(.*?)'
        r'(?=\n\s*[-*]?\s*\*\*[^*]+\*\*|\Z)'
    )
    m = re.search(pattern, multi_text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return ""


def _clean_dim_text(text: str, limit: int = 100) -> str:
    """清理维度文本：合并空白、去换行、截断到指定长度。"""
    text = re.sub(r'\s+', ' ', text).strip()
    if len(text) > limit:
        text = text[:limit]
    return text


def _parse_llm_dimensions(llm_text: str) -> list[dict] | None:
    """从 LLM 生成的多板块文本中解析 6 个维度。

    LLM 输出格式：
      🚀 **一句话定位**：xxx
      💡 **核心价值**：xxx
      🎯 **多维解读**：
      - **技术亮点**：xxx
      - **用户画像**：xxx
      - **场景落地**：xxx
      📊 **数据洞察**：xxx
    """
    sections = _split_llm_sections(llm_text)
    if not sections:
        return None

    positioning = _match_section(sections, ["一句话定位", "定位"])
    core_value = _match_section(sections, ["核心价值"])
    multi = _match_section(sections, ["多维解读"])
    data_insight = _match_section(sections, ["数据洞察"])

    tech_highlight = _extract_subsection(multi, "技术亮点")
    user_profile = _extract_subsection(multi, "用户画像")
    use_case = _extract_subsection(multi, "场景落地")

    dims = [
        {"icon": "🚀", "label": "定位", "text": _clean_dim_text(positioning)},
        {"icon": "💡", "label": "核心价值", "text": _clean_dim_text(core_value)},
        {"icon": "🔧", "label": "技术亮点", "text": _clean_dim_text(tech_highlight)},
        {"icon": "👥", "label": "用户画像", "text": _clean_dim_text(user_profile)},
        {"icon": "🎯", "label": "使用场景", "text": _clean_dim_text(use_case)},
        {"icon": "❤️", "label": "健康度", "text": _clean_dim_text(data_insight)},
    ]

    # 至少能解析出"定位"或"核心价值"才算成功
    if not dims[0]["text"] and not dims[1]["text"]:
        return None
    return dims


def _build_rule_dimensions(repo: dict, readme: str) -> list[dict]:
    """用规则推断 6 个维度（复用已有的推断函数）。"""
    cn_topics = _pick_cn_topics(repo)
    name = repo.get("name", "").lower()
    language = repo.get("language") or "Unknown"
    desc = (repo.get("description") or "").strip()
    stars_today = repo.get("stars_in_period") or 0
    quality = repo.get("quality_score", 0)
    topics = repo.get("topics", [])
    extra = repo.get("_extra", {}) or {}

    contributors = extra.get("contributors", 0)
    releases = extra.get("releases", 0)
    last_push = extra.get("last_push_days")  # None = 无数据
    updated_days = extra.get("updated_days", -1)
    ecosystem = _ecosystem_hint(topics)

    # 项目类型
    type_hint = ""
    for pat, hint in _NAME_HINTS:
        if re.search(pat, name):
            type_hint = hint
            break

    topic_str = "、".join(cn_topics[:3]) if cn_topics else "通用"

    # ── 维度1：定位 ──
    loc_parts = [f"{topic_str}领域"]
    if type_hint:
        loc_parts.append(f"属于{type_hint}")
    if language and language != "Unknown":
        loc_parts.append(f"使用{language}开发")
    positioning = "，".join(loc_parts)
    if desc and _is_mostly_chinese(desc):
        positioning += f"——{desc[:50]}"
    positioning = _clean_dim_text(positioning)

    # ── 维度2：核心价值 ──
    pain = _infer_pain_points(repo, readme)
    value_parts = []
    if pain:
        value_parts.append(f"解决{pain}")
    if stars_today >= 1000:
        value_parts.append(f"今日新增{stars_today:,}星，增速突出")
    if quality >= 0.5:
        value_parts.append("社区健康度优秀")
    if not value_parts:
        value_parts.append(f"聚焦{topic_str}，具备较强实用价值")
    core_value = _clean_dim_text("；".join(value_parts))

    # ── 维度3：技术亮点 ──
    tech_parts = []
    if language and language != "Unknown":
        tech_parts.append(f"使用{language}开发")
    if ecosystem:
        tech_parts.append(f"属于{ecosystem}生态")
    if contributors >= 10:
        tech_parts.append(f"{contributors}人协作贡献")
    if releases >= 5:
        tech_parts.append(f"已发布{releases}个Release")
    if last_push is not None and last_push <= 7:
        tech_parts.append("维护非常活跃")
    if not tech_parts:
        tech_parts.append(f"以{language}为主的技术栈")
    tech_highlight = _clean_dim_text("，".join(tech_parts))

    # ── 维度4：用户画像 ──
    user_profile = _clean_dim_text(_infer_user_profile(repo))

    # ── 维度5：使用场景 ──
    use_cases = _infer_use_cases(repo, readme)
    if not use_cases:
        use_cases = f"适合关注{topic_str}的开发者使用"
    use_cases = _clean_dim_text(use_cases)

    # ── 维度6：健康度 ──
    health_parts = []
    if updated_days >= 0:
        if updated_days <= 7:
            health_parts.append(f"近期活跃（{updated_days}天前更新）")
        elif updated_days <= 30:
            health_parts.append(f"维护中（{updated_days}天前更新）")
        elif updated_days <= 180:
            health_parts.append(f"低频更新（{updated_days}天前更新）")
        else:
            health_parts.append(f"长期未更新（{updated_days}天前）")
    elif last_push is not None:
        if last_push <= 7:
            health_parts.append("近期有推送，维护活跃")
        elif last_push <= 30:
            health_parts.append(f"最近推送于{last_push}天前")
        elif last_push > 180:
            health_parts.append(f"已{last_push}天未推送")
    if contributors:
        health_parts.append(f"{contributors}位贡献者")
    if releases:
        health_parts.append(f"{releases}个版本")
    if not health_parts:
        health_parts.append("数据待补充")
    health = _clean_dim_text("·".join(health_parts))

    return [
        {"icon": "🚀", "label": "定位", "text": positioning},
        {"icon": "💡", "label": "核心价值", "text": core_value},
        {"icon": "🔧", "label": "技术亮点", "text": tech_highlight},
        {"icon": "👥", "label": "用户画像", "text": user_profile},
        {"icon": "🎯", "label": "使用场景", "text": use_cases},
        {"icon": "❤️", "label": "健康度", "text": health},
    ]


def generate_dimensions(repo: dict, readme: str = "", llm_text: str = "",
                         api_key: str = "", provider: str = "") -> list[dict]:
    """
    生成 6 维度结构化项目介绍，统一基础模块与自定义模块的展示维度。

    每个维度格式：{"icon": str, "label": str, "text": str}
    维度顺序固定：定位 / 核心价值 / 技术亮点 / 用户画像 / 使用场景 / 健康度

    - 当 llm_text 非空时，优先从中解析 6 维度，缺失项用规则补充
    - 当 api_key 非空时，调用 LLM 生成 llm_text（用用户自己的 key）
    - 否则用规则推断（复用 _pick_cn_topics / _infer_pain_points 等函数）
    """
    rule_dims = _build_rule_dimensions(repo, readme)

    # 如果没有 llm_text 但有 api_key，尝试调用 LLM 生成
    if not (llm_text and llm_text.strip()) and api_key and readme and len(readme) >= 50:
        try:
            from src.processor.llm_summarize import summarize_project
            llm_text = summarize_project(repo, readme, api_key=api_key, provider=provider) or ""
        except Exception:
            pass

    if not (llm_text and llm_text.strip()):
        return rule_dims

    parsed = _parse_llm_dimensions(llm_text)
    if not parsed:
        return rule_dims

    # 用规则补充 LLM 未解析出的维度
    result = []
    for i in range(6):
        if parsed[i]["text"]:
            result.append(parsed[i])
        else:
            result.append(rule_dims[i])
    return result

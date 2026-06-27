"""
自定义话题解析器

策略：规则优先 → LLM 兜底 → 降级防护（4 层防御体系）

支持传入用户自己的 api_key（自定义模块个人化，不消耗项目方额度）
兼容多家厂商：DeepSeek / OpenAI / Anthropic / 通义千问 / 智谱 / Moonshot / 自定义
"""
import json
import logging
import re

import requests

logger = logging.getLogger(__name__)

_INVALID_KEYS = ("", "sk-xxxxxxxxxxxx", "sk-xxx")


# ── 多厂商 API 配置 ────────────────────────────────
# 大部分国内厂商都兼容 OpenAI 格式，只是 endpoint 和 model 不同
_PROVIDER_CONFIG = {
    "deepseek": {
        "url": "https://api.deepseek.com/v1/chat/completions",
        "model": "deepseek-chat",
        "name": "DeepSeek",
    },
    "openai": {
        "url": "https://api.openai.com/v1/chat/completions",
        "model": "gpt-4o-mini",
        "name": "OpenAI",
    },
    "anthropic": {
        "url": "https://api.anthropic.com/v1/messages",
        "model": "claude-3-5-haiku-20241022",
        "name": "Anthropic Claude",
        "format": "anthropic",  # 特殊格式
    },
    "qwen": {
        "url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "model": "qwen-turbo",
        "name": "通义千问",
    },
    "zhipu": {
        "url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "model": "glm-4-flash",
        "name": "智谱清言",
    },
    "moonshot": {
        "url": "https://api.moonshot.cn/v1/chat/completions",
        "model": "moonshot-v1-8k",
        "name": "Moonshot Kimi",
    },
}


def _detect_provider(api_key: str, provider: str = "") -> str:
    """根据 key 前缀或显式 provider 参数判断厂商"""
    p = (provider or "").lower().strip()
    if p in _PROVIDER_CONFIG:
        return p
    # 自动识别
    k = (api_key or "").lower()
    if k.startswith("sk-or-"):
        return "openai"
    if k.startswith("sk-ant-"):
        return "anthropic"
    if k.startswith("sk-"):  # DeepSeek 默认
        return "deepseek"
    return "deepseek"  # 默认


def _resolve_key(api_key: str = "") -> str:
    """解析有效 key：仅使用传入的 key，不降级到环境变量

    自定义模块个人化原则：用户没填自己的 key → 只走规则匹配，不消耗项目方额度。
    """
    k = (api_key or "").strip()
    if k and k not in _INVALID_KEYS:
        return k
    return ""


def _has_llm(api_key: str = "") -> bool:
    return bool(_resolve_key(api_key))


def _call_llm(prompt: str, system: str, api_key: str, provider: str = "",
              max_tokens: int = 500, temperature: float = 0.1) -> str | None:
    """统一调用 LLM，返回 content 字符串

    支持 OpenAI 兼容格式 + Anthropic 特殊格式
    """
    key = _resolve_key(api_key)
    if not key:
        return None

    prov = _detect_provider(api_key, provider)
    cfg = _PROVIDER_CONFIG.get(prov, _PROVIDER_CONFIG["deepseek"])

    try:
        if cfg.get("format") == "anthropic":
            # Anthropic 特殊格式
            resp = requests.post(
                cfg["url"],
                headers={
                    "x-api-key": key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": cfg["model"],
                    "max_tokens": max_tokens,
                    "system": system,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["content"][0]["text"]
        else:
            # OpenAI 兼容格式（DeepSeek/通义/智谱/Moonshot 等）
            resp = requests.post(
                cfg["url"],
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": cfg["model"],
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "response_format": {"type": "json_object"},
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.warning(f"LLM call failed ({cfg['name']}): {e}")
        return None


# ── 第一层：规则匹配 ──────────────────────────────────
_COMMON_TOPICS = {
    # AI 相关
    "AI Agent": ["agent", "mcp", "langchain", "rag", "function-call", "skill", "orchestrat", "智能体", "代理"],
    "大模型": ["llm", "gpt", "llama", "chatgpt", "openai", "deepseek", "claude", "anthropic", "mistral", "大模型", "大语言模型"],
    "文生图": ["stable-diffusion", "image-generation", "dalle", "midjourney", "txt2img", "comfyui", "文生图", "图像生成"],
    "语音AI": ["tts", "stt", "speech", "whisper", "voice", "audio", "语音", "tts"],
    "具身智能": ["embodied", "embodied-ai", "embodied-intelligence", "embodied-agent", "robotics", "robot", "robot-learning", "manipulation", "locomotion", "sim2real", "embodied-intelligence", "具身智能", "具身"],
    # 金融
    "量化交易": ["trading", "quant", "backtest", "strategy", "algorithmic-trading", "trading-bot", "quantitative", "cryptocurrency", "量化", "量化交易"],
    "金融": ["finance", "financial", "fintech", "banking", "payment", "stripe", "paypal", "金融"],
    # 开发工具
    "游戏开发": ["game", "game-engine", "unity", "unreal", "godot", "game-dev", "opengl", "directx", "游戏开发", "游戏引擎"],
    "前端框架": ["react", "vue", "angular", "svelte", "nextjs", "frontend", "tailwind", "前端"],
    "后端框架": ["django", "flask", "fastapi", "express", "spring", "laravel", "backend", "后端"],
    "数据库": ["database", "sql", "nosql", "postgres", "mysql", "redis", "mongodb", "数据库"],
    "DevOps": ["devops", "kubernetes", "k8s", "ci-cd", "terraform", "ansible", "jenkins", "gitops", "运维"],
    "CLI工具": ["cli-tool", "terminal", "tui", "command-line", "bash-script", "zsh", "命令行"],
    # 安全
    "安全工具": ["security-tool", "pentest", "osint", "exploit", "cve", "vulnerability", "infosec", "cybersecurity", "安全", "网络安全"],
    # 热门语言生态
    "Rust生态": ["rust", "cargo", "wasm", "tokio", "actix"],
    "Python生态": ["python", "pypi", "django", "flask", "fastapi", "jupyter"],
    "Go生态": ["golang", "go-lang", "gin-go", "echo-go", "fiber-go"],
    "TypeScript生态": ["typescript", "ts-node", "bun-js", "deno"],
    # 其他热门
    "区块链": ["blockchain", "web3", "ethereum", "solidity", "defi", "nft", "bitcoin", "区块链"],
    "机器人": ["robotics", "robot", "ros", "embodied", "robot-arm", "机器人", "机械臂"],
    "视频处理": ["video-processing", "ffmpeg", "video-streaming", "video-encoding", "video-editing", "youtube-dl", "视频"],
    "桌面应用": ["desktop", "electron", "tauri", "gui", "gtk", "qt", "wpf", "桌面"],
    "移动开发": ["mobile", "android", "ios", "flutter", "react-native", "swift", "kotlin", "移动"],
    "云计算": ["cloud-native", "aws", "azure", "gcp", "serverless", "kubernetes", "terraform", "云计算", "云原生"],
    "API开发": ["api-gateway", "rest-api", "graphql", "grpc", "swagger", "openapi", "restful"],
    "数据科学": ["data-science", "pandas", "numpy", "matplotlib", "jupyter", "analytics", "数据科学"],
    "设计工具": ["design-tool", "figma", "ux-design", "ui-design", "css-framework", "design-system", "prototyping", "ui-ux",
                "设计工具", "ui设计", "ux设计"],
    "测试工具": ["test-framework", "unittest", "jest", "pytest", "cypress", "selenium", "测试"],
    "浏览器": ["browser", "chrome", "firefox", "browser-extension", "playwright", "puppeteer", "浏览器"],
    "监控运维": ["monitoring-tool", "log-management", "metrics", "observability", "prometheus", "grafana", "监控"],
    "教育教程": ["tutorial", "education", "learning-path", "course", "awesome-list", "handbook", "教程", "学习"],
    "文档工具": ["documentation", "docs-generator", "markdown", "wiki", "mdx", "notion", "文档"],
    "构建工具": ["build-tool", "webpack", "vite", "esbuild", "bundler", "rollup", "构建"],
    "容器化": ["containerd", "podman", "docker-compose", "dockerfile", "registry", "容器"],
    # ── 电气工程 / 嵌入式 / 硬件 ─────────────────────
    "嵌入式开发": ["embedded", "esp32", "esp8266", "stm32", "arduino", "microcontroller",
                  "firmware", "rtos", "freertos", "zephyr", "nuttx", "bare-metal",
                  "嵌入式", "单片机", "固件", "电气工程", "电气", "自动化"],
    "电子信息": ["electronic", "fpga", "verilog", "vhdl", "dsp", "signal-processing",
                "sdr", "rfid", "nfc", "antenna", "adc", "dac", "soc", "semiconductor",
                "microcontroller", "chip-design", "silicon",
                "芯片", "集成电路", "微电子",
                "电子信息", "电子工程"],
    "物联网": ["iot", "mqtt", "smart-home", "home-automation", "home-assistant",
              "zigbee", "lora", "lorawan", "nrf", "homekit", "matter", "thread",
              "物联网", "智能家居"],
    "硬件设计": ["pcb", "kicad", "easyeda", "altium", "fpga", "verilog", "vhdl",
                "circuit", "electronics", "eda", "gerber", "schematic",
                "hardware-design", "pcba",
                "硬件设计", "硬件", "电路", "印制电路板"],
    "信号处理": ["dsp", "signal-processing", "fft", "signal-filter", "audio-processing",
                "wavelet", "convolution", "digital-signal-processing",
                "信号处理", "数字信号处理"],
    "电力系统": ["power-system", "scada", "plc", "modbus", "power-electronics",
                "battery", "charger", "solar", "inverter", "power-grid", "battery-management",
                "电力系统", "电力", "电网", "电力电子", "储能"],
    "射频通信": ["sdr", "rfid", "nfc", "radio-frequency", "wireless-communication", "lte", "5g",
                "bluetooth", "antenna", "rtl-sdr", "rf-module",
                "射频", "通信", "无线"],
    # ── 汽车工程 / 自动驾驶 ───────────────────────────
    "自动驾驶": ["autonomous-driving", "self-driving", "can-bus", "apollo",
                "autoware", "carla", "openpilot", "lidar", "adas", "automotive",
                "自动驾驶", "汽车", "车载", "无人驾驶"],
    # ── 机械工程 / 智能制造 ───────────────────────────
    "机械制造": ["cad-software", "freecad", "openscad", "3d-printing", "cnc",
                "grbl", "cam-software", "prusa", "cura", "slicer",
                "additive-manufacturing",
                "机械", "制造", "3d打印", "数控", "机械工程"],
    # ── 生物医学工程 ─────────────────────────────────
    "生物医学": ["medical", "bioinformatics", "dicom", "eeg", "emg", "openbci",
                "mri", "ct-scan", "medical-imaging", "bci", "brain-computer",
                "genome", "protein", "biomedical", "healthcare",
                "医学", "生物", "脑机接口", "医疗", "生物医学"],
    # ── 土木工程 / 建筑 ───────────────────────────────
    "土木建筑": ["gis", "bim", "qgis", "ifcopenshell", "opensees", "calculix",
                "structural", "leaflet", "openstreetmap", "civil-engineering",
                "construction", "architecture",
                "土木", "建筑", "土木工程", "地理信息"],
    # ── 机器人 / 机械臂（独立于具身智能的工程化方向）──
    "机器人控制": ["robotics", "ros", "ros2", "moveit", "gazebo", "rviz",
                  "robotic-arm", "manipulator", "ur5", "franka", "kinematics",
                  "机器人", "机械臂", "运动学"],
}


def _rule_parse(query: str) -> dict | None:
    """规则匹配：将自然语言转为关键词"""
    q = query.lower()
    for topic, keywords in _COMMON_TOPICS.items():
        if topic.lower() in q:
            return {"keywords": keywords, "topic": topic, "source": "rule"}
        for kw in keywords:
            kw_lower = kw.lower()
            # 短关键词（≤3字符且纯字母）用词边界匹配，避免 "go" 匹配 "google"
            if len(kw_lower) <= 3 and kw_lower.isalpha():
                if re.search(r'\b' + re.escape(kw_lower) + r'\b', q):
                    return {"keywords": keywords, "topic": topic, "source": "rule"}
            else:
                if kw_lower in q:
                    return {"keywords": keywords, "topic": topic, "source": "rule"}
    return None


# ── 第二层：LLM 解析 ────────────────────────────────

def _llm_parse(query: str, api_key: str = "", provider: str = "") -> dict | None:
    """用 LLM 解析自然语言 → 结构化查询条件（使用传入的 key）"""
    if not _has_llm(api_key):
        return None

    prompt = f"""你是一个技术话题解析器。将用户输入转换为 JSON 查询条件。

用户输入："{query}"

请返回严格 JSON 格式（不要 markdown 代码块）：
{{
    "topic": "话题名称（中文，5字以内）",
    "keywords": ["关键词1", "关键词2", ...],
    "topics_filter": ["github_topic1", "github_topic2"],
    "language": "python" 或 null,
    "min_stars": 50,
    "exclude": ["排除关键词"]
}}

规则：
1. keywords 用 GitHub 项目的 description/name/topics 里常见的英文词
2. topics_filter 用 GitHub 真实 topic（如 trading, game-engine）
3. 不确定的字段用 null
4. min_stars 默认 50"""

    content = _call_llm(
        prompt=prompt,
        system="你是一个 JSON 解析器，只输出合法 JSON。",
        api_key=api_key,
        provider=provider,
        max_tokens=500,
        temperature=0.1,
    )
    if not content:
        return None

    try:
        # JSON 修复：去掉可能的 markdown 代码块
        content = re.sub(r"^```json\s*", "", content.strip())
        content = re.sub(r"\s*```$", "", content.strip())
        result = json.loads(content)
        result["source"] = "llm"
        return result
    except Exception as e:
        logger.warning(f"LLM parse JSON decode failed: {e}")
        return None


# ── 第三层：降级处理 ────────────────────────────────

# 中文技术术语 → 英文关键词映射（兜底解析时使用）
_CN_EN_MAP = {
    # AI / 机器人
    "具身智能": ["embodied", "embodied-ai", "robotics", "robot"],
    "机器人": ["robotics", "robot", "ros"],
    "机器学习": ["machine-learning", "ml", "scikit-learn"],
    "深度学习": ["deep-learning", "pytorch", "tensorflow", "neural-network"],
    "计算机视觉": ["computer-vision", "cv", "opencv", "image-processing"],
    "自然语言处理": ["nlp", "natural-language-processing", "transformer"],
    "语音识别": ["speech-recognition", "asr", "whisper"],
    "自动驾驶": ["autonomous-driving", "self-driving", "autonomous-vehicle"],
    "推荐系统": ["recommendation-system", "recommender", "collaborative-filtering"],
    "知识图谱": ["knowledge-graph", "graph-database", "neo4j"],
    "数据可视化": ["data-visualization", "dashboard", "chart", "d3"],
    "增强现实": ["ar", "augmented-reality", "arkit"],
    "虚拟现实": ["vr", "virtual-reality", "unity3d"],
    "游戏引擎": ["game-engine", "unity", "unreal", "godot"],
    # 金融
    "量化交易": ["trading", "quant", "backtest", "strategy"],
    "区块链": ["blockchain", "web3", "ethereum", "solidity"],
    "低代码": ["low-code", "no-code", "visual-programming"],
    # 电气 / 能源 / 工控
    "电气": ["electrical-engineering", "power-systems", "power-grid", "power-flow"],
    "电力": ["power-systems", "power-grid", "power-engineering", "electrical-engineering"],
    "新能源": ["renewable-energy", "solar", "wind-energy", "energy-storage"],
    "能源": ["energy", "power", "energy-management", "battery"],
    "工业控制": ["plc", "scada", "industrial-automation", "modbus"],
    "嵌入式": ["embedded", "arduino", "stm32", "esp32", "microcontroller"],
    "物联网": ["iot", "internet-of-things", "embedded", "sensor"],
    # 其他
    "边缘计算": ["edge-computing", "edge", "iot"],
    "量子计算": ["quantum", "quantum-computing", "qiskit"],
    "微服务": ["microservice", "microservices", "service-mesh"],
    "容器": ["container", "docker", "kubernetes"],
    "云原生": ["cloud-native", "kubernetes", "serverless"],
    "编译器": ["compiler", "llvm", "parser"],
    "操作系统": ["operating-system", "os", "kernel"],
    "分布式": ["distributed", "distributed-system", "consensus"],
    "密码学": ["cryptography", "crypto", "encryption"],
    "爬虫": ["crawler", "scraper", "spider", "scraping"],
    "搜索引擎": ["search-engine", "elasticsearch", "search"],
    "消息队列": ["message-queue", "kafka", "rabbitmq", "mqtt"],
    "缓存": ["cache", "redis", "memcached"],
    "负载均衡": ["load-balancer", "load-balancing", "nginx"],
    "持续集成": ["ci-cd", "continuous-integration", "jenkins"],
    "代码审查": ["code-review", "lint", "static-analysis"],
    "性能监控": ["monitoring", "observability", "apm", "prometheus"],
    "日志分析": ["logging", "log-analysis", "elk", "log"],
    # 更多常见中文技术词
    "前端": ["frontend", "react", "vue", "javascript", "typescript"],
    "后端": ["backend", "api", "server", "django", "fastapi"],
    "算法": ["algorithm", "data-structure", "leetcode"],
    "可视化": ["visualization", "chart", "dashboard", "plot"],
    "架构": ["architecture", "design-pattern", "software-architecture"],
    "编码": ["encoding", "codec", "encoder", "decoder"],
    "网络": ["network", "http", "tcp", "socket", "networking"],
    "存储": ["storage", "filesystem", "database", "object-storage"],
    "仿真": ["simulation", "simulator", "physics", "emulator"],
    "建模": ["modeling", "cad", "3d-model", "bim"],
}


def _fallback_parse(query: str, api_key: str = "", provider: str = "") -> dict:
    """兜底方案：提取英文词 + 中文→英文翻译 + 中文关键词映射

    翻译优先级：本地映射表 > LLM 翻译（用户 key）> MyMemory 免费 API > 原文
    """
    from src.processor.translator import translate_to_english, extract_keywords_from_translation

    words = re.findall(r"[a-zA-Z][a-zA-Z0-9_\-.]{2,}", query)
    stop = {"the", "and", "for", "want", "see", "show", "with", "related"}
    keywords = [w.lower() for w in words if w.lower() not in stop]

    # 提取中文词
    cn_words = re.findall(r"[\u4e00-\u9fff]{2,6}", query)
    cn_stop = {"我想看", "相关的", "有没有", "的项目", "一些", "那些", "就是", "有什么", "帮我", "我要"}
    cn_words = [c for c in cn_words if c not in cn_stop]

    # 中文 → 英文关键词映射（让 _match_repo 和 GitHub Search 都能用英文匹配）
    for cn in cn_words:
        if cn in _CN_EN_MAP:
            keywords.extend(_CN_EN_MAP[cn])

    # 翻译整个查询（处理映射表未覆盖的中文词）
    # 只对包含中文的查询翻译，避免无谓的网络请求
    if cn_words:
        translation = translate_to_english(query, api_key=api_key, provider=provider)
        if translation and translation != query:
            # 从翻译结果提取英文关键词
            translated_kws = extract_keywords_from_translation(translation, max_n=5)
            keywords.extend(translated_kws)
            logger.info(f"Fallback translated '{query}' -> '{translation}' -> keywords: {translated_kws}")

    # 去重
    seen = set()
    keywords = [k for k in keywords if not (k in seen or seen.add(k))]

    if not keywords:
        keywords = ["github"]

    return {
        "topic": query[:20],
        "keywords": keywords,
        "topics_filter": [],
        "language": None,
        "min_stars": 30,
        "exclude": [],
        "source": "fallback",
    }


def parse_query(query: str, api_key: str = "", provider: str = "") -> dict:
    """
    解析用户查询，返回结构化条件

    4 层防御：
    1. 规则匹配（不消耗 API）
    2. LLM 解析（json_object 模式，用 api_key）
    3. 无效 Topic 降级 → 关键词搜索
    4. 纯关键词兜底

    Args:
        query: 用户输入的话题
        api_key: 用户自己的 LLM API Key（可选，不传则只用规则匹配）
        provider: LLM 厂商（deepseek/openai/anthropic/qwen/zhipu/moonshot，可选，自动识别）
    """
    # 第 1 层：规则
    result = _rule_parse(query)
    if result:
        logger.info(f"Query parsed by rule: {result['topic']}")
        return result

    # 第 2 层：LLM（用用户自己的 key）
    result = _llm_parse(query, api_key, provider)
    if result:
        logger.info(f"Query parsed by LLM: {result.get('topic', query[:15])}")
        return result

    # 第 3-4 层：兜底（含翻译）
    logger.info("Falling back to keyword extraction with translation")
    return _fallback_parse(query, api_key=api_key, provider=provider)


# ── 板块定义生成 ────────────────────────────────────

def _meta_sections(topic: str) -> dict:
    """元模板兜底板块（不消耗 API）"""
    return {
        "sections": [
            {"icon": "🔥", "title": f"{topic} 热门", "desc": f"{topic}方向热度最高项目",
             "sort_by": "hot_score", "limit": 10},
            {"icon": "🌟", "title": f"{topic} 新星", "desc": f"近期新建的{topic}项目",
             "sort_by": "stars", "filter_new": True, "limit": 10},
            {"icon": "🏆", "title": f"{topic} 精品", "desc": f"健康度最高的{topic}项目",
             "sort_by": "quality_score", "limit": 10},
            {"icon": "📊", "title": "数据看板", "desc": "语言分布与统计",
             "sort_by": "dashboard", "limit": 0},
        ]
    }


def generate_sections(topic: str, keywords: list[str], api_key: str = "",
                      provider: str = "") -> dict:
    """
    LLM 动态生成自定义板块定义

    Args:
        topic: 话题名
        keywords: 关键词列表
        api_key: 用户自己的 LLM API Key（可选，不传则用元模板）
        provider: LLM 厂商（可选）
    """
    if not _has_llm(api_key):
        return _meta_sections(topic)

    prompt = f"""为用户话题"{topic}"（关键词：{', '.join(keywords[:8])}）设计 4 个日报板块。

返回严格 JSON：
{{
    "sections": [
        {{
            "icon": "emoji 一个字符",
            "title": "板块名（中文，5字内）",
            "desc": "一句话说明",
            "sort_by": "hot_score|stars|quality_score|dashboard",
            "filter_new": false,
            "limit": 10
        }}
    ]
}}

要求：
- 板块要有针对性（如果话题是量化交易，板块应有回测、策略相关等）
- icon 用单个 emoji
- sort_by 从给定选项中选择
- filter_new 为 true 表示只展示近期新建项目
- 必须返回 4 个板块
- 最后一个板块必须是 dashboard 类型（统计数据）"""

    content = _call_llm(
        prompt=prompt,
        system="你是 JSON 生成器，只输出合法 JSON。",
        api_key=api_key,
        provider=provider,
        max_tokens=800,
        temperature=0.2,
    )
    if not content:
        return _meta_sections(topic)

    try:
        content = re.sub(r"^```json\s*", "", content.strip())
        content = re.sub(r"\s*```$", "", content.strip())
        return json.loads(content)
    except Exception as e:
        logger.warning(f"LLM section generation JSON decode failed: {e}")
        return _meta_sections(topic)

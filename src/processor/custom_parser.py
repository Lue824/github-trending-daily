"""
自定义话题解析器

策略：规则优先 → LLM 兜底 → 降级防护（4 层防御体系）

支持传入用户自己的 api_key（自定义模块个人化，不消耗项目方额度）
兼容多家厂商：DeepSeek / OpenAI / Anthropic / 通义千问 / 智谱 / Moonshot / 自定义
"""
import json
import logging
import os
import re

import requests

logger = logging.getLogger(__name__)

# 项目方默认 key（仅基础模块用）
DEEPSEEK_KEY = os.getenv("DEEPSEEK_API_KEY", "")

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
    "AI Agent": ["agent", "mcp", "langchain", "rag", "function-call", "skill", "orchestrat"],
    "大模型": ["llm", "gpt", "llama", "chatgpt", "openai", "deepseek", "claude", "anthropic", "mistral"],
    "文生图": ["stable-diffusion", "image-generation", "dalle", "midjourney", "txt2img", "comfyui"],
    "语音AI": ["tts", "stt", "speech", "whisper", "voice", "audio"],
    # 金融
    "量化交易": ["trading", "quant", "finance", "stock", "crypto", "backtest", "strategy"],
    "金融": ["finance", "financial", "fintech", "banking", "payment", "stripe", "paypal"],
    # 开发工具
    "游戏开发": ["game", "engine", "unity", "unreal", "godot", "rendering", "opengl"],
    "前端框架": ["react", "vue", "angular", "svelte", "nextjs", "frontend", "tailwind"],
    "后端框架": ["django", "flask", "fastapi", "express", "spring", "laravel", "backend"],
    "数据库": ["database", "sql", "nosql", "postgres", "mysql", "redis", "mongodb"],
    "DevOps": ["docker", "kubernetes", "k8s", "ci-cd", "terraform", "ansible", "jenkins"],
    "CLI工具": ["cli", "terminal", "tui", "command-line", "bash", "zsh"],
    # 安全
    "安全工具": ["security", "pentest", "osint", "exploit", "cve", "vulnerability", "hacking"],
    # 热门语言生态
    "Rust生态": ["rust", "cargo", "wasm", "tokio", "actix"],
    "Python生态": ["python", "pypi", "django", "flask", "fastapi", "jupyter"],
    "Go生态": ["go", "golang", "gin", "echo", "fiber"],
    "TypeScript生态": ["typescript", "ts", "bun", "deno"],
    # 其他热门
    "区块链": ["blockchain", "web3", "ethereum", "solidity", "defi", "nft", "bitcoin"],
    "机器人": ["robotics", "robot", "ros", "embodied", "simulation"],
    "视频处理": ["video", "ffmpeg", "streaming", "encode", "media", "youtube"],
    "桌面应用": ["desktop", "electron", "tauri", "gui", "gtk", "qt", "wpf"],
    "移动开发": ["mobile", "android", "ios", "flutter", "react-native", "swift", "kotlin"],
    "云计算": ["cloud", "aws", "azure", "gcp", "serverless", "lambda", "s3"],
    "API开发": ["api", "rest", "graphql", "grpc", "swagger", "openapi"],
    "数据科学": ["data-science", "pandas", "numpy", "matplotlib", "jupyter", "analytics"],
    "设计工具": ["design", "figma", "ui", "ux", "css", "sketch", "prototype"],
    "测试工具": ["testing", "unittest", "jest", "pytest", "cypress", "selenium"],
    "浏览器": ["browser", "chrome", "firefox", "extension", "playwright", "puppeteer"],
    "监控运维": ["monitoring", "logging", "metrics", "observability", "prometheus", "grafana"],
    "教育教程": ["tutorial", "education", "learn", "course", "awesome", "handbook"],
    "文档工具": ["documentation", "docs", "markdown", "wiki", "mdx", "notion"],
    "构建工具": ["build", "webpack", "vite", "esbuild", "bundler", "rollup"],
    "容器化": ["container", "podman", "docker-compose", "dockerfile", "registry"],
}


def _rule_parse(query: str) -> dict | None:
    """规则匹配：将自然语言转为关键词"""
    q = query.lower()
    for topic, keywords in _COMMON_TOPICS.items():
        if any(kw in q for kw in keywords) or topic.lower() in q:
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

def _fallback_parse(query: str) -> dict:
    """兜底方案：提取 query 中的英文单词 + 中文关键词"""
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9_\-.]{2,}", query)
    stop = {"the", "and", "for", "want", "see", "show", "with", "related"}
    keywords = [w.lower() for w in words if w.lower() not in stop]

    # 如果没有英文词，尝试拆中文（2-4字词）
    if not keywords:
        cn = re.findall(r"[\u4e00-\u9fff]{2,4}", query)
        # 过滤无意义词
        cn_stop = {"我想看", "相关的", "有没有", "的项目", "一些", "那些", "就是", "有什么", "帮我", "我要"}
        cn = [c for c in cn if c not in cn_stop]
        keywords = cn if cn else ["github"]  # 最后兜底

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

    # 第 3-4 层：兜底
    logger.info("Falling back to keyword extraction")
    return _fallback_parse(query)


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

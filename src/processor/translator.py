"""
中文 → 英文翻译模块
用于将用户输入的中文话题翻译成英文关键词，再传给 GitHub Search API

策略：
1. 优先用 LLM 翻译（如果用户填了 API key）
2. 其次用 MyMemory 免费翻译 API（无需 key，每天 5000 词）
3. 最后用本地映射表兜底
"""
import logging
import re
import urllib.parse
import requests

logger = logging.getLogger(__name__)

# 本地映射表兜底（常见技术术语）
_LOCAL_MAP = {
    "电气": "electrical engineering",
    "电力": "power systems",
    "新能源": "renewable energy",
    "能源": "energy",
    "工业控制": "industrial automation",
    "嵌入式": "embedded systems",
    "物联网": "internet of things",
    "具身智能": "embodied AI",
    "机器人": "robotics",
    "机器学习": "machine learning",
    "深度学习": "deep learning",
    "计算机视觉": "computer vision",
    "自然语言处理": "natural language processing",
    "语音识别": "speech recognition",
    "自动驾驶": "autonomous driving",
    "推荐系统": "recommendation system",
    "知识图谱": "knowledge graph",
    "数据可视化": "data visualization",
    "增强现实": "augmented reality",
    "虚拟现实": "virtual reality",
    "游戏引擎": "game engine",
    "量化交易": "quantitative trading",
    "区块链": "blockchain",
    "低代码": "low code",
    "边缘计算": "edge computing",
    "量子计算": "quantum computing",
    "微服务": "microservices",
    "容器": "container",
    "云原生": "cloud native",
    "编译器": "compiler",
    "操作系统": "operating system",
    "分布式": "distributed systems",
    "密码学": "cryptography",
    "爬虫": "web scraper",
    "搜索引擎": "search engine",
    "消息队列": "message queue",
    "缓存": "cache",
    "负载均衡": "load balancer",
    "持续集成": "continuous integration",
    "代码审查": "code review",
    "性能监控": "performance monitoring",
    "日志分析": "log analysis",
    "前端": "frontend",
    "后端": "backend",
    "算法": "algorithm",
    "可视化": "visualization",
    "架构": "architecture",
    "编码": "encoding",
    "网络": "network",
    "存储": "storage",
    "仿真": "simulation",
    "建模": "modeling",
}


def _is_chinese(text: str) -> bool:
    """判断文本是否包含中文"""
    return any('一' <= c <= '鿿' for c in text)


def _translate_by_llm(text: str, api_key: str, provider: str) -> str | None:
    """用用户的 LLM key 翻译（精准但需要 key）"""
    if not api_key:
        return None

    p = (provider or "").lower().strip()
    system = "You are a translator. Translate the user's Chinese text to English. Output ONLY the English translation, nothing else. If the input is already English, return it as-is."

    try:
        if p in ("", "deepseek"):
            url = "https://api.deepseek.com/v1/chat/completions"
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            body = {"model": "deepseek-chat", "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": text}],
                "max_tokens": 100, "temperature": 0.1}
        elif p in ("openai", "gpt"):
            url = "https://api.openai.com/v1/chat/completions"
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            body = {"model": "gpt-4o-mini", "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": text}],
                "max_tokens": 100, "temperature": 0.1}
        elif p in ("anthropic", "claude"):
            url = "https://api.anthropic.com/v1/messages"
            headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
            body = {"model": "claude-sonnet-4-6", "max_tokens": 100,
                    "system": system, "messages": [{"role": "user", "content": text}]}
        elif p in ("qwen", "tongyi"):
            url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            body = {"model": "qwen-plus", "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": text}],
                "max_tokens": 100, "temperature": 0.1}
        elif p in ("zhipu", "glm"):
            url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            body = {"model": "glm-4-flash", "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": text}],
                "max_tokens": 100, "temperature": 0.1}
        elif p in ("moonshot", "kimi"):
            url = "https://api.moonshot.cn/v1/chat/completions"
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            body = {"model": "moonshot-v1-8k", "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": text}],
                "max_tokens": 100, "temperature": 0.1}
        else:
            return None

        resp = requests.post(url, headers=headers, json=body, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if "choices" in data:
            return data["choices"][0]["message"]["content"].strip()
        if "content" in data:
            return data["content"][0]["text"].strip()
    except Exception as e:
        logger.warning(f"LLM translation failed: {e}")
    return None


def _translate_by_mymemory(text: str) -> str | None:
    """用 MyMemory 免费 API 翻译（无需 key，每天 5000 词）"""
    try:
        url = "https://api.mymemory.translated.net/get"
        params = {
            "q": text,
            "langpair": "zh|en",
        }
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get("responseStatus") == 200 or data.get("responseData"):
            translated = data.get("responseData", {}).get("translatedText", "")
            if translated and not translated.startswith("PLEASE SELECT"):
                return translated.strip()
    except Exception as e:
        logger.warning(f"MyMemory translation failed: {e}")
    return None


def translate_to_english(text: str, api_key: str = "", provider: str = "") -> str:
    """将中文翻译为英文

    优先级：LLM > MyMemory API > 本地映射表 > 原文返回
    """
    if not text or not text.strip():
        return text

    # 已经是英文，直接返回
    if not _is_chinese(text):
        return text

    text = text.strip()

    # 1. 本地映射表（最快，无网络开销）
    if text in _LOCAL_MAP:
        return _LOCAL_MAP[text]

    # 2. LLM 翻译（最精准，需要 key）
    if api_key:
        result = _translate_by_llm(text, api_key, provider)
        if result and _is_chinese(result) is False:
            logger.info(f"LLM translated '{text}' -> '{result}'")
            return result

    # 3. MyMemory 免费 API（无需 key）
    result = _translate_by_mymemory(text)
    if result and not _is_chinese(result):
        logger.info(f"MyMemory translated '{text}' -> '{result}'")
        return result

    # 4. 兜底：返回原文
    logger.info(f"Translation failed for '{text}', using original")
    return text


def extract_keywords_from_translation(translation: str, max_n: int = 5) -> list[str]:
    """从翻译结果中提取关键词（用于 GitHub Search API）

    例如 "electrical engineering" -> ["electrical-engineering", "electrical", "engineering"]
    """
    if not translation:
        return []

    # 转小写 + 替换标点
    text = translation.lower()
    text = re.sub(r"[^\w\s-]", " ", text)

    # 分词
    words = [w.strip("-") for w in text.split() if w.strip("-") and len(w.strip("-")) >= 2]

    # 停用词
    stop = {"the", "and", "for", "of", "to", "in", "a", "an", "is", "are", "with", "related", "system", "systems"}
    words = [w for w in words if w not in stop]

    # 去重 + 保留顺序
    seen = set()
    keywords = []
    # 先加完整短语（用连字符连接）
    if len(words) >= 2:
        phrase = "-".join(words[:3])
        keywords.append(phrase)
        seen.add(phrase)
    # 再加单个词
    for w in words:
        if w not in seen:
            keywords.append(w)
            seen.add(w)

    return keywords[:max_n]

"""
LLM 驱动的中文深度分析模块
支持 DeepSeek / Anthropic / OpenAI 兼容接口
"""
import logging
import os

import requests

logger = logging.getLogger(__name__)

# ── DeepSeek 配置 ──────────────────────────────────────
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

# ── Anthropic 配置（备选） ─────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")


def _call_llm(prompt: str, max_tokens: int = 2000) -> str | None:
    """
    调用 LLM API，自动选择可用的提供商
    优先级：DeepSeek > Anthropic
    """
    # ── 方式 1：DeepSeek (OpenAI 兼容格式) ──────────────
    if DEEPSEEK_API_KEY:
        return _call_deepseek(prompt, max_tokens)

    # ── 方式 2：Anthropic ──────────────────────────────
    if ANTHROPIC_API_KEY:
        return _call_anthropic(prompt, max_tokens)

    logger.info("No LLM API key configured (set DEEPSEEK_API_KEY or ANTHROPIC_API_KEY)")
    return None


def _call_deepseek(prompt: str, max_tokens: int = 2000) -> str | None:
    """调用 DeepSeek API（OpenAI 兼容格式）"""
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": "你是一个专业的技术分析助手，擅长用简洁的中文总结 GitHub 开源项目。"},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.3,
    }

    try:
        resp = requests.post(
            f"{DEEPSEEK_BASE_URL}/v1/chat/completions",
            headers=headers,
            json=body,
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.warning(f"DeepSeek API call failed: {e}")
        return None


def _call_anthropic(prompt: str, max_tokens: int = 2000) -> str | None:
    """调用 Anthropic API"""
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=body,
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["content"][0]["text"]
    except Exception as e:
        logger.warning(f"Anthropic API call failed: {e}")
        return None


def summarize_project(repo: dict, readme_text: str) -> str | None:
    """用 LLM 生成一个项目的中文深度介绍"""
    if not readme_text or len(readme_text) < 50:
        return None

    prompt = f"""请根据以下 GitHub 项目的 README 内容，用中文写一段项目介绍。

格式要求（严格按以下格式，每部分不超过 3 句话）：

**📌 它是什么**：[一句话概括项目定位和核心功能]

**💡 解决什么问题**：[说明这个项目存在的意义，解决的真实痛点]

**🎯 谁在用**：[典型用户群体和使用场景]

项目信息：
- 名称：{repo['full_name']}
- 语言：{repo.get('language', 'Unknown')}
- Star 数：{repo.get('stars', 0):,}
- 今日新增 Star：{repo.get('stars_in_period', 0) or 0:,}
- 描述：{repo.get('description', '')}
- 标签：{', '.join(repo.get('topics', [])[:10])}
- 领域：{', '.join(repo.get('tags', []))}

README 内容：
{readme_text[:3000]}"""

    return _call_llm(prompt, max_tokens=800)


def analyze_trends(repos: list[dict], readme_cache: dict[str, str]) -> str | None:
    """用 LLM 对当日整体趋势进行分析"""
    top_summaries = []
    for r in repos[:15]:
        summary = (
            f"- {r['full_name']} ({r.get('language', '?')}, ⭐{r.get('stars', 0):,}, "
            f"今日+{r.get('stars_in_period', 0) or 0:,}): {r.get('description', '')[:150]}"
        )
        if r.get("tags"):
            summary += f" [领域: {', '.join(r['tags'])}]"
        top_summaries.append(summary)

    from collections import Counter
    lang_counter = Counter(r.get("language", "Unknown") for r in repos)
    tag_counter = Counter()
    for r in repos:
        for t in r.get("tags", []):
            tag_counter[t] += 1

    prompt = f"""请分析以下 GitHub 今日热门项目列表，用中文总结 3-5 条核心趋势。

今日数据：
- 总收录项目：{len(repos)} 个
- AI/ML相关：{sum(1 for r in repos if r.get('is_focus'))} 个
- 语言分布 TOP5：{dict(lang_counter.most_common(5))}
- 领域分布：{dict(tag_counter.most_common(5))}

TOP 项目列表：
{chr(10).join(top_summaries)}

请输出 3-5 条趋势，每条格式：
**趋势 N：标题** — 一句话说明，附上代表项目。

最后加一句总结。
使用中文。"""

    return _call_llm(prompt, max_tokens=1000)

"""
LLM 驱动的中文深度分析模块
支持 DeepSeek / Anthropic / OpenAI 兼容接口

Prompt 输出格式：
  🚀 一句话定位 → 💡 核心价值 → 🎯 多维解读 → 📊 数据洞察
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
    if DEEPSEEK_API_KEY and DEEPSEEK_API_KEY not in ("", "sk-xxxxxxxxxxxx"):
        return _call_deepseek(prompt, max_tokens)

    if ANTHROPIC_API_KEY and ANTHROPIC_API_KEY not in ("", "sk-ant-xxxxxxxxxxxx"):
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
            {"role": "system", "content": "你是一位资深开源项目分析师，擅长结合数据做深度技术分析。输出格式严格遵循用户要求。"},
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
    """用 LLM 生成多维度全景项目介绍"""
    if not readme_text or len(readme_text) < 50:
        return None

    extra = repo.get("_extra", {}) or {}

    stars = repo.get("stars", 0)
    stars_today = repo.get("stars_in_period", 0) or 0
    forks = repo.get("forks", 0)
    burst = repo.get("burst_score", 0)
    quality = repo.get("quality_score", 0)
    potential = repo.get("potential_score", 0)
    ai_radar = repo.get("ai_radar_score", 0)
    is_trap = repo.get("is_trap", False)
    trap_signals = repo.get("trap_signals", 0)
    streak = repo.get("streak_days", 0)

    contributors = extra.get("contributors", 0)
    open_issues = extra.get("open_issues", 0)
    open_prs = extra.get("open_prs", 0)
    last_push = extra.get("last_push_days", 999)
    releases = extra.get("releases", 0)
    commits = extra.get("commits_12w", 0)
    created_days = extra.get("created_days", 0)

    # 生态标签
    eco_tags = []
    try:
        from src.processor.ai_scoring import get_eco_tags
        eco_tags = get_eco_tags(repo)
    except Exception:
        pass

    # 健康度简述
    health_parts = []
    if last_push <= 7:
        health_parts.append("🟢 活跃推送")
    elif last_push <= 90:
        health_parts.append("🟡 较活跃")
    elif last_push > 180:
        health_parts.append("⏸ 半年未更新")
    if contributors >= 20:
        health_parts.append(f"{contributors} 人贡献")
    elif contributors <= 1 and stars > 1000:
        health_parts.append("⚠️ 单人维护")
    if releases >= 10:
        health_parts.append(f"{releases} 个 Release")
    if commits >= 500:
        health_parts.append("高频提交")
    health_note = "，".join(health_parts) if health_parts else "健康度数据有限"

    # 陷阱提示
    trap_note = ""
    if is_trap and trap_signals >= 2:
        signals_detail = []
        if extra.get("open_issues", 0) > 10:
            signals_detail.append(f"{open_issues} 个开放 Issue")
        if last_push > 180:
            signals_detail.append(f"最后推送 {last_push} 天前")
        if releases == 0 and created_days > 180:
            signals_detail.append("无 Release")
        if contributors <= 1 and stars > 5000:
            signals_detail.append("单人维护")
        trap_note = f"⚠️ 已检测到 {trap_signals} 个陷阱信号：{'、'.join(signals_detail)}。"

    prompt = f"""你是一位资深开源项目分析师。请根据以下结构化数据和 README 内容，撰写一份多维度全景项目介绍。

---
**📦 基本信息**
名称：{repo['full_name']}
描述：{repo.get('description', '') or '无'}
语言：{repo.get('language', 'Unknown')}
⭐ Star：{stars:,} | 今日新增：{stars_today:,} | Fork：{forks:,}
连续在榜：{streak} 天

**🏥 健康度**
贡献者：{contributors} 人 | 开放 Issue：{open_issues} | 开放 PR：{open_prs}
最近推送：{last_push}天前 | Release：{releases} 个 | 近12周提交：{commits} 次
创建天数：{created_days}天
综合：{health_note}
{trap_note}

**📊 多维评分**
爆发分 {burst:.2f} | 质量分 {quality:.2f} | 潜力分 {potential:.2f} | AI雷达分 {ai_radar:.2f}
{chr(10) + '**🌐 生态**：' + '、'.join(eco_tags) if eco_tags else ''}
**🏷️ 领域**：{'、'.join(repo.get('tags', [])) if repo.get('tags') else '无'}
**🔖 Topics**：{'、'.join(repo.get('topics', [])[:10])}

**📖 README（前 3000 字符）**
{readme_text[:3000]}

---
**输出要求**（严格使用以下 Markdown 格式，每个板块 1-3 句话）：

🚀 **一句话定位**
用一句话说清产品形态、核心能力和目标用户。

💡 **核心价值**
这个项目解决了什么真实痛点？为什么值得关注？引用 Star 增速、生态位置等数据。

🎯 **多维解读**
- **技术亮点**：架构、性能、语言生态的突出优势
- **用户画像**：最适合哪类开发者 / 团队
- **场景落地**：2-3 个典型应用场景

📊 **数据洞察**
结合评分的趋势判断。例如"爆发分 {burst:.2f} + 质量分 {quality:.2f}，双高项目"、"{contributors} 人协作，社区活跃"、"{stars_today:,} 日增量，增速跻身头部"。如果有陷阱信号请客观提及。

使用中文，语气专业有温度。不要罗列原始数据，要给出分析结论。"""

    return _call_llm(prompt, max_tokens=1200)


def analyze_trends(repos: list[dict], readme_cache: dict[str, str]) -> str | None:
    """用 LLM 对当日整体趋势进行多维度分析"""
    from collections import Counter

    top_summaries = []
    for r in repos[:15]:
        line = (
            f"- {r['full_name']} ({r.get('language', '?')}, "
            f"⭐{r.get('stars', 0):,}, 今日+{r.get('stars_in_period', 0) or 0:,})"
        )
        score_bits = []
        b = r.get("burst_score", 0)
        if b > 0:
            score_bits.append(f"爆发{b:.2f}")
        q = r.get("quality_score", 0)
        if q >= 0.4:
            score_bits.append(f"质量{q:.2f}")
        if r.get("is_trap"):
            score_bits.append(f"⚠️陷阱")
        if score_bits:
            line += f" [{', '.join(score_bits)}]"
        if r.get("description"):
            line += f": {r.get('description', '')[:120]}"
        if r.get("tags"):
            line += f" [领域: {', '.join(r['tags'][:3])}]"
        top_summaries.append(line)

    lang_counter = Counter(r.get("language", "Unknown") for r in repos)
    tag_counter = Counter()
    burst_count = 0
    quality_count = 0
    trap_count = 0
    for r in repos:
        for t in r.get("tags", []):
            tag_counter[t] += 1
        if r.get("burst_score", 0) > 0:
            burst_count += 1
        if r.get("quality_score", 0) >= 0.4:
            quality_count += 1
        if r.get("is_trap"):
            trap_count += 1

    total = len(repos)
    focus_count = sum(1 for r in repos if r.get("is_focus"))

    prompt = f"""你是一位 GitHub 趋势分析师。请基于今日数据生成趋势洞察。

---
**📊 今日统计**
总收录：{total} 个 | AI/ML 相关：{focus_count} 个
正在爆发：{burst_count} 个 | 高质量：{quality_count} 个 | ⚠️ 陷阱：{trap_count} 个
语言 TOP5：{dict(lang_counter.most_common(5))}
领域 TOP5：{dict(tag_counter.most_common(5))}

**🔥 TOP 15 项目**
{chr(10).join(top_summaries)}

---
**输出要求**（严格使用以下格式）：

**趋势一：标题**（1 句话概括趋势 + 1-2 个代表项目佐证）
**趋势二：标题**
**趋势三：标题**
**趋势四：标题**（可选）
**趋势五：标题**（可选）

最后一段 **📌 今日总结**：1-2 句话概括今日整体态势（哪个赛道最热？有无异常信号？）。

使用中文。每个趋势给出具体项目作为例证，数据引用要准确。不要泛泛而谈。"""

    return _call_llm(prompt, max_tokens=1200)

"""
AI 垂类 6 板块评分系统

板块：
① 🧠 模型 & 权重 — 权重开源、参数量、HF 存在、支持框架
② 🔧 Agent & 工具链 — MCP/RAG/Function Calling、集成难度、文档
③ 📊 数据 & 评测 — 数据集规模、benchmark、更新频率
④ ⚡ 爆发信号 — 基础类爆发逻辑 + AI 过滤
⑤ ⚠️ 关注信号 — 权重不开源、长期未更新、许可证不明
⑥ 📈 AI 趋势数据 — 最热 topic、生态占比、周趋势（在 reporter 中处理）
"""
import math


_MODEL_KW = [
    "model", "models", "weight", "checkpoint", "pretrained", "fine-tun",
    "huggingface", "hf", "transformers", "pytorch", "tensorflow", "jax",
    "gguf", "onnx", "safetensors", "llama", "gpt", "bert", "t5", "diffusion",
    "vlm", "multimodal", "embedding", "tokenizer", "inference",
]
_AGENT_KW = [
    "agent", "mcp", "langchain", "rag", "retrieval", "function-call",
    "tool-use", "skill", "orchestrat", "workflow", "cli", "coding-agent",
    "claude-code", "codex", "cursor", "copilot", "autonomous",
]
_DATA_KW = [
    "dataset", "benchmark", "evaluation", "eval", "leaderboard",
    "paper", "arxiv", "research", "survey", "nlp", "cv", "computer-vision",
    "reinforcement", "rl", "robotics",
]
_WARNING_KW = [
    "api-only", "closed-source", "proprietary", "no-weight",
]

# 生态标签映射
_ECO_MAP = {
    "openai": "OpenAI", "gpt": "OpenAI", "chatgpt": "OpenAI", "codex": "OpenAI",
    "claude": "Anthropic", "anthropic": "Anthropic",
    "deepseek": "DeepSeek",
    "llama": "Meta", "meta": "Meta",
    "gemini": "Google", "google": "Google",
    "mistral": "Mistral", "mixtral": "Mistral",
    "qwen": "阿里通义",
    "glm": "智谱",
    "baichuan": "百川",
    "langchain": "LangChain",
    "pytorch": "PyTorch", "tensorflow": "TF",
    "mcp": "MCP 协议",
    "huggingface": "HuggingFace",
}


def _match_any(text: str, keywords: list[str]) -> bool:
    if not text:
        return False
    t = text.lower()
    return any(kw.lower() in t for kw in keywords)


def _build_text(repo: dict) -> str:
    return (
        f"{repo.get('name', '')} "
        f"{repo.get('description', '') or ''} "
        f"{' '.join(repo.get('topics', []))}"
    ).lower()


def score_model(repo: dict, extra: dict) -> float:
    """🧠 模型 & 权重得分"""
    text = _build_text(repo)
    if not _match_any(text, _MODEL_KW):
        return 0.0

    score = 0.0
    # 权重已开源（有 safetensors/gguf/onnx/pytorch_model 等）
    if _match_any(text, ["safetensors", "gguf", "onnx", "pytorch_model", ".bin"]):
        score += 0.3
    # HuggingFace 存在
    if _match_any(text, ["huggingface", "hf.co", "hf_"]):
        score += 0.2
    # 支持多种框架
    frameworks = sum(1 for fw in ["pytorch", "tensorflow", "jax", "onnx"]
                     if fw in text)
    score += min(0.2, frameworks * 0.07)
    # 参数量提及
    if _match_any(text, ["7b", "13b", "70b", "405b", "8b", "1b", "3b", "param"]):
        score += 0.1
    # Star 加成
    stars = repo.get("stars", 0)
    score += min(0.2, math.log(stars + 1, 1000) * 0.1)
    return min(1.0, score)


def score_agent(repo: dict, extra: dict) -> float:
    """🔧 Agent & 工具链得分"""
    text = _build_text(repo)
    if not _match_any(text, _AGENT_KW):
        return 0.0

    score = 0.0
    # 生态位置
    if _match_any(text, ["mcp", "model-context-protocol"]):
        score += 0.25
    if _match_any(text, ["langchain", "llamaindex"]):
        score += 0.2
    if _match_any(text, ["skill", "skills"]):
        score += 0.2
    if _match_any(text, ["claude-code", "codex", "cursor", "copilot"]):
        score += 0.15
    # 文档完整度（有 README 提及 tutorial/docs/example）
    if _match_any(text, ["tutorial", "documentation", "example", "quickstart"]):
        score += 0.15
    # 健康度
    quality = repo.get("quality_score", 0)
    score += quality * 0.15
    # Star 加成
    stars = repo.get("stars", 0)
    score += min(0.1, math.log(stars + 1, 1000) * 0.05)
    return min(1.0, score)


def score_data(repo: dict, extra: dict) -> float:
    """📊 数据 & 评测得分"""
    text = _build_text(repo)
    if not _match_any(text, _DATA_KW):
        return 0.0

    score = 0.0
    if _match_any(text, ["dataset", "datasets", "corpus"]):
        score += 0.3
    if _match_any(text, ["benchmark", "evaluation", "eval"]):
        score += 0.25
    if _match_any(text, ["paper", "arxiv", "research"]):
        score += 0.2
    # 更新频率
    if extra and extra.get("last_push_days", 999) <= 30:
        score += 0.15
    stars = repo.get("stars", 0)
    score += min(0.1, math.log(stars + 1, 100) * 0.05)
    return min(1.0, score)


def score_warning(repo: dict, extra: dict) -> float:
    """⚠️ 关注信号 — 返回风险分（越高越关注）"""
    text = _build_text(repo)
    risk = 0.0

    # 权重未开源
    if _match_any(text, _WARNING_KW):
        risk += 0.4
    elif _match_any(text, _MODEL_KW) and not _match_any(text,
            ["safetensors", "gguf", "onnx", "open-source", "mit", "apache"]):
        risk += 0.2

    # 长期未更新
    if extra:
        last_push = extra.get("last_push_days", 0)
        if last_push > 365:
            risk += 0.3
        elif last_push > 180:
            risk += 0.15

    # 许可证不明
    if not _match_any(text, ["mit", "apache", "gpl", "bsd", "mpl", "license"]):
        risk += 0.1

    # 单人维护 + 高星
    if extra and extra.get("contributors", 0) <= 1 and repo.get("stars", 0) > 1000:
        risk += 0.15

    return min(1.0, risk)


def get_eco_tags(repo: dict) -> list[str]:
    """提取项目生态标签"""
    text = _build_text(repo)
    tags = repo.get("tags", [])
    topics = [t.lower() for t in repo.get("topics", [])]
    seen = set()
    result = []
    for kw, label in _ECO_MAP.items():
        if kw in text or kw in " ".join(topics):
            if label not in seen:
                result.append(label)
                seen.add(label)
    return result[:3]


def compute_ai_scores(repos: list[dict], extra_cache: dict) -> list[dict]:
    """
    为焦点仓库计算 AI 垂类评分
    """
    focus = [r for r in repos if r.get("is_focus")]
    for r in focus:
        extra = extra_cache.get(r["full_name"], {})
        r["ai_model_score"] = score_model(r, extra)
        r["ai_agent_score"] = score_agent(r, extra)
        r["ai_data_score"] = score_data(r, extra)
        r["ai_warning_score"] = score_warning(r, extra)
        r["ai_eco_tags"] = get_eco_tags(r)
        # 爆发信号：复用 burst_score
        r["ai_burst"] = r.get("burst_score", 0) > 0
    return focus


def get_ai_section_repos(focus_repos: list[dict]) -> dict:
    """按板块分组"""
    return {
        "model": sorted([r for r in focus_repos if r.get("ai_model_score", 0) > 0.1],
                         key=lambda r: r["ai_model_score"], reverse=True)[:10],
        "agent": sorted([r for r in focus_repos if r.get("ai_agent_score", 0) > 0.1],
                         key=lambda r: r["ai_agent_score"], reverse=True)[:10],
        "data": sorted([r for r in focus_repos if r.get("ai_data_score", 0) > 0.1],
                        key=lambda r: r["ai_data_score"], reverse=True)[:10],
        "burst": sorted([r for r in focus_repos if r.get("ai_burst")],
                         key=lambda r: r.get("burst_score", 0), reverse=True)[:5],
        "warning": sorted([r for r in focus_repos if r.get("ai_warning_score", 0) > 0.2],
                           key=lambda r: r["ai_warning_score"], reverse=True)[:5],
    }

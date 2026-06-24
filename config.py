import os

# ── 手动加载 .env 文件（避免依赖 python-dotenv） ────────────
_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_ENV_PATH):
    with open(_ENV_PATH, "r", encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _, _val = _line.partition("=")
                _key = _key.strip()
                _val = _val.strip().strip('"').strip("'")
                if _key not in os.environ:  # 不覆盖系统环境变量
                    os.environ[_key] = _val

# ── GitHub API ──────────────────────────────────────────────
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")  # 可选，提高 API 限额

# ── Trending 爬取 ───────────────────────────────────────────
TRENDING_LANGUAGES = [
    "",          # 全部语言
    "python", "javascript", "typescript", "go", "rust",
    "java", "kotlin", "swift", "c++", "c", "c#",
    "ruby", "php", "vue", "css", "html",
]
TRENDING_SINCE = ["daily", "weekly"]  # 日榜 + 周榜

# ── 重点关注领域（用于标记和分类） ─────────────────────────
FOCUS_KEYWORDS = {
    "机器学习": [
        "machine-learning", "ml", "scikit-learn", "xgboost", "lightgbm",
        "catboost", "feature-engineering", "mlops", "automl", "ml-pipeline",
    ],
    "深度学习": [
        "deep-learning", "neural-network", "pytorch", "tensorflow",
        "keras", "jax", "paddlepaddle", "transformer", "cnn", "rnn",
        "lstm", "gan", "diffusion", "attention-mechanism",
    ],
    "大模型/AI": [
        "llm", "large-language-model", "gpt", "chatgpt", "langchain",
        "llama", "openai", "anthropic", "claude", "agent", "rag",
        "retrieval-augmented", "prompt-engineering", "fine-tuning",
        "instruction-tuning", "rlhf", "multi-modal", "vlm",
        "ai-", "-ai", "artificial-intelligence", "generative-ai",
    ],
    "具身智能": [
        "embodied", "embodied-ai", "robotics", "robot",
        "sim-to-real", "sim2real", "reinforcement-learning",
        "rl", "mujoco", "isaac", "ros", "manipulation",
        "locomotion", "grasping", "humanoid", "quadruped",
    ],
}

# ── 邮箱配置 ────────────────────────────────────────────────
EMAIL_CONFIG = {
    "smtp_host": "smtp.qq.com",
    "smtp_port": 465,
    "sender": os.getenv("QQ_EMAIL", ""),          # 你的 QQ 邮箱
    "password": os.getenv("QQ_EMAIL_AUTH_CODE", ""),  # QQ 邮箱授权码
    "receiver": os.getenv("RECEIVER_EMAIL", ""),
}

# ── 存储配置 ────────────────────────────────────────────────
# 支持通过环境变量配置数据目录（HF Spaces 用 /data，本地用 data）
DATA_DIR = os.getenv("DATA_DIR", "data")
RAW_DIR = os.path.join(DATA_DIR, "raw")
REPORTS_DIR = os.path.join(DATA_DIR, "reports")
DB_PATH = os.path.join(DATA_DIR, "trending.db")
DATA_RETENTION_DAYS = 30  # 保留最近 30 天数据

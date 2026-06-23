"""
主流程编排

流程：输入 → 拼写检查 → 正确则深度学习 → 存入数据库 → 返回结果
"""
import logging
import time

from src.spellcheck import spellcheck
from src.deep_learning import get_vector, quality_score, add_documents
from src.database import init_db, word_exists, save_word, get_word

logger = logging.getLogger(__name__)

# 初始化
init_db()

DOMAIN_KEYWORDS = [
    "neural", "network", "deep", "learning", "model", "algorithm",
    "data", "semantic", "vector", "embedding", "representation",
    "language", "processing", "nlp", "token", "sequence",
]


def process_word(word: str, source: str = "api") -> dict:
    """
    处理单个词汇的完整流程

    Returns:
        {word, spell_result, dl_result, db_saved, elapsed_ms, ...}
    """
    start = time.time()
    word = word.strip()

    # ── 步骤 a+b：格式验证 + 拼写检查 ──────────────────
    if not word or len(word) < 2:
        return {"word": word, "error": "词汇长度不足", "elapsed_ms": 0}

    spell = spellcheck(word)

    if not spell["is_correct"]:
        return {
            "word": word,
            "phase": "spellcheck",
            "spell": spell,
            "elapsed_ms": round((time.time() - start) * 1000),
        }

    # ── 步骤 c+d：深度学习处理 ──────────────────────────
    # 检查是否已存在
    existing = get_word(word)
    if existing:
        return {
            "word": word,
            "phase": "exists",
            "spell": spell,
            "existing": {
                "quality_score": existing["quality_score"],
                "frequency": existing["frequency"],
                "created_at": existing["created_at"],
            },
            "elapsed_ms": round((time.time() - start) * 1000),
        }

    vector = get_vector(word)
    quality = quality_score(word, DOMAIN_KEYWORDS)

    # ── 步骤 e：存入数据库 ────────────────────────────
    try:
        save_word(word, vector, quality, source=source, verified=True)
        db_saved = True
    except Exception as e:
        return {"word": word, "error": f"数据库写入失败: {e}", "elapsed_ms": round((time.time() - start) * 1000)}

    return {
        "word": word,
        "phase": "completed",
        "spell": spell,
        "quality": quality,
        "vector_dim": len(vector),
        "db_saved": db_saved,
        "elapsed_ms": round((time.time() - start) * 1000),
    }


def process_batch(words: list[str], source: str = "batch") -> list[dict]:
    """批量处理词汇"""
    return [process_word(w, source) for w in words]


def init_with_seed_words():
    """用种子词汇初始化系统"""
    seed = [
        "algorithm", "neural", "network", "deep", "learning",
        "embedding", "semantic", "token", "transformer", "attention",
        "gradient", "optimizer", "backpropagation", "convolution",
        "recurrent", "classification", "regression", "clustering",
        "vector", "matrix", "tensor", "pipeline",
    ]
    add_documents(seed)
    for w in seed:
        if not word_exists(w):
            vector = get_vector(w)
            quality = quality_score(w, DOMAIN_KEYWORDS)
            save_word(w, vector, quality, source="seed", verified=True)
    logger.info(f"Seeded {len(seed)} words")

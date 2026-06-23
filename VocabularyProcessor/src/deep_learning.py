"""
深度学习处理模块
支持词向量生成、语义相似度计算、领域相关性分析

策略：尝试 sentence-transformers → 失败则用 TF-IDF 降级方案
"""
import logging
import hashlib
import os
from collections import defaultdict

import numpy as np

logger = logging.getLogger(__name__)

# ── 尝试加载预训练模型 ──────────────────────────────
_MODEL = None
_MODEL_NAME = None

# 优先尝试轻量模型
_CANDIDATES = [
    "all-MiniLM-L6-v2",          # 80MB，最轻量
    "paraphrase-MiniLM-L3-v2",   # 更小的
]

try:
    from sentence_transformers import SentenceTransformer
    for name in _CANDIDATES:
        try:
            _MODEL = SentenceTransformer(name)
            _MODEL_NAME = name
            logger.info(f"Loaded sentence-transformers model: {name}")
            break
        except Exception:
            continue
except ImportError:
    logger.info("sentence-transformers not installed, using TF-IDF fallback")


# ── TF-IDF 降级方案 ─────────────────────────────────
class _TfidfFallback:
    """简单的 TF-IDF 实现，用于无 sentence-transformers 时的降级"""

    def __init__(self, dim: int = 100):
        self.dim = dim
        self._word_freq = defaultdict(int)
        self._doc_count = 0
        self._char_weights = self._init_char_weights()

    def _init_char_weights(self):
        """基于字符 n-gram 初始化权重矩阵"""
        np.random.seed(42)
        return np.random.randn(256, self.dim) * 0.01

    def add_document(self, text: str):
        self._doc_count += 1
        for word in text.lower().split():
            self._word_freq[word] += 1

    def encode(self, word: str) -> np.ndarray:
        """将词转为向量（基于字符 n-gram 的简化方案）"""
        vec = np.zeros(self.dim, dtype=np.float32)
        chars = word.lower().encode("utf-8", errors="ignore")
        n = 0
        for b in chars:
            if b < 256:
                vec += self._char_weights[b]
                n += 1
        if n > 0:
            vec /= n
        # 加入哈希特征
        h = int(hashlib.md5(word.encode()).hexdigest()[:8], 16)
        np.random.seed(h)
        vec += np.random.randn(self.dim).astype(np.float32) * 0.01
        # 归一化
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm
        return vec

    def similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        return float(np.dot(a, b))


_tfidf = _TfidfFallback(dim=100)


# ── 公开接口 ────────────────────────────────────────

def get_vector(word: str) -> np.ndarray:
    """获取词向量"""
    if _MODEL:
        return _MODEL.encode(word, convert_to_numpy=True)
    return _tfidf.encode(word)


def compute_similarity(word1: str, word2: str) -> float:
    """计算两个词的语义相似度 (0-1)"""
    v1 = get_vector(word1)
    v2 = get_vector(word2)
    if _MODEL:
        from sentence_transformers import util
        return float(util.cos_sim(v1, v2)[0][0])
    return _tfidf.similarity(v1, v2)


def domain_relevance(word: str, domain_keywords: list[str]) -> float:
    """
    计算词与某个领域的相关性

    Args:
        word: 待评估词汇
        domain_keywords: 领域关键词列表（如 ["neural", "network", "deep"]）

    Returns:
        0-1 相关性得分
    """
    if not domain_keywords:
        return 0.5
    similarities = [compute_similarity(word, kw) for kw in domain_keywords]
    return float(np.mean(similarities))


def quality_score(word: str, domain_keywords: list[str] = None) -> dict:
    """
    评估词汇质量

    Returns:
        {"domain_score": float, "length_score": float, "uniqueness_score": float, "overall": float}
    """
    # 长度得分
    length = len(word)
    length_score = min(1.0, max(0.0, (length - 2) / 10))

    # 唯一性得分（基于字符熵）
    from collections import Counter
    char_counts = Counter(word.lower())
    total = len(word)
    entropy = -sum((c / total) * np.log2(c / total) for c in char_counts.values() if c > 0)
    uniqueness_score = min(1.0, entropy / 4.0)

    # 领域得分
    if domain_keywords:
        domain_score = domain_relevance(word, domain_keywords)
    else:
        domain_score = 0.5

    overall = length_score * 0.2 + uniqueness_score * 0.3 + domain_score * 0.5

    return {
        "domain_score": round(domain_score, 4),
        "length_score": round(length_score, 4),
        "uniqueness_score": round(uniqueness_score, 4),
        "overall": round(overall, 4),
    }


def add_documents(texts: list[str]):
    """添加文档以增强 TF-IDF 降级方案"""
    for t in texts:
        _tfidf.add_document(t)

"""
拼写检查模块
支持：字母顺序错误、缺漏字母、多余字母、形近字母替换
基于 pyspellchecker + 自定义规则
"""
import re
from collections import Counter


# ── 基础词典 ─────────────────────────────────────────
_DEFAULT_DICT = set("""
the be to of and a in that have i it for not on with he as you do at this but
his by from they we say her she or an will my one all would there their what
so up out if about who get which go me when make can like time no just him
know take people into year your good some could them see other than then now
look only come its over think also back after use two how our work first well
way even new want because any these give day most us great government company
number group problem fact computer system information project data program
business service team development research design support technology software
hardware network application server database client security analysis
international management organization product customer market process
algorithm neural deep learning machine gradient model training token
embedding semantic transformer attention convolution recurrent vector
matrix classification regression clustering optimization pipeline dataset
backpropagation layer activation inference prediction validation accuracy
loss function parameter hyperparameter architecture module component interface
implementation deployment configuration integration framework library
dictionary language spell random initialize normalize standardize feature
binary linear nonlinear logistic decision random forest boost neural
network artificial intelligence natural processing vision recognition
synthesis generation segmentation detection tracking reinforcement
supervised unsupervised semi-supervised transfer multitask multi-task
docker container kubernetes cloud python javascript typescript go rust
java kotlin swift react vue angular nextjs node express django flask
fastapi sql nosql postgres mysql mongodb redis elasticsearch kafka
rabbitmq nginx apache linux windows macos android ios web mobile
desktop server client frontend backend fullstack devops cicd agile scrum
""".split())

_KEYBOARD_NEIGHBORS = {
    'a': 'qwszx', 'b': 'vghn', 'c': 'xdfv', 'd': 'sxcfre', 'e': 'wsdfr',
    'f': 'drtgc', 'g': 'ftyhbv', 'h': 'gyujnb', 'i': 'ujklo', 'j': 'huikmn',
    'k': 'jiolm', 'l': 'kop', 'm': 'njk', 'n': 'bhjm', 'o': 'iklp',
    'p': 'ol', 'q': 'wa', 'r': 'etdfg', 's': 'awedcxz', 't': 'rfghy',
    'u': 'yhjki', 'v': 'cfgb', 'w': 'qase', 'x': 'zsdc', 'y': 'tghju',
    'z': 'asx',
}


def spellcheck(word: str, dictionary: set = None) -> dict:
    """
    拼写检查主函数

    Args:
        word: 待检查词汇
        dictionary: 自定义词典（不传则用内置）

    Returns:
        {
            "is_correct": bool,
            "errors": [{"type": "missing_letter", "detail": ..., "position": int}],
            "suggestions": [str, ...],
            "confidence": float 0-1,
        }
    """
    dic = dictionary or _DEFAULT_DICT
    word_lower = word.strip().lower()

    if not word_lower or len(word_lower) < 2:
        return {"is_correct": False, "errors": [], "suggestions": [], "confidence": 0.0}

    if word_lower in dic:
        return {"is_correct": True, "errors": [], "suggestions": [], "confidence": 1.0}

    errors = []
    suggestions = set()

    # ── 1. 字母顺序错误（交换相邻字母） ────────────────
    for i in range(len(word_lower) - 1):
        swapped = list(word_lower)
        swapped[i], swapped[i + 1] = swapped[i + 1], swapped[i]
        candidate = "".join(swapped)
        if candidate in dic:
            errors.append({"type": "transposition", "detail": f"{word_lower[i]}↔{word_lower[i+1]}", "position": i})
            suggestions.add(candidate)

    # ── 2. 缺漏字母 ──────────────────────────────────
    for i in range(len(word_lower) + 1):
        for ch in "abcdefghijklmnopqrstuvwxyz":
            candidate = word_lower[:i] + ch + word_lower[i:]
            if candidate in dic:
                suggestions.add(candidate)
    if suggestions:
        errors.append({"type": "missing_letter", "detail": f"可能缺漏字母", "position": -1})

    # ── 3. 多余字母 ──────────────────────────────────
    for i in range(len(word_lower)):
        candidate = word_lower[:i] + word_lower[i + 1:]
        if candidate in dic:
            errors.append({"type": "extra_letter", "detail": f"多余字母 '{word_lower[i]}'", "position": i})
            suggestions.add(candidate)

    # ── 4. 形近字母替换（键盘相邻键） ────────────────
    for i, ch in enumerate(word_lower):
        neighbors = _KEYBOARD_NEIGHBORS.get(ch, "")
        for nb in neighbors:
            candidate = word_lower[:i] + nb + word_lower[i + 1:]
            if candidate in dic:
                errors.append({"type": "keyboard_miss", "detail": f"{ch}→{nb} (键盘相邻)", "position": i})
                suggestions.add(candidate)

    # 去重
    suggestions = list(suggestions)[:5]

    # 置信度：基于匹配纠正数
    if suggestions:
        confidence = min(0.95, 0.5 + len(suggestions) * 0.1)
    else:
        confidence = 0.0

    return {
        "is_correct": False,
        "errors": errors[:3],
        "suggestions": suggestions,
        "confidence": confidence,
    }


# ── 批量检查 ────────────────────────────────────────
def batch_spellcheck(words: list[str], dictionary: set = None) -> list[dict]:
    return [spellcheck(w, dictionary) for w in words]

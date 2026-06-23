"""Flask API 服务"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, request, jsonify, send_from_directory

from src.pipeline import process_word, process_batch, init_with_seed_words
from src.database import get_all_words, get_stats, get_recent_logs, word_exists, get_word

app = Flask(__name__, static_folder=None)

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "web")


@app.route("/")
def index():
    return send_from_directory(WEB_DIR, "index.html")


@app.route("/api/check", methods=["POST"])
def api_check():
    """处理单个词汇"""
    data = request.get_json(force=True, silent=True) or {}
    word = data.get("word", "")
    if not word:
        return jsonify({"error": "word required"}), 400
    result = process_word(word, source="web")
    return jsonify(result)


@app.route("/api/batch", methods=["POST"])
def api_batch():
    """批量处理"""
    data = request.get_json(force=True, silent=True) or {}
    words = data.get("words", [])
    if not words:
        return jsonify({"error": "words required"}), 400
    result = process_batch(words, source="batch")
    return jsonify({"results": result, "count": len(result)})


@app.route("/api/stats")
def api_stats():
    return jsonify(get_stats())


@app.route("/api/words")
def api_words():
    return jsonify(get_all_words())


@app.route("/api/logs")
def api_logs():
    return jsonify(get_recent_logs(50))


@app.route("/api/word/<word>")
def api_get_word(word):
    w = get_word(word)
    if not w:
        return jsonify({"error": "not found"}), 404
    if "vector_array" in w:
        del w["vector_array"]  # 不在 JSON 中返回二进制
    if "vector" in w:
        del w["vector"]
    return jsonify(w)


def run(host="0.0.0.0", port=5001, debug=False):
    init_with_seed_words()
    print(f"http://127.0.0.1:{port}")
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    run(debug=True)

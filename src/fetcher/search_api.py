"""
GitHub Search API 数据抓取
搜索近期高星项目和新星项目
"""
import logging
import re
from datetime import datetime, timedelta, timezone

import requests

from config import GITHUB_TOKEN

logger = logging.getLogger(__name__)

API_BASE = "https://api.github.com"
HEADERS = {
    "Accept": "application/vnd.github.v3+json",
    "User-Agent": "GitHub-Trending-Daily",
}
if GITHUB_TOKEN and GITHUB_TOKEN not in ("0", "false", "no", "none"):
    HEADERS["Authorization"] = f"Bearer {GITHUB_TOKEN}"


def _api_get(url: str, params: dict = None) -> dict | None:
    """统一的 API GET 请求"""
    try:
        resp = requests.get(url, headers=HEADERS, params=params, timeout=30)
        if resp.status_code == 403 and "rate limit" in resp.text.lower():
            logger.warning("GitHub API rate limit exceeded")
            return None
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        logger.error(f"API request failed: {e}")
        return None


def _parse_repo(item: dict, source: str) -> dict:
    """将 API 返回的 repo 对象标准化"""
    return {
        "owner": item["owner"]["login"],
        "name": item["name"],
        "full_name": item["full_name"],
        "description": item.get("description") or "",
        "language": item.get("language") or "Unknown",
        "stars": item["stargazers_count"],
        "forks": item["forks_count"],
        "topics": item.get("topics", []),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
        "source": source,
        "url": item["html_url"],
        # API 特有字段
        "open_issues": item.get("open_issues_count", 0),
        "watchers": item.get("watchers_count", 0),
    }


def search_trending_repos(min_stars: int = 500, per_page: int = 30) -> list[dict]:
    """
    搜索近期获得大量 stars 的仓库（7天内创建或推送）

    按 stars 降序排列
    """
    since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    q = f"stars:>={min_stars} pushed:>={since}"
    return _search_repos(q, "stars", per_page, source_tag="api/trending")


def search_new_hot_repos(min_stars: int = 100, per_page: int = 30) -> list[dict]:
    """
    搜索30天内新建且已获得较多 stars 的项目（新星项目）
    """
    since = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
    q = f"stars:>={min_stars} created:>={since}"
    return _search_repos(q, "stars", per_page, source_tag="api/new-stars")


def search_ai_ml_repos(per_page: int = 20) -> list[dict]:
    """
    搜索 AI/ML/具身智能 相关的高星新项目
    """
    since = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
    topics = [
        "machine-learning", "deep-learning", "artificial-intelligence",
        "llm", "large-language-model", "generative-ai", "agent",
        "robotics", "reinforcement-learning", "pytorch", "transformer",
    ]
    topic_q = " OR ".join(f"topic:{t}" for t in topics)
    q = f"({topic_q}) stars:>=50 created:>={since}"
    return _search_repos(q, "stars", per_page, source_tag="api/ai-ml")


def _search_repos(q: str, sort: str = "stars", per_page: int = 30, source_tag: str = "api") -> list[dict]:
    """执行仓库搜索"""
    url = f"{API_BASE}/search/repositories"
    params = {"q": q, "sort": sort, "order": "desc", "per_page": per_page}
    data = _api_get(url, params)
    if not data or "items" not in data:
        return []

    repos = [_parse_repo(item, source_tag) for item in data["items"]]
    logger.info(f"Search API [{source_tag}]: found {len(repos)} repos (total: {data.get('total_count', 0)})")
    return repos


def fetch_all_api() -> list[dict]:
    """通过 API 获取多方数据并汇总"""
    all_repos = []
    all_repos.extend(search_trending_repos())
    all_repos.extend(search_new_hot_repos())
    all_repos.extend(search_ai_ml_repos())
    return all_repos


def search_high_value_repos(keywords: list[str], per_page: int = 15) -> list[dict]:
    """搜索具有长期价值的高 Star 项目（非近期热门）

    筛选条件：
    - Star >= 1000（高价值门槛）
    - 最近一年内有更新（仍在维护）
    - 按 Star 数降序（保证质量）

    Args:
        keywords: 搜索关键词列表
        per_page: 返回数量

    Returns:
        高价值项目列表，每个项目带 _source_note 字段标注来源
    """
    if not keywords:
        return []

    # 构建查询：关键词 OR 组合 + stars 门槛 + pushed 最近一年
    kw_query = " OR ".join(keywords[:5])
    q = f"{kw_query} stars:>1000 pushed:>={(datetime.now(timezone.utc) - timedelta(days=365)).strftime('%Y-%m-%d')}"

    url = f"{API_BASE}/search/repositories"
    params = {
        "q": q,
        "sort": "stars",
        "order": "desc",
        "per_page": per_page,
    }
    data = _api_get(url, params)
    if not data or "items" not in data:
        # 降级：去掉时间限制重试
        params["q"] = f"{kw_query} stars:>500"
        data = _api_get(url, params)
        if not data or "items" not in data:
            return []

    repos = []
    for item in data["items"]:
        repo = _parse_repo(item, "api/high-value")
        repo["_source_note"] = "high_value"  # 标注：高价值长期项目
        repos.append(repo)

    logger.info(f"High-value search [{keywords[:3]}]: found {len(repos)} repos")
    return repos


def fetch_readme(owner: str, name: str) -> str | None:
    """
    获取仓库的 README 内容（前 3000 字符）

    Returns:
        README 的纯文本内容，失败返回 None
    """
    url = f"{API_BASE}/repos/{owner}/{name}/readme"
    headers = dict(HEADERS)
    headers["Accept"] = "application/vnd.github.v3.raw"

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 404:
            # 尝试 master 分支
            resp2 = requests.get(
                f"https://raw.githubusercontent.com/{owner}/{name}/master/README.md",
                headers={"User-Agent": HEADERS["User-Agent"]}, timeout=15
            )
            if resp2.status_code == 404:
                resp2 = requests.get(
                    f"https://raw.githubusercontent.com/{owner}/{name}/main/README.md",
                    headers={"User-Agent": HEADERS["User-Agent"]}, timeout=15
                )
            if resp2.status_code != 200:
                return None
            text = resp2.text
        elif resp.status_code == 403:
            logger.warning(f"Rate limit fetching README for {owner}/{name}")
            return None
        elif resp.status_code != 200:
            return None
        else:
            text = resp.text

        # 移除 Markdown 标记，保留纯文本
        text = _strip_markdown(text)
        # 取前 2500 字符，尽量在句子边界截断
        if len(text) > 2500:
            truncated = text[:2500]
            last_dot = truncated.rfind(".")
            if last_dot > 500:
                text = truncated[:last_dot + 1]
            else:
                text = truncated.rstrip(".") + "."
        return text.strip()
    except requests.RequestException as e:
        logger.warning(f"Failed to fetch README for {owner}/{name}: {e}")
        return None


def _strip_markdown(text: str) -> str:
    """移除 Markdown 标记，保留可读文本"""
    # 移除图片
    text = re.sub(r'!\[.*?\]\(.*?\)', '', text)
    # 链接保留文字
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    # 移除标题标记
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    # 移除代码块
    text = re.sub(r'```[\s\S]*?```', '', text)
    # 移除行内代码
    text = re.sub(r'`([^`]+)`', r'\1', text)
    # 加粗/斜体
    text = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', text)
    # 引用
    text = re.sub(r'^>\s+', '', text, flags=re.MULTILINE)
    # 列表标记
    text = re.sub(r'^[\s]*[-*+]\s+', '- ', text, flags=re.MULTILINE)
    # HTML 标签
    text = re.sub(r'<[^>]+>', '', text)
    # 多余空行
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

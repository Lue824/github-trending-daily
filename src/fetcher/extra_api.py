"""
GitHub API 额外数据抓取
获取 issues/PR/contributors/releases/commits 等健康度维度数据
"""
import logging
import re
from datetime import datetime

import requests

from config import GITHUB_TOKEN

logger = logging.getLogger(__name__)

API_BASE = "https://api.github.com"
HEADERS = {
    "Accept": "application/vnd.github.v3+json",
    "User-Agent": "GitHub-Trending-Daily",
}

_INVALID_TOKENS = ("0", "false", "no", "none", "ghp_xxxxxxxxxxxx", "sk-xxxxxxxxxxxx")

def _has_valid_token() -> bool:
    t = GITHUB_TOKEN.strip()
    if not t:
        return False
    return not any(t.lower() == x.lower() or t.lower().startswith(x.lower()) for x in _INVALID_TOKENS)

if _has_valid_token():
    HEADERS["Authorization"] = f"Bearer {GITHUB_TOKEN}"


def _api_get(url: str, timeout: int = 20) -> dict | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        if resp.status_code == 403 and "rate limit" in resp.text.lower():
            logger.warning("GitHub API rate limit exceeded")
            return None
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        logger.warning(f"Extra API request failed: {e}")
        return None


def fetch_repo_extra(owner: str, name: str) -> dict:
    """
    获取单个仓库的额外健康度数据
    无有效 Token 时只获取基本信息
    """
    result = {
        "open_issues": 0,
        "open_prs": 0,
        "contributors": 0,
        "releases": 0,
        "last_release_days": None,
        "commits_12w": 0,
        "created_days": 0,
        "last_push_days": 0,
    }

    # 1. 仓库基本信息（不需要 Token）
    repo_data = _api_get(f"{API_BASE}/repos/{owner}/{name}")
    if repo_data:
        result["open_issues"] = repo_data.get("open_issues_count", 0)
        if repo_data.get("created_at"):
            created = datetime.strptime(repo_data["created_at"], "%Y-%m-%dT%H:%M:%SZ")
            result["created_days"] = (datetime.utcnow() - created).days
        if repo_data.get("pushed_at"):
            pushed = datetime.strptime(repo_data["pushed_at"], "%Y-%m-%dT%H:%M:%SZ")
            result["last_push_days"] = (datetime.utcnow() - pushed).days

    # 没有有效 Token 时不请求额外数据
    if not _has_valid_token():
        return result

    # 2. 开放 PR 数
    try:
        resp = requests.get(
            f"{API_BASE}/repos/{owner}/{name}/pulls?state=open&per_page=1",
            headers=HEADERS, timeout=15
        )
        if resp.status_code == 200:
            link = resp.headers.get("Link", "")
            if "last" in link:
                m = re.search(r'page=(\d+)>; rel="last"', link)
                if m:
                    result["open_prs"] = int(m.group(1))
            else:
                result["open_prs"] = len(resp.json())
    except Exception:
        pass

    # 3. 贡献者数
    try:
        resp = requests.get(
            f"{API_BASE}/repos/{owner}/{name}/contributors?per_page=1&anon=true",
            headers=HEADERS, timeout=15
        )
        if resp.status_code == 200:
            link = resp.headers.get("Link", "")
            if "last" in link:
                m = re.search(r'page=(\d+)>; rel="last"', link)
                if m:
                    result["contributors"] = int(m.group(1))
            else:
                result["contributors"] = len(resp.json())
    except Exception:
        pass

    # 4. Release 数
    releases_data = _api_get(f"{API_BASE}/repos/{owner}/{name}/releases?per_page=5")
    if releases_data and isinstance(releases_data, list):
        result["releases"] = len(releases_data)
        if releases_data and releases_data[0].get("published_at"):
            last_rel = datetime.strptime(
                releases_data[0]["published_at"], "%Y-%m-%dT%H:%M:%SZ"
            )
            result["last_release_days"] = (datetime.utcnow() - last_rel).days

    # 5. 近12周提交活跃度
    commit_stats = _api_get(
        f"{API_BASE}/repos/{owner}/{name}/stats/commit_activity", timeout=30
    )
    if commit_stats and isinstance(commit_stats, list):
        result["commits_12w"] = sum(w.get("total", 0) for w in commit_stats[-12:])

    return result


def fetch_extra_batch(repos: list[dict]) -> dict[str, dict]:
    """
    批量获取多个仓库的额外数据（并发，最多 5 线程）
    无有效 Token 直接跳过
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    if not _has_valid_token():
        logger.info("Skipping extra API: no valid GITHUB_TOKEN configured")
        return {}

    limit = 50
    top_repos = repos[:limit]
    logger.info(f"Fetching extra data for top {len(top_repos)} repos (concurrent, max 5 workers)...")

    extra_cache = {}

    def _fetch_one(r):
        try:
            return r["full_name"], fetch_repo_extra(r["owner"], r["name"])
        except Exception as e:
            logger.warning(f"Extra data failed for {r['full_name']}: {e}")
            return r["full_name"], {}

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(_fetch_one, r): r for r in top_repos}
        done = 0
        for future in as_completed(futures):
            full_name, extra = future.result()
            extra_cache[full_name] = extra
            done += 1
            if done % 10 == 0:
                logger.info(f"  Extra data progress: {done}/{len(top_repos)}")

    logger.info(f"Extra data fetched for {len(extra_cache)} repos")
    return extra_cache

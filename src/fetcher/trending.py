"""
GitHub Trending 页面爬虫
数据来源: https://github.com/trending
"""
import re
import logging
from datetime import datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup

from config import TRENDING_LANGUAGES, TRENDING_SINCE

logger = logging.getLogger(__name__)

TRENDING_BASE = "https://github.com/trending"


def _parse_stars(text: str) -> int:
    """'1,234' -> 1234, '12.3k' -> 12300"""
    try:
        text = text.strip().lower()
    except (AttributeError, TypeError):
        return 0
    if not text:
        return 0
    try:
        if "k" in text:
            return int(float(text.replace("k", "")) * 1000)
        return int(text.replace(",", ""))
    except (ValueError, TypeError):
        return 0


def _parse_stars_today(text: str) -> int:
    """'1,234 stars today' -> 1234"""
    if not text:
        return 0
    m = re.search(r"([\d,]+)\s*stars?\s*(today|this week|this month)?", text.strip().lower())
    if m:
        return _parse_stars(m.group(1))
    return 0


def fetch_trending_page(language: str = "", since: str = "daily") -> list[dict]:
    """
    抓取 GitHub Trending 页面

    Args:
        language: 编程语言（空字符串 = 全部语言）
        since: daily / weekly / monthly

    Returns:
        [{"owner": "x", "name": "y", "full_name": "x/y", ...}, ...]
    """
    url = f"{TRENDING_BASE}/{language}?since={since}" if language else f"{TRENDING_BASE}?since={since}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"Failed to fetch trending page ({language}/{since}): {e}")
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    repos = []

    for article in soup.select("article.Box-row"):
        try:
            # 仓库名
            h2 = article.select_one("h2")
            if not h2:
                continue
            link = h2.select_one("a")
            if not link:
                continue
            full_name = link.get("href", "").strip("/")
            parts = full_name.split("/")
            if len(parts) != 2:
                continue
            owner, name = parts

            # 描述
            desc_el = article.select_one("p")
            description = desc_el.get_text(strip=True) if desc_el else ""

            # 语言
            lang_el = article.select_one('[itemprop="programmingLanguage"]')
            lang = lang_el.get_text(strip=True) if lang_el else "Unknown"

            # Stars 总数
            stars_el = article.select_one("a.Link--muted")
            total_stars = 0
            stars_today = 0
            if stars_el:
                stars_text = stars_el.get_text(strip=True)
                total_stars = _parse_stars(stars_text)

            # 今日/本周 stars
            for span in article.select("span.d-inline-block"):
                text = span.get_text(strip=True)
                if "star" in text.lower():
                    stars_today = _parse_stars_today(text)
                    break

            # forks
            forks = 0
            fork_els = article.select("a.Link--muted")
            if len(fork_els) > 1:
                forks = _parse_stars(fork_els[1].get_text(strip=True))

            repos.append({
                "owner": owner,
                "name": name,
                "full_name": full_name,
                "description": description,
                "language": lang,
                "stars": total_stars,
                "stars_in_period": stars_today,
                "forks": forks,
                "source": f"trending/{since}",
                "url": f"https://github.com/{full_name}",
            })
        except Exception as e:
            logger.warning(f"Error parsing repo in trending/{language or 'all'}/{since}: {e}")

    logger.info(f"Fetched {len(repos)} repos from trending/{language or 'all'}/{since}")
    return repos


def fetch_all_trending() -> list[dict]:
    """抓取所有配置的语言和时间范围的 Trending 数据"""
    all_repos = []
    for lang in TRENDING_LANGUAGES:
        for since in TRENDING_SINCE:
            repos = fetch_trending_page(lang, since)
            all_repos.extend(repos)
    return all_repos

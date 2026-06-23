"""
SQLite 存储层：持久化每日数据，支持历史对比和趋势分析
"""
import json
import logging
import sqlite3
import os
from datetime import datetime, timedelta

from config import DB_PATH, DATA_RETENTION_DAYS

logger = logging.getLogger(__name__)


def get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """初始化数据库表结构（含自动迁移）"""
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS daily_repos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                owner TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                language TEXT DEFAULT 'Unknown',
                stars INTEGER DEFAULT 0,
                forks INTEGER DEFAULT 0,
                stars_in_period INTEGER DEFAULT 0,
                topics TEXT DEFAULT '[]',
                tags TEXT DEFAULT '[]',
                is_focus INTEGER DEFAULT 0,
                hot_score REAL DEFAULT 0.0,
                sources TEXT DEFAULT '[]',
                url TEXT DEFAULT '',
                fetch_date TEXT NOT NULL,
                created_at TEXT,
                updated_at TEXT
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_repo_date
                ON daily_repos(full_name, fetch_date);

            CREATE INDEX IF NOT EXISTS idx_fetch_date
                ON daily_repos(fetch_date);

            CREATE INDEX IF NOT EXISTS idx_language
                ON daily_repos(language);

            CREATE INDEX IF NOT EXISTS idx_is_focus
                ON daily_repos(is_focus);

            CREATE TABLE IF NOT EXISTS daily_summary (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT UNIQUE NOT NULL,
                total_repos INTEGER DEFAULT 0,
                trending_repos INTEGER DEFAULT 0,
                new_star_repos INTEGER DEFAULT 0,
                focus_repos INTEGER DEFAULT 0,
                top_languages TEXT DEFAULT '{}',
                top_focus_repos TEXT DEFAULT '[]',
                report_path TEXT DEFAULT ''
            );
        """)

        # ── 迁移：新增多维评分字段 ──────────────────────
        new_cols = [
            ("burst_score", "REAL DEFAULT 0.0"),
            ("quality_score", "REAL DEFAULT 0.0"),
            ("potential_score", "REAL DEFAULT 0.0"),
            ("ai_radar_score", "REAL DEFAULT 0.0"),
            ("is_trap", "INTEGER DEFAULT 0"),
            ("trap_signals", "INTEGER DEFAULT 0"),
            ("extra_data", "TEXT DEFAULT '{}'"),
        ]
        existing = {r[1] for r in conn.execute("PRAGMA table_info(daily_repos)").fetchall()}
        for col_name, col_def in new_cols:
            if col_name not in existing:
                conn.execute(f"ALTER TABLE daily_repos ADD COLUMN {col_name} {col_def}")
                logger.info(f"Migrated DB: added column {col_name}")
        conn.commit()
    logger.info("Database initialized")


def save_daily_repos(repos: list[dict], fetch_date: str):
    """保存一批当日仓库数据（含多维评分）"""
    with get_conn() as conn:
        for repo in repos:
            conn.execute("""
                INSERT OR REPLACE INTO daily_repos
                    (full_name, owner, name, description, language,
                     stars, forks, stars_in_period, topics, tags,
                     is_focus, hot_score, sources, url, fetch_date,
                     created_at, updated_at,
                     burst_score, quality_score, potential_score,
                     ai_radar_score, is_trap, trap_signals, extra_data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?)
            """, (
                repo["full_name"],
                repo["owner"],
                repo["name"],
                repo.get("description", ""),
                repo.get("language", "Unknown"),
                repo.get("stars", 0),
                repo.get("forks", 0),
                repo.get("stars_in_period", 0),
                json.dumps(repo.get("topics", [])),
                json.dumps(repo.get("tags", [])),
                1 if repo.get("is_focus") else 0,
                repo.get("hot_score", 0),
                json.dumps(repo.get("sources", [])),
                repo.get("url", ""),
                fetch_date,
                repo.get("created_at"),
                repo.get("updated_at"),
                repo.get("burst_score", 0),
                repo.get("quality_score", 0),
                repo.get("potential_score", 0),
                repo.get("ai_radar_score", 0),
                1 if repo.get("is_trap") else 0,
                repo.get("trap_signals", 0),
                json.dumps(repo.get("_extra", {})),
            ))
        conn.commit()
    logger.info(f"Saved {len(repos)} repos for {fetch_date}")


def save_daily_summary(date: str, repos: list[dict], report_path: str = ""):
    """保存每日摘要统计"""
    from collections import Counter

    total = len(repos)
    trending = sum(1 for r in repos if any("trending" in s for s in r.get("sources", [])))
    new_star = sum(1 for r in repos if any("new-stars" in s for s in r.get("sources", [])))
    focus = sum(1 for r in repos if r.get("is_focus"))

    # 语言分布
    lang_counter = Counter(r.get("language", "Unknown") for r in repos)
    top_langs = dict(lang_counter.most_common(10))

    # Top 关注领域项目
    focus_repos = sorted(
        [r for r in repos if r.get("is_focus")],
        key=lambda r: r.get("hot_score", 0), reverse=True
    )[:10]
    top_focus = [{"full_name": r["full_name"], "tags": r.get("tags", []), "stars": r.get("stars", 0)} for r in focus_repos]

    with get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO daily_summary
                (date, total_repos, trending_repos, new_star_repos, focus_repos,
                 top_languages, top_focus_repos, report_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (date, total, trending, new_star, focus, json.dumps(top_langs), json.dumps(top_focus), report_path))
        conn.commit()


def get_history_for_repo(full_name: str, days: int = 7) -> list[dict]:
    """查询某个仓库在最近 N 天的记录（用于连续在榜判断）"""
    since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT fetch_date, stars, hot_score FROM daily_repos WHERE full_name = ? AND fetch_date >= ? ORDER BY fetch_date",
            (full_name, since)
        ).fetchall()
    return [dict(r) for r in rows]


def mark_consecutive_streak(repos: list[dict], today: str, yesterday: str) -> list[dict]:
    """标记连续在榜的仓库（昨天也在榜）"""
    with get_conn() as conn:
        yesterday_repos = set(
            r[0] for r in conn.execute(
                "SELECT full_name FROM daily_repos WHERE fetch_date = ?", (yesterday,)
            ).fetchall()
        )

    for repo in repos:
        repo["on_list_yesterday"] = repo["full_name"] in yesterday_repos

        # 计算连续在榜天数
        full_name = repo["full_name"]
        history = get_history_for_repo(full_name, days=7)
        if len(history) >= 2:
            dates = sorted(set(h["fetch_date"] for h in history))
            streak = 1
            check_date = datetime.strptime(today, "%Y-%m-%d") - timedelta(days=1)
            while check_date.strftime("%Y-%m-%d") in dates:
                streak += 1
                check_date -= timedelta(days=1)
            repo["streak_days"] = streak
        else:
            repo["streak_days"] = 1 if repo.get("on_list_yesterday") else 0

    return repos


def get_yesterday_section_ranks(yesterday: str) -> dict:
    """获取昨天各区域的排名数据

    重建与 generate_daily_report() 相同的 3 个排名区域，
    返回 {full_name: {section_key: rank}} 映射。

    Args:
        yesterday: YYYY-MM-DD 格式的日期字符串

    Returns:
        dict keyed by full_name, each value is a dict mapping
        section keys ("trending"/"new_stars"/"focus") to 1-indexed ranks.
        Only repos that made the top-N cut in each section are included.
        Returns empty dict if no data for yesterday.
    """
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT full_name, hot_score, stars, sources, is_focus "
            "FROM daily_repos WHERE fetch_date = ?",
            (yesterday,)
        ).fetchall()

    if not rows:
        return {}

    repos = []
    for r in rows:
        d = dict(r)
        d["sources"] = json.loads(d.get("sources", "[]"))
        d["is_focus"] = bool(d.get("is_focus", 0))
        repos.append(d)

    trending = sorted(
        [r for r in repos if any("trending" in s for s in r["sources"])],
        key=lambda r: r["hot_score"], reverse=True
    )[:10]

    new_stars = sorted(
        [r for r in repos if any("new-stars" in s for s in r["sources"])],
        key=lambda r: r["stars"], reverse=True
    )[:10]

    focus = sorted(
        [r for r in repos if r["is_focus"]],
        key=lambda r: r["hot_score"], reverse=True
    )[:15]

    result: dict = {}
    for rank, r in enumerate(trending, 1):
        result.setdefault(r["full_name"], {})["trending"] = rank
    for rank, r in enumerate(new_stars, 1):
        result.setdefault(r["full_name"], {})["new_stars"] = rank
    for rank, r in enumerate(focus, 1):
        result.setdefault(r["full_name"], {})["focus"] = rank

    return result


def cleanup_old_data():
    """删除超过保留期限的数据"""
    cutoff = (datetime.utcnow() - timedelta(days=DATA_RETENTION_DAYS)).strftime("%Y-%m-%d")
    with get_conn() as conn:
        deleted_repos = conn.execute("DELETE FROM daily_repos WHERE fetch_date < ?", (cutoff,)).rowcount
        deleted_summaries = conn.execute("DELETE FROM daily_summary WHERE date < ?", (cutoff,)).rowcount
        conn.commit()
    if deleted_repos or deleted_summaries:
        logger.info(f"Cleanup: removed {deleted_repos} repos and {deleted_summaries} summaries before {cutoff}")


def get_monthly_stats() -> dict:
    """获取过去30天的统计数据，用于月度趋势分析"""
    since = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")
    with get_conn() as conn:
        # 每日聚焦项目数量
        daily_focus = conn.execute("""
            SELECT fetch_date, COUNT(*) as cnt
            FROM daily_repos
            WHERE fetch_date >= ? AND is_focus = 1
            GROUP BY fetch_date ORDER BY fetch_date
        """, (since,)).fetchall()

        # Top 语言趋势
        lang_trend = conn.execute("""
            SELECT language, COUNT(*) as cnt, AVG(stars) as avg_stars
            FROM daily_repos
            WHERE fetch_date >= ?
            GROUP BY language
            ORDER BY cnt DESC LIMIT 15
        """, (since,)).fetchall()

        # 持续热门项目（出现天数最多的）
        persistent = conn.execute("""
            SELECT full_name, owner, name, language, MAX(stars) as max_stars,
                   COUNT(DISTINCT fetch_date) as days_on_list,
                   GROUP_CONCAT(DISTINCT tags) as all_tags
            FROM daily_repos
            WHERE fetch_date >= ?
            GROUP BY full_name
            HAVING days_on_list >= 3
            ORDER BY days_on_list DESC, max_stars DESC
            LIMIT 30
        """, (since,)).fetchall()

        # 增速最快项目（30天内 star 增长）
        growth = conn.execute("""
            SELECT full_name, owner, name,
                   MAX(stars) - MIN(stars) as star_growth,
                   MAX(stars) as current_stars,
                   COUNT(DISTINCT fetch_date) as days_tracked
            FROM daily_repos
            WHERE fetch_date >= ?
            GROUP BY full_name
            HAVING star_growth > 0
            ORDER BY star_growth DESC
            LIMIT 20
        """, (since,)).fetchall()

    return {
        "daily_focus": [dict(r) for r in daily_focus],
        "top_languages": [dict(r) for r in lang_trend],
        "persistent_hot": [dict(r) for r in persistent],
        "fastest_growing": [dict(r) for r in growth],
    }

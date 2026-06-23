"""多源数据去重与合并"""


def deduplicate(repos: list[dict]) -> list[dict]:
    """
    按 full_name 去重，合并多源信息

    去重策略：
    1. full_name 相同的视为同一仓库
    2. 保留 sources 记录所有数据来源
    3. 信息合并时优先取非空字段
    """
    if not repos:
        return []
    merged = {}

    for repo in repos:
        key = (repo.get("full_name") or "").lower()
        if not key:
            continue
        source = repo.get("source") or "unknown"
        if key not in merged:
            merged[key] = dict(repo)
            merged[key]["sources"] = [source]
        else:
            existing = merged[key]
            # 合并来源
            if source not in existing["sources"]:
                existing["sources"].append(source)
            # 用非空值填补空字段
            for field in ("description", "language"):
                if not existing.get(field) and repo.get(field):
                    existing[field] = repo[field]
            if (repo.get("stars") or 0) > (existing.get("stars") or 0):
                existing["stars"] = repo.get("stars") or 0
            if (repo.get("forks") or 0) > (existing.get("forks") or 0):
                existing["forks"] = repo.get("forks") or 0
            existing["topics"] = list(set((existing.get("topics") or []) + (repo.get("topics") or [])))

    result = list(merged.values())
    # 删除 sources 辅助字段之外保留
    return result

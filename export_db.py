"""Export database to JSON for HF Spaces (no binary files allowed)"""
import json
import sqlite3
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import DB_PATH, DATA_DIR

JSON_PATH = os.path.join(DATA_DIR, "repos.json")

if not os.path.exists(DB_PATH):
    print(f"Database not found at {DB_PATH}")
    sys.exit(1)

with sqlite3.connect(DB_PATH) as conn:
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM daily_repos ORDER BY hot_score DESC").fetchall()

    repos = []
    for r in rows:
        d = dict(r)
        for k in ("topics", "tags", "sources", "extra_data"):
            if d.get(k):
                d[k] = json.loads(d[k])
        repos.append(d)

    latest = rows[0]["fetch_date"] if rows else ""

os.makedirs(DATA_DIR, exist_ok=True)
with open(JSON_PATH, "w", encoding="utf-8") as f:
    json.dump({"date": latest, "repos": repos}, f, ensure_ascii=False, indent=2)

print(f"Exported {len(repos)} repos for {latest} to {JSON_PATH}")

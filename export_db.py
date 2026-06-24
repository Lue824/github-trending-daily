"""Export database to JSON for HF Spaces (no binary files allowed)"""
import json
import sqlite3
import os

DB_PATH = os.path.join("data", "trending.db")
JSON_PATH = os.path.join("data", "repos.json")

if not os.path.exists(DB_PATH):
    print(f"Database not found at {DB_PATH}")
    # Try to read from the running server
    import urllib.request
    req = urllib.request.Request(
        "http://127.0.0.1:5000/api/custom",
        data=json.dumps({"query": "python"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        resp = urllib.request.urlopen(req)
        data = json.loads(resp.read())
        print(f"Server responded: {data.get('topic', 'unknown')}")
    except Exception as e:
        print(f"Server request failed: {e}")
    exit(1)

conn = sqlite3.connect(DB_PATH)
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
os.makedirs("data", exist_ok=True)
with open(JSON_PATH, "w", encoding="utf-8") as f:
    json.dump({"date": latest, "repos": repos}, f, ensure_ascii=False, indent=2)

print(f"Exported {len(repos)} repos for {latest} to {JSON_PATH}")
conn.close()

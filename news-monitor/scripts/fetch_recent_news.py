"""Fetch recent pushed news from production DB for prompt comparison."""
import json
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "news.db"
if not DB.is_file():
    print("DB not found:", DB)
    sys.exit(1)

db = sqlite3.connect(str(DB))
db.row_factory = sqlite3.Row
rows = db.execute("""
    SELECT id, title, content_snippet, source, captured_at, status
    FROM news
    WHERE content_snippet IS NOT NULL AND length(content_snippet) > 50
      AND status IN ('fast_pushed', 'deep_pushed')
    ORDER BY captured_at DESC
    LIMIT 30
""").fetchall()
db.close()

# 跳过最近 10 条（id 2363-2372，已测过）
SKIP_IDS = set(range(2363, 2373))
output = []
for r in rows:
    if r["id"] in SKIP_IDS:
        continue
    output.append({
        "id": r["id"],
        "title": r["title"],
        "snippet": (r["content_snippet"] or "")[:400],
        "source": r["source"],
        "status": r["status"],
        "captured_at": r["captured_at"],
    })
    if len(output) >= 20:
        break

print(json.dumps(output, ensure_ascii=False, indent=2))
print(f"\n共 {len(output)} 条推送新闻", file=sys.stderr)

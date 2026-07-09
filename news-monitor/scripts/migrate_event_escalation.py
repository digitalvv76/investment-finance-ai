# scripts/migrate_event_escalation.py
"""Apply or roll back event_lines escalation columns. Run inside container."""
import sys
sys.path.insert(0, ".")
from storage.database import Database

NEW_COLS = ["escalation_state", "peak_impact", "dominant_category",
            "dominant_sentiment", "alerted_at"]

def rollback(db_path: str):
    # SQLite ADD COLUMN is safe & additive; rollback = recreate without cols.
    db = Database(db_path)
    with db._get_conn() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(event_lines)").fetchall()
                if r[1] not in NEW_COLS]
        col_list = ", ".join(cols)
        conn.execute(f"CREATE TABLE event_lines_bak AS SELECT {col_list} FROM event_lines")
        conn.execute("DROP TABLE event_lines")
        conn.execute("ALTER TABLE event_lines_bak RENAME TO event_lines")
    print("rolled back escalation columns")

if __name__ == "__main__":
    path = sys.argv[2] if len(sys.argv) > 2 else "/app/data/news.db"
    if len(sys.argv) > 1 and sys.argv[1] == "rollback":
        rollback(path)
    else:
        Database(path).migrate_event_escalation()
        print("migration applied")

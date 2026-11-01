import sqlite3, sys
from pathlib import Path

DB_DEFAULT = "brain_index.sqlite"

def main():
    if len(sys.argv) < 2:
        print('Usage: python brain_search.py "query"')
        return
    q = " ".join(sys.argv[1:])
    db = Path(DB_DEFAULT)
    if not db.exists():
        print("DB not found:", db)
        return
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row

    # Auto-detect first non-system table
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
    if not tables:
        print("No tables found.")
        return
    table = tables[0][0]
    cols = [c[1] for c in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    textcol = cols[0]

    rows = conn.execute(f"SELECT * FROM {table} WHERE {textcol} LIKE ? LIMIT 10", (f"%{q}%",)).fetchall()
    for i, r in enumerate(rows, 1):
        print(f"[{i}] {str(r[textcol])[:300]}")
    conn.close()

if __name__ == "__main__":
    main()

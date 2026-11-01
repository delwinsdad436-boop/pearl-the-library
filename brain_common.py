#!/usr/bin/env python3
# Tala Brain Tools v2 - common utilities
import os, sqlite3, json, time, re
from typing import List, Dict, Any, Tuple, Optional

DEFAULT_DB = os.environ.get("TALA_BRAIN_DB", "brain_index.sqlite")

def connect(db_path: str = DEFAULT_DB) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def list_tables(conn: sqlite3.Connection) -> List[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    return [r["name"] for r in rows]

def detect_brain_table(conn: sqlite3.Connection) -> str:
    # Preferred names in descending priority
    preferred = ["cells", "brain", "records", "entries"]
    tables = set(list_tables(conn))
    for name in preferred:
        if name in tables:
            return name
    # Fallback: any non-sqlite internal table
    for t in list_tables(conn):
        if not t.startswith("sqlite_"):
            return t
    raise RuntimeError("No usable table found in DB. Run assemble_brain_v2.py to rebuild DB.")

def get_columns(conn: sqlite3.Connection, table: str) -> List[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [r["name"] for r in rows]

def normalize_text(s: str) -> str:
    if s is None:
        return ""
    # keep it light; normalize whitespace
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def safe_int(x, default=0):
    try:
        return int(x)
    except Exception:
        return default

def ensure_memory_db(mem_path: str = "memory.sqlite") -> sqlite3.Connection:
    conn = sqlite3.connect(mem_path)
    conn.row_factory = sqlite3.Row
    conn.execute("""
    CREATE TABLE IF NOT EXISTS memories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts INTEGER NOT NULL,
        kind TEXT NOT NULL,
        key TEXT,
        value TEXT NOT NULL,
        source TEXT,
        pinned INTEGER DEFAULT 0
    )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_kind ON memories(kind)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_key ON memories(key)")
    conn.commit()
    return conn

def add_memory(kind: str, value: str, key: str = None, source: str = None, pinned: bool = False, mem_path: str = "memory.sqlite") -> int:
    conn = ensure_memory_db(mem_path)
    ts = int(time.time())
    conn.execute("INSERT INTO memories(ts, kind, key, value, source, pinned) VALUES (?,?,?,?,?,?)",
                 (ts, kind, key, value, source, 1 if pinned else 0))
    conn.commit()
    rid = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    conn.close()
    return rid

def search_memories(query: str, limit: int = 10, mem_path: str = "memory.sqlite") -> List[Dict[str, Any]]:
    conn = ensure_memory_db(mem_path)
    q = f"%{query.strip()}%"
    rows = conn.execute("""
        SELECT id, ts, kind, key, value, source, pinned
        FROM memories
        WHERE value LIKE ? OR key LIKE ?
        ORDER BY pinned DESC, ts DESC
        LIMIT ?
    """, (q, q, limit)).fetchall()
    out = [dict(r) for r in rows]
    conn.close()
    return out

def format_hit(row: dict, cols: List[str]) -> dict:
    # Best effort fields
    title = row.get("title") or row.get("term") or row.get("headword") or row.get("name") or "(no title)"
    text = row.get("text") or row.get("definition") or row.get("content") or row.get("body") or ""
    source = row.get("source") or row.get("file") or row.get("chunk_file") or row.get("origin") or ""
    return {
        "id": row.get("id") or row.get("rowid") or row.get("idx") or "",
        "title": title,
        "text": normalize_text(text),
        "source": source,
        "_raw": {k: row.get(k) for k in cols}
    }

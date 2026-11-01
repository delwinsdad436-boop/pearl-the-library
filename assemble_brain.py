#!/usr/bin/env python3
# assemble_brain.py — TalaRipper Nano→SQLite assembler (Windows-safe, offline)
# Drop-in replacement for older assemble_brain.py that mis-detected/failed nano shards.

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

VERSION = "assemble_brain_v2.0 (nano-jsonl -> sqlite+fts5)"


# ---------- helpers ----------

def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk_size)
            if not b:
                break
            h.update(b)
    return h.hexdigest()

def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def now_iso() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")

def safe_json_dumps(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, sort_keys=True)
    except Exception:
        return json.dumps({"_nonserializable": True, "repr": repr(obj)}, ensure_ascii=False, sort_keys=True)

def pick_text(rec: Dict[str, Any]) -> str:
    for k in ("text", "content", "body", "definition", "value", "entry", "chunk", "raw"):
        v = rec.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    for k in ("data", "payload"):
        v = rec.get(k)
        if isinstance(v, dict):
            for kk in ("text", "content", "body", "definition"):
                vv = v.get(kk)
                if isinstance(vv, str) and vv.strip():
                    return vv.strip()
    return safe_json_dumps(rec)

def pick_source(rec: Dict[str, Any], default_source: str) -> str:
    for k in ("source", "src", "book", "title", "name"):
        v = rec.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return default_source

def pick_path(rec: Dict[str, Any], default_path: str) -> str:
    for k in ("path", "file", "filepath", "source_path"):
        v = rec.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return default_path

def uid_for(source_file: str, line_no: int, text: str) -> str:
    seed = f"{source_file}|{line_no}|{text[:256]}".encode("utf-8", "ignore")
    return sha256_bytes(seed)

def iter_jsonl(path: Path, encoding: str = "utf-8") -> Iterable[Tuple[int, Dict[str, Any]]]:
    with path.open("r", encoding=encoding, errors="replace") as f:
        for i, line in enumerate(f, start=1):
            s = line.strip()
            if not s:
                continue
            s = s.lstrip("\ufeff")
            obj = json.loads(s)
            if isinstance(obj, dict):
                yield i, obj
            else:
                yield i, {"_value": obj}


# ---------- sqlite ----------

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS docs (
    uid TEXT PRIMARY KEY,
    source_file TEXT NOT NULL,
    line_no INTEGER NOT NULL,
    source_name TEXT,
    source_path TEXT,
    text TEXT NOT NULL,
    meta_json TEXT,
    added_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts
USING fts5(text, uid UNINDEXED);

CREATE INDEX IF NOT EXISTS idx_docs_source_file ON docs(source_file);
"""

def ensure_fts5(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS __fts5check USING fts5(x);")
        conn.execute("DROP TABLE IF EXISTS __fts5check;")
    except sqlite3.OperationalError as e:
        raise RuntimeError(
            "SQLite FTS5 is not available in this Python build. "
            "Install a Python build with FTS5 enabled, or ask me for the non-FTS fallback."
        ) from e

def open_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys=ON;")
    ensure_fts5(conn)
    conn.executescript(SCHEMA_SQL)
    return conn

def insert_record(conn: sqlite3.Connection, rec: Dict[str, Any]) -> bool:
    try:
        conn.execute(
            "INSERT INTO docs(uid, source_file, line_no, source_name, source_path, text, meta_json, added_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (
                rec["uid"],
                rec["source_file"],
                rec["line_no"],
                rec.get("source_name"),
                rec.get("source_path"),
                rec["text"],
                rec.get("meta_json"),
                rec["added_at"],
            ),
        )
    except sqlite3.IntegrityError:
        return False
    conn.execute("INSERT INTO docs_fts(text, uid) VALUES(?,?)", (rec["text"], rec["uid"]))
    return True


# ---------- main ----------

def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="assemble_brain.py",
        description="Assemble TalaRipper nano_out/*.jsonl shards into a searchable SQLite brain (FTS5).",
    )
    ap.add_argument("--nano-dir", default="nano_out", help="Folder containing nano_*.jsonl + nano_manifest.json")
    ap.add_argument("--db", default="brain_index.sqlite", help="Output SQLite DB path")
    ap.add_argument("--rebuild", action="store_true", help="Delete DB and rebuild from scratch")
    ap.add_argument("--encoding", default="utf-8", help="Text encoding to read JSONL (errors replaced)")
    ap.add_argument("--limit", type=int, default=0, help="Optional max records to ingest (0 = no limit)")
    ap.add_argument("--commit-every", type=int, default=2000, help="Commit every N inserts")
    ap.add_argument("--report", default="assemble_report.json", help="Write run report JSON here")
    ap.add_argument("--manifest", default="assemble_manifest_sha256.txt", help="Write SHA256 manifest of outputs here")
    args = ap.parse_args(argv)

    root = Path.cwd()
    nano_dir = (root / args.nano_dir).resolve()
    db_path = (root / args.db).resolve()
    report_path = (root / args.report).resolve()
    manifest_path = (root / args.manifest).resolve()

    if not nano_dir.exists() or not nano_dir.is_dir():
        print(f"[ERR] nano-dir not found: {nano_dir}")
        return 2

    jsonl_files = sorted(nano_dir.glob("nano_*.jsonl"))
    if not jsonl_files:
        print(f"[ERR] No nano_*.jsonl files in: {nano_dir}")
        return 2

    if args.rebuild and db_path.exists():
        db_path.unlink()

    conn = open_db(db_path)

    total_files = 0
    total_lines = 0
    inserted = 0
    skipped_dupe = 0
    failed_files = 0
    errors_log: list[dict[str, Any]] = []

    started = now_iso()
    commit_every = max(1, int(args.commit_every))
    limit = int(args.limit) if args.limit else 0

    try:
        for jf in jsonl_files:
            total_files += 1
            default_source = jf.name
            default_path = str(jf)

            try:
                for line_no, obj in iter_jsonl(jf, encoding=args.encoding):
                    total_lines += 1
                    if limit and inserted >= limit:
                        break

                    text = pick_text(obj)
                    source_name = pick_source(obj, default_source)
                    source_path = pick_path(obj, default_path)

                    uid = uid_for(jf.name, line_no, text)

                    meta = dict(obj)
                    if "text" in meta and isinstance(meta["text"], str) and len(meta["text"]) > 5000:
                        meta["text"] = meta["text"][:5000] + "…[truncated]"
                    meta_json = safe_json_dumps(meta)

                    rec = {
                        "uid": uid,
                        "source_file": jf.name,
                        "line_no": line_no,
                        "source_name": source_name,
                        "source_path": source_path,
                        "text": text,
                        "meta_json": meta_json,
                        "added_at": now_iso(),
                    }

                    ok = insert_record(conn, rec)
                    if ok:
                        inserted += 1
                    else:
                        skipped_dupe += 1

                    if inserted % commit_every == 0:
                        conn.commit()

                if limit and inserted >= limit:
                    break

            except Exception as e:
                failed_files += 1
                errors_log.append({"file": str(jf), "error": repr(e)})

        conn.commit()
    finally:
        conn.close()

    finished = now_iso()

    report = {
        "tool": "assemble_brain.py",
        "version": VERSION,
        "started_at": started,
        "finished_at": finished,
        "nano_dir": str(nano_dir),
        "db_path": str(db_path),
        "files_found": len(jsonl_files),
        "files_failed": failed_files,
        "lines_seen": total_lines,
        "records_inserted": inserted,
        "records_duplicates_skipped": skipped_dupe,
        "errors": errors_log[:50],
    }
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    manifest_lines = []
    for p in (db_path, report_path):
        if p.exists():
            manifest_lines.append(f"{sha256_file(p)}  {p.name}")
    manifest_path.write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")

    print("ASSEMBLE V2 COMPLETE")
    print(f"Nano dir:    {nano_dir}")
    print(f"DB:          {db_path}")
    print(f"Files found: {len(jsonl_files)}")
    print(f"Files failed:{failed_files}")
    print(f"Lines seen:  {total_lines}")
    print(f"Inserted:    {inserted}")
    print(f"Dupes skip:  {skipped_dupe}")
    print(f"Report:      {report_path}")
    print(f"Manifest:    {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

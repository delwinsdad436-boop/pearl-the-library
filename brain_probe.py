#!/usr/bin/env python3
"""brain_probe.py

Quick sanity-check for brain_index.sqlite.
Prints tables, columns, and row counts.

Usage:
  python brain_probe.py
  python brain_probe.py --db brain_index.sqlite
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--db", default="brain_index.sqlite", help="Path to sqlite DB")
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"DB not found: {db_path}")
        return 2

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    tables = cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()

    if not tables:
        print("No tables found.")
        return 1

    print(f"DB: {db_path}")
    for (t,) in tables:
        print("\nTABLE:", t)
        cols = cur.execute(f"PRAGMA table_info({t})").fetchall()
        for c in cols:
            # (cid, name, type, notnull, dflt_value, pk)
            print(f"  - {c[1]} ({c[2]})")
        try:
            n = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print("  rows:", n)
        except Exception as e:
            print("  rows: (error)", e)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

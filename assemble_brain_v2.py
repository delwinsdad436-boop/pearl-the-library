
import os
import json
import sqlite3
import argparse
from pathlib import Path
from datetime import datetime

def build_db(nano_dir, out_db, rebuild=False):
    nano_dir = Path(nano_dir)
    if not nano_dir.exists():
        print(f"[ERROR] nano_dir not found: {nano_dir}")
        return

    if rebuild and Path(out_db).exists():
        os.remove(out_db)

    conn = sqlite3.connect(out_db)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS brain (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_file TEXT,
            record_index INTEGER,
            content TEXT
        )
    """)
    conn.commit()

    total = 0
    failed = 0

    for f in sorted(nano_dir.glob("*.jsonl")):
        print(f"Loading {f.name}")
        with open(f, "r", encoding="utf-8", errors="ignore") as fh:
            for i, line in enumerate(fh):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    content = json.dumps(obj, ensure_ascii=False)
                    cur.execute(
                        "INSERT INTO brain (source_file, record_index, content) VALUES (?, ?, ?)",
                        (f.name, i, content)
                    )
                    total += 1
                except Exception:
                    failed += 1
        conn.commit()

    conn.close()

    print("\nASSEMBLY COMPLETE")
    print("Records written:", total)
    print("Records failed:", failed)
    print("Output DB:", out_db)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--nano-dir", required=True)
    parser.add_argument("--out", default="brain_index.sqlite")
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()

    build_db(args.nano_dir, args.out, args.rebuild)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
import sqlite3
import hashlib
import re
import argparse
from collections import defaultdict

def normalize(text):
    text = text.lower()
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'[^\w\s]', '', text)
    return text.strip()

def fingerprint(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def main(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Create dedupe map table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS brain_dedupe_map (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_id INTEGER,
            dupe_group TEXT,
            fingerprint TEXT,
            normalized_fingerprint TEXT,
            match_type TEXT
        )
    """)

    conn.commit()

    rows = cur.execute("SELECT id, content FROM brain").fetchall()

    raw_map = defaultdict(list)
    norm_map = defaultdict(list)

    for rid, content in rows:
        if not content:
            continue
        raw_fp = fingerprint(content)
        norm_fp = fingerprint(normalize(content))
        raw_map[raw_fp].append(rid)
        norm_map[norm_fp].append(rid)

    dupe_group_id = 0

    for fp, ids in raw_map.items():
        if len(ids) > 1:
            group = f"exact_{dupe_group_id}"
            for rid in ids:
                cur.execute(
                    "INSERT INTO brain_dedupe_map (record_id, dupe_group, fingerprint, normalized_fingerprint, match_type) VALUES (?, ?, ?, ?, ?)",
                    (rid, group, fp, None, "exact")
                )
            dupe_group_id += 1

    for fp, ids in norm_map.items():
        if len(ids) > 1:
            group = f"normalized_{dupe_group_id}"
            for rid in ids:
                cur.execute(
                    "INSERT INTO brain_dedupe_map (record_id, dupe_group, fingerprint, normalized_fingerprint, match_type) VALUES (?, ?, ?, ?, ?)",
                    (rid, group, None, fp, "normalized")
                )
            dupe_group_id += 1

    conn.commit()
    print("Soft dedupe mapping complete.")
    print("Groups created:", dupe_group_id)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="brain_index.sqlite", help="Path to SQLite brain DB")
    args = parser.parse_args()
    main(args.db)

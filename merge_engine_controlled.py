#!/usr/bin/env python3
"""
merge_engine_controlled.py

A controlled, interrupt-safe "merge planner" for TalaRipper brain_index.sqlite.

SAFE DEFAULT:
- Reads your SQLite DB
- Finds near-duplicate candidates using bucketing (avoids all-pairs)
- Shows progress + ETA
- Writes a PLAN file (JSONL) you can review

It will NOT modify your database in this build (apply is guarded).
"""

from __future__ import annotations
import argparse
import sqlite3
import time
import json
import re
import os
import sys
import hashlib
from dataclasses import dataclass
from typing import Dict, List, Tuple, Iterable, Set, Optional

DEFAULT_DB = "brain_index.sqlite"
DEFAULT_TABLE = "brain"
DEFAULT_CONTENT_COL = "content"
DEFAULT_ID_COL = "id"

WORD_RE = re.compile(r"[a-z0-9']+")

def now() -> float:
    return time.time()

def fmt_secs(s: float) -> str:
    s = max(0, int(s))
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"

def print_progress(done: int, total: int, start_t: float, prefix: str = "") -> None:
    if total <= 0:
        return
    elapsed = now() - start_t
    rate = done / elapsed if elapsed > 0 else 0.0
    remain = (total - done) / rate if rate > 0 else 0.0
    pct = (done / total) * 100
    bar_len = 24
    fill = int((done / total) * bar_len)
    bar = "#" * fill + "-" * (bar_len - fill)
    sys.stdout.write(f"\r{prefix}[{bar}] {pct:6.2f}% | ETA {fmt_secs(remain)} | {done:,}/{total:,}")
    sys.stdout.flush()

def normalize_text(s: str) -> str:
    s = s.lower()
    s = s.replace("\u00a0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s

def tokenize(s: str) -> List[str]:
    return WORD_RE.findall(s.lower())

def stable_u64(x: str, seed: int) -> int:
    h = hashlib.blake2b((str(seed) + "|" + x).encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(h, "little", signed=False)

def minhash_signature(tokens: Set[str], seeds: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
    if not tokens:
        return (0, 0, 0, 0)
    mins = []
    for sd in seeds:
        m = None
        for t in tokens:
            hv = stable_u64(t, sd)
            if m is None or hv < m:
                m = hv
        mins.append(m or 0)
    return tuple(mins)  # type: ignore

def bucket_keys(sig: Tuple[int, int, int, int]) -> Tuple[str, str, str, str]:
    a, b, c, d = sig
    return (f"A:{a}", f"B:{b}", f"C:{c}", f"D:{d}")

def cheap_signature(text: str) -> Tuple[int, int, int, int]:
    toks = set(tokenize(text))
    return minhash_signature(toks, (101, 202, 303, 404))

def ratio(a: str, b: str) -> float:
    import difflib
    return difflib.SequenceMatcher(None, a, b).ratio()

@dataclass
class Rec:
    id: int
    content: str

def detect_table_and_columns(conn: sqlite3.Connection, table: str, id_col: str, content_col: str) -> Tuple[str, str, str]:
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]

    chosen_table = table if table in tables else None
    if chosen_table is None:
        chosen_table = "brain" if "brain" in tables else (tables[0] if tables else None)
    if not chosen_table:
        raise RuntimeError("No tables found in database.")

    cur.execute(f"PRAGMA table_info({chosen_table})")
    cols = [r[1] for r in cur.fetchall()]

    chosen_id = id_col if id_col in cols else None
    chosen_content = content_col if content_col in cols else None

    if chosen_id is None:
        for c in ("id", "rowid", "pk"):
            if c in cols:
                chosen_id = c
                break
    if chosen_content is None:
        for c in ("content", "text", "body", "definition"):
            if c in cols:
                chosen_content = c
                break

    if chosen_id is None or chosen_content is None:
        raise RuntimeError(
            f"Could not find required columns. Table '{chosen_table}' has columns: {cols}. "
            f"Need an id-like column and a content/text column."
        )
    return chosen_table, chosen_id, chosen_content

def load_records(conn: sqlite3.Connection, table: str, id_col: str, content_col: str) -> List[Rec]:
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    total = int(cur.fetchone()[0] or 0)

    recs: List[Rec] = []
    start_t = now()
    cur.execute(f"SELECT {id_col}, {content_col} FROM {table}")
    fetched = 0
    while True:
        rows = cur.fetchmany(500)
        if not rows:
            break
        for rid, content in rows:
            if content is None:
                content = ""
            recs.append(Rec(int(rid), normalize_text(str(content))))
        fetched += len(rows)
        if fetched % 5000 == 0 or fetched == total:
            print_progress(fetched, total, start_t, prefix="Load  ")
    sys.stdout.write("\n")
    return recs

def build_buckets(recs: List[Rec]) -> Dict[str, List[int]]:
    buckets: Dict[str, List[int]] = {}
    start_t = now()
    total = len(recs)
    for i, r in enumerate(recs, start=1):
        sig = cheap_signature(r.content)
        for k in bucket_keys(sig):
            buckets.setdefault(k, []).append(i-1)
        if i % 200 == 0 or i == total:
            print_progress(i, total, start_t, prefix="Sig   ")
    sys.stdout.write("\n")
    return buckets

def candidate_pairs_from_buckets(buckets: Dict[str, List[int]], max_bucket: int, max_pairs: int) -> Set[Tuple[int, int]]:
    pairs: Set[Tuple[int, int]] = set()
    keys = list(buckets.keys())
    start_t = now()
    for idx, k in enumerate(keys, start=1):
        ids = buckets[k]
        if len(ids) < 2:
            continue
        if len(ids) > max_bucket:
            continue
        for i in range(len(ids)):
            a = ids[i]
            for j in range(i+1, len(ids)):
                b = ids[j]
                if a < b:
                    pairs.add((a, b))
                else:
                    pairs.add((b, a))
                if len(pairs) >= max_pairs:
                    sys.stdout.write("\n")
                    return pairs
        if idx % 100 == 0 or idx == len(keys):
            print_progress(idx, len(keys), start_t, prefix="Cand  ")
            sys.stdout.write(f" | pairs {len(pairs):,}")
            sys.stdout.flush()
    sys.stdout.write("\n")
    return pairs

def plan_merges(
    recs: List[Rec],
    pairs: Iterable[Tuple[int, int]],
    threshold: float,
    out_path: str,
    throttle_ms: int,
    checkpoint_path: Optional[str] = None,
) -> Dict[str, int]:
    pairs_list = list(pairs)
    total = len(pairs_list)
    start_t = now()

    start_index = 0
    if checkpoint_path and os.path.exists(checkpoint_path):
        try:
            with open(checkpoint_path, "r", encoding="utf-8") as f:
                ck = json.load(f)
            start_index = int(ck.get("next_index", 0))
        except Exception:
            start_index = 0

    kept = 0
    scanned = 0
    mode = "a" if start_index > 0 else "w"

    with open(out_path, mode, encoding="utf-8") as out:
        for i in range(start_index, total):
            a_idx, b_idx = pairs_list[i]
            a = recs[a_idx].content
            b = recs[b_idx].content
            s = ratio(a, b)
            scanned += 1
            if s >= threshold:
                kept += 1
                out.write(json.dumps({
                    "a_id": recs[a_idx].id,
                    "b_id": recs[b_idx].id,
                    "score": round(float(s), 6),
                    "a_len": len(a),
                    "b_len": len(b),
                }) + "\n")

            if (i+1) % 200 == 0 or (i+1) == total:
                print_progress(i+1, total, start_t, prefix="Score ")
                sys.stdout.write(f" | kept {kept:,}")
                sys.stdout.flush()
                if checkpoint_path:
                    tmp = checkpoint_path + ".tmp"
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump({"next_index": i+1, "total": total, "kept": kept}, f)
                    os.replace(tmp, checkpoint_path)

            if throttle_ms > 0 and (i+1) % 200 == 0:
                time.sleep(throttle_ms / 1000.0)

    sys.stdout.write("\n")
    return {"pairs_total": total, "pairs_scanned": scanned, "kept": kept}

def apply_merges_guardrail() -> None:
    print("\nAPPLY MODE IS GUARDED IN THIS BUILD.")
    print("If you want apply mode, I’ll generate a separate tool that:")
    print("  (1) makes a full DB backup,")
    print("  (2) logs every change,")
    print("  (3) can rollback.\n")

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--table", default=DEFAULT_TABLE)
    ap.add_argument("--id-col", default=DEFAULT_ID_COL)
    ap.add_argument("--content-col", default=DEFAULT_CONTENT_COL)
    ap.add_argument("--mode", choices=["plan", "apply"], default="plan")
    ap.add_argument("--threshold", type=float, default=0.99)
    ap.add_argument("--max-bucket", type=int, default=60)
    ap.add_argument("--max-pairs", type=int, default=200000)
    ap.add_argument("--out", default="merge_plan.jsonl")
    ap.add_argument("--checkpoint", default="merge_plan.checkpoint.json")
    ap.add_argument("--no-checkpoint", action="store_true")
    ap.add_argument("--throttle-ms", type=int, default=50)
    args = ap.parse_args()

    if not os.path.exists(args.db):
        print(f"ERROR: DB not found: {args.db}")
        return 2

    conn = sqlite3.connect(args.db)
    try:
        table, id_col, content_col = detect_table_and_columns(conn, args.table, args.id_col, args.content_col)
        print(f"Using table={table}, id_col={id_col}, content_col={content_col}")

        recs = load_records(conn, table, id_col, content_col)
        print(f"Loaded {len(recs):,} records")

        buckets = build_buckets(recs)
        print(f"Built {len(buckets):,} buckets")

        pairs = candidate_pairs_from_buckets(buckets, max_bucket=args.max_bucket, max_pairs=args.max_pairs)
        print(f"Candidate pairs: {len(pairs):,} (cap {args.max_pairs:,})")

        if args.mode == "plan":
            ck = None if args.no_checkpoint else args.checkpoint
            print(f"Writing plan to: {args.out}")
            stats = plan_merges(
                recs=recs,
                pairs=pairs,
                threshold=float(args.threshold),
                out_path=args.out,
                throttle_ms=int(args.throttle_ms),
                checkpoint_path=ck,
            )
            print("\nDONE.")
            print(json.dumps(stats, indent=2))
            print(f"\nReview: {args.out}")
            return 0

        apply_merges_guardrail()
        return 1
    finally:
        conn.close()

if __name__ == "__main__":
    raise SystemExit(main())

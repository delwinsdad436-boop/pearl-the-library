#!/usr/bin/env python3
"""
merge_engine.py — non-destructive merge engine for TalaRipper brain_index.sqlite

What it does
- Finds duplicate / near-duplicate rows in table `brain`
- Produces a PLAN (default) OR applies merges (creates canonical mappings)
- Never deletes rows. It only records canonical relationships and merge events.

Expected schema (auto-created if missing)
- brain(id INTEGER PRIMARY KEY AUTOINCREMENT, record_index INTEGER, source_file TEXT, content TEXT)

It will create:
- canonical_map(child_id INTEGER PRIMARY KEY, canonical_id INTEGER NOT NULL, reason TEXT, score REAL, created_at TEXT)
- merge_events(event_id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, reason TEXT, score REAL,
               canonical_id INTEGER, merged_child_ids TEXT)

Usage
  python merge_engine.py --db brain_index.sqlite --mode plan
  python merge_engine.py --db brain_index.sqlite --mode apply --threshold 0.98

Notes
- threshold is 0..1 (higher = stricter). Default 0.99 (very strict).
- Similarity is computed on normalized content (whitespace/punctuation normalized).
"""

import argparse
import datetime as _dt
import json
import re
import sqlite3
import sys
from difflib import SequenceMatcher
from typing import Dict, List, Tuple

# === TALA_PROGRESS_PATCH_V1 ===
import time as _tala_time
from datetime import timedelta as _tala_timedelta
_TALA_PROGRESS_LOG = r"C:\Users\delwi\TalaRipper\logs\merge_progress.log"

class _TalaProgress:
    def __init__(self, total=None, phase="merge"):
        self.total = total if (isinstance(total, int) and total > 0) else None
        self.phase = phase
        self.t0 = _tala_time.time()
        self.last = self.t0
        self.n = 0
        self.last_n = 0

    def set_phase(self, phase: str):
        self.phase = phase

    def tick(self, inc: int = 1, force: bool = False):
        self.n += inc
        now = _tala_time.time()
        if force or (now - self.last) >= 1.0:
            dt = max(1e-9, now - self.last)
            dn = self.n - self.last_n
            rate = dn / dt
            elapsed = now - self.t0
            if self.total:
                pct = min(100.0, (self.n / self.total) * 100.0)
                rem = max(0.0, self.total - self.n)
                avg = self.n / max(1e-9, elapsed)
                eta = rem / max(1e-9, avg)
                eta_s = str(_tala_timedelta(seconds=int(eta)))
                msg = f"[{self.phase}] {pct:6.2f}%  n={self.n}/{self.total}  rate={rate:,.1f}/s  ETA={eta_s}"
            else:
                msg = f"[{self.phase}] n={self.n}  rate={rate:,.1f}/s  elapsed={str(_tala_timedelta(seconds=int(elapsed)))}"
            print(msg, flush=True)
            try:
                with open(_TALA_PROGRESS_LOG, "a", encoding="utf-8") as f:
                    f.write(msg + "\n")
            except Exception:
                pass
            self.last = now
            self.last_n = self.n

# CPU-safe similarity
import re as _tala_re
from difflib import SequenceMatcher as _tala_SM
_tala_ws = _tala_re.compile(r"\s+")

def _tala_norm(s: str) -> str:
    s = (s or "").lower()
    s = _tala_ws.sub(" ", s).strip()
    return s

def _tala_jaccard(a: str, b: str) -> float:
    ta = set(a.split())
    tb = set(b.split())
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    uni = len(ta | tb)
    return inter / uni if uni else 0.0

def _tala_similarity_safe(a: str, b: str, max_chars: int = 6000) -> float:
    a = _tala_norm(a)
    b = _tala_norm(b)
    if not a or not b:
        return 0.0
    la, lb = len(a), len(b)
    mx = max(la, lb)
    if mx == 0:
        return 0.0
    if abs(la - lb) / mx > 0.65:
        return 0.0
    if mx > max_chars:
        j = _tala_jaccard(a, b)
        if j < 0.10:
            return j
        try:
            return max(j, _tala_SM(None, a[:max_chars], b[:max_chars]).ratio())
        except Exception:
            return j
    try:
        return _tala_SM(None, a, b).ratio()
    except Exception:
        return _tala_jaccard(a, b)
# === /TALA_PROGRESS_PATCH_V1 ===


def now_iso() -> str:
    return _dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def norm_text(s: str) -> str:
    if s is None:
        return ""
    s = s.strip().lower()
    # normalize whitespace
    s = re.sub(r"\s+", " ", s)
    # drop non-word punctuation but keep spaces
    s = re.sub(r"[^\w\s]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def similarity(a: str, b: str) -> float:
    # SequenceMatcher works well enough for "same content with minor differences"
    return SequenceMatcher(None, a, b).ratio()


def ensure_tables(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS canonical_map (
            child_id INTEGER PRIMARY KEY,
            canonical_id INTEGER NOT NULL,
            reason TEXT,
            score REAL,
            created_at TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS merge_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT,
            reason TEXT,
            score REAL,
            canonical_id INTEGER,
            merged_child_ids TEXT
        )
        """
    )
    conn.commit()


def load_brain_rows(conn: sqlite3.Connection) -> List[Tuple[int, str, str]]:
    """
    Returns: list of (id, source_file, content)
    """
    cur = conn.cursor()
    # tolerate missing columns if user's schema differs slightly
    # We only need id + content, and source_file if present.
    # Try most common schema first.
    for sql in [
        "SELECT id, source_file, content FROM brain",
        "SELECT id, '' as source_file, content FROM brain",
        "SELECT rowid as id, '' as source_file, content FROM brain",
    ]:
        try:
            cur.execute(sql)
            rows = cur.fetchall()
            return [(int(r[0]), str(r[1]), str(r[2]) if r[2] is not None else "") for r in rows]
        except sqlite3.Error:
            continue
    raise RuntimeError("Could not read from table `brain`. Expected columns include at least `content`.")


def already_mapped(conn: sqlite3.Connection, child_id: int) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM canonical_map WHERE child_id=?", (child_id,))
    return cur.fetchone() is not None


def plan_merges(
    rows: List[Tuple[int, str, str]],
    threshold: float,
    max_pairs: int = 250000,
) -> List[Dict]:
    """
    Very strict plan:
    1) Exact normalized match -> merge
    2) Near match above threshold -> merge
    Strategy:
    - First bucket by normalized text hash (exact).
    - Then (optional) near-dup scan within each bucket of same first N chars.
    """
    # 1) Exact normalized matches
    buckets: Dict[str, List[Tuple[int, str, str]]] = {}
    for rid, src, content in rows:
        nt = norm_text(content)
        if not nt:
            continue
        buckets.setdefault(nt, []).append((rid, src, content))

    plan: List[Dict] = []
    for nt, items in buckets.items():
        if len(items) >= 2:
            # choose smallest id as canonical
            canonical = sorted(items, key=lambda x: x[0])[0]
            children = [x for x in items if x[0] != canonical[0]]
            plan.append(
                {
                    "reason": "exact_normalized_match",
                    "score": 1.0,
                    "canonical_id": canonical[0],
                    "canonical_source": canonical[1],
                    "child_ids": [c[0] for c in children],
                    "child_sources": [c[1] for c in children],
                }
            )

    # 2) Near matches: only if threshold < 1.0
    if threshold < 1.0:
        # reduce comparison space: key by prefix of normalized text
        prefix_bins: Dict[str, List[Tuple[int, str]]] = {}
        for rid, _, content in rows:
            nt = norm_text(content)
            if not nt:
                continue
            key = nt[:40]  # prefix
            prefix_bins.setdefault(key, []).append((rid, nt))

        pairs_checked = 0
        used = set()  # ids already scheduled (avoid chaining weirdness)
        for key, items in prefix_bins.items():
            if len(items) < 2:
                continue
            # naive O(n^2) inside bin, but bins should be small; guard with max_pairs
            items_sorted = sorted(items, key=lambda x: x[0])
            for i in range(len(items_sorted)):
                if pairs_checked >= max_pairs:
                    break
                id_i, txt_i = items_sorted[i]
                for j in range(i + 1, len(items_sorted)):
                    if pairs_checked >= max_pairs:
                        break
                    id_j, txt_j = items_sorted[j]
                    pairs_checked += 1
                    if id_i in used or id_j in used:
                        continue
                    
                        try:
                            _tala_prog.tick()
                        except Exception:
                            pass
                    
                    sc = similarity(txt_i, txt_j)
                    if sc >= threshold:
                        canonical_id = min(id_i, id_j)
                        child_id = max(id_i, id_j)
                        plan.append(
                            {
                                "reason": "near_duplicate",
                                "score": float(sc),
                                "canonical_id": canonical_id,
                                "canonical_source": "",
                                "child_ids": [child_id],
                                "child_sources": [""],
                            }
                        )
                        used.add(child_id)

    # Sort: exact first, then near-dup by score desc
    plan.sort(key=lambda p: (0 if p["reason"].startswith("exact") else 1, -p["score"], p["canonical_id"]))
    return plan


def apply_plan(conn: sqlite3.Connection, plan: List[Dict], dry_run: bool = False) -> Dict[str, int]:
    ensure_tables(conn)
    cur = conn.cursor()

    created = 0
    events = 0
    for entry in plan:
        canonical_id = int(entry["canonical_id"])
        child_ids = [int(x) for x in entry["child_ids"]]
        reason = entry["reason"]
        score = float(entry["score"])

        # record mappings (skip those already mapped)
        mapped_any = False
        mapped_children: List[int] = []
        for cid in child_ids:
            if cid == canonical_id:
                continue
            if already_mapped(conn, cid):
                continue
            mapped_any = True
            mapped_children.append(cid)
            if not dry_run:
                cur.execute(
                    "INSERT OR REPLACE INTO canonical_map(child_id, canonical_id, reason, score, created_at) VALUES (?,?,?,?,?)",
                    (cid, canonical_id, reason, score, now_iso()),
                )
                created += 1

        if mapped_any:
            if not dry_run:
                cur.execute(
                    "INSERT INTO merge_events(created_at, reason, score, canonical_id, merged_child_ids) VALUES (?,?,?,?,?)",
                    (now_iso(), reason, score, canonical_id, json.dumps(mapped_children)),
                )
                events += 1

    if not dry_run:
        conn.commit()
    return {"mappings_created": created, "merge_events_created": events}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="Path to brain_index.sqlite (or brain_index.sqlite)")
    ap.add_argument("--mode", choices=["plan", "apply"], default="plan", help="plan prints merges; apply writes canonical_map")
    ap.add_argument("--threshold", type=float, default=0.99, help="Near-dup similarity threshold (0..1). Default 0.99")
    ap.add_argument("--limit", type=int, default=0, help="Optional limit of rows to scan (0 = all)")
    ap.add_argument("--max-pairs", type=int, default=250000, help="Safety cap on near-dup comparisons")
    args = ap.parse_args()

    if not (0.0 <= args.threshold <= 1.0):
        print("ERROR: --threshold must be between 0 and 1", file=sys.stderr)
        return 2

    conn = sqlite3.connect(args.db)
    try:
        ensure_tables(conn)
        rows = load_brain_rows(conn)
        if args.limit and args.limit > 0:
            rows = rows[: args.limit]

        plan = plan_merges(rows, threshold=args.threshold, max_pairs=args.max_pairs)

        print("\nMERGE ENGINE REPORT")
        print("===================")
        print(f"DB: {args.db}")
        print(f"Rows scanned: {len(rows)}")
        print(f"Planned merge groups: {len(plan)}")
        print(f"Mode: {args.mode}")
        print(f"Threshold: {args.threshold:0.4f}\n")

        if not plan:
            print("No merge candidates found.\n")
            return 0

        # Print preview
        show_n = min(30, len(plan))
        for idx in range(show_n):
            p = plan[idx]
            print(f"[{idx+1}] reason={p['reason']} score={p['score']:.4f} canonical_id={p['canonical_id']} children={p['child_ids']}")
        if len(plan) > show_n:
            print(f"... ({len(plan)-show_n} more)\n")

        if args.mode == "apply":
            out = apply_plan(conn, plan, dry_run=False)
            print("\nAPPLY RESULT")
            print("------------")
            print(f"canonical_map rows created: {out['mappings_created']}")
            print(f"merge_events rows created: {out['merge_events_created']}\n")
            print("Done.")
        else:
            print("This was a PLAN only. To APPLY:")
            print(f"  python merge_engine.py --db \"{args.db}\" --mode apply --threshold {args.threshold}")
            print()

        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

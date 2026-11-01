#!/usr/bin/env python3
import argparse, json, os, shutil, sqlite3, datetime, hashlib


def now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def sha256_file(path, chunk=1024 * 1024):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def ensure_schema(c: sqlite3.Connection):
    c.execute(
        """
    CREATE TABLE IF NOT EXISTS merge_lineage(
        dup_id      INTEGER PRIMARY KEY,
        canon_id    INTEGER NOT NULL,
        score       REAL,
        decided_at  TEXT,
        note        TEXT
    )
    """
    )
    c.execute(
        """
    CREATE TABLE IF NOT EXISTS merge_log(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        decided_at TEXT,
        event_json TEXT
    )
    """
    )
    c.execute(
        """
    CREATE VIEW IF NOT EXISTS v_brain_canon AS
    SELECT b.*
    FROM brain b
    LEFT JOIN merge_lineage ml ON ml.dup_id = b.id
    WHERE ml.dup_id IS NULL
    """
    )
    c.commit()


def iter_plan(path):
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def pick_canon(a_id, b_id, a_len, b_len):
    # Keep the longer content as canonical. Tie -> smaller id.
    if a_len is None or b_len is None:
        return (min(a_id, b_id), max(a_id, b_id))
    if a_len > b_len:
        return (a_id, b_id)
    if b_len > a_len:
        return (b_id, a_id)
    return (a_id, b_id) if a_id <= b_id else (b_id, a_id)


def make_backup(db_path, backup_dir):
    os.makedirs(backup_dir, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    base = os.path.basename(db_path)
    backup_path = os.path.join(backup_dir, f"{base}.bak_{ts}")
    shutil.copy2(db_path, backup_path)
    return backup_path


def log_event(c: sqlite3.Connection, event: dict):
    c.execute(
        "INSERT INTO merge_log(decided_at,event_json) VALUES(?,?)",
        (now_iso(), json.dumps(event, ensure_ascii=False)),
    )
    c.commit()


def apply_plan(db_path, plan_path, threshold, dry_run=False, backup_dir="backups"):
    if not os.path.exists(db_path):
        raise SystemExit(f"DB not found: {db_path}")
    if not os.path.exists(plan_path):
        raise SystemExit(f"Plan not found: {plan_path}")

    backup_path = make_backup(db_path, backup_dir) if not dry_run else None
    if backup_path:
        print(f"[BACKUP] {backup_path}")
        print(f"[BACKUP_SHA256] {sha256_file(backup_path)}")

    c = sqlite3.connect(db_path)
    c.execute("PRAGMA journal_mode=WAL;")
    c.execute("PRAGMA synchronous=NORMAL;")
    ensure_schema(c)

    existing = {row[0]: row[1] for row in c.execute("SELECT dup_id, canon_id FROM merge_lineage")}
    decided = 0
    kept = 0
    skipped = 0

    for rec in iter_plan(plan_path):
        score = float(rec.get("score", 0.0))
        if score < threshold:
            continue

        a_id = int(rec["a_id"])
        b_id = int(rec["b_id"])
        a_len = rec.get("a_len")
        b_len = rec.get("b_len")
        canon_id, dup_id = pick_canon(a_id, b_id, a_len, b_len)

        # Avoid chains: if either id already appears in lineage, skip it.
        if dup_id in existing or canon_id in existing:
            skipped += 1
            continue

        event = {
            "action": "lineage_link",
            "canon_id": canon_id,
            "dup_id": dup_id,
            "score": score,
            "rule": "keep_longest_then_smallest_id",
        }

        if dry_run:
            kept += 1
        else:
            c.execute(
                "INSERT OR REPLACE INTO merge_lineage(dup_id, canon_id, score, decided_at, note) VALUES(?,?,?,?,?)",
                (dup_id, canon_id, score, now_iso(), "non_destructive_lineage"),
            )
            log_event(c, event)
            existing[dup_id] = canon_id
            kept += 1

        decided += 1
        if decided % 500 == 0:
            print(f"[PROGRESS] decided={decided} kept={kept} skipped={skipped}")

    c.commit()
    c.close()

    print("DONE")
    print(
        json.dumps(
            {
                "threshold": threshold,
                "decisions_processed": decided,
                "kept_links": kept,
                "skipped_existing": skipped,
                "dry_run": dry_run,
                "backup": backup_path,
            },
            indent=2,
        )
    )


def rollback(db_path, backup_path):
    if not os.path.exists(backup_path):
        raise SystemExit(f"Backup not found: {backup_path}")
    if os.path.exists(db_path):
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(db_path, db_path + f".pre_rollback_{ts}")
    shutil.copy2(backup_path, db_path)
    print(f"ROLLED BACK. Restored {db_path} from {backup_path}")


def main():
    ap = argparse.ArgumentParser(
        description="Guarded apply for merge_plan.jsonl (non-destructive lineage)."
    )
    ap.add_argument("--db", default="brain_index.sqlite")
    ap.add_argument("--plan", default="merge_plan.jsonl")
    ap.add_argument("--threshold", type=float, default=0.99)
    ap.add_argument("--mode", choices=["dry-run", "apply", "rollback"], default="dry-run")
    ap.add_argument("--backup", default=None, help="Backup path for rollback mode")
    ap.add_argument("--backup-dir", default="backups", help="Where to store backups on apply")
    args = ap.parse_args()

    if args.mode == "rollback":
        if not args.backup:
            raise SystemExit("rollback requires --backup <path>")
        rollback(args.db, args.backup)
        return

    dry = args.mode == "dry-run"
    apply_plan(
        db_path=args.db,
        plan_path=args.plan,
        threshold=args.threshold,
        dry_run=dry,
        backup_dir=args.backup_dir,
    )


if __name__ == "__main__":
    main()

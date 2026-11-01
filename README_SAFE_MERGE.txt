Tala Ripper – Safe Merge Stage (NON-DESTRUCTIVE, LINEAGE-PRESERVING)
==============================================================

What this does
--------------
You already generated:  merge_plan.jsonl   (pairs of likely duplicates)
These tools will:
  1) Inspect & summarize the plan (no DB changes)
  2) Apply merges SAFELY:
      - Creates a full DB backup
      - NEVER deletes rows
      - Stores lineage mapping (duplicate -> canonical)
      - Logs every merge decision
      - Produces a "canonical view" for clean querying
  3) Export canonical rows to JSONL or a new SQLite if you want

Files
-----
A) plan_inspect.py
   Summarize merge_plan.jsonl (counts, score stats, clusters, sample pairs)

B) guarded_apply.py
   Applies the plan non-destructively with backup + logs.
   Creates tables:
     - merge_lineage(dup_id, canon_id, score, decided_at, note)
     - merge_log(id, event_json)
   And a view:
     - v_brain_canon  (records not marked as duplicates)

C) export_canon.py
   Export canonical records to:
     - canon.jsonl
     - or canon.sqlite (optional)

D) run_plan_inspect.bat / run_apply.bat
   Double-click helpers for Windows.

E) QUICK_COMMANDS.txt
   Copy/paste friendly commands.

Typical workflow
----------------
1) Put these .py files in your TalaRipper folder (same folder as brain_index.sqlite and merge_plan.jsonl)

2) Inspect first (safe):
   python plan_inspect.py --plan merge_plan.jsonl

3) Apply (safe, with backup):
   python guarded_apply.py --db brain_index.sqlite --plan merge_plan.jsonl --threshold 0.99 --mode apply

4) Query canon view:
   python -c "import sqlite3; c=sqlite3.connect('brain_index.sqlite'); print(c.execute('SELECT COUNT(*) FROM v_brain_canon').fetchone())"

If you want to undo
-------------------
guarded_apply.py prints the backup path to stdout.
Just replace brain_index.sqlite with that backup, or:
   python guarded_apply.py --db brain_index.sqlite --mode rollback --backup <backupfile>

Notes
-----
- This stage does NOT merge text together. It preserves every original record.
- It only creates lineage pointers so the system can treat duplicates as one concept.

Tala Stage G (Hybrid) — Autonomous Canon Formation
===================================================

This builds 'soft canon clusters' from brain_index.sqlite.

- Nothing is deleted.
- Nothing is overwritten.
- It only groups similar cells and assigns a hybrid score.

Install
-------
Copy canon_former.py into:
  C:\Users\delwi\TalaRipper\

Run (CMD)
---------
cd /d "C:\Users\delwi\TalaRipper"
python canon_former.py --db brain_index.sqlite --out canon_out --threshold 0.82

Outputs
-------
canon_out\
  canon_index.sqlite
  canon_clusters.jsonl
  canon_report.txt
  canon_manifest.json

Tuning
------
More merging: lower threshold (e.g. 0.78)
Less merging:  raise threshold (e.g. 0.86)

If your schema differs:
python canon_former.py --help

TALA_PROGRESS_SYSTEM.zip

This adds LOTS of progress output (percent/ETA style) to your existing merge_engine.py.

INSTALL (no editing):
1) Copy these files into your TalaRipper folder (same folder as merge_engine.py):
   - patch_merge_engine_progress.py
   - progress_watch.py

2) Run patcher:
   python patch_merge_engine_progress.py

3) Run merge (example):
   PLAN:
     python merge_engine.py --db brain_index.sqlite --mode plan --threshold 0.88 --max-pairs 2500
   APPLY:
     python merge_engine.py --db brain_index.sqlite --mode apply

LIVE MONITOR (2nd window):
   python progress_watch.py

ROLLBACK:
- Your original file is saved automatically as merge_engine.py.BAK-YYYYMMDD-HHMMSS

@echo off
cd /d "%~dp0"
python guarded_apply.py --db brain_index.sqlite --plan merge_plan.jsonl --threshold 0.99 --mode apply
pause

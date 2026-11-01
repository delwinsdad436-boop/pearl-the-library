@echo off
cd /d "%~dp0"
python plan_inspect.py --plan merge_plan.jsonl
pause

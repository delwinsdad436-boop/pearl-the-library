#!/usr/bin/env python3
"""
brain_agent.py — simple offline agent loop (no LLM required)

It can:
- search brain
- save memories
- create a task plan and checkpoint it

Usage:
  python brain_agent.py --goal "Build memory writeback"
"""
import argparse, time
from brain_common import add_memory
from brain_chat import simple_plan

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--goal", required=True, help="Your objective")
    args = ap.parse_args()

    goal = args.goal.strip()
    steps = simple_plan(goal)
    plan_txt = "\n".join([f"{i+1}. {s}" for i,s in enumerate(steps)])
    add_memory(kind="agent_goal", key=goal[:120], value=plan_txt, pinned=True)
    print("AGENT PLAN (saved to memory.sqlite):\n")
    print(plan_txt)
    print("\nNext: run brain_chat.py and ask questions; use /remember for new facts.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

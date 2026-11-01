# progress_watch.py
import time
from pathlib import Path

ROOT = Path(".")
db = ROOT / "brain_index.sqlite"
log = ROOT / "logs" / "merge_progress.log"

def fmt_bytes(n):
    for unit in ["B","KB","MB","GB","TB","PB"]:
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}EB"

while True:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print("="*70)
    print(ts)

    if db.exists():
        st = db.stat()
        print(f"DB: {db.name}  mtime={time.strftime('%H:%M:%S', time.localtime(st.st_mtime))}  size={fmt_bytes(st.st_size)}")
    else:
        print("DB: brain_index.sqlite not found here")

    if log.exists():
        try:
            tail = log.read_text(encoding="utf-8", errors="ignore").splitlines()[-15:]
            print("--- progress tail ---")
            for ln in tail:
                print(ln)
        except Exception as e:
            print("Could not read progress log:", e)
    else:
        print("No logs/merge_progress.log yet.")
    time.sleep(5)

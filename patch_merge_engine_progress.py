# patch_merge_engine_progress.py
import re
import time
import shutil
from pathlib import Path

ROOT = Path(".")
SRC = ROOT / "merge_engine.py"
if not SRC.exists():
    raise SystemExit("ERROR: merge_engine.py not found in current folder. Run this from your TalaRipper directory.")

ts = time.strftime("%Y%m%d-%H%M%S")
bak = ROOT / f"merge_engine.py.BAK-{ts}"
shutil.copy2(SRC, bak)

text = SRC.read_text(encoding="utf-8", errors="replace")

logs_dir = ROOT / "logs"
logs_dir.mkdir(exist_ok=True)
progress_log_path = str((logs_dir / "merge_progress.log").resolve())

if "TALA_PROGRESS_PATCH_V1" not in text:
    helper_block = (
        "\n# === TALA_PROGRESS_PATCH_V1 ===\n"
        "import time as _tala_time\n"
        "from datetime import timedelta as _tala_timedelta\n"
        f"_TALA_PROGRESS_LOG = r\"{progress_log_path}\"\n"
        "\n"
        "class _TalaProgress:\n"
        "    def __init__(self, total=None, phase=\"merge\"):\n"
        "        self.total = total if (isinstance(total, int) and total > 0) else None\n"
        "        self.phase = phase\n"
        "        self.t0 = _tala_time.time()\n"
        "        self.last = self.t0\n"
        "        self.n = 0\n"
        "        self.last_n = 0\n"
        "\n"
        "    def set_phase(self, phase: str):\n"
        "        self.phase = phase\n"
        "\n"
        "    def tick(self, inc: int = 1, force: bool = False):\n"
        "        self.n += inc\n"
        "        now = _tala_time.time()\n"
        "        if force or (now - self.last) >= 1.0:\n"
        "            dt = max(1e-9, now - self.last)\n"
        "            dn = self.n - self.last_n\n"
        "            rate = dn / dt\n"
        "            elapsed = now - self.t0\n"
        "            if self.total:\n"
        "                pct = min(100.0, (self.n / self.total) * 100.0)\n"
        "                rem = max(0.0, self.total - self.n)\n"
        "                avg = self.n / max(1e-9, elapsed)\n"
        "                eta = rem / max(1e-9, avg)\n"
        "                eta_s = str(_tala_timedelta(seconds=int(eta)))\n"
        "                msg = f\"[{self.phase}] {pct:6.2f}%  n={self.n}/{self.total}  rate={rate:,.1f}/s  ETA={eta_s}\"\n"
        "            else:\n"
        "                msg = f\"[{self.phase}] n={self.n}  rate={rate:,.1f}/s  elapsed={str(_tala_timedelta(seconds=int(elapsed)))}\"\n"
        "            print(msg, flush=True)\n"
        "            try:\n"
        "                with open(_TALA_PROGRESS_LOG, \"a\", encoding=\"utf-8\") as f:\n"
        "                    f.write(msg + \"\\n\")\n"
        "            except Exception:\n"
        "                pass\n"
        "            self.last = now\n"
        "            self.last_n = self.n\n"
        "\n"
        "# CPU-safe similarity\n"
        "import re as _tala_re\n"
        "from difflib import SequenceMatcher as _tala_SM\n"
        "_tala_ws = _tala_re.compile(r\"\\s+\")\n"
        "\n"
        "def _tala_norm(s: str) -> str:\n"
        "    s = (s or \"\").lower()\n"
        "    s = _tala_ws.sub(\" \", s).strip()\n"
        "    return s\n"
        "\n"
        "def _tala_jaccard(a: str, b: str) -> float:\n"
        "    ta = set(a.split())\n"
        "    tb = set(b.split())\n"
        "    if not ta and not tb:\n"
        "        return 1.0\n"
        "    if not ta or not tb:\n"
        "        return 0.0\n"
        "    inter = len(ta & tb)\n"
        "    uni = len(ta | tb)\n"
        "    return inter / uni if uni else 0.0\n"
        "\n"
        "def _tala_similarity_safe(a: str, b: str, max_chars: int = 6000) -> float:\n"
        "    a = _tala_norm(a)\n"
        "    b = _tala_norm(b)\n"
        "    if not a or not b:\n"
        "        return 0.0\n"
        "    la, lb = len(a), len(b)\n"
        "    mx = max(la, lb)\n"
        "    if mx == 0:\n"
        "        return 0.0\n"
        "    if abs(la - lb) / mx > 0.65:\n"
        "        return 0.0\n"
        "    if mx > max_chars:\n"
        "        j = _tala_jaccard(a, b)\n"
        "        if j < 0.10:\n"
        "            return j\n"
        "        try:\n"
        "            return max(j, _tala_SM(None, a[:max_chars], b[:max_chars]).ratio())\n"
        "        except Exception:\n"
        "            return j\n"
        "    try:\n"
        "        return _tala_SM(None, a, b).ratio()\n"
        "    except Exception:\n"
        "        return _tala_jaccard(a, b)\n"
        "# === /TALA_PROGRESS_PATCH_V1 ===\n"
    )

    # insert helper block after last import
    lines = text.splitlines(True)
    last_import = -1
    for i, ln in enumerate(lines):
        s = ln.lstrip()
        if s.startswith("import ") or s.startswith("from "):
            last_import = i
    if last_import >= 0:
        text = "".join(lines[:last_import+1]) + helper_block + "".join(lines[last_import+1:])
    else:
        text = helper_block + "\n" + text

# replace similarity() if present and looks difflib-based
sim_pat = r"\ndef\s+similarity\s*\((.*?)\)\s*:\s*\n(.*?)\n(?=def\s|\Z)"
m = re.search(sim_pat, text, flags=re.S)
if m and ("SequenceMatcher" in m.group(2) or ".ratio(" in m.group(2)):
    fn_args = m.group(1)
    repl = f"\ndef similarity({fn_args}):\n    return _tala_similarity_safe(a, b)\n"
    text = text[:m.start()] + repl + text[m.end():]

# inject progress object into common entrypoints (best-effort)
def inject_prog(fn_name: str, src: str) -> str:
    pat = rf"\ndef\s+{fn_name}\s*\(.*?\)\s*:\s*\n"
    mm = re.search(pat, src)
    if not mm:
        return src
    ins = mm.end()
    inject = "    _tala_prog = _TalaProgress(total=None, phase='" + fn_name + "')\n"
    return src[:ins] + inject + src[ins:]

text = inject_prog("plan_merges", text)
text = inject_prog("apply_merges", text)

# inject tick before first similarity(...) assignment call
tick_block = "\n    try:\n        _tala_prog.tick()\n    except Exception:\n        pass\n"
text = re.sub(
    r"(\n)(\s*)([a-zA-Z_][a-zA-Z0-9_]*\s*=\s*similarity\s*\()",
    lambda m: m.group(1) + m.group(2) + tick_block.replace("\n", "\n"+m.group(2)) + "\n" + m.group(2) + m.group(3),
    text,
    count=1,
    flags=re.S
)

SRC.write_text(text, encoding="utf-8", errors="ignore")

print("OK: merge_engine.py patched with progress + safe similarity")
print("Backup:", bak.name)
print("Progress log: logs\\merge_progress.log")

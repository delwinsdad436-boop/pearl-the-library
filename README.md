# The Library — TalaRipper Brain Workshop

The workshop where the brain was built. In January–February 2026, in this
folder, James Cochrum ripped books and documents into text chunks, assembled
them into a SQLite brain, and built the tools to search it, chat with it
offline, and form canon out of it safely — every merge planned, inspected,
applied behind a guard, and reversible.

This is the second of three repos:

1. **Engine + Wiring** — llama.cpp, the model, and `brain_ask2.py`, the wire
   that grounds a model's answers in this library.
2. **The Library** (this repo) — the workshop and the brain itself.
3. **The Self** — the paper brain: identity, laws, and the formation record.

## What's here

- `brain_index.sqlite` — the brain. One table, `brain` (`id`, `content`),
  **2,087 passages** ripped from dictionaries and reference works. Verified
  by row count against the live machine it was built on. It ships here as
  `brain_index.sqlite.zip` (the raw file is 36,454,400 bytes); run
  `python extract_brain.py` once to unpack it — the script verifies the
  extracted file's SHA-256, and Codespaces runs it automatically.
- `TALA_CHUNKS.zip` — the chunk archive the brain was assembled from.
- The brain tools (Python 3, standard library only, no pip installs):
  - `brain_common.py` — shared helpers: DB detection, a small memory store.
  - `brain_search.py` — CLI search (`--probe` inspects the DB).
  - `brain_chat.py` — offline chat over the brain, with memory writeback.
  - `brain_gui.py` — Tkinter search GUI.
  - `brain_agent.py`, `brain_probe.py`, `brain_rip.py`, `brain_exporter.py`
- The assembly line: `ripper.py` / `ripper_gui.py` turn documents into
  chunks; `assemble_brain.py` / `assemble_brain_v2.py` build the DB.
- The canon stations — dedupe and merge without ever losing the original:
  - `plan_inspect.py` reads a merge plan before anything moves.
  - `guarded_apply.py` applies it (backup + lineage, `--mode rollback` undoes).
  - `canon_former.py` clusters near-duplicates into canonical records
    (defaults: table `brain`, id `id`, text `content`, threshold 0.82).
  - `export_canon.py`, `merge_engine.py`, `soft_dedupe.py`, and the
    `README_*.txt` station notes James left beside each tool.
- `brain_ask.py` / `brain_ask2.py` — the wiring scripts, written later in
  this same folder, that connect this brain to a local model (they live
  permanently in the Engine + Wiring repo; copies are here because this is
  where they were born and run).

## Run it

```
python extract_brain.py
python brain_search.py --probe
python brain_search.py "due process" --limit 8
python brain_chat.py
```

Or open this repo in GitHub Codespaces — the included devcontainer starts
with Python ready, extracts the brain from its zip, and prints the brain's
passage count as a smoke test.
The tools need nothing beyond the standard library.

## Provenance

Recovered intact from the author's own archive on 2026-10-31 and verified
before staging: the brain's 2,087 rows match the count on the live laptop,
and the file is byte-identical in size (36,454,400 bytes) to the original.
Working scratch from the original folder (ripped-text temp dumps, caches)
is not included; the code, the stations, and the brain are the library.
One repair was made for publication: the usage line in `brain_search.py`
had unescaped quotes and could not run (SyntaxError); the quotes are
fixed. One transport change was made at the same gate, on the author's
ruling of 2026-11-01: the brain ships zipped (`brain_index.sqlite.zip`,
about 11 MB) because the raw 36,454,400-byte file exceeded the publishing
route's per-file limits. The brain inside is byte-identical to the
original — SHA-256 of the extracted file:
9204ab28cc9d50cfd1b2f233cb098615f259d67a7942cf97009b07d18823fb05 —
and `extract_brain.py` refuses to hand you anything that does not match
it. Nothing else was altered.

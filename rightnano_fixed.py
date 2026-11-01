
# RIGHTNANO v1 — Hardened Offline Nano Builder for TalaRipper (Windows)
# Fixes Unicode/control-char issues, validates, dedupes, and shards deterministically.

import json
import hashlib
import time
import sys
import glob
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
CELLS_DIR = ROOT / "output_json" / "cells"
BRAIN_JSONL = ROOT / "output_json" / "brain.jsonl"

NANO_DIR = ROOT / "output_json" / "nano"
PROOF_DIR = ROOT / "BOOTSTRAP" / "proof"
MANIFEST_PATH = NANO_DIR / "nano_manifest.json"
REPORT_PATH = PROOF_DIR / "nano_report.json"

MAX_RECORDS_PER_SHARD = 500
MAX_BYTES_PER_SHARD = 1_500_000

def strip_control_chars(s: str) -> str:
    if not isinstance(s, str):
        return s
    out = []
    for ch in s:
        o = ord(ch)
        if ch in ("\n", "\r", "\t"):
            out.append(ch)
        elif (0 <= o < 32) or (o == 127):
            continue
        else:
            out.append(ch)
    return "".join(out)

def deep_sanitize(x):
    if isinstance(x, str):
        return strip_control_chars(x)
    if isinstance(x, list):
        return [deep_sanitize(v) for v in x]
    if isinstance(x, dict):
        return {k: deep_sanitize(v) for k, v in x.items()}
    return x

def sha256_file(path: Path, chunk=1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()

def ensure_dirs():
    NANO_DIR.mkdir(parents=True, exist_ok=True)
    PROOF_DIR.mkdir(parents=True, exist_ok=True)

def iter_chunk_files():
    pats = [
        str(CELLS_DIR / "**" / "*.json"),
        str(CELLS_DIR / "**" / "*.jsonl"),
    ]
    files = []
    for p in pats:
        files.extend(glob.glob(p, recursive=True))
    files = sorted(set(files), key=lambda p: p.lower())
    return [Path(p) for p in files]

def parse_json_any(text: str, src: str):
    text = text.strip()
    if not text:
        return []
    if "\n" in text:
        out = []
        for i, line in enumerate(text.splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception as e:
                raise ValueError(f"JSONL parse error in {src} line {i}: {e}")
        return out
    try:
        return [json.loads(text)]
    except Exception as e:
        raise ValueError(f"JSON parse error in {src}: {e}")

def stable_id_for(rec: dict) -> str:
    cid = rec.get("cell_id")
    if isinstance(cid, str) and cid.strip():
        return cid.strip()
    b = json.dumps(rec, sort_keys=True, ensure_ascii=False).encode("utf-8", errors="replace")
    return "hash::" + hashlib.sha256(b).hexdigest()

def normalize_for_nano(rec: dict, source_hint: str) -> dict:
    if not isinstance(rec, dict):
        rec = {"_value": rec}
    rec = deep_sanitize(rec)

    nano = {}
    nano["id"] = stable_id_for(rec)
    nano["source"] = rec.get("source_name") or rec.get("source_path") or source_hint

    txt = rec.get("text", "")
    if not isinstance(txt, str):
        txt = str(txt)
    txt = strip_control_chars(txt)
    nano["text"] = txt

    nano["meta"] = {
        "source_id": rec.get("source_id"),
        "source_name": rec.get("source_name"),
        "source_path": rec.get("source_path"),
        "index": rec.get("index"),
        "paras_start": rec.get("paras_start"),
        "paras_end": rec.get("paras_end"),
        "created_utc": rec.get("created_utc"),
        "words": rec.get("words"),
    }
    nano["meta"] = {k: v for k, v in nano["meta"].items() if v is not None}
    return nano

def write_shard(shard_index: int, shard_records: list) -> Path:
    name = f"nano_shard_{shard_index:05d}.jsonl"
    path = NANO_DIR / name
    with path.open("w", encoding="utf-8", errors="replace", newline="\n") as f:
        for r in shard_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path

def load_stream():
    if BRAIN_JSONL.exists() and BRAIN_JSONL.stat().st_size > 0:
        def gen():
            with BRAIN_JSONL.open("r", encoding="utf-8", errors="replace") as f:
                for i, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    yield json.loads(line), f"brain.jsonl:line:{i}"
        return gen(), "brain_jsonl"
    else:
        files = iter_chunk_files()
        if not files:
            raise SystemExit(f"No inputs found. Expected cells under: {CELLS_DIR}")
        def gen():
            for fp in files:
                txt = fp.read_text(encoding="utf-8", errors="replace")
                for rec in parse_json_any(txt, str(fp)):
                    yield rec, str(fp)
        return gen(), "cells_dir"

def main():
    ensure_dirs()
    t0 = time.time()
    stream, mode = load_stream()
    seen = set()

    total_in = 0
    total_written = 0
    dupes = 0
    bad = 0
    errors = []

    shard_index = 0
    shard_records = []
    shard_bytes = 0

    manifest = {
        "created_local": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": mode,
        "policy": {
            "sanitize": "drop ASCII control chars except \\n\\r\\t",
            "max_records_per_shard": MAX_RECORDS_PER_SHARD,
            "max_bytes_per_shard": MAX_BYTES_PER_SHARD,
            "dedupe": "cell_id else hash"
        },
        "shards": []
    }

    def flush():
        nonlocal shard_index, shard_records, shard_bytes, total_written
        if not shard_records:
            return
        p = write_shard(shard_index, shard_records)
        h = sha256_file(p)
        size = p.stat().st_size
        manifest["shards"].append({
            "shard": p.name,
            "records": len(shard_records),
            "bytes": size,
            "sha256": h
        })
        total_written += len(shard_records)
        shard_index += 1
        shard_records = []
        shard_bytes = 0

    for rec, src in stream:
        total_in += 1
        try:
            nano = normalize_for_nano(rec, src)
            sid = nano["id"]
            if sid in seen:
                dupes += 1
                continue
            seen.add(sid)

            line = (json.dumps(nano, ensure_ascii=False) + "\n").encode("utf-8", errors="replace")
            if (len(shard_records) >= MAX_RECORDS_PER_SHARD) or (shard_bytes + len(line) > MAX_BYTES_PER_SHARD):
                flush()

            shard_records.append(nano)
            shard_bytes += len(line)

        except Exception as e:
            bad += 1
            errors.append({"source": src, "error": str(e)})
            continue

    flush()

    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False),
                             encoding="utf-8", errors="replace")

    report = {
        "timestamp_local": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": mode,
        "inputs_seen": total_in,
        "records_written": total_written,
        "dupes_skipped": dupes,
        "bad_records": bad,
        "shards_written": len(manifest["shards"]),
        "nano_dir": str(NANO_DIR),
        "nano_manifest": str(MANIFEST_PATH),
        "duration_seconds": round(time.time() - t0, 3),
        "errors_first_25": errors[:25]
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False),
                           encoding="utf-8", errors="replace")

    print("\nRIGHTNANO FIX COMPLETE")
    print(f"Mode:            {mode}")
    print(f"Inputs seen:     {total_in}")
    print(f"Written:         {total_written}")
    print(f"Dupes skipped:   {dupes}")
    print(f"Bad records:     {bad}")
    print(f"Shards:          {len(manifest['shards'])}")
    print(f"Nano dir:        {NANO_DIR}")
    print(f"Manifest:        {MANIFEST_PATH}")
    print(f"Report:          {REPORT_PATH}\n")

if __name__ == "__main__":
    main()

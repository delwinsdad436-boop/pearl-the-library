# RIGHTNANO v2 — TalaRipper Nano Builder (Windows-safe)
#
# What it does:
# - Reads JSON / JSONL cell files under output_json\cells\**\*.json
# - Extracts definition-like records (dicts) into Nano JSONL shards
# - NEVER crashes on bad input: quarantines bad files to bad_json\...
# - Writes: nano_out\nano_XXXXX.jsonl + nano_manifest.json + nano_report.json + rightnano_errors.log
#
# Usage (from C:\Users\delwi\TalaRipper):
#   python rightnano.py
# or:
#   python rightnano.py --cells-dir output_json\cells --out nano_out

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple


def sha256_bytes(b: bytes) -> str:
    h = hashlib.sha256()
    h.update(b)
    return h.hexdigest()


def safe_mkdir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def read_text_forgiving(fp: Path) -> str:
    """Read file as text, trying common encodings."""
    data = fp.read_bytes()
    # UTF-8 BOM
    for enc in ("utf-8-sig", "utf-8", "utf-16", "utf-16-le", "utf-16-be", "cp1252"):
        try:
            return data.decode(enc)
        except Exception:
            continue
    # last resort
    return data.decode("utf-8", errors="replace")


def try_parse_json(text: str) -> Any:
    """Try JSON; if it fails, try JSONL; if that fails, try Python literal."""
    s = text.strip()
    if not s:
        raise ValueError("empty file")

    # 1) Plain JSON
    try:
        return json.loads(s)
    except Exception:
        pass

    # 2) JSON Lines (multiple JSON objects per line)
    objs: List[Any] = []
    ok_lines = 0
    bad_lines = 0
    for line in s.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            objs.append(json.loads(line))
            ok_lines += 1
        except Exception:
            bad_lines += 1
            # keep going; if enough lines parse we still accept
            continue
    if ok_lines > 0 and bad_lines == 0:
        return objs
    if ok_lines > 0 and ok_lines >= max(3, bad_lines * 3):
        # mostly JSONL
        return objs

    # 3) Python literal (e.g., {'a': 1}) — SAFE-ish via literal_eval
    # This salvages files that were written as Python dict repr.
    try:
        return ast.literal_eval(s)
    except Exception as e:
        raise ValueError(f"unparseable (json/jsonl/py-literal): {e}")


def iter_input_files(cells_dir: Path) -> Iterator[Path]:
    # Recursive scan, stable order
    yield from sorted(cells_dir.rglob("*.json"))


def normalize_records(parsed: Any, src: str) -> Iterator[Dict[str, Any]]:
    """Yield dict records from parsed object."""
    if isinstance(parsed, dict):
        yield parsed
        return

    if isinstance(parsed, list):
        for item in parsed:
            if isinstance(item, dict):
                yield item
            else:
                # wrap non-dict values as a record (rare)
                yield {"value": item, "_src": src}
        return

    # scalar -> wrap
    yield {"value": parsed, "_src": src}


def quarantine_file(src_fp: Path, bad_root: Path, cells_root: Path) -> Path:
    """Move bad file into bad_root mirroring relative path from cells_root."""
    try:
        rel = src_fp.relative_to(cells_root)
    except Exception:
        rel = Path(src_fp.name)

    dst_fp = bad_root / rel
    safe_mkdir(dst_fp.parent)

    # If name collision, add suffix
    if dst_fp.exists():
        stem = dst_fp.stem
        suffix = dst_fp.suffix
        dst_fp = dst_fp.with_name(f"{stem}__dup_{int(time.time())}{suffix}")

    shutil.move(str(src_fp), str(dst_fp))
    return dst_fp


def main() -> None:
    ap = argparse.ArgumentParser(description="RIGHTNANO v2 (crash-proof TalaRipper nano builder)")
    ap.add_argument("--cells-dir", default=str(Path("output_json") / "cells"), help="Input cells root")
    ap.add_argument("--out", default=str(Path("nano_out")), help="Output folder")
    ap.add_argument("--shard-size", type=int, default=200, help="Records per shard")
    args = ap.parse_args()

    cells_dir = Path(args.cells_dir).resolve()
    out_dir = Path(args.out).resolve()

    nano_dir = out_dir
    bad_dir = out_dir / "bad_json"
    log_path = out_dir / "rightnano_errors.log"
    manifest_path = out_dir / "nano_manifest.json"
    report_path = out_dir / "nano_report.json"

    safe_mkdir(nano_dir)
    safe_mkdir(bad_dir)

    t0 = time.time()

    # Sharding
    shard_idx = 0
    rec_in_shard = 0
    total_files = 0
    good_files = 0
    bad_files = 0
    total_records = 0
    bad_records = 0
    dupes = 0

    seen_hashes: set[str] = set()

    shard_fp = nano_dir / f"nano_{shard_idx:05d}.jsonl"
    shard_fh = shard_fp.open("w", encoding="utf-8", newline="\n")

    manifest: Dict[str, Any] = {
        "created_local": time.strftime("%Y-%m-%d %H:%M:%S"),
        "cells_dir": str(cells_dir),
        "out_dir": str(out_dir),
        "shard_size": int(args.shard_size),
        "shards": [],
        "quarantine_dir": str(bad_dir),
    }

    def log(msg: str) -> None:
        with log_path.open("a", encoding="utf-8", newline="\n") as lf:
            lf.write(msg.rstrip("\n") + "\n")

    def close_shard() -> None:
        nonlocal shard_fh, shard_fp, rec_in_shard
        shard_fh.flush()
        shard_fh.close()
        manifest["shards"].append({
            "file": shard_fp.name,
            "records": rec_in_shard,
        })

    def open_next_shard() -> None:
        nonlocal shard_idx, shard_fp, shard_fh, rec_in_shard
        shard_idx += 1
        rec_in_shard = 0
        shard_fp = nano_dir / f"nano_{shard_idx:05d}.jsonl"
        shard_fh = shard_fp.open("w", encoding="utf-8", newline="\n")

    if not cells_dir.exists():
        print(f"ERROR: cells-dir not found: {cells_dir}")
        sys.exit(2)

    for fp in iter_input_files(cells_dir):
        total_files += 1
        src = str(fp)
        try:
            text = read_text_forgiving(fp)
            parsed = try_parse_json(text)
        except Exception as e:
            bad_files += 1
            try:
                moved = quarantine_file(fp, bad_dir, cells_dir)
                log(f"BAD_FILE\t{src}\t->\t{moved}\tERROR\t{e}")
            except Exception as e2:
                log(f"BAD_FILE\t{src}\tQUARANTINE_FAILED\t{e}\t{e2}")
            continue

        good_files += 1

        for rec in normalize_records(parsed, src):
            try:
                # create stable hash for de-dupe
                rec_bytes = json.dumps(rec, sort_keys=True, ensure_ascii=False).encode("utf-8", errors="replace")
                h = sha256_bytes(rec_bytes)
                if h in seen_hashes:
                    dupes += 1
                    continue
                seen_hashes.add(h)

                # add minimal metadata
                rec_out = dict(rec)
                rec_out.setdefault("_src", src)
                rec_out.setdefault("_sha256", h)

                shard_fh.write(json.dumps(rec_out, ensure_ascii=False) + "\n")
                rec_in_shard += 1
                total_records += 1

                if rec_in_shard >= int(args.shard_size):
                    close_shard()
                    open_next_shard()

            except Exception as e:
                bad_records += 1
                log(f"BAD_REC\t{src}\tERROR\t{e}")
                continue

    # finalize
    close_shard()

    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8", newline="\n")

    report = {
        "created_local": time.strftime("%Y-%m-%d %H:%M:%S"),
        "duration_seconds": round(time.time() - t0, 3),
        "cells_dir": str(cells_dir),
        "out_dir": str(out_dir),
        "files_total": total_files,
        "files_good": good_files,
        "files_bad_quarantined": bad_files,
        "records_written": total_records,
        "records_bad": bad_records,
        "dupes_skipped": dupes,
        "shards_written": len(manifest.get("shards", [])),
        "nano_dir": str(nano_dir),
        "manifest": str(manifest_path),
        "log": str(log_path),
        "quarantine": str(bad_dir),
    }

    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8", newline="\n")

    print("\nRIGHTNANO v2 COMPLETE")
    print(f"Cells:           {cells_dir}")
    print(f"Out:             {out_dir}")
    print(f"Files total:     {total_files}")
    print(f"Good files:      {good_files}")
    print(f"Bad quarantined: {bad_files}")
    print(f"Records written: {total_records}")
    print(f"Dupes skipped:   {dupes}")
    print(f"Bad records:     {bad_records}")
    print(f"Shards:          {len(manifest.get('shards', []))}")
    print(f"Manifest:        {manifest_path}")
    print(f"Log:             {log_path}\n")


if __name__ == "__main__":
    main()

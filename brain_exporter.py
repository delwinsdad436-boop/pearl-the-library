
import sqlite3, json, hashlib
from pathlib import Path
from datetime import datetime

DB_PATH = "brain_index.sqlite"
OUT_DIR = Path("exports")
RECON_DIR = OUT_DIR / "reconstructed"
CHUNKS_DIR = OUT_DIR / "chunks_jsonl"
MANIFEST = OUT_DIR / "manifest.json"

def sha256_text(s: str) -> str:
    h = hashlib.sha256()
    h.update(s.encode("utf-8", errors="ignore"))
    return h.hexdigest()

def main():
    OUT_DIR.mkdir(exist_ok=True)
    RECON_DIR.mkdir(parents=True, exist_ok=True)
    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='brain';")
    if not cur.fetchone():
        raise SystemExit("ERROR: brain table not found in DB.")

    cur.execute("SELECT COUNT(*) FROM brain;")
    total = cur.fetchone()[0]
    print(f"[export] total brain records: {total}")

    cur.execute("SELECT DISTINCT source_file FROM brain ORDER BY source_file;")
    sources = [r[0] for r in cur.fetchall() if r and r[0]]

    manifest = {
        "db": DB_PATH,
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "total_records": total,
        "sources": []
    }

    for src in sources:
        cur.execute(
            "SELECT record_index, content FROM brain WHERE source_file=? ORDER BY record_index ASC;",
            (src,)
        )
        rows = cur.fetchall()

        stitched = "".join((c or "") for _, c in rows)
        recon_path = RECON_DIR / (Path(src).stem + "__RECON.txt")
        recon_path.write_text(stitched, encoding="utf-8", errors="ignore")

        chunks_path = CHUNKS_DIR / (Path(src).stem + "__chunks.jsonl")
        with chunks_path.open("w", encoding="utf-8", errors="ignore") as f:
            for ri, content in rows:
                rec = {"source_file": src, "record_index": int(ri), "content": content or ""}
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

        entry = {
            "source_file": src,
            "records": len(rows),
            "reconstructed_file": str(recon_path),
            "chunks_file": str(chunks_path),
            "sha256": sha256_text(stitched)
        }
        manifest["sources"].append(entry)
        print(f"[export] {src}: {len(rows)} records")

    MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    con.close()
    print("[export] DONE")

if __name__ == "__main__":
    main()

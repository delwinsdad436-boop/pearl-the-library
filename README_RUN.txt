Canon Former (PATCHED)

What changed:
- Defaults now match your DB: table=brain, id_col=id, text_col=content
- Auto-detects whether a created timestamp column exists (created_utc/created_at/created) and orders by it if present.

Run:
  cd /d "C:\Users\delwi\TalaRipper"
  python canon_former.py --db brain_index.sqlite --out canon_out --threshold 0.82

It will create canon_out/canon_manifest.json and canon_out/members.jsonl

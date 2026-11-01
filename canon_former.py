#!/usr/bin/env python3
"""Tala Stage G — Autonomous Canon Formation (Hybrid scoring)

Builds stable, queryable "canon clusters" from brain_index.sqlite without deleting anything.

INPUT:
  - brain_index.sqlite (must contain a table 'brain' with at least: id, content)
    If your schema differs, use --table/--id-col/--text-col.

OUTPUT (default folder: canon_out):
  - canon_clusters.jsonl   (one cluster per line)
  - canon_manifest.json    (run metadata + settings)
  - canon_index.sqlite     (clusters + members, queryable)
  - canon_report.txt       (human-readable summary)

Hybrid score = weighted blend of:
  (1) frequency/size
  (2) temporal persistence (if created_utc exists)
  (3) cross-domain consistency (token overlap stability)
  (4) source diversity (if source_id or source_name exists)

This is *soft* canon: it never deletes; it only groups and scores.
"""

import argparse, os, json, time, math, re, sqlite3, hashlib
from collections import defaultdict

WORD_RE = re.compile(r"[A-Za-z0-9']+")

def norm_tokens(text: str):
    if not text:
        return []
    t = text.lower()
    toks = WORD_RE.findall(t)
    stop = {"the","and","to","of","a","in","is","it","for","on","that","with","as","be","by","or","an","are","at","from","this","was"}
    return [w for w in toks if w not in stop and len(w) > 1]

def sim_jaccard(a, b):
    if not a or not b:
        return 0.0
    sa, sb = set(a), set(b)
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0

def sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8", "ignore")).hexdigest()

def connect(db_path):
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    return con

def detect_cols(con, table):
    cols = [r["name"] for r in con.execute(f"PRAGMA table_info({table})")]
    return set(cols)

def fetch_rows(con, table, id_col, text_col, extra_cols):
    cols = [id_col, text_col] + [c for c in extra_cols if c]
    q = f"SELECT {', '.join(cols)} FROM {table}"
    for row in con.execute(q):
        yield row

def ensure_outdir(p):
    os.makedirs(p, exist_ok=True)

def make_canon_sqlite(path):
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS clusters (cluster_id TEXT PRIMARY KEY, score REAL, size INTEGER, rep_cell_id TEXT, rep_preview TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS members (cluster_id TEXT, cell_id TEXT)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_members_cluster ON members(cluster_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_members_cell ON members(cell_id)")
    con.commit()
    return con

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="brain_index.sqlite")
    ap.add_argument("--table", default="brain")
    ap.add_argument("--id-col", default="id")
    ap.add_argument("--text-col", default="content")
    ap.add_argument("--created-col", default="created_utc")
    ap.add_argument("--source-col", default="source")
    ap.add_argument("--source-name-col", default="source_name")
    ap.add_argument("--out", default="canon_out")
    ap.add_argument("--min-tokens", type=int, default=40)
    ap.add_argument("--threshold", type=float, default=0.82)
    ap.add_argument("--max-sample", type=int, default=60000, help="0 = all")
    ap.add_argument("--progress-every", type=int, default=2000)
    ap.add_argument("--w-freq", type=float, default=0.28)
    ap.add_argument("--w-time", type=float, default=0.24)
    ap.add_argument("--w-cons", type=float, default=0.28)
    ap.add_argument("--w-div",  type=float, default=0.20)
    args = ap.parse_args()

    ensure_outdir(args.out)

    con = connect(args.db)
    cols = detect_cols(con, args.table)

    created_col = args.created_col if args.created_col in cols else None
    source_col = args.source_col if args.source_col in cols else None
    source_name_col = args.source_name_col if args.source_name_col in cols else None

    extra = []
    if created_col: extra.append(created_col)
    if source_col: extra.append(source_col)
    if source_name_col: extra.append(source_name_col)

    rows = []
    t0 = time.time()
    scanned = 0
    for scanned, r in enumerate(fetch_rows(con, args.table, args.id_col, args.text_col, extra), start=1):
        if args.max_sample and scanned > args.max_sample:
            break
        text = r[args.text_col] if r[args.text_col] is not None else ""
        toks = norm_tokens(text)
        if len(toks) < args.min_tokens:
            continue
        item = {
            "cell_id": str(r[args.id_col]),
            "text": text,
            "tokens": toks,
            "created_utc": int(r[created_col]) if created_col and r[created_col] is not None else None,
            "source": (str(r[source_col]) if source_col and r[source_col] is not None else None) or (str(r[source_name_col]) if source_name_col and r[source_name_col] is not None else None),
        }
        rows.append(item)
        if scanned % args.progress_every == 0:
            print(f"[load] scanned={scanned:,} kept={len(rows):,} elapsed={time.time()-t0:.1f}s")
    print(f"[load] done scanned~{scanned:,} kept={len(rows):,}")

    if not rows:
        raise SystemExit("No rows kept. Lower --min-tokens or check table/columns.")

    clusters = []
    rep_tokens = []
    rep_sources = []
    rep_times = []
    assignment = [-1] * len(rows)

    for idx, item in enumerate(rows):
        best = -1
        best_sim = 0.0
        for cidx, rt in enumerate(rep_tokens):
            s = sim_jaccard(item["tokens"], rt)
            if s > best_sim:
                best_sim = s
                best = cidx
        if best_sim >= args.threshold and best >= 0:
            assignment[idx] = best
        else:
            assignment[idx] = len(clusters)
            clusters.append([])
            rep_tokens.append(item["tokens"])
            rep_sources.append(set())
            rep_times.append([])
        clusters[assignment[idx]].append(idx)
        if item["source"]:
            rep_sources[assignment[idx]].add(item["source"])
        if item["created_utc"]:
            rep_times[assignment[idx]].append(item["created_utc"])
        if (idx+1) % args.progress_every == 0:
            print(f"[cluster] processed={idx+1:,} clusters={len(clusters):,}")

    max_size = max(len(c) for c in clusters) if clusters else 1
    all_times = [t for ts in rep_times for t in ts if t]
    t_min = min(all_times) if all_times else None
    t_max = max(all_times) if all_times else None

    def time_score(ts):
        if not ts or t_min is None or t_max is None or t_max == t_min:
            return 0.5
        span = max(ts) - min(ts)
        return min(1.0, span / max(1, (t_max - t_min)))

    def consistency_score(cidx):
        inds = clusters[cidx]
        if len(inds) <= 1:
            return 0.6
        sample = inds[: min(20, len(inds))]
        rt = rep_tokens[cidx]
        sims = [sim_jaccard(rows[i]["tokens"], rt) for i in sample]
        return sum(sims) / len(sims) if sims else 0.6

    def diversity_score(cidx):
        s = len(rep_sources[cidx]) if rep_sources[cidx] else 0
        return 1.0 - math.exp(-s/3.0)

    out_jsonl = os.path.join(args.out, "canon_clusters.jsonl")
    out_manifest = os.path.join(args.out, "canon_manifest.json")
    out_report = os.path.join(args.out, "canon_report.txt")
    out_sqlite = os.path.join(args.out, "canon_index.sqlite")

    con_canon = make_canon_sqlite(out_sqlite)
    curc = con_canon.cursor()

    scored = []
    with open(out_jsonl, "w", encoding="utf-8") as f:
        for cidx, inds in enumerate(clusters):
            size = len(inds)
            freq = size / max_size
            tsc = time_score(rep_times[cidx])
            csc = consistency_score(cidx)
            dsc = diversity_score(cidx)
            score = (args.w_freq*freq) + (args.w_time*tsc) + (args.w_cons*csc) + (args.w_div*dsc)

            rep_i = inds[0]
            rep = rows[rep_i]
            preview = (rep["text"][:220].replace("\n"," ").strip())
            cluster_id = f"canon_{cidx:06d}_{sha1(rep['cell_id'])[:10]}"

            record = {
                "cluster_id": cluster_id,
                "score": round(score, 6),
                "size": size,
                "rep_cell_id": rep["cell_id"],
                "rep_preview": preview,
                "sources": sorted(list(rep_sources[cidx]))[:25],
                "members": [rows[i]["cell_id"] for i in inds],
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            scored.append((score, size, cluster_id, rep["cell_id"], preview))

            curc.execute("INSERT OR REPLACE INTO clusters(cluster_id, score, size, rep_cell_id, rep_preview) VALUES (?,?,?,?,?)",
                         (cluster_id, float(score), int(size), rep["cell_id"], preview))
            curc.executemany("INSERT INTO members(cluster_id, cell_id) VALUES (?,?)",
                             [(cluster_id, rows[i]["cell_id"]) for i in inds])
            if (cidx+1) % 500 == 0:
                con_canon.commit()
                print(f"[write] clusters_written={cidx+1:,}")

    con_canon.commit()

    scored.sort(reverse=True, key=lambda x: x[0])
    top = scored[:20]
    with open(out_report, "w", encoding="utf-8") as r:
        r.write("Tala Stage G — Autonomous Canon Formation (Hybrid)\n")
        r.write(f"db={args.db}\nkept_rows={len(rows)}\nclusters={len(clusters)}\nthreshold={args.threshold}\n")
        r.write(f"weights: freq={args.w_freq} time={args.w_time} cons={args.w_cons} div={args.w_div}\n\n")
        r.write("Top clusters by score:\n")
        for s, sz, cid, repid, prev in top:
            r.write(f"- score={s:.4f} size={sz} id={cid} rep={repid}\n  {prev}\n")

    manifest = {
        "stage": "G",
        "created_utc": int(time.time()),
        "inputs": {"db": args.db, "table": args.table},
        "outputs": {
            "canon_clusters_jsonl": out_jsonl,
            "canon_manifest_json": out_manifest,
            "canon_index_sqlite": out_sqlite,
            "canon_report_txt": out_report
        },
        "settings": {
            "threshold": args.threshold,
            "min_tokens": args.min_tokens,
            "weights": {"freq": args.w_freq, "time": args.w_time, "cons": args.w_cons, "div": args.w_div}
        }
    }
    with open(out_manifest, "w", encoding="utf-8") as mf:
        json.dump(manifest, mf, ensure_ascii=False, indent=2)

    print(f"[done] wrote -> {args.out}")

if __name__ == "__main__":
    main()

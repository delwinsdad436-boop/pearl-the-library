#!/usr/bin/env python3
import argparse, json, statistics
from collections import defaultdict, Counter


def iter_plan(path):
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def uf_make():
    parent = {}
    size = {}

    def find(x):
        parent.setdefault(x, x)
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        sa, sb = size.get(ra, 1), size.get(rb, 1)
        if sa < sb:
            ra, rb = rb, ra
        parent[rb] = ra
        size[ra] = sa + sb

    return find, union, parent


def main():
    ap = argparse.ArgumentParser(description="Inspect merge_plan.jsonl (NO DB CHANGES).")
    ap.add_argument("--plan", default="merge_plan.jsonl", help="Path to merge_plan.jsonl")
    ap.add_argument("--top", type=int, default=30, help="Show top N highest-score pairs")
    args = ap.parse_args()

    scores = []
    pairs = 0
    find, union, parent = uf_make()
    deg = Counter()

    for rec in iter_plan(args.plan):
        a = rec.get("a_id")
        b = rec.get("b_id")
        s = float(rec.get("score", 0.0))
        pairs += 1
        scores.append(s)
        union(a, b)
        deg[a] += 1
        deg[b] += 1

    if pairs == 0:
        print("Plan is empty.")
        return

    scores_sorted = sorted(scores)

    def pct(p):
        i = int(p * (len(scores_sorted) - 1))
        return scores_sorted[i]

    clusters = defaultdict(list)
    for node in parent.keys():
        clusters[find(node)].append(node)
    cluster_sizes = sorted((len(v) for v in clusters.values()), reverse=True)

    print("MERGE PLAN INSPECT")
    print("==================")
    print(f"Pairs: {pairs}")
    print(f"Unique nodes involved: {len(parent)}")
    print(f"Clusters: {len(clusters)}")
    print("")
    print("Score stats")
    print("-----------")
    print(f"min: {min(scores):.6f}")
    print(f"p50: {pct(0.50):.6f}")
    print(f"p90: {pct(0.90):.6f}")
    print(f"p95: {pct(0.95):.6f}")
    print(f"p99: {pct(0.99):.6f}")
    print(f"max: {max(scores):.6f}")
    print(f"mean: {statistics.mean(scores):.6f}")
    print("")
    print("Cluster sizes (top 20)")
    print("----------------------")
    for i, cs in enumerate(cluster_sizes[:20], start=1):
        print(f"{i:>2}. size={cs}")

    print("")
    print("Most-connected nodes (top 20)")
    print("-----------------------------")
    for node, c in deg.most_common(20):
        print(f"id={node} degree={c}")

    print("")
    print(f"Top {args.top} pairs by score")
    print("-----------------------------")
    top = []
    for rec in iter_plan(args.plan):
        s = float(rec.get("score", 0.0))
        top.append((s, rec))
    top.sort(key=lambda x: x[0], reverse=True)
    for s, rec in top[: args.top]:
        a = rec.get("a_id")
        b = rec.get("b_id")
        al = rec.get("a_len")
        bl = rec.get("b_len")
        print(f"score={s:.6f}  a_id={a} (len={al})  b_id={b} (len={bl})")


if __name__ == "__main__":
    main()

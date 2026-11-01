#!/usr/bin/env python3
import argparse, sqlite3, json, os, shutil, datetime


def now_ts():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def export_jsonl(db_path, out_path):
    c = sqlite3.connect(db_path)
    cur = c.execute(
        "SELECT id, record_index, source_file, content FROM v_brain_canon ORDER BY id"
    )
    n = 0
    with open(out_path, "w", encoding="utf-8") as f:
        for row in cur:
            obj = {
                "id": row[0],
                "record_index": row[1],
                "source_file": row[2],
                "content": row[3],
            }
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
            n += 1
    c.close()
    print(f"Wrote {n} records -> {out_path}")


def export_sqlite(db_path, out_path):
    if os.path.exists(out_path):
        shutil.copy2(out_path, out_path + f".bak_{now_ts()}")
        os.remove(out_path)

    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(out_path)

    dst.execute(
        """
    CREATE TABLE brain_canon(
        id INTEGER PRIMARY KEY,
        record_index INTEGER,
        source_file TEXT,
        content TEXT
    )
    """
    )

    cur = src.execute(
        "SELECT id, record_index, source_file, content FROM v_brain_canon ORDER BY id"
    )
    n = 0
    dst.execute("BEGIN")
    for row in cur:
        dst.execute(
            "INSERT INTO brain_canon(id,record_index,source_file,content) VALUES(?,?,?,?)",
            row,
        )
        n += 1
        if n % 1000 == 0:
            dst.commit()
            dst.execute("BEGIN")
    dst.commit()

    src.close()
    dst.close()
    print(f"Wrote {n} records -> {out_path}")


def main():
    ap = argparse.ArgumentParser(description="Export canonical records after guarded_apply.")
    ap.add_argument("--db", default="brain_index.sqlite")
    ap.add_argument("--out", default="canon.jsonl", help="Output path (.jsonl or .sqlite)")
    args = ap.parse_args()

    if args.out.lower().endswith(".sqlite") or args.out.lower().endswith(".db"):
        export_sqlite(args.db, args.out)
    else:
        export_jsonl(args.db, args.out)


if __name__ == "__main__":
    main()

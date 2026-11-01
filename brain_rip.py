import os
import sqlite3
import json

DB = "brain_index.sqlite"
INPUT = "input_texts" # put ripped OCR text files here


def init_db():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS brain (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT
        )
    """)
    conn.commit()
    conn.close()


def ingest():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    for file in os.listdir(INPUT):
        if file.endswith(".txt"):
            path = os.path.join(INPUT, file)
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()

            cell = {
                "source": file,
                "text": text
            }

            cur.execute("INSERT INTO brain (content) VALUES (?)",
                        (json.dumps(cell),))

            print(f"Ingested: {file}")

    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    ingest()
    print("BRAIN RIP COMPLETE.")
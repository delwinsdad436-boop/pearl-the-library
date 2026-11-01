# TALA searchable brain — clean sentence answers from SQLite index

import sqlite3
import re
import json

DB = "brain_index.sqlite"


# ---------------- NORMALIZATION ----------------

def normalize(text):
    text = text.replace("\\n", " ")

    # Fix PDF hyphen line wraps: disintegra- tion → disintegration
    text = re.sub(r"-\s+", "", text)

    # Fix broken word splits from line wraps: "a tion" → "ation"
    text = re.sub(r"\b([a-z])\s+([a-z]{2,})\b", r"\1\2", text)

    # Remove smart quotes
    text = text.replace("’", "")
    text = text.replace("‘", "")
    text = text.replace("“", "")
    text = text.replace("”", "")

    # Collapse whitespace
    text = re.sub(r"\s+", " ", text)

    return text.strip()


# ---------------- TOKENIZER ----------------

def tokens(t):
    return re.findall(r"\w+", t.lower())


# ---------------- CLEAN JSON CELL ----------------

def extract_text(raw):
    try:
        obj = json.loads(raw)
        return normalize(obj.get("text", ""))
    except:
        return normalize(raw)


# ---------------- SEARCH DB ----------------

def search(query):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("SELECT content FROM brain")
    rows = cur.fetchall()
    conn.close()

    qt = tokens(query)
    hits = []

    for (raw,) in rows:
        text = extract_text(raw)
        score = sum(text.lower().count(w) for w in qt)
        if score:
            hits.append((score, text))

    hits.sort(reverse=True)
    return [t for _, t in hits[:8]]


# ---------------- BUILD CLEAN ANSWER ----------------

def build_answer(query):
    qt = set(tokens(query))
    sentences = []

    for block in search(query):
        for s in re.split(r'(?<=[.!?])\s+', block):
            s_clean = normalize(s)
            if any(w in s_clean.lower() for w in qt):
                sentences.append(s_clean)

    # Remove duplicates while preserving order
    seen = set()
    final = []
    for s in sentences:
        if s not in seen:
            seen.add(s)
            final.append(s)

    return " ".join(final[:6]) or "No match found."


# ---------------- INTERACTIVE LOOP ----------------

print("TALA Ready. Type 'exit' to quit.")
while True:
    q = input(">> ")
    if q.lower() == "exit":
        break
    print("\n" + build_answer(q) + "\n")
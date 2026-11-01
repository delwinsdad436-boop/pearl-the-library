#!/usr/bin/env python3
"""brain_ask.py - Ask the TalaRipper brain a question; the local model answers FROM the record.

Run from the TalaRipper folder, with llama-server already running on 127.0.0.1:8080.
Standard library only - nothing to install.

    python brain_ask.py "What is TALA-CORE?"

How it works: keyword-searches the brain table (id, content) of brain_index.sqlite,
takes the best-matching passages, hands them plus the question to the model on
port 8080, and prints the model's answer. The brain_chat.py retriever is untouched.
"""

import json
import sqlite3
import sys
import urllib.request

DB = "brain_index.sqlite"
URL = "http://127.0.0.1:8080/v1/chat/completions"
MODEL = "Qwen3.8-27B-Q3_K_M.gguf"

TOP_K = 4            # passages handed to the model
CHUNK_TRIM = 1000    # characters kept per passage (keeps the 4096 context safe)
MAX_TOKENS = 256     # her answer budget

STOP = {
    "what", "is", "the", "a", "an", "of", "to", "in", "on", "and", "or",
    "who", "how", "why", "does", "do", "are", "was", "were", "it", "its",
    "this", "that", "with", "from", "about", "tell", "me",
}


def search(cur, question):
    words = [w.strip("?.,!;:\"'()").lower() for w in question.split()]
    keys = [w for w in words if w and w not in STOP and len(w) > 2] or words
    scored = {}
    for kw in keys:
        for rid, content in cur.execute(
            "SELECT id, content FROM brain WHERE content LIKE ?", ("%" + kw + "%",)
        ):
            entry = scored.setdefault(rid, [0, content])
            entry[0] += 1
    ranked = sorted(scored.values(), key=lambda v: -v[0])[:TOP_K]
    return [(content or "")[:CHUNK_TRIM] for _, content in ranked]


def ask(question, chunks):
    context = "\n\n---\n\n".join(chunks)
    system = (
        "You are the voice of a personal knowledge brain built by James Cochrum "
        "(the TALA-CORE record). Answer the question using ONLY the brain passages "
        "provided below. If the passages do not hold the answer, say so plainly. "
        "Speak plainly and briefly. Do not invent facts that are not in the passages."
    )
    user = "Brain passages:\n\n" + context + "\n\nQuestion: " + question
    body = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": MAX_TOKENS,
        "temperature": 0.3,
    }
    req = urllib.request.Request(
        URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=3600) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


def main():
    question = " ".join(sys.argv[1:]).strip()
    if not question:
        question = input("Ask the brain: ").strip()
    if not question:
        return
    con = sqlite3.connect(DB)
    chunks = search(con.cursor(), question)
    con.close()
    print("[%d passages pulled from the brain]" % len(chunks))
    if not chunks:
        print("The brain holds nothing on that - no passages matched.")
        return
    print("Thinking (she generates slowly on this machine)...")
    print()
    print(ask(question, chunks))


if __name__ == "__main__":
    main()

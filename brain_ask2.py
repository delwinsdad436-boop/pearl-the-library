#!/usr/bin/env python3
"""brain_ask2.py - v2 of brain_ask (new file per the alteration rule; v1 untouched).

Ask the TalaRipper brain a question; the local model answers FROM the record.
Run from the TalaRipper folder, with llama-server running on 127.0.0.1:8080.
Standard library only.

    python brain_ask2.py "What is disenchantment?"

What v2 fixes, from v1's measured failure (2026-10-31 ~21:01): v1 returned a
BLANK answer - the model's whole 256-token budget was eaten by its reasoning
block, so the final content came back empty and v1 printed nothing.
v2: (1) appends the /no_think switch so she answers directly, (2) doubles the
token budget, (3) NEVER prints a silent blank - whatever she returns (final
answer, bare reasoning, or nothing) is printed and labeled, with finish_reason.
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
MAX_TOKENS = 512     # her answer budget (v1's 256 was eaten by reasoning)

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
    user = "Brain passages:\n\n" + context + "\n\nQuestion: " + question + "\n\n/no_think"
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
    choice = data["choices"][0]
    message = choice.get("message", {})
    return (
        (message.get("content") or "").strip(),
        (message.get("reasoning_content") or "").strip(),
        choice.get("finish_reason", "?"),
    )


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
    print("Asking her (prompt ingest plus a slow generation - minutes)...")
    print()
    content, reasoning, finish = ask(question, chunks)
    if content:
        print(content)
    elif reasoning:
        print("[She returned thinking but no final answer - finish_reason: %s]" % finish)
        print(reasoning)
    else:
        print("[She returned nothing at all - finish_reason: %s. "
              "That is a report, not a blank: the wire answered, the seat was empty.]" % finish)


if __name__ == "__main__":
    main()

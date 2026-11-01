#!/usr/bin/env python3
"""extract_brain.py - unpack the brain from its transport zip.

The brain (brain_index.sqlite, 36,454,400 bytes) ships in this repo as
brain_index.sqlite.zip (about 11 MB) because the raw file exceeds the
file-size limits of the route it was published through. The file inside
is byte-identical to the original brain; this script extracts it and
proves that by SHA-256 before anything else touches it.

    python3 extract_brain.py

Safe to re-run: if brain_index.sqlite is already present and its hash
matches, it does nothing. In GitHub Codespaces this runs automatically
as part of the devcontainer setup. Standard library only.
"""

import hashlib
import os
import sys
import zipfile

ZIP_NAME = "brain_index.sqlite.zip"
DB_NAME = "brain_index.sqlite"
EXPECTED_SIZE = 36454400
EXPECTED_SHA256 = "9204ab28cc9d50cfd1b2f233cb098615f259d67a7942cf97009b07d18823fb05"


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(here, DB_NAME)
    zip_path = os.path.join(here, ZIP_NAME)

    if os.path.exists(db_path):
        if os.path.getsize(db_path) == EXPECTED_SIZE and sha256_of(db_path) == EXPECTED_SHA256:
            print("brain already extracted and verified (sha256 match):", DB_NAME)
            return 0
        print("existing", DB_NAME, "does not match the expected hash - re-extracting")

    if not os.path.exists(zip_path):
        print("ERROR:", ZIP_NAME, "not found beside this script")
        return 1

    with zipfile.ZipFile(zip_path) as z:
        z.extract(DB_NAME, here)

    size = os.path.getsize(db_path)
    digest = sha256_of(db_path)
    if size != EXPECTED_SIZE or digest != EXPECTED_SHA256:
        print("ERROR: extracted brain failed verification")
        print("  size:  ", size, "(expected", EXPECTED_SIZE, ")")
        print("  sha256:", digest)
        print("  wanted:", EXPECTED_SHA256)
        return 1

    print("brain extracted and verified:", DB_NAME, size, "bytes, sha256 match")
    return 0


if __name__ == "__main__":
    sys.exit(main())

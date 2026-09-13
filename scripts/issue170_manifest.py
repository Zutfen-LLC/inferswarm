#!/usr/bin/env python3
"""Build the Issue #170 producer-hashes record and evidence MANIFEST.

producer-hashes.json: sha256 of every Issue #170 producer/reducer
script, captured from the committed bytes at build time.
MANIFEST.sha256: sha256 over every retained evidence file.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / (
    "docs/implementation/r6-successor-arm-c-long-remainder-corpus-170/"
    "evidence")

PRODUCERS = [
    "scripts/issue170_corpus_methodology.py",
    "scripts/issue170_corpus_producer.py",
    "scripts/issue170_authority_record.py",
    "scripts/issue170_terminal_reduction.py",
    "scripts/issue170_manifest.py",
    "tests/test_issue170_long_remainder_corpus.py",
]

hashes = {}
for rel in PRODUCERS:
    path = ROOT / rel
    if not path.exists():
        continue  # tests file may not exist yet on first build
    hashes[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
(EVIDENCE / "producer-hashes.json").write_text(
    json.dumps({"schema": "inferswarm.issue170.producer-hashes/1",
                "producers": hashes}, indent=1, sort_keys=True) + "\n")

rows = []
for path in sorted(EVIDENCE.rglob("*")):
    if path.is_file() and path.name != "MANIFEST.sha256":
        rows.append((hashlib.sha256(path.read_bytes()).hexdigest(),
                     path.relative_to(ROOT)))
lines = [f"{digest}  {path}" for digest, path in rows]
(EVIDENCE / "MANIFEST.sha256").write_text("\n".join(lines) + "\n")
print("\n".join(lines))

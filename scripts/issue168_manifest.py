#!/usr/bin/env python3
"""Build docs/implementation/r6-successor-arm-c-requal-blocked-168/evidence/MANIFEST.sha256."""
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / ("docs/implementation/"
                   "r6-successor-arm-c-requal-blocked-168/evidence")
rows = []
for path in sorted(EVIDENCE.rglob("*")):
    if path.is_file() and path.name != "MANIFEST.sha256":
        rows.append((hashlib.sha256(path.read_bytes()).hexdigest(),
                     path.relative_to(ROOT)))
lines = [f"{digest}  {path}" for digest, path in rows]
(EVIDENCE / "MANIFEST.sha256").write_text("\n".join(lines) + "\n")
print("\n".join(lines))

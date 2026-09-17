#!/usr/bin/env python3
"""Issue #216 — V2-D additive evidence manifest generator."""
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AREA = ROOT / "docs/investigations/vulkan-v2-d-v340l-concurrent"
rows = []
for path in sorted(AREA.rglob("*")):
    if path.is_file() and path.name != "MANIFEST.sha256":
        rows.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(ROOT).as_posix()}")
(AREA / "MANIFEST.sha256").write_text("\n".join(rows) + "\n", encoding="utf-8")
print(f"{len(rows)} rows -> {AREA / 'MANIFEST.sha256'}")

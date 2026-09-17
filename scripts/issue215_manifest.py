#!/usr/bin/env python3
"""Issue #215 — V2-C evidence manifest generator (repo-relative rows)."""
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NS = "vulkan-v2-c-v340l-platform-stability"
AREA = ROOT / "docs/investigations" / NS

rows = []
for path in sorted(AREA.rglob("*")):
    if path.is_file() and path.name != "MANIFEST.sha256":
        rel = path.relative_to(ROOT).as_posix()
        rows.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {rel}")

out = AREA / "MANIFEST.sha256"
out.write_text("\n".join(rows) + "\n", encoding="utf-8")
print(f"{len(rows)} rows -> {out}")

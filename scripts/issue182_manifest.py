#!/usr/bin/env python3
"""Issue #182 — Arm-E evidence manifest builder (CPU-only, stdlib)."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue182_campaign_pins as P  # noqa: E402


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    root = P.EVIDENCE_DIR
    entries = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "MANIFEST.sha256":
            entries[path.relative_to(P.ROOT).as_posix()] = sha256_file(path)
    manifest = root / "MANIFEST.sha256"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        "".join(f"{digest}  {name}\n"
                for name, digest in sorted(entries.items())))
    print(json.dumps({"manifest": str(manifest), "files": len(entries)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

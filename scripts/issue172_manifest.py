#!/usr/bin/env python3
"""Issue #172 — evidence manifest builder (sha256 sidecars + MANIFEST)."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue172_campaign_pins as P  # noqa: E402


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
    lines = [
        f"{digest}  {rel}" for rel, digest in entries.items()]
    (root / "MANIFEST.sha256").write_text("\n".join(lines) + "\n")
    print(json.dumps({"manifest": str(root / "MANIFEST.sha256"),
                      "files": len(entries)}))
    return 0


import json  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())

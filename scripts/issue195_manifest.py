#!/usr/bin/env python3
"""Issue #195 R8-D evidence manifest builder (CPU-only, stdlib)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AREA = ROOT / "docs" / "investigations" / "qwen38-flash-next-r8-d"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    entries = {}
    for path in sorted(AREA.rglob("*")):
        if path.is_file() and path.name not in ("MANIFEST.sha256",
                                                "producer-hashes.json"):
            entries[path.relative_to(ROOT).as_posix()] = sha256_file(path)
    manifest = AREA / "MANIFEST.sha256"
    manifest.write_text(
        "".join(f"{digest}  {name}\n"
                for name, digest in sorted(entries.items())))
    print(json.dumps({"manifest": str(manifest), "files": len(entries)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

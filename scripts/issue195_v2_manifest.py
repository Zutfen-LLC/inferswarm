#!/usr/bin/env python3
"""Issue #195 R8-D v2: evidence manifest builder (CPU-only, stdlib).

Covers the v2 evidence namespace. The v1 MANIFEST.sha256 at the area
root stays byte-frozen (it covers the superseded v1 bytes); this v2
manifest lives at v2/MANIFEST.sha256 and covers all v2 bytes.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
V2 = ROOT / "docs/investigations/qwen38-flash-next-r8-d-v2"


def sha256_file(path: Path) -> str:
    d = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            d.update(chunk)
    return d.hexdigest()


def main() -> int:
    entries = {}
    for path in sorted(V2.rglob("*")):
        if path.is_file() and path.name not in ("MANIFEST.sha256",
                                                "producer-hashes.json"):
            entries[path.relative_to(ROOT).as_posix()] = sha256_file(path)
    (V2 / "MANIFEST.sha256").write_text(
        "".join(f"{digest}  {name}\n"
                for name, digest in sorted(entries.items())))
    print(json.dumps({"manifest": str(V2 / "MANIFEST.sha256"),
                      "files": len(entries)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

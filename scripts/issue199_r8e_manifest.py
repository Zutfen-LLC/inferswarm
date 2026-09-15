#!/usr/bin/env python3
"""Issue #199 R8-E: evidence manifest builder + producer-pin writer
(CPU-only, stdlib).

MANIFEST.sha256 covers every file under the R8-E namespace except the
manifest itself and producer-hashes.json (manifest self-reference is
unsatisfiable). producer-hashes.json pins the R8-E producer set.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
import sys  # noqa: E402
sys.path.insert(0, str(ROOT / "scripts"))
from issue199_r8e_authority import R8E_DIR, R8E_PRODUCERS  # noqa: E402

AREA = ROOT / R8E_DIR


def sha256_file(path: Path) -> str:
    d = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            d.update(chunk)
    return d.hexdigest()


def main() -> int:
    # producer pins
    pins = {}
    for rel in R8E_PRODUCERS:
        pins[rel] = sha256_file(ROOT / rel)
    (AREA / "producer-hashes.json").write_text(
        json.dumps(pins, indent=2, sort_keys=True) + "\n")
    # manifest
    entries = {}
    for path in sorted(AREA.rglob("*")):
        if path.is_file() and path.name not in ("MANIFEST.sha256",
                                                "producer-hashes.json"):
            entries[path.relative_to(ROOT).as_posix()] = sha256_file(path)
    (AREA / "MANIFEST.sha256").write_text(
        "".join(f"{digest}  {name}\n"
                for name, digest in sorted(entries.items())))
    print(json.dumps({"manifest": str(AREA / "MANIFEST.sha256"),
                      "files": len(entries),
                      "producers": len(pins)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

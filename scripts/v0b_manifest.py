#!/usr/bin/env python3
"""Generate/verify the V0-B bundle evidence manifest (lifecycle v2).

Bundle-local, immutable, repository-root-relative, self-excluding:
hashes every retained evidence/producer file of
docs/investigations/vulkan-v0-b/ and the V0-B producers under scripts/,
exactly once, after generation is complete. Excludes living repository
state and this manifest itself. Mirrors the accepted lifecycle enforced
by tests/test_evidence_manifest_lifecycle.py.

    python3 scripts/v0b_manifest.py --write
    python3 scripts/v0b_manifest.py --check
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BUNDLE = REPO / "docs/investigations/vulkan-v0-b"
MANIFEST = BUNDLE / "MANIFEST.sha256"

EXCLUDE_NAMES = {"MANIFEST.sha256"}
EXCLUDE_SUFFIXES = ()
LIVING_MARKERS = ("project-status", "ROADMAP", "workflows")

PRODUCERS = [
    "scripts/v0b_comparability_audit.py",
    "scripts/v0b_correctness_stability.py",
    "scripts/v0b_economics.py",
    "scripts/v0b_capability_assessment.py",
    "scripts/v0b_seam_comparison.py",
    "scripts/v0b_terminal.py",
    "scripts/v0b_cpu_supplement_run.py",
    "scripts/v0b_cpu_supplement_derive.py",
]
TESTS = ["tests/test_v0b_reduction.py"]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def bundle_files() -> list[Path]:
    files = sorted(
        p for p in BUNDLE.rglob("*")
        if p.is_file() and p.name not in EXCLUDE_NAMES
        and not any(p.name.endswith(s) for s in EXCLUDE_SUFFIXES))
    for rel in PRODUCERS + TESTS:
        p = REPO / rel
        if p.exists():
            files.append(p)
    return files


def rows() -> list[tuple[str, str]]:
    out = []
    seen = set()
    for p in bundle_files():
        rel = p.relative_to(REPO).as_posix()
        if rel in seen:
            raise SystemExit(f"duplicate manifest row: {rel}")
        seen.add(rel)
        for marker in LIVING_MARKERS:
            if marker in rel:
                raise SystemExit(f"living file must not be in a manifest: {rel}")
        out.append((sha256(p), rel))
    return out


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in ("--write", "--check"):
        print(__doc__)
        return 2
    check = sys.argv[1] == "--check"
    current = "".join(f"{d}  {r}\n" for d, r in rows())
    if check:
        if not MANIFEST.exists():
            print("FAIL: manifest missing")
            return 1
        if MANIFEST.read_text() != current:
            print("FAIL: manifest drift — regenerate with --write")
            return 1
        print(f"OK: {MANIFEST.relative_to(REPO)} current ({current.count(chr(10))} rows)")
        return 0
    MANIFEST.write_text(current)
    print(f"wrote {MANIFEST.relative_to(REPO)} ({current.count(chr(10))} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

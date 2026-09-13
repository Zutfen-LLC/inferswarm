#!/usr/bin/env python3
"""Build or verify the bundle-local Issue #153 remediation manifest.

Same shape as the #137 bundle manifest: an immutable integrity index
whose inputs never depend on its own bytes.  Living repository documents
and CI configuration stay outside the evidence bundle (enforced by
tests/test_evidence_manifest_lifecycle.py).
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = Path(
    "docs/implementation/r6-successor-dense-full-integration-117/remediation"
)
MANIFEST = BUNDLE / "evidence" / "MANIFEST.sha256"

PRODUCERS = frozenset({
    "scripts/issue153_phase0_inventory.py",
    "scripts/issue153_producer_delta.py",
    "scripts/issue153_boundary_matrix.py",
    "scripts/issue153_manifest.py",
    "tests/test_issue153_arm_c_remediation.py",
})

EVIDENCE_FILES = frozenset({
    "README.md",
    "evidence/phase0-inventory.json",
    "evidence/producer-delta.json",
    "evidence/boundary-matrix.json",
})

MANIFEST_ROW_WIDTH = 2  # "<sha256>  <relative-path>"


class ManifestError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expected_entries(root: Path) -> dict[str, str]:
    bundle = root / BUNDLE
    actual = {
        path.relative_to(bundle).as_posix()
        for path in bundle.rglob("*")
        if path.is_file() and path != root / MANIFEST
    }
    if actual != EVIDENCE_FILES:
        missing = sorted(EVIDENCE_FILES - actual)
        unexpected = sorted(actual - EVIDENCE_FILES)
        raise ManifestError(
            f"Issue #153 bundle inventory mismatch; missing={missing}, "
            f"unexpected={unexpected}")
    entries: dict[str, str] = {}
    for name in sorted(EVIDENCE_FILES):
        relative = BUNDLE / name
        entries[relative.as_posix()] = sha256(root / relative)
    for name in sorted(PRODUCERS):
        entries[name] = sha256(root / name)
    return entries


def render(root: Path) -> bytes:
    lines = [
        f"{digest}  {relative}"
        for relative, digest in sorted(expected_entries(root).items())
    ]
    return ("\n".join(lines) + "\n").encode()


def parse(data: bytes) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in data.decode().splitlines():
        digest, separator, relative = line.partition("  ")
        if not separator or len(digest) != 64:
            raise ManifestError(f"malformed manifest line: {line!r}")
        if relative in entries:
            raise ManifestError(f"duplicate manifest row: {relative}")
        entries[relative] = digest
    return entries


def check(root: Path) -> None:
    manifest = root / MANIFEST
    if not manifest.is_file():
        raise ManifestError(f"missing manifest: {manifest}")
    entries = parse(manifest.read_bytes())
    expected = expected_entries(root)
    if set(entries) != set(expected):
        unexpected = sorted(set(entries) - set(expected))
        missing = sorted(set(expected) - set(entries))
        raise ManifestError(
            f"manifest entry set drift (unexpected={unexpected}, "
            f"missing={missing})"
        )
    for relative, digest in sorted(expected.items()):
        if entries[relative] != digest:
            raise ManifestError(
                f"manifest drift for {relative}: recorded "
                f"{entries[relative]} != actual {digest}"
            )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if args.check:
        check(ROOT)
        print(f"manifest OK: {MANIFEST}")
        return 0
    target = ROOT / MANIFEST
    target.write_bytes(render(ROOT))
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

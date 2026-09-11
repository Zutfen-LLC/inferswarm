#!/usr/bin/env python3
"""Build or verify the immutable, bundle-local Issue #137 manifest.

The manifest is a terminal integrity index: none of its inputs may depend on
its current bytes.  Living repository documents and CI configuration are
deliberately outside the evidence bundle.
"""
from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = Path(
    "docs/implementation/r6-successor-dense-full-integration-117/evidence/"
    "arm-c-regime4-diagnosis-137"
)
MANIFEST = BUNDLE / "MANIFEST.sha256"

PRODUCERS = frozenset({
    "scripts/issue137_binding.py",
    "scripts/issue137_conclusions.py",
    "scripts/issue137_manifest.py",
    "scripts/issue137_phase1_inventory.py",
    "scripts/issue137_probe_driver.py",
    "tests/test_issue137_regime4_diagnosis.py",
    "tests/test_issue137_regime4_diagnosis_correction.py",
})

EVIDENCE_FILES = frozenset({
    "METHODOLOGY.md",
    "README.md",
    "diagnostic-conclusions.json",
    "i137-diag-A-1789127822.json",
    "i137-diag-A-1789129558.json",
    "i137-diag-A-1789129893.json",
    "i137-diag-A-1789130927.json",
    "i137-diag-A-1789131013.json",
    "i137-diag-A-1789131099.json",
    "i137-diag-A-1789131186.json",
    "i137-diag-A2-1789128152.json",
    "i137-diag-B-1789130217.json",
    "i137-diag-C-1789128426.json",
    "i137-diag-C2-1789141057.json",
    "i137-diag-D-1789128772.json",
    "i137-diag-D2-1789129163.json",
    "i137-diag-D2-1789130625.json",
    "manifest-first-stage1-d2b.json",
    "manifest-middle-stage2-d2b.json",
    "phase1-inventory.json",
    "remote-last-stage-ledger-c2/launcher-loop.log",
    "remote-last-stage-ledger-c2/ready-101.json",
    "remote-last-stage-ledger-c2/ready-102.json",
    "remote-last-stage-ledger-c2/ready-103.json",
    "remote-last-stage-ledger-c2/ready-104.json",
    "remote-last-stage-ledger-c2/ready-105.json",
    "remote-last-stage-ledger-c2/ready-106.json",
    "remote-last-stage-ledger-c2/ready-107.json",
    "remote-last-stage-ledger-c2/ready-108.json",
    "remote-last-stage-ledger-c2/ready-109.json",
    "remote-last-stage-ledger-c2/ready-110.json",
    "remote-last-stage-ledger-c2/ready-111.json",
    "remote-last-stage-ledger-c2/ready-112.json",
    "remote-last-stage-ledger-c2/ready-113.json",
})

FORBIDDEN_LIVING_PATHS = frozenset({
    ".github/workflows/ci.yml",
    "ARCHITECTURE.md",
    "README.md",
    "ROADMAP.md",
    "docs/implementation/README.md",
    "docs/project-status.json",
    "docs/protocols/README.md",
})


class ManifestError(ValueError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def expected_entries(root: Path = ROOT) -> dict[str, str]:
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
            f"Issue #137 bundle inventory mismatch; missing={missing}, "
            f"unexpected={unexpected}")

    relative_paths = {
        *(str(BUNDLE / name) for name in EVIDENCE_FILES),
        *PRODUCERS,
    }
    if str(MANIFEST) in relative_paths:
        raise ManifestError("manifest must not hash itself")
    forbidden = relative_paths & FORBIDDEN_LIVING_PATHS
    if forbidden:
        raise ManifestError(
            f"living repository paths are not evidence: {sorted(forbidden)}")

    entries = {}
    for relative in sorted(relative_paths):
        path = root / relative
        if not path.is_file():
            raise ManifestError(f"manifest input is missing: {relative}")
        entries[relative] = sha256(path)
    return entries


def render(root: Path = ROOT) -> bytes:
    return "".join(
        f"{digest}  {path}\n"
        for path, digest in expected_entries(root).items()
    ).encode("utf-8")


def parse(data: bytes) -> dict[str, str]:
    entries = {}
    for line in data.decode("utf-8").splitlines():
        digest, separator, path = line.partition("  ")
        if (not separator or not re.fullmatch(r"[0-9a-f]{64}", digest)
                or not path or path in entries):
            raise ManifestError("malformed or duplicate manifest row")
        entries[path] = digest
    return entries


def check(root: Path = ROOT) -> None:
    manifest = root / MANIFEST
    if not manifest.is_file():
        raise ManifestError(f"manifest is missing: {MANIFEST}")
    expected = render(root)
    parse(manifest.read_bytes())
    if manifest.read_bytes() != expected:
        raise ManifestError(
            "Issue #137 manifest drift; regenerate only after reviewing every "
            "changed bundle input")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.write:
            (ROOT / MANIFEST).write_bytes(render(ROOT))
            print(f"Updated {MANIFEST}")
        else:
            check(ROOT)
            print("Issue #137 evidence manifest is current")
    except (OSError, UnicodeError, ManifestError) as error:
        print(f"Issue #137 manifest error: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

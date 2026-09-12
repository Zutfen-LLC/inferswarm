#!/usr/bin/env python3
"""Build or verify the immutable, bundle-local V0-C evidence manifest.

This CPU-only verifier covers the frozen V0-C methodology, retained physical
observation, exact execution-seam/adapter/manifest sources, and their contract
tests.  The manifest is terminal: it never hashes itself, and ``--check``
fails closed on a missing, incomplete, drifted, or unexpectedly expanded bundle.

    python3 scripts/v0c_manifest.py --write
    python3 scripts/v0c_manifest.py --check
"""
from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = Path("docs/investigations/vulkan-v0-c")
MANIFEST = BUNDLE / "MANIFEST.sha256"

EVIDENCE_FILES = frozenset({
    "ATTEMPT-01-CORRECTION.json",
    "ATTEMPT-01-PREQUALIFICATION-AUTHORITY.json",
    "CANONICAL-EXECUTION-AUTHORITY.json",
    "CANONICAL-EXECUTION-AUTHORITY-R2.json",
    "FINAL-TERMINAL.md",
    "INITIAL-OBSERVATION.md",
    "METHODOLOGY.md",
    "PHASE0-RUNTIME-IDENTITY.md",
    "PLAN-BINDING-ATTEMPT-01.json",
    "evidence/v0c-amd-a-final-qualification/capability-record.json",
    "evidence/v0c-amd-a-final-qualification/qualification-observation.json",
    "evidence/v0c-final-plan/candidate-set.json",
    "evidence/v0c-final-plan/frozen-plan.json",
    "evidence/v0c-final-plan/resource-snapshot.json",
    "evidence/v0c-final-execution/accounting.json",
    "evidence/v0c-final-execution/canonical-execution-observation.json",
    "evidence/v0c-final-execution/correctness-result.json",
    "evidence/v0c-final-execution/execution-receipt.json",
    "evidence/v0c-final-execution/negative-controls.json",
    "evidence/v0c-final-execution/terminal.json",
    "raw/v0c-amd-a-01/exit-code.txt",
    "raw/v0c-amd-a-01/stderr.txt",
    "raw/v0c-amd-a-01/stdout.txt",
    "raw/v0c-amd-a-final-canonical-01/attempt.json",
    "raw/v0c-amd-a-final-canonical-01/exit-code.txt",
    "raw/v0c-amd-a-final-canonical-01/stderr.txt",
    "raw/v0c-amd-a-final-canonical-01/stdout.txt",
    "raw/v0c-amd-a-final-qualification-01/attempt.json",
    "raw/v0c-amd-a-final-qualification-01/exit-code.txt",
    "raw/v0c-amd-a-final-qualification-01/stderr.txt",
    "raw/v0c-amd-a-final-qualification-01/stdout.txt",
})
SOURCES = frozenset({
    "scripts/v0c_canonical_run.py",
    "scripts/v0c_correctness.py",
    "scripts/v0c_execution_seam.py",
    "scripts/v0c_manifest.py",
    "scripts/v0c_vulkan_adapter.py",
})
TESTS = frozenset({
    "tests/test_v0c_canonical_run.py",
    "tests/test_v0c_correctness.py",
    "tests/test_v0c_evidence_manifest.py",
    "tests/test_v0c_execution_seam.py",
    "tests/test_v0c_vulkan_adapter.py",
})
FORBIDDEN_LIVING_PATHS = frozenset({
    ".github/workflows/ci.yml",
    "ARCHITECTURE.md",
    "README.md",
    "ROADMAP.md",
    "docs/project-status.json",
})


class ManifestError(ValueError):
    """A V0-C evidence-manifest integrity contract was not satisfied."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def required_paths() -> frozenset[str]:
    """Return the fixed terminal-manifest inputs, never including itself."""
    paths = frozenset({
        *(str(BUNDLE / name) for name in EVIDENCE_FILES),
        *SOURCES,
        *TESTS,
    })
    if MANIFEST.as_posix() in paths:
        raise ManifestError("manifest must not hash itself")
    forbidden = paths & FORBIDDEN_LIVING_PATHS
    if forbidden:
        raise ManifestError(
            f"living repository paths are not evidence: {sorted(forbidden)}"
        )
    return paths


def expected_entries(root: Path = ROOT) -> dict[str, str]:
    """Validate fixed V0-C inventory and return deterministic digest rows."""
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
            "V0-C bundle inventory mismatch; "
            f"missing={missing}, unexpected={unexpected}"
        )

    entries = {}
    for relative in sorted(required_paths()):
        path = root / relative
        if not path.is_file():
            raise ManifestError(f"manifest input missing: {relative}")
        entries[relative] = sha256(path)
    return entries


def render(root: Path = ROOT) -> bytes:
    """Render canonical, sorted manifest bytes from fixed inputs."""
    return "".join(
        f"{digest}  {path}\n"
        for path, digest in expected_entries(root).items()
    ).encode("utf-8")


def parse(data: bytes) -> dict[str, str]:
    """Parse canonical digest rows while rejecting malformed duplicates."""
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise ManifestError("manifest is not valid UTF-8") from error
    entries = {}
    for line in lines:
        digest, separator, path = line.partition("  ")
        if (not separator or not re.fullmatch(r"[0-9a-f]{64}", digest)
                or not path or path in entries):
            raise ManifestError("malformed or duplicate manifest row")
        entries[path] = digest
    return entries


def check(root: Path = ROOT) -> None:
    """Fail closed unless the manifest is complete, canonical, and current."""
    manifest = root / MANIFEST
    if not manifest.is_file():
        raise ManifestError(f"manifest missing: {MANIFEST}")
    expected = expected_entries(root)
    committed = parse(manifest.read_bytes())
    missing = sorted(set(expected) - set(committed))
    if missing:
        raise ManifestError(f"manifest incomplete; missing rows={missing}")
    unexpected = sorted(set(committed) - set(expected))
    if unexpected:
        raise ManifestError(f"manifest has unexpected rows={unexpected}")
    for path, digest in expected.items():
        if committed[path] != digest:
            raise ManifestError(f"manifest drift: digest differs for {path}")
    if manifest.read_bytes() != render(root):
        raise ManifestError("manifest drift: noncanonical row order or formatting")


def main(argv: list[str] | None = None) -> int:
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
            print("V0-C evidence manifest is current")
    except (OSError, ManifestError) as error:
        print(f"V0-C manifest error: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

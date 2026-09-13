#!/usr/bin/env python3
"""Build or verify the fixed-inventory additive V1-B evidence manifest."""
from __future__ import annotations

import argparse
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = Path("docs/investigations/vulkan-v1-b")
MANIFEST = BUNDLE / "MANIFEST.sha256"
EVIDENCE = frozenset({
    "README.md", "STATUS.json", "PHYSICAL-AUTHORITY.json", "FINAL-TERMINAL.json",
    "CROSS-SUBJECT-AUDIT.json", "reference-visible-output.txt",
    "evidence/v1b-nv-a-plan-01/resource-snapshot.json",
    "evidence/v1b-nv-a-plan-01/candidate-set.json",
    "evidence/v1b-nv-a-plan-01/frozen-plan.json",
    "raw/v1b-nv-a-qualification-01/stdout.txt",
    "raw/v1b-nv-a-qualification-01/stderr.txt",
    "raw/v1b-nv-a-qualification-01/exit-code.txt",
    "raw/v1b-nv-a-qualification-01/qualification.json",
    "raw/v1b-nv-a-stability-01/stdout.txt",
    "raw/v1b-nv-a-stability-01/stderr.txt",
    "raw/v1b-nv-a-stability-01/exit-code.txt",
    "raw/v1b-nv-a-stability-01/stability.json",
    "raw/v1b-nv-a-stability-02/stdout.txt",
    "raw/v1b-nv-a-stability-02/stderr.txt",
    "raw/v1b-nv-a-stability-02/exit-code.txt",
    "raw/v1b-nv-a-stability-02/stability.json",
    "raw/v1b-nv-a-stability-03/stdout.txt",
    "raw/v1b-nv-a-stability-03/stderr.txt",
    "raw/v1b-nv-a-stability-03/exit-code.txt",
    "raw/v1b-nv-a-stability-03/stability.json",
    "raw/v1b-nv-a-canonical-01/stdout.txt",
    "raw/v1b-nv-a-canonical-01/stderr.txt",
    "raw/v1b-nv-a-canonical-01/exit-code.txt",
    "raw/v1b-nv-a-canonical-01/runner-stdout.txt",
    "raw/v1b-nv-a-canonical-01/runner-stderr.txt",
    "raw/v1b-nv-a-canonical-01/runner-exit-code.txt",
    "raw/v1b-nv-a-canonical-01/canonical-attempt.json",
})
SOURCES = frozenset({"scripts/v1b_campaign.py", "scripts/v1b_manifest.py"})
TESTS = frozenset({"tests/test_v1b_campaign.py", "tests/test_v1b_evidence_manifest.py"})


class ManifestError(ValueError):
    """A V1-B evidence inventory or digest is missing, changed, or expanded."""


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def required_paths() -> frozenset[str]:
    return frozenset({*(str(BUNDLE / path) for path in EVIDENCE), *SOURCES, *TESTS})


def expected_entries(root: Path = ROOT) -> dict[str, str]:
    actual = {path.relative_to(root / BUNDLE).as_posix() for path in (root / BUNDLE).rglob("*")
              if path.is_file() and path != root / MANIFEST}
    if actual != EVIDENCE:
        raise ManifestError(f"V1-B bundle inventory mismatch: missing={sorted(EVIDENCE - actual)}, unexpected={sorted(actual - EVIDENCE)}")
    return {path: digest(root / path) for path in sorted(required_paths())}


def render(root: Path = ROOT) -> bytes:
    return "".join(f"{value}  {key}\n" for key, value in expected_entries(root).items()).encode()


def _parse(data: bytes) -> dict[str, str]:
    rows = {}
    for line in data.decode().splitlines():
        value, separator, key = line.partition("  ")
        if not separator or len(value) != 64 or key in rows:
            raise ManifestError("malformed manifest row")
        rows[key] = value
    return rows


def check(root: Path = ROOT) -> None:
    manifest = root / MANIFEST
    if not manifest.is_file():
        raise ManifestError("V1-B manifest missing")
    expected = expected_entries(root)
    if _parse(manifest.read_bytes()) != expected or manifest.read_bytes() != render(root):
        raise ManifestError("V1-B manifest drift")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.write:
            (ROOT / MANIFEST).write_bytes(render())
            print("Updated V1-B manifest")
        else:
            check()
            print("V1-B evidence manifest is current")
    except (OSError, ManifestError) as error:
        print(f"V1-B manifest error: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

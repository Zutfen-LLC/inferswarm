#!/usr/bin/env python3
"""Build or verify the fixed-inventory additive V1-A evidence manifest."""
from __future__ import annotations

import argparse
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = Path("docs/investigations/vulkan-v1-a")
MANIFEST = BUNDLE / "MANIFEST.sha256"
EVIDENCE = frozenset({"README.md", "COUPLING-AUDIT.json", "STATUS.json"})
SOURCES = frozenset({"scripts/v1a_execution_participant.py", "scripts/v1a_vulkan_adapter.py", "scripts/v1a_manifest.py"})
TESTS = frozenset({"tests/test_v1a_execution_participant.py", "tests/test_v1a_vulkan_adapter.py", "tests/test_v1a_evidence_manifest.py"})


class ManifestError(ValueError):
    """A V1-A evidence inventory or digest is missing, changed, or expanded."""


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def required_paths() -> frozenset[str]:
    return frozenset({*(str(BUNDLE / path) for path in EVIDENCE), *SOURCES, *TESTS})


def expected_entries(root: Path = ROOT) -> dict[str, str]:
    actual = {path.relative_to(root / BUNDLE).as_posix() for path in (root / BUNDLE).rglob("*")
              if path.is_file() and path != root / MANIFEST}
    if actual != EVIDENCE:
        raise ManifestError(f"V1-A bundle inventory mismatch: missing={sorted(EVIDENCE - actual)}, unexpected={sorted(actual - EVIDENCE)}")
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
        raise ManifestError("V1-A manifest missing")
    expected = expected_entries(root)
    if _parse(manifest.read_bytes()) != expected or manifest.read_bytes() != render(root):
        raise ManifestError("V1-A manifest drift")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.write:
            (ROOT / MANIFEST).write_bytes(render())
            print("Updated V1-A manifest")
        else:
            check()
            print("V1-A evidence manifest is current")
    except (OSError, ManifestError) as error:
        print(f"V1-A manifest error: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

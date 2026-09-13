#!/usr/bin/env python3
"""Build or verify the fixed-inventory additive V1-C evidence manifest.

Before the V1-C physical campaign completes, the bundle contains only
the prospectively frozen authority: the manifest is written in a
PROSPECTIVE state that pins the authority, the campaign producers, and
the focused tests. When the campaign completes, the terminal evidence
inventory below is what ``--write`` records and ``--check`` enforces;
until then ``--check`` accepts exactly the prospective inventory and
fails closed on anything else.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = Path("docs/investigations/vulkan-v1-c")
MANIFEST = BUNDLE / "MANIFEST.sha256"

# Terminal (post-campaign) evidence inventory. The campaign mode
# determines which inventory is current.
EVIDENCE_TERMINAL = frozenset({
    "README.md", "STATUS.json", "PHYSICAL-AUTHORITY.json", "FINAL-TERMINAL.json",
    "CROSS-SUBJECT-AUDIT.json", "RETAINED-TRANSCRIPT-REGRESSIONS.json",
    "evidence/v1c-nv-a-plan-01/resource-snapshot.json",
    "evidence/v1c-nv-a-plan-01/candidate-set.json",
    "evidence/v1c-nv-a-plan-01/frozen-plan.json",
    "evidence/v1c-nv-a-canonical-01/accounting.json",
    "evidence/v1c-nv-a-canonical-01/correctness-result.json",
    "evidence/v1c-nv-a-canonical-01/canonical-observation.json",
    "evidence/v1c-nv-a-canonical-01/execution-receipt.json",
    "raw/v1c-nv-a-qualification-01/stdout.txt",
    "raw/v1c-nv-a-qualification-01/stderr.txt",
    "raw/v1c-nv-a-qualification-01/exit-code.txt",
    "raw/v1c-nv-a-qualification-01/qualification.json",
    "raw/v1c-nv-a-canonical-01/stdout.txt",
    "raw/v1c-nv-a-canonical-01/stderr.txt",
    "raw/v1c-nv-a-canonical-01/exit-code.txt",
    "raw/v1c-nv-a-canonical-01/canonical-execution.json",
})
# Prospective (pre-campaign) inventory ladder. Each rung is the exact
# bundle content permitted at that campaign boundary; the manifest
# fails closed on any inventory that is not exactly one rung. The
# ladder only ever grows toward the terminal inventory.
EVIDENCE_LADDER = (
    # Phase 0: additive namespace created, README only.
    frozenset({"README.md"}),
    # Phase 2/4: CPU-only retained-transcript regression proof retained
    # before the source freeze.
    frozenset({"README.md", "RETAINED-TRANSCRIPT-REGRESSIONS.json"}),
    # Phase 5: prospective physical authority frozen before any V1-C
    # correctness-bearing physical output.
    frozenset({"README.md", "RETAINED-TRANSCRIPT-REGRESSIONS.json",
               "PHYSICAL-AUTHORITY.json"}),
    # Terminal: full campaign evidence.
    None,  # EVIDENCE_TERMINAL, substituted below
)
EVIDENCE_LADDER = tuple(
    EVIDENCE_TERMINAL if rung is None else rung for rung in EVIDENCE_LADDER)
EVIDENCE_PROSPECTIVE = EVIDENCE_LADDER
SOURCES = frozenset({
    "scripts/v1c_accounting.py", "scripts/v1c_runner.py", "scripts/v1c_manifest.py",
    # accepted predecessor sources pinned by this campaign's authority
    "scripts/v1a_execution_participant.py", "scripts/v1a_vulkan_adapter.py",
    "scripts/v1a_runner.py", "scripts/v0c_canonical_run.py", "scripts/v0c_correctness.py",
})
TESTS = frozenset({
    "tests/test_v1c_accounting.py", "tests/test_v1c_runner.py", "tests/test_v1c_evidence_manifest.py",
})


class ManifestError(ValueError):
    """A V1-C evidence inventory or digest is missing, changed, or expanded."""


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def current_inventory(root: Path = ROOT) -> frozenset[str]:
    return frozenset(path.relative_to(root / BUNDLE).as_posix()
                     for path in (root / BUNDLE).rglob("*")
                     if path.is_file() and path != root / MANIFEST)


def required_paths(root: Path = ROOT) -> frozenset[str]:
    actual = current_inventory(root)
    for rung in EVIDENCE_LADDER:
        if actual == rung:
            return frozenset({*(str(BUNDLE / path) for path in rung), *SOURCES, *TESTS})
    raise ManifestError(
        f"V1-C bundle inventory mismatch: missing={sorted(EVIDENCE_TERMINAL - actual)}, "
        f"unexpected={sorted(actual - EVIDENCE_TERMINAL)}")


def expected_entries(root: Path = ROOT) -> dict[str, str]:
    return {path: digest(root / path) for path in sorted(required_paths(root))}


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
        raise ManifestError("V1-C manifest missing")
    expected = expected_entries(root)
    if _parse(manifest.read_bytes()) != expected or manifest.read_bytes() != render(root):
        raise ManifestError("V1-C manifest drift")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.write:
            (ROOT / MANIFEST).write_bytes(render())
            print("Updated V1-C manifest")
        else:
            check()
            print("V1-C evidence manifest is current")
    except (OSError, ManifestError) as error:
        print(f"V1-C manifest error: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""V2-A generalized fixed-inventory evidence bundle generator/verifier.

Generalizes the accepted additive evidence lifecycle: the bundle
inventory is derived from an inventory CONTRACT (a ladder of exact
permitted states toward a terminal inventory) declared as DATA per
campaign namespace, instead of a hand-written per-subject producer.
``--contract`` points at a JSON contract; the V2-A contract covers both
physical campaigns (both subjects' evidence live in the SAME additive
namespace, so a campaign is a data difference, not a producer fork).

Fails closed on missing, drifted, unexpected, or incomplete evidence:
the on-disk bundle must equal EXACTLY one ladder rung, every pinned
source/test must match its recorded digest, and the manifest bytes must
be the canonical rendering.
"""
from __future__ import annotations

import argparse
import json
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = ROOT / "docs/investigations/vulkan-v2-a/manifest-contract.json"


class ManifestError(ValueError):
    """A V2-A evidence inventory or digest is missing, changed, or expanded."""


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def load_contract(path: Path) -> dict:
    contract = json.loads(path.read_text(encoding="utf-8"))
    for key in ("bundle", "ladder", "sources", "tests"):
        if key not in contract:
            raise ManifestError(f"inventory contract missing key: {key}")
    rungs = contract["ladder"]
    if not isinstance(rungs, list) or not rungs:
        raise ManifestError("inventory contract ladder must be a non-empty list")
    seen = []
    for rung in rungs:
        entries = sorted(rung.get("evidence", []))
        if entries in seen:
            raise ManifestError("ladder rungs must be strictly increasing")
        seen.append(entries)
    return contract


def current_inventory(bundle_dir: Path) -> frozenset[str]:
    return frozenset(path.relative_to(bundle_dir).as_posix()
                     for path in bundle_dir.rglob("*")
                     if path.is_file() and path.name != "MANIFEST.sha256"
                     and path.name != "manifest-contract.json")


def required_paths(contract: dict, root: Path = ROOT) -> frozenset[str]:
    bundle = root / contract["bundle"]
    actual = current_inventory(bundle)
    for rung in contract["ladder"]:
        if actual == frozenset(rung["evidence"]):
            return frozenset({str(Path(contract["bundle"]) / path) for path in rung["evidence"]}
                             | set(contract["sources"]) | set(contract["tests"]))
    terminal = frozenset(contract["ladder"][-1]["evidence"])
    raise ManifestError(
        f"V2-A bundle inventory mismatch: missing={sorted(terminal - actual)}, "
        f"unexpected={sorted(actual - terminal)}")


def expected_entries(contract: dict, root: Path = ROOT) -> dict[str, str]:
    return {path: digest(root / path) for path in sorted(required_paths(contract, root))}


def render(contract: dict, root: Path = ROOT) -> bytes:
    return "".join(f"{value}  {key}\n"
                   for key, value in expected_entries(contract, root).items()).encode()


def _parse(data: bytes) -> dict[str, str]:
    rows = {}
    for line in data.decode().splitlines():
        value, separator, key = line.partition("  ")
        if not separator or len(value) != 64 or key in rows:
            raise ManifestError("malformed manifest row")
        rows[key] = value
    return rows


def check(contract: dict, root: Path = ROOT) -> None:
    manifest = root / contract["bundle"] / "MANIFEST.sha256"
    if not manifest.is_file():
        raise ManifestError("V2-A manifest missing")
    if _parse(manifest.read_bytes()) != expected_entries(contract, root) \
            or manifest.read_bytes() != render(contract, root):
        raise ManifestError("V2-A manifest drift")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        contract = load_contract(Path(args.contract))
        if args.write:
            (ROOT / contract["bundle"] / "MANIFEST.sha256").write_bytes(render(contract))
            print(f"Updated V2-A manifest ({contract['bundle']})")
        else:
            check(contract)
            print(f"V2-A evidence manifest is current ({contract['bundle']})")
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"V2-A manifest error: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

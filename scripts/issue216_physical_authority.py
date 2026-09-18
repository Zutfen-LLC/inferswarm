#!/usr/bin/env python3
"""Issue #216 — immutable predecessor identity and fresh mapping producer.

`build` derives V2-D's intended two physical resources exclusively from the
accepted V2-B/V2-C authorities. `fresh-map` is the only execution-time mapping
collector: it reuses the accepted V2-A R3 discovery/binding grammar and retains
its raw probes. Neither command executes a V2-D correctness workload.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
AREA_REL = "docs/investigations/vulkan-v2-d-v340l-concurrent"
CAMPAIGN_ID = "issue216-v2d-v340l-concurrent-dual-die-v1"

SOURCES = {
    "v2b": {
        "terminal": ("docs/investigations/vulkan-v2-b-v340l/TERMINAL.json",
                     "fb9e1c5c6cd6934cc035b7d5b05e4a3342770bc85ba878d65533e5f54ae76147",
                     "V2B_V340L_DUAL_DIE_QUALIFICATION_PASS"),
        "authorities": {
            "a": ("docs/investigations/vulkan-v2-b-v340l/AUTHORITY-V340L-A.json",
                  "59e2429914564b9bfc8a4d5a33a303d10f3fbd8e6dbecfdb8fcee5723ca61f54"),
            "b": ("docs/investigations/vulkan-v2-b-v340l/AUTHORITY-V340L-B.json",
                  "109f5752a30ab1befca68118b3fa8e7c770cf083b302054025908a60da200eab"),
        },
    },
    "v2c": {
        "terminal": ("docs/investigations/vulkan-v2-c-v340l-platform-stability/cycles-v2/TERMINAL-V2.json",
                     "497b5b966fa658657105ba2212fdf2f07bd14840a02db24d7d8297d12c8c97fe",
                     "V2C_V340L_PLATFORM_STABILITY_PASS"),
        "authorities": {
            "a": ("docs/investigations/vulkan-v2-c-v340l-platform-stability/AUTHORITY-V2C-V2-FINAL-A.json",
                  "078d46a8b088ff7eb91041f3df866b963f7f64b8a1bf85859f406ae3f8120b33"),
            "b": ("docs/investigations/vulkan-v2-c-v340l-platform-stability/AUTHORITY-V2C-V2-FINAL-B.json",
                  "3cff3ed7cb1e222a724fe4130938fcb1bfd0af37a528498a6504f01c01912c69"),
        },
    },
}


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_file(path: Path) -> str:
    return sha256(path.read_bytes())


def authority_digest(doc: dict[str, Any]) -> str:
    body = dict(doc)
    body.pop("authority_digest", None)
    return sha256(canonical(body))


def _load(root: Path, rel: str, expected: str) -> dict[str, Any]:
    path = root / rel
    if not path.is_file() or digest_file(path) != expected:
        raise ValueError(f"accepted input digest mismatch: {rel}")
    return json.loads(path.read_text(encoding="utf-8"))


def _participant(doc: dict[str, Any]) -> dict[str, Any]:
    """Return accepted intended identity, never an execution-time selector/BDF."""
    frozen = doc["frozen"]
    return {
        "compute_unit_id": frozen["compute_unit_id"],
        "memory_resource_id": frozen["memory_resource_id"],
        "vram_bytes": frozen["memory_bytes"],
        "hostname": frozen["hostname"],
        "historical_qualification_observation": {
            "selector": frozen["selector"], "pci_bdf": frozen["physical_device_bdf"],
        },
    }


def _runtime(doc: dict[str, Any]) -> dict[str, Any]:
    frozen = doc["frozen"]
    return {
        "executable": frozen["executable"],
        "executable_sha256": frozen["executable_sha256"],
        "model": frozen["model"],
        "model_sha256": frozen["model_sha256"],
        "model_bytes": frozen["model_bytes"],
        "reference_path": "docs/investigations/vulkan-v1-a/reference-visible-output.txt",
        "reference_sha256": "9013db8fb38982f9085754e69fa3feb2f74c7372360da686fe90a3444f26182d",
        "source_commit": frozen["runtime_source_commit"],
    }


def build_authority(root: Path = ROOT) -> dict[str, Any]:
    source_rows: dict[str, Any] = {}
    generations: dict[tuple[str, str], dict[str, Any]] = {}
    for generation, spec in SOURCES.items():
        term_rel, term_sha, required = spec["terminal"]
        terminal = _load(root, term_rel, term_sha)
        if terminal.get("terminal") != required:
            raise ValueError(f"unaccepted predecessor terminal: {generation}")
        source_rows[generation] = {"terminal": {"path": term_rel, "sha256": term_sha,
                                                   "required_terminal": required}, "authorities": {}}
        for die, (rel, expected) in spec["authorities"].items():
            generations[(generation, die)] = _load(root, rel, expected)
            source_rows[generation]["authorities"][die] = {"path": rel, "sha256": expected}
    a = _participant(generations[("v2b", "a")]); b = _participant(generations[("v2b", "b")])
    runtime = _runtime(generations[("v2b", "a")])
    for die, expected in (("a", a), ("b", b)):
        if _participant(generations[("v2c", die)]) != expected:
            raise ValueError(f"V2-B/V2-C physical identity disagreement for {die}")
        if _runtime(generations[("v2b", die)]) != runtime or _runtime(generations[("v2c", die)]) != runtime:
            raise ValueError("accepted runtime/model authority disagreement")
    if any(a[k] == b[k] for k in ("compute_unit_id", "memory_resource_id")):
        raise ValueError("accepted authorities do not establish two distinct dies")
    intended = {die: {k: value for k, value in row.items() if k != "historical_qualification_observation"}
                for die, row in (("a", a), ("b", b))}
    history = {die: row["historical_qualification_observation"] for die, row in (("a", a), ("b", b))}
    doc: dict[str, Any] = {
        "schema": "inferswarm.v2d.physical-authority/1", "campaign_id": CAMPAIGN_ID,
        "accepted_sources": source_rows, "runtime": runtime,
        "intended_participants": intended,
        "historical_qualification_observations": history,
        "required_fresh_mapping": {"schema": "inferswarm.v2d.fresh-physical-mapping/1",
                                    "must_use_v2a_r3_validation": True,
                                    "require_exact_participant_set": ["a", "b"],
                                    "require_distinct_selector_bdf_cu_mr": True,
                                    "require_raw_probe_revalidation": True},
    }
    doc["authority_digest"] = authority_digest(doc)
    return doc


def verify_authority(doc: dict[str, Any], root: Path = ROOT) -> bool:
    try:
        expected = build_authority(root)
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return False
    return doc == expected and doc.get("authority_digest") == authority_digest(doc)


def write_authority(root: Path = ROOT) -> Path:
    out = root / AREA_REL / "PHYSICAL-AUTHORITY.json"
    out.write_bytes(json.dumps(build_authority(root), indent=1, sort_keys=True).encode() + b"\n")
    return out


def fresh_map(authority_path: Path, attempt_id: str, out: Path, repo: Path) -> dict[str, Any]:
    """Collect fresh mapping with accepted V2-A R3 machinery; no model tokens."""
    authority = json.loads(authority_path.read_text(encoding="utf-8"))
    if not verify_authority(authority, repo):
        raise ValueError("invalid immutable V2-D physical authority")
    sys.path.insert(0, str(repo / "scripts"))
    import v2a_discovery_v3 as discovery  # accepted parser/validator
    runtime = authority["runtime"]
    raw = out / "raw"
    raw.mkdir(parents=True, exist_ok=False)
    inventory = discovery.build_inventory(runtime_executable=runtime["executable"])
    # Resolve the CURRENT inventory only.  Historical selectors/BDFs are never
    # supplied to the discovery API; assignment is later corroborated against
    # fresh root/switch/endpoint topology in the preflight receipt.
    bindings = discovery.build_bindings(inventory, model=runtime["model"], raw_root=raw, raw_rel_dir=".")
    bound = [row for row in bindings["bindings"] if row.get("binding_status") == "BOUND"]
    if len(bound) != 2 or len({row.get("pci_bdf") for row in bound}) != 2:
        raise ValueError("fresh discovery did not establish exactly two distinct bound devices")
    # The labels are a fresh topology-assignment request, not a selector/BDF
    # assumption.  Preflight must supply the raw topology proof before later
    # receipts are accepted.
    rows = {}
    for die, row in zip(("a", "b"), sorted(bound, key=lambda item: item["pci_bdf"])):
        rows[die] = {"intended_identity": authority["intended_participants"][die],
                     "fresh_selector": row["selector"], "fresh_pci_bdf": row["pci_bdf"],
                     "fresh_device_name": row.get("device_name"), "fresh_binding": row}
    record = {"schema": "inferswarm.v2d.fresh-physical-mapping/1", "campaign_id": CAMPAIGN_ID,
              "attempt_id": attempt_id, "authority_path": authority_path.as_posix(),
              "authority_digest": authority["authority_digest"], "inventory": inventory,
              "bindings": bindings, "participants": rows,
              "mapping_requires_fresh_topology_corroboration": True}
    record["mapping_digest"] = sha256(canonical({"participants": rows}))
    path = out / "FRESH-PHYSICAL-MAPPING.json"
    path.write_bytes(json.dumps(record, indent=1, sort_keys=True).encode() + b"\n")
    return record


def main() -> int:
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build").add_argument("--repo", default=str(ROOT))
    m = sub.add_parser("fresh-map"); m.add_argument("--authority", required=True); m.add_argument("--attempt-id", required=True)
    m.add_argument("--out", required=True); m.add_argument("--repo", required=True)
    args = ap.parse_args()
    if args.cmd == "build":
        print(write_authority(Path(args.repo)))
    else:
        fresh_map(Path(args.authority), args.attempt_id, Path(args.out), Path(args.repo))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

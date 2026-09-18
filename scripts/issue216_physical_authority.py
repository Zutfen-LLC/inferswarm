#!/usr/bin/env python3
"""Issue #216 — V2-D immutable intended-identity authority (rebuild v2).

`build` derives V2-D's intended two physical resources exclusively from
accepted V2-B + V2-C authority bytes (path/sha/terminal pinned; every
predecessor file re-hashed at build). It emits intended identity only —
it contains NO execution-time selector/BDF: those come from a fresh
mapping receipt collected per attempt with the accepted V2-A R3
discovery machinery.

`fresh-map` is the single execution-time mapping collector. It runs the
accepted discovery (inventory + zero-token identity probes) and requires
that the fresh bindings CORROBORATE the intended identity: exactly two
BOUND Vega devices, distinct BDF/selector, each binding's identity-proof
line re-derived from retained raw probe bytes (R3 semantics), and the
BDF↔CU/MR correspondence must be consistent with the accepted V2-B
authority (selector↔BDF stable since qualification). If corroboration
fails, mapping fails closed — V2-D never executes against an unproven
device mapping.

Neither command executes a V2-D correctness-bearing workload.
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue216_receipt as rc

ROOT = Path(__file__).resolve().parents[1]

# Accepted predecessor pins. Digests are NEVER hand-copied: each consumed
# file's sha256 is loaded at build time from the predecessor's own accepted
# MANIFEST.sha256 rows (repo-root-relative paths, re-hashed by the repo's
# manifest lifecycle tests), and the file bytes are then re-hashed and
# required to match the manifest row. A hand-copied digest always drifts.
MANIFEST_OF = {
    "v2b": "docs/investigations/vulkan-v2-b-v340l/MANIFEST.sha256",
    "v2c": ("docs/investigations/vulkan-v2-c-v340l-platform-stability/"
            "MANIFEST.sha256"),
}
SOURCES = {
    "v2b": {
        "merge": "f91119d05e7079c780c7b88be6138fed0920b759",
        "terminal": ("docs/investigations/vulkan-v2-b-v340l/TERMINAL.json",
                     "V2B_V340L_DUAL_DIE_QUALIFICATION_PASS"),
        "authorities": {
            "a": "docs/investigations/vulkan-v2-b-v340l/AUTHORITY-V340L-A.json",
            "b": "docs/investigations/vulkan-v2-b-v340l/AUTHORITY-V340L-B.json",
        },
    },
    "v2c": {
        "merge": "605d0b465dc2bd015a7c832c67f4adcd7aefeb61",
        "terminal": ("docs/investigations/vulkan-v2-c-v340l-platform-stability/cycles-v2/TERMINAL-V2.json",
                     "V2C_V340L_PLATFORM_STABILITY_PASS"),
        "authorities": {
            "a": ("docs/investigations/vulkan-v2-c-v340l-platform-stability/"
                  "AUTHORITY-V2C-V2-FINAL-A.json"),
            "b": ("docs/investigations/vulkan-v2-c-v340l-platform-stability/"
                  "AUTHORITY-V2C-V2-FINAL-B.json"),
        },
    },
}

V2D0_RUNTIME_IDENTITY = ("docs/investigations/vulkan-v2-d0-overlap-seam/"
                         "RUNTIME-IDENTITY.json")

VEGA_DEVICE_ID = 0x6864


class AuthorityError(RuntimeError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _manifest_rows(root: Path, rel_manifest: str) -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in (root / rel_manifest).read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 2:
            rows[parts[1]] = parts[0]
    if not rows:
        raise AuthorityError(f"empty/missing manifest: {rel_manifest}")
    return rows


def _load(root: Path, rel: str, expected: str | None = None,
          manifest_rows: dict[str, str] | None = None) -> dict[str, Any]:
    """Load an accepted predecessor file, pinning its digest from its own
    accepted MANIFEST.sha256 row when available (never a hand-copied pin),
    else from the passed expected digest."""
    path = root / rel
    if not path.is_file():
        raise AuthorityError(f"accepted input missing: {rel}")
    actual = sha256(path.read_bytes())
    if manifest_rows is not None:
        row = manifest_rows.get(rel)
        if row is None:
            raise AuthorityError(f"no manifest row for {rel}")
        if actual != row:
            raise AuthorityError(
                f"accepted input diverges from its accepted manifest row: "
                f"{rel}")
    elif expected is not None and actual != expected:
        raise AuthorityError(f"accepted input digest mismatch: {rel}")
    return json.loads(path.read_text(encoding="utf-8"))


def _participant(doc: dict[str, Any]) -> dict[str, Any]:
    frozen = doc["frozen"]
    return {
        "compute_unit_id": frozen["compute_unit_id"],
        "memory_resource_id": frozen["memory_resource_id"],
        "vram_bytes": frozen["memory_bytes"],
        "hostname": frozen["hostname"],
        "historical_qualification_binding": {
            "selector": frozen["selector"],
            "pci_bdf": frozen["physical_device_bdf"],
        },
    }


def _runtime(doc: dict[str, Any]) -> dict[str, Any]:
    frozen = doc["frozen"]
    return {k: frozen[k] for k in (
        "executable", "executable_sha256", "model", "model_sha256",
        "model_bytes", "runtime_source_commit")}


def build_authority(root: Path = ROOT) -> dict[str, Any]:
    source_rows: dict[str, Any] = {}
    generations: dict[tuple[str, str], dict[str, Any]] = {}
    for generation, spec in SOURCES.items():
        rows = _manifest_rows(root, MANIFEST_OF[generation])
        term_rel, required = spec["terminal"]
        terminal = _load(root, term_rel, manifest_rows=rows)
        if terminal.get("terminal") != required:
            raise AuthorityError(
                f"unaccepted predecessor terminal: {generation}")
        source_rows[generation] = {
            "merge": spec["merge"],
            "manifest": {"path": MANIFEST_OF[generation]},
            "terminal": {"path": term_rel, "sha256": rows[term_rel],
                         "required_terminal": required},
            "authorities": {},
        }
        for die, rel in spec["authorities"].items():
            generations[(generation, die)] = _load(root, rel,
                                                   manifest_rows=rows)
            source_rows[generation]["authorities"][die] = {
                "path": rel, "sha256": rows[rel]}

    # V2-D0 runtime identity (corrected seam instrument pins).
    v2d0 = _load(root, V2D0_RUNTIME_IDENTITY, _v2d0_expected(root))

    a = _participant(generations[("v2b", "a")])
    b = _participant(generations[("v2b", "b")])
    runtime = _runtime(generations[("v2b", "a")])
    for die, expected_row in (("a", a), ("b", b)):
        if _participant(generations[("v2c", die)]) != expected_row:
            raise AuthorityError(
                f"V2-B/V2-C physical identity disagreement for die {die}")
        if _runtime(generations[("v2b", die)]) != runtime:
            raise AuthorityError("V2-B runtime authority disagreement")
        if _runtime(generations[("v2c", die)]) != runtime:
            raise AuthorityError("V2-C runtime authority disagreement")
    if any(a[k] == b[k] for k in ("compute_unit_id", "memory_resource_id")):
        raise AuthorityError("accepted authorities do not establish two "
                             "distinct dies")
    if a["hostname"] != b["hostname"] or a["hostname"] != "inferswarm02":
        raise AuthorityError("accepted authorities disagree on host")

    intended = {die: {k: v for k, v in row.items()
                      if k != "historical_qualification_binding"}
                for die, row in (("a", a), ("b", b))}
    history = {die: row["historical_qualification_binding"]
               for die, row in (("a", a), ("b", b))}

    doc = {
        "schema": "inferswarm.v2d.physical-authority/2",
        "campaign_id": rc.CAMPAIGN_ID,
        "accepted_sources": source_rows,
        "runtime": {
            **{k: runtime[k] for k in (
                "executable", "executable_sha256", "model", "model_sha256",
                "model_bytes")},
            "runtime_source_commit": runtime["runtime_source_commit"],
            "reference_path": rc.FROZEN_RUNTIME["reference_path"],
            "reference_sha256": rc.FROZEN_RUNTIME["reference_sha256"],
            "observe_runtime_executable":
                rc.FROZEN_RUNTIME["observe_runtime_executable"],
            "observe_runtime_instrumented_ggml_vulkan_sha256":
                rc.FROZEN_RUNTIME[
                    "observe_runtime_instrumented_ggml_vulkan_sha256"],
            "observe_runtime_source_commit":
                rc.FROZEN_RUNTIME["observe_runtime_source_commit"],
            "observe_env_gate": rc.FROZEN_RUNTIME["observe_env_gate"],
        },
        "v2d0_runtime_identity": {
            "path": V2D0_RUNTIME_IDENTITY,
            "sha256": _v2d0_expected(root),
            "corrected_instrumented_ggml_vulkan_sha256": v2d0[
                "corrected_instrumented_ggml_vulkan_sha256"],
            "pinned_commit": v2d0["pinned_commit"],
        },
        "intended_participants": intended,
        "historical_qualification_bindings": history,
        "required_fresh_mapping": {
            "schema": "inferswarm.v2d.fresh-mapping/2",
            "must_use_v2a_r3_validation": True,
            "require_exact_participant_set": ["a", "b"],
            "require_distinct_selector_bdf": True,
            "require_intended_identity_corroboration": True,
            "device_uuid_cross_bind": "per-run, via each execution's seam observe-record header (assembler-enforced)",
            "require_raw_probe_revalidation": True,
        },
        "nonclaims": [
            "intended identity only: no selector/BDF in this document "
            "authorizes execution; execution requires a fresh mapping "
            "receipt corroborating this identity on the current boot",
        ],
    }
    doc["authority_digest"] = sha256(canonical(
        {k: v for k, v in doc.items() if k != "authority_digest"}))
    return doc


def _v2d0_expected(root: Path) -> str:
    # The V2-D0 runtime-identity pin is re-derived from the file bytes so a
    # hand-copied digest can never drift (lesson: hand-copied digests drift).
    path = root / V2D0_RUNTIME_IDENTITY
    if not path.is_file():
        raise AuthorityError(f"missing {V2D0_RUNTIME_IDENTITY}")
    return sha256(path.read_bytes())


def verify_authority(doc: dict[str, Any], root: Path = ROOT) -> bool:
    try:
        return doc == build_authority(root)
    except (OSError, KeyError, TypeError, ValueError, AuthorityError,
            json.JSONDecodeError):
        return False


def write_authority(root: Path = ROOT) -> Path:
    out = root / rc.AREA_REL / "PHYSICAL-AUTHORITY.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(json.dumps(build_authority(root), indent=1,
                               sort_keys=True).encode("utf-8") + b"\n")
    return out


# ---------------------------------------------------------------------------
# Fresh mapping (execution-time collector; runs on inferswarm02).
# ---------------------------------------------------------------------------

def fresh_map(authority_path: Path, attempt_id: str, out: Path,
              repo: Path, *, fixture: bool = False) -> dict[str, Any]:
    """Collect + corroborate the fresh two-die mapping (no model tokens)."""
    authority = json.loads(authority_path.read_text(encoding="utf-8"))
    if not verify_authority(authority, repo):
        raise AuthorityError("invalid immutable V2-D physical authority")
    sys.path.insert(0, str(repo / "scripts"))
    import v2a_discovery_v3 as discovery  # accepted R3 machinery

    runtime = authority["runtime"]
    raw = out / "raw"
    raw.mkdir(parents=True, exist_ok=False)
    inventory = discovery.build_inventory(
        runtime_executable=runtime["executable"])
    bindings = discovery.build_bindings(
        inventory, model=runtime["model"], raw_root=raw,
        raw_rel_dir=".")

    bound = [row for row in bindings["bindings"]
             if row.get("binding_status") == "BOUND"]
    vega_bound = [row for row in bound
                  if "V340" in (row.get("device_name") or "").upper()]
    if len(vega_bound) != 2 or len({r["pci_bdf"] for r in vega_bound}) != 2 \
            or len({r["selector"] for r in vega_bound}) != 2:
        raise AuthorityError(
            "fresh discovery did not establish exactly two distinct bound "
            "V340 devices")

    # Intended-identity corroboration: the accepted V2-B authority binds
    # CU id -> selector -> BDF. The fresh mapping must reproduce that
    # correspondence for both dies (stable since qualification).
    history = authority["historical_qualification_bindings"]
    rows: dict[str, dict[str, Any]] = {}
    for die in ("a", "b"):
        hist = history[die]
        match = [row for row in vega_bound
                 if row["selector"] == hist["selector"]
                 and row["pci_bdf"] == hist["pci_bdf"]]
        if len(match) != 1:
            raise AuthorityError(
                f"fresh mapping does not corroborate intended identity for "
                f"die {die}: expected selector={hist['selector']} "
                f"bdf={hist['pci_bdf']}")
        row = match[0]
        rows[die] = {
            "intended_identity": authority["intended_participants"][die],
            "fresh_selector": row["selector"],
            "fresh_pci_bdf": row["pci_bdf"],
            "fresh_device_name": row["device_name"],
            "fresh_binding": row,
        }
    # Distinct physical identity per participant is established by the
    # R3 binding (distinct selector AND distinct BDF, both verified by
    # the accepted validator); the per-run device-UUID cross-bind is
    # enforced by the assembler via each run's seam observe header.

    record = {
        "schema": "inferswarm.v2d.fresh-mapping/2",
        "campaign_id": rc.CAMPAIGN_ID,
        "attempt_id": attempt_id,
        "authority_path": authority_path.as_posix(),
        "authority_digest": authority["authority_digest"],
        "inventory": inventory,
        "bindings": bindings,
        "participants": rows,
        "fixture": fixture,
    }
    record["mapping_digest"] = sha256(canonical(
        {k: v for k, v in record.items() if k != "mapping_digest"}))
    return record


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--repo", default=str(ROOT))
    m = sub.add_parser("fresh-map")
    m.add_argument("--authority", required=True)
    m.add_argument("--attempt-id", required=True)
    m.add_argument("--out", required=True)
    m.add_argument("--repo", required=True)
    args = ap.parse_args()
    if args.cmd == "build":
        print(write_authority(Path(args.repo)))
    else:
        record = fresh_map(Path(args.authority), args.attempt_id,
                           Path(args.out), Path(args.repo))
        out = Path(args.out) / "fresh-mapping.json"
        out.write_bytes(json.dumps(record, indent=1, sort_keys=True)
                        .encode("utf-8") + b"\n")
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

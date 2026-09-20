#!/usr/bin/env python3
"""Issue #230 — V2-F immutable intended-identity authority builder.

`build` derives V2-F's intended physical resources exclusively from
accepted predecessor bytes (paths/sha/terminal pinned through each
predecessor's own accepted MANIFEST.sha256 rows, every file re-hashed at
build — a hand-copied digest always drifts):

  V2-B (#210/PR #212)   dual-die qualification PASS
  V2-C (#215/PR #217)   platform stability PASS
  V2-D (#216/PR #221)   PLATFORM_STRESS_FAIL — inherited as a SAFETY
                        CONSTRAINT. The fault record's seam identity is
                        pinned so V2-F can prove its mechanism is not
                        materially that seam.
  V2-E (#228/PR #229)   EVIDENCE_BLOCKED terminal — the corrected pf2
                        census (advertisement authority) and its fresh
                        selector/BDF bindings are consumed as PREREQUISITE
                        AUTHORITY. V2-F does NOT recollect the capability
                        census "merely to seek a different answer".

The emitted document carries intended identity only; execution-time
selector/BDF binding comes from a fresh mapping receipt collected per
attempt with the accepted V2-A R3 discovery machinery PLUS a current-boot
UUID->BDF join performed by the V2-F identity probe, both corroborated
against this authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue230_receipt as rc

ROOT = Path(__file__).resolve().parents[1]

MANIFEST_OF = {
    "v2b": "docs/investigations/vulkan-v2-b-v340l/MANIFEST.sha256",
    "v2c": ("docs/investigations/vulkan-v2-c-v340l-platform-stability/"
            "MANIFEST.sha256"),
    "v2d": ("docs/investigations/vulkan-v2-d-v340l-concurrent/"
            "MANIFEST.sha256"),
    "v2e": ("docs/investigations/vulkan-v2-e-v340l-peer-link/"
            "MANIFEST.sha256"),
}
SOURCES = {
    "v2b": {
        "merge": "f91119d05e7079c780b7b88be6138fed0920b759",
        "terminal": ("docs/investigations/vulkan-v2-b-v340l/TERMINAL.json",
                     "V2B_V340L_DUAL_DIE_QUALIFICATION_PASS"),
        "authorities": {
            "a": "docs/investigations/vulkan-v2-b-v340l/AUTHORITY-V340L-A.json",
            "b": "docs/investigations/vulkan-v2-b-v340l/AUTHORITY-V340L-B.json",
        },
    },
    "v2c": {
        "merge": "605d0b465dc2bd015a7c832c6744adcd7aefeb61",
        "terminal": ("docs/investigations/vulkan-v2-c-v340l-platform-stability/cycles-v2/TERMINAL-V2.json",
                     "V2C_V340L_PLATFORM_STABILITY_PASS"),
        "authorities": {
            "a": ("docs/investigations/vulkan-v2-c-v340l-platform-stability/"
                  "AUTHORITY-V2C-V2-FINAL-A.json"),
            "b": ("docs/investigations/vulkan-v2-c-v340l-platform-stability/"
                  "AUTHORITY-V2C-V2-FINAL-B.json"),
        },
    },
    "v2d": {
        "merge": "fe690249873a9bf7ca19d788a2fab5e580473394",
        "terminal": ("docs/investigations/vulkan-v2-d-v340l-concurrent/"
                     "evidence/TERMINAL.json",
                     "V2D_V340L_PLATFORM_STRESS_FAIL"),
        "fault_evidence": ("docs/investigations/vulkan-v2-d-v340l-concurrent/"
                           "evidence/ASSEMBLY.json"),
    },
    "v2e": {
        "merge": "78a91de435ffc9e1678574a754bbdd49d67dbd7a",
        "terminal": ("docs/investigations/vulkan-v2-e-v340l-peer-link/"
                     "evidence/TERMINAL.json",
                     "V2E_EVIDENCE_BLOCKED"),
        "preflight": ("docs/investigations/vulkan-v2-e-v340l-peer-link/"
                      "evidence/preflight/preflight.json"),
        "census_raw": (
            "docs/investigations/vulkan-v2-e-v340l-peer-link/evidence/"
            "preflight/raw/capability-probe.stdout",
            "docs/investigations/vulkan-v2-e-v340l-peer-link/evidence/"
            "preflight/raw/ext-matrix.stdout",
        ),
        "mapping": ("docs/investigations/vulkan-v2-e-v340l-peer-link/"
                    "evidence/preflight/mapping/fresh-mapping.json"),
    },
}


class AuthorityError(RuntimeError):
    pass


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: Any) -> bytes:
    return rc.canonical(value)


def _load_manifest_rows(root: Path, rel: str) -> dict[str, str]:
    path = root / rel
    if not path.is_file():
        raise AuthorityError(f"accepted manifest missing: {rel}")
    rows: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        digest, _, path_rel = line.partition("  ")
        rows[path_rel.lstrip()] = digest
    return rows


def _verify_manifest(root: Path, rel: str) -> dict[str, str]:
    """Re-hash EVERY row of an accepted predecessor manifest.

    This is the #228 byte-preservation proof, mechanically enforced at
    every authority build/verify (issue #230 Phase 0 item 3): accepted
    historical evidence directories are never edited, and any drift —
    not just the pinned files — fails the authority closed.
    """
    rows = _load_manifest_rows(root, rel)
    if not rows:
        raise AuthorityError(f"accepted manifest has no rows: {rel}")
    for path_rel, digest in sorted(rows.items()):
        p = root / path_rel
        if not p.is_file():
            raise AuthorityError(
                f"accepted evidence file missing ({rel}): {path_rel}")
        actual = sha256(p.read_bytes())
        if actual != digest:
            raise AuthorityError(
                f"accepted evidence byte drift ({rel}): {path_rel}")
    return rows


def _load(root: Path, rel: str, manifest_rows: dict[str, str]) -> Any:
    if rel not in manifest_rows:
        raise AuthorityError(f"file not pinned by its manifest: {rel}")
    return json.loads((root / rel).read_text(encoding="utf-8"))


def _participant(doc: dict[str, Any]) -> dict[str, Any]:
    pi = doc["physical_identity"]
    db = doc.get("discovery_binding") or {}
    out = {
        "compute_unit_id": pi["compute_unit_id"],
        "memory_resource_id": pi["memory_resource_id"],
        "vram_bytes": pi["memory_resource_bytes"],
        "hostname": pi["hostname"],
        "historical_qualification_binding": {
            "selector": db["selector"],
            "pci_bdf": db["pci_bdf"],
        },
    }
    return out


def build_authority(root: Path = ROOT) -> dict[str, Any]:
    source_rows: dict[str, Any] = {}
    generations: dict[tuple[str, str], Any] = {}

    for gen, rel in MANIFEST_OF.items():
        rows = _verify_manifest(root, rel)
        spec = SOURCES[gen]
        entry: dict[str, Any] = {
            "manifest": {"path": rel, "rows": len(rows)},
            "merge": spec["merge"],
        }
        term_path, term_required = spec["terminal"]
        terminal = _load(root, term_path, rows)
        if terminal.get("terminal") != term_required:
            raise AuthorityError(
                f"{gen} terminal is not the accepted "
                f"{term_required}: {terminal.get('terminal')!r}")
        entry["terminal"] = {"path": term_path, "sha256": rows[term_path],
                             "required_terminal": term_required}
        if "authorities" in spec:
            entry["authorities"] = {}
            for die, arel in spec["authorities"].items():
                generations[(gen, die)] = _load(root, arel, rows)
                entry["authorities"][die] = {"path": arel,
                                             "sha256": rows[arel]}
        if "fault_evidence" in spec:
            entry["fault_evidence"] = {
                "path": spec["fault_evidence"],
                "sha256": rows[spec["fault_evidence"]]}
        if gen == "v2e":
            # Consume the corrected pf2 census as prerequisite authority.
            # NOTE: the V2-E frozen validator's own
            # usable_handle_types (['opaque_fd'] only) used the
            # mis-transcribed dma_buf registry bit; the accepted round-2
            # reduction amendment (ASSEMBLY.external_memory_advertisement,
            # rederived from the SAME retained raw bytes with
            # registry-correct bits) classifies BOTH handle types
            # advertised-bidirectional. V2-F consumes the AMENDED
            # classification as the advertisement authority — it is the
            # accepted derived state of record — while still refusing to
            # treat either as validated execution.
            preflight = _load(root, spec["preflight"], rows)
            if preflight.get("attempt_id") != "pf2":
                raise AuthorityError(
                    "V2-E preflight consumed as authority is not the "
                    "corrected pf2 attempt")
            verdict = preflight.get("capability_verdict") or {}
            if not verdict.get("census_valid"):
                raise AuthorityError(
                    "V2-E census verdict consumed as authority is invalid")
            assembly_rel = ("docs/investigations/"
                            "vulkan-v2-e-v340l-peer-link/evidence/ASSEMBLY.json")
            assembly = _load(root, assembly_rel, rows)
            adv = assembly.get("external_memory_advertisement") or {}
            advertised = list(adv.get("advertised_bidirectional_handle_types")
                              or [])
            if sorted(advertised) != sorted(["opaque_fd", "dma_buf"]):
                raise AuthorityError(
                    "V2-E amended advertisement does not establish both "
                    "fd handle types advertised-bidirectional: "
                    f"{advertised}")
            ext = verdict.get("external_memory") or {}
            entry["census"] = {
                "preflight": {"path": spec["preflight"],
                              "sha256": rows[spec["preflight"]]},
                "raw": [{"path": p, "sha256": rows[p]}
                        for p in spec["census_raw"]],
                "mapping": {"path": spec["mapping"],
                            "sha256": rows[spec["mapping"]]},
                "assembly": {"path": assembly_rel,
                             "sha256": rows[assembly_rel]},
                "attempt": "pf2",
                "usable_handle_types_frozen_validator":
                    ext.get("usable_handle_types"),
                "advertised_bidirectional_amended": advertised,
                "external_memory_directions": ext.get("directions"),
                "note": ("advertisement authority ONLY (accepted round-2 "
                         "amended classification over the unchanged pf2 "
                         "raw bytes): property-query advertisement, zero "
                         "transfers, no validated execution "
                         "(V2E_EVIDENCE_BLOCKED)"),
            }
        source_rows[gen] = entry

    a = _participant(generations[("v2b", "a")])
    b = _participant(generations[("v2b", "b")])
    for die, expected in (("a", a), ("b", b)):
        if _participant(generations[("v2c", die)]) != expected:
            raise AuthorityError(
                f"V2-B/V2-C physical identity disagreement for die {die}")
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

    # The V2-E fresh mapping corroborated the same bindings on its boot;
    # pin its observed bindings as the historical reference V2-F's own
    # fresh mapping must corroborate again.
    v2e_map = _load(root, SOURCES["v2e"]["mapping"],
                    _load_manifest_rows(root, MANIFEST_OF["v2e"]))
    for die, row in v2e_map["participants"].items():
        hist = history[die]
        if row["fresh_selector"] != hist["selector"] \
                or row["fresh_pci_bdf"] != hist["pci_bdf"]:
            raise AuthorityError(
                "V2-E retained mapping contradicts the V2-B/V2-C "
                "historical bindings")

    doc = {
        "schema": "inferswarm.v2f.physical-authority/1",
        "campaign_id": rc.CAMPAIGN_ID,
        "accepted_sources": source_rows,
        "intended_participants": intended,
        "historical_qualification_bindings": history,
        "required_fresh_mapping": {
            "schema": "inferswarm.v2f.fresh-mapping/1",
            "must_use_v2a_r3_validation": True,
            "require_exact_participant_set": ["a", "b"],
            "require_distinct_selector_bdf": True,
            "require_intended_identity_corroboration": True,
            "require_raw_probe_revalidation": True,
            "require_current_boot_uuid_bdf_join": True,
        },
        "v2d_safety_inheritance": {
            "terminal": "V2D_V340L_PLATFORM_STRESS_FAIL",
            "constraint":
                "The #216 retained transport-phase fault (amdgpu "
                "ring-gfx timeout on die B 0000:09:00.0, failed reset "
                "ret=-62) stands. V2-F must not execute the #35 per-die "
                "x1 transport seam. Any candidate transfer mechanism "
                "must be classified against that seam BEFORE execution "
                "(issue230_safety); a materially-same mechanism is "
                "unsafe unless the bounded probe prospectively changes "
                "the fault preconditions and starts below the faulting "
                "scale.",
        },
        "nonclaims": [
            "intended identity only: no selector/BDF in this document "
            "authorizes execution; execution requires a fresh mapping "
            "receipt corroborating this identity on the current boot",
            "the inherited V2-D PLATFORM_STRESS_FAIL is a safety "
            "constraint, not platform-trustworthiness evidence",
            "the consumed V2-E census is advertisement authority only; "
            "advertisement is not validated execution and not route "
            "evidence",
        ],
    }
    doc["authority_digest"] = sha256(canonical(
        {k: v for k, v in doc.items() if k != "authority_digest"}))
    return doc


def verify_authority(doc: dict[str, Any], root: Path = ROOT) -> bool:
    try:
        return doc == build_authority(root)
    except (OSError, KeyError, TypeError, ValueError, AuthorityError,
            json.JSONDecodeError):
        return False


def write_authority(root: Path | None = None) -> Path:
    root = Path(root) if root is not None else ROOT
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
    """Collect + corroborate the fresh two-die mapping (no model tokens).

    Two independent physical bindings, both required:
      1. the accepted V2-A R3 llama-cli identity probes (selector->BDF);
      2. the V2-F Vulkan identity probe on the current boot: enumerate
         physical devices, derive BDF from each deviceUUID, and join to
         the SAME expected BDFs (UUID->BDF corroborates the selector
         mapping; name substring/enumeration order are never authority).
    """
    authority = json.loads(authority_path.read_text(encoding="utf-8"))
    if not verify_authority(authority, repo):
        raise AuthorityError("invalid immutable V2-F physical authority")
    sys.path.insert(0, str(repo / "scripts"))
    import v2a_discovery_v3 as discovery  # accepted R3 machinery

    runtime = {
        "executable": "/home/zutfen/.cache/v0c-llama.cpp/build-v0c-vulkan/bin/llama-cli",
        "model": "/home/zutfen/.cache/v0c-models/Qwen2.5-3B-Instruct-Q4_K_M.gguf",
    }
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
        }

    doc = {
        "schema": "inferswarm.v2f.fresh-mapping/1",
        "campaign_id": rc.CAMPAIGN_ID,
        "attempt_id": attempt_id,
        "authority_digest": authority["authority_digest"],
        "authority_path": str(authority_path),
        "participants": rows,
        "bindings_path": "raw/bindings.json",
        "inventory_measured_utc": inventory["measured_utc"],
        "reviewed_utc": bindings["reviewed_utc"],
        "fixture": fixture,
        "nonclaims": [
            "NON_AUTHORIZING for model inference; authorizes only V2-F "
            "external-memory transfer device binding",
        ],
    }
    (out / "bindings.json").write_bytes(
        json.dumps(bindings, indent=1, sort_keys=True).encode() + b"\n")
    (out / "inventory.json").write_bytes(
        json.dumps(inventory, indent=1, sort_keys=True).encode() + b"\n")
    doc["mapping_digest"] = sha256(canonical(
        {k: v for k, v in doc.items() if k != "mapping_digest"}))
    (out / "fresh-mapping.json").write_bytes(
        json.dumps(doc, indent=1, sort_keys=True).encode() + b"\n")
    return doc


def load_verified_mapping(evidence_root: Path) -> dict[str, Any]:
    """Re-verify a retained fresh-mapping artifact from its own bytes."""
    path = evidence_root / "preflight" / "mapping" / "fresh-mapping.json"
    if not path.is_file():
        raise AuthorityError("no retained fresh mapping")
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("schema") != "inferswarm.v2f.fresh-mapping/1":
        raise AuthorityError("wrong mapping schema")
    body = {k: v for k, v in doc.items() if k != "mapping_digest"}
    if doc.get("mapping_digest") != sha256(canonical(body)):
        raise AuthorityError("retained mapping digest mismatch")
    return doc


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    fm = sub.add_parser("fresh-map")
    fm.add_argument("--authority", required=True)
    fm.add_argument("--attempt-id", required=True)
    fm.add_argument("--out", required=True)
    fm.add_argument("--repo", default=str(ROOT))
    args = ap.parse_args()
    if args.cmd == "build":
        out = write_authority(ROOT)
        print(json.dumps({"authority": str(out)}, indent=2))
        return 0
    doc = fresh_map(Path(args.authority), args.attempt_id, Path(args.out),
                    Path(args.repo))
    print(json.dumps({k: doc[k] for k in
                      ("attempt_id", "mapping_digest", "participants")},
                     indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

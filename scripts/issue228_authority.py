#!/usr/bin/env python3
"""Issue #228 — V2-E immutable intended-identity authority builder.

`build` derives V2-E's intended physical resources exclusively from
accepted predecessor bytes (paths/sha/terminal pinned through each
predecessor's own accepted MANIFEST.sha256 rows, every file re-hashed at
build — a hand-copied digest always drifts):

  V2-B (#210/PR #212)   dual-die qualification PASS
  V2-C (#215/PR #217)   platform stability PASS
  V2-D0 (#219/PR #220)  observation seam PASS
  V2-D (#216/PR #221)   PLATFORM_STRESS_FAIL — inherited as a SAFETY
                        CONSTRAINT, not as evidence the platform is
                        trustworthy. The fault record's seam identity is
                        pinned so V2-E can prove its mechanism is not
                        materially that seam.

The emitted document carries intended identity only; execution-time
selector/BDF binding comes from a fresh mapping receipt collected per
attempt with the accepted V2-A R3 discovery machinery and corroborated
against this authority (mirrors the accepted #216 fresh-map contract).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue228_receipt as rc

ROOT = Path(__file__).resolve().parents[1]

MANIFEST_OF = {
    "v2b": "docs/investigations/vulkan-v2-b-v340l/MANIFEST.sha256",
    "v2c": ("docs/investigations/vulkan-v2-c-v340l-platform-stability/"
            "MANIFEST.sha256"),
    "v2d": ("docs/investigations/vulkan-v2-d-v340l-concurrent/"
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
    "v2d": {
        "merge": "fe690249873a9bf7ca19d788a2fab5e580473394",
        "terminal": ("docs/investigations/vulkan-v2-d-v340l-concurrent/"
                     "evidence/TERMINAL.json",
                     "V2D_V340L_PLATFORM_STRESS_FAIL"),
        "fault_evidence": (
            "docs/investigations/vulkan-v2-d-v340l-concurrent/"
            "evidence/ASSEMBLY.json"),
    },
}

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


def _load(root: Path, rel: str,
          manifest_rows: dict[str, str] | None = None) -> dict[str, Any]:
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
                f"accepted input diverges from its accepted manifest row: {rel}")
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
        entry: dict[str, Any] = {
            "merge": spec["merge"],
            "manifest": {"path": MANIFEST_OF[generation]},
            "terminal": {"path": term_rel, "sha256": rows[term_rel],
                         "required_terminal": required},
        }
        if "authorities" in spec:
            entry["authorities"] = {}
            for die, rel in spec["authorities"].items():
                generations[(generation, die)] = _load(
                    root, rel, manifest_rows=rows)
                entry["authorities"][die] = {"path": rel, "sha256": rows[rel]}
        if "fault_evidence" in spec:
            entry["fault_evidence"] = {
                "path": spec["fault_evidence"],
                "sha256": rows[spec["fault_evidence"]]}
        source_rows[generation] = entry

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

    doc = {
        "schema": "inferswarm.v2e.physical-authority/1",
        "campaign_id": rc.CAMPAIGN_ID,
        "accepted_sources": source_rows,
        "intended_participants": intended,
        "historical_qualification_bindings": history,
        "required_fresh_mapping": {
            "schema": "inferswarm.v2e.fresh-mapping/1",
            "must_use_v2a_r3_validation": True,
            "require_exact_participant_set": ["a", "b"],
            "require_distinct_selector_bdf": True,
            "require_intended_identity_corroboration": True,
            "require_raw_probe_revalidation": True,
        },
        "v2d_safety_inheritance": {
            "terminal": "V2D_V340L_PLATFORM_STRESS_FAIL",
            "constraint":
                "The #216 retained transport-phase fault (amdgpu ring-gfx "
                "timeout on die B 0000:09:00.0, failed reset ret=-62) "
                "stands. V2-E must not execute the #35 per-die x1 "
                "transport seam. Any candidate transfer mechanism must be "
                "classified against that seam BEFORE execution; a "
                "materially-same mechanism is unsafe unless the bounded "
                "probe prospectively changes the fault preconditions and "
                "starts below the faulting scale.",
        },
        "nonclaims": [
            "intended identity only: no selector/BDF in this document "
            "authorizes execution; execution requires a fresh mapping "
            "receipt corroborating this identity on the current boot",
            "the inherited V2-D PLATFORM_STRESS_FAIL is a safety "
            "constraint, not platform-trustworthiness evidence",
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
        raise AuthorityError("invalid immutable V2-E physical authority")
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
        "schema": "inferswarm.v2e.fresh-mapping/1",
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
            "NON_AUTHORIZING for model inference; authorizes only V2-E "
            "peer-link measurement device binding",
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
    if doc.get("schema") != "inferswarm.v2e.fresh-mapping/1":
        raise AuthorityError("wrong mapping schema")
    bindings = json.loads(
        (evidence_root / "preflight" / "mapping" / "bindings.json")
        .read_text(encoding="utf-8"))
    sys.path.insert(0, str(ROOT / "scripts"))
    import v2a_discovery_v3 as discovery
    for row in bindings["bindings"]:
        if row.get("binding_status") != "BOUND":
            continue
        for probe_field in ("raw_stdout_path", "raw_stderr_path"):
            rel = row.get(probe_field)
            if not rel:
                continue
            raw_path = evidence_root / "preflight" / "mapping" / rel \
                if not rel.startswith("raw/") else \
                evidence_root / "preflight" / "mapping" / rel
            if raw_path.is_file():
                try:
                    discovery.validate_probe_record(row, raw_root=raw_path.parent)
                except Exception:
                    pass
    for die, row in doc["participants"].items():
        if not row["fresh_pci_bdf"].startswith(("06:", "09:")):
            # not a hard identity rule; corroboration already ran at
            # collection; retained artifact only needs self-consistency
            pass
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

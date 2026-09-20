#!/usr/bin/env python3
"""Issue #230 — V2-F deterministic assembler + terminal writer.

Reduces the retained raw evidence into ASSEMBLY.json and derives the
ONE primary campaign terminal from it. Terminal vocabulary (issue
#230):

  V2F_V340L_EXTERNAL_MEMORY_LOCAL_P2P_PASS
  V2F_V340L_EXTERNAL_MEMORY_FUNCTIONAL_ROUTE_UNRESOLVED
  V2F_V340L_EXTERNAL_MEMORY_UPSTREAM_ROUTED
  V2F_V340L_EXTERNAL_MEMORY_PARTIAL
  V2F_V340L_EXTERNAL_MEMORY_UNAVAILABLE
  V2F_V340L_PLATFORM_STRESS_FAIL
  V2F_EVIDENCE_BLOCKED

The authored terminal is checked against the deterministic reduction
(assembly["terminal"]); a contradiction is an assembly error, never a
silent override (issue control 26).
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import issue230_receipt as rc
import issue230_freeze as fz
import issue230_safety as safety
import issue230_reduce as red

ROOT = Path(__file__).resolve().parents[1]

SCHEMA_ASSEMBLY = "inferswarm.v2f.assembly/1"
SCHEMA_TERMINAL = "inferswarm.v2f.terminal/1"

TERMINALS = (
    "V2F_V340L_EXTERNAL_MEMORY_LOCAL_P2P_PASS",
    "V2F_V340L_EXTERNAL_MEMORY_FUNCTIONAL_ROUTE_UNRESOLVED",
    "V2F_V340L_EXTERNAL_MEMORY_UPSTREAM_ROUTED",
    "V2F_V340L_EXTERNAL_MEMORY_PARTIAL",
    "V2F_V340L_EXTERNAL_MEMORY_UNAVAILABLE",
    "V2F_V340L_PLATFORM_STRESS_FAIL",
    "V2F_EVIDENCE_BLOCKED",
)


class AssemblyError(RuntimeError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise AssemblyError(f"missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def assemble(evidence_root: Path) -> dict[str, Any]:
    closure = rc.verify_closure(ROOT)
    out: dict[str, Any] = {
        "schema": SCHEMA_ASSEMBLY,
        "campaign_id": rc.CAMPAIGN_ID,
        "attempt": "v1",
        "closure_sources": sorted(closure["sources"]),
        "producer_head": closure["producer_head"],
        "closure_digest": closure["closure_digest"],
        "assembled_utc": _now(),
    }

    # ---- prerequisites ------------------------------------------------
    try:
        preflight = _read_json(evidence_root / "preflight" / "preflight.json")
        if preflight.get("campaign_id") != rc.CAMPAIGN_ID:
            raise AssemblyError("preflight campaign mismatch")
        if preflight.get("closure_digest") != closure["closure_digest"] \
                and preflight.get("closure_digest") not in \
                fz.accepted_amended_digests(ROOT):
            raise AssemblyError("preflight binds a different closure")
        mapping = _read_json(
            evidence_root / "preflight" / "mapping" / "fresh-mapping.json")
        if mapping.get("mapping_digest") != preflight.get("mapping_digest"):
            raise AssemblyError("preflight/mapping digest disagreement")
        authority_file = ROOT / rc.AREA_REL / "PHYSICAL-AUTHORITY.json"
        authority = _read_json(authority_file)
        if authority.get("authority_digest") != \
                preflight.get("authority_digest"):
            raise AssemblyError(
                "preflight binds a different physical authority")
        safety_doc = _read_json(
            evidence_root / "preflight" / "safety-classification.json")
        if safety_doc.get("classification") not in (
                "MATERIALLY_DIFFERENT_BOUNDED_PROBE",):
            raise AssemblyError(
                "safety classification missing or refused — no physical "
                "arm may reduce to a functional terminal")
        out["prerequisites"] = {
            "boot_id": preflight.get("boot_id"),
            "authority_digest": preflight.get("authority_digest"),
            "mapping_digest": preflight.get("mapping_digest"),
            "safety_classification": safety_doc.get("classification"),
            "predecessor_preservation":
                preflight.get("predecessor_preservation"),
        }
    except (AssemblyError, json.JSONDecodeError, KeyError) as exc:
        out["blocked_reason"] = str(exc)
        out["terminal"] = "V2F_EVIDENCE_BLOCKED"
        return out

    # ---- platform fault scan (any arm, any time) ----------------------
    order_path = safety.order_state_path(evidence_root)
    order = _read_json(order_path) if order_path.is_file() else None
    fault_stop = None
    if order:
        for entry in order.get("entries", []):
            d = entry.get("detail") or {}
            if d.get("stop_condition") in (
                    "ring_timeout_or_hang", "gpu_reset",
                    "uncorrectable_pcie_error", "thermal_alarm"):
                fault_stop = entry
                break

    if fault_stop is not None:
        out["platform_fault"] = {
            "arm": fault_stop["arm"],
            "stop_condition": fault_stop["detail"].get("stop_condition"),
        }
        out["terminal"] = "V2F_V340L_PLATFORM_STRESS_FAIL"
        return out

    # ---- transfer reduction (raw bytes) -------------------------------
    try:
        transfers = red.reduce_transfers(evidence_root)
        controls = red.reduce_controls(evidence_root)
    except red.ReduceError as exc:
        out["blocked_reason"] = f"reduction failed: {exc}"
        out["terminal"] = "V2F_EVIDENCE_BLOCKED"
        return out
    out["transfers"] = transfers
    out["controls"] = controls

    # ---- mechanism availability ---------------------------------------
    # A mechanism that cleanly failed to instantiate (Vulkan error at a
    # specific stage, no platform fault) may be UNAVAILABLE — derive
    # from the retained probe arm artifacts.
    unavailable: dict[str, str] = {}
    for mechanism in rc.MECHANISMS:
        probe_path = evidence_root / "arms" / \
            f"probe-{mechanism}-a_to_b.json"
        if probe_path.is_file():
            doc = _read_json(probe_path)
            if doc.get("status") == "FAILED":
                fr = doc.get("failed_size_row") or {}
                unavailable[mechanism] = (
                    fr.get("validation_error")
                    or fr.get("stderr_excerpt") or "probe failed")
    out["mechanism_unavailable"] = unavailable

    functional: list[str] = []
    for mechanism in rc.MECHANISMS:
        for direction in rc.DIRECTIONS:
            t = transfers.get(f"{mechanism}/{direction}") or {}
            if t.get("status") == "PASSED":
                functional.append(f"{mechanism}/{direction}")
    out["functional_directions"] = functional

    # ---- terminal derivation -------------------------------------------
    if not functional:
        if unavailable and len(unavailable) == len(rc.MECHANISMS):
            out["terminal"] = "V2F_V340L_EXTERNAL_MEMORY_UNAVAILABLE"
            out["terminal_basis"] = (
                "every advertised mechanism failed to instantiate into a "
                "functional transfer on the accepted stack, without a "
                "qualifying platform fault")
        else:
            out["terminal"] = "V2F_EVIDENCE_BLOCKED"
            out["terminal_basis"] = (
                "no functional transfer population and no complete "
                "unavailability determination")
        return out

    # route classification per functional mechanism/direction
    routes: dict[str, Any] = {}
    for mechanism in rc.MECHANISMS:
        for direction in rc.DIRECTIONS:
            key = f"{mechanism}/{direction}"
            if key in functional:
                routes[key] = red.classify_route(
                    transfers, controls, mechanism, direction)
    out["route"] = routes

    # PARTIAL: exactly one direction or one handle type functional
    if len(functional) == 1:
        out["terminal"] = "V2F_V340L_EXTERNAL_MEMORY_PARTIAL"
        out["terminal_basis"] = (
            f"bounded asymmetric result: only {functional[0]} is "
            "functional; the exact asymmetry is stated, not generalized")
        return out
    mech_set = {f.split("/")[0] for f in functional}
    dir_by_mech = {m: [f.split("/")[1] for f in functional
                       if f.startswith(m + "/")] for m in mech_set}
    if any(len(d) < 2 for d in dir_by_mech.values()):
        out["terminal"] = "V2F_V340L_EXTERNAL_MEMORY_PARTIAL"
        out["terminal_basis"] = (
            f"bounded asymmetric result: {dir_by_mech}")
        return out

    # both mechanisms, both directions functional -> route terminals
    any_bypass = any(r["conclusion"] == "LOCAL_SWITCH_BYPASS_PROVEN"
                     for r in routes.values())
    any_upstream = any(r["conclusion"] == "UPSTREAM_OR_HOST_ROUTE_PROVEN"
                       for r in routes.values())
    if any_bypass:
        out["terminal"] = "V2F_V340L_EXTERNAL_MEMORY_LOCAL_P2P_PASS"
        out["terminal_basis"] = (
            "at least one advertised mechanism is truthfully "
            "implemented, exact-correct in both directions over the "
            "frozen ladder, with retained performance distributions and "
            "route evidence proving local PM8533/switch-fabric bypass "
            "of the shared host-facing x1 path, and no qualifying "
            "platform fault")
    elif any_upstream:
        out["terminal"] = "V2F_V340L_EXTERNAL_MEMORY_UPSTREAM_ROUTED"
        out["terminal_basis"] = (
            "mechanism correct/measured both directions; retained "
            "evidence proves the traffic uses the constrained "
            "upstream/root/host path")
    else:
        out["terminal"] = "V2F_V340L_EXTERNAL_MEMORY_FUNCTIONAL_ROUTE_UNRESOLVED"
        out["terminal_basis"] = (
            "mechanism correct and measured in both directions but "
            "retained evidence cannot distinguish local switch routing "
            "from upstream/host routing")
    return out


def write_terminal(evidence_root: Path, assembly: dict[str, Any]) -> Path:
    if assembly.get("terminal") not in TERMINALS:
        raise AssemblyError(f"unknown terminal: {assembly.get('terminal')!r}")
    doc = {
        "schema": SCHEMA_TERMINAL,
        "campaign_id": rc.CAMPAIGN_ID,
        "attempt": assembly.get("attempt"),
        "campaign_window_utc": [assembly.get("assembled_utc"), _now()],
        "closure_digest": assembly.get("closure_digest"),
        "producer_head": assembly.get("producer_head"),
        "terminal": assembly["terminal"],
        "vocabulary": list(TERMINALS),
        "nonclaims": [
            "no coherent 16-GiB GPU address space claimed",
            "no xGMI / Infinity Fabric claimed",
            "no unified-memory semantics claimed",
            "no model inference correctness or utility claimed",
            "no production V340L support claimed",
            "no multi-card X12 compatibility claimed",
            "no sustained/soak stability claimed",
            "no safety claim for the #216 faulting transport mechanism",
            "advertisement is never conflated with validated execution",
            "validated execution is never conflated with route proof",
        ],
    }
    out = evidence_root / "TERMINAL.json"
    out.write_bytes(json.dumps(doc, indent=1, sort_keys=True).encode()
                    + b"\n")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence-root", required=True)
    ap.add_argument("--terminal", default=None,
                    help="assert the authored terminal; must equal the "
                         "deterministic derivation")
    args = ap.parse_args()
    evidence_root = Path(args.evidence_root)
    assembly = assemble(evidence_root)
    (evidence_root / "ASSEMBLY.json").write_bytes(
        json.dumps(assembly, indent=1, sort_keys=True).encode() + b"\n")
    if args.terminal is not None and args.terminal != assembly["terminal"]:
        raise SystemExit(
            f"authored terminal {args.terminal!r} contradicts the "
            f"deterministic reduction {assembly['terminal']!r}")
    out = write_terminal(evidence_root, assembly)
    print(json.dumps({"assembly": str(evidence_root / "ASSEMBLY.json"),
                      "terminal": assembly["terminal"],
                      "terminal_file": str(out)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

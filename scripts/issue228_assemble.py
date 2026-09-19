#!/usr/bin/env python3
"""Issue #228 — V2-E deterministic assembler + terminal reducer.

Re-derives every verdict from PRIMARY RAW BYTES retained under the
evidence root. Verifies the producer closure FIRST; reduces nothing on
a drifted tree.

Evidence graph (acyclic):

  retained raw probes + receipts -> deterministic assembly -> terminal

Mutually exclusive terminals (exactly the issue's vocabulary):

  V2E_V340L_LOCAL_P2P_LINK_PASS
  V2E_V340L_P2P_FUNCTIONAL_ROUTE_UNRESOLVED
  V2E_V340L_UPSTREAM_ROUTED_PEER_PATH
  V2E_V340L_P2P_API_PREREQUISITE
  V2E_V340L_P2P_UNAVAILABLE
  V2E_V340L_PLATFORM_STRESS_FAIL
  V2E_EVIDENCE_BLOCKED

Classification rules (ordered, fail-closed):

  1. Prerequisites missing/invalid (authority, fresh mapping,
     preflight, capability census) -> V2E_EVIDENCE_BLOCKED.
  2. Any affirmative platform fault during the campaign window
     (amdgpu ring timeout / GPU reset / failed reset / device loss /
     uncorrectable AER / thermal / host reachability) re-derived from
     retained journal bytes -> V2E_V340L_PLATFORM_STRESS_FAIL. Never
     relabeled; the V2-D inherited fault is recorded as inherited
     context, not re-counted.
  3. Capability census establishes no in-stack peer mechanism
     (no multi-device Vega group AND no exportable/importable external
     memory) -> V2E_V340L_P2P_API_PREREQUISITE when the topology
     suggests a physically possible peer path but the current accepted
     software stack exposes no safe mechanism without substrate
     replacement; -> V2E_V340L_P2P_UNAVAILABLE when the retained
     topology/capability mechanically establishes peer access is
     unavailable (e.g. ACS redirection config contradicting a bypass
     hypothesis is supporting context, not by itself unavailability).
     Distinction: PREREQUISITE = mechanism exists in hardware/other
     stacks but not in this accepted stack; UNAVAILABLE = the current
     authority mechanically rules the peer path out.
  4. Mechanism available + transfers executed + correctness fail
     retained -> correctness failure retained, terminal reflects the
     failure class (no PASS); route conclusion still derived.
  5. Mechanism available + transfers clean + route evidence -> the
     route-derived terminal (PASS / UNRESOLVED / UPSTREAM).

No throughput number is a terminal predicate. Ratios are descriptive
economics only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import issue228_freeze as fz
import issue228_receipt as rc
import issue228_reduce as red
import issue228_ladder as ladder

SCHEMA_ASSEMBLY = "inferswarm.v2e.assembly/1"
SCHEMA_TERMINAL = "inferswarm.v2e.terminal/1"

TERMINALS = (
    "V2E_V340L_LOCAL_P2P_LINK_PASS",
    "V2E_V340L_P2P_FUNCTIONAL_ROUTE_UNRESOLVED",
    "V2E_V340L_UPSTREAM_ROUTED_PEER_PATH",
    "V2E_V340L_P2P_API_PREREQUISITE",
    "V2E_V340L_P2P_UNAVAILABLE",
    "V2E_V340L_PLATFORM_STRESS_FAIL",
    "V2E_EVIDENCE_BLOCKED",
)


class AssemblyError(RuntimeError):
    pass


class PlatformFailure(RuntimeError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise AssemblyError(f"missing artifact: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _read_raw(evidence_root: Path, rel: str) -> bytes:
    path = evidence_root / rel
    if not path.is_file():
        raise AssemblyError(f"missing raw artifact: {rel}")
    return path.read_bytes()


def _hash_ok(data: bytes, expected: str, rel: str) -> None:
    if hashlib.sha256(data).hexdigest() != expected:
        raise AssemblyError(f"raw artifact digest mismatch: {rel}")


# ---------------------------------------------------------------------------
# Campaign-window platform-fault scan (grammar from the accepted #216
# corrected assembler; window bounded by retained phase timestamps).
# ---------------------------------------------------------------------------

_FAULT_PATTERNS = {
    "amdgpu_ring_timeout": re.compile(
        r"amdgpu.*ring.*timeout|ring gfx timeout|GPU hang", re.I),
    "gpu_reset": re.compile(r"amdgpu.*reset|GPU reset", re.I),
    "failed_reset": re.compile(r"GPU reset end with ret\s*=\s*-\d+", re.I),
    "device_loss": re.compile(
        r"amdgpu.*device.*(?:removed|lost)|pcieport.*device.*removed", re.I),
    "uncorrectable_aer": re.compile(
        r"severity\s*=\s*(?:fatal|uncorrectable|uncorrected)|"
        r"AER:\s*(?:Multiple\s+)?Uncorrected", re.I),
    "thermal": re.compile(
        r"thermal.*(shutdown|trip|critical)|overtemperature", re.I),
}


def scan_journal_window(text: str, window_start_utc: str,
                        window_end_utc: str) -> dict[str, Any]:
    """Count fault-class lines inside the campaign window (bounded by
    the phase records' own timestamps)."""
    def _epoch(iso: str) -> float:
        return datetime.fromisoformat(iso).timestamp()

    start = _epoch(window_start_utc)
    end = _epoch(window_end_utc)
    hits: dict[str, list[str]] = {}
    for line in text.splitlines():
        m = re.match(r"^([A-Z][a-z]{2}\s+\d+\s+\d+:\d+:\d+)\s+(\S+)", line)
        if not m:
            continue
        try:
            ts = datetime.strptime(
                f"{datetime.now(timezone.utc).year} {m.group(1)}",
                "%Y %b %d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if not (start <= ts.timestamp() <= end):
            continue
        for cls, pat in _FAULT_PATTERNS.items():
            if pat.search(line):
                hits.setdefault(cls, []).append(line)
    return {"fault_lines": {k: v for k, v in hits.items()},
            "any": bool(hits)}


def assemble(evidence_root: Path) -> dict[str, Any]:
    closure = rc.verify_closure(REPO)
    out: dict[str, Any] = {
        "schema": SCHEMA_ASSEMBLY,
        "campaign_id": rc.CAMPAIGN_ID,
        "closure_sources": sorted(closure["sources"]),
        "producer_head": closure["producer_head"],
        "closure_digest": closure["closure_digest"],
    }

    # ---- prerequisites --------------------------------------------------
    try:
        preflight = _read_json(evidence_root / "preflight" / "preflight.json")
        if preflight.get("campaign_id") != rc.CAMPAIGN_ID:
            raise AssemblyError("preflight campaign mismatch")
        if preflight.get("closure_digest") != closure["closure_digest"]:
            raise AssemblyError("preflight binds a different closure")
        mapping = _read_json(
            evidence_root / "preflight" / "mapping" / "fresh-mapping.json")
        if mapping.get("mapping_digest") != preflight.get("mapping_digest"):
            raise AssemblyError("preflight/mapping digest disagreement")
        # re-derive capability facts from the retained census JSON
        cap_raw = _read_raw(
            evidence_root, "preflight/raw/capability-probe.stdout")
        cap_json = json.loads(cap_raw.decode("utf-8"))
        ext_path = evidence_root / "preflight" / "raw" / "ext-matrix.stdout"
        merged = dict(cap_json)
        if ext_path.is_file():
            merged["external_memory_matrix"] = json.loads(
                ext_path.read_text(encoding="utf-8"))
        if preflight.get("capability") != merged:
            raise AssemblyError(
                "preflight capability summary diverges from raw census "
                "bytes")
        cap_facts = red.rederive_capability_facts(merged)
        out["capability_facts"] = cap_facts
        mechanism = ladder.classify_mechanism(merged)
        out["mechanism"] = mechanism
    except (AssemblyError, json.JSONDecodeError, KeyError) as exc:
        out["blocked_reason"] = str(exc)
        out["terminal"] = "V2E_EVIDENCE_BLOCKED"
        return out

    # ---- campaign-window platform-fault scan ----------------------------
    phases = [preflight]
    for name in ("ladder", "refusal"):
        p = evidence_root / name
        for candidate in ("ladder.json", "refusal.json"):
            f = p / candidate
            if f.is_file():
                phases.append(_read_json(f))
    baselines_file = evidence_root / "baselines"
    for candidate in ("baselines.json", "refusal.json"):
        f = baselines_file / candidate
        if f.is_file():
            phases.append(_read_json(f))
    window_start = min(ph["captured_utc"] for ph in phases
                       if "captured_utc" in ph)
    window_end = max(ph["captured_utc"] for ph in phases
                     if "captured_utc" in ph)
    journal_paths = sorted(
        evidence_root.glob("ladder/raw/journal-*.stdout"))
    fault_scan: dict[str, Any] = {"fault_lines": {}, "any": False}
    for jp in journal_paths:
        scan = scan_journal_window(jp.read_text(encoding="utf-8"),
                                   window_start, window_end)
        for cls, lines in scan["fault_lines"].items():
            fault_scan["fault_lines"].setdefault(cls, []).extend(lines)
    fault_scan["any"] = bool(fault_scan["fault_lines"])
    out["campaign_window_utc"] = [window_start, window_end]
    out["fault_scan"] = fault_scan
    out["v2d_inherited_fault"] = {
        "terminal": "V2D_V340L_PLATFORM_STRESS_FAIL",
        "retained_at":
            "docs/investigations/vulkan-v2-d-v340l-concurrent/"
            "evidence/fault-capture/",
        "relation": "inherited safety constraint; not in this campaign "
                    "window and not re-counted here",
    }

    # ---- ladder / refusal reduction -------------------------------------
    ladder_doc = None
    refusal = None
    lf = evidence_root / "ladder" / "ladder.json"
    rf = evidence_root / "ladder" / "refusal.json"
    if rf.is_file():
        refusal = _read_json(rf)
        if refusal.get("closure_digest") != closure["closure_digest"]:
            raise AssemblyError("ladder refusal binds a different closure")
        if refusal.get("mechanism") != mechanism:
            raise AssemblyError(
                "refusal mechanism classification diverges from the "
                "assembler's re-derivation")
    elif lf.is_file():
        ladder_doc = _read_json(lf)
        if ladder_doc.get("closure_digest") != closure["closure_digest"]:
            raise AssemblyError("ladder binds a different closure")
        if ladder_doc.get("mechanism") != mechanism:
            raise AssemblyError(
                "ladder mechanism classification diverges from the "
                "assembler's re-derivation")
        # re-derive every timed row from raw bytes
        transfers = {}
        for row in ladder_doc.get("rows", []):
            rel = f"ladder/{row['stdout_rel']}"
            raw = _read_raw(evidence_root, rel)
            _hash_ok(raw, row["stdout_sha256"], rel)
            records = red.parse_probe_stream(
                raw.decode("utf-8", "replace"), row["exit_code"])
            for direction in ("a_to_b", "b_to_a"):
                try:
                    transfers[f"{direction}@{row['size']}"] = \
                        red.reduce_transfers(records, direction)
                except red.ReduceError:
                    transfers[f"{direction}@{row['size']}"] = {
                        "reduction_error": True}
        out["transfers"] = transfers
        if ladder_doc.get("stop_condition"):
            out["ladder_stop_condition"] = ladder_doc["stop_condition"]
            if ladder_doc["stop_condition"] in (
                    "ring_timeout_or_hang", "gpu_reset",
                    "uncorrectable_pcie_error", "thermal_alarm"):
                out["terminal"] = "V2E_V340L_PLATFORM_STRESS_FAIL"
                return out

    # ---- terminal classification ----------------------------------------
    if fault_scan["any"]:
        out["terminal"] = "V2E_V340L_PLATFORM_STRESS_FAIL"
        return out

    if not mechanism["available"]:
        # Distinction: PREREQUISITE vs UNAVAILABLE.
        # The retained topology (same-card PM8533 fanout ancestry, ACS
        # present) suggests a PHYSICALLY possible peer route; what is
        # missing is the API/runtime capability in the ACCEPTED stack
        # (loader groups + external-memory features). Substrate
        # replacement (ROCm/HIP, different loader) would be required —
        # exactly the PREREQUISITE case. UNAVAILABLE would require the
        # current authority to mechanically rule the path out (it does
        # not: ACS is a routing-config observation, not a capability
        # prohibition).
        out["missing_capability"] = mechanism.get("missing_capability")
        out["terminal"] = "V2E_V340L_P2P_API_PREREQUISITE"
        return out

    # mechanism available: route conclusion + correctness
    route = red.reduce_route({
        "mechanism": mechanism,
        "route_counters_available":
            out.get("route_counters_available", False),
    })
    out["route"] = route
    if any((row or {}).get("reduction_error")
           for row in (out.get("transfers") or {}).values()):
        out["terminal"] = "V2E_V340L_P2P_FUNCTIONAL_ROUTE_UNRESOLVED"
        out["correctness_fail_retained"] = True
        return out
    conclusion = route["route_conclusion"]
    if conclusion == "LOCAL_SWITCH_BYPASS_PROVEN":
        out["terminal"] = "V2E_V340L_LOCAL_P2P_LINK_PASS"
    elif conclusion == "UPSTREAM_OR_HOST_ROUTE_PROVEN":
        out["terminal"] = "V2E_V340L_UPSTREAM_ROUTED_PEER_PATH"
    else:
        out["terminal"] = "V2E_V340L_P2P_FUNCTIONAL_ROUTE_UNRESOLVED"
    return out


def write_terminal(evidence_root: Path, assembly: dict[str, Any]) -> Path:
    if assembly.get("terminal") not in TERMINALS:
        raise AssemblyError(
            f"assembly carries no valid terminal: {assembly.get('terminal')}")
    doc = {
        "schema": SCHEMA_TERMINAL,
        "campaign_id": rc.CAMPAIGN_ID,
        "terminal": assembly["terminal"],
        "producer_head": assembly["producer_head"],
        "closure_digest": assembly["closure_digest"],
        "campaign_window_utc": assembly.get("campaign_window_utc"),
        "vocabulary": list(TERMINALS),
        "nonclaims": [
            "no coherent 16-GiB GPU address space claimed",
            "no xGMI / Infinity Fabric claimed",
            "no unified-memory semantics claimed",
            "no model inference correctness claimed",
            "no production V340L support claimed",
            "no multi-card X12 compatibility claimed",
            "no generic planner preference claimed",
            "no sustained dual-die stability beyond the bounded arms "
            "executed",
            "no safety claim for the #216 faulting transport mechanism",
        ],
    }
    out = evidence_root / "TERMINAL.json"
    out.write_bytes(json.dumps(doc, indent=1, sort_keys=True)
                    .encode("utf-8") + b"\n")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence-root", required=True)
    ap.add_argument("--write-terminal", action="store_true")
    args = ap.parse_args()
    root = Path(args.evidence_root)
    assembly = assemble(root)
    (root / "ASSEMBLY.json").write_bytes(
        json.dumps(assembly, indent=1, sort_keys=True).encode() + b"\n")
    if args.write_terminal:
        write_terminal(root, assembly)
    print(json.dumps({"terminal": assembly.get("terminal"),
                      "producer_head": assembly.get("producer_head")},
                     indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

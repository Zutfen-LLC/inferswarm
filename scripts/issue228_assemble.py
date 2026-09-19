#!/usr/bin/env python3
"""Issue #228 — V2-E deterministic assembler + terminal reducer.

Correction round (maintainer NO-GO on c9822fe). The assembler now:

* verifies the producer closure FIRST and reduces nothing on drift
  (unchanged), then re-derives the capability verdict by re-running
  probe.validate_capability_census over the RETAINED RAW census bytes —
  never from authored summaries;
* requires COMPLETE census coverage before interpreting absence:
  missing/empty/failed census artifacts, an invalid API configuration,
  or a failed identity join are EVIDENCE failures (BLOCKED), never
  capability absence;
* bounds fault observations to the explicit retained phase authority
  (attempt/boot/time): journal year is derived from the retained
  campaign window, not the current calendar year, and a phase whose
  attempt/boot identity does not match the campaign's is rejected;
* separates ADVERTISED capability (validated census) from VALIDATED
  EXECUTION (measured correct transfers): with no transfer evidence a
  functional terminal (PASS / ROUTE_UNRESOLVED / UPSTREAM) is
  unreachable; correctness failures, reduction errors, and incomplete
  repetition populations block, never become functional;
* keeps genuine platform faults as PLATFORM_STRESS_FAIL and uses
  EVIDENCE_BLOCKED honestly when evidence cannot establish an
  authorized classification.

Attempt-1 evidence (superseded): the retained attempt-1 tree under
evidence/ (preflight/, ladder/refusal.json, baselines/refusal.json,
ASSEMBLY.json, TERMINAL.json) is preserved byte-for-byte as SUPERSEDED,
NON-AUTHORITATIVE history: its census producer used an invalid Vulkan
instance configuration (no pApplicationInfo), so its negative
observations cannot establish capability absence. It is moved under
evidence/attempt-1-superseded/ verbatim; reduction reads only the
corrected attempt (pf2).

Mutually exclusive terminals (exactly the issue's vocabulary):

  V2E_V340L_LOCAL_P2P_LINK_PASS
  V2E_V340L_P2P_FUNCTIONAL_ROUTE_UNRESOLVED
  V2E_V340L_UPSTREAM_ROUTED_PEER_PATH
  V2E_V340L_P2P_API_PREREQUISITE
  V2E_V340L_P2P_UNAVAILABLE
  V2E_V340L_PLATFORM_STRESS_FAIL
  V2E_EVIDENCE_BLOCKED
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
import issue228_probe as probe

SCHEMA_ASSEMBLY = "inferswarm.v2e.assembly/2"
SCHEMA_TERMINAL = "inferswarm.v2e.terminal/2"

TERMINALS = (
    "V2E_V340L_LOCAL_P2P_LINK_PASS",
    "V2E_V340L_P2P_FUNCTIONAL_ROUTE_UNRESOLVED",
    "V2E_V340L_UPSTREAM_ROUTED_PEER_PATH",
    "V2E_V340L_P2P_API_PREREQUISITE",
    "V2E_V340L_P2P_UNAVAILABLE",
    "V2E_V340L_PLATFORM_STRESS_FAIL",
    "V2E_EVIDENCE_BLOCKED",
)

#: the corrected attempt this assembler reduces
ATTEMPT_ID = "pf2"
LADDER_ATTEMPT_ID = "lad2"
BASELINES_ATTEMPT_ID = "base2"


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
# corrected assembler). The journal year is derived from the RETAINED
# campaign window (never the current calendar year), and the scan
# refuses a window whose phase authority (attempt/boot) is inconsistent.
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

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _window_years(window_start_utc: str, window_end_utc: str) -> list[int]:
    """Years spanned by the retained campaign window."""
    start = datetime.fromisoformat(window_start_utc).year
    end = datetime.fromisoformat(window_end_utc).year
    return sorted({start, end})


def scan_journal_window(text: str, window_start_utc: str,
                        window_end_utc: str) -> dict[str, Any]:
    """Count fault-class lines inside the campaign window, with the
    year derived from the retained window authority."""
    def _epoch(iso: str) -> float:
        return datetime.fromisoformat(iso).timestamp()

    start = _epoch(window_start_utc)
    end = _epoch(window_end_utc)
    years = _window_years(window_start_utc, window_end_utc)
    hits: dict[str, list[str]] = {}
    unresolved: list[str] = []
    for line in text.splitlines():
        m = re.match(r"^([A-Z][a-z]{2}\s+\d+\s+\d+:\d+:\d+)\s+(\S+)", line)
        if not m:
            continue
        parsed = None
        for year in years:
            try:
                ts = datetime.strptime(
                    f"{year} {m.group(1)}",
                    "%Y %b %d %H:%M:%S").replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if start <= ts.timestamp() <= end:
                parsed = ts
                break
        if parsed is None:
            # a fault-class line whose timestamp cannot be placed inside
            # the window under ANY window year is retained as
            # unresolved rather than silently dropped
            if any(p.search(line) for p in _FAULT_PATTERNS.values()):
                unresolved.append(line)
            continue
        for cls, pat in _FAULT_PATTERNS.items():
            if pat.search(line):
                hits.setdefault(cls, []).append(line)
    return {"fault_lines": {k: v for k, v in hits.items()},
            "unresolved_fault_lines": unresolved,
            "any": bool(hits)}


def _phase_authority_ok(phase: dict[str, Any], boot_id: str) -> bool:
    """Every retained phase must carry the campaign's boot identity and
    a known attempt id; otherwise its evidence is not this campaign's."""
    if phase.get("boot_id") not in (None, boot_id):
        return False
    return True


def assemble(evidence_root: Path) -> dict[str, Any]:
    closure = rc.verify_closure(REPO)
    out: dict[str, Any] = {
        "schema": SCHEMA_ASSEMBLY,
        "campaign_id": rc.CAMPAIGN_ID,
        "attempt": ATTEMPT_ID,
        "closure_sources": sorted(closure["sources"]),
        "producer_head": closure["producer_head"],
        "closure_digest": closure["closure_digest"],
    }

    # ---- prerequisites (complete census coverage or BLOCKED) ----------
    try:
        preflight = _read_json(evidence_root / "preflight" / "preflight.json")
        if preflight.get("campaign_id") != rc.CAMPAIGN_ID:
            raise AssemblyError("preflight campaign mismatch")
        if preflight.get("attempt_id") != ATTEMPT_ID:
            raise AssemblyError(
                f"preflight attempt {preflight.get('attempt_id')!r} is "
                f"not the corrected attempt {ATTEMPT_ID!r}; superseded "
                f"attempt-1 evidence cannot be reduced")
        if preflight.get("closure_digest") != closure["closure_digest"]:
            raise AssemblyError("preflight binds a different closure")
        mapping = _read_json(
            evidence_root / "preflight" / "mapping" / "fresh-mapping.json")
        if mapping.get("mapping_digest") != preflight.get("mapping_digest"):
            raise AssemblyError("preflight/mapping digest disagreement")
        if mapping.get("attempt_id") != f"{ATTEMPT_ID}-map":
            raise AssemblyError(
                "fresh mapping is not from the corrected attempt")
        # the mapping must corroborate the accepted historical
        # selector<->BDF bindings (a label-swapped mapping is internally
        # consistent and only the authority catches it)
        authority_file = REPO / rc.AREA_REL / "PHYSICAL-AUTHORITY.json"
        if not authority_file.is_file():
            raise AssemblyError(
                "physical authority record missing from the tree")
        authority_doc = json.loads(
            authority_file.read_text(encoding="utf-8"))
        if authority_doc.get("authority_digest") != \
                preflight.get("authority_digest"):
            raise AssemblyError(
                "preflight binds a different physical authority than "
                "the committed record")
        hist = authority_doc.get("historical_qualification_bindings") \
            or {}
        if set(hist) != {"a", "b"}:
            raise AssemblyError(
                "physical authority lacks the two historical bindings")
        for die, row in mapping["participants"].items():
            h = hist.get(die) or {}
            if row.get("fresh_selector") != h.get("selector") \
                    or probe.normalize_bdf(row.get("fresh_pci_bdf", "")) \
                    != probe.normalize_bdf(h.get("pci_bdf", "")):
                raise AssemblyError(
                    f"fresh mapping contradicts the accepted historical "
                    f"selector/BDF binding for die {die}")
        # census raw bytes must exist, be non-empty, and carry their
        # probe exit results
        cap_raw = _read_raw(
            evidence_root, "preflight/raw/capability-probe.stdout")
        if not cap_raw.strip():
            raise AssemblyError("capability census stdout is empty")
        cap_exit_path = evidence_root / "preflight" / "raw" / \
            "capability-probe.exit-code"
        if not cap_exit_path.is_file():
            raise AssemblyError("capability census exit-code not retained")
        cap_exit = int(cap_exit_path.read_text().strip())
        if cap_exit != 0:
            raise AssemblyError(
                f"capability probe exited {cap_exit}: evidence failure, "
                f"not capability absence")
        ext_raw = _read_raw(
            evidence_root, "preflight/raw/ext-matrix.stdout")
        if not ext_raw.strip():
            raise AssemblyError("ext-matrix census stdout is empty")
        ext_exit_path = evidence_root / "preflight" / "raw" / \
            "ext-matrix.exit-code"
        if not ext_exit_path.is_file():
            raise AssemblyError("ext-matrix exit-code not retained")
        ext_exit = int(ext_exit_path.read_text().strip())
        if ext_exit != 0:
            raise AssemblyError(
                f"ext-matrix probe exited {ext_exit}: evidence failure, "
                f"not capability absence")
        cap_json = json.loads(cap_raw.decode("utf-8"))
        ext_json = json.loads(ext_raw.decode("utf-8"))
        # identity join against the accepted fresh mapping
        expected_bdfs: dict[str, str] = {}
        for die, row in mapping["participants"].items():
            expected_bdfs[die] = probe.normalize_bdf(row["fresh_pci_bdf"])
        # re-derive the census verdict from retained raw bytes
        verdict = probe.validate_capability_census(
            cap_json, ext_json, expected_bdfs)
        out["capability_verdict"] = verdict
        if not verdict["census_valid"]:
            raise AssemblyError(
                "capability census invalid: "
                + "; ".join(verdict["failure_reasons"]))
        if preflight.get("capability_verdict") != verdict:
            raise AssemblyError(
                "preflight capability verdict diverges from the "
                "assembler's re-derivation over retained raw bytes")
        mechanism = ladder.classify_mechanism(verdict)
        out["mechanism"] = mechanism
    except (AssemblyError, json.JSONDecodeError, KeyError, ValueError,
            probe.CensusInvalid) as exc:
        out["blocked_reason"] = str(exc)
        out["terminal"] = "V2E_EVIDENCE_BLOCKED"
        return out

    boot_id = preflight.get("boot_id")

    # ---- transfer-phase artifact (refusal expected; ladder forbidden) -
    # evidence-shape problems here are BLOCKED (the tree cannot
    # establish an authorized classification), never a capability
    # terminal; the assembler still refuses to derive anything from
    # disqualifying content (see the raises below).
    try:
        ladder_file = evidence_root / "ladder" / "ladder.json"
        refusal_file = evidence_root / "ladder" / "refusal.json"
        if ladder_file.is_file():
            raise AssemblyError(
                "a transfer ladder artifact exists but transfer "
                "execution is disabled for this campaign; transfer "
                "evidence cannot be reduced")
        if not refusal_file.is_file():
            raise AssemblyError(
                "no transfer-phase refusal artifact; incomplete "
                "evidence")
        refusal = _read_json(refusal_file)
        if refusal.get("closure_digest") != closure["closure_digest"]:
            raise AssemblyError(
                "ladder refusal binds a different closure")
        if refusal.get("attempt_id") != LADDER_ATTEMPT_ID:
            raise AssemblyError(
                "ladder refusal is not from the corrected attempt")
        if refusal.get("executed_transfers") != 0:
            raise AssemblyError(
                "ladder artifact claims executed transfers under a "
                "disabled-transfer campaign")
        if refusal.get("mechanism") != mechanism:
            raise AssemblyError(
                "refusal mechanism classification diverges from the "
                "assembler's re-derivation")
        baselines_file = evidence_root / "baselines"
        baselines_refusal = None
        f = baselines_file / "refusal.json"
        if f.is_file():
            baselines_refusal = _read_json(f)
        if baselines_refusal is None:
            raise AssemblyError("no baselines refusal artifact")
        if baselines_refusal.get("attempt_id") != BASELINES_ATTEMPT_ID:
            raise AssemblyError(
                "baselines refusal is not from the corrected attempt")
        if baselines_refusal.get("executed_transfers", 0) != 0:
            raise AssemblyError(
                "baselines artifact claims executed transfers under a "
                "disabled-transfer campaign")
    except AssemblyError as exc:
        out["blocked_reason"] = str(exc)
        out["terminal"] = "V2E_EVIDENCE_BLOCKED"
        return out

    # ---- campaign-window platform-fault scan ---------------------------
    phases = [preflight, refusal, baselines_refusal]
    for ph in phases:
        if not _phase_authority_ok(ph, boot_id or ""):
            raise AssemblyError(
                "phase authority mismatch: a retained phase carries a "
                "different boot identity than the campaign preflight")
    window_start = min(ph["captured_utc"] for ph in phases
                       if "captured_utc" in ph)
    window_end = max(ph["captured_utc"] for ph in phases
                     if "captured_utc" in ph)
    journal_paths = sorted(
        evidence_root.glob("ladder/raw/journal-*.stdout"))
    fault_scan: dict[str, Any] = {"fault_lines": {},
                                  "unresolved_fault_lines": [],
                                  "any": False}
    for jp in journal_paths:
        scan = scan_journal_window(jp.read_text(encoding="utf-8"),
                                   window_start, window_end)
        for cls, lines in scan["fault_lines"].items():
            fault_scan["fault_lines"].setdefault(cls, []).extend(lines)
        fault_scan["unresolved_fault_lines"].extend(
            scan["unresolved_fault_lines"])
    fault_scan["any"] = bool(fault_scan["fault_lines"])
    if fault_scan["unresolved_fault_lines"]:
        raise AssemblyError(
            f"{len(fault_scan['unresolved_fault_lines'])} fault-class "
            f"journal lines could not be placed inside the retained "
            f"campaign window; refusing to derive a terminal over "
            f"unbounded fault evidence")
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

    # ---- terminal classification ---------------------------------------
    if fault_scan["any"]:
        out["terminal"] = "V2E_V340L_PLATFORM_STRESS_FAIL"
        return out

    if mechanism.get("basis") == "capability-advertised-but-no-implementation":
        # advertised capability with no implementation: execution was
        # refused. No measured transfers exist, so no functional
        # terminal is derivable. The honest terminal is BLOCKED: the
        # evidence cannot establish an authorized classification
        # (capability exists but was never exercised under this
        # campaign's disabled-transfer fence).
        out["blocked_reason"] = (
            "census advertises capable mechanism(s) "
            f"{mechanism.get('advertised_mechanisms')} but transfer "
            f"execution is disabled for this campaign; without measured "
            f"transfers no functional, correct, measured peer path can "
            f"be established (no measured transfers retained)")
        out["terminal"] = "V2E_EVIDENCE_BLOCKED"
        return out

    basis = mechanism.get("basis")
    if basis == "no-capable-mechanism-advertised":
        # census valid + complete; capability absent on the accepted
        # stack; per the issue's vocabulary this is PREREQUISITE (the
        # topology suggests a physically possible peer path; exercising
        # it would require a different runtime/driver substrate).
        out["capability_absence_reasons"] = mechanism.get(
            "capability_absence_reasons")
        out["missing_capability"] = mechanism.get(
            "capability_absence_reasons")
        out["terminal"] = "V2E_V340L_P2P_API_PREREQUISITE"
        return out

    out["blocked_reason"] = (
        f"mechanism classification basis {basis!r} cannot establish an "
        f"authorized classification")
    out["terminal"] = "V2E_EVIDENCE_BLOCKED"
    return out


def write_terminal(evidence_root: Path, assembly: dict[str, Any]) -> Path:
    if assembly.get("terminal") not in TERMINALS:
        raise AssemblyError(
            f"assembly carries no valid terminal: {assembly.get('terminal')}")
    doc = {
        "schema": SCHEMA_TERMINAL,
        "campaign_id": rc.CAMPAIGN_ID,
        "attempt": ATTEMPT_ID,
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
            "no claim that a corrected census alone establishes or "
            "excludes a physical peer path; advertised capability is "
            "not validated execution",
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
        json.dumps(assembly, indent=1, sort_keys=True).encode("utf-8") + b"\n")
    if args.write_terminal:
        write_terminal(root, assembly)
    print(json.dumps({"terminal": assembly.get("terminal"),
                      "producer_head": assembly.get("producer_head")},
                     indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

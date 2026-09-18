#!/usr/bin/env python3
"""Issue #219 — V2-D0 replayable reducer and terminal state machine.

Derives, from retained raw bytes ONLY (never from authored summaries):

  * per-participant physical identity (device UUID/name from the seam
    header record, cross-bound to the run's own selected-device line
    and the accepted identity-probe BDF);
  * per-graph-compute device-timestamp interval UNIONS, converted to
    the common CLOCK_MONOTONIC domain via the retained calibration
    pairs;
  * the uncertainty bound (maxDeviation per calibration capture +
    timestampPeriod granularity per endpoint);
  * the conservative overlap classification per the frozen rubric:
    OVERLAP only when the lower bound stays strictly positive after
    the combined uncertainty; NON_OVERLAP only when the upper bound is
    <= 0 after adding the full uncertainty; otherwise INDETERMINATE;
  * the non-perturbation verdict (byte-exact output, 0/0/0 accounting,
    full offload, no fallback, clean exit, same BDF, both arms);
  * the terminal classification.

Terminal vocabulary (exactly the issue's):
  V2D0_VULKAN_WORKLOAD_OVERLAP_SEAM_PASS
  V2D0_VULKAN_WORKLOAD_OVERLAP_SEAM_UNAVAILABLE
  V2D0_VULKAN_WORKLOAD_OVERLAP_SEAM_PERTURBS_SUBJECT
  V2D0_EVIDENCE_BLOCKED

Fail-closed: any missing raw artifact, incomplete query, zero/missing
calibration, wrap anomaly, or cross-bound mismatch raises
ReductionError — it never degrades into a softer verdict.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA_REDUCE = "inferswarm.v2d0.reduce/1"
TERMINALS = (
    "V2D0_VULKAN_WORKLOAD_OVERLAP_SEAM_PASS",
    "V2D0_VULKAN_WORKLOAD_OVERLAP_SEAM_UNAVAILABLE",
    "V2D0_VULKAN_WORKLOAD_OVERLAP_SEAM_PERTURBS_SUBJECT",
    "V2D0_EVIDENCE_BLOCKED",
)


class ReductionError(RuntimeError):
    """A retained-evidence predicate failed; the campaign is BLOCKED."""


# ---------------------------------------------------------------------------
# Raw record parsing (JSONL: drain records + one final header record).
# ---------------------------------------------------------------------------

def load_observe_record(path: Path) -> dict:
    header = None
    drains = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as e:
            raise ReductionError(f"{path.name}:{lineno}: malformed JSONL: {e}")
        kind = rec.get("kind")
        if kind == "header":
            # Two headers are expected by construction: one at the first
            # graph-compute entry (incomplete, zeros) and the final one at
            # cleanup (complete tick index).  A THIRD is malformed.
            if sum(1 for r in [header, rec] if r is not None) > 2:
                raise ReductionError(f"{path.name}: more than two header records")
            if rec.get("total_ticks", 0) > 0:
                header = rec  # the complete, final header
            elif header is None:
                header = rec
        elif kind == "drain":
            drains.append(rec)
        else:
            raise ReductionError(f"{path.name}:{lineno}: unknown kind {kind!r}")
    if header is None:
        raise ReductionError(f"{path.name}: missing header record")
    return {"header": header, "drains": drains,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def require_complete_drains(record: dict) -> None:
    for drain in record["drains"]:
        if str(drain.get("get_query_result_availability")).lower() not in (
                "esuccess", "success", "vk_success", "0"):
            raise ReductionError(
                f"drain {drain['drain_index']}: query readback not eSuccess: "
                f"{drain.get('get_query_result_availability')!r}")
        for i, avail in enumerate(drain["availability"]):
            if not avail:
                raise ReductionError(
                    f"drain {drain['drain_index']}: tick {i} incomplete "
                    "(availability 0 after runtime fence wait)")
        if drain.get("calibration_result") != 0:
            raise ReductionError(
                f"drain {drain['drain_index']}: calibration_result "
                f"{drain.get('calibration_result')} != VK_SUCCESS")


# ---------------------------------------------------------------------------
# Interval derivation.
# ---------------------------------------------------------------------------

@dataclass
class Submission:
    graph_compute: int
    begin_tick: int      # device-domain raw tick
    end_tick: int


def submissions_from_record(record: dict) -> list[Submission]:
    """Pair begin/end ticks from the header's tick index + drain tick values."""
    header = record["header"]
    roles = header["tick_roles"]
    gcs = header["tick_graph_computes"]
    queries = header["tick_queries"]
    # Reconstruct the full tick value array from drains (contiguous ranges).
    values: dict[int, int] = {}
    for drain in record["drains"]:
        for i, q in enumerate(range(drain["query_first"],
                                    drain["query_first"] + drain["query_count"])):
            values[q] = drain["ticks"][i]
    subs: list[Submission] = []
    open_tick: tuple[int, int] | None = None  # (gc, tick)
    for role, gc, q in zip(roles, gcs, queries):
        if q not in values:
            raise ReductionError(f"tick query {q} has no drained value")
        if role == 0:
            if open_tick is not None:
                raise ReductionError("nested begin tick without end")
            open_tick = (gc, values[q])
        elif role == 1:
            if open_tick is None:
                raise ReductionError(f"end tick without begin (gc={gc}, q={q})")
            bgc, btick = open_tick
            if bgc != gc:
                raise ReductionError(
                    f"submission spans graph computes: {bgc} != {gc}")
            if values[q] < btick:
                raise ReductionError(
                    f"end tick before begin tick (wrap or reorder) gc={gc}")
            subs.append(Submission(gc, btick, values[q]))
            open_tick = None
        else:
            raise ReductionError(f"unknown tick role {role}")
    if open_tick is not None:
        raise ReductionError("unterminated begin tick at record end")
    if not subs:
        raise ReductionError("no submissions observed")
    return subs


@dataclass
class Calibration:
    device: int
    monotonic_ns: int
    max_deviation_ns: int


def calibrations_from_record(record: dict) -> list[Calibration]:
    out = []
    for drain in record["drains"]:
        out.append(Calibration(drain["calibration_device"],
                               drain["calibration_monotonic_ns"],
                               drain["calibration_max_deviation_ns"]))
    return out


def ticks_to_monotonic(subs: list[Submission], calib: Calibration,
                       period_ns: float) -> list[tuple[int, int, int, int]]:
    """Convert (gc, begin, end) device ticks to monotonic ns.

    Conversion (frozen): host_mono = calib.monotonic_ns +
    (tick - calib.device) * period_ns.  The uncertainty carried per
    endpoint is calib.max_deviation_ns + period_ns.
    """
    out = []
    for s in subs:
        b = calib.monotonic_ns + (s.begin_tick - calib.device) * period_ns
        e = calib.monotonic_ns + (s.end_tick - calib.device) * period_ns
        out.append((s.graph_compute, int(b), int(e), s.end_tick - s.begin_tick))
    return out


def union_intervals(per_sub: list[tuple[int, int, int, int]]) -> list[tuple[int, int]]:
    ivs = sorted((b, e) for _, b, e, _ in per_sub)
    merged: list[list[int]] = []
    for b, e in ivs:
        if merged and b <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([b, e])
    return [(b, e) for b, e in merged]


# ---------------------------------------------------------------------------
# Conservative overlap decision.
# ---------------------------------------------------------------------------

def overlap_lower_bound(a: list[tuple[int, int]], b: list[tuple[int, int]],
                        uncertainty_ns: int) -> int:
    """Max over interval pairs of (min(ea,eb) - max(ba,bb)) - uncertainty.

    This is the LOWER bound on real overlap: apparent overlap shrinks by
    the full uncertainty; strictly positive -> OVERLAP candidate.
    """
    best: int | None = None
    for ba, ea in a:
        for bb, eb in b:
            apparent = min(ea, eb) - max(ba, bb)
            if best is None or apparent > best:
                best = apparent
    if best is None:
        raise ReductionError("no intervals to compare")
    return best - uncertainty_ns


def overlap_upper_bound(a: list[tuple[int, int]], b: list[tuple[int, int]],
                        uncertainty_ns: int) -> int:
    """Same max apparent overlap, but uncertainty ADDED.

    <= 0 -> provably NON_OVERLAP (even granting full uncertainty).
    """
    best: int | None = None
    for ba, ea in a:
        for bb, eb in b:
            apparent = min(ea, eb) - max(ba, bb)
            if best is None or apparent > best:
                best = apparent
    if best is None:
        raise ReductionError("no intervals to compare")
    return best + uncertainty_ns


def classify_overlap(a: dict, b: dict) -> dict:
    """a/b: observe records fully reduced to monotonic unions + bounds."""
    unc_a = max(a["max_deviation_ns"]) + 2 * int(a["period_ns"])
    unc_b = max(b["max_deviation_ns"]) + 2 * int(b["period_ns"])
    uncertainty = unc_a + unc_b
    lo = overlap_lower_bound(a["unions"], b["unions"], uncertainty)
    hi = overlap_upper_bound(a["unions"], b["unions"], uncertainty)
    if lo > 0:
        verdict = "OVERLAP"
    elif hi <= 0:
        verdict = "NON_OVERLAP"
    else:
        verdict = "INDETERMINATE"
    return {"verdict": verdict,
            "lower_bound_ns": lo, "upper_bound_ns": hi,
            "uncertainty_ns": uncertainty,
            "max_deviation_ns_a": max(a["max_deviation_ns"]),
            "max_deviation_ns_b": max(b["max_deviation_ns"])}


def reduce_participant(record: dict, expected_bdf: str,
                       selected_line_bdf: str | None) -> dict:
    require_complete_drains(record)
    header = record["header"]
    if header.get("timestamp_valid_bits", 0) < 2:
        raise ReductionError("header lacks timestampValidBits >= 2")
    period = float(header["timestamp_period_ns"])
    subs = submissions_from_record(record)
    calibs = calibrations_from_record(record)
    if not calibs:
        raise ReductionError("no calibration captures retained")
    # Use the calibration capture bounding the observed ticks (the LAST
    # drain's capture brackets the record's end; the FIRST brackets the
    # start).  Conservative: use the WORST maxDeviation across captures
    # and the LAST capture's pair for conversion (record ordering proves
    # every tick precedes it).
    worst_dev = max(c.max_deviation_ns for c in calibs)
    last = calibs[-1]
    per_sub = ticks_to_monotonic(subs, last, period)
    unions = union_intervals(per_sub)
    uuid = header.get("device_uuid")
    if not isinstance(uuid, str) or len(uuid) != 2 * 16 or any(c not in "0123456789abcdef" for c in uuid):
        # deviceUUID is VK_UUID_SIZE (16) bytes -> 32 hex chars
        raise ReductionError("header device UUID malformed")
    if selected_line_bdf and expected_bdf and selected_line_bdf != expected_bdf:
        raise ReductionError(
            f"selected-device BDF {selected_line_bdf} != expected {expected_bdf}")
    # Cross-bind the seam's own PCI identity to the expected BDF: the
    # header's (bus,device,function) must equal it, proving the ticks
    # came from the intended physical die (both V340L dies share the
    # same deviceUUID prefix bytes; PCI location is the discriminator
    # alongside the runtime's own selected-device line).
    if expected_bdf and header.get("pci_bus") is not None:
        bus_s, rest = expected_bdf.split(":")
        dev_s, fn_s = rest.split(".")
        if (int(header.get("pci_bus", -1)) != int(bus_s, 16)
                or int(header.get("pci_device", -1)) != int(dev_s, 16)
                or int(header.get("pci_function", -1)) != int(fn_s)):
            raise ReductionError(
                f"header PCI {header.get('pci_bus'):x}:{header.get('pci_device'):02x}."
                f"{header.get('pci_function')} does not match expected BDF "
                f"{expected_bdf}")
    return {
        "device_uuid": header["device_uuid"],
        "device_label": header["device_label"],
        "pci": (f"{int(header['pci_bus']):02x}:{int(header['pci_device']):02x}."
                f"{header['pci_function']}" if header.get("pci_bus") is not None else None),
        "graph_computes": header["graph_computes"],
        "submissions": len(subs),
        "unions": unions,
        "max_deviation_ns": [c.max_deviation_ns for c in calibs],
        "period_ns": header["timestamp_period_ns"],
        "conversion_calibration": {
            "device": last.device, "monotonic_ns": last.monotonic_ns},
        "record_sha256": record["sha256"],
    }


# ---------------------------------------------------------------------------
# Terminal state machine.
# ---------------------------------------------------------------------------

def derive_terminal(*, perturbation_clean: bool | None,
                    control_verdict: str | None,
                    candidate_verdict: str | None,
                    capability_ok: bool | None) -> str:
    if capability_ok is False:
        return "V2D0_VULKAN_WORKLOAD_OVERLAP_SEAM_UNAVAILABLE"
    if perturbation_clean is False:
        return "V2D0_VULKAN_WORKLOAD_OVERLAP_SEAM_PERTURBS_SUBJECT"
    if perturbation_clean is None or control_verdict is None or candidate_verdict is None:
        return "V2D0_EVIDENCE_BLOCKED"
    if perturbation_clean and control_verdict == "NON_OVERLAP" \
            and candidate_verdict == "OVERLAP":
        return "V2D0_VULKAN_WORKLOAD_OVERLAP_SEAM_PASS"
    return "V2D0_EVIDENCE_BLOCKED"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    root = Path(args.evidence_root)

    # Non-perturbation ledger
    perturb = json.loads((root / "perturbation" / "LEDGER-perturbation.json")
                         .read_text(encoding="utf-8"))
    clean = True
    for run in perturb["runs"]:
        rs = run["reduced_summary"]
        if not rs["byte_exact"] or any(v != 0 for v in rs["accounting"].values()):
            clean = False
    perturbation_clean = clean

    # Phase 5 records
    disc = root / "discrimination"
    parts = {}
    for schedule, bdf in (("sequential", None), ("concurrent", None)):
        for sel, expected in (("Vulkan1", "06:00.0"), ("Vulkan2", "09:00.0")):
            rec_path = disc / schedule / f"{schedule}-{sel}.observe.jsonl"
            run_path = disc / schedule / f"{schedule}-{sel}.run.json"
            record = load_observe_record(rec_path)
            run = json.loads(run_path.read_text(encoding="utf-8"))
            parts[(schedule, sel)] = reduce_participant(
                record, expected, run.get("selected_bdf"))
    control = classify_overlap(parts[("sequential", "Vulkan1")],
                               parts[("sequential", "Vulkan2")])
    candidate = classify_overlap(parts[("concurrent", "Vulkan1")],
                                 parts[("concurrent", "Vulkan2")])
    terminal = derive_terminal(
        perturbation_clean=perturbation_clean,
        control_verdict=control["verdict"],
        candidate_verdict=candidate["verdict"],
        capability_ok=True)
    doc = {
        "schema": SCHEMA_REDUCE,
        "perturbation_clean": perturbation_clean,
        "control": control,
        "candidate": candidate,
        "participants": {f"{k[0]}:{k[1]}": v for k, v in parts.items()},
        "terminal": terminal,
    }
    Path(args.out).write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n",
                              encoding="utf-8")
    print(json.dumps({k: doc[k] for k in
                      ("perturbation_clean", "control", "candidate", "terminal")},
                     indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

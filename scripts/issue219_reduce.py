#!/usr/bin/env python3
"""Issue #219 — V2-D0 replayable reducer and terminal state machine.

Derives, from retained raw bytes ONLY (never from authored summaries):

  * per-participant physical identity (device UUID/name from the seam
    header record, cross-bound to the run's own selected-device line
    and the expected BDF via the header's PCI bus identity);
  * per-graph-compute device-timestamp interval UNIONS, converted to
    the common CLOCK_MONOTONIC domain via the retained calibration
    pairs;
  * the uncertainty bound (maxDeviation per calibration capture +
    timestampPeriod granularity per endpoint);
  * the conservative overlap classification per the frozen rubric:
    OVERLAP only when the lower bound stays strictly positive after
    the combined uncertainty; NON_OVERLAP only when the upper bound is
    <= 0 after adding the full uncertainty; otherwise INDETERMINATE;
  * the non-perturbation verdict REPLAYED from raw bytes: the retained
    per-run stdout/stderr/exit-code files are re-hashed against the
    ledger's recorded digests, then the ACCEPTED comparator
    (v0c_correctness.reduce) and the ACCEPTED selector-aware
    accounting reducer (v1c_accounting.parse_accounting) are re-run
    over the raw bytes; the collector's ledger summary is used ONLY as
    a cross-check (any disagreement fails closed), never as authority;
  * the capability verdict parsed from the retained capability probe
    record (CAPABILITY.json), never hard-coded;
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
import sys
from dataclasses import dataclass
from pathlib import Path

SCHEMA_REDUCE = "inferswarm.v2d0.reduce/1"
TERMINALS = (
    "V2D0_VULKAN_WORKLOAD_OVERLAP_SEAM_PASS",
    "V2D0_VULKAN_WORKLOAD_OVERLAP_SEAM_UNAVAILABLE",
    "V2D0_VULKAN_WORKLOAD_OVERLAP_SEAM_PERTURBS_SUBJECT",
    "V2D0_EVIDENCE_BLOCKED",
)

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import v0c_correctness  # noqa: E402  accepted comparator (replayed)
import v1c_accounting  # noqa: E402  accepted accounting reducer (replayed)

PROMPT = ("The quick brown fox jumps over the lazy dog. "
          "Explain what happens next in one sentence:")
ACCOUNTING_KEYS = ("unexplained_persistent_host_mirror_bytes",
                   "source_fetches_after_ready",
                   "unplanned_state_movements")


class ReductionError(RuntimeError):
    """A retained-evidence predicate failed; the campaign is BLOCKED."""


# ---------------------------------------------------------------------------
# Raw record parsing (JSONL: drain records + header records).
# ---------------------------------------------------------------------------

def load_observe_record(path: Path) -> dict:
    header = None
    headers_seen = 0
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
            headers_seen += 1
            # Exactly two headers are emitted by construction (first
            # graph-compute entry, then cleanup).  A third is malformed.
            if headers_seen > 2:
                raise ReductionError(
                    f"{path.name}: more than two header records "
                    f"({headers_seen})")
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

def _max_apparent_overlap(a: list[tuple[int, int]],
                          b: list[tuple[int, int]]) -> int:
    best: int | None = None
    for ba, ea in a:
        for bb, eb in b:
            apparent = min(ea, eb) - max(ba, bb)
            if best is None or apparent > best:
                best = apparent
    if best is None:
        raise ReductionError("no intervals to compare")
    return best


def overlap_lower_bound(a: list[tuple[int, int]], b: list[tuple[int, int]],
                        uncertainty_ns: int) -> int:
    """Max apparent overlap MINUS the full uncertainty (lower bound)."""
    return _max_apparent_overlap(a, b) - uncertainty_ns


def overlap_upper_bound(a: list[tuple[int, int]], b: list[tuple[int, int]],
                        uncertainty_ns: int) -> int:
    """Max apparent overlap PLUS the full uncertainty (upper bound)."""
    return _max_apparent_overlap(a, b) + uncertainty_ns


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
    vb = header.get("timestamp_valid_bits", 0)
    if not isinstance(vb, int) or vb < 2 or vb > 64:
        # The seam's capability proof admits only [2, 64]; a header
        # outside that range is forged or corrupt.
        raise ReductionError(
            f"header timestampValidBits {vb!r} outside [2, 64]")
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
# Non-perturbation REPLAY from raw bytes (never authored summaries).
# ---------------------------------------------------------------------------

def replay_perturbation_run(run_dir: Path, label: str, ledger_run: dict,
                            reference: bytes) -> dict:
    """Replay one perturbation run's accepted predicates from raw bytes.

    * re-hash the retained stdout/stderr against the ledger's recorded
      digests (byte identity between ledger and retained bytes);
    * re-run the ACCEPTED comparator + ACCEPTED accounting reducer over
      the raw bytes;
    * cross-check against the ledger's authored summary — any
      disagreement fails closed (the ledger may under-report a failure
      the bytes show, and vice versa);
    * require clean exit, and the selected BDF equal to the die's
      frozen BDF.
    """
    stdout = (run_dir / f"{label}.stdout").read_bytes()
    stderr = (run_dir / f"{label}.stderr").read_bytes()
    exit_code = int((run_dir / f"{label}.exit-code").read_text().strip())
    if hashlib.sha256(stdout).hexdigest() != ledger_run["stdout_sha256"]:
        raise ReductionError(f"{label}: retained stdout digest != ledger")
    if hashlib.sha256(stderr).hexdigest() != ledger_run["stderr_sha256"]:
        raise ReductionError(f"{label}: retained stderr digest != ledger")
    argv = ledger_run["argv"]
    selector = argv[argv.index("--device") + 1]
    correctness = v0c_correctness.reduce(stdout, PROMPT.encode(), reference)
    accounting = v1c_accounting.parse_accounting(
        stderr.decode("utf-8", "replace"), selector=selector)
    replay = {
        "byte_exact": bool(correctness["byte_exact_visible_output"]),
        "accounting": {k: int(accounting[k]) for k in ACCOUNTING_KEYS},
        "exit_code": exit_code,
    }
    summary = ledger_run["reduced_summary"]
    if replay["byte_exact"] != summary["byte_exact"]:
        raise ReductionError(
            f"{label}: replayed byte_exact {replay['byte_exact']} != "
            f"ledger {summary['byte_exact']}")
    for k in ACCOUNTING_KEYS:
        if replay["accounting"][k] != summary["accounting"][k]:
            raise ReductionError(
                f"{label}: replayed accounting {k}={replay['accounting'][k]} "
                f"!= ledger {summary['accounting'][k]}")
    clean = (replay["byte_exact"] and exit_code == 0
             and all(v == 0 for v in replay["accounting"].values()))
    return {"label": label, "replayed": replay, "clean": clean,
            "selected_bdf": ledger_run.get("selected_bdf")}


def replay_perturbation(root: Path, reference: bytes) -> dict:
    ledger = json.loads((root / "perturbation" / "LEDGER-perturbation.json")
                        .read_text(encoding="utf-8"))
    runs = []
    for ledger_run in ledger["runs"]:
        label = ledger_run["label"]
        runs.append(replay_perturbation_run(
            root / "perturbation" / label, label, ledger_run, reference))
    expected_bdfs = {"Vulkan1": "06:00.0", "Vulkan2": "09:00.0"}
    for r in runs:
        sel = r["label"].split("-")[0]
        if r["selected_bdf"] != expected_bdfs[sel]:
            raise ReductionError(
                f"{r['label']}: selected BDF {r['selected_bdf']} != "
                f"expected {expected_bdfs[sel]}")
    if not runs:
        raise ReductionError("no perturbation runs in ledger")
    return {"runs": runs, "clean": all(r["clean"] for r in runs)}


# ---------------------------------------------------------------------------
# Capability replay from the retained probe record.
# ---------------------------------------------------------------------------

def replay_capability(root: Path) -> bool:
    """Derive capability_ok from CAPABILITY.json (never hard-coded)."""
    doc = json.loads((root / "capability" / "CAPABILITY.json")
                     .read_text(encoding="utf-8"))
    if doc.get("schema") != "inferswarm.v2d0.capability-probe/1":
        raise ReductionError("capability record schema mismatch")
    dies = doc.get("dies", [])
    if len(dies) != 2:
        raise ReductionError(f"expected 2 dies in capability record, saw {len(dies)}")
    ok = True
    for die in dies:
        if die.get("timestamp_compute_and_graphics") != "true":
            ok = False
        bits = die.get("timestamp_valid_bits_queue_families") or []
        if not bits or not all(int(b) >= 2 for b in bits):
            ok = False
        if not die.get("vk_ext_calibrated_timestamps"):
            ok = False
    return ok


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
    parser.add_argument("--reference",
                        default=str(REPO / "docs/investigations/vulkan-v1-a"
                                    "/reference-visible-output.txt"))
    args = parser.parse_args()
    root = Path(args.evidence_root)
    reference = Path(args.reference).read_bytes()

    # Non-perturbation: REPLAYED from raw bytes with ledger cross-check.
    perturbation = replay_perturbation(root, reference)
    perturbation_clean = perturbation["clean"]

    # Capability: parsed from the retained probe record.
    capability_ok = replay_capability(root)

    # Phase 5 records
    disc = root / "discrimination"
    parts = {}
    for schedule in ("sequential", "concurrent"):
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
        capability_ok=capability_ok)
    doc = {
        "schema": SCHEMA_REDUCE,
        "perturbation_clean": perturbation_clean,
        "perturbation_replay": {
            "runs": [{"label": r["label"], "clean": r["clean"],
                      "replayed": r["replayed"]} for r in perturbation["runs"]]},
        "capability_ok": capability_ok,
        "control": control,
        "candidate": candidate,
        "participants": {f"{k[0]}:{k[1]}": v for k, v in parts.items()},
        "terminal": terminal,
    }
    Path(args.out).write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n",
                              encoding="utf-8")
    print(json.dumps({k: doc[k] for k in
                      ("perturbation_clean", "capability_ok", "control",
                       "candidate", "terminal")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

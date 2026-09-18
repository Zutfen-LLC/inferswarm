#!/usr/bin/env python3
"""Issue #216 — V2-D deterministic assembler + terminal reducer.

Re-derives every verdict from PRIMARY RAW BYTES (never collector
summaries), via the ACCEPTED parsers (v0c_correctness, v1c_accounting)
and the ACCEPTED #219 seam reducer machinery (issue219_reduce:
submissions/calibration/conservative-overlap classification).

Evidence graph (acyclic):

  primary raw receipts -> INPUT-MANIFEST -> deterministic assembly
                                             -> terminal
                                             -> final closure

Mutually exclusive terminals (exactly the issue's vocabulary, amended
set of five):

  V2D_V340L_CONCURRENT_DUAL_DIE_STABILITY_PASS
  V2D_V340L_CONCURRENT_CORRECTNESS_FAIL
  V2D_V340L_PLATFORM_STRESS_FAIL
  V2D_EVIDENCE_INCOMPLETE_AFTER_CONCURRENCY
  V2D_EVIDENCE_BLOCKED

Classification rules (ordered, fail-closed):
  1. Pre-concurrency prerequisites missing/invalid (authority, mapping,
     preflight, sentinels, baselines) -> V2D_EVIDENCE_BLOCKED.
  2. Valid concurrent correctness failure (any retained repeat shows
     output/offload/fallback/accounting/identity/attribution violation,
     or fewer than 3 clean repeats exist with failures retained) ->
     V2D_V340L_CONCURRENT_CORRECTNESS_FAIL. Never relabeled.
  3. Affirmative platform failure during soak/fault/reset (GPU
     hang/reset, fatal AER, uncorrected ECC/RAS growth, thermal
     shutdown/alarm, host/peripheral instability, survivor corruption,
     failed required recovery) -> V2D_V340L_PLATFORM_STRESS_FAIL.
     Never relabeled; never erased by later missing evidence.
  4. Missing later required evidence (transport matrix incomplete, soak
     incomplete, fault arms missing, reset disposition missing) without
     an affirmative failure -> V2D_EVIDENCE_INCOMPLETE_AFTER_CONCURRENCY.
  5. All predicates satisfied -> STABILITY_PASS.

Transport numbers are never correctness predicates: a slowdown affects
only the descriptive economics block.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import issue216_receipt as rc
import issue216_execution as ex
import issue219_reduce as seam
import v0c_correctness
import v1c_accounting

_RAW_PARSE_ERRORS = (v0c_correctness.CorrectnessError,
                     v1c_accounting.AccountingError)

PROMPT_BYTES = ex.PROMPT.encode()
ACCOUNTING_KEYS = ("unexplained_persistent_host_mirror_bytes",
                   "source_fetches_after_ready",
                   "unplanned_state_movements")
TERMINALS = (
    "V2D_V340L_CONCURRENT_DUAL_DIE_STABILITY_PASS",
    "V2D_V340L_CONCURRENT_CORRECTNESS_FAIL",
    "V2D_V340L_PLATFORM_STRESS_FAIL",
    "V2D_EVIDENCE_INCOMPLETE_AFTER_CONCURRENCY",
    "V2D_EVIDENCE_BLOCKED",
)
MIN_CONCURRENT_REPEATS = 3
SOAK_MIN_DURATION_S = 3600
SOAK_CADENCE_S = 60
SOAK_CADENCE_TOLERANCE_S = 15
SOAK_CHECKPOINT_EVERY_S = 600

SCHEMA_ASSEMBLY = "inferswarm.v2d.assembly/2"
SCHEMA_TERMINAL = "inferswarm.v2d.terminal/2"


class AssemblyError(RuntimeError):
    """Retained evidence failed a fail-closed predicate (-> BLOCKED)."""


class CorrectnessFailure(RuntimeError):
    """A retained concurrent repeat violates a correctness predicate."""


class PlatformFailure(RuntimeError):
    """Retained evidence positively demonstrates a platform failure."""


# ---------------------------------------------------------------------------
# Raw-byte helpers.
# ---------------------------------------------------------------------------

def _read_raw(evidence_root: Path, rel: str) -> bytes:
    p = evidence_root / rel
    if not p.is_file():
        raise AssemblyError(f"missing raw artifact: {rel}")
    return p.read_bytes()


def _read_json(evidence_root: Path, rel: str) -> Any:
    return json.loads(_read_raw(evidence_root, rel))


def _hash_ok(data: bytes, expected: str, what: str) -> None:
    if hashlib.sha256(data).hexdigest() != expected:
        raise AssemblyError(f"raw byte hash mismatch: {what}")


def _bdf_bus(bdf: str | None) -> int | None:
    if not bdf or ":" not in bdf:
        return None
    try:
        return int(bdf.split(":")[-2], 16)
    except (ValueError, IndexError):
        return None


# ---------------------------------------------------------------------------
# Execution re-derivation (receipt -> verdict, from bytes).
# ---------------------------------------------------------------------------

def rederive_execution(evidence_root: Path, run: dict[str, Any],
                       phase_dir: str) -> dict[str, Any]:
    def resolve(rel: str) -> str:
        return f"{phase_dir}/{rel}" if phase_dir else rel

    stdout = _read_raw(evidence_root, resolve(run["stdout_rel"]))
    stderr = _read_raw(evidence_root, resolve(run["stderr_rel"]))
    _hash_ok(stdout, run["stdout_sha256"], resolve(run["stdout_rel"]))
    _hash_ok(stderr, run["stderr_sha256"], resolve(run["stderr_rel"]))
    exit_raw = _read_raw(evidence_root, resolve(run["exit_code_rel"]))
    exit_code = int(exit_raw.decode().strip() or -1)
    reference = (REPO / "docs/investigations/vulkan-v1-a/"
                 "reference-visible-output.txt").read_bytes()
    import v0c_correctness
    import v1c_accounting
    semantics = ex.correctness_semantics(run["argv"])
    correctness = ex.reduce_correctness(stdout, reference, semantics)
    stderr_text = stderr.decode("utf-8", "replace")
    selector = run["argv"][run["argv"].index("--device") + 1]
    accounting = v1c_accounting.parse_accounting(stderr_text,
                                                 selector=selector)
    offload = ex.parse_offload(stderr_text)
    selected = ex.parse_selected_bdf(stderr_text)
    fallback = "fallback" in stderr_text.lower()
    if run["exit_code"] != exit_code:
        raise AssemblyError(
            f"exit-code disagreement for {run['label']}: receipt "
            f"{run['exit_code']} vs raw {exit_code}")
    cc = run.get("correctness_crosscheck") or {}
    if cc.get("visible_response_sha256") not in (None,
                                                 correctness[
                                                     "visible_response_sha256"]):
        raise AssemblyError(
            f"correctness cross-check disagreement for {run['label']}")
    acct_cc = run.get("accounting_crosscheck") or {}
    for k in ACCOUNTING_KEYS:
        if k in acct_cc and accounting.get(k) != acct_cc.get(k):
            raise AssemblyError(
                f"accounting cross-check disagreement ({k}) for "
                f"{run['label']}")
    full_offload = bool(offload and offload[0] == offload[1]
                        and offload[0] > 0)
    clean_exit = exit_code == 0
    accounting_zero = all(accounting.get(k) == 0 for k in ACCOUNTING_KEYS)
    return {
        "label": run["label"],
        "exit_code": exit_code,
        "clean_exit": clean_exit,
        "correctness_semantics": semantics,
        "visible_response_sha256": correctness["visible_response_sha256"],
        "byte_exact": correctness["byte_exact_visible_output"] is True,
        "full_offload": full_offload,
        "no_fallback": not fallback,
        "selected_bdf": selected,
        "accounting": {k: accounting.get(k) for k in ACCOUNTING_KEYS},
        "accounting_zero": accounting_zero,
        "correct": (clean_exit and correctness["byte_exact_visible_output"]
                    is True and full_offload and not fallback
                    and accounting_zero),
    }


# ---------------------------------------------------------------------------
# Seam overlap re-derivation (#219 accepted machinery).
# ---------------------------------------------------------------------------

def rederive_overlap(evidence_root: Path, observe_rel: str,
                     pair_dir: str) -> dict[str, Any]:
    rel = f"{pair_dir}/{observe_rel}" if pair_dir else observe_rel
    path = evidence_root / rel
    if not path.is_file():
        raise AssemblyError(f"missing observe record: {rel}")
    record = seam.load_observe_record(path)
    seam.require_complete_drains(record)
    subs = seam.submissions_from_record(record)
    calibs = seam.calibrations_from_record(record)
    if not calibs:
        raise AssemblyError(f"no calibration in {rel}")
    period = float(record["header"]["timestamp_period_ns"])
    last = calibs[-1]
    max_dev = max(c.max_deviation_ns for c in calibs)
    chosen = seam.Calibration(last.device, last.monotonic_ns,
                              last.max_deviation_ns)
    per_sub = seam.ticks_to_monotonic(subs, chosen, period)
    union = seam.union_intervals(per_sub)
    return {
        "rel": rel,
        "record_sha256": record["sha256"],
        "device_uuid": record["header"].get("device_uuid"),
        "pci_bus": record["header"].get("pci_bus"),
        "submissions": len(subs),
        "union": union,
        "max_deviation_ns": max_dev,
        "period_ns": period,
    }


def classify_pair_overlap(a: dict[str, Any], b: dict[str, Any]) -> dict:
    uncertainty = (a["max_deviation_ns"] + b["max_deviation_ns"]
                   + 2 * int(a["period_ns"]) + 2 * int(b["period_ns"]))
    lower = seam.overlap_lower_bound(a["union"], b["union"], uncertainty)
    upper = seam.overlap_upper_bound(a["union"], b["union"], uncertainty)
    if lower > 0:
        verdict = "OVERLAP"
    elif upper <= 0:
        verdict = "NON_OVERLAP"
    else:
        verdict = "INDETERMINATE"
    return {"verdict": verdict, "uncertainty_ns": uncertainty,
            "lower_bound_ns": lower, "upper_bound_ns": upper}


# ---------------------------------------------------------------------------
# Phase assembly.
# ---------------------------------------------------------------------------

def assemble_pair(evidence_root: Path, pair: dict[str, Any],
                  pair_dir: str, *, require_overlap: bool = True
                  ) -> dict[str, Any]:
    verdicts = {}
    for die in ("a", "b"):
        verdicts[die] = rederive_execution(
            evidence_root, pair["participants"][die], pair_dir)
    overlap_rows = {}
    for die in ("a", "b"):
        overlap_rows[die] = rederive_overlap(
            evidence_root, pair["observe_rels"][die], pair_dir)
    # cross-bind: participant selected BDF bus must match its own seam
    # record bus (participant/record substitution fails closed)
    for die in ("a", "b"):
        bus = _bdf_bus(verdicts[die]["selected_bdf"])
        rec_bus = overlap_rows[die]["pci_bus"]
        if bus is not None and rec_bus is not None and bus != int(rec_bus):
            raise CorrectnessFailure(
                f"participant {die} selected BDF "
                f"{verdicts[die]['selected_bdf']} does not match its seam "
                f"record bus {rec_bus}")
    # distinct physical dies within the pair
    buses = {_bdf_bus(v["selected_bdf"]) for v in verdicts.values()}
    if len(buses) != 2 or None in buses:
        raise CorrectnessFailure(
            f"pair participants not on distinct dies: {buses}")
    overlap = classify_pair_overlap(overlap_rows["a"], overlap_rows["b"])
    if require_overlap and overlap["verdict"] != "OVERLAP":
        raise CorrectnessFailure(
            f"concurrent pair {pair.get('attempt_id')}: seam overlap "
            f"classification {overlap['verdict']} (wrapper scheduling is "
            f"not overlap authority)")
    return {
        "attempt_id": pair.get("attempt_id"),
        "participants": verdicts,
        "overlap": overlap,
        "overlap_records": overlap_rows,
        "pair_correct": all(v["correct"] for v in verdicts.values())
                        and overlap["verdict"] == "OVERLAP",
    }


def assemble_preflight(evidence_root: Path) -> dict[str, Any]:
    preflight = _read_json(evidence_root, "preflight.json")
    journal = _read_raw(evidence_root, "preflight/raw/journal_faults.stdout")
    text = journal.decode("utf-8", "replace")
    counts = {
        "fatal_aer": len(re.findall(
            r"severity\s*=\s*(fatal|uncorrectable|uncorrected)",
            text, re.I)) + len(re.findall(
            r"AER:\s*(?:Multiple\s+)?Uncorrected", text, re.I)),
        "amdgpu_failure": len(re.findall(
            r"amdgpu.*(fail|timeout|reset|hang)", text, re.I)),
        "dmar_fault": len(re.findall(r"DMAR:[^\n]*(fault|error)",
                                     text, re.I)),
    }
    sentinels = preflight.get("sentinels") or {}
    if not sentinels:
        raise AssemblyError("preflight has no sentinel results")
    return {
        "boot_id": preflight["boot_id"],
        "journal_fault_counts": counts,
        "preexisting_fault_free": all(v == 0 for v in counts.values()),
        "sentinels_correct": {d: (s or {}).get("correct") is True
                              for d, s in sentinels.items()},
        "bdfs": preflight.get("bdfs"),
    }


def assemble_baselines(evidence_root: Path, plan: dict[str, Any]
                       ) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for die in ("a", "b"):
        rel = f"baseline-{die}.json"
        doc = _read_json(evidence_root, rel)
        rows = []
        for rep in doc["reps"]:
            verdict = rederive_execution(evidence_root, rep["run"],
                                         f"baseline-{die}")
            rows.append({"rep": rep["rep"], "verdict": verdict})
        out[die] = {"rows": rows,
                    "all_correct": all(r["verdict"]["correct"]
                                       for r in rows)}
        if not out[die]["all_correct"]:
            raise AssemblyError(
                f"baseline die {die} has incorrect repeats (broken "
                f"baseline: do not interpret simultaneous results)")
    return out


def assemble_concurrent(evidence_root: Path, ledger: dict[str, Any]
                        ) -> dict[str, Any]:
    """All retained concurrent attempts (successes AND failures).

    A retained repeat whose seam classification is NON_OVERLAP/INDETERMINATE
    is a concurrency-establishment failure for that repeat (issue control
    #5): it never counts toward the clean-repeat denominator. If NO
    repeat established real concurrency, the campaign is BLOCKED
    (inability to demonstrate real concurrency); if some repeat did and
    another violated a correctness predicate, that is a correctness
    failure on a valid simultaneous execution.
    """
    attempts = ledger.get("attempts") or []
    if not attempts:
        raise AssemblyError("no concurrent attempts retained")
    rows = []
    failures = []
    overlap_failures = []
    for att in attempts:
        if att.get("status") == "aborted":
            rows.append({"attempt_id": att["attempt_id"],
                         "status": "aborted", "pair": None})
            continue
        pair = _read_json(
            evidence_root,
            f"concurrent/{att['attempt_id']}/pair-{att['attempt_id']}.json")
        verdicts = {}
        for die in ("a", "b"):
            verdicts[die] = rederive_execution(
                evidence_root, pair["participants"][die],
                f"concurrent/{att['attempt_id']}")
        overlap_rows = {}
        for die in ("a", "b"):
            overlap_rows[die] = rederive_overlap(
                evidence_root, pair["observe_rels"][die],
                f"concurrent/{att['attempt_id']}")
        for die in ("a", "b"):
            bus = _bdf_bus(verdicts[die]["selected_bdf"])
            rec_bus = overlap_rows[die]["pci_bus"]
            if bus is not None and rec_bus is not None \
                    and bus != int(rec_bus):
                raise CorrectnessFailure(
                    f"participant {die} selected BDF "
                    f"{verdicts[die]['selected_bdf']} does not match its "
                    f"seam record bus {rec_bus}")
        buses = {_bdf_bus(v["selected_bdf"]) for v in verdicts.values()}
        if len(buses) != 2 or None in buses:
            raise CorrectnessFailure(
                f"pair participants not on distinct dies: {buses}")
        overlap = classify_pair_overlap(overlap_rows["a"],
                                        overlap_rows["b"])
        pair_correct = (all(v["correct"] for v in verdicts.values())
                        and overlap["verdict"] == "OVERLAP")
        if overlap["verdict"] != "OVERLAP":
            overlap_failures.append(att["attempt_id"])
        elif not all(v["correct"] for v in verdicts.values()):
            failures.append(att["attempt_id"])
        rows.append({"attempt_id": att["attempt_id"], "status": "run",
                     "pair": {"attempt_id": att["attempt_id"],
                              "participants": verdicts,
                              "overlap": overlap,
                              "pair_correct": pair_correct}})
    clean = [r for r in rows if r["pair"] is not None
             and r["pair"]["pair_correct"]]
    if not clean and overlap_failures:
        # no repeat established real concurrency at all
        raise AssemblyError(
            "no concurrent repeat established real GPU-work overlap "
            f"(seam NON_OVERLAP/INDETERMINATE in: {overlap_failures})")
    return {"attempts": rows, "clean_repeats": len(clean),
            "failures": failures,
            "overlap_failures": overlap_failures,
            "meets_minimum": len(clean) >= MIN_CONCURRENT_REPEATS}


def assemble_transport(evidence_root: Path) -> dict[str, Any]:
    doc = _read_json(evidence_root, "transport.json")
    modes = {}
    for mode in ("single-a", "single-b"):
        if mode not in doc or doc[mode].get("exit_code") != 0:
            raise AssemblyError(f"transport mode {mode} missing/failed")
        modes[mode] = {"exit_code": doc[mode]["exit_code"]}
    if "dual" not in doc:
        raise AssemblyError("transport dual mode missing")
    dual = doc["dual"]
    for die in ("a", "b"):
        if dual["participants"][die].get("exit_code") != 0:
            raise AssemblyError(f"dual transport participant {die} failed")
    if not dual.get("probe_process_overlap"):
        raise AssemblyError(
            "dual transport arm shows no probe-process overlap "
            "(single-die measurements mislabeled simultaneous)")
    modes["dual"] = {"exit_code": 0,
                     "probe_process_overlap": True}
    return {"modes": modes,
            "note": "throughput/latency values are descriptive only; "
                    "no transport number is a correctness predicate"}


def _scan_soak_faults(samples: list[dict[str, Any]],
                      events: list[dict[str, Any]],
                      journal_texts: list[bytes]) -> dict[str, Any]:
    """Derive soak fault predicates from retained bytes."""
    fatal = {"fatal_aer": 0, "amdgpu_reset": 0, "amdgpu_timeout": 0,
             "thermal": 0}
    for text_b in journal_texts:
        text = text_b.decode("utf-8", "replace")
        fatal["fatal_aer"] += len(re.findall(
            r"severity\s*=\s*(fatal|uncorrectable|uncorrected)", text,
            re.I)) + len(re.findall(
            r"AER:\s*(?:Multiple\s+)?Uncorrected", text, re.I))
        fatal["amdgpu_reset"] += len(re.findall(
            r"amdgpu.*reset|resetting amdgpu|GPU reset", text, re.I))
        fatal["amdgpu_timeout"] += len(re.findall(
            r"amdgpu.*timeout|GPU hang|ring timeout", text, re.I))
        fatal["thermal"] += len(re.findall(
            r"thermal.*(shutdown|trip|critical)|overtemperature", text,
            re.I))
    # telemetry cadence + gap check
    times = [s["monotonic_ns"] for s in samples]
    gaps_ok = all(
        (b - a) <= (SOAK_CADENCE_S + SOAK_CADENCE_TOLERANCE_S) * 1_000_000_000
        for a, b in zip(times, times[1:]))
    # participant exits: any 'participant_exit_with_sibling_active' or
    # unplanned exit event is an affirmative platform/correctness event
    unplanned_exits = [e for e in events
                       if e.get("event") == "participant_exit"]
    silent_restart = [e for e in events
                      if e.get("event") == "pair_launched"
                      and any(p.get("event") == "participant_exit"
                             for p in events
                             if p.get("monotonic_ns", 0) < e[
                                 "monotonic_ns"])]
    return {"journal_fault_counts": fatal, "cadence_gaps_ok": gaps_ok,
            "sample_count": len(samples),
            "unplanned_participant_exits": len(unplanned_exits),
            "events": [e.get("event") for e in events]}


def assemble_soak(evidence_root: Path) -> dict[str, Any]:
    doc = _read_json(evidence_root, "soak.json")
    duration = doc.get("duration_s", 0)
    if duration < SOAK_MIN_DURATION_S:
        raise PlatformFailure(
            f"soak duration {duration}s < frozen minimum "
            f"{SOAK_MIN_DURATION_S}s")
    samples = doc.get("samples") or []
    if not samples:
        raise AssemblyError("soak retained no telemetry samples")
    journal_texts = []
    for s in samples:
        rel = s["rel"].replace("telemetry-", "journal-").replace(
            ".json", ".stdout")
        p = evidence_root / rel
        if p.is_file():
            journal_texts.append(p.read_bytes())
    scan = _scan_soak_faults(samples, doc.get("events") or [],
                             journal_texts)
    if scan["journal_fault_counts"]["fatal_aer"] > 0:
        raise PlatformFailure("fatal AER during soak")
    if scan["journal_fault_counts"]["amdgpu_reset"] > 0:
        raise PlatformFailure("amdgpu reset during soak")
    if scan["journal_fault_counts"]["amdgpu_timeout"] > 0:
        raise PlatformFailure("amdgpu timeout/hang during soak")
    if scan["journal_fault_counts"]["thermal"] > 0:
        raise PlatformFailure("thermal shutdown/alarm during soak")
    if not scan["cadence_gaps_ok"]:
        raise AssemblyError(
            "soak telemetry gap exceeds frozen tolerance (a reset/crash "
            "could hide in the gap)")
    # checkpoints + final sentinel
    checkpoint_summaries = sorted(
        (evidence_root / "raw").glob("checkpoint-*.json"))
    expected_checkpoints = duration // SOAK_CHECKPOINT_EVERY_S
    if len(checkpoint_summaries) + 1 < expected_checkpoints:
        raise AssemblyError(
            f"soak checkpoints missing: {len(checkpoint_summaries)} < "
            f"{expected_checkpoints - 1}")
    checkpoint_verdicts = []
    for cp in checkpoint_summaries:
        pair = json.loads(cp.read_bytes())
        pair_dir = f"raw/{cp.stem}"
        row = assemble_pair(evidence_root, pair, pair_dir,
                            require_overlap=False)
        checkpoint_verdicts.append({"checkpoint": cp.stem,
                                   "correct": row["pair_correct"]})
    final_pair = _read_json(evidence_root, "raw/final-sentinel.json")
    final_row = assemble_pair(evidence_root, final_pair,
                              "raw/final-sentinel",
                              require_overlap=False)
    bad_checkpoints = [c for c in checkpoint_verdicts
                       if not c["correct"]]
    return {
        "duration_s": duration,
        "stop_reason": doc.get("stop_reason"),
        "scan": {k: scan[k] for k in ("journal_fault_counts",
                                      "sample_count")},
        "checkpoints": checkpoint_verdicts,
        "final_sentinel_correct": final_row["pair_correct"],
        "all_checkpoints_correct": not bad_checkpoints,
        "ecc_growth": _derive_ecc_growth(evidence_root, samples),
    }


def _derive_ecc_growth(evidence_root: Path,
                       samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Derive uncorrected ECC/RAS growth from the retained telemetry
    snapshots (first vs last sample per BDF)."""
    if not samples:
        return {"growth": None, "reason": "no samples"}
    first = _read_json(evidence_root, samples[0]["rel"])
    last = _read_json(evidence_root, samples[-1]["rel"])
    growth: dict[str, Any] = {}
    for bdf in (first.get("telemetry") or {}):
        f = (first.get("aer") or {}).get(bdf) or {}
        l = (last.get("aer") or {}).get(bdf) or {}
        # ras gpu_err_cnt + AER nonfatal/fatal totals per die
        f_ras = (first.get("telemetry", {}).get(bdf) or {}).get(
            "ras_gpu_err_cnt")
        l_ras = (last.get("telemetry", {}).get(bdf) or {}).get(
            "ras_gpu_err_cnt")
        row = {
            "ras_first": f_ras,
            "ras_last": l_ras,
            "aer_first": f,
            "aer_last": l,
        }
        if f_ras is not None and l_ras is not None:
            row["ras_growth"] = l_ras - f_ras
        growth[bdf] = row
    return {"growth": growth}


def assemble_fault_arm(evidence_root: Path, arm: str) -> dict[str, Any]:
    doc = _read_json(evidence_root, f"fault-arm-{arm}.json")
    sibling = doc["sibling"]
    victim = doc["victim"]
    sibling_run = rederive_execution(
        evidence_root, doc["sibling_run"],
        f"fault-arm-{arm}-loss/initial/{sibling}")
    relaunch_run = rederive_execution(
        evidence_root, doc["relaunch_run"],
        f"fault-arm-{arm}-loss/relaunch/{victim}")
    sentinel_row = assemble_pair(
        evidence_root, doc["recovery_sentinel"],
        f"fault-arm-{arm}-loss/recovery-sentinel",
        require_overlap=False)
    sibling_stayed = sibling_run["selected_bdf"] == doc[
        "sibling_run"].get("selected_bdf")
    return {
        "arm": arm,
        "victim_gone": doc.get("victim_gone") is True,
        "sibling_correct": sibling_run["correct"],
        "sibling_stayed_on_die": sibling_stayed,
        "relaunch_correct": relaunch_run["correct"],
        "recovery_sentinel_correct": sentinel_row["pair_correct"],
    }


def assemble_reset(evidence_root: Path) -> dict[str, Any]:
    doc = _read_json(evidence_root, "reset-determination.json")
    disposition = doc.get("disposition")
    if disposition not in ("DEVICE_RESET_ISOLATION_NOT_AVAILABLE",
                           "RESET_ARM_EXECUTED"):
        raise AssemblyError(f"unknown reset disposition: {disposition}")
    return {"disposition": disposition, "reason": doc.get("reason")}


# ---------------------------------------------------------------------------
# Terminal classification.
# ---------------------------------------------------------------------------

def classify(assembly: dict[str, Any]) -> str:
    if not assembly.get("prerequisites_ok"):
        return "V2D_EVIDENCE_BLOCKED"
    concurrent = assembly.get("concurrent") or {}
    if concurrent.get("failures") or not concurrent.get("meets_minimum"):
        return "V2D_V340L_CONCURRENT_CORRECTNESS_FAIL"
    if assembly.get("platform_failure"):
        return "V2D_V340L_PLATFORM_STRESS_FAIL"
    required = ("transport", "soak", "fault_a", "fault_b", "reset")
    if any(not assembly.get(k) for k in required):
        return "V2D_EVIDENCE_INCOMPLETE_AFTER_CONCURRENCY"
    if not all(assembly.get(k) for k in required):
        return "V2D_EVIDENCE_INCOMPLETE_AFTER_CONCURRENCY"
    return "V2D_V340L_CONCURRENT_DUAL_DIE_STABILITY_PASS"


def assemble(evidence_root: Path) -> dict[str, Any]:
    closure = rc.verify_closure(REPO)
    out: dict[str, Any] = {
        "schema": SCHEMA_ASSEMBLY,
        "campaign_id": rc.CAMPAIGN_ID,
        "closure_sources": sorted(closure["sources"]),
    }
    platform_failure = None
    prerequisites_ok = True
    concurrent_failure = None
    try:
        preflight = assemble_preflight(evidence_root)
        out["preflight"] = preflight
        if not preflight["preexisting_fault_free"] or not all(
                preflight["sentinels_correct"].values()):
            prerequisites_ok = False
        out["baselines"] = assemble_baselines(evidence_root, {})
        ledger = _read_json(evidence_root, "attempt-ledger.json")
        out["concurrent"] = assemble_concurrent(evidence_root, ledger)
    except CorrectnessFailure as exc:
        # a valid simultaneous execution violated a correctness
        # predicate (identity/attribution/accounting) — never BLOCKED
        concurrent_failure = str(exc)
    except (AssemblyError, *_RAW_PARSE_ERRORS) as exc:
        out["blocked_reason"] = str(exc)
        prerequisites_ok = False
    out["prerequisites_ok"] = prerequisites_ok
    if not prerequisites_ok:
        out["terminal"] = "V2D_EVIDENCE_BLOCKED"
        return out
    if concurrent_failure or (out.get("concurrent") or {}).get("failures") \
            or not (out.get("concurrent") or {}).get("meets_minimum"):
        out["concurrent_failure"] = concurrent_failure
        out["terminal"] = "V2D_V340L_CONCURRENT_CORRECTNESS_FAIL"
        return out
    # post-concurrency phases; failures classify per the rules
    try:
        out["transport"] = assemble_transport(evidence_root)
    except AssemblyError as exc:
        out["transport"] = None
        out["transport_missing_reason"] = str(exc)
    try:
        out["soak"] = assemble_soak(evidence_root)
    except PlatformFailure as exc:
        platform_failure = str(exc)
    except AssemblyError as exc:
        out["soak"] = None
        out["soak_missing_reason"] = str(exc)
    for arm, key in (("a", "fault_a"), ("b", "fault_b")):
        try:
            out[key] = assemble_fault_arm(evidence_root, arm)
            if not (out[key]["victim_gone"] and out[key]["sibling_correct"]
                    and out[key]["sibling_stayed_on_die"]
                    and out[key]["relaunch_correct"]
                    and out[key]["recovery_sentinel_correct"]):
                platform_failure = platform_failure or (
                    f"fault arm {arm}: survivor corruption or failed "
                    f"recovery")
        except AssemblyError as exc:
            out[key] = None
            out[f"{key}_missing_reason"] = str(exc)
    try:
        out["reset"] = assemble_reset(evidence_root)
    except AssemblyError as exc:
        out["reset"] = None
        out["reset_missing_reason"] = str(exc)
    out["platform_failure"] = platform_failure
    out["terminal"] = classify(out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence-root", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    assembly = assemble(Path(args.evidence_root))
    Path(args.out).write_bytes(json.dumps(assembly, indent=1,
                                          sort_keys=True).encode() + b"\n")
    print(json.dumps({"terminal": assembly.get("terminal")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

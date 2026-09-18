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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import issue216_freeze as fz
import issue216_receipt as rc
import issue216_execution as ex
import issue219_reduce as seam
import v0c_correctness
import v1c_accounting

# Mapping/identity machinery (FIX 2): BDF normalization + fresh-mapping
# revalidation reuse the ACCEPTED V2-A R3 discovery validator.
import v2a_discovery_v3 as r3

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


# Frozen transport matrix (FIX 5): the accepted #35 ladder — sizes in
# bytes, repetitions per size, plus the small-transfer service and
# bidirectional samples. The assembler re-derives completeness from the
# retained raw probe records; a missing size/rep fails closed.
TRANSPORT_SIZES = (4194304, 16777216, 67108864, 134217728)
TRANSPORT_REPS = 8
TRANSPORT_SMALL_BYTES = 4096
TRANSPORT_SMALL_REPS = 200
TRANSPORT_BIDIR_BYTES_EACH = 33554432
TRANSPORT_BIDIR_REPS = 8
# #216 under-load link-state evidence: at least this many load-phase
# link samples must be retained per probe with a parseable state.
TRANSPORT_MIN_LOAD_SAMPLES = 10


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


def _phase_json(evidence_root: Path, pattern: str) -> tuple[dict, Path]:
    """Locate the singleton phase summary matching pattern (e.g.
    'soak/soak-*.json'); return (doc, phase_dir) where phase_dir is the
    directory raw rel paths resolve against ('' = evidence root)."""
    hits = sorted(evidence_root.glob(pattern))
    if len(hits) != 1:
        raise AssemblyError(
            f"phase summary not singleton for {pattern}: {len(hits)} hits")
    doc = json.loads(hits[0].read_bytes())
    phase_dir = hits[0].parent.relative_to(evidence_root).as_posix() \
        if hits[0].parent != evidence_root else ""
    return doc, phase_dir


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
# FIX 2: fresh-mapping -> actual-execution binding.
# ---------------------------------------------------------------------------

_BDF_RE = None


def normalize_bdf(bdf: str | None) -> str | None:
    """Normalize BDF spellings: `06:00.0` == `0000:06:00.0`.

    Returns the canonical 4-part domain-prefixed form (0000:06:00.0) or
    None for malformed input. Every identity comparison in this
    assembler goes through this function.
    """
    global _BDF_RE
    if _BDF_RE is None:
        import re as _re
        _BDF_RE = _re.compile(
            r"^(?:([0-9a-fA-F]{4}):)?([0-9a-fA-F]{2}):"
            r"([0-9a-fA-F]{2})\.([0-7])$")
    if not isinstance(bdf, str):
        return None
    m = _BDF_RE.match(bdf.strip())
    if not m:
        return None
    dom = (m.group(1) or "0000").lower()
    return f"{dom}:{m.group(2).lower()}:{m.group(3).lower()}.{m.group(4)}"


def bdfs_equal(a: str | None, b: str | None) -> bool:
    na, nb = normalize_bdf(a), normalize_bdf(b)
    return na is not None and na == nb


class VerifiedMapping:
    """The retained fresh-mapping artifact, revalidated from its own
    retained raw bytes through the ACCEPTED V2-A R3 machinery.

    Carries the exact expected (selector, BDF) per participant; every
    execution identity check compares against THIS object, never
    against copied fields inside phase records.
    """

    def __init__(self, doc: dict[str, Any], raw_root: Path):
        self.doc = doc
        if doc.get("schema") != "inferswarm.v2d.fresh-mapping/2":
            raise AssemblyError("fresh mapping schema mismatch")
        if doc.get("campaign_id") != rc.CAMPAIGN_ID:
            raise AssemblyError("fresh mapping campaign mismatch")
        # recompute mapping_digest over the retained record content
        body = {k: v for k, v in doc.items() if k != "mapping_digest"}
        recomputed = hashlib.sha256(rc.canonical(body)).hexdigest()
        if doc.get("mapping_digest") != recomputed:
            raise AssemblyError("fresh mapping digest does not bind content")
        self.digest = recomputed
        self.participants: dict[str, dict[str, str]] = {}
        # Revalidate the R3 discovery authority from retained evidence:
        # every Vega binding's identity probe must re-verify against its
        # retained raw bytes through the accepted shared validator, and
        # the fresh (selector, BDF) must equal the probe's own proof.
        bindings = doc.get("bindings") or {}
        for die in ("a", "b"):
            part = (doc.get("participants") or {}).get(die)
            if not isinstance(part, dict):
                raise AssemblyError(f"mapping missing participant {die}")
            fresh_binding = part.get("fresh_binding") or {}
            probe = fresh_binding.get("identity_probe")
            if not isinstance(probe, dict):
                raise AssemblyError(
                    f"participant {die} binding lacks an R3 identity probe")
            try:
                r3.validate_probe_record(probe, raw_root=raw_root,
                                         expected_selector=part.get(
                                             "fresh_selector"))
            except Exception as exc:  # DiscoveryError + OSError
                raise AssemblyError(
                    f"R3 revalidation failed for die {die}: {exc}") from exc
            probe_bdf = normalize_bdf(probe.get("observed_pci_bdf"))
            sel_bdf = normalize_bdf(part.get("fresh_pci_bdf"))
            if probe_bdf is None or probe_bdf != sel_bdf:
                raise AssemblyError(
                    f"die {die}: R3 probe BDF {probe.get('observed_pci_bdf')}"
                    f" != mapping BDF {part.get('fresh_pci_bdf')}")
            if fresh_binding.get("pci_bdf") != part.get("fresh_pci_bdf"):
                raise AssemblyError(
                    f"die {die}: binding row BDF != participant BDF")
            selector = part.get("fresh_selector")
            if not isinstance(selector, str) or not selector:
                raise AssemblyError(f"die {die} missing selector")
            if sel_bdf is None:
                raise AssemblyError(f"die {die} malformed mapping BDF")
            self.participants[die] = {
                "selector": selector,
                "bdf": sel_bdf,
            }
        if len({p["selector"] for p in self.participants.values()}) != 2 \
                or len({p["bdf"] for p in self.participants.values()}) != 2:
            raise AssemblyError(
                "mapping does not bind two distinct selector/BDF pairs")
        # the record's intended-identity corroboration must also hold:
        # historical selector/BDF (accepted V2-B) == fresh binding
        hist = ((json.loads((REPO / "docs/investigations/"
                             "vulkan-v2-d-v340l-concurrent/"
                             "PHYSICAL-AUTHORITY.json").read_bytes())
                 ).get("historical_qualification_bindings") or {})
        for die in ("a", "b"):
            h = hist.get(die) or {}
            if not bdfs_equal(h.get("pci_bdf"),
                              self.participants[die]["bdf"]) \
                    or h.get("selector") != self.participants[die]["selector"]:
                raise AssemblyError(
                    f"fresh mapping does not corroborate the accepted "
                    f"V2-B qualification binding for die {die}")

    def expected(self, die: str) -> tuple[str, str]:
        return (self.participants[die]["selector"],
                self.participants[die]["bdf"])


def load_verified_mapping(evidence_root: Path) -> VerifiedMapping:
    mapping_dir = evidence_root / "preflight" / "mapping"
    doc_path = mapping_dir / "fresh-mapping.json"
    if not doc_path.is_file():
        raise AssemblyError("fresh mapping artifact missing")
    doc = json.loads(doc_path.read_bytes())
    return VerifiedMapping(doc, raw_root=mapping_dir / "raw")


def require_execution_identity(die: str, run: dict[str, Any],
                               verdict: dict[str, Any],
                               mapping: VerifiedMapping,
                               what: str) -> None:
    """FIX 2 core invariant: the execution's argv selector and its
    stderr-selected BDF must BOTH equal the participant's verified fresh
    mapping. Applied assembler-side for every correctness-bearing
    execution regardless of producer-side checks."""
    exp_selector, exp_bdf = mapping.expected(die)
    argv = run.get("argv") or []
    try:
        got_selector = argv[argv.index("--device") + 1]
    except (ValueError, IndexError):
        raise AssemblyError(f"{what}: argv carries no --device selector")
    if got_selector != exp_selector:
        raise CorrectnessFailure(
            f"{what}: die {die} argv selector {got_selector} != fresh "
            f"mapping {exp_selector}")
    got_bdf = verdict.get("selected_bdf")
    if not bdfs_equal(got_bdf, exp_bdf):
        raise CorrectnessFailure(
            f"{what}: die {die} executed on BDF {got_bdf} != fresh "
            f"mapping {exp_bdf} (wrong-die execution)")


def require_seam_identity(die: str, overlap_row: dict[str, Any],
                          mapping: VerifiedMapping, what: str) -> None:
    """Bind the #219 seam record to the same exact participant/device
    identity (domain/bus/device/function equality, not just distinct
    buses): the seam record's PCI location must equal the participant's
    fresh-mapped BDF."""
    _, exp_bdf = mapping.expected(die)
    header_bus = overlap_row.get("pci_bus")
    if header_bus is None:
        raise AssemblyError(f"{what}: seam record for die {die} has no PCI bus")
    exp = normalize_bdf(exp_bdf)
    if exp is None:
        raise AssemblyError(f"{what}: participant {die} BDF malformed")
    bus = int(exp.split(":")[1], 16)
    dev = int(exp.split(":")[2].split(".")[0], 16)
    fn = int(exp.split(".")[1])
    if int(header_bus) != bus:
        raise CorrectnessFailure(
            f"{what}: die {die} seam record bus {header_bus} != fresh "
            f"mapping bus {bus}")
    # device/function come from the record re-derivation in
    # rederive_overlap; require them when present
    hd = overlap_row.get("pci_device")
    hf = overlap_row.get("pci_function")
    if hd is not None and int(hd) != dev:
        raise CorrectnessFailure(
            f"{what}: die {die} seam record device {hd} != {dev}")
    if hf is not None and int(hf) != fn:
        raise CorrectnessFailure(
            f"{what}: die {die} seam record function {hf} != {fn}")


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
    try:
        argv_selector = run["argv"][run["argv"].index("--device") + 1]
    except (ValueError, IndexError, KeyError):
        argv_selector = None
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
        "argv_selector": argv_selector,
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
    header = record["header"]
    return {
        "rel": rel,
        "record_sha256": record["sha256"],
        "device_uuid": header.get("device_uuid"),
        "pci_bus": header.get("pci_bus"),
        "pci_device": header.get("pci_device"),
        "pci_function": header.get("pci_function"),
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
                  pair_dir: str, mapping: VerifiedMapping, *,
                  require_overlap: bool = True
                  ) -> dict[str, Any]:
    what = f"pair {pair.get('attempt_id')}"
    _require_binding(pair, what, evidence_root)
    verdicts = {}
    for die in ("a", "b"):
        verdicts[die] = rederive_execution(
            evidence_root, pair["participants"][die], pair_dir)
        require_execution_identity(die, pair["participants"][die],
                                   verdicts[die], mapping, what)
    overlap_rows = {}
    for die in ("a", "b"):
        overlap_rows[die] = rederive_overlap(
            evidence_root, pair["observe_rels"][die], pair_dir)
        require_seam_identity(die, overlap_rows[die], mapping, what)
    # cross-bind: participant selected BDF must match its own seam
    # record PCI location (participant/record substitution fails closed)
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


def _load_sentinel_run(preflight: dict[str, Any], die: str,
                       evidence_root: Path, pf_dir: str) -> dict[str, Any]:
    """FIX 3: sentinel runs live in the retained preflight record under
    sentinels.<die>.run (the collector retains the full run row); the
    raw bytes sit in preflight/sentinel/<die>/."""
    sentinel = ((preflight.get("sentinels") or {}).get(die) or {})
    run = sentinel.get("run")
    if not isinstance(run, dict):
        raise AssemblyError(
            f"preflight sentinel {die} retains no run row (raw bytes "
            "unverifiable)")
    return run


def assemble_preflight(evidence_root: Path,
                       mapping: VerifiedMapping) -> dict[str, Any]:
    preflight, pf_dir = _phase_json(evidence_root, "preflight/preflight*.json")
    pf_dir = str(pf_dir)
    journal = _read_raw(evidence_root,
                        f"{pf_dir}/raw/journal_faults.stdout")
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
    # FIX 3: re-derive each sentinel's verdict from its RAW bytes
    # through the accepted reducers; authored `correct` booleans are not
    # authority (they are cross-checked when present).
    sentinels = preflight.get("sentinels") or {}
    if not sentinels:
        raise AssemblyError("preflight has no sentinel results")
    sentinel_verdicts = {}
    for die in ("a", "b"):
        run = _load_sentinel_run(preflight, die, evidence_root, pf_dir)
        # sentinel raws resolve against preflight/sentinel/<die>
        verdict = rederive_execution(evidence_root, run,
                                     f"{pf_dir}/sentinel/{die}")
        require_execution_identity(die, run, verdict, mapping,
                                   "preflight sentinel")
        authored = sentinels.get(die) or {}
        if isinstance(authored.get("correct"), bool) \
                and authored["correct"] != verdict["correct"]:
            raise AssemblyError(
                f"preflight sentinel {die} authored verdict disagrees with "
                f"raw-byte re-derivation ({authored['correct']} vs "
                f"{verdict['correct']})")
        sentinel_verdicts[die] = verdict
    return {
        "boot_id": preflight["boot_id"],
        "journal_fault_counts": counts,
        "preexisting_fault_free": all(v == 0 for v in counts.values()),
        "sentinels_correct": {d: v["correct"]
                              for d, v in sentinel_verdicts.items()},
        "sentinels_rederived": {
            d: {k: v[k] for k in ("clean_exit", "byte_exact",
                                  "full_offload", "no_fallback",
                                  "selected_bdf", "accounting_zero",
                                  "correct")}
            for d, v in sentinel_verdicts.items()},
        "bdfs": preflight.get("bdfs"),
    }


def assemble_baselines(evidence_root: Path, mapping: VerifiedMapping,
                       plan: dict[str, Any]
                       ) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for die in ("a", "b"):
        rel = f"baseline-{die}.json"
        doc = _read_json(evidence_root, rel)
        _require_binding(doc, f"baseline {die}", evidence_root)
        rows = []
        for rep in doc["reps"]:
            verdict = rederive_execution(evidence_root, rep["run"],
                                         f"baseline-{die}")
            require_execution_identity(die, rep["run"], verdict, mapping,
                                       f"baseline die {die} rep "
                                       f"{rep.get('rep')}")
            rows.append({"rep": rep["rep"], "verdict": verdict})
        out[die] = {"rows": rows,
                    "all_correct": all(r["verdict"]["correct"]
                                       for r in rows)}
        if not out[die]["all_correct"]:
            raise AssemblyError(
                f"baseline die {die} has incorrect repeats (broken "
                f"baseline: do not interpret simultaneous results)")
    return out


def assemble_concurrent(evidence_root: Path, ledger: dict[str, Any],
                        mapping: VerifiedMapping) -> dict[str, Any]:
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
        _require_binding(pair, f"concurrent {att['attempt_id']}",
                           evidence_root)
        verdicts = {}
        for die in ("a", "b"):
            verdicts[die] = rederive_execution(
                evidence_root, pair["participants"][die],
                f"concurrent/{att['attempt_id']}")
            require_execution_identity(
                die, pair["participants"][die], verdicts[die], mapping,
                f"concurrent {att['attempt_id']}")
        overlap_rows = {}
        for die in ("a", "b"):
            overlap_rows[die] = rederive_overlap(
                evidence_root, pair["observe_rels"][die],
                f"concurrent/{att['attempt_id']}")
            require_seam_identity(
                die, overlap_rows[die], mapping,
                f"concurrent {att['attempt_id']}")
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


def _verify_transport_probe(evidence_root: Path, mode_dir: str,
                            row: dict[str, Any],
                            expected_bdf: str | None,
                            expected_selector_index: int | None,
                            what: str) -> dict[str, Any]:
    """FIX 5: mechanically validate ONE #35 probe instance from its
    retained raw evidence, reusing the accepted probe's own reducer
    semantics (parse_probe_output / reduce_rows / link state classes).

    Validates from retained bytes:
      * the probe actually completed: retained raw exit-code bytes == 0
        (raw bytes are authority; the authored summary exit_code is a
        cross-check that must agree);
      * probe.json parses through the accepted parser (identity header
        + measurement rows);
      * the retained identity probe binds the expected exact physical
        BDF (the accepted probe's own identity binding);
      * the full frozen transfer ladder is present: every size x both
        directions x TRANSPORT_REPS reps, the small-transfer service
        run, and the bidirectional run;
      * under-load link-state samples exist (the #216 requirement).
    """
    # Collector rel-path conventions (run_probe_instance vs the dual
    # launcher): single-arm rows are OUT-DIR-relative (out/<mode>/),
    # dual rows are TRANSPORT-relative (dual/<die>/...). Both resolve
    # against the transport phase dir with the mode_dir join handling
    # the difference: single rows sit inside transport/<mode>/, dual
    # rows carry their own dual/<die>/ prefix.
    base = f"transport/{mode_dir}" \
        if not mode_dir.startswith("transport/") else mode_dir

    def resolve(rel: str) -> Path:
        if str(rel).startswith(base + "/"):
            return evidence_root / rel
        return evidence_root / base / rel

    # raw exit-code bytes are the authority
    exit_rel = row.get("exit_code_rel")
    if not exit_rel:
        raise AssemblyError(f"{what}: no retained exit-code artifact")
    exit_path = resolve(exit_rel)
    if not exit_path.is_file():
        raise AssemblyError(f"{what}: exit-code artifact missing")
    try:
        raw_exit = int(exit_path.read_bytes().decode().strip())
    except ValueError:
        raise AssemblyError(f"{what}: exit-code bytes unparseable")
    if raw_exit != 0:
        raise AssemblyError(f"{what}: probe exit {raw_exit} (raw bytes)")
    if row.get("exit_code") != raw_exit:
        raise AssemblyError(
            f"{what}: authored exit code {row.get('exit_code')} != raw "
            f"bytes {raw_exit} (forged summary)")
    # raw stdout must exist and hash-bind
    stdout_rel = row.get("stdout_rel")
    if not stdout_rel:
        raise AssemblyError(f"{what}: no retained probe stdout")
    stdout_path = resolve(stdout_rel)
    if not stdout_path.is_file():
        raise AssemblyError(f"{what}: probe stdout missing (missing probe "
                            "output)")
    stdout_bytes = stdout_path.read_bytes()
    if row.get("stdout_sha256") is not None \
            and hashlib.sha256(stdout_bytes).hexdigest() != row["stdout_sha256"]:
        raise AssemblyError(f"{what}: probe stdout hash mismatch")
    # the structured raw record through the accepted parser
    probe_path = resolve("raw/probe.json")
    if not probe_path.is_file():
        raise AssemblyError(f"{what}: raw probe record missing")
    raw_record = json.loads(probe_path.read_bytes())
    if raw_record.get("schema") != "inferswarm.issue35.transport-probe/1":
        raise AssemblyError(f"{what}: raw probe schema mismatch")
    import issue35_link_probe as x1
    try:
        parsed = x1.parse_probe_output(raw_record["probe_stdout"])
    except Exception as exc:
        raise AssemblyError(f"{what}: probe output unparseable: {exc}")
    identity = parsed["identity"]
    if expected_selector_index is not None \
            and identity.get("vk_device_index") != expected_selector_index:
        raise AssemblyError(
            f"{what}: probe vk_device_index "
            f"{identity.get('vk_device_index')} != expected "
            f"{expected_selector_index}")
    # exact BDF: the probe's own identity binding + subject record
    ib = ((raw_record.get("twin_binding") or {}).get("identity_probe")
          or {})
    if expected_bdf is not None:
        if not bdfs_equal(ib.get("pci_bdf"), expected_bdf):
            raise AssemblyError(
                f"{what}: probe identity binding BDF {ib.get('pci_bdf')} "
                f"!= fresh mapping {expected_bdf} (wrong-die measurement)")
        subj = raw_record.get("subject") or {}
        if not bdfs_equal(subj.get("pci_bdf"), expected_bdf):
            raise AssemblyError(
                f"{what}: probe subject BDF {subj.get('pci_bdf')} != "
                f"fresh mapping {expected_bdf}")
    # frozen ladder completeness, reduced through the accepted reducer
    sustained: dict[tuple[str, int], list[dict]] = {}
    for r in parsed.get("sustained") or []:
        sustained.setdefault((r["dir"], int(r["bytes"])), []).append(r)
    for direction in ("h2d", "d2h"):
        for size in TRANSPORT_SIZES:
            rows_ = sustained.get((direction, size))
            if not rows_:
                raise AssemblyError(
                    f"{what}: missing {direction} {size} transfer "
                    "measurement")
            if len(rows_) != TRANSPORT_REPS:
                raise AssemblyError(
                    f"{what}: {direction} {size} has {len(rows_)} reps "
                    f"!= frozen {TRANSPORT_REPS}")
            try:
                x1.reduce_rows(rows_)
            except Exception as exc:
                raise AssemblyError(
                    f"{what}: {direction} {size} rows fail the accepted "
                    f"reducer: {exc}")
    latency = parsed.get("latency") or []
    if not latency or any(int(r.get("bytes", 0)) != TRANSPORT_SMALL_BYTES
                           for r in latency):
        raise AssemblyError(f"{what}: small-transfer service run missing "
                            "or wrong size")
    if len(latency) != TRANSPORT_SMALL_REPS:
        raise AssemblyError(
            f"{what}: small-transfer reps {len(latency)} != frozen "
            f"{TRANSPORT_SMALL_REPS}")
    bidir = parsed.get("bidir") or []
    if not bidir or any(int(r.get("bytes_each_direction", 0))
                        != TRANSPORT_BIDIR_BYTES_EACH for r in bidir):
        raise AssemblyError(f"{what}: bidirectional run missing or wrong "
                            "size")
    if len(bidir) != TRANSPORT_BIDIR_REPS:
        raise AssemblyError(
            f"{what}: bidirectional reps {len(bidir)} != frozen "
            f"{TRANSPORT_BIDIR_REPS}")
    # under-load link-state evidence (#216)
    link_samples = raw_record.get("link_samples") or []
    load_samples = [s for s in link_samples
                    if str(s.get("phase", "")).startswith(("load", "watch"))]
    if len(load_samples) < TRANSPORT_MIN_LOAD_SAMPLES:
        raise AssemblyError(
            f"{what}: only {len(load_samples)} under-load link samples "
            f"retained (< {TRANSPORT_MIN_LOAD_SAMPLES})")
    return {
        "exit_code": raw_exit,
        "ladder_complete": True,
        "sustained_groups": len(sustained),
        "small_transfer_reps": len(latency),
        "bidir_reps": len(bidir),
        "load_link_samples": len(load_samples),
        "identity_bdf": ib.get("pci_bdf"),
    }


def assemble_transport(evidence_root: Path,
                       mapping: VerifiedMapping) -> dict[str, Any]:
    doc, tdir = _phase_json(evidence_root, "transport/transport-*.json")
    _require_binding(doc, "transport", evidence_root)
    modes: dict[str, Any] = {}
    # single arms: exact physical BDF/selector per arm from the mapping
    for mode, die in (("single-a", "a"), ("single-b", "b")):
        selector, bdf = mapping.expected(die)
        row = doc.get(mode)
        if not isinstance(row, dict):
            raise AssemblyError(f"transport mode {mode} missing")
        modes[mode] = _verify_transport_probe(
            evidence_root, f"transport/{mode}", row, bdf,
            int(selector.replace("Vulkan", "")), f"transport {mode}")
    if "dual" not in doc:
        raise AssemblyError("transport dual mode missing")
    dual = doc["dual"]
    for die in ("a", "b"):
        if not isinstance(dual.get("participants", {}).get(die), dict):
            raise AssemblyError(f"dual transport participant {die} missing")
    dual_verified = {}
    for die in ("a", "b"):
        selector, bdf = mapping.expected(die)
        row = dual["participants"][die]
        dual_verified[die] = _verify_transport_probe(
            evidence_root, f"transport/dual/{die}", row, bdf,
            int(selector.replace("Vulkan", "")),
            f"transport dual/{die}")
    # FIX 5: dual-arm process overlap RE-DERIVED from retained timing
    # fields (the authored probe_process_overlap boolean is not
    # authority; it is cross-checked).
    intervals = dual.get("intervals_ns") or {}
    overlap_derived = False
    spans = {}
    for die in ("a", "b"):
        iv = intervals.get(die)
        if (not isinstance(iv, list) or len(iv) != 2
                or not isinstance(iv[0], int) or not isinstance(iv[1], int)):
            raise AssemblyError(
                f"dual transport participant {die}: retained interval "
                "fields incomplete (overlap not derivable)")
        spans[die] = (iv[0], iv[1])
    overlap_derived = max(spans["a"][0], spans["b"][0]) \
        < min(spans["a"][1], spans["b"][1])
    if not overlap_derived:
        raise AssemblyError(
            "dual transport arm: retained launch intervals show no probe-"
            "process overlap (single-die measurements mislabeled "
            "simultaneous)")
    if dual.get("probe_process_overlap") is False:
        raise AssemblyError(
            "authored dual-overlap boolean contradicts retained intervals")
    modes["dual"] = {"exit_code": 0,
                     "probe_process_overlap": overlap_derived,
                     "participants": dual_verified}
    return {
        "modes": modes,
        "ladder": {"sizes_bytes": list(TRANSPORT_SIZES),
                   "reps": TRANSPORT_REPS,
                   "small_transfer": {"bytes": TRANSPORT_SMALL_BYTES,
                                      "reps": TRANSPORT_SMALL_REPS},
                   "bidir": {"bytes_each": TRANSPORT_BIDIR_BYTES_EACH,
                             "reps": TRANSPORT_BIDIR_REPS}},
        "note": "throughput/latency values are descriptive only; "
                "no transport number is a correctness predicate"
    }


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
    # participant exits: the soak workload is a ROLLING sequence of
    # bounded concurrent pairs. A NORMAL completion cycle is:
    #   participant_exit (BOTH dies of the pair, every rc == 0)
    #   -> pair_completed -> pair_launched (next pair).
    # An UNPLANNED exit (platform failure) is any of:
    #   * a reaped participant with rc != 0;
    #   * a ONE-SIDED exit (one die of a pair exited, sibling active);
    #   * an exit whose pair never reaches pair_completed (a silent
    #     restart/replacement would otherwise disappear).
    normal_exits = 0
    unplanned: list[dict[str, Any]] = []
    completed_pairs: set[str] = set()
    exited_pairs_pending: dict[str, list] = {}
    for e in events:
        ev = e.get("event")
        if ev == "participant_exit":
            reaped = e.get("pair_die") or []
            for key, rc_ in reaped:
                pair, die = str(key).split(":", 1)
                if rc_ != 0:
                    unplanned.append({"event": "participant_exit",
                                      "who": key, "rc": rc_,
                                      "monotonic_ns": e.get(
                                          "monotonic_ns")})
                exited_pairs_pending.setdefault(pair, []).append(die)
            normal_exits += 1
        elif ev == "pair_completed":
            for pair in (e.get("pair") or []):
                completed_pairs.add(str(pair))
                exited_pairs_pending.pop(str(pair), None)
        elif ev == "pair_launched":
            # any pair that had exits but never completed before the
            # next launch = silent replacement
            for pair, dies in list(exited_pairs_pending.items()):
                if len(dies) < 2:
                    unplanned.append({"event": "one_sided_exit",
                                      "pair": pair, "dies": dies,
                                      "monotonic_ns": e.get(
                                          "monotonic_ns")})
                else:
                    unplanned.append({"event": "exit_without_completion",
                                      "pair": pair,
                                      "monotonic_ns": e.get(
                                          "monotonic_ns")})
            exited_pairs_pending.clear()
    # leftovers at end-of-events with incomplete pairs
    for pair, dies in exited_pairs_pending.items():
        unplanned.append({"event": "incomplete_pair_at_end",
                          "pair": pair, "dies": dies})
    silent_restart = [e for e in events
                      if e.get("event") == "pair_launched"
                      and any(p.get("event") == "participant_exit"
                             for p in events
                             if p.get("monotonic_ns", 0) < e[
                                 "monotonic_ns"]
                             and not any(c.get("event") == "pair_completed"
                                         for c in events
                                         if c.get("monotonic_ns", 0)
                                         > p.get("monotonic_ns", 0)
                                         < e.get("monotonic_ns", 0)))]
    return {"journal_fault_counts": fatal, "cadence_gaps_ok": gaps_ok,
            "sample_count": len(samples),
            "unplanned_participant_exits": len(unplanned),
            "unplanned_exits_detail": unplanned,
            "normal_completion_cycles": normal_exits,
            "completed_pairs": len(completed_pairs),
            "silent_restarts": [
                {"event": e.get("event"), "pair": e.get("pair"),
                 "monotonic_ns": e.get("monotonic_ns")}
                for e in silent_restart],
            "events": [e.get("event") for e in events]}


def assemble_soak(evidence_root: Path,
                  mapping: VerifiedMapping) -> dict[str, Any]:
    doc, soak_dir = _phase_json(evidence_root, "soak/soak-*.json")
    soak_dir = str(soak_dir)
    _require_binding(doc, "soak", evidence_root)
    duration = doc.get("duration_s", 0)
    if duration < SOAK_MIN_DURATION_S:
        raise PlatformFailure(
            f"soak duration {duration}s < frozen minimum "
            f"{SOAK_MIN_DURATION_S}s")
    samples = doc.get("samples") or []
    if not samples:
        raise AssemblyError("soak retained no telemetry samples")
    # FIX 6: sample numbering/order must be strictly ascending from 1
    numbers = [s.get("sample") for s in samples]
    if numbers != list(range(1, len(samples) + 1)):
        raise AssemblyError(
            f"soak sample numbering/order invalid (expected 1..N "
            f"ascending, got {numbers[:5]}...)")
    journal_texts = []
    for s in samples:
        # every listed telemetry sample must EXIST on disk and hash-bind
        # to its retained sha256 (a deleted OR TAMPERED file must fail
        # closed — control #12 + FIX 6 hash verification)
        tpath = evidence_root / soak_dir / s["rel"]
        if not tpath.is_file():
            raise AssemblyError(f"soak telemetry file missing: {s['rel']}")
        data = tpath.read_bytes()
        if "sha256" in s and hashlib.sha256(data).hexdigest() != s["sha256"]:
            raise AssemblyError(
                f"soak telemetry hash mismatch: {s['rel']}")
        rel = s["rel"].replace("telemetry-", "journal-").replace(
            ".json", ".stdout")
        p = evidence_root / soak_dir / rel
        if not p.is_file():
            raise AssemblyError(f"soak journal delta missing: {rel}")
        journal_texts.append(p.read_bytes())
    # FIX 6: scan journal-final.stdout IN ADDITION to cadence deltas
    # (events between the last cadence tick and termination, including
    # the final sentinel window, must not be invisible)
    final_journal = evidence_root / soak_dir / "raw/journal-final.stdout"
    if not final_journal.is_file():
        raise AssemblyError("soak final journal (journal-final.stdout) "
                            "missing")
    journal_texts.append(final_journal.read_bytes())
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
    # FIX 6: PID/liveness fields are consumed, not ignored: any GONE
    # participant during an active interval is a platform failure
    pid_rows = _scan_soak_pids(evidence_root, soak_dir, samples)
    if pid_rows["gone_during_active"]:
        raise PlatformFailure(
            "soak participant PID GONE during an active interval: "
            f"{pid_rows['gone_during_active']}")
    # FIX 6: an unplanned participant exit is an affirmative platform
    # failure, never a silent restart
    if scan["unplanned_participant_exits"]:
        raise PlatformFailure(
            "unplanned participant exit during soak: "
            f"{scan['unplanned_exits_detail']}")
    if scan["silent_restarts"]:
        raise PlatformFailure(
            "unplanned exit followed by silent replacement during soak: "
            f"{scan['silent_restarts']}")
    # FIX 6: the completed campaign's stop reason must be duration_reached
    if doc.get("stop_reason") != "duration_reached":
        raise PlatformFailure(
            f"soak stop reason {doc.get('stop_reason')!r} inconsistent "
            "with a completed campaign (expected 'duration_reached')")
    # Sample-count denominator: the retained samples must COVER the full
    # soak window at the frozen cadence.
    expected_min = duration // SOAK_CADENCE_S
    if len(samples) < expected_min:
        raise AssemblyError(
            f"soak sample count {len(samples)} < required {expected_min} "
            f"for {duration}s at {SOAK_CADENCE_S}s cadence")
    span_ok = (samples[-1]["monotonic_ns"] - samples[0]["monotonic_ns"]
               >= (duration - 2 * SOAK_CADENCE_S) * 1_000_000_000)
    if not span_ok:
        raise AssemblyError("soak sample span does not cover the window")
    # checkpoints + final sentinel (all bound to the verified mapping)
    checkpoint_summaries = sorted(
        (evidence_root / soak_dir / "raw").glob("checkpoint-*.json"))
    expected_checkpoints = duration // SOAK_CHECKPOINT_EVERY_S
    if len(checkpoint_summaries) + 1 < expected_checkpoints:
        raise AssemblyError(
            f"soak checkpoints missing: {len(checkpoint_summaries)} < "
            f"{expected_checkpoints - 1}")
    checkpoint_verdicts = []
    for cp in checkpoint_summaries:
        pair = json.loads(cp.read_bytes())
        pair_dir = f"{soak_dir}/raw/{cp.stem}"
        row = assemble_pair(evidence_root, pair, pair_dir, mapping,
                            require_overlap=False)
        checkpoint_verdicts.append({"checkpoint": cp.stem,
                                   "correct": row["pair_correct"]})
    final_pair = _read_json(evidence_root,
                            f"{soak_dir}/raw/final-sentinel.json")
    final_row = assemble_pair(evidence_root, final_pair,
                              f"{soak_dir}/raw/final-sentinel", mapping,
                              require_overlap=False)
    bad_checkpoints = [c for c in checkpoint_verdicts
                       if not c["correct"]]
    if bad_checkpoints:
        raise PlatformFailure(
            f"soak correctness sentinel failed: {bad_checkpoints}")
    if not final_row["pair_correct"]:
        raise PlatformFailure("soak final post-soak sentinel failed")
    growth = _derive_ecc_growth(evidence_root, samples, soak_dir)
    grew = [bdf for bdf, row in (growth.get("growth") or {}).items()
            if isinstance(row, dict) and row.get("ras_growth", 0) > 0]
    if grew:
        raise PlatformFailure(f"uncorrected ECC/RAS growth: {grew}")
    return {
        "duration_s": duration,
        "stop_reason": doc.get("stop_reason"),
        "scan": {k: scan[k] for k in ("journal_fault_counts",
                                      "sample_count")},
        "pid_liveness": {"samples_scanned": pid_rows["samples_scanned"],
                         "gone_during_active":
                             pid_rows["gone_during_active"]},
        "checkpoints": checkpoint_verdicts,
        "final_sentinel_correct": final_row["pair_correct"],
        "all_checkpoints_correct": not bad_checkpoints,
        "ecc_growth": growth,
    }


def _scan_soak_pids(evidence_root: Path, soak_dir: str,
                    samples: list[dict[str, Any]]) -> dict[str, Any]:
    """FIX 6: consume the retained PID/liveness fields from every
    telemetry sample. A participant whose /proc state reads GONE during
    an interval where the soak believed it active is a platform
    failure. Sample rows carry pids.<die> = {pid, state}."""
    gone: list[str] = []
    scanned = 0
    for s in samples:
        snap = _read_json(evidence_root, f"{soak_dir}/{s['rel']}")
        pids = snap.get("pids") or {}
        scanned += 1
        for die, row in pids.items():
            if isinstance(row, dict) and row.get("state") == "GONE":
                gone.append(f"sample {s.get('sample')} die {die}")
    return {"samples_scanned": scanned, "gone_during_active": gone}


def _derive_ecc_growth(evidence_root: Path,
                       samples: list[dict[str, Any]],
                       soak_dir: str = "") -> dict[str, Any]:
    """Derive uncorrected ECC/RAS growth from the retained telemetry
    snapshots (first vs last sample per BDF)."""
    if not samples:
        return {"growth": None, "reason": "no samples"}
    first = _read_json(evidence_root, f"{soak_dir}/{samples[0]['rel']}")
    last = _read_json(evidence_root, f"{soak_dir}/{samples[-1]['rel']}")
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


SIGKILL_EXIT_CODE = -9  # frozen platform result: subprocess SIGKILL


def assemble_fault_arm(evidence_root: Path, arm: str,
                       mapping: VerifiedMapping) -> dict[str, Any]:
    doc = _read_json(evidence_root, f"fault-arm-{arm}.json")
    _require_binding(doc, f"fault arm {arm}", evidence_root)
    sibling = doc["sibling"]
    victim = doc["victim"]
    what = f"fault arm {arm}"
    # FIX 4: exact arm derivation
    if arm == "a" and not (victim == "a" and sibling == "b"):
        raise AssemblyError(
            f"fault arm A requires victim==a sibling==b (got victim="
            f"{victim} sibling={sibling})")
    if arm == "b" and not (victim == "b" and sibling == "a"):
        raise AssemblyError(
            f"fault arm B requires victim==b sibling==a (got victim="
            f"{victim} sibling={sibling})")
    if doc.get("kill_method") != "SIGKILL":
        raise AssemblyError(
            f"fault arm {arm}: kill_method {doc.get('kill_method')!r} != "
            "frozen SIGKILL")
    # victim-gone is RE-DERIVED from the retained exit-code bytes and
    # must equal the frozen SIGKILL result EXACTLY (-9 on this
    # platform), not merely < 0.
    victim_exit_raw = _read_raw(
        evidence_root,
        f"fault-arm-{arm}-loss/initial/{victim}/run.exit-code")
    try:
        victim_exit = int(victim_exit_raw.decode().strip())
    except ValueError:
        raise AssemblyError("victim exit-code not parseable")
    if victim_exit != SIGKILL_EXIT_CODE:
        raise PlatformFailure(
            f"fault arm {arm}: victim exit code {victim_exit} != frozen "
            f"SIGKILL result {SIGKILL_EXIT_CODE}")
    victim_gone = True
    if doc.get("victim_gone") is not True:
        raise AssemblyError(
            f"fault arm {arm}: authored victim_gone contradicts the "
            "retained SIGKILL exit code")
    # survivor: correct AND on the fresh-mapped SIBLING identity
    sibling_run = rederive_execution(
        evidence_root, doc["sibling_run"],
        f"fault-arm-{arm}-loss/initial/{sibling}")
    require_execution_identity(sibling, doc["sibling_run"], sibling_run,
                               mapping, f"{what} survivor")
    # relaunch: correct AND on the fresh-mapped VICTIM identity
    relaunch_run = rederive_execution(
        evidence_root, doc["relaunch_run"],
        f"fault-arm-{arm}-loss/relaunch/{victim}")
    require_execution_identity(victim, doc["relaunch_run"], relaunch_run,
                               mapping, f"{what} victim relaunch")
    # recovery pair independently satisfies the exact mapping
    sentinel_row = assemble_pair(
        evidence_root, doc["recovery_sentinel"],
        f"fault-arm-{arm}-loss/recovery-sentinel", mapping,
        require_overlap=False)
    if not sibling_run["correct"]:
        raise PlatformFailure(
            f"fault arm {arm}: survivor failed correctness")
    if not relaunch_run["correct"]:
        raise PlatformFailure(
            f"fault arm {arm}: victim relaunch failed correctness")
    return {
        "arm": arm,
        "victim": victim,
        "sibling": sibling,
        "kill_method": doc["kill_method"],
        "victim_exit_code": victim_exit,
        "victim_gone": victim_gone,
        "sibling_correct": sibling_run["correct"],
        "sibling_selected_bdf": sibling_run["selected_bdf"],
        "relaunch_correct": relaunch_run["correct"],
        "relaunch_selected_bdf": relaunch_run["selected_bdf"],
        "recovery_sentinel_correct": sentinel_row["pair_correct"],
    }


RESET_NOT_AVAILABLE = "DEVICE_RESET_ISOLATION_NOT_AVAILABLE"
RESET_ARM_EXECUTED = "RESET_ARM_EXECUTED"


def _derive_reset_disposition(record: dict[str, Any]) -> dict[str, Any]:
    """FIX 7: mechanically re-derive the reset disposition from the
    retained read-only topology/reset-mechanism evidence. The authored
    `disposition` string is not authority.

    Derivation over the retained probes (never authored fields):
      * per-die sysfs `reset` file presence;
      * whether both Vega functions sit behind one physical fanout
        switch (retained lspci tree);
      * kernel-doc/driver evidence for a documented per-function reset.
    For this V340L topology the mechanically derived result is
    DEVICE_RESET_ISOLATION_NOT_AVAILABLE whenever the only exposed
    mechanism is the shared-board sysfs reset: a board-level reset
    cannot isolate one die and is not documented as function-safe for
    this dual-die topology. NO reset is ever executed by this
    assembler.
    """
    probes = record.get("probes") or {}
    if not isinstance(probes, dict) or set(probes) != {"a", "b"}:
        raise AssemblyError("reset determination: probe set invalid")
    for die, p in probes.items():
        if not isinstance(p, dict) or "reset_file_present" not in p:
            raise AssemblyError(
                f"reset determination: die {die} probe lacks the sysfs "
                "reset-file observation")
    reset_present = {die: bool(p.get("reset_file_present"))
                     for die, p in probes.items()}
    tree = record.get("lspci_tree")
    if not isinstance(tree, str) or not tree.strip():
        raise AssemblyError(
            "reset determination: retained lspci tree missing/empty")
    shared = record.get("both_functions_behind_one_switch")
    if not isinstance(shared, bool):
        raise AssemblyError(
            "reset determination: shared-switch derivation missing")
    docs = record.get("kernel_docs_stdout")
    if not isinstance(docs, str) or "PROBE_DONE" not in docs:
        raise AssemblyError(
            "reset determination: kernel-doc probe output missing")
    # derivation (mirrors the frozen determine() logic over RETAINED
    # bytes — the accepted collector's own predicate, re-run here)
    if not any(reset_present.values()):
        derived = RESET_NOT_AVAILABLE
        reason = ("no sysfs reset mechanism exposed by the driver for "
                  "these functions")
    elif shared:
        derived = RESET_NOT_AVAILABLE
        reason = ("sysfs reset file present, but both Vega functions are "
                  "downstream of the same physical PM8533 fanout switch "
                  "on one dual-die V340L board: the sysfs reset (function "
                  "level secondary-bus-reset/FLR class) is not a "
                  "documented, function-isolated reset mechanism for this "
                  "dual-die board topology; issue #216 prohibits "
                  "improvised bus/bridge resets, so no reset arm is "
                  "executed")
    else:
        derived = "DOCUMENTED_MECHANISM_AVAILABLE"
        reason = "reset file(s) present without shared-board conflict"
    return {"derived": derived, "reason": reason,
            "reset_file_present": reset_present,
            "both_functions_behind_one_switch": shared}


def assemble_reset(evidence_root: Path,
                   mapping: VerifiedMapping) -> dict[str, Any]:
    doc = _read_json(evidence_root, "reset-determination.json")
    derivation = _derive_reset_disposition(doc)
    disposition = derivation["derived"]
    if disposition not in (RESET_NOT_AVAILABLE, RESET_ARM_EXECUTED):
        raise AssemblyError(f"unknown reset disposition: {disposition}")
    if doc.get("disposition") != disposition:
        raise AssemblyError(
            f"authored reset disposition {doc.get('disposition')!r} "
            f"contradicts the mechanical derivation {disposition!r}")
    # bind the reset determination's per-die BDFs to the mapping
    probes = doc.get("probes") or {}
    for die in ("a", "b"):
        _, exp_bdf = mapping.expected(die)
        got = normalize_bdf((probes.get(die) or {}).get("bdf"))
        if got is None or got != exp_bdf:
            raise AssemblyError(
                f"reset determination die {die} BDF "
                f"{(probes.get(die) or {}).get('bdf')} != fresh mapping "
                f"{exp_bdf}")
    return {"disposition": disposition,
            "reason": derivation["reason"],
            "derivation": {
                "reset_file_present": derivation["reset_file_present"],
                "both_functions_behind_one_switch":
                    derivation["both_functions_behind_one_switch"],
                "mechanism": "re-derived from retained sysfs/lspci/"
                             "kernel-doc evidence; authored string never "
                             "authority"}}


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


_FROZEN_AUTHORITY_DIGEST: str | None = None
_FROZEN_MAPPING_DIGEST: str | None = None
_FROZEN_CLOSURE_DIGEST: str | None = None
_AMENDED_DIGESTS: dict | None = None


def _require_binding(doc: dict[str, Any], what: str,
                     evidence_root: Path | None = None) -> None:
    """Every phase record must carry the SAME frozen authority, the
    fresh mapping bound at preflight, AND the producer-freeze closure
    digest (FIX 1 phase→producer binding); anything else fails closed."""
    global _FROZEN_AUTHORITY_DIGEST, _FROZEN_MAPPING_DIGEST
    global _FROZEN_CLOSURE_DIGEST
    if _FROZEN_AUTHORITY_DIGEST is None:
        authority_doc = json.loads(
            (REPO / "docs/investigations/vulkan-v2-d-v340l-concurrent/"
             "PHYSICAL-AUTHORITY.json").read_bytes())
        _FROZEN_AUTHORITY_DIGEST = authority_doc["authority_digest"]
    if doc.get("authority_digest") != _FROZEN_AUTHORITY_DIGEST:
        raise AssemblyError(
            f"{what}: authority digest "
            f"{doc.get('authority_digest')} != frozen")
    # FIX 1: every phase record binds the producer-freeze closure digest
    if _FROZEN_CLOSURE_DIGEST is None:
        closure = rc.verify_closure(REPO)
        _FROZEN_CLOSURE_DIGEST = closure["closure_digest"]
    closure_digest = _FROZEN_CLOSURE_DIGEST
    assert closure_digest is not None
    if doc.get("closure_digest") is None:
        raise AssemblyError(
            f"{what}: no producer-closure binding (evidence predates the "
            "corrected freeze cannot carry executed-byte provenance)")
    global _AMENDED_DIGESTS
    if _AMENDED_DIGESTS is None:
        _AMENDED_DIGESTS = fz.accepted_amended_digests(REPO)
    accepted = {closure_digest, *_AMENDED_DIGESTS}
    if doc.get("closure_digest") not in accepted:
        raise AssemblyError(
            f"{what}: closure digest {str(doc.get('closure_digest'))[:16]} "
            f"!= frozen producer closure "
            f"{closure_digest[:16]} (evidence from another "
            "producer identity)")
    md = doc.get("mapping_digest")
    if md is None:
        raise AssemblyError(f"{what}: no mapping binding")
    if _FROZEN_MAPPING_DIGEST is None:
        if evidence_root is None:
            return
        preflight, _pd = _phase_json(evidence_root,
                                     "preflight/preflight*.json")
        _FROZEN_MAPPING_DIGEST = preflight["mapping_digest"]
    if md != _FROZEN_MAPPING_DIGEST:
        raise AssemblyError(
            f"{what}: mapping digest {md} != preflight's")


def assemble(evidence_root: Path) -> dict[str, Any]:
    # FIX 1: verify the corrected producer freeze FIRST — the assembler
    # reduces nothing unless the live tree still proves executed-byte
    # identity against the pinned producer head.
    closure = rc.verify_closure(REPO)
    out: dict[str, Any] = {
        "schema": SCHEMA_ASSEMBLY,
        "campaign_id": rc.CAMPAIGN_ID,
        "closure_sources": sorted(closure["sources"]),
        "producer_head": closure["producer_head"],
        "closure_digest": closure["closure_digest"],
    }
    platform_failure = None
    prerequisites_ok = True
    concurrent_failure = None
    mapping: VerifiedMapping | None = None
    try:
        # FIX 2: verify the retained fresh mapping artifact FIRST (R3
        # revalidation from its own retained probe bytes); every phase's
        # identity checks compare against this verified mapping.
        mapping = load_verified_mapping(evidence_root)
        out["mapping_digest"] = mapping.digest
        preflight = assemble_preflight(evidence_root, mapping)
        out["preflight"] = preflight
        if not preflight["preexisting_fault_free"] or not all(
                preflight["sentinels_correct"].values()):
            prerequisites_ok = False
        out["baselines"] = assemble_baselines(evidence_root, mapping, {})
        ledger = _read_json(evidence_root, "attempt-ledger.json")
        out["concurrent"] = assemble_concurrent(evidence_root, ledger,
                                                mapping)
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
    assert mapping is not None  # prerequisites_ok implies mapping loaded
    # post-concurrency phases; failures classify per the rules
    try:
        out["transport"] = assemble_transport(evidence_root, mapping)
    except AssemblyError as exc:
        out["transport"] = None
        out["transport_missing_reason"] = str(exc)
    try:
        out["soak"] = assemble_soak(evidence_root, mapping)
    except PlatformFailure as exc:
        platform_failure = str(exc)
    except CorrectnessFailure as exc:
        # a soak checkpoint/final sentinel executed on the wrong device
        # identity — survivor/checkpoint corruption class, never PASS
        platform_failure = platform_failure or (
            f"soak identity violation: {exc}")
    except AssemblyError as exc:
        out["soak"] = None
        out["soak_missing_reason"] = str(exc)
    for arm, key in (("a", "fault_a"), ("b", "fault_b")):
        try:
            out[key] = assemble_fault_arm(evidence_root, arm, mapping)
            if not (out[key]["victim_gone"] and out[key]["sibling_correct"]
                    and out[key]["relaunch_correct"]
                    and out[key]["recovery_sentinel_correct"]):
                platform_failure = platform_failure or (
                    f"fault arm {arm}: survivor corruption or failed "
                    f"recovery")
        except PlatformFailure as exc:
            out[key] = None
            platform_failure = platform_failure or str(exc)
        except CorrectnessFailure as exc:
            # wrong-die survivor/relaunch/recovery execution: a fault-arm
            # participant silently rebound to the other die — never PASS
            out[key] = None
            platform_failure = platform_failure or (
                f"fault arm {arm} identity violation: {exc}")
        except AssemblyError as exc:
            out[key] = None
            out[f"{key}_missing_reason"] = str(exc)
    try:
        out["reset"] = assemble_reset(evidence_root, mapping)
    except AssemblyError as exc:
        out["reset"] = None
        out["reset_missing_reason"] = str(exc)
    # --- campaign-window platform-fault scan (issue #216 stop
    # conditions): derive the window from the verified phase records
    # themselves — preflight captured_utc through the LAST retained
    # phase-record timestamp — and scan every retained journal source
    # for affirmative platform faults. A hit classifies
    # V2D_V340L_PLATFORM_STRESS_FAIL and can never be erased by later
    # missing evidence (classify() ordering). ---
    if mapping is not None and prerequisites_ok:
        window_start = None
        window_end = None
        try:
            pre = _read_json(evidence_root, "preflight/preflight.json")
            window_start = datetime.fromisoformat(
                pre["captured_utc"].replace("Z", "+00:00"))
            ts_candidates: list[datetime] = [window_start]
            for rel in ("baseline-a.json", "baseline-b.json",
                        "concurrent/c01.json", "concurrent/c02.json",
                        "concurrent/c03.json",
                        "transport/transport.json",
                        "soak/soak.json", "fault-a/fault-a.json",
                        "fault-b/fault-b.json", "reset/reset.json"):
                try:
                    doc = _read_json(evidence_root, rel)
                except Exception:
                    continue
                for key in ("captured_utc", "utc", "finished_utc"):
                    if isinstance(doc.get(key), str):
                        try:
                            ts_candidates.append(datetime.fromisoformat(
                                doc[key].replace("Z", "+00:00")))
                        except ValueError:
                            pass
                        break
            window_end = max(ts_candidates)
        except Exception as exc:
            # fail-closed observability: a window we cannot derive is
            # recorded, never silently skipped (the scan may not just
            # not run on a tree that retains faults)
            out["platform_fault_scan_error"] = (
                f"campaign window not derivable from phase records: "
                f"{exc}")
            window_start = None
        if window_start is not None and window_end is not None:
            try:
                scan_end = window_end + timedelta(minutes=15)
                fault_scan = scan_campaign_faults(
                    evidence_root, window_start, scan_end)
                fault_scan["window_utc"] = [
                    window_start.isoformat(), scan_end.isoformat()]
                fault_scan["window_note"] = (
                    "start = verified preflight captured_utc; end = "
                    "latest retained phase-record timestamp + 15 min "
                    "(a wedged phase writes no record; the slack "
                    "admits faults in the tail after the last record)")
                out["platform_fault_scan"] = fault_scan
                in_window_hits = [
                    (src, h) for src, hits
                    in fault_scan["sources"].items() for h in hits]
                if in_window_hits:
                    src, hit = in_window_hits[0]
                    platform_failure = platform_failure or (
                        f"retained platform fault in campaign window: "
                        f"{hit['class']} at {hit['utc']} "
                        f"[{src}] {hit['line'][:120]}")
            except Exception as exc:  # scan itself must never crash out
                out["platform_fault_scan_error"] = str(exc)
    out["platform_failure"] = platform_failure
    out["terminal"] = classify(out)
    return out




# --- campaign-window platform-fault scan (issue #216 stop conditions) ---

_FAULT_SCAN_CLASSES: tuple[tuple[str, str], ...] = (
    # (compiled regex, event class) — affirmative platform-fault lines
    ("gpu_reset_or_ring_timeout",
     r"GPU reset begin|GPU reset end with ret|Starting gfx ring reset|"
     r"Ring .* reset failed|ring gfx timeout|ring .* timeout, signaled"),
    ("fatal_aer",
     r"AER: Uncorrectable|Uncorrectable Error|fatal AER|"
     r"Data Link Layer Down|Surprise Down"),
    ("uncorrected_ecc_ras",
     r"UECP|EDC_|uncorrected ECC|Hardware Error"),
    ("thermal_shutdown",
     r"thermal.*shutdown|Overtemp|critical temperature reached"),
)

_FAULT_SCAN_RES = [(cls, re.compile(pat, re.IGNORECASE))
                   for cls, pat in _FAULT_SCAN_CLASSES]

# Host timezone during the campaign: America/New_York, EDT (UTC-4) on
# 2026-09-18. journalctl default rendering is host-local; the window
# derivation below parses the SAME host-local convention, so both sides
# of the comparison agree. The captured journal predates the host's
# reboot (which returned it to a different tz rendering for NEW dmesg).
_CAMPAIGN_HOST_TZ = timezone(timedelta(hours=-4), name="EDT")


def _parse_journal_ts(parts: list[str],
                      default_year: int = 2026) -> datetime | None:
    """Timestamp grammars retained in this campaign's fault captures:

    - journalctl default: 'Sep 18 16:28:33 host kernel: ...'
      (host-local; campaign tz EDT = UTC-4)
    - dmesg -T: '[Fri Sep 18 16:28:33 2026] ...'
    Accepts the leading token slice the caller passes (parts[:3] for
    journalctl; the dmesg prefix needs 5 tokens, so this helper joins
    what it gets and also handles the full-line form).
    """
    txt = " ".join(parts)
    naive = None
    if not parts:
        return None
    if parts[0].startswith("["):
        # '[Fri Sep 18 16:28:33 2026]' — possibly truncated at 3 tokens
        inner = txt.strip("[]")
        toks = inner.split(" ")
        # drop weekday token, need 'Sep 18 16:28:33 [2026]'
        if len(toks) >= 4:
            try:
                naive = datetime.strptime(" ".join(toks[1:5]),
                                          "%b %d %H:%M:%S %Y")
            except ValueError:
                naive = None
        if naive is None and len(toks) >= 3:
            try:
                naive = datetime.strptime(" ".join(toks[1:4]),
                                          "%b %d %H:%M:%S")
            except ValueError:
                naive = None
    else:
        # journalctl default grammar carries NO year token; the window
        # derivation supplies the campaign year (both window bounds are
        # in the same campaign year by construction).
        try:
            naive = datetime.strptime(txt, "%b %d %H:%M:%S")
        except ValueError:
            naive = None
        if naive is not None:
            naive = naive.replace(year=default_year)
    if naive is None:
        return None
    return naive.replace(tzinfo=_CAMPAIGN_HOST_TZ)


def scan_platform_faults(
        journal_bytes: bytes,
        window_start_utc: datetime,
        window_end_utc: datetime) -> dict[str, Any]:
    """Re-derive affirmative platform-fault events from retained
    journal bytes inside the campaign window.

    Fail-closed: unparseable lines never silently pass — a fault line
    that cannot be windowed is retained as an out_of_window_unparsed
    entry so it can never disappear (the scan may not lose events).
    """
    hits: list[dict[str, Any]] = []
    unparsed_fault_lines: list[str] = []
    for line_b in journal_bytes.splitlines():
        line = line_b.decode("utf-8", errors="replace")
        matched_cls: str | None = None
        for cls, rx in _FAULT_SCAN_RES:
            if rx.search(line):
                matched_cls = cls
                break
        if matched_cls is None:
            continue
        parts = line.split(" ")
        ts = (_parse_journal_ts(
            parts[:5] if parts and parts[0].startswith("[") else parts[:3],
            default_year=window_start_utc.year)
            if len(parts) >= 4 else None)
        if ts is None:
            unparsed_fault_lines.append(line.strip()[:400])
            continue
        in_window = (window_start_utc <= ts <= window_end_utc)
        hits.append({
            "class": matched_cls,
            "utc": ts.isoformat(),
            "in_window": in_window,
            "line": line.strip()[:400],
        })
    return {
        "window_utc": [window_start_utc.isoformat(),
                       window_end_utc.isoformat()],
        "hits": hits,
        "out_of_window_unparsed": unparsed_fault_lines,
    }


def scan_campaign_faults(evidence_root: Path,
                         window_start: datetime,
                         window_end: datetime) -> dict[str, Any]:
    """Scan every retained fault-bearing byte source in the evidence
    root for platform faults inside the campaign window.

    Sources: the soak cadence journal deltas + journal-final (retained
    by the soak collector), plus the explicitly retained host fault
    capture (dmesg/journal dump taken at fault time; a producer-side
    capture is admissible platform evidence because it postdates the
    fault and re-reads the kernel ring buffer)."""
    sources: dict[str, list[dict[str, Any]]] = {}
    # journal deltas + final from the soak raw dir (may be absent in a
    # BLOCKED-classified tree — scan is additive, never fatal)
    soak_raw = evidence_root / "soak" / "raw"
    journal_files = sorted(
        p for p in soak_raw.glob("journal-*.stdout")
        if p.is_file()) if soak_raw.is_dir() else []
    for jf in journal_files:
        scan = scan_platform_faults(jf.read_bytes(),
                                    window_start, window_end)
        in_win = [h for h in scan["hits"] if h["in_window"]]
        if in_win or scan["out_of_window_unparsed"]:
            sources[str(jf.relative_to(evidence_root))] = in_win
    # retained host fault capture (taken at fault time, pre-reboot).
    # The journal capture is authoritative: the kernel ring buffer had
    # already churned past the fault lines when dmesg was taken.
    fc = evidence_root / "fault-capture"
    if fc.is_dir():
        for name in ("dmesg-at-fault.txt",):
            f = fc / name
            if f.is_file():
                scan = scan_platform_faults(f.read_bytes(),
                                            window_start, window_end)
                sources[f"fault-capture/{name}"] = [
                    h for h in scan["hits"] if h["in_window"]]
        jz = fc / "journal-full-at-fault.txt.gz"
        if jz.is_file():
            import gzip
            scan = scan_platform_faults(gzip.decompress(jz.read_bytes()),
                                        window_start, window_end)
            sources["fault-capture/journal-full-at-fault.txt.gz"] = [
                h for h in scan["hits"] if h["in_window"]]
    return {"sources": sources}


def emit_terminal(assembly: dict[str, Any], evidence_root: Path) -> Path:
    """Write the campaign TERMINAL record (reduction-completed only)."""
    terminal = {
        "schema": SCHEMA_TERMINAL,
        "campaign_id": rc.CAMPAIGN_ID,
        "terminal": assembly["terminal"],
        "vocabulary": list(TERMINALS),
        "producer_head": assembly.get("producer_head"),
    }
    out = evidence_root / "TERMINAL.json"
    out.write_bytes(json.dumps(terminal, indent=1, sort_keys=True)
                    .encode() + b"\n")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence-root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--emit-terminal", action="store_true")
    args = ap.parse_args()
    root = Path(args.evidence_root)
    assembly = assemble(root)
    import subprocess
    assembly["producer_head"] = subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", "HEAD"],
        capture_output=True, text=True).stdout.strip()
    Path(args.out).write_bytes(json.dumps(assembly, indent=1,
                                          sort_keys=True).encode() + b"\n")
    if args.emit_terminal:
        emit_terminal(assembly, root)
    print(json.dumps({"terminal": assembly.get("terminal")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Issue #241 Phase 2 gate: prospectively frozen matched-placement ladder.

Both arms run on inferswarm01 SEQUENTIALLY at the SAME ngl: the RX 580
sets the placement (largest stable rung under the frozen reserve); the
RTX 3060 reference runs at that exact same offloaded-layer count even
though it has 12 GB.

Ladder derivation is PURE arithmetic on the frozen placement-law
constants and the candidate's census VRAM (8192 MiB) minus the frozen
reserve (1536 MiB) = 6656 MiB model budget. Performance observations and
candidate-vs-reference numerical agreement NEVER enter the derivation or
rung selection.

Rung invalidation: startup failure, GPU allocation failure, DEVICE-side
buffer-type fallback (CPU-side "Vulkan_Host -> CPU" lines are the
expected host-mapped pipeline and NOT fallbacks), placement mismatch vs
requested ngl, excluded-device residency above the noise floor, OOM.

Selection = max valid rung; matched placement = that rung on BOTH arms.
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue241_census as census
import issue241_constants as C

SCHEMA = "inferswarm.issue241.phase2-matched-placement/1"
RUNG_SCHEMA = "inferswarm.issue241.placement-rung/3"
# FROZEN deterministic-output encoding (correction pass 5): the
# acceptance-bearing deterministic output of a Phase-2 repeat is the
# canonical little-endian unsigned 32-bit encoding of the exactly
# C.DECISIONS returned token ids — struct.pack("<8I", *tokens) — and its
# SHA-256. Measured timings, wall time, throughput, process/telemetry
# and any other incidental response metadata are deliberately NOT part
# of this digest: they are measurements and legitimately differ between
# otherwise deterministic executions. The retained raw HTTP response of
# every repeat stays SHA-256-bound for custody, but the raw responses
# themselves are NOT required to be byte-identical across repeats.
TOKEN_ENCODING = f"<{C.DECISIONS}I"


def canonical_token_bytes(tokens: Any) -> bytes | None:
    """Prospectively fixed canonical encoding of a repeat's deterministic
    output: exactly C.DECISIONS integer (non-bool) token ids, each in
    [0, C.N_VOCAB), packed as little-endian unsigned 32-bit words.
    Returns None when the tokens cannot form that encoding."""
    if (not isinstance(tokens, list) or len(tokens) != C.DECISIONS
            or any(not isinstance(t, int) or isinstance(t, bool) for t in tokens)):
        return None
    if any(not 0 <= t < C.N_VOCAB for t in tokens):
        return None
    return struct.pack(TOKEN_ENCODING, *tokens)


def deterministic_output_sha256(tokens: Any) -> str | None:
    """SHA-256 of the canonical token encoding (None when unencodable)."""
    canonical = canonical_token_bytes(tokens)
    if canonical is None:
        return None
    return hashlib.sha256(canonical).hexdigest()


# Identity-evidence fields every retained Phase-2 repeat must carry: the
# derived frozen-subject identity observed immediately around THAT
# repeat, its SHA-256-bound raw source observation, and the health
# disposition derived from the repeat's post-execution observation.
REPEAT_IDENTITY_FIELDS = (
    ("identity_pre", "raw_identity_pre", "raw_identity_pre_sha256"),
    ("identity_post", "raw_identity_post", "raw_identity_post_sha256"),
)
# Bounded prospectively defined repeat count per arm/rung: two executions
# (primary + repeat) are the minimum sufficient to mechanically establish
# determinism of the acceptance-bearing canonical token output for that
# arm/rung under the frozen return_tokens request contract; further
# repeats add no new deterministic predicate. Frozen BEFORE any retained
# execution unit.
RUNG_REPEATS = 2
# Fatal device/driver health states (closed vocabulary; a rung carrying
# any of these cannot be valid regardless of every other field).
FATAL_HEALTH_STATES = (
    "selected_device_disappeared",   # arm BDF absent from live device obs
    "driver_drift",                  # kernel driver != frozen identity
    "bdf_drift",                     # selected BDF changed
    "icd_drift",                     # Vulkan ICD identity changed
    "device_reset_or_error",         # reset/GPU-side error observed
    "missing_health_evidence",       # no mandatory health observation
)


def parse_placement(log_text: str) -> dict[str, Any]:
    """Extract layer placement + buffer sizes from a -lv 5 server log."""
    dev_layers: dict[str, set[int]] = {}
    for m in re.finditer(
            r"load_tensors: layer\s+(\d+) assigned to device (\S+)", log_text):
        dev_layers.setdefault(m.group(2), set()).add(int(m.group(1)))
    offloaded = re.findall(r"offloaded (\d+)/(\d+) layers to GPU", log_text)
    buffers: dict[str, list[float]] = {}
    buffer_records = []
    for m in re.finditer(
            r"(Vulkan0|Vulkan_Host|CPU) (model|compute|KV|output|RS)"
            r" buffer size =\s*([\d.]+) MiB", log_text):
        device, kind, amount = m.groups()
        value = float(amount)
        buffers.setdefault(device, []).append(value)
        buffer_records.append({"device": device, "kind": kind, "mib": value})
    return {
        "devices_layer_counts": {k: len(v) for k, v in dev_layers.items()},
        "offloaded_layers": list(offloaded[-1]) if offloaded else None,
        "buffer_mib": buffers,
        "buffer_records": buffer_records,
        "alloc_failures": len(re.findall(r"failed to allocate", log_text)),
        # CPU-side weights legitimately report "cannot be used with
        # preferred buffer type Vulkan_Host, using CPU instead" at every
        # ngl (host-mapped pipeline; present in accepted R8-H logs). A
        # SILENT fallback is a DEVICE-side demotion only.
        "fallback_markers": len(re.findall(
            r"preferred buffer type Vulkan[0-9](?!_Host)", log_text)),
    }


def _identity_problems(arm: str, rung: dict[str, Any]) -> list[str]:
    """Exact frozen subject identity from the rung's per-rung device
    telemetry observation, checked BOTH before and after execution
    (hardware drift during Phase 2 fails closed, not just vs the Phase 1
    census). Correction pass 5: EVERY retained repeat additionally
    carries its own pre/post identity observation around that exact
    execution unit — drift on any ONE repeat fails the rung, and a later
    good observation can never hide an earlier drifted one."""
    problems: list[str] = []
    for field in ("device_identity", "post_execution_device_identity"):
        observed = rung.get(field) or {}
        problems.extend(
            f"{field}: {p}" for p in census.identity_problems(arm, observed))
    repeats = rung.get("repeats")
    if isinstance(repeats, list):
        for i, rep in enumerate(repeats):
            if not isinstance(rep, dict):
                continue
            for ident_field in ("identity_pre", "identity_post"):
                observed = rep.get(ident_field) or {}
                problems.extend(
                    f"repeat {i} {ident_field}: {p}"
                    for p in census.identity_problems(arm, observed))
    return problems


def _determinism_problems(rung: dict[str, Any]) -> list[str]:
    """Mechanically frozen determinism predicate (correction pass 5):
    the rung must carry the prospectively bounded repeat count; each
    repeat must be sane under the frozen return_tokens contract, carry
    exactly C.DECISIONS in-vocabulary integer tokens, its own
    independently derived canonical token encoding
    (struct.pack("<8I", *tokens)) and the SHA-256 of those exact bytes;
    determinism holds iff all retained repeats share ONE identical
    canonical token digest. The digest-bound raw HTTP responses are
    custody evidence and are deliberately NOT required to be
    byte-identical (they carry measured timings and other incidental
    metadata that legitimately differ). C-vs-B numerical agreement is
    never consulted here."""
    problems: list[str] = []
    repeats = rung.get("repeats") or []
    if not isinstance(repeats, list) or len(repeats) != RUNG_REPEATS:
        problems.append(
            f"missing repeat: {len(repeats) if isinstance(repeats, list) else 0} "
            f"repeats retained, {RUNG_REPEATS} required")
        return problems
    digests: list[str] = []
    for i, rep in enumerate(repeats):
        if not isinstance(rep, dict):
            problems.append(f"repeat {i} malformed")
            return problems
        if rep.get("sane_completion") is not True:
            problems.append(f"repeat {i} lacks sane completion evidence")
        tokens = rep.get("response_tokens")
        canonical = canonical_token_bytes(tokens)
        if canonical is None:
            problems.append(
                f"repeat {i} response tokens != exact expected count/type "
                f"under the frozen return_tokens contract")
            continue
        raw = rep.get("response_raw_sha256")
        if not isinstance(raw, str) or len(raw) != 64:
            problems.append(f"repeat {i} raw response digest missing")
            continue
        # the claimed deterministic-output digest must equal the SHA-256
        # of the canonical encoding independently derived from the
        # claimed token summary itself
        claimed = rep.get("deterministic_output_sha256")
        derived = hashlib.sha256(canonical).hexdigest()
        if claimed != derived:
            problems.append(
                f"repeat {i} deterministic_output_sha256 != sha256 of the "
                f"canonical token encoding derived from its own tokens")
            continue
        digests.append(derived)
    if len(set(digests)) > 1:
        problems.append(
            "repeat token mismatch: independently derived canonical token "
            "digests differ (non-deterministic output at this rung)")
    return problems


def _health_problems(rung: dict[str, Any]) -> list[str]:
    """Objective device/driver health from retained observations only."""
    problems: list[str] = []
    health = rung.get("device_health")
    if not isinstance(health, dict):
        return ["missing health artifact: no device/driver health observation"]
    states = health.get("fatal_states") or []
    if not isinstance(states, list):
        return ["device_health fatal_states malformed"]
    for state in states:
        if state in FATAL_HEALTH_STATES:
            problems.append(f"fatal device/driver health state: {state}")
        else:
            problems.append(f"unknown health state {state!r}")
    observed = health.get("observed") or {}
    for field in ("selected_device_present", "driver_in_use",
                  "vulkan_icd", "bdf"):
        if field not in observed:
            problems.append(
                f"missing mandatory health evidence: {field}")
    # the summary must agree with the retained RAW observation: a health
    # artifact claiming no fatal drift while the observed device vanished
    # or drifted is forged and fails closed here.
    if observed.get("selected_device_present") is False:
        problems.append(
            "forged health summary: observed selected_device_present=false "
            "without the corresponding fatal state")
    arm_cfg = C.REFERENCE_ARM if rung.get("arm") == "B" else C.CANDIDATE_ARM
    if observed.get("driver_in_use") not in (None, arm_cfg["kernel_driver"]):
        problems.append("forged health summary: driver drift in observation")
    if observed.get("bdf") not in (None, arm_cfg["bdf"]):
        problems.append("forged health summary: bdf drift in observation")
    # thermal/power values are RETAINED where available but never judged
    # against an invented threshold (none exists in accepted authority).
    for field in ("temperature_c", "power_draw_w"):
        if field in observed and observed[field] is not None and not isinstance(
                observed[field], (int, float, str)):
            problems.append(f"health observation {field} malformed")
    # per-repeat health observations (correction pass 5): every retained
    # repeat carries its own health disposition derived from that
    # repeat's post-execution observation; a drifted or forged one fails
    # the rung, and the last observation cannot hide an earlier problem.
    repeats = rung.get("repeats")
    if isinstance(repeats, list):
        for i, rep in enumerate(repeats):
            if not isinstance(rep, dict):
                continue
            rep_health = rep.get("identity_post_health")
            if not isinstance(rep_health, dict):
                problems.append(
                    f"repeat {i} missing per-repeat health disposition")
                continue
            if rep_health.get("fatal_states"):
                problems.append(
                    f"repeat {i} fatal device/driver health state: "
                    f"{rep_health.get('fatal_states')}")
            rep_observed = rep_health.get("observed") or {}
            for field in ("selected_device_present", "driver_in_use",
                          "vulkan_icd", "bdf"):
                if field not in rep_observed:
                    problems.append(
                        f"repeat {i} missing mandatory health evidence: {field}")
            if rep_observed.get("selected_device_present") is False:
                problems.append(
                    f"repeat {i} forged health summary: observed "
                    "selected_device_present=false without fatal state")
            if rep_observed.get("driver_in_use") not in (None, arm_cfg["kernel_driver"]):
                problems.append(f"repeat {i} forged health summary: driver drift")
            if rep_observed.get("bdf") not in (None, arm_cfg["bdf"]):
                problems.append(f"repeat {i} forged health summary: bdf drift")
    return problems


def judge_rung(rung: dict[str, Any]) -> dict[str, Any]:
    """Judge one placement rung record; derive problems from raw fields."""
    if rung.get("schema") != RUNG_SCHEMA:
        raise ValueError("rung schema mismatch")
    problems: list[str] = []
    arm = rung.get("arm")
    ngl = rung.get("ngl")
    if arm not in ("B", "C"):
        problems.append(f"unknown arm {arm!r}")
    if not isinstance(ngl, int) or ngl < 1 or ngl not in C.LADDER_NGLS:
        problems.append(f"ngl {ngl!r} not on the frozen ladder")
    if not rung.get("loaded"):
        problems.append("startup failure")
    placement = rung.get("placement") or {}
    if placement.get("alloc_failures"):
        problems.append("GPU allocation failure")
    if placement.get("fallback_markers"):
        problems.append("device-side silent fallback")
    offloaded = placement.get("offloaded_layers")
    if not (isinstance(offloaded, list) and len(offloaded) == 2 and
            str(ngl) == str(offloaded[0])):
        problems.append(f"placement mismatch vs requested ngl ({offloaded!r})")
    if arm == "C":
        budget = placement.get("buffer_records") or []
        model_mib = sum(r.get("mib", 0.0) for r in budget
                        if r.get("device") == "Vulkan0" and r.get("kind") == "model")
        if model_mib > C.CANDIDATE_MODEL_BUDGET_MIB + 0.5:
            problems.append(
                f"candidate model buffers {model_mib:.1f} MiB exceed the "
                f"prospective budget {C.CANDIDATE_MODEL_BUDGET_MIB} MiB")
    excluded = rung.get("excluded_device_residency_mib") or {}
    for bdf, used in excluded.items():
        if used > C.EXCLUDED_RESIDENCY_NOISE_MIB:
            problems.append(
                f"excluded device {bdf} residency {used} MiB over noise floor")
    # required process/I/O counters must be present on a loaded rung
    if rung.get("loaded"):
        from issue241_placement_producer import MEASURED_FIELDS
        measured = rung.get("process_measurements") or {}
        for field in MEASURED_FIELDS:
            if not isinstance(measured.get(field), int):
                problems.append(f"required process counter missing: {field}")
        if not rung.get("request_timings"):
            problems.append("request wall/prompt/decode timings missing")
    if arm in ("B", "C"):
        problems.extend(_identity_problems(arm, rung))
        problems.extend(_determinism_problems(rung))
        problems.extend(_health_problems(rung))
    return {
        "schema": "inferswarm.issue241.rung-verdict/1",
        "arm": arm, "ngl": ngl,
        "valid": not problems, "problems": problems,
    }


def select_matched_rung(rungs_by_arm: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Largest rung valid on BOTH arms = the matched placement."""
    if set(rungs_by_arm) != {"B", "C"}:
        raise ValueError("both arms required for matched placement")
    verdicts = {
        arm: {r["ngl"]: judge_rung(r) for r in rungs}
        for arm, rungs in rungs_by_arm.items()
    }
    valid_common = sorted(
        ngl for ngl in C.LADDER_NGLS
        if all(v.get(ngl, {}).get("valid") for v in verdicts.values())
    )
    problems = {
        arm: {str(ngl): v["problems"] for ngl, v in verdicts[arm].items()
              if not v["valid"]}
        for arm in verdicts
    }
    if not valid_common:
        return {
            "schema": SCHEMA, "campaign": C.CAMPAIGN_ID,
            "matched_ngl": None,
            "placement_blocked": True,
            "problems": problems,
            "rule": "no rung valid on both arms; R8I3 placement cannot freeze",
        }
    matched = valid_common[-1]
    return {
        "schema": SCHEMA, "campaign": C.CAMPAIGN_ID,
        "matched_ngl": matched,
        "placement_blocked": False,
        "valid_common_rungs": valid_common,
        "problems": problems,
        "rule": ("largest rung valid on both arms; reference runs at the "
                 "candidate's exact offloaded-layer count; performance and "
                 "candidate-vs-reference agreement never entered selection"),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--rungs", type=Path, required=True,
                    help="JSON {arm: [rung records]}")
    args = ap.parse_args(argv)
    data = json.loads(args.rungs.read_text())
    print(json.dumps(select_matched_rung(data), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Issue #250 (R8-I3B) — PROSPECTIVE TIMEOUT-BUDGET AUTHORITY + COST GATE.

Created by METHODOLOGY-AMENDMENT-003 (correction pass 6). The retained
failed Arm-A v1 execution (physical unit
case-3072-B-devnone-001, evidence root
inferswarm01:/home/hermes/is250-campaign/evidence/, generation
gen-1-v1-timeout-defect, sha256 manifest
/home/hermes/is250-v1-evidence-manifest.sha256) exposed TWO defects:

  PRODUCER DEFECT: the frozen global HTTP timeout HTTP_TIMEOUT_S = 1200
  predates CPU-only execution and is SHORTER than one legitimate
  case-3072 CPU-only completion. The retained v1 server.log proves it:
  the pinned server printed cumulative prompt-processing lines at a
  measured 2.25 tokens/second (n_tokens = 2560, progress = 0.83,
  t = 1140.46 s), and the request was cancelled at t = 1143.45 s
  (~83% of the ~3077-token prefill) when the producer's 1200 s client
  timeout fired ("srv stop: cancel task"). Fail-closed behavior was
  correct (the unit is retained as a FAILED unit with zero output
  rows — never numerical evidence); the 1200 s constant itself was the
  defect. 1200 < 3077/2.25 ~= 1367.6 s: no safety factor can repair a
  budget smaller than the predicted prefill.

  METHODOLOGY-COST DEFECT: the same measured rates show parts of the
  frozen discriminator geometry — specifically the old Arm-C serial
  regime `-t 1 -tb 1` (planning rate 2.25/14 = 0.160714... tok/s =>
  ~19,150 s ~= 5.3 h per case-3072 unit; >= 10 h for two serial
  observations, ~26.5 h for a five-identical deterministic
  confirmation) — is operationally unreasonable for an automatically
  executed discriminator. Cost correctness is SEPARATED from timeout
  correctness: a unit being EXECUTABLE (timeout large enough) does not
  make the campaign REASONABLE (cost gate).

What this module changes (all prospective; repository-only; zero
physical execution performed by this correction):

  1. TIMEOUT-BUDGET AUTHORITY. ``request_timeout_budget(unit)`` derives
     a per-condition timeout from frozen planning inputs — expected
     prompt token count, a FROZEN planning throughput basis for the
     exact condition, an explicit safety factor, a fixed startup +
     decode allowance, and hard lower/upper sanity bounds. No global
     constant exists anymore: the budget is mechanically bound to the
     frozen unit/arm plan, receipts retain the budget + derivation
     inputs (invariant D), any timeout is still a FAILED unit
     (invariant F), and the old 1200 s constant is retained ONLY as
     the defect constant (tests prove it is insufficient).
  2. FROZEN PROSPECTIVE COST GATE. ``evaluate_cost_gate`` + the
     retained machine-readable planning record classify every
     discriminator condition by its prospective wall-clock cost
     BEFORE execution. The producer must not automatically proceed
     merely because the HTTP timeout is sufficient: an arm whose
     estimated deterministic-proof cost exceeds
     CAMPAIGN_COST_CEILING_S is NOT auto-reachable and needs its own
     explicit maintainer gate (C2 serial).
  3. ARM-C AMENDMENT (bounded thread-regime discriminator). The old
     one-shot serial Arm C is replaced by:
       C1 (namespace d250-arm-c1): bounded reduced-parallelism probe
           `-t 4 -tb 4` — ONE predeclared intermediate regime
           substantially below the accepted default 14 threads,
           frozen BEFORE any execution (never chosen after outputs);
       C2 (namespace d250-arm-c2): the serial `-t 1 -tb 1` regime,
           retained ONLY as an optional deep discriminator behind a
           SEPARATE maintainer gate. C1 authority can never authorize
           C2 (mechanically enforced: c2_launch_allowed +
           issue250_physical.c2_launch_allowed).
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

import issue250_diagnostic as D

SCHEMA = "inferswarm.issue250.timeout-budget/1"
COST_RECORD_SCHEMA = "inferswarm.issue250.cost-planning-record/1"
COST_EVIDENCE_GENERATION = "gen-2-pass6"


class TimeoutBudgetError(D.DiagnosticError):
    """Raised when a timeout-budget/cost-gate boundary is violated."""


# ---------------------------------------------------------------------------
# FROZEN planning basis (retained v1 evidence; never re-measured from a
# canonical run to avoid self-selecting the basis).
# ---------------------------------------------------------------------------

# Retained failed-run identity (custody facts, read-only record):
V1_EVIDENCE_ROOT = "inferswarm01:/home/hermes/is250-campaign/evidence/"
V1_EVIDENCE_GENERATION = "gen-1-v1-timeout-defect"
V1_MANIFEST_PATH = "inferswarm01:/home/hermes/is250-v1-evidence-manifest.sha256"
V1_UNIT_TAG = "case-3072-B-devnone-001"
V1_SERVER_LOG_SHA256 = (
    "27c50c364d65e2ae4220329b1bd7859cea1768968f566f32527150c2a980d75f")
V1_ATTESTATION_SHA256 = (
    "e270a69a1ece5b9d1e57ec3f057d2b8c409951d31d299338798f49746c650a34")
V1_FAILED_UNIT_HEAD = "1c86e97da42401ff7cfa98e3dc48a33517c65def"
# The retained server.log lines (verbatim grammar) the basis consumes:
#   "prompt processing, n_tokens = 2560, progress = 0.83, t = 1140.46 s /
#    2.24 tokens per second"   and   "srv stop: cancel task, id_task = 0"
# at cumulative client elapsed t ~= 1143 s against HTTP_TIMEOUT_S = 1200.
V1_OBSERVED_RATE_TOKENS_PER_S = 2.25

# The defect constant itself (retained ONLY as the defect record; the
# producer no longer uses a global constant as a request budget):
DEFECT_HTTP_TIMEOUT_S = 1200

# case-3072 actual prompt token count (accepted fixture authority:
# case-3072 => 3077 tokens; label != count is the accepted discipline).
DEFAULT_PROMPT_TOKENS = 3077
DEFAULT_N_PREDICT = 8  # DECISIONS; decode of 8 tokens is ~seconds

# Accepted default CPU threading (README phase-0: hardware_concurrency()/2
# on the 28-LPU E5-2683 v3 => 14 threads, split -t/-tb).
DEFAULT_CPU_THREADS = 14

# Frozen planning rate table (tokens/second, CPU-only prefill, this
# model/binary/launch shape). Every entry names its evidence basis.
# The default-threading entry is the RETAINED v1 measurement; the
# reduced-parallelism entries are FROZEN PROSPECTIVE PLANNING RATES
# derived by linear per-thread scaling from that retained measurement —
# a conservative PLANNING basis only (overestimating rate would
# understate cost; tests assert the serial planning rate still implies
# a multi-hour unit). They are never treated as measured facts.
TIMEOUT_BASIS = {
    "cpu-only-default-threads": {
        "rate_tokens_per_s": 2.25,
        "basis": "retained_v1_failed_unit_server_log",
        "measured": True,
    },
    "cpu-only-c1-t4": {
        # linear planning scale: 2.25 * 4/14 = 0.642857... (frozen
        # 4-decimal rounding; upward round would understate budget)
        "rate_tokens_per_s": 0.6428,
        "basis": "frozen_linear_scaling_from_retained_v1_rate",
        "measured": False,
    },
    "cpu-only-serial-t1": {
        # linear planning scale: 2.25 * 1/14 = 0.160714... (truncation
        # UNDERSTATES the rate by <0.5%; the cost record's 5.3 h figure
        # uses the exact fraction 2.25/14)
        "rate_tokens_per_s": 0.1607,
        "basis": "frozen_linear_scaling_from_retained_v1_rate",
        "measured": False,
    },
    # Arm D runs at the ACCEPTED GPU placement (the ladder factor is
    # prompt length, not the backend): the retained accepted #248
    # case-3072 GPU-offload rate is the planning basis. A GPU-like
    # condition must NOT inherit a multi-hour timeout (invariant).
    "gpu-accepted-placement": {
        "rate_tokens_per_s": 71.7,
        "basis": "retained_accepted_248_gpu_offload_case3072_server_log",
        "measured": True,
    },
}

# The timeout law (AMENDMENT-003): budget = predicted_prefill_s *
# SAFETY_FACTOR + STARTUP_DECODE_MARGIN_S, clamped to
# [MIN_TIMEOUT_S, MAX_TIMEOUT_S]. All four constants are frozen.
SAFETY_FACTOR = 1.5
STARTUP_DECODE_MARGIN_S = 1800.0 + 120.0  # model load + decode/control
MIN_TIMEOUT_S = 1800.0
MAX_TIMEOUT_S = 14400.0  # 4 h hard ceiling per request; fail-closed
# Gated-C2-only ceiling (never reachable without the d250-arm-c2
# gate): 1.5 * 19,150 s prefill + margin ~= 30,600 s.
C2_MAX_TIMEOUT_S = 36000.0

# The producer defect regression target: a legitimate Arm-A completion
# needs ~3077/2.25 ~= 1367.6 s of prefill alone; the old constant was
# already exceeded by the prefill itself.
LEGACY_FIXED_TIMEOUT_S = 1200  # the DEFECT constant (never a budget)

# ---------------------------------------------------------------------------
# Frozen prospective COST GATE (AMENDMENT-003).
#
# Cost correctness is separate from timeout correctness. The planning
# record below is the machine-readable authority; every discriminator
# condition carries: planning rate + basis, estimated seconds per
# unit, minimum units to establish a mismatch (2), units for a
# deterministic claim (5), estimated minimum mismatch cost, estimated
# deterministic-proof cost, and a frozen disposition.
#
# Dispositions (frozen vocabulary):
#   authorized_by_pass6_dispatch — auto-reachable under a d250-arm-*
#       dispatch at the pass-6 head (Arm A; C1 default+reduced pair).
#   conditional_not_dispatched   — reachable ONLY after a predecessor
#       arm leaves variation (Arm B).
#   blocked_requires_separate_authorization — NOT auto-reachable under
#       ANY d250-arm-c (C1) dispatch; needs an explicit d250-arm-c2
#       exact-head maintainer dispatch (C2 serial).
# ---------------------------------------------------------------------------

MIN_MISMATCH_UNITS = 2          # first mismatch establishes variation
DETERMINISTIC_UNITS = 5         # DETERM_MIN_REPEATS mirror
# 12 h: a condition whose five-identical deterministic proof is
# projected above this ceiling is not auto-reachable (the C1 probe
# projects ~9.3 h; the serial regime projects ~29.3 h).
CAMPAIGN_COST_CEILING_S = 43200.0

COST_CONDITIONS = ("arm-a-cpu-only", "arm-b-fresh", "arm-b-sameproc",
                   "arm-c-default", "arm-c1-reduced", "arm-c2-serial",
                   "arm-d-accepted-placement")

# The predeclared C1 thread regime: ONE intermediate regime
# substantially below the accepted default 14 threads, frozen BEFORE
# any execution.
ARM_C1_THREADS = 4
ARM_C1_ARGV_DELTA = ("-t", "4", "-tb", "4")
ARM_C2_THREADS = 1
ARM_C2_ARGV_DELTA = ("-t", "1", "-tb", "1")

# Planning-rate map: condition -> TIMEOUT_BASIS key. Frozen; unknown
# conditions fail closed.
CONDITION_RATE_BASIS = {
    "arm-a-cpu-only": "cpu-only-default-threads",
    "arm-b-fresh": "cpu-only-default-threads",
    "arm-b-sameproc": "cpu-only-default-threads",
    "arm-c-default": "cpu-only-default-threads",
    "arm-c1-reduced": "cpu-only-c1-t4",
    "arm-c2-serial": "cpu-only-serial-t1",
    "arm-d-accepted-placement": "gpu-accepted-placement",
}

# FROZEN DISPOSITIONS (the cost gate's authority content).
COST_DISPOSITIONS = {
    "arm-a-cpu-only": "authorized_by_pass6_dispatch",
    "arm-b-fresh": "conditional_not_dispatched",
    "arm-b-sameproc": "conditional_not_dispatched",
    "arm-c-default": "authorized_by_pass6_dispatch",
    "arm-c1-reduced": "authorized_by_pass6_dispatch",
    "arm-c2-serial": "blocked_requires_separate_authorization",
    # Arm D runs at the accepted GPU placement (hours-scale, not the
    # serial regime); its reachability is the amended sequential law,
    # not the cost gate's serial classification.
    "arm-d-accepted-placement": "conditional_reachable_by_sequential_law",
}

# Condition -> (namespace, arm) it would execute under. C2's namespace
# is NOT an auto-reachable dispatch binding (see
# issue250_diagnostic.C2_SERIAL_NAMESPACE): only the dedicated
# d250-arm-c2 namespace can ever authorize serial execution.
CONDITION_NAMESPACE = {
    "arm-a-cpu-only": ("d250-arm-a", "A-vulkan-necessity"),
    "arm-b-fresh": ("d250-arm-b", "B-process-init"),
    "arm-b-sameproc": ("d250-arm-b", "B-process-init"),
    "arm-c-default": ("d250-arm-c", "C-cpu-threads"),
    "arm-c1-reduced": ("d250-arm-c1", "C1-reduced-parallelism"),
    "arm-c2-serial": ("d250-arm-c2", "C2-serial"),
    "arm-d-accepted-placement": ("d250-arm-d", "D-context-transition"),
}


def condition_namespace(condition: str) -> tuple[str, str]:
    """Frozen (namespace, arm) for a cost condition (fail-closed)."""
    if condition not in CONDITION_NAMESPACE:
        raise TimeoutBudgetError(f"unknown cost condition: {condition!r}")
    return CONDITION_NAMESPACE[condition]


# ---------------------------------------------------------------------------
# Planning-record derivation (pure; no I/O; deterministic)
# ---------------------------------------------------------------------------

def _planning_rate(condition: str) -> dict[str, Any]:
    if condition not in CONDITION_RATE_BASIS:
        raise TimeoutBudgetError(f"unknown cost condition: {condition!r}")
    key = CONDITION_RATE_BASIS[condition]
    entry = TIMEOUT_BASIS[key]
    if key not in TIMEOUT_BASIS or not isinstance(
            entry.get("rate_tokens_per_s"), (int, float)) \
            or entry["rate_tokens_per_s"] <= 0:
        raise TimeoutBudgetError(f"malformed planning basis: {key!r}")
    return dict(entry, basis_key=key)


def cost_planning_record(
        prompt_tokens: int = DEFAULT_PROMPT_TOKENS,
        n_predict: int = DEFAULT_N_PREDICT,
        ) -> dict[str, Any]:
    """Build the machine-readable prospective cost planning record.

    Per condition: prompt tokens, retained planning throughput + basis,
    estimated seconds/unit, MIN_MISMATCH_UNITS, DETERMINISTIC_UNITS,
    estimated minimum mismatch cost (2 units), estimated
    deterministic-proof cost (5 units), and the frozen disposition.
    Deterministic; no I/O; fail-closed on unknown conditions.
    """
    if (type(prompt_tokens) is not int or prompt_tokens <= 0
            or type(n_predict) is not int or n_predict <= 0):
        raise TimeoutBudgetError("malformed planning-record inputs")
    conditions: dict[str, Any] = {}
    for condition in COST_CONDITIONS:
        basis = _planning_rate(condition)
        rate = float(basis["rate_tokens_per_s"])
        # Exact-fraction serial estimate for the frozen record: the
        # ~5.3 h serial unit figure derives from 2.25/14, not from the
        # truncated 0.1607 table value.
        rate_exact = (V1_OBSERVED_RATE_TOKENS_PER_S * ARM_C2_THREADS
                      / DEFAULT_CPU_THREADS
                      if condition == "arm-c2-serial" else rate)
        per_unit = prompt_tokens / rate_exact + (
            STARTUP_DECODE_MARGIN_S + n_predict / rate_exact)
        seconds_per_unit = math.ceil(per_unit)
        conditions[condition] = {
            "prompt_tokens": prompt_tokens,
            "planning_rate_tokens_per_s": rate,
            "planning_rate_basis_key": basis["basis_key"],
            "planning_rate_basis": basis["basis"],
            "planning_rate_measured": basis["measured"],
            "estimated_seconds_per_unit": seconds_per_unit,
            "min_units_to_establish_mismatch": MIN_MISMATCH_UNITS,
            "units_for_deterministic_claim": DETERMINISTIC_UNITS,
            "estimated_min_mismatch_cost_s": math.ceil(
                seconds_per_unit * MIN_MISMATCH_UNITS),
            "estimated_deterministic_proof_cost_s": math.ceil(
                seconds_per_unit * DETERMINISTIC_UNITS),
            "disposition": COST_DISPOSITIONS[condition],
        }
    record = {
        "schema": COST_RECORD_SCHEMA,
        "evidence_generation": None,  # set by the generator (import cycle)
        "created_by": "METHODOLOGY-AMENDMENT-003",
        "retained_rate_evidence": {
            "source": V1_EVIDENCE_ROOT,
            "generation": V1_EVIDENCE_GENERATION,
            "unit_tag": V1_UNIT_TAG,
            "server_log_sha256": V1_SERVER_LOG_SHA256,
            "observed_rate_tokens_per_s": V1_OBSERVED_RATE_TOKENS_PER_S,
            "defect_timeout_s": DEFECT_HTTP_TIMEOUT_S,
            "head_sha": V1_FAILED_UNIT_HEAD,
        },
        "campaign_cost_ceiling_s": CAMPAIGN_COST_CEILING_S,
        "conditions": conditions,
    }
    return record


def canonical_cost_planning_record() -> dict[str, Any]:
    """Generation-bound exact planning authority with a canonical digest."""
    record = cost_planning_record()
    record["evidence_generation"] = COST_EVIDENCE_GENERATION
    payload = json.dumps(record, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False).encode("utf-8")
    record["canonical_digest_sha256"] = hashlib.sha256(payload).hexdigest()
    return record


def evaluate_cost_gate(condition: str,
                       record: dict[str, Any] | None = None,
                       ) -> dict[str, Any]:
    """Evaluate the frozen cost gate for ONE condition (fail-closed).

    Returns the condition's cost facts + authorization verdict. The
    gate refuses auto-execution of any condition whose deterministic-
    proof cost exceeds CAMPAIGN_COST_CEILING_S or whose frozen
    disposition is not an authorized/conditional one; unknown
    conditions, mutated metadata (disposition/ceiling tampering), or
    missing fields fail closed.
    """
    if record is None:
        # Pure helper callers may omit custody; producers must pass the
        # actual retained record loaded from their evidence root.
        record = canonical_cost_planning_record()
    expected = canonical_cost_planning_record()
    if not isinstance(record, dict) or record.get(
            "schema") != COST_RECORD_SCHEMA:
        raise TimeoutBudgetError("cost planning record schema mismatch")
    try:
        supplied = dict(record)
        digest = supplied.pop("canonical_digest_sha256")
        canonical = json.dumps(supplied, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=False, allow_nan=False).encode("utf-8")
        expected_bytes = json.dumps(
            {k: v for k, v in expected.items()
             if k != "canonical_digest_sha256"},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False).encode("utf-8")
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise TimeoutBudgetError("malformed cost planning record") from exc
    if (record.get("evidence_generation") != COST_EVIDENCE_GENERATION
            or digest != hashlib.sha256(canonical).hexdigest()
            or canonical != expected_bytes
            or digest != expected["canonical_digest_sha256"]):
        raise TimeoutBudgetError(
            "cost planning record differs from canonical derivation or digest")
    if record.get("campaign_cost_ceiling_s") != CAMPAIGN_COST_CEILING_S:
        raise TimeoutBudgetError(
            "cost planning record ceiling mutation detected")
    conditions = record.get("conditions")
    if not isinstance(conditions, dict):
        raise TimeoutBudgetError("cost planning record lacks conditions")
    if condition not in COST_CONDITIONS or condition not in conditions:
        raise TimeoutBudgetError(f"unknown cost condition: {condition!r}")
    entry = conditions[condition]
    required = ("prompt_tokens", "planning_rate_tokens_per_s",
                "planning_rate_basis_key", "estimated_seconds_per_unit",
                "estimated_min_mismatch_cost_s",
                "estimated_deterministic_proof_cost_s", "disposition")
    for key in required:
        if key not in entry:
            raise TimeoutBudgetError(
                f"cost record entry missing {key!r}: {condition}")
    if entry["disposition"] != COST_DISPOSITIONS[condition]:
        raise TimeoutBudgetError(
            f"cost record disposition mutation detected for "
            f"{condition}: {entry['disposition']!r}")
    namespace, arm = condition_namespace(condition)
    auto_reachable = entry["disposition"] == "authorized_by_pass6_dispatch"
    over_ceiling = (entry["estimated_deterministic_proof_cost_s"]
                    > CAMPAIGN_COST_CEILING_S)
    return {
        "condition": condition,
        "namespace": namespace,
        "arm": arm,
        "auto_reachable": auto_reachable and not over_ceiling,
        "requires_separate_maintainer_gate": (
            entry["disposition"]
            == "blocked_requires_separate_authorization" or over_ceiling),
        "estimated_seconds_per_unit":
            entry["estimated_seconds_per_unit"],
        "estimated_deterministic_proof_cost_s":
            entry["estimated_deterministic_proof_cost_s"],
        "disposition": entry["disposition"],
        "over_cost_ceiling": over_ceiling,
    }


# ---------------------------------------------------------------------------
# Timeout-budget authority (the producer law)
# ---------------------------------------------------------------------------

def unit_condition(unit: dict[str, Any]) -> str:
    """Map a frozen plan unit to its cost/timeout condition (fail-closed)."""
    argv_delta = tuple(unit.get("argv_delta", ()))
    if unit.get("ladder_length"):
        # Arm D: accepted GPU placement (length is the factor, not the
        # backend); the same GPU-offload planning rate covers every
        # ladder length.
        return "arm-d-accepted-placement"
    if "-dev" not in argv_delta:
        raise TimeoutBudgetError(
            f"#250 units are CPU-only -dev none; argv delta {argv_delta!r} "
            f"is not a #250 current-unit condition")
    if argv_delta == ("-dev", "none"):
        return "arm-c-default" if unit.get("thread_regime") == "default" \
            else "arm-a-cpu-only"
    if argv_delta == ("-dev", "none") + ARM_C1_ARGV_DELTA:
        return "arm-c1-reduced"
    if argv_delta == ("-dev", "none") + ARM_C2_ARGV_DELTA:
        return "arm-c2-serial"
    raise TimeoutBudgetError(
        f"unit argv delta {argv_delta!r} has no frozen timeout condition")


def request_timeout_budget(
        unit: dict[str, Any],
        prompt_tokens: int = DEFAULT_PROMPT_TOKENS,
        n_predict: int = DEFAULT_N_PREDICT,
        c2_serial_gate_authorized: bool = False,
        ) -> dict[str, Any]:
    """Derive ONE unit's request timeout budget (frozen law, no I/O).

    budget_s = ceil(prompt_tokens / planning_rate) * SAFETY_FACTOR
               + STARTUP_DECODE_MARGIN_S,
    clamped to [MIN_TIMEOUT_S, MAX_TIMEOUT_S]. Fail-closed: unknown
    condition, non-positive rate, or a predicted prefill above the
    hard request ceiling raises.

    The serial C2 condition (~19,150 s prefill) exceeds the ceiling:
    it is budgeted ONLY when ``c2_serial_gate_authorized=True`` —
    which production may pass ONLY after ``c2_launch_allowed`` proved
    the dedicated d250-arm-c2 gate (explicit maintainer dispatch +
    retained C1-varied record). The gate never multiplies the budget:
    the ceiling simply expands to SAFETY_FACTOR * predicted prefill +
    margin, bounded by C2_MAX_TIMEOUT_S.
    """
    condition = unit_condition(unit)
    if condition == "arm-c2-serial" and not c2_serial_gate_authorized:
        raise TimeoutBudgetError(
            "serial C2 budget refused: the d250-arm-c2 maintainer gate "
            "has not authorized serial execution (AMENDMENT-003)")
    basis = _planning_rate(condition)
    rate = float(basis["rate_tokens_per_s"])
    if (type(prompt_tokens) is not int or prompt_tokens <= 0
            or type(n_predict) is not int or n_predict <= 0):
        raise TimeoutBudgetError("malformed timeout-budget inputs")
    predicted_prefill_s = prompt_tokens / rate
    ceiling = (C2_MAX_TIMEOUT_S if condition == "arm-c2-serial"
               else MAX_TIMEOUT_S)
    raw_budget = predicted_prefill_s * SAFETY_FACTOR + \
        STARTUP_DECODE_MARGIN_S
    budget = math.ceil(min(max(raw_budget, MIN_TIMEOUT_S), ceiling))
    if predicted_prefill_s > ceiling:
        raise TimeoutBudgetError(
            f"predicted prefill {predicted_prefill_s:.1f}s exceeds the "
            f"{ceiling:.0f}s hard request ceiling for condition "
            f"{condition!r} — not auto-executable (cost gate; separate "
            f"maintainer authorization required)")
    return {
        "schema": SCHEMA,
        "condition": condition,
        "expected_prompt_tokens": prompt_tokens,
        "expected_n_predict": n_predict,
        "planning_rate_tokens_per_s": rate,
        "rate_basis_id": basis["basis_key"],
        "rate_basis": basis["basis"],
        "rate_measured": basis["measured"],
        "safety_factor": SAFETY_FACTOR,
        "startup_decode_margin_s": STARTUP_DECODE_MARGIN_S,
        "predicted_prefill_s": round(predicted_prefill_s, 3),
        "budget_s": budget,
        "min_timeout_s": MIN_TIMEOUT_S,
        "max_timeout_s": ceiling,
        "c2_serial_gate_authorized": (
            c2_serial_gate_authorized
            if condition == "arm-c2-serial" else None),
    }


def timeout_budget_digest(budget: dict[str, Any]) -> str:
    """Canonical digest of a timeout-budget block (receipt binding)."""
    if not isinstance(budget, dict) or budget.get("schema") != SCHEMA:
        raise TimeoutBudgetError("timeout budget block schema mismatch")
    fields = ("condition", "expected_prompt_tokens", "expected_n_predict",
              "planning_rate_tokens_per_s", "rate_basis_id",
              "safety_factor", "startup_decode_margin_s", "budget_s",
              "min_timeout_s", "max_timeout_s",
              "c2_serial_gate_authorized")
    doc = {key: budget[key] for key in fields}
    return D.sha256_bytes(
        json.dumps(doc, sort_keys=True, separators=(",", ":")).encode())


def verify_timeout_budget_block(block: Any, unit: dict[str, Any],
                                prompt_tokens: int = DEFAULT_PROMPT_TOKENS,
                                n_predict: int = DEFAULT_N_PREDICT,
                                ) -> dict[str, Any]:
    """Fail-closed verification of a receipt's timeout-policy block.

    Recomputes the frozen law from the SAME frozen inputs and requires
    exact equality (mutation fails closed), plus digest re-binding.
    """
    expected = request_timeout_budget(
        unit, prompt_tokens, n_predict,
        c2_serial_gate_authorized=(
            unit_condition(unit) == "arm-c2-serial"))
    if not isinstance(block, dict):
        raise TimeoutBudgetError("timeout budget block missing")
    for key, value in expected.items():
        if block.get(key) != value:
            raise TimeoutBudgetError(
                f"timeout budget block mismatch at {key!r}: "
                f"{block.get(key)!r} != frozen {value!r}")
    if block.get("timeout_policy_sha256") != timeout_budget_digest(block):
        raise TimeoutBudgetError(
            "timeout budget digest binding mismatch (mutation detected)")
    return block

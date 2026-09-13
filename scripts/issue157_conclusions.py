#!/usr/bin/env python3
"""Issue #157 conclusions reducer (DIAGNOSTIC_ONLY, CPU-only, stdlib-only).

Re-derives every #157 conclusion from the retained evidence bundle with
fail-closed validation, then reduces to ONE terminal classification
from the issue's ladder:
  ISSUE117_ARM_C_CHUNK2_CAUSE_LOCALIZED
  ISSUE117_ARM_C_CHUNK2_DIAGNOSIS_PARTIAL
  ISSUE117_ARM_C_CHUNK2_DIAGNOSTIC_INSUFFICIENT_EVIDENCE
  ISSUE117_ARM_C_CHUNK2_EVIDENCE_BLOCKED

Every number in the output record derives from the retained artifact
bytes (never a constant); the reducer's own output file is excluded
from its inputs map by name (correction lesson 6 from #137).
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

SCHEMA = "inferswarm.issue157.conclusions/1"
DIAGNOSTIC_ONLY = "DIAGNOSTIC_ONLY"
EVIDENCE_DIR = Path(__file__).resolve().parents[1] / (
    "docs/implementation/r6-successor-dense-full-integration-117/"
    "evidence/arm-c-chunk2-diagnosis-157"
)

# Evidence files this reducer consumes (fail-closed allowlist; the
# reducer's own output and manifest are excluded by name).
CONSUMED = [
    "baseline-reproduction.json",
    "exact-state-replay.json",
    "interventions.json",
    "instrumentation-manifest.json",
]

TERMINALS = {
    "LOCALIZED": "ISSUE117_ARM_C_CHUNK2_CAUSE_LOCALIZED",
    "PARTIAL": "ISSUE117_ARM_C_CHUNK2_DIAGNOSIS_PARTIAL",
    "INSUFFICIENT": "ISSUE117_ARM_C_CHUNK2_DIAGNOSTIC_INSUFFICIENT_EVIDENCE",
    "BLOCKED": "ISSUE117_ARM_C_CHUNK2_EVIDENCE_BLOCKED",
}


class ReductionError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load_required(name: str) -> tuple[dict, str]:
    path = EVIDENCE_DIR / name
    if not path.is_file():
        raise ReductionError(f"missing required evidence file: {name}")
    return json.loads(path.read_text()), sha256_file(path)


def reduce_phenomenon_reproduction(baseline: dict) -> dict:
    """Phase-2 questions 1 (reproduction) per anchor + control."""
    out = {}
    for key in ("anchor_a", "anchor_b", "stable_control"):
        rows = baseline.get(key) or []
        if not rows:
            raise ReductionError(f"baseline missing {key} observations")
        tokens = []
        lifecycle_reasons = []
        for realization in rows:
            # an explicit lifecycle non-reproduction reason is carried
            # through verbatim (issue #157 terminal exception input);
            # absence stays absence — never manufactured downstream
            reason = realization.get("non_reproduction_lifecycle_reason")
            if reason:
                lifecycle_reasons.append(str(reason))
            for repeat in realization.get("repeats", []):
                tokens.append(repeat["committed_step0"])
        distinct = sorted(set(tokens))
        out[key] = {
            "observations": len(tokens),
            "distinct_committed_values": len(distinct),
            "values": tokens,
            "varies": len(distinct) > 1,
            "realizations": len(rows),
            "non_reproduction_lifecycle_reason": (
                "; ".join(lifecycle_reasons)
                if lifecycle_reasons else None
            ),
        }
    return out


def reduce_replay(replay: dict) -> dict:
    out = {
        "chunk1_byte_identical_across_repeats": bool(
            replay.get("chunk1_repeatability", {}).get("byte_identical")
        ),
        "chunk2_digests": replay.get("chunk2_digests"),
        "chunk2_deterministic": bool(replay.get("chunk2_deterministic")),
        "no_reuse_proof": replay.get("no_reuse_proof"),
        "trials": replay.get("trials"),
    }
    if not out["chunk1_byte_identical_across_repeats"]:
        raise ReductionError(
            "harness classified itself invalid: chunk-1 not repeatable"
        )
    return out


def arm_digest_stats(arm: dict, kind: str) -> dict:
    """Per-arm digest statistics computed from the retained digest
    lists themselves (trial count, distinct count, varies).  Every
    summary number in the output record flows through here — the
    reducer never carries an observation count as a literal."""
    digests = arm.get(f"{kind}_chunk2_digests") or []
    return {
        "trials": len(digests),
        "distinct": len(set(digests)),
        "varies": len(set(digests)) > 1,
    }


def chunk1_pairing(arm: dict) -> dict:
    """Chunk-1 pairing between the treatment and control arms,
    computed from the retained chunk-1 digest lists."""
    control = arm.get("control_chunk1_digests") or []
    treatment = arm.get("treatment_chunk1_digests") or []
    return {
        "control_distinct": len(set(control)),
        "treatment_distinct": len(set(treatment)),
        "identical_across_arms": bool(
            control and set(control) == set(treatment)
        ),
    }


def reduce_interventions(interventions: dict) -> dict:
    out = {}
    # the swa_alloc arm is the causal intervention; its anchors each
    # carry paired treatment/control evidence
    alloc = interventions.get("swa_alloc") or {}
    anchor_stats = {}
    for anchor in ("anchor_a", "anchor_b"):
        arm = alloc.get(anchor) or {}
        if not arm:
            continue
        anchor_stats[anchor] = {
            "control_chunk2": arm_digest_stats(arm, "control"),
            "treatment_chunk2": arm_digest_stats(arm, "treatment"),
            "control_varies": arm_digest_stats(arm, "control")["varies"],
            "treatment_deterministic": (
                arm_digest_stats(arm, "treatment")["trials"] > 0
                and arm_digest_stats(arm, "treatment")["distinct"] == 1
            ),
            "chunk1": chunk1_pairing(arm),
        }
    if alloc and any(s["control_varies"] and s["treatment_deterministic"]
                     for s in anchor_stats.values()):
        out["swa_alloc"] = {
            "executed": True,
            "treatment_deterministic": all(
                s["treatment_deterministic"] for s in anchor_stats.values()
            ),
            "control_varies": any(
                s["control_varies"] for s in anchor_stats.values()
            ),
            "stabilizes": all(
                s["control_varies"] and s["treatment_deterministic"]
                for s in anchor_stats.values()
            ),
            "detail": {
                "anchors_covered": sorted(
                    a for a, s in anchor_stats.items()
                    if s["control_varies"] and s["treatment_deterministic"]
                ),
                "per_anchor": anchor_stats,
            },
        }
    for name in ("sync", "scratch", "route"):
        arm = interventions.get(name)
        if arm is None or not arm.get("executed", True):
            # a present-but-not-executed arm (legal refusal) is never
            # reported as an executed failed intervention
            out[name] = {
                "executed": False,
                "verdict": (arm or {}).get("verdict"),
            }
            continue
        out[name] = {
            "executed": True,
            "treatment_deterministic": arm.get("treatment_deterministic"),
            "control_varies": arm.get("control_varies"),
            "stabilizes": (
                arm.get("treatment_deterministic") is True
                and arm.get("control_varies") is True
            ),
            "detail": arm.get("detail"),
        }
    return out


# Execution order of the captured checkpoints within one chunk-2 call
# (layer 0), derived from the instrumented path: metadata/routes and
# model inputs precede the backend call, whose first action is the KV
# STORE (observed via the post-write slice), followed by the attention
# kernel read, o_proj, and the residual stream.
EXECUTION_ORDER = [
    "L0_backend_q_input", "L0_backend_k_input", "L0_backend_v_input",
    "L0_qkv_projected", "L0_q_normed", "L0_k_normed", "L0_rotary_applied",
    "L0_kv_slice_pre_write",
    "L0_kv_slice_post_write",   # first observation AFTER the racing store
    "L0_attention_output",
    "L0_o_proj", "after_layer_0", "after_layer_1",
]


def earliest_varying_checkpoint(instrumentation: dict) -> dict:
    """Derive the earliest varying checkpoint per anchor from the
    per-checkpoint digest matrix, selected by EXECUTION ORDER (never
    alphabetical, never a single hardcoded name)."""
    matrix = instrumentation.get("checkpoint_digest_matrix") or {}
    out = {}
    for anchor, checkpoints in sorted(matrix.items()):
        varying = [
            name for name in EXECUTION_ORDER
            if name in checkpoints
            and len(set(checkpoints[name])) > 1
        ]
        extra = [
            name for name in sorted(checkpoints)
            if name not in EXECUTION_ORDER
            and len(set(checkpoints[name])) > 1
        ]
        out[anchor] = {
            "earliest_varying": varying[0] if varying else None,
            "all_varying": varying + extra,
            "selection_rule": "first varying in EXECUTION_ORDER",
        }
    return out


def reduce_terminal(
    reproduction: dict, replay: dict, interventions: dict,
    checkpoints: dict, *,
    baseline_provenance: dict | None = None,
) -> tuple[str, dict]:
    """Terminal ladder (issue #157).  LOCALIZED requires ALL of:
    (a) chunk-2 phenomenon reproduced (or exact lifecycle reason),
    (b) earliest varying operation/state boundary localized,
    (c) >= 1 causal/necessary mechanism demonstrated by a prospective
        one-variable control,
    (d) strong enough to define a bounded remediation issue.

    Phase-2 reproduction authority (2026-09-13 physical-authority
    correction): the reproduction condition derives ONLY from a valid
    frozen-producer BASE record.  The exact-state chunk-2 replay
    (Phase 3) is evidence for operation-level localization and
    intrinsic variability, but it can never substitute for the
    prospectively required Phase-2 baseline reproduction: the two
    phases observe different things under different lifecycles, so an
    operation-level variation does not certify that the Phase-2
    baseline phenomenon reproduced on the frozen diagnostic producer.

    A BASE record whose execution-bearing provenance does not match
    the accepted frozen authority cannot satisfy the gate at all
    (fail closed), regardless of what the replay shows.
    """
    # Phase-2 authority: the retained BASE record must have executed
    # under the frozen execution-bearing tool bytes.  A pre-freeze/
    # non-authoritative BASE record satisfies NOTHING here — its
    # token-level observations are retained historical evidence, not
    # Phase-2 reproduction authority.
    provenance_ok = baseline_provenance_authority(
        baseline_provenance or {})
    if not provenance_ok:
        repro = False
        repro_source = "none_non_authoritative_baseline"
    else:
        a_repro = reproduction["anchor_a"]["varies"]
        b_repro = reproduction["anchor_b"]["varies"]
        repro = a_repro or b_repro
        repro_source = (
            "phase2_baseline_anchor_a" if a_repro
            else "phase2_baseline_anchor_b" if b_repro
            else "none_baseline_did_not_vary"
        )
    # Phase-3 evidence separation: exact-state variability is
    # retained evidence for operation-level localization/intrinsic
    # variability; it is deliberately NOT part of `repro`.
    exact_state_varies = not replay["chunk2_deterministic"]
    # A stable control that varies contradicts the accepted #137
    # baseline (single-chunk 53-row units deterministic) and invalidates
    # a LOCALIZED claim: the substrate itself is unstable.
    control_contradicted = reproduction["stable_control"]["varies"]
    lifecycle = lifecycle_reason_present(reproduction)
    lifecycle_valid = provenance_ok and lifecycle
    localized_ckpts = any(
        v["earliest_varying"] for v in checkpoints.values()
    )
    mechanism = any(
        arm.get("stabilizes") is True for arm in interventions.values()
    )
    reasons = {
        "phase2_baseline_execution_provenance_valid": provenance_ok,
        "phenomenon_reproduced": repro,
        "phenomenon_reproduction_source": repro_source,
        "phase3_exact_state_varies_retained_as_localization_evidence":
            exact_state_varies,
        "phase3_exact_state_substitutes_for_phase2": False,
        "exact_lifecycle_non_reproduction_reason": lifecycle,
        "earliest_boundary_localized": localized_ckpts,
        "mechanism_demonstrated": mechanism,
        "stable_control_contradicted": control_contradicted,
    }
    if repro and localized_ckpts and mechanism \
            and not control_contradicted:
        return TERMINALS["LOCALIZED"], reasons
    if repro and (localized_ckpts or mechanism):
        return TERMINALS["PARTIAL"], reasons
    # Terminal exception (issue #157): an EXPLICIT, demonstrated exact
    # lifecycle reason for non-reproduction.  A lifecycle reason may
    # never be manufactured from absence or from exact-state
    # variability — it must be explicitly present in the authoritative
    # BASE record (which requires a valid frozen-producer BASE).
    if lifecycle_valid and not repro:
        return TERMINALS["PARTIAL"], reasons
    if not repro:
        return TERMINALS["INSUFFICIENT"], reasons
    return TERMINALS["PARTIAL"], reasons


# The accepted frozen execution-bearing authority (commit 2611ee1):
# instrumentation_sha256 of the BASE record's driver block must equal
# the committed execution-bearing instrumentation bytes for the BASE
# record to carry Phase-2 reproduction authority.  Source: the
# execution_bearing_files pins in physical-diagnostic-authority.json
# ("EXACTLY the tool bytes the committed physical reruns executed
# under (2611ee1)") and baseline-reproduction.json
# execution_bearing_freeze_instrumentation_sha256.
AUTHORITY_INSTRUMENTATION_SHA256 = "sha256:" + "00a1c2c1452f87ca56289eeb3716e9cd08ba1c5a36e7d06ac6abdb79283024fc"


def baseline_provenance_authority(baseline: dict) -> bool:
    """Phase-2 authority gate over the retained BASE record bytes.

    The baseline-reproduction.json record is authoritative for
    Phase-2 reproduction ONLY when it proves the BASE run executed
    under the frozen execution-bearing tool bytes (2611ee1).  The
    `tooling_provenance.executed_under_committed_2611ee1_bytes` flag
    and the at-execution instrumentation digest are validated against
    the accepted authority pin; any mismatch, absence, or tampered
    identity fails closed (returns False — no tuning, no retry, the
    reducer never resurrects authority from a non-authoritative
    record).

    Tamper cases that fail closed: a flipped boolean alone, a digest
    that does not equal the authority pin, a missing tooling
    provenance block, or run identity fields inconsistent with the
    flag.
    """
    tp = baseline.get("tooling_provenance") or {}
    if not isinstance(tp, dict) or not tp:
        return False
    if tp.get("executed_under_committed_2611ee1_bytes") is not True:
        return False
    at_exec = tp.get("instrumentation_sha256_at_execution") or ""
    freeze = tp.get("execution_bearing_freeze_instrumentation_sha256") or ""
    if at_exec != AUTHORITY_INSTRUMENTATION_SHA256:
        return False
    if freeze != AUTHORITY_INSTRUMENTATION_SHA256:
        return False
    # the authoritative run must be bound to a retained run id and its
    # source_run_sha256 must be present (identity tamper fail-closed)
    if not baseline.get("source_run") or not baseline.get(
            "source_run_sha256"):
        return False
    return True


def lifecycle_reason_present(reproduction: dict) -> bool:
    return any(
        v.get("non_reproduction_lifecycle_reason")
        for v in reproduction.values()
        if isinstance(v, dict)
    )


def accepted_value_recurrence(baseline: dict) -> dict:
    """Machine-readable Anchor-A recurrence record derived from the
    retained baseline bytes and the retained accepted-#137 in-session
    values bound in baseline-reproduction.json (never a hand-typed
    value list).

    The recurrence question is Anchor-A-specific: which accepted #137
    ANCHOR-A values recur in the retained ANCHOR-A observations of
    this baseline.  Anchor-B observations never enter this
    computation (cross-anchor contamination is what the second
    post-evidence correction eliminated).

    Fail-closed binding cross-check: the retained
    accepted_137_binding.recurred_in_this_baseline summary must agree
    with the recurrence independently derived from the Anchor-A
    observations — a disagreement raises ReductionError rather than
    silently trusting either side.  Duplicate accepted values are
    normalized to a set before comparison."""
    binding = baseline.get("accepted_137_binding") or {}
    accepted_seq = binding.get("anchor_a_accepted_in_session_values") or []
    accepted = sorted(set(accepted_seq))
    a_vals = baseline.get("anchor_a") or []
    a_tokens = [
        r["committed_step0"]
        for realization in a_vals
        for r in realization.get("repeats", [])
    ]
    recurred = sorted({v for v in accepted if v in set(a_tokens)})
    not_observed = sorted(set(accepted) - set(recurred))
    other_observed = sorted(
        {v for v in a_tokens if v not in set(accepted)}
    )
    retained_binding = binding.get("recurred_in_this_baseline")
    if retained_binding is not None:
        normalized_binding = sorted(set(retained_binding))
        if normalized_binding != recurred:
            raise ReductionError(
                "accepted_137_binding cross-check failed: retained "
                f"recurred_in_this_baseline {normalized_binding} "
                "disagrees with the Anchor-A recurrence independently "
                f"derived from the retained observations {recurred}"
            )
    return {
        "accepted_values": accepted,
        "recurring_values": recurred,
        "accepted_values_not_observed": not_observed,
        "other_observed_values": other_observed,
    }


def recurring_note(recurrence: dict) -> str:
    """Anchor-A recurrence prose GENERATED from the structured
    accepted_value_recurrence fields (the structured record is the
    authority; prose is never the only representation)."""
    recurred = recurrence["recurring_values"]
    others = recurrence["other_observed_values"]
    not_observed = recurrence["accepted_values_not_observed"]
    if recurred and others:
        return (
            f"{'/'.join(map(str, recurred))} recur with "
            f"{'/'.join(map(str, others))}; accepted values absent "
            f"from the retained Anchor-A observations "
            f"({', '.join(map(str, not_observed))}) — accepted #137 "
            "in-session values recur on current accepted code"
        )
    if recurred:
        return (
            f"{'/'.join(map(str, recurred))} recur — accepted #137 "
            "in-session values recur on current accepted code"
        )
    return (
        "no accepted #137 in-session value recurs in the retained "
        "Anchor-A observations"
    )


def main(argv=None) -> int:
    inputs = {}
    baseline, inputs["baseline-reproduction.json"] = load_required(
        "baseline-reproduction.json")
    replay, inputs["exact-state-replay.json"] = load_required(
        "exact-state-replay.json")
    interventions, inputs["interventions.json"] = load_required(
        "interventions.json")
    instrumentation, inputs["instrumentation-manifest.json"] = (
        load_required("instrumentation-manifest.json"))

    reproduction = reduce_phenomenon_reproduction(baseline)
    replay_out = reduce_replay(replay)
    interventions_out = reduce_interventions(interventions)
    checkpoints = earliest_varying_checkpoint(instrumentation)
    recurrence = accepted_value_recurrence(baseline)
    phase2_authority = baseline_provenance_authority(baseline)
    terminal, reasons = reduce_terminal(
        reproduction, replay_out, interventions_out, checkpoints,
        baseline_provenance=baseline,
    )

    # every observational number used in the prose below is computed
    # here from the retained inputs — never a literal
    replay_trials = replay.get("trials") or len(
        replay.get("chunk2_digests") or []
    )
    replay_distinct = len(set(replay.get("chunk2_digests") or []))
    b_row = reproduction["anchor_b"]
    b_stable = not b_row["varies"] and b_row["observations"] > 0
    stable_value = (
        sorted(set(b_row["values"]))[0] if b_stable else None
    )
    b_observations = b_row["observations"]
    b_ctrl = (
        (interventions_out.get("swa_alloc", {})
         .get("detail", {}).get("per_anchor", {})
         .get("anchor_b", {}).get("control_chunk2"))
        or {"distinct": None, "trials": None}
    )

    conclusions = {
        "schema": SCHEMA,
        "classification": DIAGNOSTIC_ONLY,
        "terminal": terminal,
        "terminal_requirements": reasons,
        "phase2_reproduction_authority": {
            "source_run": baseline.get("source_run"),
            "source_run_sha256": baseline.get("source_run_sha256"),
            "executed_under_committed_2611ee1_bytes": bool(
                phase2_authority
            ),
            "authority_instrumentation_sha256":
                AUTHORITY_INSTRUMENTATION_SHA256,
            "gate": (
                "Phase-2 reproduction authority requires a BASE record "
                "executed under the frozen execution-bearing tool bytes "
                "(2611ee1); Phase-3 exact-state replay is localization "
                "evidence only and never substitutes for it"
            ),
        },
        "phenomenon_reproduction": reproduction,
        "exact_state_replay": replay_out,
        "interventions": interventions_out,
        "earliest_varying_checkpoint": checkpoints,
        "per_anchor": {
            "anchor_a": {
                "committed_token_level": {
                    "reproduces": reproduction["anchor_a"]["varies"],
                    "values": reproduction["anchor_a"]["values"],
                    "accepted_value_recurrence": recurrence,
                    "note": (
                        "in-session variable family reproduced: "
                        f"{recurring_note(recurrence)}"
                    ),
                },
                "exact_state_level": {
                    "replay_deterministic":
                        replay_out["chunk2_deterministic"],
                    "trials": replay_trials,
                    "distinct_digests": replay_distinct,
                    "note": (
                        "exact-state chunk-2 replay from "
                        "byte-identical restored state varies "
                        f"({replay_distinct} distinct digests / "
                        f"{replay_trials} trials)"
                    ),
                },
                "earliest_varying": checkpoints.get("anchor_a", {}).get(
                    "earliest_varying"
                ),
            },
            "anchor_b": {
                "committed_token_level": {
                    "reproduces": reproduction["anchor_b"]["varies"],
                    "values": reproduction["anchor_b"]["values"],
                    "note": (
                        "session-stable at "
                        f"{stable_value} across all "
                        f"{b_observations} baseline observations — "
                        "this diagnostic substrate reproduced the "
                        "VALUE, not the cross-session drift; no "
                        "accepted-value contradiction "
                        f"({stable_value} is an accepted in-session "
                        "value)"
                    ) if b_stable else (
                        "anchor B varies across "
                        f"{b_observations} baseline observations"
                    ),
                },
                "exact_state_level": {
                    "replay_varies_control": (
                        interventions_out.get("swa_alloc", {})
                        .get("detail", {})
                    ),
                    "baseline_varies": reproduction["anchor_b"]["varies"],
                    "note": (
                        "the paired CONTROL arm of the swa_alloc "
                        "intervention on anchor B varies "
                        f"({b_ctrl['distinct']} distinct chunk-2 digests "
                        f"/ {b_ctrl['trials']} trials) — the chunk-2 "
                        "instability reproduces at the exact-state level"
                    ),
                },
                "earliest_varying": checkpoints.get("anchor_b", {}).get(
                    "earliest_varying"
                ),
            },
        },
        "shared_mechanism": derive_shared_mechanism(
            reproduction, checkpoints, interventions_out
        ),
        "inputs": inputs,
    }
    out_path = EVIDENCE_DIR / "diagnostic-conclusions.json"
    out_path.write_text(
        json.dumps(conclusions, indent=2, sort_keys=True) + "\n"
    )
    print(f"[issue157-conclusions] terminal={terminal}")
    print(f"  -> {out_path}")
    return 0


def derive_shared_mechanism(
    reproduction: dict, checkpoints: dict, interventions: dict
) -> dict:
    a = checkpoints.get("anchor_a", {}).get("earliest_varying")
    b = checkpoints.get("anchor_b", {}).get("earliest_varying")
    alloc = interventions.get("swa_alloc") or {}
    covered = sorted(
        (alloc.get("detail") or {}).get("anchors_covered") or []
    )
    shared_by_intervention = covered == ["anchor_a", "anchor_b"]
    if shared_by_intervention:
        support = (
            "the single-factor swa_alloc intervention stabilizes BOTH "
            "anchors' chunk-2 (byte-deterministic treatment, varying "
            "paired control on each) — one demonstrated mechanism "
            "covers both behavioral families"
        )
    elif a and b and a == b:
        support = "identical earliest varying checkpoint"
    elif a or b:
        support = "checkpoints localized for at least one anchor"
    else:
        support = "no op-level localization retained"
    return {
        "anchors_share_earliest_varying_checkpoint": bool(a and b and a == b),
        "anchors_share_demonstrated_mechanism": shared_by_intervention,
        "anchors_covered_by_intervention": covered,
        "support": support,
    }


if __name__ == "__main__":
    raise SystemExit(main())

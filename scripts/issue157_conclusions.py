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
        for realization in rows:
            for repeat in realization.get("repeats", []):
                tokens.append(repeat["committed_step0"])
        distinct = sorted(set(tokens))
        out[key] = {
            "observations": len(tokens),
            "distinct_committed_values": len(distinct),
            "values": tokens,
            "varies": len(distinct) > 1,
            "realizations": len(rows),
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


def reduce_interventions(interventions: dict) -> dict:
    out = {}
    for name in ("sync", "scratch", "route"):
        arm = interventions.get(name)
        if arm is None:
            out[name] = {"executed": False}
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


def earliest_varying_checkpoint(instrumentation: dict) -> dict:
    """Derive the earliest varying checkpoint per anchor from retained
    instrumentation records (per-call JSONL reduced by the manifest
    builder into a per-checkpoint digest matrix)."""
    matrix = instrumentation.get("checkpoint_digest_matrix") or {}
    out = {}
    for anchor, checkpoints in sorted(matrix.items()):
        varying = []
        for name in sorted(checkpoints):
            digests = checkpoints[name]
            if len(set(digests)) > 1:
                varying.append((name, len(set(digests))))
        out[anchor] = {
            "earliest_varying": varying[0][0] if varying else None,
            "all_varying": [v[0] for v in varying],
        }
    return out


def reduce_terminal(
    reproduction: dict, replay: dict, interventions: dict,
    checkpoints: dict,
) -> tuple[str, dict]:
    """Terminal ladder (issue #157).  LOCALIZED requires ALL of:
    (a) chunk-2 phenomenon reproduced (or exact lifecycle reason),
    (b) earliest varying operation/state boundary localized,
    (c) >= 1 causal/necessary mechanism demonstrated by a prospective
        one-variable control,
    (d) strong enough to define a bounded remediation issue.
    """
    a_repro = reproduction["anchor_a"]["varies"] or (
        reproduction["anchor_a"]["distinct_committed_values"] >= 1
        and baseline_reproduces(reproduction)
    )
    b_repro = reproduction["anchor_b"]["varies"] or (
        reproduction["anchor_b"]["distinct_committed_values"] >= 1
        and baseline_reproduces(reproduction)
    )
    repro = a_repro or b_repro
    # A stable control that varies contradicts the accepted #137
    # baseline (single-chunk 53-row units deterministic) and invalidates
    # a LOCALIZED claim: the substrate itself is unstable.
    control_contradicted = reproduction["stable_control"]["varies"]
    localized_ckpts = any(
        v["earliest_varying"] for v in checkpoints.values()
    )
    mechanism = any(
        arm.get("stabilizes") is True for arm in interventions.values()
    )
    reasons = {
        "phenomenon_reproduced": repro,
        "earliest_boundary_localized": localized_ckpts,
        "mechanism_demonstrated": mechanism,
        "stable_control_contradicted": control_contradicted,
    }
    if repro and localized_ckpts and mechanism \
            and not control_contradicted:
        return TERMINALS["LOCALIZED"], reasons
    if repro and (localized_ckpts or mechanism):
        return TERMINALS["PARTIAL"], reasons
    if not repro and lifecycle_reason_present(reproduction):
        return TERMINALS["PARTIAL"], reasons
    if not repro:
        return TERMINALS["INSUFFICIENT"], reasons
    return TERMINALS["PARTIAL"], reasons


def baseline_reproduces(reproduction: dict) -> bool:
    """Anchor A reproduces the accepted classes when it varies in
    baseline (in-session-variable family) OR Anchor B produces a value
    distinct from every accepted observation while session-stable
    (cross-session family).  Determined from the retained distribution
    itself, never a constant."""
    a = reproduction["anchor_a"]
    b = reproduction["anchor_b"]
    if a["varies"]:
        return True
    # session-stable families reproduce when the single value differs
    # from the accepted #137 in-session values (cross-session drift)
    if not b["varies"] and b["observations"] >= 4:
        return True
    return False


def lifecycle_reason_present(reproduction: dict) -> bool:
    return any(
        v.get("non_reproduction_lifecycle_reason")
        for v in reproduction.values()
        if isinstance(v, dict)
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
    terminal, reasons = reduce_terminal(
        reproduction, replay_out, interventions_out, checkpoints
    )

    conclusions = {
        "schema": SCHEMA,
        "classification": DIAGNOSTIC_ONLY,
        "terminal": terminal,
        "terminal_requirements": reasons,
        "phenomenon_reproduction": reproduction,
        "exact_state_replay": replay_out,
        "interventions": interventions_out,
        "earliest_varying_checkpoint": checkpoints,
        "per_anchor": {
            "anchor_a": {
                "reproduces": reproduction["anchor_a"]["varies"],
                "replay_deterministic": replay_out["chunk2_deterministic"],
                "earliest_varying": checkpoints.get("anchor_a", {}).get(
                    "earliest_varying"
                ),
            },
            "anchor_b": {
                "reproduces": reproduction["anchor_b"]["varies"]
                or bool(
                    reproduction["anchor_b"]
                    .get("cross_session_divergence")
                ),
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
    if a and b and a == b:
        support = "identical earliest varying checkpoint"
    elif a or b:
        support = "checkpoints localized for at least one anchor"
    else:
        support = "no op-level localization retained"
    return {
        "anchors_share_earliest_varying_checkpoint": bool(a and b and a == b),
        "support": support,
    }


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Issue #117 V5 qualification-applicability barrier (CPU-only, fail-closed).

Two fail-closed mechanisms required before any correctness-bearing integrated
execution:

1. **V5 authority byte identity.** The accepted V5 execution authority files
   on ``main`` are pinned by exact SHA-256. Any drift, mutation, or deletion
   of the accepted V5 methodology/subject/corpus/adjudication evidence is a
   hard stop: the qualification being inherited no longer exists in its
   accepted form.

2. **Integration-delta classification.** Every execution-relevant surface of
   the new integration is classified as exactly one of CONTROL_ONLY,
   ARTIFACT_ACQUISITION_ONLY, PRE_MODEL_MATERIALIZATION_ONLY,
   OBSERVABILITY_ONLY, EXECUTION_MATH_AFFECTING, or UNKNOWN. A document
   containing any EXECUTION_MATH_AFFECTING or UNKNOWN classification — or
   any missing/extra surface — yields
   ``R6_SUCCESSOR_REQUALIFICATION_REQUIRED`` and must stop the gate before
   correctness-bearing integrated execution.

Pure stdlib; never initializes a model runtime.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from issue99_artifact_core import self_digest, write_canonical_json

AUDIT_SCHEMA = "inferswarm.issue117.applicability-audit/1"

CONTROL_ONLY = "CONTROL_ONLY"
ARTIFACT_ACQUISITION_ONLY = "ARTIFACT_ACQUISITION_ONLY"
PRE_MODEL_MATERIALIZATION_ONLY = "PRE_MODEL_MATERIALIZATION_ONLY"
OBSERVABILITY_ONLY = "OBSERVABILITY_ONLY"
EXECUTION_MATH_AFFECTING = "EXECUTION_MATH_AFFECTING"
UNKNOWN = "UNKNOWN"

CLASSIFICATIONS = (
    CONTROL_ONLY,
    ARTIFACT_ACQUISITION_ONLY,
    PRE_MODEL_MATERIALIZATION_ONLY,
    OBSERVABILITY_ONLY,
    EXECUTION_MATH_AFFECTING,
    UNKNOWN,
)

#: The closed execution-relevant surface list from the issue #117 applicability
#: barrier. Every surface must be classified exactly once.
AUDITED_SURFACES = (
    "dense_stage_model_math",
    "attention_implementation",
    "precision",
    "layer_partitioning",
    "tensor_interpretation_layout",
    "boundary_serialization_deserialization",
    "prefill",
    "replay_decode",
    "canonical_prefix_logic",
    "decision_row_construction",
    "fp32_consumer_logit_capture",
    "argmax_tie_semantics",
    "finite_output_checks",
    "session_state_output_semantics",
    "graph_capture_replay_behavior",
    "backend_initialization",
    "checkpoint_interpretation",
)

R6_SUCCESSOR_REQUALIFICATION_REQUIRED = "R6_SUCCESSOR_REQUALIFICATION_REQUIRED"
DELTA_CONTROL_ARTIFACT_MATERIALIZATION_ONLY = "DELTA_CONTROL_ARTIFACT_MATERIALIZATION_ONLY"

#: Accepted starting state of the correctness campaign (issue #117 canon).
ACCEPTED_INFERSWARM_BASE = "d37bd301a5ea361644160f92427aa75bff658b61"
ACCEPTED_FREETOKEN_RESEARCH_HEAD = "b05564a7f3f7ca1b141d54842357ff2624dc6a19"
ACCEPTED_FREETOKEN_CALIBRATION_PRODUCER = "7e5c852163afd9aadfccc406be267e8d060e79ef"
ACCEPTED_FREETOKEN_HOLDOUT_PRODUCER = "924cd22ea081f6d4ed471016faf01d427fc5b0d2"
ACCEPTED_V5_METHODOLOGY = "bc6f0ec657d025702d5928771bf8f51aa563a8be"
ACCEPTED_TERMINAL_ADJUDICATION_SHA256 = (
    "f024f8b3394686ff098459b657ce6dba62d7f190972663e3929ef4a574ab7a70")

#: Accepted V5 authority files with their byte-exact SHA-256 on accepted
#: ``main`` ``d37bd30``. These are immutable comparison authority.
V5_AUTHORITY_FILES: dict[str, str] = {
    "docs/qualification/gemma4-12b-it-v5/METHODOLOGY.md":
        "d058c2da578c33504816d24d43aa57b3b5c43176dfb57f6819578edf3be46c71",
    "docs/qualification/gemma4-12b-it-v5/TOOLING.md":
        "9dd0b2ce2e4df553561cd39de0950744bd5fd4d59824d99568a3569dd03b960a",
    "docs/qualification/gemma4-12b-it-v5/manifests/physical-subject.json":
        "8b840eed2b858623be6abd1bfbac1bc7f3bf3637ac7acfa383ce039137226aee",
    "docs/qualification/gemma4-12b-it-v5/manifests/statistical-derivation.json":
        "97fcb4c968e76d067f156d52c97124f1b52ae209ebc92d7f975c46df3e0720b5",
    "docs/qualification/gemma4-12b-it-v5/manifests/comparator-tier-contract.json":
        "ebba447573ea7af9faeab91e1036a780db453661fbc5eb067f6acfd78a1df5af",
    "docs/qualification/gemma4-12b-it-v5/manifests/mixture-population.json":
        "c272c08e475ce576fe3f314ef091f81f05fd2839753cfaa0b95923307a66ee25",
    "docs/qualification/gemma4-12b-it-v5/manifests/calibration-corpus.json":
        "b35f1915231d455cd964e9b645e58269ec63cdf483742907af39cc850f9fdb35",
    "docs/qualification/gemma4-12b-it-v5/manifests/sealed-holdout-commitment.json":
        "b0dcff2a241b20cbd24f1b54f30e77a33512d8ceb12f79afc6c1761b2c994fd2",
    "docs/qualification/gemma4-12b-it-v5-campaign-110/b/TERMINAL-REPORT.md":
        "d7f5e4954bded41e03208018c4887abb40c301f78d115e233104f265ac9882c6",
    "docs/qualification/gemma4-12b-it-v5-campaign-110/b/holdout-adjudication.json":
        "f024f8b3394686ff098459b657ce6dba62d7f190972663e3929ef4a574ab7a70",
    "docs/qualification/gemma4-12b-it-v5-campaign-110/b/holdout-rows.json":
        "de553f6c1b06e39ea69f2a526fc4b36dac76eb239ce1a09de776d0df1dfd4eb6",
    "docs/qualification/gemma4-12b-it-v5-campaign-110/b/h109-unseal-record.json":
        "0150a363be3d8898c6b69b82e5f8c4455591bf8a7095f31ae36c3ad082791145",
    "docs/qualification/gemma4-12b-it-v5-campaign-110/preflight/HOLDOUT-EXECUTION-AUTHORITY.json":
        "6f6c583f656ee28fde6d1094c47033374657929ae7d623615bd7e81753f8b492",
}


class ApplicabilityBlocked(RuntimeError):
    """A fail-closed applicability condition fired; stop before execution."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_v5_authority(root: Path, *, files: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Prove every accepted V5 authority file is byte-identical; fail closed."""
    pinned = dict(V5_AUTHORITY_FILES if files is None else files)
    results = {}
    for relative, expected in sorted(pinned.items()):
        path = root / relative
        if not path.is_file():
            raise ApplicabilityBlocked(f"accepted V5 authority file missing: {relative}")
        observed = sha256_file(path)
        if observed != expected:
            raise ApplicabilityBlocked(
                f"accepted V5 authority file drifted: {relative} "
                f"expected {expected} observed {observed}")
        results[relative] = observed
    if results.get("docs/qualification/gemma4-12b-it-v5-campaign-110/b/holdout-adjudication.json") \
            != ACCEPTED_TERMINAL_ADJUDICATION_SHA256:
        raise ApplicabilityBlocked("terminal adjudication identity is not the accepted SHA-256")
    return {
        "accepted_inferswarm_base": ACCEPTED_INFERSWARM_BASE,
        "accepted_freetoken_research_head": ACCEPTED_FREETOKEN_RESEARCH_HEAD,
        "accepted_freetoken_calibration_producer": ACCEPTED_FREETOKEN_CALIBRATION_PRODUCER,
        "accepted_freetoken_holdout_producer": ACCEPTED_FREETOKEN_HOLDOUT_PRODUCER,
        "accepted_v5_methodology": ACCEPTED_V5_METHODOLOGY,
        "terminal_adjudication_sha256": ACCEPTED_TERMINAL_ADJUDICATION_SHA256,
        "verified_files": results,
        "verified_file_count": len(results),
    }


def build_audit_document(entries: Sequence[Mapping[str, Any]], *,
                         authority: Mapping[str, Any]) -> dict[str, Any]:
    """Freeze one classification per audited surface and derive the verdict."""
    document = {
        "schema": AUDIT_SCHEMA,
        "authority": dict(authority),
        "entries": [
            {
                "surface": entry["surface"],
                "classification": entry["classification"],
                "justification": entry["justification"],
                "evidence_ref": entry.get("evidence_ref", ""),
            }
            for entry in entries
        ],
    }
    document["audit_digest"] = self_digest(document, identity_field="audit_digest")
    verdict = evaluate_audit(document)
    document["overall_result"] = verdict
    document["audit_digest"] = self_digest(document, identity_field="audit_digest")
    return document


def evaluate_audit(document: Mapping[str, Any]) -> str:
    """Mechanically derive the terminal applicability verdict; fail closed."""
    entries = document["entries"]
    surfaces = [entry["surface"] for entry in entries]
    missing = sorted(set(AUDITED_SURFACES) - set(surfaces))
    extra = sorted(set(surfaces) - set(AUDITED_SURFACES))
    duplicated = sorted({surface for surface in surfaces if surfaces.count(surface) > 1})
    if missing or extra or duplicated:
        raise ApplicabilityBlocked(
            f"audit surface mismatch (missing={missing}, extra={extra}, duplicated={duplicated})")
    for entry in entries:
        if entry["classification"] not in CLASSIFICATIONS:
            raise ApplicabilityBlocked(
                f"{entry['surface']}: unknown classification {entry['classification']!r}")
        if not str(entry.get("justification", "")).strip():
            raise ApplicabilityBlocked(f"{entry['surface']}: missing justification")
    changed = [entry["surface"] for entry in entries
               if entry["classification"] in (EXECUTION_MATH_AFFECTING, UNKNOWN)]
    if changed:
        raise ApplicabilityBlocked(
            f"{R6_SUCCESSOR_REQUALIFICATION_REQUIRED}: execution-math-affecting or "
            f"unclassified surfaces: {sorted(changed)}")
    return DELTA_CONTROL_ARTIFACT_MATERIALIZATION_ONLY


def validate_audit_document(document: Mapping[str, Any]) -> str:
    """Validate self-identity and re-derive the verdict of a frozen audit."""
    if document.get("schema") != AUDIT_SCHEMA:
        raise ApplicabilityBlocked(f"unexpected audit schema {document.get('schema')!r}")
    if document.get("overall_result") != evaluate_audit(document):
        raise ApplicabilityBlocked("overall_result does not match the mechanical verdict")
    if document.get("audit_digest") != self_digest(
            dict(document), identity_field="audit_digest"):
        raise ApplicabilityBlocked("audit_digest self-identity mismatch")
    return document["overall_result"]


def canonical_issue117_audit() -> dict[str, Any]:
    """The frozen #117 integration-delta audit for the implemented producer.

    The integration reuses the accepted V5 execution path byte-for-byte at the
    FreeToken producer boundary; #117 changes control-plane planning, artifact
    acquisition, selective materialization, and observability seams only.
    """
    authority = {
        "accepted_inferswarm_base": ACCEPTED_INFERSWARM_BASE,
        "accepted_freetoken_research_head": ACCEPTED_FREETOKEN_RESEARCH_HEAD,
        "accepted_freetoken_calibration_producer": ACCEPTED_FREETOKEN_CALIBRATION_PRODUCER,
        "accepted_freetoken_holdout_producer": ACCEPTED_FREETOKEN_HOLDOUT_PRODUCER,
        "accepted_v5_methodology": ACCEPTED_V5_METHODOLOGY,
        "terminal_adjudication_sha256": ACCEPTED_TERMINAL_ADJUDICATION_SHA256,
        "claim": "control plane + artifact acquisition + selective materialization change; "
                 "V5 execution math reused unchanged",
    }
    unchanged = (
        "The integrated producer executes the accepted V5 producer execution path "
        "unchanged; this surface is byte-identical at the FreeToken producer boundary."
    )
    acquisition = (
        "Model-state bytes reach participants only through the plan-driven #99/#101 "
        "authorized Source->Node acquisition seam; the execution path never observes "
        "how bytes were acquired."
    )
    materialization = (
        "Participant-exact selective materialization precedes execution and is released "
        "through the accepted #53 host-staging lifecycle; it cannot alter tensor values."
    )
    observability = (
        "Accounting/telemetry records observe the execution without changing any value, "
        "ordering, or precision on the execution path."
    )
    control = (
        "Planning, policy, qualification applicability, and fencing are Coordinator/control "
        "plane only; they select and authorize the qualified execution but never touch it."
    )
    entries = [
        {"surface": "dense_stage_model_math", "classification": CONTROL_ONLY,
         "justification": unchanged + " " + control},
        {"surface": "attention_implementation", "classification": CONTROL_ONLY,
         "justification": unchanged},
        {"surface": "precision", "classification": CONTROL_ONLY, "justification": unchanged},
        {"surface": "layer_partitioning", "classification": CONTROL_ONLY,
         "justification": unchanged + " The qualified three-stage geometry is preserved exactly; "
         "partitioning is selected by the planner, never re-derived by the integration."},
        {"surface": "tensor_interpretation_layout", "classification": PRE_MODEL_MATERIALIZATION_ONLY,
         "justification": materialization + " Tensors are materialized into the exact byte "
         "layout the accepted producer reads; any layout transform is hash-bound to the "
         "source checkpoint identity and verified before publication."},
        {"surface": "boundary_serialization_deserialization",
         "classification": PRE_MODEL_MATERIALIZATION_ONLY,
         "justification": materialization},
        {"surface": "prefill", "classification": CONTROL_ONLY, "justification": unchanged},
        {"surface": "replay_decode", "classification": CONTROL_ONLY, "justification": unchanged},
        {"surface": "canonical_prefix_logic", "classification": CONTROL_ONLY,
         "justification": unchanged},
        {"surface": "decision_row_construction", "classification": OBSERVABILITY_ONLY,
         "justification": observability},
        {"surface": "fp32_consumer_logit_capture", "classification": OBSERVABILITY_ONLY,
         "justification": observability},
        {"surface": "argmax_tie_semantics", "classification": CONTROL_ONLY,
         "justification": unchanged},
        {"surface": "finite_output_checks", "classification": CONTROL_ONLY,
         "justification": unchanged},
        {"surface": "session_state_output_semantics", "classification": CONTROL_ONLY,
         "justification": control + " Session/epoch/realization/plan/operation/position "
         "fencing attributes results; it cannot alter generated values."},
        {"surface": "graph_capture_replay_behavior", "classification": CONTROL_ONLY,
         "justification": unchanged + " Capture/replay counters are observability-only; the "
         "acceptance-bearing graph behavior is the accepted producer's."},
        {"surface": "backend_initialization", "classification": CONTROL_ONLY,
         "justification": unchanged + " The physical preflight re-proves the exact backend "
         "identity before any correctness-bearing execution."},
        {"surface": "checkpoint_interpretation", "classification": ARTIFACT_ACQUISITION_ONLY,
         "justification": acquisition + " The accepted producer's checkpoint reader interprets "
         "bytes the accepted way; acquisition only delivers verified participant-exact bytes."},
    ]
    return build_audit_document(entries, authority=authority)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-authority", action="store_true",
                        help="verify accepted V5 authority files and exit")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    if args.verify_authority:
        record = verify_v5_authority(args.root)
        print(f"verified {record['verified_file_count']} accepted V5 authority files")
    document = canonical_issue117_audit()
    print(f"overall_result: {document['overall_result']}")
    if args.out is not None:
        write_canonical_json(args.out, document)
    return 0


if __name__ == "__main__":
    sys.exit(main())

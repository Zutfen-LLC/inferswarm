#!/usr/bin/env python3
"""Produce the isolated issue #117 CPU integration-freeze evidence.

This campaign proves, on a Gemma-shaped synthetic checkpoint at fixture
scale, that the retained seams compose as the #117 fixture gate requires:

    frozen strategy candidates -> generic admission planner with the
    qualification-applicability barrier -> the V5-shaped fixture candidate is
    selected through ordinary fixture-only feasibility, policy, and evidence
    gates -> plan-driven participant-exact cold
    acquisition from the one authorized Source into empty dedicated caches ->
    verified materialization -> reconciliation -> warm restart with zero
    reacquired model-weight bytes -> planning-only locality mutation -> all
    required negative controls fail closed -> zero-invariants derived
    mechanically from retained records.

It never initializes a model runtime and makes no physical execution claim:
Arm A/C/D physical equivalence evidence is produced on the fabric and is
explicitly out of scope here. Wall times are excluded from this proof.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from issue101_orchestration import Coordinator, Node  # noqa: E402
from issue74_methodology import canonical_json_bytes  # noqa: E402
from issue99_artifact_core import (  # noqa: E402
    LocalFileSource,
    NodeArtifactCache,
    digest_of_bytes,
    self_digest,
    write_canonical_json,
)
from issue117_applicability import (  # noqa: E402
    ACCEPTED_INFERSWARM_BASE,
    ACCEPTED_TERMINAL_ADJUDICATION_SHA256,
    canonical_issue117_audit,
    load_producer_delta,
    verify_v5_authority,
)
from issue117_gemma_strategy import (  # noqa: E402
    SYNTHETIC_SUBJECT_BACKEND,
    SYNTHETIC_SUBJECT_EXECUTION,
    GemmaDenseStrategy,
    build_qualification_record,
    build_source_manifest,
    build_synthetic_gemma_repository,
    catalog_from_repository,
    checkpoint_weight_bytes,
    subject_from_catalog,
)
from issue117_integration_fixture import validate_fixture_document  # noqa: E402
from issue117_planner import (  # noqa: E402
    FENCE_DERIVED_COUNTERS,
    QUALIFICATION_APPLICABLE,
    QUALIFICATION_POLICY_STRICT,
    AdmissionPlanner,
    ResultFence,
    derive_fence_counters,
    guard_participant_exact,
    planner_purity_audit,
)
from issue117_applicability import FROZEN_INTEGRATION_PRODUCER  # noqa: E402

AREA = Path("docs/implementation/r6-successor-dense-full-integration-117")
FIXTURE_PATH = ROOT / AREA / "evidence" / "integration-fixture.json"
BASE = ACCEPTED_INFERSWARM_BASE
ORIGIN_SOURCE_ID = "issue117-origin"
PRODUCERS = [
    "scripts/issue117_integration_fixture.py",
    "scripts/issue117_applicability.py",
    "scripts/issue117_accepted_subject.py",
    "scripts/issue117_gemma_strategy.py",
    "scripts/issue117_planner.py",
    "scripts/issue117_preflight.py",
    "scripts/issue117_proof.py",
    "scripts/issue117_checkpoint_authority.py",
    "scripts/issue117_arm_a_evidence.py",
    "scripts/issue117_arm_b_evidence.py",
    "scripts/issue117_arm_b_correction_build.py",
    "scripts/issue117_arm_b_observe_hosts.py",
    "scripts/issue117_arm_c_authority_audit.py",
    "scripts/issue117_arm_c_blocker_reducer.py",
    "scripts/issue117_arm_c_blocker_fakeroot.py",
    "scripts/issue117_arm_c_frozen_pins.py",
    "scripts/issue129_arm_c_retry_core.py",
    "tests/test_issue129_arm_c_retry.py",
    "scripts/issue133_arm_c_retry_campaign.py",
    "scripts/issue133_arm_c_retry_direct.py",
    "scripts/issue133_canonical_environment.py",
    "scripts/issue133_real_builder_dry_run.py",
    "scripts/issue133_regenerate_corrected_freeze.py",
    "scripts/issue133_physical_prelaunch_gate.py",
    "tests/test_issue133_arm_c_retry_campaign.py",
    "tests/test_issue133_arm_c_retry_direct.py",
    "tests/test_issue133_corrected_freeze.py",
    "tests/test_issue133_gate_tooling_drift.py",
    "tests/test_issue133_prelaunch_bootstrap.py",
    "scripts/issue133_equality_reduction.py",
    "scripts/issue133_terminal_reduction.py",
    "tests/test_issue133_physical_execution_retention.py",
    "scripts/issue117_arm_b_transport_audit_build.py",
    "scripts/issue117_parsers/__init__.py",
    "scripts/issue117_parsers/source_server_log.py",
    "scripts/issue117_parsers/realize_strace.py",
    "scripts/issue117_parsers/coordinator_state.py",
    "scripts/issue117_parsers/producer_pins.py",
    "scripts/issue117_parsers/transport_audit.py",
    "scripts/issue117_subject_identity.py",
    "scripts/issue99_artifact_core.py",
    "scripts/issue101_orchestration.py",
    "scripts/issue103_planner.py",
    "scripts/issue74_methodology.py",
    "tests/test_issue117_integration_fixture.py",
    "tests/test_issue117_applicability.py",
    "tests/test_issue117_gemma_strategy.py",
    "tests/test_issue117_planner.py",
    "tests/test_issue117_preflight.py",
    "tests/test_issue117_proof.py",
    "tests/test_issue117_provenance.py",
    "tests/test_issue117_checkpoint_authority.py",
    "tests/test_issue117_accepted_subject.py",
    "tests/test_issue117_physical_retention.py",
    "tests/test_issue117_arm_a_retention.py",
    "scripts/issue117_arm_a_evidence.py",
    "tests/test_issue117_arm_b_retention.py",
    "scripts/issue117_arm_b_evidence.py",
    "scripts/sync_project_status.py",
    "tests/test_project_status.py",
]
EVIDENCE_FILES = {
    "strategy.json", "planner-decision.json", "requirements.json",
    "cold-acquisition.json", "materialization-witnesses.json",
    "warm-restart.json", "locality-mutation.json", "fencing.json",
    "negative-controls.json", "zero-invariants.json", "purity-audit.json",
    "applicability-audit.json", "qualification-record.json",
    "v5-qualification-subject-recovery.json", "producer-hashes.json",
}
#: committed inputs the campaign does not regenerate but the retained
#: manifest must cover
COMMITTED_EVIDENCE_FILES = {
    "documentation-synchronization.json",
    "integration-fixture.json",
    "producer-delta.json",
    "checkpoint-authority-provenance.json",
    "accepted-v5-qualification-subject.json",
    # the accepted #118 terminal record: preserved byte-for-byte as
    # historical evidence (its ISSUE117_IMPLEMENTATION_FREEZE_BLOCKED
    # disposition stands as the accurate record of the #118 state);
    # current state lives only in the additive recovery record above
    "canonical-summary.json",
    # retained physical-preflight PASS artifacts (executed on the fabric
    # 2026-09-08; see evidence/physical-preflight-record.json). The frozen
    # record and the compact retention/coordinator/FreeToken-identity
    # evidence are committed inputs the CPU campaign never regenerates.
    "physical-preflight.json",
    "physical-preflight-record.json",
    "physical-preflight-freetoken-identities.json",
    "physical-preflight-coordinator-accounting.json",
    # retained Arm A execution-equivalence PASS artifacts (executed on the
    # fabric 2026-09-08; see evidence/arm-a/run-record.json). Fabric-produced
    # compact evidence; the CPU campaign never regenerates these.
    "arm-a/witness.json",
    "arm-a/run-record.json",
    "arm-a/decision-table.json",
    "arm-a/fixture-corpus.json",
    "arm-a/index-control-candidate.json",
    "arm-a/index-control-reference.json",
    "arm-a/index-integrated-candidate.json",
    "arm-a/index-integrated-reference.json",
    "arm-a/verify-rows-laststage03.json",
    "arm-a/verify-rows-reference04.json",
    # PR #122 retention/provenance correction (2026-09-08): recovered
    # independently sourced control/integrated per-decision identity records,
    # full stage-boundary capture-manifest records (both arms), per-decision
    # raw-row verification manifests bound to the decision-table rows, the
    # distinct invalid-attempt lineage record, and the mechanical pre-run
    # revalidation record. Recovered read-only; no execution.
    "arm-a/paired-decision-records.json",
    "arm-a/capture-manifest-records.json",
    "arm-a/raw-row-manifest-laststage03.json",
    "arm-a/raw-row-manifest-reference04.json",
    "arm-a/attempt-lineage.json",
    "arm-a/prerun-revalidation.json",
    # PR #122 review-correction pass (2026-09-08, findings 1-2): the
    # accepted-checkpoint byte-continuity proof (inode/ctime/mtime/full-sha
    # per host + launch-path bindings) and the exact valid-run Compute Unit
    # bindings (per-stage observed GPU UUIDs from run-side capture/service/
    # reference records + verbatim launch commands). Recovered read-only;
    # no execution.
    "arm-a/checkpoint-continuity.json",
    "arm-a/run-device-bindings.json",
    # retained Arm B cold-acquisition + realization PASS artifacts
    # (executed on the fabric 2026-09-08; see evidence/arm-b/ records:
    # cold-root prestates, source census/plan/requirements, coordinator
    # authorization, per-host acquisition ledgers, per-stage
    # assemble/realize reports, runtime-read audits, post-inventories,
    # coordinator counters, and the 6774474->5179c41 delta audit).
    # Fabric-produced compact evidence; the CPU campaign never regenerates
    # these. Reduced by scripts/issue117_arm_b_evidence.py.
    "arm-b/cold-root-prestate-inferswarm01.json",
    "arm-b/cold-root-prestate-inferswarm03.json",
    "arm-b/source-census.json",
    "arm-b/source-block-plan.json",
    "arm-b/execution-plan.json",
    "arm-b/requirements.json",
    "arm-b/delta-audit.json",
    "arm-b/coordinator-record.json",
    "arm-b/coordinator-deltas.json",
    "arm-b/coordinator-counters.json",
    "arm-b/acquisition-ledger-inferswarm01.json",
    "arm-b/acquisition-ledger-inferswarm03.json",
    "arm-b/inventory-post-inferswarm01.json",
    "arm-b/inventory-post-inferswarm03.json",
    "arm-b/assemble-stage-1.json",
    "arm-b/assemble-stage-2.json",
    "arm-b/assemble-stage-3.json",
    "arm-b/realize-stage-1.json",
    "arm-b/realize-stage-2.json",
    "arm-b/realize-stage-3.json",
    "arm-b/read-audit-stage-1.json",
    "arm-b/read-audit-stage-2.json",
    "arm-b/read-audit-stage-3.json",
    # PR #127 correction (retention/derivation only, no rerun): the
    # attempt-lineage record (six invalid launches + the valid campaign,
    # recovered from contemporaneous transcript/host evidence) and the
    # three low-level accounting records backing the corrected zero
    # invariants
    "arm-b/attempt-lineage.json",
    "arm-b/runtime-fallback-accounting.json",
    "arm-b/steady-state-movement.json",
    "arm-b/coordinator-transport-accounting.json",
    # PR #127 round-3 correction (maintainer findings 1-5): the RAW
    # retained evidence the reducer now parses directly — the byte-exact
    # source-server access log, the three realize-strace logs, the
    # byte-pinned producer sources (participant driver scripts + the
    # frozen FreeToken worktree files that fix lifecycle-counter
    # semantics) — and the machine-readable read-only host observations
    # (coordinator state-tree inventory, root-inode continuity, host
    # raw-log pins)
    "arm-b/raw/source-server-access.log",
    "arm-b/raw/realize-strace.stage-1.log",
    "arm-b/raw/realize-strace.stage-2.log",
    "arm-b/raw/realize-strace.stage-3.log",
    "arm-b/raw/producer/armb_common.py",
    "arm-b/raw/producer/armb_inventory.py",
    "arm-b/raw/producer/armb_materialize.py",
    "arm-b/raw/producer/armb_node_acquire.py",
    "arm-b/raw/producer/armb_plan_core.py",
    "arm-b/raw/producer/armb_read_audit.py",
    "arm-b/raw/producer/armb_realize_child.py",
    "arm-b/raw/producer/armb_realize_child.inferswarm03.py",
    "arm-b/raw/producer/armb_source_server.py",
    "arm-b/raw/producer/issue74_methodology.py",
    "arm-b/raw/producer/issue99_artifact_core.py",
    "arm-b/raw/producer/stage_runtime.py",
    "arm-b/raw/producer/stage_runtime.inferswarm03.py",
    "arm-b/raw/producer/loader.py",
    "arm-b/raw/producer/loader.inferswarm03.py",
    "arm-b/raw/producer/r6_dense_census.py",
    "arm-b/raw/producer/SHA256SUMS",
    "arm-b/observations/coordinator-state-inventory.json",
    "arm-b/observations/root-inode-continuity.json",
    "arm-b/observations/host-raw-log-pins.json",
    # PR #127 round-4 correction (P1-1/P1-2): byte-exact raw copies of
    # all eight coordinator operational files (cross-bound to the
    # observed inventory by exact path/size/sha256) and the
    # digest-bound execution-session transport audit backing the
    # receipt-path derivation of the coordinator zero invariants
    "arm-b/raw/coordinator/inventory-inferswarm01.json",
    "arm-b/raw/coordinator/inventory-inferswarm03.json",
    "arm-b/raw/coordinator/scripts/armb_common.py",
    "arm-b/raw/coordinator/scripts/armb_coordinator.py",
    "arm-b/raw/coordinator/scripts/armb_inventory.py",
    "arm-b/raw/coordinator/scripts/armb_plan_core.py",
    "arm-b/raw/coordinator/scripts/__pycache__/armb_coordinator.cpython-313.pyc",
    "arm-b/raw/coordinator/scripts/__pycache__/armb_plan_core.cpython-313.pyc",
    "arm-b/observations/coordinator-transport-audit.json",
    # retained Arm C ordinary-serving campaign artifacts (executed on the
    # fabric 2026-09-09; see evidence/arm-c/run-record.json). Fabric-produced
    # compact evidence; the CPU campaign never regenerates these. The gzip
    # strace captures are retained compressed; digests pin the compressed
    # bytes.
    "arm-c/run-record.json",
    "arm-c/attempt-lineage.json",
    # frozen FreeToken producer bytes @ 924cd22e retained verbatim and
    # sha256-pinned: the ordinary-path invocation-semantics derivation
    # (correction /2) reads these; never regenerated
    "arm-c/frozen-freetoken/924cd22e/python/freetoken/research/"
    "r5b_epochs.py",
    "arm-c/frozen-freetoken/924cd22e/benchmarks/inferswarm_r6/"
    "coordinator.py",
    "arm-c/frozen-freetoken/924cd22e/benchmarks/inferswarm_r6/"
    "xc_strategy.py",
    # issue #129: additional frozen control-plane bytes retained verbatim
    # from the same producer. These bytes stay in the additive #129 area.
    "arm-c-retry/frozen-source/924cd22e/python/freetoken/research/"
    "r3_planner.py",
    "arm-c-retry/frozen-source/924cd22e/python/freetoken/research/"
    "r5a_serving.py",
    "arm-c-retry/frozen-source/924cd22e/benchmarks/inferswarm_r6/"
    "strategy.py",
    "arm-c/reconciliation.json",
    "arm-c/chain-plan.json",
    "arm-c/plan-verification.json",
    "arm-c/direct-run.json",
    "arm-c/direct/execution-plan.json",
    "arm-c/ordinary-campaign.json",
    "arm-c/fencing-arm.json",
    "arm-c/coordinator-report.json",
    "arm-c/lifecycle-serving-report.json",
    "arm-c/coordinator-env.json",
    "arm-c/coordinator-census-pre.json",
    "arm-c/coordinator-census-post.json",
    "arm-c/host-census-pre-01.json",
    "arm-c/host-census-post-01.json",
    "arm-c/host-census-pre-03.json",
    "arm-c/host-census-post-03.json",
    "arm-c/strace-audit.json",
    "arm-c/strace/direct.strace.gz",
    "arm-c/strace/node-agent.strace.gz",
    "arm-c/strace/last-stage-direct.strace.gz",
    "arm-c/strace/last-stage-ordinary.strace.gz",
    "arm-c/last-stage-direct.json",
    "arm-c/last-stage-ordinary.json",
    "arm-c/decoded-bytes.json",
    "arm-c/equality.json",
    "arm-c/zero-invariants.json",
    "arm-c/invalid-attempt-6/direct-run.json",
    # retention/derivation correction pass (2026-09-09, no rerun):
    # frozen-authority audit, recovered /2 lineage, and the derived
    # blocker terminal
    "arm-c/pre-execution-authority-audit.json",
    "arm-c/blocker-reduction.json",
    # issue #129 CPU-only Arm-C retry methodology artifacts (2026-09-09):
    # frozen rendered prompt-token fixture + full methodology reduction,
    # derived from retained accepted evidence; the accepted arm-c/ blocker
    # bytes above are read-only input and are never regenerated here —
    # they are preserved byte-exact from the accepted merge by the
    # regression in tests/test_issue129_arm_c_retry.py
    "arm-c-retry/prompt-fixture.json",
    "arm-c-retry/methodology-run.json",
    "arm-c-retry/authority.json",
    "arm-c-retry/integrity.json",
    "arm-c-retry/frozen-tokenizer/assets/chat_template.jinja",
    "arm-c-retry/frozen-tokenizer/assets/config.json",
    "arm-c-retry/frozen-tokenizer/assets/generation_config.json",
    "arm-c-retry/frozen-tokenizer/assets/tokenizer.json",
    "arm-c-retry/frozen-tokenizer/assets/tokenizer_config.json",
    "arm-c-retry/frozen-tokenizer/requirements.txt",
    "arm-c-retry/frozen-tokenizer/software-identity.json",
    # issue #133 physical Arm-C retry campaign (2026-09-10): the reviewed
    # physical-campaign authority document binding the fresh campaign and
    # the execution-freeze record pinning the correctness-bearing driver
    # bytes before the first launch
    "arm-c-retry/physical-campaign-authority.json",
    "arm-c-retry/execution-freeze.json",
    "arm-c-retry/phase-a-correction.json",
    # issue #133 Phase-B corrected freeze (2026-09-10): live GPU identity
    # observation (read-only), corrected canonical environment support,
    # and the phase-B correction record
    "arm-c-retry/gpu-identity-observation.json",
    "arm-c-retry/phase-b-correction.json",
    # issue #133 physical execution (2026-09-10): the first physical Arm-C
    # retry campaign's retained evidence — terminal FAIL
    # ISSUE117_ARM_C_ORDINARY_SERVING_FAIL (18/24; six regime-4
    # committed-token divergences re-observed on freshly executed arms;
    # all Coordinator-zero/fencing/data-path/deployment-identity
    # invariants held; no STOP fired)
    "arm-c-retry/physical-execution/README.md",
    "arm-c-retry/physical-execution/terminal-reduction.json",
    "arm-c-retry/physical-execution/equality-reduction.json",
    "arm-c-retry/physical-execution/strace-audit.json",
    "arm-c-retry/physical-execution/strace-raw-pins.json",
    "arm-c-retry/physical-execution/substrate-reconciliation-01.json",
    "arm-c-retry/physical-execution/substrate-reconciliation-03.json",
    "arm-c-retry/physical-execution/last-stage-direct.json",
    "arm-c-retry/physical-execution/last-stage-ordinary.json",
    "arm-c-retry/physical-execution/attempts/armc-retry-physical-1.json",
    "arm-c-retry/physical-execution/attempts/execution-plan.launch1.json",
    "arm-c-retry/physical-execution/preflight/prelaunch-verdict-run1.json",
    "arm-c-retry/physical-execution/preflight/"
    "prelaunch-verdict-immediate-prelaunch.json",
    "arm-c-retry/physical-execution/preflight/"
    "tokenizer-deployment-proof.json",
    "arm-c-retry/physical-execution/preflight/host-preflight-01.json",
    "arm-c-retry/physical-execution/preflight/host-preflight-03.json",
    # review 5173318161: coordinator receive/materialization/bulk
    # boundary proof inputs (vendored executed sources + pins doc)
    "arm-c-retry/physical-execution/"
    "coordinator-boundary-source-pins.json",
    "arm-c-retry/frozen-source/924cd22e/benchmarks/inferswarm_r6/"
    "node_agent.py",
    "arm-c-retry/frozen-source/924cd22e/benchmarks/inferswarm_r6/"
    "chain_runtime.py",
    "arm-c-retry/frozen-source/924cd22e/benchmarks/inferswarm_r6/"
    "stage_chain.py",
    "arm-c-retry/frozen-source/924cd22e/benchmarks/inferswarm_xc/"
    "cpu_only.py",
    "arm-c-retry/frozen-source/924cd22e/python/freetoken/research/"
    "xc_wire.py",
    "arm-c-retry/frozen-source/924cd22e/python/freetoken/research/"
    "xc_coordinator.py",
    # issue #137 Arm-C regime-4 diagnosis (2026-09-11,
    # DIAGNOSTIC_ONLY): CPU-only causal inventory, physical diagnostic
    # probe records (fresh i137-diag-* run identity), per-layer capture
    # manifests, and the fail-closed conclusions reduction deriving
    # ISSUE117_ARM_C_REGIME4_DIAGNOSIS_LOCALIZED; the accepted #133
    # terminal FAIL is unchanged historical evidence
    "arm-c-regime4-diagnosis-137/METHODOLOGY.md",
    "arm-c-regime4-diagnosis-137/README.md",
    "arm-c-regime4-diagnosis-137/phase1-inventory.json",
    "arm-c-regime4-diagnosis-137/i137-diag-A-1789127822.json",
    "arm-c-regime4-diagnosis-137/i137-diag-A-1789129558.json",
    "arm-c-regime4-diagnosis-137/i137-diag-A-1789129893.json",
    "arm-c-regime4-diagnosis-137/i137-diag-A-1789130927.json",
    "arm-c-regime4-diagnosis-137/i137-diag-A-1789131013.json",
    "arm-c-regime4-diagnosis-137/i137-diag-A-1789131099.json",
    "arm-c-regime4-diagnosis-137/i137-diag-A-1789131186.json",
    "arm-c-regime4-diagnosis-137/i137-diag-A2-1789128152.json",
    "arm-c-regime4-diagnosis-137/i137-diag-B-1789130217.json",
    "arm-c-regime4-diagnosis-137/i137-diag-C-1789128426.json",
    "arm-c-regime4-diagnosis-137/i137-diag-D-1789128772.json",
    "arm-c-regime4-diagnosis-137/i137-diag-D2-1789129163.json",
    "arm-c-regime4-diagnosis-137/i137-diag-D2-1789130625.json",
    "arm-c-regime4-diagnosis-137/manifest-first-stage1-d2b.json",
    "arm-c-regime4-diagnosis-137/manifest-middle-stage2-d2b.json",
    "arm-c-regime4-diagnosis-137/diagnostic-conclusions.json",
}

#: preservation pin: the accepted #118 canonical summary's exact bytes.
#: The campaign never rewrites this file; a preservation regression and the
#: retained MANIFEST enforce the pin.
ACCEPTED_118_CANONICAL_SUMMARY_SHA256 = (
    "26520e1608d9b12b5ac9e2667e55b9a8f5342818e3c701abaaaafb4319c57d4a")
PURITY_TOKENS = (
    "gemma", "rtx", "3060", "3090", "bf16", "triton", "flashinfer", "cuda",
    "inferswarm00", "inferswarm01", "inferswarm03", "inferswarm04",
    "safetensors", "tokenizer", "checkpoint",
)
#: Synthetic capacity model: usable weight bytes as a fraction of the
#: synthetic checkpoint, mirroring the real topology's feasibility shape.
#: The fractions are chosen against the exact participant-requirement
#: accounting (assigned + declared shared state per stage): a 16-layer stage
#: with its embedding/shared-head state needs 98,368 bytes (42.9% of the
#: 229,440-byte synthetic checkpoint) and a 24-layer stage needs 131,072
#: bytes (57.1%), so any 3060-class fraction in [42.9%, 57.1%) makes the
#: V5-shaped fixture candidate feasible and every 24-layer stage infeasible; 0.50
#: sits inside that window. A whole-checkpoint single stage (229,440 unique
#: bytes) fits only the reference 3090-class CU at 1.06. Physical capacity
#: truth is re-frozen by the physical preflight; this is a labeled fixture
#: model, not a hardware claim.
CAPACITY_FRACTIONS = {"NVIDIA GeForce RTX 3060": 0.50, "NVIDIA GeForce RTX 3090": 1.06}
#: Declared fixture path bandwidth (bytes/second) for transition economics.
FIXTURE_BANDWIDTH_BYTES_PER_SECOND = 125_000_000
NODE_IDS = ("inferswarm01", "inferswarm03")
PLANNING_EVIDENCE_CONTRACT = {
    "path": {"evidence_version": "issue117-evidence-v1",
             "evidence_identity": "path-band-v1",
             "applicability_context": {"fixture": "cpu-only", "arm": "planning"}},
}
FIXTURE_QUALIFICATION_RECORD_ID = "inferswarm.issue117.fixture-qualification/1"


def require(condition: Any, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def subject_identity_digest(subject: Mapping[str, Any]) -> str:
    """The Issue #117 execution-equality subject digest."""
    from issue117_subject_identity import subject_digest
    return subject_digest(subject)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture_adjudication_identity(fixture_digest: str,
                                  qualification_subject_digest: str) -> str:
    """The fixture-scoped terminal adjudication identity.

    The CPU fixture world's qualification authority is the fixture contract
    itself: the digest binds the frozen fixture document and the exact
    execution-equality subject identity. It is labeled fixture-scoped
    everywhere and is never the accepted V5 adjudication identity.
    """
    payload = canonical_json_bytes({
        "scope": "issue117-cpu-fixture",
        "fixture_digest": fixture_digest,
        "qualification_subject_digest": qualification_subject_digest,
    })
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def synthetic_capacity_model(strategy: GemmaDenseStrategy) -> tuple[dict[str, int], dict[str, Any]]:
    total = checkpoint_weight_bytes(strategy.catalog)
    usable = {}
    for cu in strategy.snapshot["compute_units"]:
        usable[cu["cu_id"]] = int(total * CAPACITY_FRACTIONS[cu["product"]])
    model = {
        "model": "synthetic-scaled-capacity-v2",
        "note": "fixture-only capacity fractions chosen against the exact "
                "participant-requirement accounting (16-layer stage with "
                "embedding/shared-head state feasible, 24-layer stages "
                "infeasible, whole checkpoint only on the reference CU); "
                "physical capacities are re-frozen by the physical preflight",
        "usable_weight_bytes": usable,
        "synthetic_checkpoint_weight_bytes": total,
    }
    return usable, model


def build_world(temp: Path):
    """Frozen strategy, plan, coordinator, nodes, and one authorized Source.

    The SOURCE side builds the catalog and artifact manifest (the only
    byte-reading steps); the strategy/planning waist consumes the resulting
    descriptors. The qualification subject is derived from the exact
    synthetic catalog, so the fixture world can never claim the accepted
    Gemma checkpoint identity.
    """
    repo = temp / "source-repository"
    config, objects = build_synthetic_gemma_repository(repo)
    catalog = catalog_from_repository(repo, config=config)

    def source_bytes(name: str) -> bytes:
        return objects[name]

    manifest = build_source_manifest(catalog, source_bytes=source_bytes)
    subject = subject_from_catalog(
        catalog, execution=SYNTHETIC_SUBJECT_EXECUTION, backend=SYNTHETIC_SUBJECT_BACKEND)
    strategy = GemmaDenseStrategy(catalog=catalog, subject=subject,
                                  source_manifest=manifest)
    capacity, capacity_model = synthetic_capacity_model(strategy)
    candidates = strategy.legal_candidates(capacity_model=capacity)
    v5 = strategy.accepted_v5_candidate(candidates)

    fixture_digest_document = json.loads(FIXTURE_PATH.read_text())
    fixture_digest = fixture_digest_document["fixture_digest"]
    subject_digest = subject_identity_digest(v5["qualification_subject"])
    adjudication = fixture_adjudication_identity(fixture_digest, subject_digest)
    qualification_record = build_qualification_record(
        qualification_record_id=FIXTURE_QUALIFICATION_RECORD_ID,
        terminal_disposition="V5_QUALIFICATION_PASS",
        terminal_adjudication_sha256=adjudication,
        qualification_subject=v5["qualification_subject"],
        authority_extra={"fixture_digest": fixture_digest},
        scope="issue117-cpu-fixture")

    origin = LocalFileSource(source_id=ORIGIN_SOURCE_ID, root=repo)
    nodes = {node_id: Node(node_id, NodeArtifactCache(temp / "issue117-caches" / node_id))
             for node_id in NODE_IDS}
    coordinator = Coordinator(
        node_sources=[nodes[node_id].descriptor() for node_id in NODE_IDS],
        origin_sources=[origin.descriptor()])
    plan = strategy.plan(v5)
    requirements = coordinator.freeze(plan, strategy.resolve)
    for node in nodes.values():
        coordinator.ingest(node.inventory())
    return {
        "temp": temp, "repo": repo, "objects": objects, "config": config,
        "catalog": catalog, "manifest": manifest, "subject": subject,
        "strategy": strategy, "capacity": capacity,
        "capacity_model": capacity_model, "candidates": candidates, "v5": v5,
        "fixture_digest": fixture_digest, "adjudication": adjudication,
        "qualification_record": qualification_record, "origin": origin,
        "nodes": nodes, "coordinator": coordinator, "plan": plan,
        "requirements": requirements,
    }


def build_path_evidence(world) -> list[dict[str, Any]]:
    """Freeze one bandwidth record per required artifact of the V5 plan.

    Sources are the coordinator's own authorizations, so ranking evidence can
    never name a source the control plane would not authorize.
    """
    from issue103_planner import validate_path_evidence

    coordinator = world["coordinator"]
    evidence = []
    for participant in world["requirements"]["participants"]:
        delta = coordinator.delta(participant["participant_id"])
        stage_number = participant["participant_id"].rsplit(".stage-", 1)[1]
        for artifact_id in delta["missing_artifact_ids"]:
            ticket = coordinator.authorize(delta, artifact_id)
            document = {
                "schema": "issue103.path-evidence/1",
                "candidate_id": f"{world['v5']['candidate_id']}::stage-{stage_number}",
                "participant_id": participant["participant_id"],
                "node_id": participant["node_id"],
                "artifact_id": artifact_id,
                "source": ticket["source"],
                "target_node_id": participant["node_id"],
                "target": {"execution_unit_id": participant["execution_unit_id"]},
                "path_id": f"fixture-path-{artifact_id}",
                "bandwidth_bytes_per_second": FIXTURE_BANDWIDTH_BYTES_PER_SECOND,
                "evidence_version": "issue117-evidence-v1",
                "evidence_identity": "path-band-v1",
                "applicability_context": {"fixture": "cpu-only", "arm": "planning"},
                "requirement_identity": artifact_id,
                "plan_digest": world["plan"]["plan_digest"],
                "requirements_digest": world["requirements"]["requirements_digest"],
            }
            document["evidence_digest"] = self_digest(document, identity_field="evidence_digest")
            validate_path_evidence(document)
            evidence.append(document)
    return evidence


def build_admission_planner(world, *, requirements_by_candidate=None,
                            candidate_overrides=None,
                            path_evidence_by_candidate=None,
                            evidence_contract=None,
                            coordinators_by_candidate=None) -> AdmissionPlanner:
    strategy = world["strategy"]
    candidates = world["candidates"]
    if candidate_overrides:
        # control-plane misuse simulations supply fully-formed candidates;
        # the planner recomputes every subject digest from the subject itself
        candidates = [dict(candidate) for candidate in candidates]
        for candidate in candidates:
            override = candidate_overrides.get(candidate["candidate_id"])
            if override is not None:
                candidate.update(override)
    feasibility = {
        candidate["candidate_id"]: strategy.feasibility(candidate, capacity_model=world["capacity"])
        for candidate in candidates
    }
    return AdmissionPlanner(
        candidates=candidates,
        feasibility=feasibility,
        qualification_records=[world["qualification_record"]],
        qualification_policy=fixture_qualification_policy(world),
        requirements_by_candidate=requirements_by_candidate or {
            world["v5"]["candidate_id"]: world["requirements"]},
        path_evidence_by_candidate=path_evidence_by_candidate
        if path_evidence_by_candidate is not None
        else {world["v5"]["candidate_id"]: build_path_evidence(world)},
        evidence_contract=evidence_contract or PLANNING_EVIDENCE_CONTRACT,
        coordinators_by_candidate=coordinators_by_candidate
        if coordinators_by_candidate is not None
        else {world["v5"]["candidate_id"]: world["coordinator"]},
    )


def fixture_qualification_policy(world) -> dict[str, Any]:
    """The fixture world's strict qualification policy.

    Declares the shared machinery-local subject keys so the evaluator
    compares execution-equality subject identities. The physical preflight
    has no accepted V5 record while the authority blocker remains unresolved.
    """
    from issue117_subject_identity import MACHINERY_LOCAL_SUBJECT_KEYS
    return {
        "policy": QUALIFICATION_POLICY_STRICT,
        "accepted_dispositions": ("V5_QUALIFICATION_PASS",),
        "accepted_adjudication_sha256": world["adjudication"],
        "machinery_local_subject_keys": MACHINERY_LOCAL_SUBJECT_KEYS,
        "required_for_admission": True,
    }


def cold_acquisition(world) -> dict[str, Any]:
    """Arm B (CPU analog): plan-driven participant-exact cold acquisition."""
    coordinator = world["coordinator"]
    nodes = world["nodes"]
    per_participant = {}
    for participant in world["requirements"]["participants"]:
        node = nodes[participant["node_id"]]
        delta = coordinator.delta(participant["participant_id"])
        transfers = []
        for artifact_id in delta["missing_artifact_ids"]:
            ticket = coordinator.authorize(delta, artifact_id)
            record = next(r for r in participant["required_artifacts"]
                          if r["artifact_id"] == artifact_id)
            result = node.acquire(coordinator, ticket, world["origin"])
            require(result["status"] in ("ACQUIRED", "CACHE_HIT"),
                    f"cold arm transfer failed for {artifact_id}: {result['status']}")
            # a content-identical shared-state variant is a verified cache
            # hit, not a transfer: declared shared state is acquired once
            transferred = result["bytes"] if result["status"] == "ACQUIRED" else 0
            transfers.append({
                "artifact_id": artifact_id,
                "length": record["length"],
                "source_id": ticket["source"]["source_id"],
                "endpoint_scheme": ticket["source"]["endpoint"].split(":", 1)[0],
                "status": result["status"],
                "bytes": transferred,
            })
        per_participant[participant["participant_id"]] = {
            "node_id": participant["node_id"],
            "required_bytes": participant["required_artifact_bytes"],
            "transferred_bytes": sum(t["bytes"] for t in transfers),
            "cache_hit_bytes": sum(t["length"] for t in transfers
                                   if t["status"] == "CACHE_HIT"),
            "transfer_count": len(transfers),
            "transfers": transfers,
        }
    # publish verified local state and refresh inventories for later arms
    for participant in world["requirements"]["participants"]:
        node = nodes[participant["node_id"]]
        for record in participant["required_artifacts"]:
            node.publish(record)
        coordinator.ingest(node.inventory())
    return {
        "plan_digest": world["plan"]["plan_digest"],
        "per_participant": per_participant,
        "coordinator_bytes_observed": coordinator.bytes_observed,
        "origin_requests_by_object": {
            name: len(world["origin"].requests_for(name))
            for name in sorted(world["objects"])
        },
    }


def materialize_and_reconcile(world, *, coordinator, nodes) -> dict[str, Any]:
    """Materialize planned state only, reconcile, and derive stage witnesses."""
    witnesses = {}
    for participant in world["requirements"]["participants"]:
        node = nodes[participant["node_id"]]
        identity = {"epoch": world["plan"]["epoch"],
                    "participant_id": participant["participant_id"],
                    "node_id": node.node_id}
        materializations = []
        witness_pairs = []
        for record in participant["required_artifacts"]:
            data = node.cache.open_verified(record)
            for logical_state_id in record["satisfies_logical_state_ids"]:
                materializations.append({**identity, "logical_state_id": logical_state_id,
                                         "verification": "VERIFIED_CACHE_SOURCE",
                                         "observed_bytes": len(data),
                                         "expected_bytes": record["length"]})
                witness_pairs.append([logical_state_id, hashlib.sha256(data).hexdigest()])
        reconciliation = coordinator.reconcile(
            participant["participant_id"],
            [r["artifact_id"] for r in participant["required_artifacts"]],
            materializations)
        witness_pairs.sort()
        witnesses[participant["participant_id"]] = {
            "node_id": node.node_id,
            "state_count": len(witness_pairs),
            "witness_digest": digest_of_bytes(
                json.dumps(witness_pairs, sort_keys=True, separators=(",", ":")).encode()),
            "reconciliation_status": reconciliation["status"],
        }
    return witnesses


def warm_restart(world) -> dict[str, Any]:
    """Arm D (CPU analog): restart realization; reacquire zero weight bytes."""
    coordinator = Coordinator(
        node_sources=[world["nodes"][node_id].descriptor() for node_id in NODE_IDS],
        origin_sources=[world["origin"].descriptor()])
    nodes = {node_id: Node(node_id, NodeArtifactCache(world["temp"] / "issue117-caches" / node_id))
             for node_id in NODE_IDS}
    for node in nodes.values():
        coordinator.ingest(node.inventory())
    requirements = coordinator.freeze(world["plan"], world["strategy"].resolve)
    require(requirements["requirements_digest"]
            == world["requirements"]["requirements_digest"],
            "warm restart changed the frozen requirements")
    per_participant = {}
    for participant in requirements["participants"]:
        node = nodes[participant["node_id"]]
        delta = coordinator.delta(participant["participant_id"])
        reacquired_bytes = 0
        cache_hit_bytes = 0
        for artifact_id in sorted(delta["missing_artifact_ids"] + delta["local_artifact_ids"]):
            ticket = coordinator.authorize(delta, artifact_id)
            if artifact_id in delta["missing_artifact_ids"]:
                source = world["origin"]
            else:
                record = next(r for r in participant["required_artifacts"]
                              if r["artifact_id"] == artifact_id)
                source = node.source(record)
            result = node.acquire(coordinator, ticket, source)
            if result["status"] == "ACQUIRED":
                reacquired_bytes += result["bytes"]
            elif result["status"] == "CACHE_HIT":
                cache_hit_bytes += result["bytes"]
            else:
                raise AssertionError(f"warm restart transfer returned {result['status']}")
        per_participant[participant["participant_id"]] = {
            "node_id": node.node_id,
            "reacquired_bytes": reacquired_bytes,
            "cache_hit_bytes": cache_hit_bytes,
        }
    witnesses = materialize_and_reconcile(world, coordinator=coordinator, nodes=nodes)
    return {
        "plan_digest": world["plan"]["plan_digest"],
        "per_participant": per_participant,
        "warm_restart_model_weight_transfer_bytes": sum(
            entry["reacquired_bytes"] for entry in per_participant.values()),
        "witnesses": witnesses,
        "coordinator_bytes_observed": coordinator.bytes_observed,
    }


def locality_mutation(world, decision_cold) -> dict[str, Any]:
    """Arm E (planning-only): verified inventory changes economics only.

    After the cold realization the participants hold verified state; a second
    planning pass over identical strategy/policy/qualification inputs must
    show a lower (here: zero) transition cost while every gate outcome is
    unchanged and no unqualified candidate becomes admissible.
    """
    planner = build_admission_planner(world)
    decision_warm = planner.rank()
    gates_cold = {row["candidate_id"]: row["gates"] for row in decision_cold["candidates"]}
    gates_warm = {row["candidate_id"]: row["gates"] for row in decision_warm["candidates"]}
    unchanged = {candidate_id: gates_cold[candidate_id] == gates_warm[candidate_id]
                 for candidate_id in gates_cold}
    cold_row = next(row for row in decision_cold["candidates"]
                    if row["candidate_id"] == world["v5"]["candidate_id"])
    warm_row = next(row for row in decision_warm["candidates"]
                    if row["candidate_id"] == world["v5"]["candidate_id"])
    return {
        "objective": decision_warm["objective"],
        "selected_candidate_id": decision_warm["selected_candidate_id"],
        "v5_transition_seconds_cold": cold_row["estimated_transition_seconds"],
        "v5_transition_seconds_warm": warm_row["estimated_transition_seconds"],
        "v5_missing_bytes_cold": cold_row["missing_bytes"],
        "v5_missing_bytes_warm": warm_row["missing_bytes"],
        "gate_ledger_unchanged": unchanged,
        "all_gates_unchanged": all(unchanged.values()),
        "economics_changed": (cold_row["estimated_transition_seconds"]
                              != warm_row["estimated_transition_seconds"]),
    }


#: Ledger event classes that would indicate out-of-band model-state movement
#: or host-RAM mirror staging. None exist on the accepted ordinary path;
#: the accounting below sums them from retained records, so poisoning the
#: records makes the derived invariants nonzero.
HOST_MIRROR_STAGING_EVENT = "HOST_MIRROR_STAGE"
HOST_MIRROR_RELEASE_EVENT = "HOST_MIRROR_RELEASE"
UNPLANNED_MODEL_STATE_MOVEMENT_EVENT = "MODEL_STATE_MOVE"


def staging_accounting(world) -> dict[str, Any]:
    """Accepted #53 host-staging semantics derived from retained records.

    Persistent partials, verified cache bytes, host-mirror bytes, and
    out-of-band model-state movement are summed from the nodes' inventories
    and acquisition ledgers. No acceptance zero is written here: an empty
    record set sums to zero, and the negative controls poison the records to
    prove the derivations are non-vacuous.
    """
    required_artifact_ids = {
        record["artifact_id"]
        for participant in world["requirements"]["participants"]
        for record in participant["required_artifacts"]
    }
    persistent_partials = 0
    verified_cache_bytes = 0
    mirror_staged_bytes = 0
    mirror_released_bytes = 0
    unplanned_movement_bytes = 0
    for node in world["nodes"].values():
        inventory = node.cache.inventory()
        persistent_partials += len(inventory["partial_transfers"])
        verified_cache_bytes += sum(
            obj["length"] for obj in inventory["verified_objects"]
            if obj["byte_digest_verified"])
        for event in node.ledger.events:
            if event["event"] == HOST_MIRROR_STAGING_EVENT:
                mirror_staged_bytes += event.get("bytes", 0)
            elif event["event"] == HOST_MIRROR_RELEASE_EVENT:
                mirror_released_bytes += event.get("bytes", 0)
            elif event["event"] == UNPLANNED_MODEL_STATE_MOVEMENT_EVENT \
                    and event.get("artifact_id") not in required_artifact_ids:
                unplanned_movement_bytes += event.get("bytes", 0)
    return {
        "persistent_partial_states": persistent_partials,
        "verified_cache_bytes": verified_cache_bytes,
        "unexplained_persistent_host_mirror_bytes":
            mirror_staged_bytes - mirror_released_bytes,
        "unplanned_steady_state_model_state_movement_bytes": unplanned_movement_bytes,
        "note": "a durable verified artifact cache on local storage is not a "
                "host-RAM mirror; it may remain after realization",
    }


def count_bytes_payloads(value: Any) -> int:
    """Count raw ``bytes`` payloads embedded in control-plane documents.

    The Coordinator/planning waist must only ever see small immutable
    descriptors; this derivation records any bytes payload that leaked into
    the retained control-plane documents.
    """
    if isinstance(value, (bytes, bytearray)):
        return 1
    if isinstance(value, Mapping):
        return sum(count_bytes_payloads(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return sum(count_bytes_payloads(item) for item in value)
    return 0


def derive_coverage_invariants(requirements: Mapping[str, Any], *,
                               objects: Mapping[str, bytes],
                               total_weight: int) -> dict[str, int]:
    """Derive the whole-model-dependency invariants from retained records.

    ``unexplained_full_model_dependency`` counts upstream objects fully
    covered by byte-range requirements without being declared whole-object
    metadata; ``participant_requires_complete_model_repository`` counts
    participants whose weight bytes are not a proper subset of the
    checkpoint. Both are computed from the requirements document, so
    poisoning the requirements makes them nonzero.
    """
    whole_metadata_objects = {
        record["origin"]["source_object"]
        for participant in requirements["participants"]
        for record in participant["required_artifacts"]
        if record["kind"] == "whole_object"
    }
    full_object_bytes = 0
    for name, data in objects.items():
        if name in whole_metadata_objects:
            continue
        covered = bytearray(len(data))
        for participant in requirements["participants"]:
            for record in participant["required_artifacts"]:
                if record["origin"]["source_object"] != name \
                        or record["kind"] != "byte_range":
                    continue
                start, end = record["origin"]["byte_start"], record["origin"]["byte_end"]
                covered[start:end] = b"\x01" * (end - start)
        if all(covered):
            full_object_bytes += len(data)
    complete_participants = 0
    for participant in requirements["participants"]:
        weight = sum(record["length"] for record in participant["required_artifacts"]
                     if record["kind"] == "byte_range")
        if total_weight and weight >= total_weight:
            complete_participants += 1
    return {
        "unexplained_full_model_dependency": full_object_bytes,
        "participant_requires_complete_model_repository": complete_participants,
    }


def derive_zero_invariants(world, *, decision, accounting, cold, warm, mutation,
                           fence_summary, audit) -> dict[str, Any]:
    """Every acceptance invariant derived from retained records, not asserted."""
    strategy = world["strategy"]
    catalog = world["catalog"]
    purity = planner_purity_audit(
        ROOT / "scripts" / "issue117_planner.py", PURITY_TOKENS)
    staging = staging_accounting(world)

    required_artifact_ids = {
        record["artifact_id"]
        for participant in world["requirements"]["participants"]
        for record in participant["required_artifacts"]
    }
    ledger_events = [event for node in world["nodes"].values() for event in node.ledger.events]
    acquired = [event for event in ledger_events if event["event"] == "ACQUIRED"]
    unrelated = sum(event["bytes"] for event in acquired
                    if event["artifact_id"] not in required_artifact_ids)

    coverage = derive_coverage_invariants(
        world["requirements"], objects=world["objects"],
        total_weight=checkpoint_weight_bytes(catalog))

    executed_ids = {decision["selected_candidate_id"]} if decision["selected_candidate_id"] else set()
    inapplicable_executed = sum(
        1 for row in decision["candidates"]
        if row["candidate_id"] in executed_ids
        and row["gates"]["qualification_applicability"]["status"] != QUALIFICATION_APPLICABLE)

    weight_units = set(strategy.logical_state_units())
    unassigned = 0
    for participant in world["requirements"]["participants"]:
        declared = (set(participant["required_logical_state"]["assigned"])
                    | set(participant["required_logical_state"]["declared_shared"])
                    | set(participant["required_logical_state"]["required_metadata"]))
        for record in participant["required_artifacts"]:
            if not set(record["satisfies_logical_state_ids"]) & (declared & weight_units):
                unassigned += record["length"]

    plan_digests = {world["plan"]["plan_digest"], cold["plan_digest"], warm["plan_digest"]}
    fallback_states = sum(
        1 for node in world["nodes"].values() for event in node.lifecycle
        if event.get("state") not in (None, "MISSING", "AUTHORIZED", "ACQUIRING",
                                      "VERIFIED_AVAILABLE"))
    control_plane_documents = {
        "plan": world["plan"],
        "requirements": world["requirements"],
        "qualification_record": world["qualification_record"],
        "source_manifest": world["manifest"],
        "decision": decision,
        "strategy": strategy.frozen_document(world["candidates"],
                                             capacity_model=world["capacity"]),
    }
    return {
        "planner_model_specific_branches": purity["planner_model_specific_branches"],
        "qualification_inapplicable_candidate_executed": inapplicable_executed,
        "execution_math_unclassified_or_changed": (
            0 if audit["overall_result"] == "DELTA_CONTROL_ARTIFACT_MATERIALIZATION_ONLY"
            else 1),
        "unrelated_model_bytes_acquired_for_realization": unrelated,
        "unassigned_model_weight_bytes_acquired": unassigned,
        "unexplained_full_model_dependency":
            coverage["unexplained_full_model_dependency"],
        "participant_requires_complete_model_repository":
            coverage["participant_requires_complete_model_repository"],
        "coordinator_bulk_artifact_bytes_observed": world["coordinator"].bytes_observed,
        "control_plane_document_byte_payloads": sum(
            count_bytes_payloads(document)
            for document in control_plane_documents.values()),
        "unverified_state_used_as_locality_evidence": sum(
            1 for node in world["nodes"].values()
            for obj in node.cache.inventory()["verified_objects"]
            if not obj["byte_digest_verified"]),
        "unauthorized_source_used": sum(
            1 for event in acquired if event.get("source_id") != ORIGIN_SOURCE_ID),
        "unexplained_transition_bytes": accounting["unexplained_transition_bytes"],
        "unexplained_persistent_host_mirror_bytes":
            staging["unexplained_persistent_host_mirror_bytes"],
        "unplanned_steady_state_model_state_movement_bytes":
            staging["unplanned_steady_state_model_state_movement_bytes"],
        "runtime_fallback_events": fallback_states,
        "silent_plan_substitution_events": len(plan_digests) - 1,
        **{name: fence_summary[name] for name in FENCE_DERIVED_COUNTERS},
        "warm_restart_model_weight_transfer_bytes":
            warm["warm_restart_model_weight_transfer_bytes"],
    }


class _RogueSource:
    """A Source the control plane never authorized."""

    def __init__(self, root: Path):
        self._source = LocalFileSource(source_id="rogue-origin", root=root)

    @property
    def source_id(self) -> str:
        return self._source.source_id

    def descriptor(self):
        return self._source.descriptor()

    def read(self, origin, offset, length):
        return self._source.read(origin, offset, length)


class _DriftedSource:
    """The authorized Source identity after descriptor drift."""

    def __init__(self, endpoint: str):
        self._endpoint = endpoint
        self.source_id = "issue117-origin"

    def descriptor(self):
        return {"source_id": self.source_id, "endpoint": self._endpoint + "#drifted"}

    def read(self, origin, offset, length):
        raise AssertionError("a drifted source must never be read")


class NegativeControls:
    """Every control must fail closed; controls never touch live state."""

    def __init__(self):
        self.results: list[dict[str, Any]] = []

    def expect_failure(self, name: str, invocation: Callable[[], None], expected: str,
                       *, matched_reason: str | None = None):
        try:
            invocation()
        except Exception as error:
            reason = str(error).split("\n")[0]
            token = matched_reason or expected
            self.results.append({
                "control": name, "failed_closed": True,
                "reason": reason[:200], "expected": expected,
                "matched": token in str(error),
            })
            return
        self.results.append({"control": name, "failed_closed": False,
                             "reason": "NO_ERROR_RAISED", "expected": expected,
                             "matched": False})

    def record(self, name: str, passed: bool, reason: str, expected: str):
        self.results.append({"control": name, "failed_closed": passed,
                             "reason": reason[:200], "expected": expected,
                             "matched": passed})

    def expect_pass(self, name: str, invocation: Callable[[], None], description: str):
        """A positive gate property: raise on violation, record on hold."""
        try:
            invocation()
        except Exception as error:
            self.record(name, False, str(error), description)
            return
        self.record(name, True, description, description)

    @property
    def all_failed_closed(self) -> bool:
        return all(entry["failed_closed"] and entry["matched"] for entry in self.results)


def run_negative_controls(world, fixture_path: Path) -> NegativeControls:
    controls = NegativeControls()
    strategy = world["strategy"]
    coordinator = world["coordinator"]
    nodes = world["nodes"]

    def whole_model_injection():
        # a throwaway Coordinator so the live frozen plan is never replaced
        throwaway = Coordinator(
            node_sources=[nodes[node_id].descriptor() for node_id in NODE_IDS],
            origin_sources=[world["origin"].descriptor()])
        injected = json.loads(json.dumps(world["plan"]))
        injected["participants"][0]["required_state"]["assigned_logical_state"] = (
            ["state.embedding"]
            + [f"state.layer.{layer}" for layer in range(strategy.layers)]
            + ["state.final_norm"])
        injected.pop("plan_digest")
        injected["plan_digest"] = self_digest(injected, identity_field="plan_digest")
        requirements = throwaway.freeze(injected, strategy.resolve)
        guard_participant_exact(
            requirements,
            total_model_weight_bytes=checkpoint_weight_bytes(world["catalog"]))

    def unrelated_acquisition_accounting():
        # a throwaway Node proves the derivation counts unrequired bytes
        scratch = Node("scratch", NodeArtifactCache(world["temp"] / "scratch-cache"))
        scratch.ledger.record({"event": "ACQUIRED", "participant_id": "scratch",
                               "artifact_id": "intruder-object", "bytes": 4096,
                               "source_id": ORIGIN_SOURCE_ID})
        derived = derive_unrelated_bytes_for(scratch.ledger.events, required=set())
        if derived != 4096:
            raise AssertionError(f"unrelated acquisition mis-counted: {derived}")

    def coordinator_bulk_bytes():
        throwaway = Coordinator(
            node_sources=[nodes[node_id].descriptor() for node_id in NODE_IDS],
            origin_sources=[world["origin"].descriptor()])
        throwaway.freeze(b"raw model weight bytes", strategy.resolve)

    def unverified_local_credit():
        record = world["requirements"]["participants"][0]["required_artifacts"][0]
        nodes["inferswarm01"].cache.publish(record, b"")

    def corrupt_cache_object():
        participant = world["requirements"]["participants"][0]
        record = participant["required_artifacts"][0]
        node = nodes[participant["node_id"]]
        path = node.cache.lookup(record["content_digest"])
        if path is None:
            raise AssertionError("expected a cached object")
        original = path.read_bytes()
        path.write_bytes(b"\x00" + original[1:])
        try:
            node.cache.open_verified(record)
        finally:
            path.write_bytes(original)

    def unauthorized_source():
        participant = world["requirements"]["participants"][0]
        delta = coordinator.delta(participant["participant_id"])
        artifact_id = (delta["missing_artifact_ids"] or delta["local_artifact_ids"])[0]
        ticket = coordinator.authorize(delta, artifact_id)
        nodes[participant["node_id"]].acquire(coordinator, ticket,
                                              _RogueSource(world["repo"]))

    def source_descriptor_drift():
        participant = world["requirements"]["participants"][0]
        delta = coordinator.delta(participant["participant_id"])
        artifact_id = (delta["missing_artifact_ids"] or delta["local_artifact_ids"])[0]
        ticket = coordinator.authorize(delta, artifact_id)
        nodes[participant["node_id"]].acquire(
            coordinator, ticket, _DriftedSource(ticket["source"]["endpoint"]))

    def missing_path_evidence_yields_unranked():
        # a clean world: frozen plan, empty inventories, missing bytes, and
        # no path evidence -> the admissible candidate must stay unranked
        empty_nodes = {node_id: Node(node_id, NodeArtifactCache(
            world["temp"] / "empty-caches" / node_id)) for node_id in NODE_IDS}
        clean = Coordinator(
            node_sources=[empty_nodes[node_id].descriptor() for node_id in NODE_IDS],
            origin_sources=[world["origin"].descriptor()])
        for node in empty_nodes.values():
            clean.ingest(node.inventory())
        clean.freeze(world["plan"], strategy.resolve)
        planner = AdmissionPlanner(
            candidates=world["candidates"],
            feasibility={c["candidate_id"]: strategy.feasibility(
                c, capacity_model=world["capacity"]) for c in world["candidates"]},
            qualification_records=[world["qualification_record"]],
            qualification_policy=fixture_qualification_policy(world),
            requirements_by_candidate={world["v5"]["candidate_id"]: world["requirements"]},
            path_evidence_by_candidate={},
            evidence_contract=PLANNING_EVIDENCE_CONTRACT,
            coordinators_by_candidate={world["v5"]["candidate_id"]: clean})
        decision = planner.rank()
        if decision["selected_candidate_id"] is not None:
            raise AssertionError("selection without path evidence")
        v5_row = next(row for row in decision["candidates"]
                      if row["candidate_id"] == world["v5"]["candidate_id"])
        if not v5_row["admissible"]:
            raise AssertionError("qualification gate broke without path evidence")
        if v5_row["ranking_status"] != "FEASIBLE_UNRANKED":
            raise AssertionError("missing evidence invented economics")
        if v5_row["missing_bytes"] <= 0:
            raise AssertionError("control world has no missing bytes")

    def changed_executor_cannot_inherit():
        # a materially changed execution-bearing subject (new geometry and
        # producer identity) recomputes to a different subject digest and
        # must resolve QUALIFICATION_NOT_APPLICABLE
        from issue117_subject_identity import subject_digest
        mutated = json.loads(json.dumps(world["v5"]))
        mutated["stages"][0]["layer_end"] = 17
        mutated["stages"][1]["layer_start"] = 17
        mutated["qualification_subject"] = world["strategy"].qualification_subject(mutated)
        mutated["qualification_subject_digest"] = subject_digest(
            mutated["qualification_subject"])
        planner = build_admission_planner(
            world, candidate_overrides={world["v5"]["candidate_id"]: mutated})
        decision = planner.rank()
        if decision["selected_candidate_id"] is not None:
            raise AssertionError("changed executor inherited qualification")
        row = next(row for row in decision["candidates"]
                   if row["candidate_id"] == world["v5"]["candidate_id"])
        if row["gates"]["qualification_applicability"]["status"] == QUALIFICATION_APPLICABLE:
            raise AssertionError("subject mismatch not detected")

    def lying_subject_digest_is_refused():
        # a candidate whose declared subject digest does not recompute from
        # its own subject is control-plane misuse and fails loudly
        lying = json.loads(json.dumps(world["v5"]))
        lying["qualification_subject_digest"] = "sha256:" + "0" * 64
        planner = build_admission_planner(
            world, candidate_overrides={world["v5"]["candidate_id"]: lying})
        planner.rank()

    def accepted_subject_recovery_is_loadable_and_independent():
        # positive control: the accepted V5 qualification subject now loads
        # from byte-pinned historical evidence, with the exact accepted
        # terminal adjudication identity, WITHOUT any candidate machinery
        # (the reconstruction module imports no strategy/planner modules)
        from issue117_accepted_subject import accepted_v5_qualification_record
        record = accepted_v5_qualification_record(ROOT)
        assert record["authority"]["terminal_adjudication_sha256"] == (
            ACCEPTED_TERMINAL_ADJUDICATION_SHA256), (
            "recovered record is not bound to the accepted adjudication")
        import issue117_accepted_subject as accepted_subject
        import sys as _sys
        banned = ("issue117_gemma_strategy", "issue117_planner",
                  "issue117_preflight", "issue117_proof",
                  "issue117_integration_fixture")
        loaded = {name for name in _sys.modules if name in banned}
        source = _sys.modules[accepted_subject.__name__].__dict__
        assert not any(source.get(name) for name in banned), (
            "reconstruction module binds candidate machinery")
        assert not loaded or all(
            not accepted_subject.__dict__.get(name) for name in banned), (
            "reconstruction depends on candidate machinery")

    def accepted_subject_evidence_tampering_is_fail_closed():
        # byte-tamper the pinned physical-subject evidence in a throwaway
        # root: the reconstruction must fail closed (drift detection)
        import shutil
        import tempfile as _tempfile
        import issue117_accepted_subject as accepted_subject
        with _tempfile.TemporaryDirectory() as temp:
            relative = ("docs/qualification/gemma4-12b-it-v5/manifests/"
                        "physical-subject.json")
            target = Path(temp) / relative
            target.parent.mkdir(parents=True)
            shutil.copyfile(ROOT / relative, target)
            data = json.loads(target.read_text())
            data["execution"] = "tampered execution semantics"
            target.write_text(json.dumps(data))
            accepted_subject.accepted_v5_qualification_record(Path(temp))
        raise AssertionError("tampered evidence did not fail closed")

    def changed_execution_producer_cannot_reapply_audit():
        # poison the frozen producer delta: one execution-bearing zone file
        # changes bytes in the integration producer -> building the audit
        # must stop with R6_SUCCESSOR_REQUALIFICATION_REQUIRED, never DELTA_
        import issue117_applicability as applicability
        poisoned = load_producer_delta(ROOT)
        math_file = next(entry for entry in poisoned["zone_files"]
                         if "dense_stage_model_math" in entry["surfaces"]
                         and entry["delta"] == applicability.DELTA_IDENTICAL)
        math_file["integration_sha256"] = "sha256:" + "f" * 64
        math_file["delta"] = applicability.DELTA_CHANGED
        poisoned.pop("producer_delta_digest")
        poisoned["producer_delta_digest"] = self_digest(
            poisoned, identity_field="producer_delta_digest")
        applicability.build_audit_document(
            poisoned, authority={"integration_producer":
                                 applicability.FROZEN_INTEGRATION_PRODUCER,
                                 "execution_authority":
                                 applicability.ACCEPTED_FREETOKEN_EXECUTION_AUTHORITY})

    def fence_derivation_is_non_vacuous():
        # poison the committed-result ledger with a forged wrong-session
        # result: the derived counter must become nonzero
        import issue117_planner as planner_module
        fencing = run_fencing(world, json.loads(FIXTURE_PATH.read_text()))
        authority = fencing["summary"]["authority"]
        poisoned_ledger = list(fencing["committed_result_records"]) + [{
            "contract_id": authority["contract_id"],
            "session_id": "other-session",
            "epoch": authority["epoch"],
            "realization_id": authority["realization_id"],
            "plan_digest": authority["plan_digest"],
            "operation": "decode",
            "position": len(fencing["committed_result_records"]) // 2,
        }]
        derived = planner_module.derive_fence_counters(poisoned_ledger, authority=authority)
        if derived["wrong_session_result_committed"] < 1:
            raise AssertionError("poisoned fence ledger derived zero invalid results")

    def staging_derivation_is_non_vacuous():
        # poison a scratch node ledger with host-mirror staging and an
        # unplanned model-state movement: the derived accounting must see it
        scratch = Node("scratch", NodeArtifactCache(world["temp"] / "poison-cache"))
        scratch.ledger.record({"event": HOST_MIRROR_STAGING_EVENT,
                               "participant_id": "scratch",
                               "artifact_id": "mirrored-state", "bytes": 8192})
        scratch.ledger.record({"event": UNPLANNED_MODEL_STATE_MOVEMENT_EVENT,
                               "participant_id": "scratch",
                               "artifact_id": "unplanned-state", "bytes": 4096})
        poisoned = dict(world)
        poisoned["nodes"] = {**world["nodes"], "scratch": scratch}
        accounting = staging_accounting(poisoned)
        if accounting["unexplained_persistent_host_mirror_bytes"] < 8192 \
                or accounting["unplanned_steady_state_model_state_movement_bytes"] < 4096:
            raise AssertionError("poisoned staging records derived zero")

    def coverage_derivation_is_non_vacuous():
        # poison a requirements copy so one participant requires both whole
        # upstream shards: the derived coverage invariants must go nonzero
        poisoned = json.loads(json.dumps(world["requirements"]))
        shards = sorted(name for name in world["objects"]
                        if name.endswith(".safetensors"))
        participant = poisoned["participants"][0]
        participant["required_artifacts"] = [
            record for record in participant["required_artifacts"]
            if record["origin"].get("source_object") not in shards
        ] + [{
            "kind": "byte_range",
            "content_digest": "sha256:" + "0" * 64,
            "length": len(world["objects"][shard]),
            "requirement_class": "assigned_logical_state",
            "satisfies_logical_state_ids": ["state.layer.0"],
            "origin": {"source_object": shard, "byte_start": 0,
                       "byte_end": len(world["objects"][shard])},
        } for shard in shards]
        derived = derive_coverage_invariants(
            poisoned, objects=world["objects"],
            total_weight=checkpoint_weight_bytes(world["catalog"]))
        if derived["unexplained_full_model_dependency"] <= 0:
            raise AssertionError("poisoned coverage derived zero full-model bytes")
        if derived["participant_requires_complete_model_repository"] < 1:
            raise AssertionError("poisoned coverage derived zero complete participants")

    def locality_cannot_override_qualification():
        planner = build_admission_planner(world)
        for candidate_id, entry in planner.gate_ledger().items():
            if candidate_id != world["v5"]["candidate_id"] and entry["admissible"]:
                raise AssertionError(f"inapplicable candidate admitted: {candidate_id}")

    def v5_authority_tamper_is_fail_closed():
        # byte-tamper a pinned authority file in a throwaway repo root: the
        # verification must detect the drift (never a path artifact)
        import shutil
        import tempfile as _tempfile
        import issue117_applicability as applicability
        with _tempfile.TemporaryDirectory() as temp:
            relative = ("docs/qualification/gemma4-12b-it-v5-campaign-110/b/"
                        "holdout-adjudication.json")
            target = Path(temp) / relative
            target.parent.mkdir(parents=True)
            shutil.copyfile(ROOT / relative, target)
            data = json.loads(target.read_text())
            data["tampered"] = True
            target.write_text(json.dumps(data))
            verify_v5_authority(Path(temp), files={
                relative: applicability.V5_AUTHORITY_FILES[relative]})

    def fixture_digest_drift():
        tampered = json.loads(fixture_path.read_text())
        tampered["cases"][0]["case"]["prompt_text"] += " tampered"
        validate_fixture_document(tampered)

    controls.expect_failure(
        "whole_model_requirement_injection", whole_model_injection,
        "REQUIRES_COMPLETE_MODEL_REPOSITORY")
    try:
        unrelated_acquisition_accounting()
        controls.record("unrelated_artifact_acquisition_fails_accounting",
                        True, "accounting derived 4096 unrelated bytes",
                        "accounting counts unrelated bytes")
    except Exception as error:
        controls.record("unrelated_artifact_acquisition_fails_accounting",
                        False, str(error), "accounting counts unrelated bytes")
    controls.expect_failure(
        "coordinator_bulk_byte_injection", coordinator_bulk_bytes, "SOURCE_UNAUTHORIZED")
    controls.expect_failure(
        "unverified_local_artifact_earns_no_credit", unverified_local_credit,
        "INTEGRITY_DIGEST_MISMATCH")
    controls.expect_failure(
        "corrupt_cache_object_fails_closed", corrupt_cache_object, "CACHE_OBJECT_TAMPERED")
    controls.expect_failure(
        "unauthorized_source_rejected", unauthorized_source, "SOURCE_UNAUTHORIZED")
    controls.expect_failure(
        "source_descriptor_drift_rejected", source_descriptor_drift, "SOURCE_UNAUTHORIZED")
    controls.expect_pass(
        "missing_path_evidence_yields_unranked_not_guessed",
        missing_path_evidence_yields_unranked,
        "admissible candidate stays FEASIBLE_UNRANKED without evidence")
    controls.expect_pass(
        "changed_executor_cannot_inherit_qualification",
        changed_executor_cannot_inherit,
        "changed executor resolves QUALIFICATION_NOT_APPLICABLE and is not admitted")
    controls.expect_failure(
        "lying_subject_digest_is_control_plane_misuse", lying_subject_digest_is_refused,
        "does not match its own subject")
    controls.expect_pass(
        "accepted_v5_qualification_subject_provenance_recovered",
        accepted_subject_recovery_is_loadable_and_independent,
        "accepted subject loads from byte-pinned historical evidence with the "
        "accepted terminal adjudication identity and no candidate machinery")
    controls.expect_failure(
        "accepted_subject_evidence_tampering_is_fail_closed",
        accepted_subject_evidence_tampering_is_fail_closed,
        "drifted")
    controls.expect_failure(
        "changed_execution_producer_requires_requalification",
        changed_execution_producer_cannot_reapply_audit,
        "R6_SUCCESSOR_REQUALIFICATION_REQUIRED")
    controls.expect_pass(
        "fence_ledger_derivation_is_non_vacuous", fence_derivation_is_non_vacuous,
        "poisoned committed-result ledger derives a nonzero invalid counter")
    controls.expect_pass(
        "staging_ledger_derivation_is_non_vacuous", staging_derivation_is_non_vacuous,
        "poisoned staging records derive nonzero mirror/movement bytes")
    controls.expect_pass(
        "coverage_derivation_is_non_vacuous", coverage_derivation_is_non_vacuous,
        "poisoned requirements derive nonzero whole-model dependency invariants")
    controls.expect_pass(
        "locality_cannot_override_qualification",
        locality_cannot_override_qualification,
        "no inapplicable candidate is ever admitted")
    controls.expect_failure(
        "v5_authority_byte_tampering_is_fail_closed", v5_authority_tamper_is_fail_closed,
        "drifted")
    controls.expect_failure(
        "fixture_integrity_is_fail_closed", fixture_digest_drift, "mismatch")
    return controls


def derive_unrelated_bytes_for(events, *, required: set[str]) -> int:
    return sum(event["bytes"] for event in events
               if event["event"] == "ACQUIRED" and event["artifact_id"] not in required)


def run_fencing(world, fixture_document) -> dict[str, Any]:
    fence = ResultFence(
        contract_id="inferswarm.issue117.serving-contract/1",
        session_id="issue117-cpu-session-1",
        epoch=world["plan"]["epoch"],
        realization_id=f"realization-{world['plan']['plan_digest'][:16]}",
        plan_digest=world["plan"]["plan_digest"],
        operations=("prefill", "decode"),
    )
    case_ids = sorted(entry["case"]["case_id"] for entry in fixture_document["cases"])
    base = {"contract_id": fence.authority["contract_id"],
            "session_id": fence.authority["session_id"],
            "epoch": fence.authority["epoch"],
            "realization_id": fence.authority["realization_id"],
            "plan_digest": fence.authority["plan_digest"]}
    committed = 0
    for position, case_id in enumerate(case_ids):
        for operation in ("prefill", "decode"):
            fence.commit({**base, "operation": operation, "position": position,
                          "request_identity": case_id})
            committed += 1

    def attempt(**overrides):
        fence.commit({**base, "operation": "decode",
                      "position": len(case_ids), "request_identity": case_ids[0],
                      **overrides})

    negatives = []
    for name, overrides, expected in (
            ("stale_position", {"position": 0}, "WRONG_POSITION"),
            ("wrong_session", {"session_id": "other"}, "WRONG_SESSION"),
            ("wrong_plan", {"plan_digest": "other"}, "WRONG_PLAN"),
            ("wrong_epoch", {"epoch": 99}, "WRONG_EPOCH"),
            ("wrong_position_gap", {"position": 7}, "WRONG_POSITION"),
            ("unknown_operation", {"operation": "speculative"}, "UNKNOWN_OPERATION")):
        try:
            attempt(**overrides)
            negatives.append({"control": name, "failed_closed": False,
                              "reason": "COMMITTED", "matched": False})
        except Exception as error:
            negatives.append({"control": name, "failed_closed": True,
                              "reason": str(error).split(":")[0],
                              "matched": expected in str(error)})
    return {
        "authority": fence.authority,
        "committed_results": committed,
        "committed_result_records": list(fence.committed_results),
        "rejected_attempt_records": list(fence.rejections),
        "fixture_case_count": len(case_ids),
        "summary": fence.summary(),
        "negative_controls": negatives,
        "all_negatives_failed_closed": all(
            entry["failed_closed"] and entry["matched"] for entry in negatives),
    }


def run_campaign(out_dir: Path | None = None, *, fixture_path: Path | None = None) -> dict[str, Any]:
    fixture_path = fixture_path or FIXTURE_PATH
    fixture_document = json.loads(fixture_path.read_text())
    validate_fixture_document(fixture_document)

    authority = verify_v5_authority(ROOT)
    audit = canonical_issue117_audit(ROOT)

    import shutil
    # A fixed working root keeps the retained evidence byte-deterministic:
    # source endpoints and cache paths enter the frozen documents, so a
    # random temp path would change evidence bytes per machine. The campaign
    # is a serial orchestrator process and is not concurrency-safe by design.
    working = Path(tempfile.gettempdir()) / "issue117-cpu-campaign"
    shutil.rmtree(working, ignore_errors=True)
    working.mkdir(parents=True)
    try:
        world = build_world(working)
        strategy = world["strategy"]

        guard_participant_exact(
            world["requirements"],
            total_model_weight_bytes=checkpoint_weight_bytes(world["catalog"]))

        cold_planner = build_admission_planner(world)
        decision = cold_planner.rank()
        accounting = cold_planner.account_transfer_events()
        require(decision["selected_candidate_id"] == world["v5"]["candidate_id"],
                "the V5-shaped fixture candidate must win through the ordinary gates")

        cold = cold_acquisition(world)
        witnesses = materialize_and_reconcile(world, coordinator=world["coordinator"],
                                              nodes=world["nodes"])
        warm = warm_restart(world)
        require(warm["witnesses"] == witnesses, "warm restart changed the witnesses")
        mutation = locality_mutation(world, decision)
        require(mutation["all_gates_unchanged"] and mutation["economics_changed"],
                "locality mutation must change economics and nothing else")
        fence = run_fencing(world, fixture_document)
        require(fence["all_negatives_failed_closed"], "fence negatives did not fail closed")

        zero = derive_zero_invariants(world, decision=decision, accounting=accounting,
                                      cold=cold, warm=warm, mutation=mutation,
                                      fence_summary=fence["summary"], audit=audit)
        unexpected = {name: value for name, value in zero.items() if value != 0}
        if unexpected:
            raise AssertionError(f"zero-invariants not zero: {unexpected}")

        controls = run_negative_controls(world, fixture_path)
        if not controls.all_failed_closed:
            failed = [entry for entry in controls.results
                      if not (entry["failed_closed"] and entry["matched"])]
            raise AssertionError(f"negative controls did not fail closed: {failed}")

        strategy_doc = strategy.frozen_document(
            world["candidates"], capacity_model=world["capacity"])
        source_side_bytes = (world["catalog"]["source_bytes_hashed"]
                             + world["manifest"]["source_bytes_read"])
        from issue117_accepted_subject import accepted_v5_qualification_record
        accepted_record = accepted_v5_qualification_record(ROOT)
        # Preservation guard: the accepted #118 canonical summary is
        # immutable historical terminal evidence. The campaign never writes
        # it; it must exist and be byte-exact the accepted #118 state
        # (deletion is also refused here, not just drift).
        committed_summary = (ROOT / AREA / "evidence" / "canonical-summary.json")
        if not committed_summary.is_file():
            raise AssertionError(
                "the accepted #118 canonical-summary.json is missing; "
                "historical terminal evidence cannot be deleted")
        if sha(committed_summary) != ACCEPTED_118_CANONICAL_SUMMARY_SHA256:
            raise AssertionError(
                "the accepted #118 canonical-summary.json has drifted from "
                "its preserved historical bytes; current state belongs in "
                "the additive recovery record, never in a rewrite")
        # Additive current-state record (PR #120): states the recovered
        # provenance WITHOUT rewriting the accepted #118 terminal evidence.
        summary = {
            "schema": "inferswarm.issue117.current-gate-state/1",
            "classification": "V5_QUALIFICATION_SUBJECT_PROVENANCE_RECOVERED",
            "accepted_subject_digest":
                accepted_record["qualification_subject_digest"],
            "checkpoint_authority": "RECOVERED",
            "qualification_subject": "RECOVERED",
            "issue117_previous_freeze_disposition":
                "ISSUE117_IMPLEMENTATION_FREEZE_BLOCKED",
            "current_issue117_state":
                "ISSUE117_IMPLEMENTATION_FREEZE_PENDING_RE_EVALUATION",
            "physical_preflight_executed": False,
            "physical_arms_executed": False,
            "gate": "issue #117 CPU fixture campaign",
            "accepted_inferswarm_base": BASE,
            "accepted_freetoken_research_head": authority["accepted_freetoken_research_head"],
            "frozen_integration_producer": FROZEN_INTEGRATION_PRODUCER,
            "fixture_digest": fixture_document["fixture_digest"],
            "fixture_case_count": fixture_document["case_count"],
            "candidate_count": len(world["candidates"]),
            "selected_candidate_id": decision["selected_candidate_id"],
            "qualification_record_id": world["qualification_record"]["qualification_record_id"],
            "qualification_record_scope": world["qualification_record"]["scope"],
            "qualification_adjudication_identity":
                world["qualification_record"]["authority"]["terminal_adjudication_sha256"],
            "accepted_118_canonical_summary_sha256":
                "sha256:" + ACCEPTED_118_CANONICAL_SUMMARY_SHA256,
            "checkpoint_identity_model": (
                "checkpoint_authority_sha256 is a retained repeated value and "
                "catalog_content_digest is a mechanical content identity; "
                "they are separate named identities, neither establishes an "
                "independent qualification authority"),
            "source_side_model_bytes_hashed": source_side_bytes,
            "coordinator_bulk_bytes_observed": cold["coordinator_bytes_observed"],
            "cold_transferred_bytes": {
                participant: entry["transferred_bytes"]
                for participant, entry in cold["per_participant"].items()},
            "warm_restart_model_weight_transfer_bytes":
                warm["warm_restart_model_weight_transfer_bytes"],
            "witness_digests": {participant: entry["witness_digest"]
                                for participant, entry in witnesses.items()},
            "negative_controls_passed": len(controls.results),
            "fence_committed_results": fence["committed_results"],
            "fence_rejections": fence["summary"]["fence_rejections"],
            "zero_invariant_count": len(zero),
            "cpu_fixture_disposition": "ISSUE117_CPU_FIXTURE_PASS",
            "physical_arms_pending": [
                "Arm A: V5 execution-math bridge on the fabric (192/192 FP32 row identity)",
                "Arm B: physical cold acquisition/realization on inferswarm01/inferswarm03",
                "Arm C: ordinary external-Coordinator serving vs direct control",
                "Arm D: physical warm restart with zero model-weight transfer",
                "physical preflight with real per-CU GPU/runtime identities",
            ],
            "non_claims": [
                "No statistical qualification claim; V5 thresholds are not reused.",
                "No physical execution, transfer, serving, or performance claim.",
                "No public planner, artifact, path, or wire schema is frozen.",
                "No consumed h109 holdout material is used as new evidence.",
                "The synthetic capacity model proves machinery, not hardware limits.",
                "The qualification record is fixture-scoped. The accepted V5 "
                "qualification subject was recovered independently from "
                "byte-pinned historical evidence "
                "(V5_QUALIFICATION_SUBJECT_PROVENANCE_RECOVERED); the CPU "
                "fixture does not use or depend on it.",
                "The producer-delta zone closure statically resolves every "
                "dynamic import mechanism: resolved in-repository targets are "
                "zone members hashed at both producers; external module "
                "imports are bound to accepted runtime identities; find_spec "
                "probes are allowlisted availability probes that execute no "
                "target bytes. Unresolved dynamic targets or actual "
                "unresolved in-repository module imports fail the closure "
                "closed. Residual non-claim: probe-gated backend selection "
                "(sgl_kernel/vllm) is admission logic; the accepted V5 dense "
                "path selects none of the probed backends.",
                "Source-side catalog/manifest construction hashes and reads "
                "model bytes by design; only the Coordinator/planning waist "
                "is zero-bulk-byte.",
            ],
        }
        documents = {
            "strategy.json": strategy_doc,
            "planner-decision.json": decision,
            "requirements.json": world["requirements"],
            "cold-acquisition.json": {**cold,
                                      "capacity_model": world["capacity_model"],
                                      "transition_accounting": accounting},
            "materialization-witnesses.json": witnesses,
            "warm-restart.json": warm,
            "locality-mutation.json": mutation,
            "fencing.json": fence,
            "negative-controls.json": {"controls": controls.results},
            "zero-invariants.json": zero,
            "purity-audit.json": planner_purity_audit(
                ROOT / "scripts" / "issue117_planner.py", PURITY_TOKENS),
            "applicability-audit.json": audit,
            "qualification-record.json": world["qualification_record"],
            "v5-qualification-subject-recovery.json": summary,
        }
        documents["producer-hashes.json"] = {path: sha(ROOT / path) for path in PRODUCERS}
    finally:
        shutil.rmtree(working, ignore_errors=True)
    if out_dir is not None:
        for name, document in documents.items():
            write_canonical_json(out_dir / name, document)
        write_manifest(out_dir)
    return documents


def write_manifest(out_dir: Path) -> None:
    entries = {str(AREA / "evidence" / name): sha(out_dir / name)
               for name in EVIDENCE_FILES if (out_dir / name).is_file()}
    for name in COMMITTED_EVIDENCE_FILES:
        committed = ROOT / AREA / "evidence" / name
        if committed.is_file():
            entries[str(AREA / "evidence" / name)] = sha(committed)
    entries.update({path: sha(ROOT / path) for path in PRODUCERS})
    for path in (str(AREA / "METHODOLOGY.md"), str(AREA / "README.md"),
                 str(AREA / "METHODOLOGY-ARM-C-RETRY.md"),
                 str(AREA / "CHECKPOINT-AUTHORITY-BLOCKER.md"),
                 ".github/workflows/ci.yml"):
        if (ROOT / path).is_file():
            entries[path] = sha(ROOT / path)
    (out_dir / "MANIFEST.sha256").write_text(
        "".join(f"{digest}  {path}\n" for path, digest in sorted(entries.items())))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / AREA / "evidence")
    parser.add_argument("--fixture", type=Path, default=None)
    args = parser.parse_args()
    documents = run_campaign(args.out, fixture_path=args.fixture)
    print(documents["v5-qualification-subject-recovery.json"]
          ["current_issue117_state"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

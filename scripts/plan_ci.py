#!/usr/bin/env python3
"""Deterministic repository-owned CI planner (Issue #148).

Maps an explicit set of changed paths to a machine-readable CI plan:
which registered CI groups must run for this change, whether the plan
had to escalate to full regression, and why. The planner is pure
standard library, deterministic (same inputs -> byte-identical plan),
and fail-closed: any changed path it cannot classify selects full
regression rather than a narrow plan.

The planner is the single selection authority for conditional CI
groups. A third-party action never decides which correctness suites
run. The registry lives in ``ci_groups.json`` next to this script;
``--emit-registry`` regenerates a canonical registry from the mapping
tables in this file so the two can never drift apart (a unit test
asserts this).

Usage::

    # PR mode: classify a changed-path set (one path per line on stdin)
    git diff --name-only origin/main...HEAD | python3 scripts/plan_ci.py --mode pr

    # Explicit paths on the command line
    python3 scripts/plan_ci.py --mode pr -- path1 path2 ...

    # Force full regression (push-to-main, manual, or fail-closed escalation)
    python3 scripts/plan_ci.py --mode full

    # Ask what a path would select
    python3 scripts/plan_ci.py --mode pr -- docs/README.md

    # Validate the registry and plan schema
    python3 scripts/plan_ci.py --self-check

Plan JSON shape (stable contract)::

    {
      "mode": "targeted" | "full",
      "groups": [...],            # sorted unique group ids to run
      "full_regression": bool,
      "reason": [...],            # sorted human-readable justification lines
      "planner": "scripts/plan_ci.py",
      "planner_version": 1,
      "schema": "ci-plan/1"
    }

Fail-closed rules (any of these forces ``mode=full``):

* a changed path is not classified by any rule (unknown surface);
* the planner's own source, the group registry, or the planner tests
  change (the selection authority itself moved);
* CI workflow files change;
* the canonical dependency authority (``requirements-test.txt``,
  bootstrap/doctor scripts) changes;
* repository-level authority surfaces change (finalizer, status
  syncer, evidence manifest tooling, evidence-manifest docs);
* ``--mode full`` was requested;
* the changed-path input is malformed (duplicate paths, empty lines,
  absolute paths, ``..`` traversal, whitespace, trailing slash) —
  malformed input is never silently normalized into a narrow plan.

Always-on groups (``repo-integrity``) are included in every plan; on
full regression every registered group is included.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = Path(__file__).resolve().parent / "ci_groups.json"

PLANNER_VERSION = 1
PLAN_SCHEMA = "ci-plan/1"

# Path-pattern style literals (exact file or directory prefix; a
# pattern ending in "/" matches that directory subtree).
ALWAYS_ON_GROUPS = ["repo-integrity"]

# The CI-selection authority itself. Any change here re-runs everything.
SELF_AUTHORITY_PATHS = [
    "scripts/plan_ci.py",
    "scripts/ci_groups.json",
    "tests/test_plan_ci.py",
]

# CI workflow files: a workflow change can alter how any group runs.
CI_WORKFLOW_PREFIXES = [".github/workflows/"]

# Dependency/environment authority: consumed by every suite.
ENV_AUTHORITY_PATHS = [
    "requirements-test.txt",
    "scripts/bootstrap_test_env.py",
    "scripts/check_test_env.py",
]

# Repository-wide authority surfaces: finalizer, generated status,
# evidence manifest lifecycle, project status authority docs.
REPO_AUTHORITY_PATHS = [
    "scripts/finalize_repository.py",
    "scripts/sync_project_status.py",
    "docs/finalization.md",
    "docs/status-maintenance.md",
    "docs/evidence-manifests.md",
    "docs/project-status.json",
    # Issue #246 retention authority: the per-module audit, the
    # retired-lineage evidence pins (a pin change is how retired
    # accepted evidence would be rewritten), the retired-test-row
    # tombstones (how a deleted test leaves an accepted manifest), and
    # their checker.
    "docs/ci/test-retention-audit.json",
    "docs/ci/retired-lineage-pins.sha256",
    "docs/ci/retired-test-rows.json",
    "scripts/check_ci_test_retention.py",
]

# Shared test infrastructure consumed by (potentially) every family.
SHARED_TEST_PATHS = [
    "conftest.py",
    "tests/__init__.py",
]


def _sort_unique(items):
    return sorted(set(items))


# ---------------------------------------------------------------------------
# Group registry
# ---------------------------------------------------------------------------

# test modules (unittest names under tests/) executed by each group.
# "docs/README.md" style entries below use path patterns instead.
GROUP_TEST_MODULES = {
    "repo-integrity": [
        # Always-on: schema/status/finalizer/manifest/hygiene semantics.
        "test_project_status",
        "test_finalize_repository",
        "test_evidence_manifest_lifecycle",
        "test_issue131_cpu_test_env",
        "test_plan_ci",
        "test_run_full_cpu_suite",
        # Issue #246: retention audit + retired-lineage integrity.
        "test_ci_test_retention",
    ],
    "issue-74-79": [
        "test_issue74_methodology",
    ],
    "issue-83-95": [
        "test_issue83_semantic_contract",
        "test_issue93_numerical_core_doctrine",
        "test_issue108_post_v4_statistical_metric_doctrine",
    ],
    "issue-109-110": [
        "test_issue109_v5_methodology",
        "test_issue109_v5_thresholds",
        "test_issue109_v5_methodology_freeze",
        "test_issue110_v5_custody_handoff",
        "test_issue110_terminal_report_decimals",
        # Issue #246: the consumed-holdout non-reuse guard extracted from the
        # retired #168/#172/#182 and V3 suites (V5/#110 doctrine).
        "test_consumed_holdout_boundary",
    ],
    "issue-117-133": [
        "test_issue117_provenance",
        "test_issue117_accepted_subject",
        "test_issue117_arm_a_retention",
        "test_issue117_arm_b_retention",
        "test_issue117_arm_c_retention",
        "test_issue133_physical_execution_retention",
        "test_issue184_final_closure",
    ],
    # Issue #213: campaign gate ordering / exact-head suite receipts.
    "issue-213-gate-ordering": [
        "test_issue213_campaign_gate_ordering",
        # Issue #226: hosted Final CPU Validation CI (successor doctrine
        # in the same orchestration line; envelope validates against the
        # same #213 machinery).
        "test_issue226_final_validation_ci",
    ],
    "issue-187-r7a": [
        "test_issue187_r7a",
    ],
    "issue-209-r7b": [
        "test_issue209_r7b",
    ],
    # Issue #222 R7-C: current-fleet physical feasibility (capacity prerequisite).
    "issue-222-r7c": [
        "test_issue222_r7c",
    ],
    "issue-99-103": [
        "test_issue99_artifact_core",
        "test_issue99_proof",
        "test_issue101_orchestration",
        "test_issue101_proof",
        "test_issue103_planner",
        "test_issue200_r8f_source_policy",
        "test_issue200_r8f_proof",
    ],
    # Issue #246 split the former monolithic ``vulkan-v0-b`` bucket by
    # current dependency/authority boundary (import-graph component).
    # Current R8-I Qwen heterogeneous-Vulkan qualification authority.
    "r8i-qwen-qualification": [
        "test_issue237_r8i_methodology",
        "test_issue244_r8i5_v340l_import",
        # Issue #248 R8-I3A: reference-arm Vulkan row nondeterminism
        # diagnosis (diagnostic-only follow-up to the accepted #241
        # blocked terminal; same R8-I qualification lineage).
        "test_issue248_diagnostic",
    ],
    # R8-A/B Qwen static lineage (R8-A is the living frontier reference;
    # R8-B fixtures feed R8-I).
    "r8-qwen-lineage": [
        "test_issue189_r8a",
        "test_issue191_r8b",
    ],
    # CPU-only methodology gates not surfaced as CI steps on main; they
    # are part of full regression so no coverage is lost.
    "issue-115-cleanup": [
        "test_issue115_cleanup_retention",
    ],
}

# Issue #246 lifecycle rule: every group declares the current invariant
# (owner) it protects. A group exists because it protects current
# contracts, reachable regressions, or current evidence integrity —
# never for lineage continuity alone. Per-module classification lives
# in docs/ci/test-retention-audit.json (checked by
# scripts/check_ci_test_retention.py).
GROUP_INVARIANTS = {
    "repo-integrity":
        "Repository authority: canonical CPU environment, generated status, "
        "deterministic finalization, evidence-manifest lifecycle, CI "
        "planner/registry/workflow parity, full-suite identity, retention "
        "audit, exact retired-test-row tombstones, and retired-lineage "
        "evidence integrity.",
    "issue-74-79":
        "Shared qualification methodology core (issue74_methodology is "
        "imported by every later qualification line, including R8-I).",
    "issue-83-95":
        "Semantic/numerical-core and post-v4 statistical doctrine consumed "
        "by the accepted V5 contract and current R8-I comparator semantics.",
    "issue-109-110":
        "Accepted V5 dense Gemma qualification capability: methodology "
        "freeze, thresholds, holdout custody hand-off, and the consumed-"
        "holdout non-reuse boundary (h86/h109 never become successor "
        "inputs).",
    "issue-117-133":
        "Accepted #117 Arm A-C subject/arm evidence bindings consumed by the "
        "V5 subject lineage, and the #184 A-E closure of the living status "
        "record.",
    "issue-213-gate-ordering":
        "Current campaign gate-ordering doctrine: exact-head suite "
        "receipts and hosted Final CPU Validation.",
    "issue-187-r7a":
        "R7-A DeepSeek static census authority feeding the open R7 track.",
    "issue-209-r7b":
        "R7-B DeepSeek physical-gate record pending maintainer acceptance.",
    "issue-222-r7c":
        "R7-C current-fleet capacity prerequisite for the R7 track.",
    "issue-99-103":
        "Accepted acquisition, orchestration, and locality-planning "
        "capabilities plus the R8-F source-policy seam.",
    "r8i-qwen-qualification":
        "Current R8-I Qwen heterogeneous-Vulkan qualification authority: "
        "methodology freeze, holdout custody, comparator semantics, and the "
        "accepted R8-I4 V340L import. Current R8/Qwen work joins this group.",
    "r8-qwen-lineage":
        "R8-A frontier census and the R8-B evidence consumed by R8-I.",
    "issue-115-cleanup":
        "V5 cleanup retention manifest and the no-plaintext/secret custody "
        "guard.",
}

# Path -> group selection rules. Order does not matter; a path may
# select multiple groups. Patterns are exact paths or subtree
# prefixes ending in "/". Unlisted paths are UNCLASSIFIED and select
# full regression (fail closed) unless a prefix rule matches.
#
# Selection model per family F with owned directory prefix P:
#   - changes under P select group F (docs, evidence, scripts, tests);
#   - a test-module change additionally selects every family whose
#     module list contains that module (a test module is the family's
#     own regression surface, and its imports couple it to producers);
#   - a script change selects every family whose test modules import
#     it, directly or transitively (Issue #246 import-closure fan-out,
#     enforced by tests/test_plan_ci.py TestImportClosureFanout);
#   - scripts/ and tests/ are shared namespaces: any script or test
#     NOT under a family prefix and NOT the module-bound script of a
#     family is unclassified -> full regression (fail closed).
PATH_GROUPS = {
    # Repository-wide authority
    "scripts/sync_project_status.py": ["repo-integrity"],
    "scripts/finalize_repository.py": ["repo-integrity"],
    "scripts/issue137_manifest.py": ["repo-integrity"],
    "scripts/check_phase0_workloads.py": ["repo-integrity"],
    "scripts/check_ci_test_retention.py": ["repo-integrity"],  # + authority -> full
    "docs/ci/": ["repo-integrity"],
    "docs/project-status.json": ["repo-integrity"],
    "docs/status-maintenance.md": ["repo-integrity"],
    # Living hardware inventory receipts (Issue #196): raw read-only
    # scan captures backing the living PCIe slot ledger; superseded by
    # later refreshes, never retained experiment evidence.
    "docs/hardware/current-inventory/": ["repo-integrity"],
    "docs/finalization.md": ["repo-integrity"],
    "docs/evidence-manifests.md": ["repo-integrity"],
    "scripts/README.md": ["repo-integrity"],
    "tests/test_project_status.py": ["repo-integrity"],
    "tests/test_finalize_repository.py": ["repo-integrity"],
    "tests/test_evidence_manifest_lifecycle.py": ["repo-integrity"],
    "tests/test_issue131_cpu_test_env.py": ["repo-integrity"],
    "tests/test_issue187_r7a.py": ["issue-187-r7a"],
    "tests/test_issue209_r7b.py": ["issue-209-r7b"],
    "tests/test_issue222_r7c.py": ["issue-222-r7c"],
    "scripts/bootstrap_test_env.py": ["repo-integrity"],   # + env authority -> full
    "scripts/check_test_env.py": ["repo-integrity"],       # + env authority -> full
    "requirements-test.txt": ["repo-integrity"],           # + env authority -> full

    # Issue family surfaces
    "scripts/issue74_methodology.py": [
        "issue-109-110",
        "issue-117-133",
        "issue-74-79",
        "issue-83-95",
        "issue-99-103",
        "r8i-qwen-qualification"],
    "scripts/commit_issue74_holdout.py": ["issue-74-79"],
    "scripts/seal_issue74_holdout.py": ["issue-74-79"],
    "scripts/generate_issue74_corpora.py": ["issue-74-79", "issue-109-110"],
    "scripts/hash_issue74_artifacts.py": ["issue-74-79"],
    "scripts/select_issue74_margin_stress.py": ["issue-74-79"],
    "scripts/select_issue76_margin_stress_v2.py": ["repo-integrity"],
    "scripts/generate_issue76_stress_pool_v2.py": ["repo-integrity"],
    "scripts/issue79_v2_thresholds.py": ["repo-integrity"],
    "scripts/verify_issue79_v2_unseal.py": ["repo-integrity"],
    "docs/qualification/gemma4-12b-it-v1/": ["issue-74-79"],
    "docs/qualification/gemma4-12b-it-v2/": ["repo-integrity"],

    "scripts/issue83_first_divergence.py": ["issue-83-95"],
    "scripts/issue86_v3_methodology.py": ["repo-integrity"],
    "scripts/issue86_v3_thresholds.py": ["repo-integrity"],
    "scripts/issue90_post_v3_diagnosis.py": ["repo-integrity"],
    "scripts/issue95_v4_contract.py": ["repo-integrity"],
    "scripts/issue95_v4_methodology.py": [
        "issue-83-95",
        "issue-109-110",
        "r8i-qwen-qualification"],
    "scripts/issue95_v4_thresholds.py": ["repo-integrity"],
    "scripts/verify_issue86_v3_unseal.py": ["repo-integrity"],
    "scripts/verify_issue95_v4_unseal.py": ["repo-integrity"],
    "scripts/select_issue86_margin_stress_v3.py": ["repo-integrity"],
    "scripts/select_issue95_margin_stress_v4.py": ["repo-integrity"],
    "scripts/generate_issue86_corpora.py": ["repo-integrity"],
    "scripts/generate_issue95_corpora.py": ["repo-integrity"],
    "scripts/commit_issue86_holdout.py": ["repo-integrity"],
    "scripts/commit_issue86_stress_selection.py": ["repo-integrity"],
    "scripts/commit_issue95_holdout.py": ["repo-integrity"],
    "scripts/commit_issue95_stress_selection.py": ["repo-integrity"],
    "scripts/build_issue86_disjointness.py": ["repo-integrity"],
    "scripts/build_issue86_schemas.py": ["repo-integrity"],
    "scripts/build_issue95_disjointness.py": ["repo-integrity"],
    "scripts/build_issue95_schemas.py": ["repo-integrity"],
    "scripts/issue105_post_v4_core_diagnosis.py": ["repo-integrity"],
    "scripts/issue108_post_v4_statistical_metric_doctrine.py": [
        "issue-83-95",
        "issue-109-110"],
    "docs/adr/": ["issue-83-95"],  # ADRs decide; doctrine changes are broad
    "docs/architecture/": ["issue-83-95"],
    "docs/qualification/gemma4-12b-it-semantic-83/": ["issue-83-95"],
    "docs/qualification/gemma4-12b-it-v3/": ["repo-integrity"],
    "docs/qualification/gemma4-12b-it-v3-campaign-88/": ["repo-integrity"],
    "docs/qualification/gemma4-12b-it-v4/": ["repo-integrity"],
    "docs/qualification/gemma4-12b-it-post-v3-envelope-diagnosis/":
        ["repo-integrity"],
    "docs/qualification/gemma4-12b-it-post-v4-core-diagnosis/":
        ["repo-integrity", "issue-83-95"],
    "docs/qualification/post-v3-numerical-core-doctrine/": ["issue-83-95",
        "issue-109-110"],  # test_issue109_v5_methodology also pins it

    "scripts/issue109_v5_contract.py": ["issue-109-110"],
    "scripts/issue109_v5_methodology.py": ["issue-109-110"],
    "scripts/issue109_v5_methodology_freeze.py": ["issue-109-110"],
    "scripts/issue109_v5_thresholds.py": ["issue-109-110"],
    "scripts/issue110_v5_custody.py": ["issue-109-110"],
    "scripts/issue110_v5_thresholds.py": ["issue-109-110"],
    "scripts/verify_issue109_v5_unseal.py": ["issue-109-110"],
    "scripts/commit_issue109_holdout.py": ["issue-109-110"],
    "scripts/commit_issue109_stress_selection.py": ["issue-109-110"],
    "scripts/select_issue109_margin_stress_v5.py": ["issue-109-110"],
    "scripts/generate_issue109_corpora.py": ["issue-109-110"],
    "scripts/build_issue109_build_audit.py": ["issue-109-110"],
    "scripts/build_issue109_disjointness.py": ["issue-109-110"],
    "scripts/build_issue109_historical_exclusion.py": ["issue-109-110"],
    "scripts/build_issue109_schemas.py": ["issue-109-110"],
    "scripts/validate_issue109_prerequisites.py": ["issue-109-110"],
    # Accepted V5 methodology/campaign evidence. The #109/#110 suites
    # consume these trees directly, and Issue #117 reconstructs/binds
    # the accepted V5/#110 subject evidence, so both lineages run.
    "docs/qualification/gemma4-12b-it-v5/": ["issue-109-110", "issue-117-133"],
    "docs/qualification/gemma4-12b-it-v5-campaign-110/": ["issue-109-110",
        "issue-117-133"],
    # Issue #115 cleanup producers/retained evidence (narrower than the
    # campaign-110 tree: test_issue115_cleanup_retention reads exactly
    # this subtree; classification unions with the parent rule).
    "docs/qualification/gemma4-12b-it-v5-campaign-110/cleanup/": ["issue-115-cleanup",
        "issue-109-110", "issue-117-133"],
    "docs/qualification/post-v4-statistical-metric-doctrine/": ["issue-109-110"],

    # Shared qualification lineage evidence consumed by #117 subject
    # reconstruction (test_issue117_accepted_subject / applicability /
    # preflight read these campaign trees directly).
    "docs/qualification/gemma4-12b-it-v2-campaign-81/":
        ["repo-integrity", "issue-117-133"],
    "docs/qualification/gemma4-12b-it-v4-campaign-97/":
        ["repo-integrity", "issue-117-133"],

    # Issue #117 producer scripts and evidence tree.
    "scripts/issue117_accepted_subject.py": ["issue-117-133"],
    "scripts/issue117_applicability.py": ["issue-117-133"],
    "scripts/issue117_arm_a_evidence.py": ["issue-117-133"],
    "scripts/issue117_arm_b_correction_build.py": ["repo-integrity"],
    "scripts/issue117_arm_b_evidence.py": ["repo-integrity"],
    "scripts/issue117_arm_b_observe_hosts.py": ["repo-integrity"],
    "scripts/issue117_arm_b_transport_audit_build.py": ["repo-integrity"],
    "scripts/issue117_arm_c_authority_audit.py": ["repo-integrity"],
    "scripts/issue117_arm_c_blocker_fakeroot.py": ["repo-integrity"],
    "scripts/issue117_arm_c_blocker_reducer.py": ["repo-integrity"],
    "scripts/issue117_arm_c_client.py": ["repo-integrity"],
    "scripts/issue117_arm_c_decoded_bytes.py": ["repo-integrity"],
    "scripts/issue117_arm_c_direct.py": ["repo-integrity"],
    "scripts/issue117_arm_c_evidence.py": ["repo-integrity"],
    "scripts/issue117_arm_c_fakeroot.py": ["issue-117-133"],
    "scripts/issue117_arm_c_frozen_pins.py": ["repo-integrity"],
    "scripts/issue117_arm_c_observe.py": ["repo-integrity"],
    "scripts/issue117_arm_c_plan.py": ["repo-integrity"],
    "scripts/issue117_arm_c_serving_evidence.py": ["repo-integrity"],
    "scripts/issue117_checkpoint_authority.py": ["issue-117-133"],
    "scripts/issue117_gemma_strategy.py": ["issue-117-133"],
    "scripts/issue117_integration_fixture.py": ["issue-117-133"],
    "scripts/issue117_parsers/": ["issue-117-133"],
    "scripts/issue117_planner.py": ["issue-117-133"],
    "scripts/issue117_preflight.py": ["issue-117-133"],
    "scripts/issue117_proof.py": ["repo-integrity", "issue-117-133"],
    "scripts/issue117_subject_identity.py": ["issue-117-133"],
    "scripts/issue129_arm_c_retry_core.py": ["repo-integrity"],
    "scripts/issue133_arm_c_retry_campaign.py": ["repo-integrity"],
    "scripts/issue133_arm_c_retry_direct.py": ["repo-integrity"],
    "scripts/issue133_canonical_environment.py": ["repo-integrity"],
    "scripts/issue133_equality_reduction.py": ["repo-integrity"],
    "scripts/issue133_physical_prelaunch_gate.py": ["repo-integrity"],
    "scripts/issue133_real_builder_dry_run.py": ["repo-integrity"],
    "scripts/issue133_regenerate_corrected_freeze.py": ["repo-integrity"],
    "scripts/issue133_terminal_reduction.py": ["repo-integrity"],
    "docs/implementation/r6-successor-dense-full-integration-117/": ["issue-117-133"],
    # Issues #166/#168/#170/#172/#182 Arm-C/Arm-E records: behavior suites
    # retired (Issue #246, PR #247 correction round 1). The bundles and
    # producers are integrity-pinned; test_issue184_final_closure still
    # reads the A-E trees, so issue-117-133 also runs.
    "docs/implementation/r6-successor-arm-c-swa-remediation-166/":
        ["repo-integrity", "issue-117-133"],
    "docs/implementation/r6-successor-arm-c-requal-blocked-168/":
        ["repo-integrity", "issue-117-133"],
    "scripts/issue168_corpus_census.py": ["repo-integrity"],
    "scripts/issue168_terminal_reduction.py": ["repo-integrity"],
    "scripts/issue168_manifest.py": ["repo-integrity"],
    "docs/implementation/r6-successor-arm-c-long-remainder-corpus-170/":
        ["repo-integrity", "issue-117-133"],
    "scripts/issue170_corpus_methodology.py": ["repo-integrity"],
    "scripts/issue170_corpus_producer.py": ["repo-integrity"],
    "scripts/issue170_authority_record.py": ["repo-integrity"],
    "scripts/issue170_terminal_reduction.py": ["repo-integrity"],
    "scripts/issue170_manifest.py": ["repo-integrity"],
    "docs/implementation/r6-successor-arm-c-requalification-172/":
        ["repo-integrity", "issue-117-133"],
    "scripts/issue172_campaign_pins.py": ["repo-integrity"],
    "scripts/issue172_authority.py": ["repo-integrity"],
    "scripts/issue172_corpus_bind.py": ["repo-integrity"],
    "scripts/issue172_direct_loop.py": ["repo-integrity"],
    "scripts/issue172_ordinary_loop.py": ["repo-integrity"],
    "scripts/issue172_cpu_preflight.py": ["repo-integrity"],
    "scripts/issue172_physical_preflight.py": ["repo-integrity"],
    "scripts/issue172_refreeze.py": ["repo-integrity"],
    "scripts/issue172_real_builder_dry_run.py": ["repo-integrity"],
    "scripts/issue172_direct_driver.py": ["repo-integrity"],
    "scripts/issue172_ordinary_client.py": ["repo-integrity"],
    "scripts/issue172_serving_evidence.py": ["repo-integrity"],
    "scripts/issue172_equality_reduce.py": ["repo-integrity"],
    "scripts/issue172_sentinel_reduce.py": ["repo-integrity"],
    "scripts/issue172_swa_observation.py": ["repo-integrity"],
    "scripts/issue172_zero_invariants.py": ["repo-integrity"],
    "scripts/issue172_terminal.py": ["repo-integrity"],
    "scripts/issue172_manifest.py": ["repo-integrity"],
    # Retired #175 Arm-D behavior suite (Issue #246): integrity-only.
    "docs/implementation/r6-successor-arm-d-warm-restart-175/":
        ["repo-integrity"],
    "scripts/issue175_assemble.py": ["repo-integrity"],
    "scripts/issue175_authority.py": ["repo-integrity"],
    "scripts/issue175_campaign_pins.py": ["repo-integrity"],
    "scripts/issue175_inventory.py": ["repo-integrity"],
    "scripts/issue175_manifest.py": ["repo-integrity"],
    "scripts/issue175_ordinary_client.py": ["repo-integrity"],
    "scripts/issue175_reduce.py": ["repo-integrity"],
    "scripts/issue175_terminal.py": ["repo-integrity"],
    "docs/implementation/r6-successor-arm-e-locality-mutation-182/":
        ["repo-integrity", "issue-117-133"],
    "scripts/issue182_campaign_pins.py": ["repo-integrity"],
    "scripts/issue182_authority.py": ["repo-integrity"],
    "scripts/issue182_inventory.py": ["repo-integrity"],
    "scripts/issue182_compare.py": ["repo-integrity"],
    "scripts/issue182_terminal.py": ["repo-integrity"],
    "scripts/issue187_r7a_census.py": ["issue-187-r7a"],
    "scripts/issue187_r7a_manifest.py": ["issue-187-r7a", "issue-222-r7c"],
    "scripts/issue187_r7a_reducer.py": ["issue-187-r7a", "issue-222-r7c"],
    "scripts/issue209_r7b_manifest.py": ["issue-209-r7b", "issue-222-r7c"],
    "scripts/issue209_r7b_reducer.py": ["issue-209-r7b", "issue-222-r7c"],
    "scripts/issue209_r7b_fixture.py": ["issue-209-r7b", "issue-222-r7c"],
    "scripts/issue222_r7c.py": ["issue-222-r7c"],
    "docs/investigations/deepseek-v41-flash-r7-b/": ["issue-209-r7b"],
    "scripts/issue182_manifest.py": ["repo-integrity"],
    # Issue #213 campaign gate ordering (orchestration tooling + tests);
    # Issue #226 adds the hosted Final CPU Validation workflow, envelope
    # seams, and its controls in the same doctrinal group.  (Workflow
    # files themselves stay under the CI_WORKFLOW_PREFIXES fail-closed
    # rule — a workflow change always selects full regression; these
    # entries deliberately do NOT narrow that.)
    "scripts/issue213_gate_orchestration.py": ["issue-213-gate-ordering"],
    "docs/campaign-gate-ordering.md": ["issue-213-gate-ordering"],
    # The parallel full-suite runner itself (Issue #173): its contract
    # tests are repo-integrity modules; classify explicitly instead of
    # failing closed to full regression for every runner-only change.
    "scripts/run_full_cpu_suite.py": [
        "repo-integrity",
        "issue-213-gate-ordering"],
    # Issue #137 retained evidence lives inside the #117 evidence tree;
    # its behavior suites are retired (Issue #246) and the bundle is
    # integrity-pinned (the #117 prefix rule above also matches, and
    # classification unions all matching rules).
    "docs/implementation/r6-successor-dense-full-integration-117/evidence/arm-c-regime4-diagnosis-137/": [
        "repo-integrity",
        "issue-117-133"],

    "scripts/issue137_binding.py": ["repo-integrity"],
    # Retired #157 chunk-2 diagnosis behavior suite (Issue #246): the
    # bundle is integrity-pinned.
    "docs/implementation/r6-successor-dense-full-integration-117/evidence/arm-c-chunk2-diagnosis-157/":
        ["issue-117-133", "repo-integrity"],
    "scripts/issue157_baseline_record.py": ["repo-integrity"],
    "scripts/issue157_binding.py": ["repo-integrity"],
    "scripts/issue157_conclusions.py": ["repo-integrity"],
    "scripts/issue157_instrumentation.py": ["repo-integrity"],
    "scripts/issue157_manifest.py": ["repo-integrity"],
    "scripts/issue157_probe_driver.py": ["repo-integrity"],
    "scripts/issue157_replay_harness.py": ["repo-integrity"],
    "scripts/issue157_replay_worker.py": ["repo-integrity"],
    "scripts/issue157_sitecustomize.py": ["repo-integrity"],
    # Retired #153 Arm-C remediation suite (Issue #246): the bundle under
    # the #117 implementation area and its producers are integrity-pinned.
    "scripts/issue153_phase0_inventory.py": ["repo-integrity"],
    "scripts/issue153_producer_delta.py": ["repo-integrity"],
    "scripts/issue153_boundary_matrix.py": ["repo-integrity"],
    "scripts/issue153_manifest.py": ["repo-integrity"],
    "scripts/issue137_conclusions.py": ["repo-integrity"],
    "scripts/issue137_phase1_inventory.py": ["repo-integrity"],
    "scripts/issue137_probe_driver.py": ["repo-integrity"],
    # (The synthetic docs/implementation/vulkan-arm-c-regime4-diagnosis-137/
    # prefix never matched a tracked path; the real retained #137
    # evidence rule lives with the #117 tree above.)

    "scripts/issue99_artifact_core.py": ["issue-117-133", "issue-99-103"],
    "scripts/issue99_mini_model.py": ["issue-99-103"],
    "scripts/issue99_proof.py": ["issue-99-103"],
    "scripts/issue101_fixture.py": ["issue-99-103"],
    "scripts/issue101_orchestration.py": ["issue-117-133", "issue-99-103"],
    "scripts/issue101_proof.py": ["issue-99-103"],
    "scripts/issue103_fixture.py": ["issue-99-103"],
    "scripts/issue103_planner.py": ["issue-117-133", "issue-99-103"],
    "scripts/issue103_proof.py": ["issue-99-103"],
    # #103 evidence; test_issue117_provenance and test_issue103_planner /
    # test_evidence_manifest_lifecycle consume this shared tree.
    "docs/implementation/artifact-locality-transition-planning-103/": ["issue-99-103",
        "issue-117-133"],
    # #99/#101 evidence; test_issue117_provenance pins these exact bytes
    # as the #117 subject provenance, so the shared tree fans out.
    "docs/implementation/plan-driven-artifact-acquisition-99/": ["issue-99-103",
        "issue-117-133"],
    "docs/implementation/plan-driven-artifact-orchestration-101/": ["issue-99-103",
        "issue-117-133"],
    # Issue #200 (R8-F) internal Source-policy seam: additive extension of
    # the #99/#101 architecture that never modifies their pinned producers;
    # shares the same CPU-only lineage group.
    "scripts/issue200_r8f_source_policy.py": ["issue-99-103"],
    "scripts/issue200_r8f_fixture.py": ["issue-99-103"],
    "scripts/issue200_r8f_proof.py": ["issue-99-103"],
    "scripts/issue200_r8f_terminal_reduction.py": ["issue-99-103"],
    "scripts/issue200_r8f_rpc_cache_mechanism.py": ["issue-99-103"],
    "scripts/issue200_r8f_physical.py": ["issue-99-103"],
    "tests/test_issue200_r8f_source_policy.py": ["issue-99-103"],
    "tests/test_issue200_r8f_proof.py": ["issue-99-103"],
    "docs/implementation/r8-f-local-backing-source-policy-200/": ["issue-99-103"],

    # Issue #246 topology: the former monolithic vulkan-v0-b bucket split
    # by current dependency/authority boundary (import-graph component).
    # Retired lineages select the always-on repo-integrity group, whose
    # retired-lineage integrity check (scripts/check_ci_test_retention.py)
    # pins their accepted evidence, manifests, and producers; a consumer
    # group is added only where a retained test reads that evidence.
    #
    # Current R8-I Qwen heterogeneous-Vulkan qualification (#237/#244).
    "docs/qualification/qwen38-vulkan-v1/": ["r8i-qwen-qualification"],
    "scripts/issue237_build_exclusion_inventory.py":
        ["r8i-qwen-qualification"],
    "scripts/issue237_freeze_tooling.py": ["r8i-qwen-qualification"],
    "scripts/issue237_generate_corpora.py": ["r8i-qwen-qualification"],
    "scripts/issue237_length_bands.py": ["r8i-qwen-qualification"],
    "scripts/issue237_methodology.py": ["r8i-qwen-qualification"],
    "scripts/issue237_reconstruct_tokenizer.py": ["r8i-qwen-qualification"],
    "scripts/issue237_schemas.py": ["r8i-qwen-qualification"],
    "scripts/issue237_seal_holdout.py": ["r8i-qwen-qualification"],
    "scripts/issue237_semantic_adjudication.py": ["r8i-qwen-qualification"],
    "scripts/issue237_thresholds.py": ["r8i-qwen-qualification"],
    "scripts/issue237_unseal_preflight.py": ["r8i-qwen-qualification"],
    "docs/investigations/qwen38-flash-next-r8-i4-v340l-z440/":
        ["r8i-qwen-qualification"],
    "scripts/issue248_analysis.py": ["r8i-qwen-qualification"],
    "scripts/issue248_diagnostic.py": ["r8i-qwen-qualification"],
    "scripts/issue248_health.py": ["r8i-qwen-qualification"],
    "scripts/issue248_identity.py": ["r8i-qwen-qualification"],
    "scripts/issue248_physical.py": ["r8i-qwen-qualification"],
    "scripts/issue248_terminal.py": ["r8i-qwen-qualification"],
    "docs/investigations/qwen38-flash-next-r8-i3a-ref-nondeterminism/":
        ["r8i-qwen-qualification"],
    "docs/hardware/pcie-slot-ledger.md": ["r8i-qwen-qualification"],
    # R8-A/B Qwen lineage; R8-A/R8-B evidence also feeds the #237
    # historical-exclusion inventory and length-band derivation. Retired
    # R8-D/R8-D-v2 suites (Issue #246): integrity-only.
    "docs/investigations/qwen38-flash-next-r8-a/":
        ["r8-qwen-lineage", "r8i-qwen-qualification"],
    "docs/investigations/qwen38-flash-next-r8-b/":
        ["r8-qwen-lineage", "r8i-qwen-qualification"],
    "docs/investigations/qwen38-flash-next-r8-c/":
        ["r8-qwen-lineage", "repo-integrity"],
    "docs/investigations/qwen38-flash-next-r8-d/": ["repo-integrity"],
    "docs/investigations/qwen38-flash-next-r8-d-v2/": ["repo-integrity"],
    "scripts/issue189_r8a_reducer.py": ["r8-qwen-lineage", "issue-222-r7c"],
    "scripts/issue191_derive_fixtures.py": ["r8-qwen-lineage"],
    "scripts/issue191_negative_controls.py": ["r8-qwen-lineage"],
    "scripts/issue191_r8b_authority.py": ["r8-qwen-lineage"],
    "scripts/issue191_run_ladder.py": ["r8-qwen-lineage"],
    "scripts/issue191_terminal_reduction.py": ["r8-qwen-lineage"],
    "scripts/issue191_verify_split_set.py": ["r8-qwen-lineage"],
    "scripts/issue195_manifest.py": ["repo-integrity"],
    "scripts/issue195_negative_controls.py": ["repo-integrity"],
    "scripts/issue195_r8d_authority.py": ["repo-integrity"],
    "scripts/issue195_run_ladder.py": ["repo-integrity"],
    "scripts/issue195_sampler_probe.py": ["repo-integrity"],
    "scripts/issue195_terminal_reduction.py": ["repo-integrity"],
    "scripts/issue195_v2_authority.py": ["repo-integrity"],
    "scripts/issue195_v2_freeze_reference.py": ["repo-integrity"],
    "scripts/issue195_v2_launch.py": ["repo-integrity"],
    "scripts/issue195_v2_manifest.py": ["repo-integrity"],
    "scripts/issue195_v2_negative_controls.py": ["repo-integrity"],
    "scripts/issue195_v2_run_ladder.py": ["repo-integrity"],
    "scripts/issue195_v2_terminal_reduction.py": ["repo-integrity"],
    # Retired R8-C/E/G/H behavior suites (Issue #246): integrity-only,
    # except where current #237 tooling reads the evidence.
    "docs/investigations/qwen38-flash-next-r8-e/": ["repo-integrity"],
    "docs/investigations/qwen38-flash-next-r8-g/":
        ["r8i-qwen-qualification", "repo-integrity"],
    "docs/investigations/qwen38-flash-next-r8-h-vulkan/":
        ["r8i-qwen-qualification", "repo-integrity"],
    "scripts/issue193_phase1_reduction.py": ["repo-integrity"],
    "scripts/issue193_r8c_authority.py": ["repo-integrity"],
    "scripts/issue193_terminal_reduction.py": ["repo-integrity"],
    "scripts/issue199_r8e_authority.py": ["repo-integrity"],
    "scripts/issue199_r8e_capture.py": ["repo-integrity"],
    "scripts/issue199_r8e_launch.py": ["repo-integrity"],
    "scripts/issue199_r8e_manifest.py": ["repo-integrity"],
    "scripts/issue199_r8e_negative_controls.py": ["repo-integrity"],
    "scripts/issue199_r8e_terminal_reduction.py": ["repo-integrity"],
    "scripts/issue207_r8g_authority.py": ["repo-integrity"],
    "scripts/issue207_r8g_capture.py": ["repo-integrity"],
    "scripts/issue207_r8g_launch.py": ["repo-integrity"],
    "scripts/issue207_r8g_manifest.py": ["repo-integrity"],
    "scripts/issue207_r8g_negative_controls.py": ["repo-integrity"],
    "scripts/issue207_r8g_reduce.py": ["repo-integrity"],
    "scripts/issue234_assemble.py": ["repo-integrity"],
    "scripts/issue234_authority.py": ["repo-integrity"],
    "scripts/issue234_characterize.py": ["repo-integrity"],
    "scripts/issue234_freeze.py": ["repo-integrity"],
    "scripts/issue234_health.py": ["repo-integrity"],
    "scripts/issue234_host.py": ["repo-integrity"],
    "scripts/issue234_ladder.py": ["repo-integrity"],
    "scripts/issue234_manifest.py": ["repo-integrity"],
    "scripts/issue234_observe.py": ["repo-integrity"],
    "scripts/issue234_placement.py": ["repo-integrity"],
    "scripts/issue234_receipt.py": ["repo-integrity"],
    "scripts/issue234_reduce.py": ["repo-integrity"],
    "scripts/issue234_runtime.py": ["repo-integrity"],
    # Retired V0-A/V0-B Vulkan lineage (Issue #246): integrity-only.
    "scripts/v0a_correctness_derive.py": ["repo-integrity"],
    "scripts/v0a_correctness_run.py": ["repo-integrity"],
    "scripts/v0a_materialization_derive.py": ["repo-integrity"],
    "scripts/v0a_materialization_run.py": ["repo-integrity"],
    "scripts/v0b_capability_assessment.py": ["repo-integrity"],
    "scripts/v0b_comparability_audit.py": ["repo-integrity"],
    "scripts/v0b_correctness_stability.py": ["repo-integrity"],
    "scripts/v0b_cpu_proof.py": ["repo-integrity"],
    "scripts/v0b_cpu_supplement_derive.py": ["repo-integrity"],
    "scripts/v0b_cpu_supplement_run.py": ["repo-integrity"],
    "scripts/v0b_economics.py": ["repo-integrity"],
    "scripts/v0b_manifest.py": ["repo-integrity"],
    "scripts/v0b_seam_comparison.py": ["repo-integrity"],
    "scripts/v0b_terminal.py": ["repo-integrity"],
    "docs/investigations/vulkan-v0-a/": ["repo-integrity"],
    "docs/investigations/vulkan-v0-b/": ["repo-integrity"],
    # Retired V0-C/V1/V2-A Vulkan harness lineage (Issue #246):
    # integrity-only.
    "scripts/v0c_canonical_run.py": ["repo-integrity"],
    "scripts/v0c_correctness.py": ["repo-integrity"],
    "scripts/v0c_execution_seam.py": ["repo-integrity"],
    "scripts/v0c_manifest.py": ["repo-integrity"],
    "scripts/v0c_vulkan_adapter.py": ["repo-integrity"],
    "scripts/v1a_execution_participant.py": ["repo-integrity"],
    "scripts/v1a_manifest.py": ["repo-integrity"],
    "scripts/v1a_runner.py": ["repo-integrity"],
    "scripts/v1a_vulkan_adapter.py": ["repo-integrity"],
    "scripts/v1b_campaign.py": ["repo-integrity"],
    "scripts/v1b_manifest.py": ["repo-integrity"],
    "scripts/v1c_accounting.py": ["repo-integrity"],
    "scripts/v1c_manifest.py": ["repo-integrity"],
    "scripts/v1c_runner.py": ["repo-integrity"],
    "scripts/v2a_authority.py": ["repo-integrity"],
    "scripts/v2a_authority_v2.py": ["repo-integrity"],
    "scripts/v2a_authority_v3.py": ["repo-integrity"],
    "scripts/v2a_discovery.py": ["repo-integrity"],
    "scripts/v2a_discovery_v2.py": ["repo-integrity"],
    "scripts/v2a_discovery_v3.py": ["repo-integrity"],
    "scripts/v2a_harness.py": ["repo-integrity"],
    "scripts/v2a_manifest.py": ["repo-integrity"],
    "docs/investigations/vulkan-v0-c/": ["repo-integrity"],
    "docs/investigations/vulkan-v1-a/": ["repo-integrity"],
    "docs/investigations/vulkan-v1-b/": ["repo-integrity"],
    "docs/investigations/vulkan-v1-c/": ["repo-integrity"],
    "docs/investigations/vulkan-v2-a/": ["repo-integrity"],
    # Retired #35 x1 interconnect envelope lineage (Issue #246):
    # integrity-only.
    "scripts/issue35_coarse_concurrent.py": ["repo-integrity"],
    "scripts/issue35_envelope.py": ["repo-integrity"],
    "scripts/issue35_link_probe.py": ["repo-integrity"],
    "scripts/issue35_residency_facts.py": ["repo-integrity"],
    "scripts/issue35_role_sweep.py": ["repo-integrity"],
    "docs/investigations/link-x1-envelope/": ["repo-integrity"],
    # Retired V2-B..V2-G V340L campaign behavior suites (Issue #246).
    "docs/investigations/vulkan-v2-b-v340l/": ["repo-integrity"],
    "docs/investigations/vulkan-v2-c-v340l-platform-stability/":
        ["repo-integrity"],
    "docs/investigations/vulkan-v2-d0-overlap-seam/": ["repo-integrity"],
    "docs/investigations/vulkan-v2-d-v340l-concurrent/": ["repo-integrity"],
    "docs/investigations/vulkan-v2-e-v340l-peer-link/": ["repo-integrity"],
    "docs/investigations/vulkan-v2-f-v340l-external-memory/":
        ["repo-integrity"],
    "docs/investigations/vulkan-v2-g-pcie-path-remediation/":
        ["repo-integrity"],
    "scripts/issue210_assemble.py": ["repo-integrity"],
    "scripts/issue210_build_authorities.py": ["repo-integrity"],
    "scripts/issue210_manifest.py": ["repo-integrity"],
    "scripts/issue210_terminal.py": ["repo-integrity"],
    "scripts/issue215_build_final_authorities.py": ["repo-integrity"],
    "scripts/issue215_build_final_authorities_v2.py": ["repo-integrity"],
    "scripts/issue215_campaign_plan.py": ["repo-integrity"],
    "scripts/issue215_final_canonical.py": ["repo-integrity"],
    "scripts/issue215_manifest.py": ["repo-integrity"],
    "scripts/issue215_sentinel.py": ["repo-integrity"],
    "scripts/issue215_snapshot.py": ["repo-integrity"],
    "scripts/issue215_terminal.py": ["repo-integrity"],
    "scripts/issue215_v2_authority.py": ["repo-integrity"],
    "scripts/issue216_assemble.py": ["repo-integrity"],
    "scripts/issue216_concurrent.py": ["repo-integrity"],
    "scripts/issue216_execution.py": ["repo-integrity"],
    "scripts/issue216_fault.py": ["repo-integrity"],
    "scripts/issue216_freeze.py": ["repo-integrity"],
    "scripts/issue216_host.py": ["repo-integrity"],
    "scripts/issue216_manifest.py": ["repo-integrity"],
    "scripts/issue216_physical_authority.py": ["repo-integrity"],
    "scripts/issue216_preflight.py": ["repo-integrity"],
    "scripts/issue216_receipt.py": ["repo-integrity"],
    "scripts/issue216_reset.py": ["repo-integrity"],
    "scripts/issue216_soak.py": ["repo-integrity"],
    "scripts/issue216_transport.py": ["repo-integrity"],
    "scripts/issue219_capability_probe.py": ["repo-integrity"],
    "scripts/issue219_manifest.py": ["repo-integrity"],
    "scripts/issue219_observe_collector.py": ["repo-integrity"],
    "scripts/issue219_patch.py": ["repo-integrity"],
    "scripts/issue219_reduce.py": ["repo-integrity"],
    "scripts/issue219_seam_rubric.py": ["repo-integrity"],
    "scripts/issue228_assemble.py": ["repo-integrity"],
    "scripts/issue228_authority.py": ["repo-integrity"],
    "scripts/issue228_baselines.py": ["repo-integrity"],
    "scripts/issue228_capability.py": ["repo-integrity"],
    "scripts/issue228_freeze.py": ["repo-integrity"],
    "scripts/issue228_host.py": ["repo-integrity"],
    "scripts/issue228_ladder.py": ["repo-integrity"],
    "scripts/issue228_manifest.py": ["repo-integrity"],
    "scripts/issue228_probe.py": ["repo-integrity"],
    "scripts/issue228_receipt.py": ["repo-integrity"],
    "scripts/issue228_reduce.py": ["repo-integrity"],
    "scripts/issue230_assemble.py": ["repo-integrity"],
    "scripts/issue230_authority.py": ["repo-integrity"],
    "scripts/issue230_freeze.py": ["repo-integrity"],
    "scripts/issue230_host.py": ["repo-integrity"],
    "scripts/issue230_manifest.py": ["repo-integrity"],
    "scripts/issue230_preflight.py": ["repo-integrity"],
    "scripts/issue230_receipt.py": ["repo-integrity"],
    "scripts/issue230_reduce.py": ["repo-integrity"],
    "scripts/issue230_runner.py": ["repo-integrity"],
    "scripts/issue230_safety.py": ["repo-integrity"],
    "scripts/issue230_transfer.py": ["repo-integrity"],
    "scripts/issue232_assemble.py": ["repo-integrity"],
    "scripts/issue232_authority.py": ["repo-integrity"],
    "scripts/issue232_baseline.py": ["repo-integrity"],
    "scripts/issue232_bootproof.py": ["repo-integrity"],
    "scripts/issue232_coldproof.py": ["repo-integrity"],
    "scripts/issue232_freeze.py": ["repo-integrity"],
    "scripts/issue232_gate.py": ["repo-integrity"],
    "scripts/issue232_host.py": ["repo-integrity"],
    "scripts/issue232_manifest.py": ["repo-integrity"],
    "scripts/issue232_qualify.py": ["repo-integrity"],
    "scripts/issue232_receipt.py": ["repo-integrity"],
    "scripts/issue232_reduce.py": ["repo-integrity"],
    "scripts/issue232_replay.py": ["repo-integrity"],
    # Retired Phase-1/Phase1R derivation replays (Issue #246).
    "scripts/analyze_phase1_p6.py": ["repo-integrity"],
    "scripts/derive_phase1_placement.py": ["repo-integrity"],
    "scripts/derive_phase1_placement_v2.py": ["repo-integrity"],
    "scripts/derive_phase1r_d3_placement.py": ["repo-integrity"],
    "scripts/derive_phase1r_d4_placement.py": ["repo-integrity"],
    "scripts/derive_phase1r_d7_placement.py": ["repo-integrity"],
    "docs/benchmarks/results/phase1/": ["repo-integrity"],
    "docs/investigations/data/": ["repo-integrity"],
    "docs/investigations/deepseek-v41-flash-r7-a/": ["issue-187-r7a"],
    "docs/investigations/deepseek-v41-flash-r7-c/": ["issue-222-r7c"],
    # Phase-0 retained results: p0c-hardware-profile.json is consumed
    # by scripts/issue117_applicability.py (#117 applicability check).
    "docs/benchmarks/results/phase0/": ["issue-117-133"],
    # Frozen Phase-0 workloads: verified by scripts/check_phase0_workloads
    # .py, an always-on repo-integrity step.
    "docs/benchmarks/workloads/": ["repo-integrity"],

    # Top-level documentation: cheap always-on checks only. Deeper
    # documentation surfaces are family-owned above or fall through to
    # the generic docs classification below.
    "README.md": ["repo-integrity"],
    "CONTRIBUTING.md": ["repo-integrity"],
    "SECURITY.md": ["repo-integrity"],
    "BENCHMARKING.md": ["repo-integrity"],
    "AGENTS.md": ["repo-integrity"],
    "ARCHITECTURE.md": ["repo-integrity"],
    "ROADMAP.md": ["repo-integrity"],
    "LICENSE": ["repo-integrity"],
    ".gitignore": ["repo-integrity"],
    ".github/ISSUE_TEMPLATE/": ["repo-integrity"],

}

# Generic documentation classification. Any docs/ path not matched by an
# explicit rule above is ordinary prose ONLY when it is a Markdown file;
# any other unmapped docs/ file (generated evidence, retained data,
# manifests, schemas, producer files, ...) is evidence-bearing and fails
# closed to full regression. Adding a new evidence-bearing docs subtree
# requires registering it in PATH_GROUPS (or documenting why it is
# prose-only); the repository-tree coverage tests enforce this.
DOCS_PROSE_SUFFIX = ".md"

# Documentation subtrees that are pure prose for a specific family.
# (Superseded by explicit PATH_GROUPS entries; kept for registry
# stability.)
DOCS_FAMILY_PREFIXES = [
    # (prefix, group) — must match PATH_GROUPS entries
]

# Full-regression trigger surfaces (in addition to unclassified paths).
FULL_REGRESSION_PATHS = (
    SELF_AUTHORITY_PATHS
    + ENV_AUTHORITY_PATHS
    + REPO_AUTHORITY_PATHS
)


def _module_groups():
    """Reverse index: test module name -> groups listing it."""
    index = {}
    for group, modules in GROUP_TEST_MODULES.items():
        for m in modules:
            index.setdefault(m, []).append(group)
    return index


def classify_path(path):
    """Return (groups, classified) for a single changed path.

    ``classified`` is False when the path matches no rule and must
    fail closed to full regression.
    """
    if path in PATH_GROUPS:
        return list(PATH_GROUPS[path]), True
    # test module by name
    if path.startswith("tests/test_") and path.endswith(".py"):
        mod = path[len("tests/"):-len(".py")]
        if mod in _MODULE_GROUPS_CACHE:
            return list(_MODULE_GROUPS_CACHE[mod]), True
        # unregistered test module: shared test namespace, fail closed
        return [], False
    # directory-prefix rules
    groups = []
    matched = False
    for pattern, pgroups in PATH_GROUPS.items():
        if pattern.endswith("/") and path.startswith(pattern):
            groups.extend(pgroups)
            matched = True
    if matched:
        return _sort_unique(groups), True
    # generic documentation: ordinary Markdown prose stays narrow
    # (repo-integrity only); any other unmapped docs/ file is
    # evidence-bearing and fails closed to full regression
    if path.startswith("docs/") and path.endswith(DOCS_PROSE_SUFFIX):
        return ["repo-integrity"], True
    # generic test-infra roots
    if path in SHARED_TEST_PATHS:
        return [], False  # shared helpers: fail closed to full
    if path.startswith("tests/"):
        return [], False  # helper/fixture modules: fail closed
    if path.startswith("scripts/"):
        # unregistered script: fail closed (shared producer namespace)
        return [], False
    return [], False


_MODULE_GROUPS_CACHE = _module_groups()


def _validate_paths(paths):
    """Fail closed on malformed path input. Returns error list."""
    errors = []
    seen = set()
    for p in paths:
        if not p:
            errors.append("empty path line")
            continue
        if p != p.strip():
            errors.append(f"path has surrounding whitespace: {p!r}")
            continue
        if p.startswith("/") or p.startswith("\\"):
            errors.append(f"absolute path: {p!r}")
            continue
        if ".." in p.split("/"):
            errors.append(f"path traversal: {p!r}")
            continue
        if p.endswith("/"):
            errors.append(f"directory-style trailing slash: {p!r}")
            continue
        if "\\" in p:
            errors.append(f"backslash in path: {p!r}")
            continue
        if p in seen:
            errors.append(f"duplicate path: {p!r}")
            continue
        seen.add(p)
    return errors


def plan(changed_paths, mode="pr", force_full_reason=None):
    """Compute the CI plan for a changed-path set.

    Deterministic: same inputs -> identical plan dict.
    """
    if mode not in ("pr", "full"):
        raise ValueError(f"unknown mode: {mode!r}")

    reasons = []
    groups = set(ALWAYS_ON_GROUPS)
    full = False

    if mode == "full":
        full = True
        reasons.append("mode: full regression requested (push to main, "
                       "manual full, or escalation)")
    else:
        if not changed_paths:
            # empty/absent diff is ambiguous, never a proven no-op
            full = True
            reasons.append("fail-closed: empty changed-path set is "
                           "ambiguous, selecting full regression")
        malformed = _validate_paths(changed_paths)
        if malformed:
            full = True
            reasons.append("fail-closed: malformed changed-path input: "
                           + "; ".join(malformed))
        else:
            for path in changed_paths:
                if path in SELF_AUTHORITY_PATHS:
                    full = True
                    reasons.append(
                        f"fail-closed: CI selection authority changed: {path}")
                for prefix in CI_WORKFLOW_PREFIXES:
                    if path.startswith(prefix):
                        full = True
                        reasons.append(
                            f"fail-closed: CI workflow changed: {path}")
                if path in ENV_AUTHORITY_PATHS:
                    full = True
                    reasons.append(
                        "fail-closed: canonical dependency/environment "
                        f"authority changed: {path}")
                if path in REPO_AUTHORITY_PATHS:
                    full = True
                    reasons.append(
                        "fail-closed: repository authority surface changed: "
                        f"{path}")
                pgroups, classified = classify_path(path)
                if not classified:
                    full = True
                    reasons.append(
                        "fail-closed: unclassified changed path selects "
                        f"full regression: {path}")
                else:
                    for g in pgroups:
                        groups.add(g)
                        reasons.append(f"{path} -> {g}")
        if force_full_reason:
            full = True
            reasons.append(f"fail-closed: {force_full_reason}")

    if full:
        groups = set(GROUP_TEST_MODULES.keys())
        # keep only registered groups
    else:
        # every targeted group must be registered
        unknown = groups - set(GROUP_TEST_MODULES.keys())
        if unknown:
            raise AssertionError(f"plan references unregistered groups: {sorted(unknown)}")

    return {
        "mode": "full" if full else "targeted",
        "groups": _sort_unique(groups),
        "full_regression": full,
        "reason": _sort_unique(reasons),
        "planner": "scripts/plan_ci.py",
        "planner_version": PLANNER_VERSION,
        "schema": PLAN_SCHEMA,
    }


# ---------------------------------------------------------------------------
# Registry emission / validation
# ---------------------------------------------------------------------------

def build_registry():
    """Canonical registry dict derived from the mapping tables."""
    module_index = _module_groups()
    return {
        "schema": "ci-groups/1",
        "planner": "scripts/plan_ci.py",
        "planner_version": PLANNER_VERSION,
        "always_on": list(ALWAYS_ON_GROUPS),
        "groups": {
            group: {
                "invariant": GROUP_INVARIANTS.get(group, ""),
                "test_modules": list(modules),
            }
            for group, modules in sorted(GROUP_TEST_MODULES.items())
        },
        "path_rules": {
            pattern: list(g) for pattern, g in sorted(PATH_GROUPS.items())
        },
        "full_regression_paths": _sort_unique(FULL_REGRESSION_PATHS),
    }


def load_registry(path=None):
    p = Path(path) if path else REGISTRY_PATH
    return json.loads(p.read_text(encoding="utf-8"))


def self_check():
    """Validate registry freshness and internal consistency."""
    errors = []
    reg = build_registry()
    canonical = json.dumps(reg, sort_keys=True, indent=1) + "\n"
    on_disk = REGISTRY_PATH.read_text(encoding="utf-8")
    if on_disk != canonical:
        errors.append("ci_groups.json is not the canonical registry; "
                      "regenerate with --emit-registry")
    # every module in exactly one group
    seen = {}
    for g, info in reg["groups"].items():
        for m in info["test_modules"]:
            if m in seen:
                errors.append(f"module {m} in both {seen[m]} and {g}")
            seen[m] = g
    # every group declares its current invariant (Issue #246)
    for g, info in reg["groups"].items():
        if not info["invariant"].strip():
            errors.append(f"group {g} declares no current invariant "
                          "(GROUP_INVARIANTS)")
    for g in sorted(set(GROUP_INVARIANTS) - set(GROUP_TEST_MODULES)):
        errors.append(f"invariant declared for unregistered group {g}")
    # every rule references registered groups
    for pattern, gs in reg["path_rules"].items():
        for g in gs:
            if g not in reg["groups"]:
                errors.append(f"path rule {pattern} references unknown group {g}")
    return errors


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mode", choices=("pr", "full"), default="pr",
                    help="pr: classify changed paths; full: force full regression")
    ap.add_argument("--self-check", action="store_true",
                    help="validate the group registry and exit")
    ap.add_argument("--emit-registry", action="store_true",
                    help="(re)write the canonical ci_groups.json and exit")
    ap.add_argument("--output", help="write plan JSON here (default stdout)")
    ap.add_argument("paths", nargs="*",
                    help="changed paths (alternatively pass paths on stdin, "
                         "one per line)")
    args = ap.parse_args(argv)

    if args.emit_registry:
        REGISTRY_PATH.write_text(
            json.dumps(build_registry(), sort_keys=True, indent=1) + "\n",
            encoding="utf-8")
        print(f"wrote {REGISTRY_PATH}")
        return 0

    errors = self_check()
    if args.self_check or errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        if args.self_check:
            print("self-check: OK" if not errors else "self-check: FAILED")
            return 0 if not errors else 1
        return 1

    if args.paths:
        changed = list(args.paths)
    else:
        # Preserve every stdin line (including blank ones) so that
        # malformed input reaches _validate_paths and fails closed
        # instead of being silently filtered into a narrow plan.
        changed = [line.rstrip("\n") for line in sys.stdin]

    result = plan(changed, mode=args.mode)
    text = json.dumps(result, indent=1, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())

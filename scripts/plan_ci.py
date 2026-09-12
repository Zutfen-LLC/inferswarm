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
    "scripts/issue137_manifest.py",
    "docs/finalization.md",
    "docs/status-maintenance.md",
    "docs/evidence-manifests.md",
    "docs/project-status.json",
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
    ],
    "issue-74-79": [
        "test_issue74_methodology",
        "test_issue76_v2_stress_selection",
        "test_issue79_v2_threshold_tooling",
    ],
    "issue-83-95": [
        "test_issue83_semantic_contract",
        "test_issue86_v3_methodology",
        "test_issue90_post_v3_diagnosis",
        "test_issue93_numerical_core_doctrine",
        "test_issue95_v4_methodology",
        "test_issue95_v4_thresholds",
        "test_issue105_post_v4_core_diagnosis",
        "test_issue108_post_v4_statistical_metric_doctrine",
    ],
    "issue-109-110": [
        "test_issue109_v5_methodology",
        "test_issue109_v5_thresholds",
        "test_issue109_v5_methodology_freeze",
        "test_issue110_v5_custody_handoff",
        "test_issue110_terminal_report_decimals",
    ],
    "issue-117-133": [
        "test_issue117_integration_fixture",
        "test_issue117_applicability",
        "test_issue117_gemma_strategy",
        "test_issue117_planner",
        "test_issue117_preflight",
        "test_issue117_proof",
        "test_issue117_provenance",
        "test_issue117_checkpoint_authority",
        "test_issue117_accepted_subject",
        "test_issue117_physical_retention",
        "test_issue117_arm_a_retention",
        "test_issue117_arm_b_retention",
        "test_issue117_arm_c_retention",
        "test_issue117_arm_c_blocker",
        "test_issue129_arm_c_retry",
        "test_issue133_arm_c_retry_campaign",
        "test_issue133_arm_c_retry_direct",
        "test_issue133_corrected_freeze",
        "test_issue133_gate_tooling_drift",
        "test_issue133_prelaunch_bootstrap",
        "test_issue133_physical_execution_retention",
        "test_issue153_arm_c_remediation",
    ],
    "issue-137": [
        "test_issue137_regime4_diagnosis",
        "test_issue137_regime4_diagnosis_correction",
    ],
    "issue-99-103": [
        "test_issue99_artifact_core",
        "test_issue99_proof",
        "test_issue101_orchestration",
        "test_issue101_proof",
        "test_issue103_planner",
    ],
    "vulkan-v0-b": [
        "test_v0b_reduction",
        "test_v0c_canonical_run",
        "test_v0c_correctness",
        "test_v0c_evidence_manifest",
        "test_v0c_execution_seam",
        "test_v0c_vulkan_adapter",
    ],
    "phase1-analysis": [
        "test_analyze_phase1_p6",
        "test_derive_phase1_placement_v2",
        "test_derive_phase1r_d3_placement",
        "test_derive_phase1r_d4_placement",
        "test_derive_phase1r_d7_placement",
    ],
    # CPU-only methodology gates not surfaced as CI steps on main; they
    # are part of full regression so no coverage is lost.
    "issue-115-cleanup": [
        "test_issue115_cleanup_retention",
    ],
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
#   - scripts/ and tests/ are shared namespaces: any script or test
#     NOT under a family prefix and NOT the module-bound script of a
#     family is unclassified -> full regression (fail closed).
PATH_GROUPS = {
    # Repository-wide authority
    "scripts/sync_project_status.py": ["repo-integrity"],
    "scripts/finalize_repository.py": ["repo-integrity"],
    "scripts/issue137_manifest.py": ["repo-integrity"],
    "scripts/check_phase0_workloads.py": ["repo-integrity"],
    "docs/project-status.json": ["repo-integrity"],
    "docs/status-maintenance.md": ["repo-integrity"],
    "docs/finalization.md": ["repo-integrity"],
    "docs/evidence-manifests.md": ["repo-integrity"],
    "scripts/README.md": ["repo-integrity"],
    "tests/test_project_status.py": ["repo-integrity"],
    "tests/test_finalize_repository.py": ["repo-integrity"],
    "tests/test_evidence_manifest_lifecycle.py": ["repo-integrity"],
    "tests/test_issue131_cpu_test_env.py": ["repo-integrity"],
    "scripts/bootstrap_test_env.py": ["repo-integrity"],   # + env authority -> full
    "scripts/check_test_env.py": ["repo-integrity"],       # + env authority -> full
    "requirements-test.txt": ["repo-integrity"],           # + env authority -> full

    # Issue family surfaces
    "scripts/issue74_methodology.py": ["issue-74-79"],
    "scripts/commit_issue74_holdout.py": ["issue-74-79"],
    "scripts/seal_issue74_holdout.py": ["issue-74-79"],
    "scripts/generate_issue74_corpora.py": ["issue-74-79"],
    "scripts/hash_issue74_artifacts.py": ["issue-74-79"],
    "scripts/select_issue74_margin_stress.py": ["issue-74-79"],
    "scripts/select_issue76_margin_stress_v2.py": ["issue-74-79"],
    "scripts/generate_issue76_stress_pool_v2.py": ["issue-74-79"],
    "scripts/issue79_v2_thresholds.py": ["issue-74-79"],
    "scripts/verify_issue79_v2_unseal.py": ["issue-74-79"],
    "docs/qualification/gemma4-12b-it-v1/": ["issue-74-79"],
    "docs/qualification/gemma4-12b-it-v2/": ["issue-74-79"],

    "scripts/issue83_first_divergence.py": ["issue-83-95"],
    "scripts/issue86_v3_methodology.py": ["issue-83-95"],
    "scripts/issue86_v3_thresholds.py": ["issue-83-95"],
    "scripts/issue90_post_v3_diagnosis.py": ["issue-83-95"],
    "scripts/issue95_v4_contract.py": ["issue-83-95"],
    "scripts/issue95_v4_methodology.py": ["issue-83-95"],
    "scripts/issue95_v4_thresholds.py": ["issue-83-95"],
    "scripts/verify_issue86_v3_unseal.py": ["issue-83-95"],
    "scripts/verify_issue95_v4_unseal.py": ["issue-83-95"],
    "scripts/select_issue86_margin_stress_v3.py": ["issue-83-95"],
    "scripts/select_issue95_margin_stress_v4.py": ["issue-83-95"],
    "scripts/generate_issue86_corpora.py": ["issue-83-95"],
    "scripts/generate_issue95_corpora.py": ["issue-83-95"],
    "scripts/commit_issue86_holdout.py": ["issue-83-95"],
    "scripts/commit_issue86_stress_selection.py": ["issue-83-95"],
    "scripts/commit_issue95_holdout.py": ["issue-83-95"],
    "scripts/commit_issue95_stress_selection.py": ["issue-83-95"],
    "scripts/build_issue86_disjointness.py": ["issue-83-95"],
    "scripts/build_issue86_schemas.py": ["issue-83-95"],
    "scripts/build_issue95_disjointness.py": ["issue-83-95"],
    "scripts/build_issue95_schemas.py": ["issue-83-95"],
    "scripts/issue105_post_v4_core_diagnosis.py": ["issue-83-95"],
    "scripts/issue108_post_v4_statistical_metric_doctrine.py": ["issue-83-95"],
    "docs/adr/": ["issue-83-95"],  # ADRs decide; doctrine changes are broad
    "docs/architecture/": ["issue-83-95"],
    "docs/qualification/gemma4-12b-it-semantic-83/": ["issue-83-95"],
    "docs/qualification/gemma4-12b-it-v3/": ["issue-83-95"],
    "docs/qualification/gemma4-12b-it-v3-campaign-88/": ["issue-83-95"],
    "docs/qualification/gemma4-12b-it-v4/": ["issue-83-95"],
    "docs/qualification/gemma4-12b-it-post-v3-envelope-diagnosis/": ["issue-83-95"],
    "docs/qualification/gemma4-12b-it-post-v4-core-diagnosis/": ["issue-83-95"],
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
    "docs/qualification/gemma4-12b-it-v2-campaign-81/": ["issue-117-133"],
    "docs/qualification/gemma4-12b-it-v4-campaign-97/": ["issue-117-133"],

    # Issue #117 producer scripts and evidence tree.
    "scripts/issue117_accepted_subject.py": ["issue-117-133"],
    "scripts/issue117_applicability.py": ["issue-117-133"],
    "scripts/issue117_arm_a_evidence.py": ["issue-117-133"],
    "scripts/issue117_arm_b_correction_build.py": ["issue-117-133"],
    "scripts/issue117_arm_b_evidence.py": ["issue-117-133"],
    "scripts/issue117_arm_b_observe_hosts.py": ["issue-117-133"],
    "scripts/issue117_arm_b_transport_audit_build.py": ["issue-117-133"],
    "scripts/issue117_arm_c_authority_audit.py": ["issue-117-133"],
    "scripts/issue117_arm_c_blocker_fakeroot.py": ["issue-117-133"],
    "scripts/issue117_arm_c_blocker_reducer.py": ["issue-117-133"],
    "scripts/issue117_arm_c_client.py": ["issue-117-133"],
    "scripts/issue117_arm_c_decoded_bytes.py": ["issue-117-133"],
    "scripts/issue117_arm_c_direct.py": ["issue-117-133"],
    "scripts/issue117_arm_c_evidence.py": ["issue-117-133"],
    "scripts/issue117_arm_c_fakeroot.py": ["issue-117-133"],
    "scripts/issue117_arm_c_frozen_pins.py": ["issue-117-133"],
    "scripts/issue117_arm_c_observe.py": ["issue-117-133"],
    "scripts/issue117_arm_c_plan.py": ["issue-117-133"],
    "scripts/issue117_arm_c_serving_evidence.py": ["issue-117-133"],
    "scripts/issue117_checkpoint_authority.py": ["issue-117-133"],
    "scripts/issue117_gemma_strategy.py": ["issue-117-133"],
    "scripts/issue117_integration_fixture.py": ["issue-117-133"],
    "scripts/issue117_parsers/": ["issue-117-133"],
    "scripts/issue117_planner.py": ["issue-117-133"],
    "scripts/issue117_preflight.py": ["issue-117-133"],
    "scripts/issue117_proof.py": ["issue-117-133"],
    "scripts/issue117_subject_identity.py": ["issue-117-133"],
    "scripts/issue129_arm_c_retry_core.py": ["issue-117-133"],
    "scripts/issue133_arm_c_retry_campaign.py": ["issue-117-133"],
    "scripts/issue133_arm_c_retry_direct.py": ["issue-117-133"],
    "scripts/issue133_canonical_environment.py": ["issue-117-133"],
    "scripts/issue133_equality_reduction.py": ["issue-117-133"],
    "scripts/issue133_physical_prelaunch_gate.py": ["issue-117-133"],
    "scripts/issue133_real_builder_dry_run.py": ["issue-117-133"],
    "scripts/issue133_regenerate_corrected_freeze.py": ["issue-117-133"],
    "scripts/issue133_terminal_reduction.py": ["issue-117-133"],
    "docs/implementation/r6-successor-dense-full-integration-117/": ["issue-117-133"],
    # Issue #137 retained evidence lives inside the #117 evidence tree;
    # the narrower #137 subtree fans out to both its semantic group and
    # the broader shared-tree lineage (the #117 prefix rule above also
    # matches, and classification unions all matching rules).
    "docs/implementation/r6-successor-dense-full-integration-117/evidence/arm-c-regime4-diagnosis-137/":
        ["issue-137", "issue-117-133"],

    "scripts/issue137_binding.py": ["issue-137"],
    # Issue #153 Arm-C remediation slice (CPU-only; bundle lives under the
    # #117 implementation area, scripts + tests classified to the
    # issue-117-133 lineage group).
    "scripts/issue153_phase0_inventory.py": ["issue-117-133"],
    "scripts/issue153_producer_delta.py": ["issue-117-133"],
    "scripts/issue153_boundary_matrix.py": ["issue-117-133"],
    "scripts/issue153_manifest.py": ["issue-117-133", "repo-integrity"],
    "tests/test_issue153_arm_c_remediation.py": ["issue-117-133"],
    "scripts/issue137_conclusions.py": ["issue-137"],
    "scripts/issue137_phase1_inventory.py": ["issue-137"],
    "scripts/issue137_probe_driver.py": ["issue-137",
        "issue-74-79"],   # Phase-1 probes feed 74-79 placement lineage
    # (The synthetic docs/implementation/vulkan-arm-c-regime4-diagnosis-137/
    # prefix never matched a tracked path; the real retained #137
    # evidence rule lives with the #117 tree above.)

    "scripts/issue99_artifact_core.py": ["issue-99-103"],
    "scripts/issue99_mini_model.py": ["issue-99-103"],
    "scripts/issue99_proof.py": ["issue-99-103"],
    "scripts/issue101_fixture.py": ["issue-99-103"],
    "scripts/issue101_orchestration.py": ["issue-99-103"],
    "scripts/issue101_proof.py": ["issue-99-103"],
    "scripts/issue103_fixture.py": ["issue-99-103"],
    "scripts/issue103_planner.py": ["issue-99-103"],
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

    "scripts/v0a_correctness_derive.py": ["vulkan-v0-b"],
    "scripts/v0a_correctness_run.py": ["vulkan-v0-b"],
    "scripts/v0a_materialization_derive.py": ["vulkan-v0-b"],
    "scripts/v0a_materialization_run.py": ["vulkan-v0-b"],
    "scripts/v0b_capability_assessment.py": ["vulkan-v0-b"],
    "scripts/v0b_comparability_audit.py": ["vulkan-v0-b"],
    "scripts/v0b_correctness_stability.py": ["vulkan-v0-b"],
    "scripts/v0b_cpu_proof.py": ["vulkan-v0-b"],
    "scripts/v0b_cpu_supplement_derive.py": ["vulkan-v0-b"],
    "scripts/v0b_cpu_supplement_run.py": ["vulkan-v0-b"],
    "scripts/v0b_economics.py": ["vulkan-v0-b"],
    "scripts/v0b_manifest.py": ["vulkan-v0-b"],
    "scripts/v0b_seam_comparison.py": ["vulkan-v0-b"],
    "scripts/v0b_terminal.py": ["vulkan-v0-b"],
    # Retained V0-A/V0-B investigation evidence. test_v0b_reduction
    # reads both trees directly (V0-B consumes accepted V0-A evidence),
    # so both select vulkan-v0-b.
    "docs/investigations/vulkan-v0-a/": ["vulkan-v0-b"],
    "docs/investigations/vulkan-v0-b/": ["vulkan-v0-b"],
    "docs/investigations/vulkan-v0-c/": ["vulkan-v0-b"],
    "scripts/v0c_canonical_run.py": ["vulkan-v0-b"],
    "scripts/v0c_correctness.py": ["vulkan-v0-b"],
    "scripts/v0c_execution_seam.py": ["vulkan-v0-b"],
    "scripts/v0c_manifest.py": ["vulkan-v0-b"],
    "scripts/v0c_vulkan_adapter.py": ["vulkan-v0-b"],
    "tests/test_v0c_canonical_run.py": ["vulkan-v0-b"],
    "tests/test_v0c_correctness.py": ["vulkan-v0-b"],
    "tests/test_v0c_evidence_manifest.py": ["vulkan-v0-b"],
    "tests/test_v0c_execution_seam.py": ["vulkan-v0-b"],
    "tests/test_v0c_vulkan_adapter.py": ["vulkan-v0-b"],

    "scripts/analyze_phase1_p6.py": ["phase1-analysis"],
    "scripts/derive_phase1_placement.py": ["phase1-analysis"],
    "scripts/derive_phase1_placement_v2.py": ["phase1-analysis"],
    "scripts/derive_phase1r_d3_placement.py": ["phase1-analysis"],
    "scripts/derive_phase1r_d4_placement.py": ["phase1-analysis"],
    "scripts/derive_phase1r_d7_placement.py": ["phase1-analysis"],
    # Retained Phase-1 campaign evidence and placement data.
    "docs/benchmarks/results/phase1/": ["phase1-analysis"],
    "docs/investigations/data/": ["phase1-analysis"],
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

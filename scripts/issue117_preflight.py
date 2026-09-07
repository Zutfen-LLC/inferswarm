#!/usr/bin/env python3
"""Issue #117 physical preflight (fail-closed, CPU-only validation).

Before the first correctness-bearing Arm-A run, the frozen preflight record
must prove every identity the gate depends on. This module defines the
record schema and the fail-closed validator. Physical fields (GPU UUIDs,
driver/runtime identities, node filesystem proofs) are collected on the
fabric; this validator re-derives every identity that is derivable from the
accepted repository state and refuses the run when anything is missing,
drifted, or self-inconsistent.

Pure stdlib.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from issue117_applicability import (
    ACCEPTED_INFERSWARM_BASE,
    DELTA_CONTROL_ARTIFACT_MATERIALIZATION_ONLY,
    verify_v5_authority,
)
from issue117_gemma_strategy import (
    ACCEPTED_V5_GEOMETRY,
    MODEL_SUBJECT,
    RESOURCE_SNAPSHOT,
)

PREFLIGHT_SCHEMA = "inferswarm.issue117.physical-preflight/1"

REQUIRED_BACKEND_KEYS = ("torch", "cuda_runtime", "nvidia_driver", "triton", "flashinfer")
REQUIRED_PARTICIPANT_ROLES = (
    "stage-1", "stage-2", "stage-3",
)


class PreflightBlocked(RuntimeError):
    """The preflight record does not permit correctness-bearing execution."""


def build_preflight(
    *,
    inferswarm_head: str,
    inferswarm_clean_worktree: bool,
    freetoken_integration_producer: str,
    freetoken_clean_worktree: bool,
    v5_authority_sha256: Mapping[str, str],
    nodes: Sequence[Mapping[str, Any]],
    candidate_set: Mapping[str, Any],
    qualification_applicability: Sequence[Mapping[str, Any]],
    applicability_audit_digest: str,
    applicability_audit_result: str,
    fixture_digest: str,
    source_descriptors: Mapping[str, Any],
    cold_cache_proofs: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Assemble the frozen preflight record from collected identities."""
    document = {
        "schema": PREFLIGHT_SCHEMA,
        "implementation": {
            "inferswarm_head": inferswarm_head,
            "inferswarm_clean_worktree": bool(inferswarm_clean_worktree),
            "freetoken_integration_producer": freetoken_integration_producer,
            "freetoken_clean_worktree": bool(freetoken_clean_worktree),
            "accepted_inferswarm_base": ACCEPTED_INFERSWARM_BASE,
        },
        "v5_authority_sha256": dict(v5_authority_sha256),
        "model_subject": dict(MODEL_SUBJECT),
        "resource_identity": {
            "coordinator": dict(RESOURCE_SNAPSHOT["coordinator"]),
            "coordinator_cuda_initialized": 0,
            "coordinator_model_weight_bytes_received": 0,
            "coordinator_model_weight_bytes_materialized": 0,
            "compute_units": [
                {key: cu[key] for key in ("cu_id", "node", "gpu_index", "product", "role")}
                for cu in RESOURCE_SNAPSHOT["compute_units"]
            ],
        },
        "nodes": [dict(node) for node in nodes],
        "candidate_set": dict(candidate_set),
        "qualification_applicability": [
            dict(entry) for entry in qualification_applicability],
        "applicability_audit": {
            "audit_digest": applicability_audit_digest,
            "overall_result": applicability_audit_result,
        },
        "integration_fixture_digest": fixture_digest,
        "source_descriptors": dict(source_descriptors),
        "cold_cache_proofs": [dict(proof) for proof in cold_cache_proofs],
    }
    document["preflight_digest"] = _self_digest(document)
    return document


def _self_digest(document: Mapping[str, Any]) -> str:
    from issue99_artifact_core import self_digest
    return self_digest(document, identity_field="preflight_digest")


def validate_preflight(document: Mapping[str, Any], *, repo_root: Path,
                       fixture_path: Path | None = None) -> list[str]:
    """Re-derive every derivable identity; return all failures (empty = pass)."""
    failures: list[str] = []
    if document.get("schema") != PREFLIGHT_SCHEMA:
        return [f"schema mismatch: {document.get('schema')!r}"]
    if document.get("preflight_digest") != _self_digest(document):
        failures.append("preflight_digest self-identity mismatch")

    implementation = document.get("implementation", {})
    for field in ("inferswarm_head", "freetoken_integration_producer"):
        value = implementation.get(field, "")
        if not (isinstance(value, str) and len(value) == 40
                and all(char in "0123456789abcdef" for char in value)):
            failures.append(f"implementation.{field} is not a git SHA: {value!r}")
    if not implementation.get("inferswarm_clean_worktree"):
        failures.append("inferswarm worktree is not clean")
    if not implementation.get("freetoken_clean_worktree"):
        failures.append("freetoken worktree is not clean")
    if implementation.get("accepted_inferswarm_base") != ACCEPTED_INFERSWARM_BASE:
        failures.append("accepted inferswarm base not bound")

    # V5 authority byte identity: pinned values must equal accepted values,
    # and (when the pins are right) the actual repository must still match.
    pinned = document.get("v5_authority_sha256", {})
    from issue117_applicability import V5_AUTHORITY_FILES
    pins_match = pinned.keys() == V5_AUTHORITY_FILES.keys() and all(
        pinned.get(relative) == expected
        for relative, expected in V5_AUTHORITY_FILES.items())
    if not pins_match:
        failures.append("v5 authority pins do not match the accepted identities")
    else:
        try:
            verify_v5_authority(repo_root)
        except Exception as error:
            failures.append(f"v5 authority drift in repository: {error}")

    # Model/representation/backend identity
    subject = document.get("model_subject", {})
    for field in ("model_id", "revision", "checkpoint_sha256", "representation", "execution"):
        if subject.get(field) != MODEL_SUBJECT.get(field):
            failures.append(f"model_subject.{field} drift: {subject.get(field)!r}")
    backend = subject.get("backend", {})
    for key in REQUIRED_BACKEND_KEYS:
        if backend.get(key) != MODEL_SUBJECT["backend"][key]:
            failures.append(f"model_subject.backend.{key} drift: {backend.get(key)!r}")

    # Coordinator invariants
    resource = document.get("resource_identity", {})
    if resource.get("coordinator", {}).get("node") != "inferswarm00" \
            or not resource.get("coordinator", {}).get("cpu_only"):
        failures.append("coordinator identity is not the CPU-only inferswarm00")
    for field in ("coordinator_cuda_initialized",
                  "coordinator_model_weight_bytes_received",
                  "coordinator_model_weight_bytes_materialized"):
        if resource.get(field) != 0:
            failures.append(f"{field} != 0")

    # Node records: exact GPU identity per Compute Unit
    nodes = document.get("nodes", [])
    node_index = {}
    for node in nodes:
        missing = [field for field in
                   ("node", "gpu_uuid", "gpu_product", "compute_capability",
                    "torch", "cuda_runtime", "nvidia_driver", "triton", "flashinfer")
                   if not node.get(field)]
        if missing:
            failures.append(f"node record {node.get('node', '?')!r} missing {missing}")
        node_index[node.get("node")] = node
        for key in REQUIRED_BACKEND_KEYS:
            if node.get(key) and node.get(key) != MODEL_SUBJECT["backend"][key]:
                failures.append(f"node {node.get('node')} {key} drift: {node.get(key)}")
    for cu in resource.get("compute_units", []):
        node = node_index.get(cu["node"])
        if node is None:
            failures.append(f"no node record for {cu['node']}")
        elif node.get("gpu_product") != cu["product"]:
            failures.append(
                f"{cu['cu_id']}: product drift {node.get('gpu_product')!r} != {cu['product']!r}")

    # Candidate set + qualification applicability
    candidate_set = document.get("candidate_set", {})
    if not candidate_set.get("candidates"):
        failures.append("candidate set is empty")
    applicability = {
        entry.get("candidate_id"): entry
        for entry in document.get("qualification_applicability", [])
    }
    v5_candidates = []
    for candidate in candidate_set.get("candidates", []):
        entry = applicability.get(candidate.get("candidate_id"))
        if entry is None:
            failures.append(f"no qualification-applicability record for "
                            f"{candidate.get('candidate_id')}")
            continue
        if entry.get("applicability") not in (
                "QUALIFICATION_APPLICABLE", "QUALIFICATION_NOT_APPLICABLE"):
            failures.append(f"malformed applicability for {candidate.get('candidate_id')}")
        if candidate.get("stage_structure") == [
                dict(stage) for stage in ACCEPTED_V5_GEOMETRY]:
            v5_candidates.append((candidate, entry))
    if not v5_candidates:
        failures.append("candidate set does not contain the accepted V5 geometry")
    else:
        for candidate, entry in v5_candidates:
            if entry.get("applicability") != "QUALIFICATION_APPLICABLE":
                failures.append("accepted V5 candidate did not resolve "
                                "QUALIFICATION_APPLICABLE")

    # Applicability audit
    audit = document.get("applicability_audit", {})
    if audit.get("overall_result") != DELTA_CONTROL_ARTIFACT_MATERIALIZATION_ONLY:
        failures.append(f"applicability audit result: {audit.get('overall_result')!r}")
    from issue117_applicability import canonical_issue117_audit
    expected_audit = canonical_issue117_audit()
    if audit.get("audit_digest") != expected_audit["audit_digest"]:
        failures.append("applicability audit digest is not the frozen #117 audit")

    # Integration fixture
    if fixture_path is not None:
        try:
            fixture_document = json.loads(fixture_path.read_text())
            if fixture_document.get("fixture_digest") != document.get("integration_fixture_digest"):
                failures.append("integration fixture digest mismatch")
        except (OSError, ValueError) as error:
            failures.append(f"fixture unreadable: {error}")
    if not document.get("integration_fixture_digest"):
        failures.append("integration fixture digest missing")

    # Source descriptors
    descriptors = document.get("source_descriptors", {})
    if not descriptors.get("descriptors"):
        failures.append("no authorized Source descriptors frozen")
    if not descriptors.get("descriptors_digest"):
        failures.append("source descriptors digest missing")

    # Cold-cache proofs
    proofs = document.get("cold_cache_proofs", [])
    if not proofs:
        failures.append("no cold-cache proofs frozen")
    for proof in proofs:
        for field in ("participant_id", "cache_root", "materialized_root"):
            if not proof.get(field):
                failures.append(f"cold-cache proof missing {field}")
        for field in ("cache_entry_count", "cache_bytes", "materialized_entry_count",
                      "materialized_bytes"):
            if proof.get(field) != 0:
                failures.append(f"cold-cache proof {field} != 0")
        if not proof.get("no_symlink_alias"):
            failures.append("cold-cache proof does not exclude symlink/hardlink aliasing")
        if not proof.get("source_possession_separate"):
            failures.append("cold-cache proof does not separate source possession")
    return failures


def require_preflight_valid(document: Mapping[str, Any], *, repo_root: Path,
                            fixture_path: Path | None = None) -> None:
    failures = validate_preflight(document, repo_root=repo_root, fixture_path=fixture_path)
    if failures:
        raise PreflightBlocked(
            "physical preflight failed:\n" + "\n".join(f"  - {f}" for f in failures))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("preflight", type=Path)
    parser.add_argument("--repo-root", type=Path,
                        default=Path(__file__).resolve().parents[1])
    parser.add_argument("--fixture", type=Path, default=None)
    args = parser.parse_args(argv)
    document = json.loads(args.preflight.read_text())
    failures = validate_preflight(document, repo_root=args.repo_root,
                                  fixture_path=args.fixture)
    if failures:
        print("PREFLIGHT_INVALID")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("PREFLIGHT_VALID")
    return 0


if __name__ == "__main__":
    sys.exit(main())

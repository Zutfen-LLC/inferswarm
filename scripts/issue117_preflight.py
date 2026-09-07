#!/usr/bin/env python3
"""Issue #117 physical preflight (fail-closed, CPU-only validation).

Before the first correctness-bearing Arm-A run, the frozen preflight record
must prove every identity the gate depends on. This module defines the
record schema and the fail-closed validator. Physical fields are collected
on the fabric; this validator re-derives every identity that is derivable
from the accepted repository state and refuses the run when anything is
missing, drifted, or self-inconsistent.

Bindings enforced here (fail-closed):

- the FreeToken integration producer is the EXACT SHA the frozen
  applicability audit was built for (``FROZEN_INTEGRATION_PRODUCER``) — a
  random syntactically valid SHA cannot pass;
- every Compute Unit — never one record per node — binds node, GPU index,
  the exact retained V5 GPU UUID, exact product, exact compute capability,
  role, and runtime identity, all from the accepted retained evidence
  (``ACCEPTED_COMPUTE_UNITS``), not from freshly supplied values;
- the source descriptor set is digest-bound and re-verified;
- the candidate set and every qualification-applicability record are
  digest-bound; each candidate's subject digest must recompute;
- the committed fixture is validated in full, not merely digest-compared;
- cold-cache proofs are mechanically collected filesystem facts (walked
  entries with lstat facts), not caller-supplied booleans; symlink and
  hardlink aliasing must be absent from the collected facts, and source
  possession must be disjoint from the participant cold roots.

Pure stdlib.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from issue117_applicability import (
    ACCEPTED_COMPUTE_UNITS,
    ACCEPTED_PHYSICAL_IDENTITY_FILES,
    ACCEPTED_INFERSWARM_BASE,
    DELTA_CONTROL_ARTIFACT_MATERIALIZATION_ONLY,
    FROZEN_INTEGRATION_PRODUCER,
    V5_AUTHORITY_FILES,
    canonical_issue117_audit,
    verify_v5_authority,
)
from issue117_gemma_strategy import (
    ACCEPTED_V5_GEOMETRY,
    MODEL_SUBJECT,
    RESOURCE_SNAPSHOT,
)
from issue99_artifact_core import self_digest

PREFLIGHT_SCHEMA = "inferswarm.issue117.physical-preflight/2"
COLD_CACHE_PROOF_SCHEMA = "inferswarm.issue117.cold-cache-proof/1"
COLD_CACHE_COLLECTOR = "issue117.preflight.cold-cache-collector/1"

REQUIRED_BACKEND_KEYS = ("torch", "cuda_runtime", "nvidia_driver", "triton", "flashinfer")

CU_RECORD_FIELDS = ("cu_id", "node", "gpu_index", "gpu_uuid", "gpu_product",
                    "compute_capability", "role")


class PreflightBlocked(RuntimeError):
    """The preflight record does not permit correctness-bearing execution."""


# ---------------------------------------------------------------------------
# Mechanically collected cold-cache proofs
# ---------------------------------------------------------------------------


def _scan_root(root: Path) -> dict[str, Any]:
    """Collect filesystem facts for one root (lstat-based, no booleans)."""
    facts: dict[str, Any] = {
        "root": str(root),
        "root_exists": root.is_dir(),
        "root_is_symlink": root.is_symlink(),
        "entries": [],
    }
    if root.is_dir():
        for path in sorted(root.rglob("*")):
            stat = path.lstat()
            facts["entries"].append({
                "path": path.relative_to(root).as_posix(),
                "is_symlink": path.is_symlink(),
                "hardlink_count": 1 if path.is_symlink() else stat.st_nlink,
                "size": 0 if path.is_symlink() or path.is_dir() else stat.st_size,
            })
    facts["entry_count"] = len(facts["entries"])
    facts["total_bytes"] = sum(entry["size"] for entry in facts["entries"])
    facts["symlink_entries"] = [entry["path"] for entry in facts["entries"]
                                if entry["is_symlink"]]
    facts["hardlink_entries"] = [entry["path"] for entry in facts["entries"]
                                 if entry["hardlink_count"] > 1]
    return facts


def collect_cold_cache_proof(*, participant_id: str, cache_root: Path,
                             materialized_root: Path) -> dict[str, Any]:
    """Mechanically collect a cold-cache proof from filesystem facts.

    The fabric-side collector runs this per participant against the dedicated
    issue #117 roots; the validator re-derives every conclusion from the
    recorded facts instead of trusting caller booleans.
    """
    proof = {
        "schema": COLD_CACHE_PROOF_SCHEMA,
        "collector": COLD_CACHE_COLLECTOR,
        "participant_id": participant_id,
        "cache_facts": _scan_root(Path(cache_root)),
        "materialized_facts": _scan_root(Path(materialized_root)),
    }
    proof["proof_digest"] = self_digest(proof, identity_field="proof_digest")
    return proof


def _validate_collected_facts(facts: Mapping[str, Any], label: str,
                              failures: list[str]) -> None:
    entries = facts.get("entries")
    if not isinstance(entries, list):
        failures.append(f"{label}: no collected entry listing")
        return
    if facts.get("entry_count") != len(entries):
        failures.append(f"{label}: recorded entry_count != collected listing")
    if facts.get("total_bytes") != sum(
            entry.get("size", 0) for entry in entries):
        failures.append(f"{label}: recorded total_bytes != collected listing")
    if facts.get("symlink_entries") != [entry["path"] for entry in entries
                                        if entry.get("is_symlink")]:
        failures.append(f"{label}: symlink accounting inconsistent")
    if facts.get("hardlink_entries") != [entry["path"] for entry in entries
                                         if entry.get("hardlink_count", 1) > 1]:
        failures.append(f"{label}: hardlink accounting inconsistent")
    if facts.get("root_is_symlink"):
        failures.append(f"{label}: root itself is a symlink")
    if not facts.get("root_exists"):
        failures.append(f"{label}: root missing at collection time")


def _paths_disjoint(a: str, b: str) -> bool:
    from os.path import abspath
    a, b = abspath(a), abspath(b)
    return not (a == b or a.startswith(b + os.sep) or b.startswith(a + os.sep))


def candidate_set_digest(candidates: Sequence[Mapping[str, Any]]) -> str:
    """The digest binding the exact candidate set identity."""
    return self_digest({"candidates": [dict(c) for c in candidates]},
                       identity_field="candidate_set_digest")


def source_descriptors_digest(descriptors: Sequence[Mapping[str, Any]]) -> str:
    """The digest binding the exact authorized Source descriptor set."""
    return self_digest({"descriptors": [dict(d) for d in descriptors]},
                       identity_field="descriptors_digest")


# ---------------------------------------------------------------------------
# Preflight record
# ---------------------------------------------------------------------------


def build_preflight(
    *,
    inferswarm_head: str,
    inferswarm_clean_worktree: bool,
    freetoken_integration_producer: str,
    freetoken_clean_worktree: bool,
    v5_authority_sha256: Mapping[str, str],
    compute_units: Sequence[Mapping[str, Any]],
    candidate_set: Mapping[str, Any],
    qualification_applicability: Sequence[Mapping[str, Any]],
    applicability_audit_digest: str,
    applicability_audit_result: str,
    fixture_digest: str,
    source_descriptors: Mapping[str, Any],
    cold_cache_proofs: Sequence[Mapping[str, Any]],
    source_possession_roots: Sequence[str] = (),
    coordinator_cuda_initialized: int = 0,
    coordinator_model_weight_bytes_received: int = 0,
    coordinator_model_weight_bytes_materialized: int = 0,
) -> dict[str, Any]:
    """Assemble the frozen preflight record from collected identities.

    The coordinator counters are fabric-collected facts supplied by the
    orchestrator, not constants: the builder records whatever was observed,
    and the validator refuses any nonzero observation.
    """
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
            "coordinator_cuda_initialized": int(coordinator_cuda_initialized),
            "coordinator_model_weight_bytes_received":
                int(coordinator_model_weight_bytes_received),
            "coordinator_model_weight_bytes_materialized":
                int(coordinator_model_weight_bytes_materialized),
            "compute_units": [
                {key: cu[key] for key in ("cu_id", "node", "gpu_index", "product", "role")}
                for cu in RESOURCE_SNAPSHOT["compute_units"]
            ],
        },
        "compute_units": [dict(cu) for cu in compute_units],
        "source_possession_roots": [str(root) for root in source_possession_roots],
        "candidate_set": {
            "candidates": [dict(candidate) for candidate in candidate_set["candidates"]],
            "candidate_set_digest": candidate_set["candidate_set_digest"],
        },
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
    return self_digest(document, identity_field="preflight_digest")


def validate_preflight(document: Mapping[str, Any], *, repo_root: Path,
                       fixture_path: Path | None = None) -> list[str]:
    """Re-derive every derivable identity; return all failures (empty = pass).

    ``fixture_path`` defaults to the committed integration fixture under
    ``repo_root``; the committed fixture is always fully validated, never
    merely digest-compared.
    """
    failures: list[str] = []
    if fixture_path is None:
        fixture_path = (repo_root / "docs/implementation/"
                        "r6-successor-dense-full-integration-117/evidence/"
                        "integration-fixture.json")
    if document.get("schema") != PREFLIGHT_SCHEMA:
        return [f"schema mismatch: {document.get('schema')!r}"]
    if document.get("preflight_digest") != _self_digest(document):
        failures.append("preflight_digest self-identity mismatch")

    implementation = document.get("implementation", {})
    if implementation.get("freetoken_integration_producer") \
            != FROZEN_INTEGRATION_PRODUCER:
        failures.append(
            "freetoken_integration_producer is not the exact producer the "
            f"frozen applicability audit binds ({FROZEN_INTEGRATION_PRODUCER!r}); "
            f"got {implementation.get('freetoken_integration_producer')!r}")
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

    # V5 authority + physical identity byte pins: pinned values must equal
    # accepted values, and (when the pins are right) the actual repository
    # must still match.
    pinned = document.get("v5_authority_sha256", {})
    expected_pins = {**V5_AUTHORITY_FILES, **ACCEPTED_PHYSICAL_IDENTITY_FILES}
    pins_match = pinned.keys() == expected_pins.keys() and all(
        pinned.get(relative) == expected
        for relative, expected in expected_pins.items())
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

    # Compute Unit records: exact per-CU identity from the accepted evidence
    snapshot_roles = {cu["cu_id"]: cu["role"]
                      for cu in resource.get("compute_units", [])}
    accepted_by_cu = {cu["cu_id"]: cu for cu in ACCEPTED_COMPUTE_UNITS}
    records_by_cu: dict[str, list[Mapping[str, Any]]] = {}
    for record in document.get("compute_units", []):
        records_by_cu.setdefault(record.get("cu_id"), []).append(record)
    for cu_id, accepted in accepted_by_cu.items():
        records = records_by_cu.get(cu_id, [])
        if len(records) != 1:
            failures.append(f"{cu_id}: expected exactly one Compute Unit record, "
                            f"found {len(records)}")
            continue
        record = records[0]
        for field in CU_RECORD_FIELDS:
            if not record.get(field) and record.get(field) != 0:
                failures.append(f"{cu_id}: Compute Unit record missing {field}")
        runtime = record.get("runtime", {})
        for key in REQUIRED_BACKEND_KEYS:
            if runtime.get(key) != MODEL_SUBJECT["backend"][key]:
                failures.append(f"{cu_id}: runtime {key} drift: {runtime.get(key)!r}")
        if not isinstance(record.get("node_identity"), Mapping) \
                or not record["node_identity"]:
            failures.append(f"{cu_id}: exact node/runtime identity missing")
            continue
        fingerprint = record["node_identity"].get("node_fingerprint")
        if not (isinstance(fingerprint, str) and len(fingerprint) == 64
                and all(char in "0123456789abcdef" for char in fingerprint)):
            failures.append(
                f"{cu_id}: node_identity carries no collected node/runtime "
                "identity digest (64-hex node_fingerprint required)")
        if record.get("gpu_uuid") != accepted["gpu_uuid"]:
            failures.append(
                f"{cu_id}: gpu_uuid is not the retained V5 identity "
                f"({record.get('gpu_uuid')!r} != {accepted['gpu_uuid']!r})")
        if record.get("node") != accepted["node"] \
                or record.get("gpu_index") != accepted["gpu_index"]:
            failures.append(f"{cu_id}: node/gpu_index drift")
        if record.get("gpu_product") != accepted["product"]:
            failures.append(
                f"{cu_id}: gpu_product is not the retained identity "
                f"({record.get('gpu_product')!r} != {accepted['product']!r})")
        if record.get("compute_capability") != accepted["compute_capability"]:
            failures.append(
                f"{cu_id}: compute_capability is not the retained measured "
                f"identity ({record.get('compute_capability')!r} != "
                f"{accepted['compute_capability']!r})")
        if record.get("role") != snapshot_roles.get(cu_id):
            failures.append(f"{cu_id}: role drift vs the frozen snapshot")
    extra_cus = sorted(set(records_by_cu) - set(accepted_by_cu) - {None})
    if extra_cus:
        failures.append(f"unrecognized Compute Unit records: {extra_cus}")

    # Candidate set identity: digest-bound, subject digests recomputed
    candidate_set = document.get("candidate_set", {})
    candidates = candidate_set.get("candidates", [])
    if not candidates:
        failures.append("candidate set is empty")
    recomputed_set_digest = candidate_set_digest(candidates)
    if candidate_set.get("candidate_set_digest") != recomputed_set_digest:
        failures.append("candidate_set_digest does not recompute from the "
                        "recorded candidate set")
    applicability: dict[str, Mapping[str, Any]] = {}
    for entry in document.get("qualification_applicability", []):
        digest = entry.get("record_digest")
        recomputed = self_digest(
            {key: value for key, value in entry.items() if key != "record_digest"},
            identity_field="record_digest")
        if digest != recomputed:
            failures.append(
                f"qualification-applicability record for "
                f"{entry.get('candidate_id')!r} is not digest-bound")
        applicability[entry.get("candidate_id")] = entry
    v5_candidates = []
    for candidate in candidates:
        subject = candidate.get("qualification_subject")
        subject_digest = candidate.get("qualification_subject_digest")
        if not isinstance(subject, Mapping) or not subject_digest:
            failures.append(
                f"candidate {candidate.get('candidate_id')!r} carries no "
                "qualification subject identity")
            continue
        from issue74_methodology import canonical_json_bytes
        from issue99_artifact_core import digest_of_bytes
        if digest_of_bytes(canonical_json_bytes(subject)) != subject_digest:
            failures.append(
                f"candidate {candidate.get('candidate_id')!r} subject digest "
                "does not recompute from its subject")
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

    # Applicability audit: frozen, producer-bound, and consistent with the
    # producer identity this record binds
    audit = document.get("applicability_audit", {})
    if audit.get("overall_result") != DELTA_CONTROL_ARTIFACT_MATERIALIZATION_ONLY:
        failures.append(f"applicability audit result: {audit.get('overall_result')!r}")
    try:
        expected_audit = canonical_issue117_audit(repo_root)
        if audit.get("audit_digest") != expected_audit["audit_digest"]:
            failures.append("applicability audit digest is not the frozen "
                            "#117 producer-bound audit")
        elif expected_audit["authority"]["integration_producer"] \
                != implementation.get("freetoken_integration_producer"):
            failures.append("applicability audit producer binding does not "
                            "match the record's integration producer")
    except Exception as error:
        failures.append(f"applicability audit unavailable: {error}")

    # Integration fixture: full validation of the committed document
    if fixture_path is not None:
        try:
            from issue117_integration_fixture import validate_fixture_document
            fixture_document = json.loads(fixture_path.read_text())
            validate_fixture_document(fixture_document)
            if fixture_document.get("fixture_digest") \
                    != document.get("integration_fixture_digest"):
                failures.append("integration fixture digest mismatch")
        except (OSError, ValueError) as error:
            failures.append(f"fixture unreadable: {error}")
        except Exception as error:
            failures.append(f"fixture validation failed: {error}")
    if not document.get("integration_fixture_digest"):
        failures.append("integration fixture digest missing")

    # Source descriptors: digest-bound set of exact descriptors
    descriptors = document.get("source_descriptors", {})
    descriptor_list = descriptors.get("descriptors")
    if not descriptor_list:
        failures.append("no authorized Source descriptors frozen")
    else:
        recomputed = source_descriptors_digest(descriptor_list)
        if descriptors.get("descriptors_digest") != recomputed:
            failures.append("source descriptors digest does not recompute")
        for descriptor in descriptor_list:
            if not isinstance(descriptor, Mapping) \
                    or not descriptor.get("source_id") or not descriptor.get("endpoint"):
                failures.append("malformed source descriptor")

    # Cold-cache proofs: mechanically collected filesystem facts
    proofs = document.get("cold_cache_proofs", [])
    if not proofs:
        failures.append("no cold-cache proofs frozen")
    possession_roots = [str(root) for root in document.get("source_possession_roots", [])]
    for proof in proofs:
        if proof.get("schema") != COLD_CACHE_PROOF_SCHEMA \
                or proof.get("collector") != COLD_CACHE_COLLECTOR:
            failures.append(
                f"cold-cache proof for {proof.get('participant_id')!r} is not "
                "a mechanically collected record")
            continue
        if proof.get("proof_digest") != self_digest(
                dict(proof), identity_field="proof_digest"):
            failures.append(
                f"cold-cache proof for {proof.get('participant_id')!r} has a "
                "self-identity mismatch")
        cache_facts = proof.get("cache_facts", {})
        materialized_facts = proof.get("materialized_facts", {})
        _validate_collected_facts(cache_facts, f"{proof.get('participant_id')} cache", failures)
        _validate_collected_facts(materialized_facts,
                                  f"{proof.get('participant_id')} materialized", failures)
        if cache_facts.get("entry_count") != 0 or cache_facts.get("total_bytes") != 0:
            failures.append(
                f"cold-cache proof {proof.get('participant_id')!r}: cache root "
                "is not empty at collection")
        if materialized_facts.get("entry_count") != 0 \
                or materialized_facts.get("total_bytes") != 0:
            failures.append(
                f"cold-cache proof {proof.get('participant_id')!r}: materialized "
                "root is not empty at collection")
        if cache_facts.get("symlink_entries") or cache_facts.get("hardlink_entries") \
                or materialized_facts.get("symlink_entries") \
                or materialized_facts.get("hardlink_entries"):
            failures.append(
                f"cold-cache proof {proof.get('participant_id')!r}: symlink/"
                "hardlink aliasing present in collected facts")
        for possession in possession_roots:
            for root_fact in (cache_facts.get("root", ""), materialized_facts.get("root", "")):
                if root_fact and not _paths_disjoint(possession, root_fact):
                    failures.append(
                        f"cold-cache proof {proof.get('participant_id')!r}: source "
                        f"possession {possession!r} is not separate from {root_fact!r}")
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

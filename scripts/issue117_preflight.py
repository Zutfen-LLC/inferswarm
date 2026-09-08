#!/usr/bin/env python3
"""Issue #117 physical preflight (fail-closed, CPU-only validation).

Before the first correctness-bearing Arm-A run, the frozen preflight record
must prove every identity the gate depends on. This module defines the
record schema and the fail-closed validator. Physical fields are collected
on the fabric; this validator re-derives every identity that is derivable
from the accepted repository state and refuses the run when anything is
missing, drifted, or self-inconsistent.

Bindings enforced here (fail-closed):

- **repository identities are mechanically collected Git evidence, never
  caller assertions.** The InferSwarm and FreeToken records are collected
  from the actual repositories (``git rev-parse HEAD``, ``git status
  --porcelain``); the validator re-checks the InferSwarm checkout against
  ``repo_root`` and the FreeToken checkout against ``freetoken_root`` when
  the repository is supplied, and always requires the FreeToken HEAD to
  equal the exact producer the frozen applicability audit binds. A SHA that
  merely looks valid cannot pass: it must equal the observed checkout.
- the FreeToken integration producer is the EXACT SHA the frozen
  applicability audit was built for (``FROZEN_INTEGRATION_PRODUCER``);
- every Compute Unit — never one record per node — binds node, GPU index,
  the exact retained V5 GPU UUID, exact product, exact compute capability,
  role, and runtime identity, all from the accepted retained evidence
  (``ACCEPTED_COMPUTE_UNITS``), not from freshly supplied values;
- the source descriptor set is digest-bound and re-verified;
- **qualification applicability is derived, never trusted.** Every stored
  applicability record is compared against an independently derived verdict:
  the validator recomputes each candidate's execution-equality subject
  digest and compares it against the accepted V5 qualification subject
  independently reconstructed from byte-pinned historical evidence
  (``V5_QUALIFICATION_SUBJECT_PROVENANCE_RECOVERED``; the record is loaded
  and its evidence pins re-verified on every derivation). It refuses any
  fabricated ``QUALIFICATION_APPLICABLE`` and fails closed to
  ``QUALIFICATION_NOT_APPLICABLE`` whenever the evidence is missing,
  drifted, or tampered;
- the committed fixture is validated in full, not merely digest-compared;
- cold-cache proofs are mechanically collected filesystem facts (walked
  entries with lstat facts), not caller-supplied booleans; symlink and
  hardlink aliasing must be absent from the collected facts;
- **source possession is proven, not asserted.** Every local (``file://``)
  Source must carry a mechanically collected possession record whose root
  exists, is not a symlink, and is disjoint from every participant cache and
  materialized root; an empty possession set with local Sources present
  cannot pass. Remote Sources must carry an explicit remote source-kind
  identity whose acquisition semantics make local aliasing impossible.

Pure stdlib.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
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
from issue117_planner import (
    MACHINERY_LOCAL_SUBJECT_KEYS,
    QUALIFICATION_APPLICABLE,
    QUALIFICATION_NOT_APPLICABLE,
    QUALIFICATION_POLICY_STRICT,
    evaluate_qualification_applicability,
)
from issue99_artifact_core import self_digest

PREFLIGHT_SCHEMA = "inferswarm.issue117.physical-preflight/3"
COLD_CACHE_PROOF_SCHEMA = "inferswarm.issue117.cold-cache-proof/1"
COLD_CACHE_COLLECTOR = "issue117.preflight.cold-cache-collector/1"
REPOSITORY_IDENTITY_SCHEMA = "inferswarm.issue117.repository-identity/1"
REPOSITORY_IDENTITY_COLLECTOR = "issue117.preflight.repository-identity-collector/1"
SOURCE_POSSESSION_SCHEMA = "inferswarm.issue117.source-possession/1"

REQUIRED_BACKEND_KEYS = ("torch", "cuda_runtime", "nvidia_driver", "triton", "flashinfer")

CU_RECORD_FIELDS = ("cu_id", "node", "gpu_index", "gpu_uuid", "gpu_product",
                    "compute_capability", "role")

#: Source descriptor kinds. ``local_file`` Sources require proven possession;
#: ``remote_object`` Sources acquire over a network endpoint whose semantics
#: make local path aliasing impossible.
LOCAL_SOURCE_KIND = "local_file"
REMOTE_SOURCE_KIND = "remote_object"
SOURCE_KINDS = (LOCAL_SOURCE_KIND, REMOTE_SOURCE_KIND)


class PreflightBlocked(RuntimeError):
    """The preflight record does not permit correctness-bearing execution."""


# ---------------------------------------------------------------------------
# Mechanically collected repository identities (InferSwarm / FreeToken)
# ---------------------------------------------------------------------------


def _git_text(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True)
    if result.returncode != 0:
        raise PreflightBlocked(
            f"git {' '.join(args[:2])} failed at {root}: "
            f"{result.stderr.decode(errors='replace').strip()[:200]}")
    return result.stdout.decode()


def collect_repository_identity(root: Path, *, role: str,
                                integration_producer: str | None = None) -> dict[str, Any]:
    """Mechanically collect the Git identity of an actual repository checkout.

    Collection reads ``git rev-parse HEAD``, ``git status --porcelain``, and
    branch telemetry from the real checkout. When ``integration_producer`` is
    supplied (FreeToken), collection itself refuses any checkout whose HEAD
    is not exactly the producer being collected for. Branch/ref names are
    telemetry only and are never authority.
    """
    root = Path(root).resolve()
    if not (root / ".git").exists():
        raise PreflightBlocked(f"{root} is not a Git repository")
    head = _git_text(root, "rev-parse", "HEAD").strip()
    porcelain = _git_text(root, "status", "--porcelain")
    branch = _git_text(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
    if integration_producer is not None and head != integration_producer:
        raise PreflightBlocked(
            f"{role}: checkout HEAD {head!r} is not the integration producer "
            f"{integration_producer!r} being collected for")
    record = {
        "schema": REPOSITORY_IDENTITY_SCHEMA,
        "collector": REPOSITORY_IDENTITY_COLLECTOR,
        "role": role,
        "repo_root": str(root),
        "head": head,
        "branch": branch,
        "porcelain": porcelain,
        "clean": porcelain == "",
    }
    if integration_producer is not None:
        record["integration_producer"] = integration_producer
    record["repository_identity_digest"] = self_digest(
        record, identity_field="repository_identity_digest")
    return record


def _validate_repository_identity(record: Mapping[str, Any], *, role: str,
                                  failures: list[str]) -> None:
    if record.get("schema") != REPOSITORY_IDENTITY_SCHEMA \
            or record.get("collector") != REPOSITORY_IDENTITY_COLLECTOR:
        failures.append(f"{role} identity is not a mechanically collected record")
        return
    if record.get("repository_identity_digest") != self_digest(
            {key: value for key, value in record.items()
             if key != "repository_identity_digest"},
            identity_field="repository_identity_digest"):
        failures.append(f"{role} identity record is edited (self-identity mismatch)")
        return
    head = record.get("head", "")
    if not (isinstance(head, str) and len(head) == 40
            and all(char in "0123456789abcdef" for char in head)):
        failures.append(f"{role} identity head is not a git SHA: {head!r}")
    if not isinstance(record.get("porcelain"), str):
        failures.append(f"{role} identity carries no collected porcelain evidence")
    if record.get("clean") is not (record.get("porcelain") == ""):
        failures.append(f"{role} identity cleanliness is not derived from the "
                        "collected porcelain evidence")


def _recheck_repository_identity(record: Mapping[str, Any], *, root: Path,
                                 role: str, failures: list[str]) -> None:
    """Independently re-derive the identity from the actual checkout."""
    try:
        observed_head = _git_text(root, "rev-parse", "HEAD").strip()
        observed_porcelain = _git_text(root, "status", "--porcelain")
    except PreflightBlocked as error:
        failures.append(f"{role} re-check failed: {error}")
        return
    if record.get("head") != observed_head:
        failures.append(
            f"{role} identity head {record.get('head')!r} does not equal the "
            f"observed checkout {observed_head!r}")
    if record.get("porcelain") != observed_porcelain:
        failures.append(
            f"{role} identity porcelain evidence does not equal the observed "
            "checkout state")


# ---------------------------------------------------------------------------
# Mechanically collected cold-cache proofs and source possession
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


def collect_source_possession_record(*, source_id: str, root: Path) -> dict[str, Any]:
    """Mechanically collect one local Source's possession facts."""
    record = {
        "schema": SOURCE_POSSESSION_SCHEMA,
        "collector": COLD_CACHE_COLLECTOR,
        "source_id": source_id,
        "facts": _scan_root(Path(root)),
    }
    record["possession_digest"] = self_digest(
        record, identity_field="possession_digest")
    return record


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


def possession_root_for(descriptor: Mapping[str, Any]) -> str | None:
    """The local possession root implied by one Source descriptor.

    ``file://`` Sources possess exactly the endpoint directory (unless an
    explicit possession root was recorded at authorization); remote Sources
    possess nothing locally.
    """
    if descriptor.get("source_kind") == REMOTE_SOURCE_KIND:
        return None
    if descriptor.get("possession_root"):
        return str(descriptor["possession_root"])
    endpoint = str(descriptor.get("endpoint", ""))
    if endpoint.startswith("file://"):
        return endpoint[len("file://"):]
    return endpoint or None


def _qualification_policy() -> dict[str, Any]:
    """The strict accepted qualification policy, from retained evidence."""
    from issue117_applicability import ACCEPTED_TERMINAL_ADJUDICATION_SHA256
    return {
        "policy": QUALIFICATION_POLICY_STRICT,
        "accepted_dispositions": ("V5_QUALIFICATION_PASS",),
        "accepted_adjudication_sha256": ACCEPTED_TERMINAL_ADJUDICATION_SHA256,
        "machinery_local_subject_keys": MACHINERY_LOCAL_SUBJECT_KEYS,
        "required_for_admission": True,
    }


def derive_candidate_applicability(
        candidates: Sequence[Mapping[str, Any]],
        *, inferswarm_root: Path | None = None,
) -> dict[str, dict[str, Any]]:
    """Independently derive qualification applicability for every candidate.

    The accepted V5 qualification subject was recovered from retained
    historical evidence (``V5_QUALIFICATION_SUBJECT_PROVENANCE_RECOVERED``,
    2026-09-07; see ``issue117_accepted_subject``). Applicability is the
    ordinary generic-gate verdict: the candidate's execution-equality
    subject digest must equal the accepted record's subject digest, where
    the accepted record is loaded (and byte-pinned evidence re-verified) on
    every call — never trusted from a stored record. A candidate cannot
    self-author authority: only the independently reconstructed accepted
    record enters the gate. Missing, drifted, or tampered evidence makes
    every candidate NOT_APPLICABLE.
    """
    policy = _qualification_policy()
    records: list[Mapping[str, Any]] = []
    try:
        from issue117_gemma_strategy import retained_v5_qualification_authority
        records.append(retained_v5_qualification_authority(inferswarm_root))
    except Exception:
        pass  # fail closed below: no accepted evidence -> NOT_APPLICABLE
    derived: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        candidate_id = str(candidate.get("candidate_id"))
        try:
            derived[candidate_id] = evaluate_qualification_applicability(
                candidate, records, policy)
        except Exception as error:
            derived[candidate_id] = {
                "status": QUALIFICATION_NOT_APPLICABLE,
                "reason": f"EVALUATION_REFUSED: {str(error).splitlines()[0][:160]}",
            }
    return derived


# ---------------------------------------------------------------------------
# Preflight record
# ---------------------------------------------------------------------------


def build_preflight(
    *,
    inferswarm_identity: Mapping[str, Any],
    freetoken_identity: Mapping[str, Any],
    v5_authority_sha256: Mapping[str, str],
    compute_units: Sequence[Mapping[str, Any]],
    candidate_set: Mapping[str, Any],
    qualification_applicability: Sequence[Mapping[str, Any]],
    applicability_audit_digest: str,
    applicability_audit_result: str,
    fixture_digest: str,
    source_descriptors: Mapping[str, Any],
    source_possession_records: Sequence[Mapping[str, Any]],
    cold_cache_proofs: Sequence[Mapping[str, Any]],
    coordinator_cuda_initialized: int = 0,
    coordinator_model_weight_bytes_received: int = 0,
    coordinator_model_weight_bytes_materialized: int = 0,
) -> dict[str, Any]:
    """Assemble the frozen preflight record from collected identities.

    Every repository identity and possession record is a mechanically
    collected document (see the collectors above); the coordinator counters
    are fabric-collected facts supplied by the orchestrator, not constants:
    the builder records whatever was observed, and the validator refuses any
    nonzero observation.
    """
    document = {
        "schema": PREFLIGHT_SCHEMA,
        "implementation": {
            "inferswarm_identity": dict(inferswarm_identity),
            "freetoken_identity": dict(freetoken_identity),
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
        "source_possession_records": [
            dict(record) for record in source_possession_records],
        "cold_cache_proofs": [dict(proof) for proof in cold_cache_proofs],
    }
    document["preflight_digest"] = _self_digest(document)
    return document


def _self_digest(document: Mapping[str, Any]) -> str:
    return self_digest(document, identity_field="preflight_digest")


def _stage_triples(candidate: Mapping[str, Any]) -> list[tuple[str, int, int]]:
    return [(stage.get("cu_id"), stage.get("layer_start"), stage.get("layer_end"))
            for stage in candidate.get("stage_structure", [])]


def _accepted_subject_available(repo_root: Path) -> bool:
    """Whether the accepted V5 qualification subject loads from evidence."""
    try:
        from issue117_gemma_strategy import retained_v5_qualification_authority
        retained_v5_qualification_authority(repo_root)
        return True
    except Exception:
        return False


def _validate_preflight(document: Mapping[str, Any], *, repo_root: Path,
                        fixture_path: Path | None, freetoken_root: Path | None,
                        checkpoint_root: Path | None, physical: bool) -> list[str]:
    """Re-derive every derivable identity; return all failures (empty = pass).

    ``fixture_path`` defaults to the committed integration fixture under
    ``repo_root``; the committed fixture is always fully validated, never
    merely digest-compared. A physical preflight requires accessible
    FreeToken and checkpoint checkouts. It independently re-checks the
    FreeToken identity record. It fails closed until retained checkpoint
    authority evidence supplies a mechanical byte-to-authority derivation.
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

    # -- repository identities: mechanical records, independently re-checked -
    implementation = document.get("implementation", {})
    inferswarm_identity = implementation.get("inferswarm_identity", {})
    freetoken_identity = implementation.get("freetoken_identity", {})
    _validate_repository_identity(inferswarm_identity, role="inferswarm",
                                  failures=failures)
    _validate_repository_identity(freetoken_identity, role="freetoken",
                                  failures=failures)
    if freetoken_identity.get("integration_producer") \
            != FROZEN_INTEGRATION_PRODUCER:
        failures.append(
            "freetoken_integration_producer is not the exact producer the "
            f"frozen applicability audit binds ({FROZEN_INTEGRATION_PRODUCER!r}); "
            f"got {freetoken_identity.get('integration_producer')!r}")
    if freetoken_identity.get("head") \
            != freetoken_identity.get("integration_producer"):
        failures.append(
            "FreeToken checkout HEAD does not equal the producer bound by the "
            f"applicability audit ({freetoken_identity.get('head')!r} != "
            f"{freetoken_identity.get('integration_producer')!r})")
    if not inferswarm_identity.get("clean"):
        failures.append("inferswarm worktree is not clean (collected evidence)")
    if not freetoken_identity.get("clean"):
        failures.append("freetoken worktree is not clean (collected evidence)")
    _recheck_repository_identity(inferswarm_identity, root=repo_root,
                                 role="inferswarm", failures=failures)
    if physical:
        if freetoken_root is None:
            failures.append("physical preflight requires a FreeToken checkout path")
        elif not Path(freetoken_root).is_dir():
            failures.append("physical preflight FreeToken checkout path is inaccessible")
        else:
            _recheck_repository_identity(freetoken_identity,
                                         root=Path(freetoken_root), role="freetoken",
                                         failures=failures)
        if checkpoint_root is None:
            failures.append("physical preflight requires the checkpoint checkout path")
        elif not Path(checkpoint_root).is_dir():
            failures.append("physical preflight checkpoint checkout path is inaccessible")
        else:
            try:
                from issue117_checkpoint_authority import (
                    validate_checkpoint_repository,
                )
                record = validate_checkpoint_repository(Path(checkpoint_root),
                                                        root=repo_root)
                if record.get("weights_sha256") != document.get(
                        "model_subject", {}).get("checkpoint_authority_sha256"):
                    failures.append(
                        "model_subject.checkpoint_authority_sha256 does not match "
                        "the mechanically derived checkpoint authority")
            except Exception as error:
                failures.append(
                    "checkpoint authority derivation failed for the candidate "
                    f"repository: {error}")
    elif freetoken_root is not None and Path(freetoken_root).is_dir():
        _recheck_repository_identity(freetoken_identity,
                                     root=Path(freetoken_root), role="freetoken",
                                     failures=failures)
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

    # Model/representation/backend/authority identity: the frozen subject
    # must equal the retained constants, and the checkpoint authority must
    # be exactly what the retained evidence files record.
    subject = document.get("model_subject", {})
    for field in ("model_id", "revision", "checkpoint_authority_sha256",
                  "representation", "execution"):
        if subject.get(field) != MODEL_SUBJECT.get(field):
            failures.append(f"model_subject.{field} drift: {subject.get(field)!r}")
    backend = subject.get("backend", {})
    for key in REQUIRED_BACKEND_KEYS:
        if backend.get(key) != MODEL_SUBJECT["backend"][key]:
            failures.append(f"model_subject.backend.{key} drift: {backend.get(key)!r}")
    try:
        from issue117_applicability import accepted_checkpoint_authority_from_evidence
        if subject.get("checkpoint_authority_sha256") \
                != accepted_checkpoint_authority_from_evidence(repo_root):
            failures.append(
                "model_subject.checkpoint_authority_sha256 is not the accepted "
                "authority identity recorded by the retained evidence files")
    except Exception as error:
        failures.append(f"checkpoint authority evidence unavailable: {error}")

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
    stored: dict[str, list[Mapping[str, Any]]] = {}
    for entry in document.get("qualification_applicability", []):
        digest = entry.get("record_digest")
        recomputed = self_digest(
            {key: value for key, value in entry.items() if key != "record_digest"},
            identity_field="record_digest")
        if digest != recomputed:
            failures.append(
                f"qualification-applicability record for "
                f"{entry.get('candidate_id')!r} is not digest-bound")
        stored.setdefault(entry.get("candidate_id"), []).append(entry)
    for candidate_id, entries in stored.items():
        if len(entries) > 1:
            statuses = sorted({entry.get("applicability") for entry in entries})
            failures.append(
                f"duplicated/conflicting qualification-applicability records "
                f"for {candidate_id!r}: {statuses}")

    # Qualification applicability is DERIVED, never trusted: evaluate every
    # candidate against the accepted V5 evidence with the strict policy and
    # refuse any mismatch with the retained records.
    derived = derive_candidate_applicability(candidates, inferswarm_root=repo_root)
    v5_triples = [(stage["cu_id"], stage["layer_start"], stage["layer_end"])
                  for stage in ACCEPTED_V5_GEOMETRY]
    v5_seen = False
    for candidate in candidates:
        candidate_id = str(candidate.get("candidate_id"))
        subject_result = candidate.get("qualification_subject")
        subject_digest = candidate.get("qualification_subject_digest")
        if not isinstance(subject_result, Mapping) or not subject_digest:
            failures.append(
                f"candidate {candidate_id!r} carries no qualification subject "
                "identity")
            continue
        from issue74_methodology import canonical_json_bytes
        from issue99_artifact_core import digest_of_bytes
        from issue117_subject_identity import execution_equality_subject
        if digest_of_bytes(canonical_json_bytes(execution_equality_subject(
                subject_result))) != subject_digest:
            failures.append(
                f"candidate {candidate_id!r} subject digest "
                "does not recompute from its subject")
        if MACHINERY_LOCAL_SUBJECT_KEYS[0] not in subject_result:
            failures.append(
                f"candidate {candidate_id!r} subject carries no "
                f"{MACHINERY_LOCAL_SUBJECT_KEYS[0]} content identity")
        entries = stored.get(candidate_id, [])
        if not entries:
            failures.append(f"no qualification-applicability record for "
                            f"{candidate_id}")
            continue
        entry = entries[0]
        if entry.get("applicability") not in (
                QUALIFICATION_APPLICABLE, QUALIFICATION_NOT_APPLICABLE):
            failures.append(f"malformed applicability for {candidate_id}")
        expected_status = derived.get(candidate_id, {}).get("status")
        if entry.get("applicability") != expected_status:
            failures.append(
                f"retained applicability for {candidate_id!r} "
                f"({entry.get('applicability')!r}) does not equal the "
                f"independently derived verdict ({expected_status!r}; reason "
                f"{derived.get(candidate_id, {}).get('reason')!r})")
        if _stage_triples(candidate) == v5_triples:
            v5_seen = True
            if expected_status == QUALIFICATION_APPLICABLE and not (
                    _accepted_subject_available(repo_root)):
                failures.append(
                    "candidate derived QUALIFICATION_APPLICABLE without a "
                    "retained accepted V5 qualification subject")
    if not v5_seen:
        failures.append("candidate set does not contain the accepted V5 geometry")

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
                != freetoken_identity.get("integration_producer"):
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
            elif descriptor.get("source_kind") not in SOURCE_KINDS:
                failures.append(
                    f"source descriptor {descriptor.get('source_id')!r} carries "
                    "no explicit source-kind identity")

    # Source possession: proven disjointness, mandatory for local Sources
    possession_records = document.get("source_possession_records", [])
    possession_by_source: dict[str, Mapping[str, Any]] = {}
    for record in possession_records:
        if record.get("schema") != SOURCE_POSSESSION_SCHEMA \
                or record.get("collector") != COLD_CACHE_COLLECTOR:
            failures.append(
                f"source-possession record for {record.get('source_id')!r} is "
                "not a mechanically collected record")
            continue
        if record.get("possession_digest") != self_digest(
                {key: value for key, value in record.items()
                 if key != "possession_digest"},
                identity_field="possession_digest"):
            failures.append(
                f"source-possession record for {record.get('source_id')!r} is "
                "edited (self-identity mismatch)")
            continue
        _validate_collected_facts(record.get("facts", {}),
                                  f"possession {record.get('source_id')}",
                                  failures)
        possession_by_source[record.get("source_id")] = record
    local_sources = [descriptor for descriptor in (descriptor_list or [])
                     if isinstance(descriptor, Mapping)
                     and descriptor.get("source_kind") == LOCAL_SOURCE_KIND]
    if local_sources and not possession_records:
        failures.append(
            "local Sources are authorized but no source-possession evidence "
            "exists; possession separation is not proven")
    for descriptor in local_sources:
        source_id = descriptor.get("source_id")
        expected_root = possession_root_for(descriptor)
        record = possession_by_source.get(source_id)
        if record is None:
            failures.append(
                f"local Source {source_id!r} carries no source-possession "
                "record; possession cannot be established")
            continue
        observed_root = record.get("facts", {}).get("root")
        if expected_root and observed_root != expected_root:
            failures.append(
                f"source-possession record for {source_id!r} was collected "
                f"from {observed_root!r}, not the Source's authorized "
                f"possession root {expected_root!r}")
    possession_roots = [record["facts"]["root"] for record in
                        possession_by_source.values() if record.get("facts")]
    proofs = document.get("cold_cache_proofs", [])
    if not proofs:
        failures.append("no cold-cache proofs frozen")
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


def validate_fixture_preflight(document: Mapping[str, Any], *, repo_root: Path,
                               fixture_path: Path | None = None,
                               freetoken_root: Path | None = None) -> list[str]:
    """Validate a CPU fixture preflight record.

    This test-only path does not inspect physical repositories. It cannot
    report or produce a physical-preflight pass.
    """
    return _validate_preflight(document, repo_root=repo_root,
                               fixture_path=fixture_path, freetoken_root=freetoken_root,
                               checkpoint_root=None, physical=False)


def validate_preflight(document: Mapping[str, Any], *, repo_root: Path,
                       fixture_path: Path | None = None,
                       freetoken_root: Path | None = None,
                       checkpoint_root: Path | None = None) -> list[str]:
    """Validate a physical preflight from actual repository checkouts."""
    return _validate_preflight(document, repo_root=repo_root,
                               fixture_path=fixture_path,
                               freetoken_root=freetoken_root,
                               checkpoint_root=checkpoint_root, physical=True)


def require_preflight_valid(document: Mapping[str, Any], *, repo_root: Path,
                            fixture_path: Path | None = None,
                            freetoken_root: Path | None = None,
                            checkpoint_root: Path | None = None) -> None:
    failures = validate_preflight(document, repo_root=repo_root,
                                  fixture_path=fixture_path,
                                  freetoken_root=freetoken_root,
                                  checkpoint_root=checkpoint_root)
    if failures:
        raise PreflightBlocked(
            "physical preflight failed:\n" + "\n".join(f"  - {f}" for f in failures))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("preflight", type=Path)
    parser.add_argument("--repo-root", type=Path,
                        default=Path(__file__).resolve().parents[1])
    parser.add_argument("--freetoken-root", type=Path, default=None)
    parser.add_argument("--checkpoint-root", type=Path, default=None)
    parser.add_argument("--fixture", type=Path, default=None)
    args = parser.parse_args(argv)
    document = json.loads(args.preflight.read_text())
    failures = validate_preflight(document, repo_root=args.repo_root,
                                  fixture_path=args.fixture,
                                  freetoken_root=args.freetoken_root,
                                  checkpoint_root=args.checkpoint_root)
    if failures:
        print("PREFLIGHT_INVALID")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("PREFLIGHT_VALID")
    return 0


if __name__ == "__main__":
    sys.exit(main())

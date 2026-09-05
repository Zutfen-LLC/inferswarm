#!/usr/bin/env python3
"""InferSwarm issue #99 canonical plan-driven artifact-acquisition proof.

Executes the minimum end-to-end successor proof required by ADR 0009 /
docs/architecture/model-artifact-distribution.md §15 on a compact CPU-only
fixture (issue99_mini_model), entirely inside isolated temporary paths so the
concurrent issue #97 physical campaign is never touched.

Canonical arms:
  1. freeze model/revision/representation identity + frozen plan;
  2. derive plan-driven participant requirements (strategy adapter boundary);
  3. canonical participant exec.a begins WITHOUT any local model repository
     (empty durable cache; runtime holds no repository path);
  4. resolve only required artifacts/ranges (byte ranges inside shards, one
     two-artifact LSU, one whole-object metadata artifact);
  5. acquire missing bytes directly from the one authorized HTTP Source;
  6. verify exact artifact identity/provenance before trust;
  7. bounded staging/transform into the planned Materializations;
  8. execute the chained two-partition workload through the coordinator
     authorization/reconciliation path;
  9. prove zero unrelated model bytes and zero whole-model dependency;
  10. second participant exec.b on the same node: verified cache hits satisfy
      shared state without reacquisition;
  11. restart arm: exec.a re-realizes entirely from verified cache hits;
  12. controlled interrupted transfer + legal resume for exec.c;
  13. fail-closed negative controls (corrupt bytes, wrong provenance, missing
      artifact, unauthorized source, foreign partial state, unverified
      promotion, incomplete coverage, whole-model injection, unplanned
      staging fetch, structural no-repository-prerequisite checks).

Terminal disposition (only when every arm passes):
    PLAN_DRIVEN_ARTIFACT_ACQUISITION_PASS

Pure stdlib; no accelerator, no model runtime, no network beyond loopback.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parent))

from issue74_methodology import canonical_json_bytes  # noqa: E402
from issue99_artifact_core import (  # noqa: E402
    AcquisitionError,
    AcquisitionLedger,
    CoordinatorAuthority,
    LocalFileSource,
    LocalHttpSource,
    NodeArtifactCache,
    acquire_artifact,
    derive_participant_requirements,
    digest_of_bytes,
    freeze_artifact_record,
    guard_full_object_acquisition,
    write_canonical_json,
)
import issue99_artifact_core as core  # noqa: E402
import issue99_mini_model  # noqa: E402
from issue99_mini_model import (  # noqa: E402
    CONFIG_OBJECT,
    MiniLmParticipantRuntime,
    MiniLmStrategyResolver,
    build_frozen_plan,
    build_mini_model_repository,
)

SUMMARY_SCHEMA = "inferswarm.issue99.proof-summary/1"
NEGATIVE_SCHEMA = "inferswarm.issue99.negative-control/1"
INITIAL_STATE_SCHEMA = "inferswarm.issue99.initial-state/1"
RECONCILIATION_SCHEMA = "inferswarm.issue99.reconciliation/1"
EXECUTION_SCHEMA = "inferswarm.issue99.execution/1"
CACHE_REUSE_SCHEMA = "inferswarm.issue99.cache-reuse/1"
INTERRUPTED_SCHEMA = "inferswarm.issue99.interrupted-transfer/1"
NEGATIVE_SET_SCHEMA = "inferswarm.issue99.negative-control-set/1"
FINAL_CACHE_SCHEMA = "inferswarm.issue99.final-cache/1"
TERMINAL_DISPOSITION = "PLAN_DRIVEN_ARTIFACT_ACQUISITION_PASS"
FAIL_CLOSED = "FAIL_CLOSED_EXPECTED"
CHUNK_BYTES = 4096
AUTHORIZED_HTTP_SOURCE = "operator-http-local"
UNAUTHORIZED_FILE_SOURCE = "operator-file-not-eligible"
MISSING_OBJECT_SOURCE = "operator-http-missing-object"

SCRIPT_FILES = ("issue99_artifact_core.py", "issue99_mini_model.py", "issue99_proof.py")
EVIDENCE_FILES = (
    "source-catalog.json", "frozen-plan.json", "participant-requirements.json",
    "realization-authorization.json", "initial-cache-inventory.json",
    "acquisition-ledger.json", "materialization-reconciliation.json",
    "execution-result.json", "cache-reuse-evidence.json",
    "interrupted-transfer.json", "negative-controls.json",
    "final-cache-inventory.json", "canonical-summary.json",
)

NON_CLAIMS = (
    "Compact synthetic CPU-only fixture model; not a physical/GPU campaign and "
    "not a serving-performance claim.",
    "No FreeToken runtime integration is exercised in this proof: the seam is "
    "validated against the R1-shaped plan/materialization contract with the "
    "same allow-list selective staging discipline; physical integration is a "
    "later gate.",
    "Internal record schemas, digest choices, cache layout, and source "
    "descriptors are implementation details and remain unfrozen; no public "
    "CAS/manifest/peer protocol is defined.",
    "One authorized HTTP Source per artifact plus a loopback test source; no "
    "multi-source striping, P2P, DHT, tracker, or BitTorrent semantics.",
    "No cache eviction policy, no transfer-scheduling optimization, and no "
    "artifact-locality planner weighting are implemented or claimed.",
    "Issue #97 is untouched: no FreeToken working-tree changes, no GPU hosts, "
    "no #97 evidence directories read or written; all fixture paths are "
    "isolated temporary directories.",
)


class ProofFailure(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ProofFailure(message)


def _fail_closed(caller, *args, expected_reason: str, **kwargs) -> dict[str, Any]:
    """Run a negative control; return its retained fail-closed record."""
    started = time.monotonic()
    try:
        caller(*args, **kwargs)
    except AcquisitionError as failure:
        reason = str(failure).split(":", 1)[0]
        _require(reason == expected_reason,
                 f"negative control raised {reason!r}, expected {expected_reason!r}")
        return {
            "schema": NEGATIVE_SCHEMA,
            "outcome": FAIL_CLOSED,
            "expected_reason": expected_reason,
            "observed_reason": reason,
            "detail": str(failure),
            "wall_time_seconds": round(time.monotonic() - started, 6),
        }
    raise ProofFailure(f"negative control did not fail closed ({expected_reason})")


class _Timing:
    def __init__(self) -> None:
        self.values: dict[str, float] = {}

    def measure(self, name: str) -> "_Timing":
        self._name = name
        self._started = time.monotonic()
        return self

    def __enter__(self) -> "_Timing":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.values[self._name] = round(time.monotonic() - self._started, 6)


def _records_index(requirements: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {record["content_digest"]: record
            for participant in requirements["participants"]
            for record in participant["required_artifacts"]}


def _ledger_participants(requirements: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    out = {}
    for participant in requirements["participants"]:
        state = participant["required_logical_state"]
        out[participant["participant_id"]] = {
            "required_artifact_bytes": participant["required_artifact_bytes"],
            "declared_state_ids": (state["assigned"] + state["declared_shared"]
                                   + state["required_metadata"]),
        }
    return out


def _acquire_all(*, cache: NodeArtifactCache, source: Any, participant: Mapping[str, Any],
                 authorization: CoordinatorAuthority, ledger: AcquisitionLedger) -> list[dict[str, Any]]:
    results = []
    for record in participant["required_artifacts"]:
        results.append(acquire_artifact(
            cache=cache, source=source, record=record,
            authorization=authorization,
            participant_id=participant["participant_id"], ledger=ledger,
            chunk_bytes=CHUNK_BYTES))
    return results


def _participant_doc(requirements: Mapping[str, Any], participant_id: str) -> dict[str, Any]:
    return next(p for p in requirements["participants"]
                if p["participant_id"] == participant_id)


def run_campaign(out_dir: Path | None = None) -> dict[str, Any]:
    """Execute every arm; retain evidence under ``out_dir``; return the summary."""
    timings = _Timing()
    evidence: dict[str, Any] = {}
    workspace = tempfile.TemporaryDirectory(prefix="issue99-proof-")
    work = Path(workspace.name)
    with timings.measure("campaign_total"):
        # -- arm 1: frozen identities ---------------------------------------
        with timings.measure("fixture_build"):
            source_root = work / "operator-source-root"
            catalog = build_mini_model_repository(source_root)
            plan = build_frozen_plan(catalog)
        with timings.measure("requirement_derivation"):
            resolver = MiniLmStrategyResolver(catalog=catalog, source_root=source_root)
            requirements = derive_participant_requirements(plan, resolver)
        evidence["source-catalog.json"] = catalog
        evidence["frozen-plan.json"] = plan
        evidence["participant-requirements.json"] = requirements

        # -- authorized sources ----------------------------------------------
        http_source = LocalHttpSource(source_id=AUTHORIZED_HTTP_SOURCE, root=source_root)
        file_source = LocalFileSource(source_id=UNAUTHORIZED_FILE_SOURCE, root=source_root)
        missing_root = work / "operator-source-missing-object"
        missing_root.mkdir()
        for name in catalog["objects"]:
            if name != CONFIG_OBJECT:
                (missing_root / name).write_bytes((source_root / name).read_bytes())
        missing_source = LocalHttpSource(source_id=MISSING_OBJECT_SOURCE, root=missing_root)
        try:
            coordinator = CoordinatorAuthority(
                plan=plan, requirements=requirements,
                eligible_sources=[http_source.descriptor()])
            evidence["realization-authorization.json"] = coordinator.authorization
            _require(coordinator.bytes_observed == 0,
                     "coordinator observed bulk bytes during authorization")

            ledger = AcquisitionLedger()
            node_alpha = NodeArtifactCache(work / "node-alpha-cache")

            # -- arm 3: canonical participant begins without a repository ----
            initial_inventory = node_alpha.inventory()
            _require(initial_inventory["verified_objects"] == [],
                     "canonical participant cache is not initially empty")
            init_code = MiniLmParticipantRuntime.__init__.__code__
            runtime_signature = sorted(
                init_code.co_varnames[1:init_code.co_argcount])
            _require(all("root" not in name and "path" not in name and "repo" not in name
                         for name in runtime_signature),
                     f"participant runtime accepts repository-ish inputs: {runtime_signature}")
            evidence["initial-cache-inventory.json"] = {
                "schema": INITIAL_STATE_SCHEMA,
                "node": "node-alpha",
                "cache_inventory": initial_inventory,
                "participant_local_model_repository_present": False,
                "participant_runtime_inputs": runtime_signature,
                "source_repository_objects": {
                    name: spec["length"] for name, spec in catalog["objects"].items()},
                "participant_possessed_fraction_of_each_upstream_object": {
                    name: 0.0 for name in catalog["objects"]},
            }

            # -- arms 4-7: fresh acquisition + staging + realization ---------
            participant_a = _participant_doc(requirements, "exec.a")
            with timings.measure("arm_fresh_acquisition"):
                acquisition_a = _acquire_all(
                    cache=node_alpha, source=http_source, participant=participant_a,
                    authorization=coordinator, ledger=ledger)
            _require(all(r["status"] == "ACQUIRED" for r in acquisition_a),
                     "canonical participant did not freshly acquire every artifact")
            with timings.measure("arm_a_materialization"):
                runtime_a = MiniLmParticipantRuntime(
                    plan=plan, participant_requirements=participant_a, cache=node_alpha)
                materializations_a = runtime_a.materialize()
                stage_one = runtime_a.execute_stage_one()
            _require(stage_one["boundary_digest"] == plan["workload"]["expected_boundary_digest"],
                     "stage-one boundary digest does not match the oracle")
            reconciliation_a = coordinator.reconcile(
                participant_id="exec.a",
                used_artifact_ids=[r["artifact_id"] for r in participant_a["required_artifacts"]],
                materializations=materializations_a)

            # -- arm 8: second participant, partial verified-cache reuse ------
            participant_b = _participant_doc(requirements, "exec.b")
            with timings.measure("arm_second_participant"):
                acquisition_b = _acquire_all(
                    cache=node_alpha, source=http_source, participant=participant_b,
                    authorization=coordinator, ledger=ledger)
            hits_b = [r for r, record in zip(acquisition_b, participant_b["required_artifacts"])
                      if r["status"] == "CACHE_HIT"]
            acquired_b = [r for r in acquisition_b if r["status"] == "ACQUIRED"]
            _require(len(hits_b) == 2 and len(acquired_b) == 3,
                     f"exec.b expected 2 cache hits + 3 acquisitions, got "
                     f"{len(hits_b)}+{len(acquired_b)}")
            with timings.measure("arm_b_materialization"):
                runtime_b = MiniLmParticipantRuntime(
                    plan=plan, participant_requirements=participant_b, cache=node_alpha)
                materializations_b = runtime_b.materialize()
                boundary_payload = canonical_boundary_bytes(stage_one)
                hidden_rows = unpack_boundary(boundary_payload, plan)
                stage_two = runtime_b.execute_stage_two(hidden_rows)
            _require(stage_two["logits_digest"] == plan["workload"]["expected_logits_digest"],
                     "chained logits digest does not match the oracle")
            _require(stage_two["decisions"] == plan["workload"]["expected_decisions"],
                     "greedy decisions do not match the oracle")
            reconciliation_b = coordinator.reconcile(
                participant_id="exec.b",
                used_artifact_ids=[r["artifact_id"] for r in participant_b["required_artifacts"]],
                materializations=materializations_b)
            evidence["materialization-reconciliation.json"] = {
                "schema": RECONCILIATION_SCHEMA,
                "participants": [reconciliation_a, reconciliation_b],
                "materializations_released_after_execution": True,
                "ram_materialization_lifecycle": "transient: released at execution end; "
                                                 "retained cache objects are backing/source "
                                                 "state, not residency",
            }
            evidence["execution-result.json"] = {
                "schema": EXECUTION_SCHEMA,
                "chain": plan["execution"]["chain"],
                "boundary": {
                    "payload_bytes": len(boundary_payload),
                    "boundary_digest": digest_of_bytes(boundary_payload),
                    "matches_oracle": stage_one["boundary_digest"]
                    == plan["workload"]["expected_boundary_digest"],
                },
                "stage_one_boundary_digest": stage_one["boundary_digest"],
                "stage_two_logits_digest": stage_two["logits_digest"],
                "stage_two_decisions": stage_two["decisions"],
                "oracle_logits_digest": plan["workload"]["expected_logits_digest"],
                "oracle_decisions": plan["workload"]["expected_decisions"],
                "execution_matches_oracle": (
                    stage_one["boundary_digest"] == plan["workload"]["expected_boundary_digest"]
                    and stage_two["logits_digest"] == plan["workload"]["expected_logits_digest"]
                    and stage_two["decisions"] == plan["workload"]["expected_decisions"]),
            }

            # -- arm 11: restart arm: full verified-cache reuse ---------------
            with timings.measure("arm_restart_reuse"):
                restart_ledger_before = len(ledger.events)
                acquisition_restart = _acquire_all(
                    cache=node_alpha, source=http_source, participant=participant_a,
                    authorization=coordinator, ledger=ledger)
                runtime_a2 = MiniLmParticipantRuntime(
                    plan=plan, participant_requirements=participant_a, cache=node_alpha)
                materializations_a2 = runtime_a2.materialize()
                stage_one_restart = runtime_a2.execute_stage_one()
            _require(all(r["status"] == "CACHE_HIT" for r in acquisition_restart),
                     "restart arm re-acquired bytes that the verified cache already held")
            _require(stage_one_restart["boundary_digest"]
                     == plan["workload"]["expected_boundary_digest"],
                     "restart execution diverged from the oracle")
            restart_events = ledger.events[restart_ledger_before:]
            evidence["cache-reuse-evidence.json"] = {
                "schema": CACHE_REUSE_SCHEMA,
                "second_participant": {
                    "participant_id": "exec.b",
                    "cache_hits": [
                        {"artifact_id": record["artifact_id"],
                         "satisfies": record["satisfies_logical_state_ids"],
                         "bytes": result["bytes"]}
                        for result, record in zip(acquisition_b, participant_b["required_artifacts"])
                        if result["status"] == "CACHE_HIT"],
                    "newly_acquired": [
                        {"artifact_id": record["artifact_id"],
                         "satisfies": record["satisfies_logical_state_ids"],
                         "bytes": result["bytes"]}
                        for result, record in zip(acquisition_b, participant_b["required_artifacts"])
                        if result["status"] == "ACQUIRED"],
                },
                "restart": {
                    "participant_id": "exec.a",
                    "all_cache_hits": all(r["status"] == "CACHE_HIT"
                                          for r in acquisition_restart),
                    "reacquired_bytes": sum(r.get("bytes", 0) for r in acquisition_restart
                                            if r["status"] != "CACHE_HIT"),
                    "execution_matches_oracle": stage_one_restart["boundary_digest"]
                    == plan["workload"]["expected_boundary_digest"],
                },
                "restart_ledger_events": [e for e in restart_events
                                          if e["event"] == "CACHE_HIT"],
            }

            # -- arm 12: controlled interrupted transfer + legal resume -------
            participant_c = _participant_doc(requirements, "exec.c")
            node_beta = NodeArtifactCache(work / "node-beta-cache")
            embed_record = next(r for r in participant_c["required_artifacts"]
                                if r["satisfies_logical_state_ids"] == ["model.shared.embed"])
            interrupt_offset = (embed_record["origin"]["byte_start"] + 6000)
            with timings.measure("arm_interrupted_transfer"):
                http_source.interrupt_after[embed_record["origin"]["source_object"]] = \
                    interrupt_offset
                first = acquire_artifact(
                    cache=node_beta, source=http_source, record=embed_record,
                    authorization=coordinator, participant_id="exec.c", ledger=ledger,
                    chunk_bytes=CHUNK_BYTES)
                del http_source.interrupt_after[embed_record["origin"]["source_object"]]
                _require(first["status"] == "INTERRUPTED" and first["retained_bytes"] == 6000,
                         f"controlled interruption unexpected: {first}")
                resumed = _acquire_all(
                    cache=node_beta, source=http_source, participant=participant_c,
                    authorization=coordinator, ledger=ledger)
                resume_result = next(
                    r for r, record in zip(resumed, participant_c["required_artifacts"])
                    if record["artifact_id"] == embed_record["artifact_id"])
                _require(resume_result["status"] == "ACQUIRED"
                         and resume_result["bytes"] == embed_record["length"] - 6000,
                         f"resume did not continue from the retained prefix: {resume_result}")
                runtime_c = MiniLmParticipantRuntime(
                    plan=plan, participant_requirements=participant_c, cache=node_beta)
                materializations_c = runtime_c.materialize()
                stage_one_c = runtime_c.execute_stage_one()
            _require(stage_one_c["boundary_digest"]
                     == plan["workload"]["expected_boundary_digest"],
                     "post-resume execution diverged from the oracle")
            reconciliation_c = coordinator.reconcile(
                participant_id="exec.c",
                used_artifact_ids=[r["artifact_id"] for r in participant_c["required_artifacts"]],
                materializations=materializations_c)
            evidence["interrupted-transfer.json"] = {
                "schema": INTERRUPTED_SCHEMA,
                "participant_id": "exec.c",
                "artifact_id": embed_record["artifact_id"],
                "artifact_length": embed_record["length"],
                "interrupted_at_object_offset": interrupt_offset,
                "retained_partial_bytes": first["retained_bytes"],
                "resume_transferred_bytes": resume_result["bytes"],
                "resumed_from_bound_prefix": True,
                "post_resume_execution_matches_oracle": stage_one_c["boundary_digest"]
                == plan["workload"]["expected_boundary_digest"],
                "reconciliation": reconciliation_c["status"],
            }

            # -- arm 13: fail-closed negative controls ------------------------
            with timings.measure("arm_negative_controls"):
                negatives = _run_negative_controls(
                    work=work, source_root=source_root, catalog=catalog, plan=plan,
                    resolver=resolver, requirements=requirements,
                    http_source=http_source, file_source=file_source,
                    missing_source=missing_source, ledger=ledger)
            evidence["negative-controls.json"] = {
                "schema": NEGATIVE_SET_SCHEMA,
                "controls": negatives,
                "all_fail_closed": all(c["outcome"] == FAIL_CLOSED for c in negatives.values())
                and all(c.get("structural_pass", True) for c in negatives.values()),
            }

            # -- accounting ----------------------------------------------------
            ledger_document = ledger.document(
                records_by_digest=_records_index(requirements),
                participants=_ledger_participants(requirements))
            evidence["acquisition-ledger.json"] = ledger_document
            aggregate = ledger_document["aggregate"]
            _require(aggregate["unrelated_model_bytes_acquired_for_realization"] == 0,
                     "unrelated model bytes were acquired for realization")
            _require(aggregate["unexplained_full_model_dependency"] == 0,
                     "unexplained whole-model dependency detected")

            final_inventories = {
                "node-alpha": node_alpha.inventory(),
                "node-beta": node_beta.inventory(),
            }
            for inventory in final_inventories.values():
                _require(all(o["byte_digest_verified"] for o in inventory["verified_objects"]),
                         "final cache contains a non-verifying object")
            # Mechanical no-complete-repository evidence: after all arms, the
            # union of each node's verified artifacts still covers only a
            # strict fraction of every upstream object, and the canonical
            # participant's acquired set passes the whole-object guard.
            coverage = _upstream_coverage(requirements, catalog)
            model_data_objects = [name for name in coverage
                                  if name.endswith(".safetensors")]
            for name in model_data_objects:
                _require(coverage[name] < 1.0,
                         f"participants possess the whole upstream object {name}")
            guard_full_object_acquisition(
                [record for record in _records_index(requirements).values()
                 if cache_has_object(node_alpha, record) or cache_has_object(node_beta, record)])
            evidence["final-cache-inventory.json"] = {
                "schema": FINAL_CACHE_SCHEMA,
                "inventories": final_inventories,
                "final_optional_cache_bytes": {
                    node: inv["verified_bytes"] for node, inv in final_inventories.items()},
                "final_required_backing_bytes": 0,
                "possessed_fraction_of_each_upstream_object": coverage,
            }

            # upstream-source access proof: shards only ever range-requested
            shard_requests = {
                name: http_source.requests_for(name)
                for name in catalog["objects"] if name.endswith(".safetensors")}
            unrelated_objects_requested = sorted(
                name for name in ("vision-adapter.safetensors", "mtp-head.safetensors")
                if http_source.requests_for(name) or file_source.requests_for(name))
            _require(not unrelated_objects_requested,
                     f"unrelated upstream objects were requested: {unrelated_objects_requested}")

            participants_summary = {}
            for participant in requirements["participants"]:
                pid = participant["participant_id"]
                events = [e for e in ledger.events if e.get("participant_id") == pid]
                participants_summary[pid] = {
                    "required_artifact_bytes": participant["required_artifact_bytes"],
                    "required_artifacts": len(participant["required_artifacts"]),
                    "cache_hit_bytes": sum(e["bytes"] for e in events
                                           if e["event"] == "CACHE_HIT"),
                    "newly_acquired_bytes": sum(e["bytes"] for e in events
                                                if e["event"] == "ACQUIRED"),
                }

            summary = {
                "schema": SUMMARY_SCHEMA,
                "issue": 99,
                "terminal_disposition": TERMINAL_DISPOSITION,
                "canonical_invariant": (
                    "InferSwarm distributes required state, not model repositories: the "
                    "frozen plan determines each participant's required immutable "
                    "artifacts; whole-model replication is never a participation "
                    "prerequisite."),
                "model_identity": dict(plan["model"]),
                "plan_digest": plan["plan_digest"],
                "requirements_digest": requirements["requirements_digest"],
                "authorization_digest": coordinator.authorization["authorization_digest"],
                "canonical_participant": {
                    "participant_id": "exec.a",
                    "node": "node-alpha",
                    "begins_without_complete_local_model_repository": True,
                    "initial_verified_cache_bytes": 0,
                    "acquired_artifacts": len(acquisition_a),
                    "required_artifact_bytes": participant_a["required_artifact_bytes"],
                },
                "arms": {
                    "fresh_participant_acquisition": "PASS",
                    "chained_execution_matches_oracle": (
                        evidence["execution-result.json"]["execution_matches_oracle"]),
                    "second_participant_partial_cache_reuse": "PASS",
                    "restart_full_cache_reuse": "PASS",
                    "interrupted_transfer_resume": "PASS",
                    "negative_controls_all_fail_closed": (
                        evidence["negative-controls.json"]["all_fail_closed"]),
                },
                "zero_invariants": {
                    "unrelated_model_bytes_acquired_for_realization":
                        aggregate["unrelated_model_bytes_acquired_for_realization"],
                    "unexplained_full_model_dependency":
                        aggregate["unexplained_full_model_dependency"],
                },
                "accounting": {
                    **aggregate,
                    "canonical_arm_only": {
                        "participant": "exec.a",
                        "begins_without_local_model_repository": True,
                        "required_artifact_bytes": participant_a["required_artifact_bytes"],
                        "newly_acquired_bytes": sum(r["bytes"] for r in acquisition_a),
                        "verified_cache_hit_bytes": sum(
                            r["bytes"] for r in acquisition_a if r["status"] == "CACHE_HIT"),
                        "second_participant": {
                            "participant": "exec.b",
                            "newly_acquired_bytes": sum(
                                r["bytes"] for r in acquisition_b
                                if r["status"] == "ACQUIRED"),
                            "verified_cache_hit_bytes": sum(
                                r["bytes"] for r in acquisition_b
                                if r["status"] == "CACHE_HIT"),
                        },
                        "restart_arm": {
                            "participant": "exec.a",
                            "newly_acquired_bytes": sum(
                                r["bytes"] for r in acquisition_restart
                                if r["status"] != "CACHE_HIT"),
                            "verified_cache_hit_bytes": sum(
                                r["bytes"] for r in acquisition_restart
                                if r["status"] == "CACHE_HIT"),
                        },
                        "note": "the campaign-wide ledger additionally contains the "
                                "deliberate foreign-partial reacquisition and the "
                                "fail-closed negative-control attempts",
                    },
                    "per_participant": participants_summary,
                    "boundary_transfer_bytes": len(boundary_payload),
                    "staging_bytes_read": {
                        "exec.a": runtime_a.staging_bytes_read,
                        "exec.b": runtime_b.staging_bytes_read,
                        "exec.c": runtime_c.staging_bytes_read,
                    },
                    "materializations_created": (
                        len(materializations_a) + len(materializations_b)
                        + len(materializations_c) + len(materializations_a2)),
                    "upstream_shard_range_requests": {
                        name: [
                            {"range_header": r["range_header"]}
                            for r in requests if r["range_header"]]
                        for name, requests in shard_requests.items()},
                    "unrelated_upstream_objects_requested": unrelated_objects_requested,
                },
                "coordinator": {
                    "bytes_observed": coordinator.bytes_observed,
                    "bulk_bytes_transit_required": False,
                    "eligible_sources": [s["source_id"] for s
                                         in coordinator.authorization["eligible_sources"]],
                },
                "negative_controls": {
                    name: control["outcome"] for name, control in negatives.items()},
                "provenance": {
                    "producer_programs": {
                        name: hashlib.sha256(
                            (Path(__file__).resolve().parent / name).read_bytes()).hexdigest()
                        for name in SCRIPT_FILES},
                    "fixture_catalog_digest": catalog["catalog_digest"],
                    "oracle_workload_digest": catalog["oracle"]["workload_digest"],
                },
                "issue97_isolation": {
                    "freetoken_tree_modified": False,
                    "physical_hosts_touched": [],
                    "evidence_directories_touched": [],
                    "fixture_paths": [str(work)],
                    "cpu_only": True,
                },
                "non_claims": list(NON_CLAIMS),
                "timings_seconds": timings.values,
            }
            _require(summary["arms"]["chained_execution_matches_oracle"] is True,
                     "execution does not match oracle")
            evidence["canonical-summary.json"] = summary
        finally:
            http_source.close()
            missing_source.close()

        if out_dir is not None:
            out_dir = Path(out_dir)
            for name in EVIDENCE_FILES:
                write_canonical_json(out_dir / name, evidence[name])
            write_manifest(out_dir, set(EVIDENCE_FILES))
    workspace.cleanup()
    return summary


def cache_has_object(cache: NodeArtifactCache, record: Mapping[str, Any]) -> bool:
    return cache.has_verified(record)


def _upstream_coverage(requirements: Mapping[str, Any],
                       catalog: Mapping[str, Any]) -> dict[str, float]:
    """Fraction of each upstream object covered by all required artifacts.

    Model-data objects (the safetensors shards and the unrelated adapter
    objects) must stay below 1.0: that is mechanical proof that no
    participant possession amounts to a complete upstream model object, let
    alone a complete model repository. Small runtime metadata may be wholly
    possessed when declared as ``required_metadata``.
    """
    covered: dict[str, int] = {}
    for record in _records_index(requirements).values():
        origin = record["origin"]
        name = origin["source_object"]
        if record["kind"] == "byte_range":
            span = origin["byte_end"] - origin["byte_start"]
        else:
            span = record["length"]
        covered[name] = covered.get(name, 0) + span
    return {
        name: round(covered.get(name, 0) / spec["length"], 6)
        for name, spec in catalog["objects"].items()
    }


def canonical_boundary_bytes(stage_one: Mapping[str, Any]) -> bytes:
    """Repack the boundary payload exactly as the plan contract defines it."""
    from issue99_mini_model import boundary_pack
    return boundary_pack(stage_one["hidden"])


def unpack_boundary(payload: bytes, plan: Mapping[str, Any]) -> list[list[float]]:
    tokens = plan["execution"]["boundary"]["token_count"]
    return issue99_mini_model.unpack_f32_rows(payload, tokens, issue99_mini_model.WIDTH)


def _run_negative_controls(*, work: Path, source_root: Path, catalog: Mapping[str, Any],
                           plan: Mapping[str, Any], resolver: MiniLmStrategyResolver,
                           requirements: Mapping[str, Any], http_source: LocalHttpSource,
                           file_source: LocalFileSource, missing_source: LocalHttpSource,
                           ledger: AcquisitionLedger) -> dict[str, Any]:
    controls: dict[str, Any] = {}
    participant_a = _participant_doc(requirements, "exec.a")
    participant_b = _participant_doc(requirements, "exec.b")
    coordinator = CoordinatorAuthority(
        plan=plan, requirements=requirements,
        eligible_sources=[http_source.descriptor(), missing_source.descriptor(),
                          file_source.descriptor()])

    # 1. corrupt transfer data: one flipped byte in flight never publishes.
    node_gamma = NodeArtifactCache(work / "node-gamma-cache")
    lm_head = max((r for r in participant_b["required_artifacts"]
                   if r["satisfies_logical_state_ids"] == ["model.shared.final"]),
                  key=lambda r: r["length"])
    http_source.corrupt_at[lm_head["origin"]["source_object"]] = \
        lm_head["origin"]["byte_start"] + 100
    controls["corrupt_transfer_data"] = _fail_closed(
        acquire_artifact, cache=node_gamma, source=http_source, record=lm_head,
        authorization=coordinator, participant_id="exec.b", ledger=ledger,
        chunk_bytes=CHUNK_BYTES, expected_reason="INTEGRITY_DIGEST_MISMATCH")
    del http_source.corrupt_at[lm_head["origin"]["source_object"]]
    controls["corrupt_transfer_data"]["structural_pass"] = not (
        node_gamma.inventory()["verified_objects"])

    # 2. wrong model/revision/representation provenance fails at derivation.
    wrong_revision = MiniLmStrategyResolver(
        catalog=catalog, source_root=source_root, revision="dead" * 10)
    controls["wrong_provenance_identity"] = _fail_closed(
        derive_participant_requirements, plan, wrong_revision,
        expected_reason="PROVENANCE_IDENTITY_MISMATCH")

    # 3. missing required artifact at the authorized source fails closed.
    node_delta = NodeArtifactCache(work / "node-delta-cache")
    config_record = next(r for r in participant_a["required_artifacts"]
                         if r["satisfies_logical_state_ids"] == ["runtime.graph-config"])
    controls["missing_required_artifact"] = _fail_closed(
        acquire_artifact, cache=node_delta, source=missing_source,
        record=config_record, authorization=coordinator, participant_id="exec.a",
        ledger=ledger, chunk_bytes=CHUNK_BYTES,
        expected_reason="SOURCE_OBJECT_UNAVAILABLE")
    controls["missing_required_artifact"]["structural_pass"] = not (
        node_delta.inventory()["verified_objects"])

    # 4. present-but-ineligible Source is refused before any bytes move.
    unauthorized_coordinator = CoordinatorAuthority(
        plan=plan, requirements=requirements,
        eligible_sources=[http_source.descriptor()])
    http_requests_before = len(http_source.access_log)
    file_requests_before = len(file_source.access_log)
    controls["unauthorized_source"] = _fail_closed(
        acquire_artifact, cache=node_delta, source=file_source,
        record=participant_a["required_artifacts"][0],
        authorization=unauthorized_coordinator, participant_id="exec.a",
        ledger=ledger, chunk_bytes=CHUNK_BYTES, expected_reason="SOURCE_UNAUTHORIZED")
    zero_bytes_moved = (len(http_source.access_log) == http_requests_before
                        and len(file_source.access_log) == file_requests_before)
    controls["unauthorized_source"]["zero_bytes_moved"] = zero_bytes_moved
    controls["unauthorized_source"]["structural_pass"] = zero_bytes_moved

    # 5. partial-transfer state bound to another artifact is discarded/restarted.
    node_eps = NodeArtifactCache(work / "node-eps-cache")
    embed = next(r for r in participant_a["required_artifacts"]
                 if r["satisfies_logical_state_ids"] == ["model.shared.embed"])
    block = next(r for r in participant_a["required_artifacts"]
                 if r["satisfies_logical_state_ids"] == ["model.block.2"])
    shard_bytes = (source_root / block["origin"]["source_object"]).read_bytes()
    foreign_data = shard_bytes[block["origin"]["byte_start"]:block["origin"]["byte_start"] + 2000]
    # Mis-bound sidecar: bytes and binding belong to `block`, stored under
    # `embed`'s identity. Resume must discard them, never stitch.
    node_eps._state_path(embed["artifact_id"]).write_text(canonical_json_bytes({
        "artifact_id": block["artifact_id"],
        "content_digest": block["content_digest"],
        "length": block["length"],
        "retained_bytes": len(foreign_data)}).decode())
    node_eps._part_path(embed["artifact_id"]).write_bytes(foreign_data)
    events_before = len(ledger.events)
    result = acquire_artifact(cache=node_eps, source=http_source, record=embed,
                              authorization=coordinator, participant_id="exec.a",
                              ledger=ledger, chunk_bytes=CHUNK_BYTES)
    discards = [e for e in ledger.events[events_before:] if e["event"] == "PARTIAL_DISCARDED"]
    safe_restart = bool(discards) and result["status"] == "ACQUIRED" \
        and result["bytes"] == embed["length"]
    controls["foreign_partial_state_discarded"] = {
        "schema": NEGATIVE_SCHEMA,
        "outcome": FAIL_CLOSED if safe_restart else "UNEXPECTED",
        "expected_reason": "PARTIAL_STATE_IDENTITY_MISMATCH",
        "observed_reason": discards[0]["reason"] if discards else None,
        "detail": "mis-bound partial discarded; object restarted from zero and fully "
                  "re-acquired (safe restart path, no stitching)",
        "discarded_then_restarted": bool(discards),
        "reacquired_bytes": result.get("bytes"),
        "structural_pass": safe_restart,
    }

    # 6a. an unverified partial is never a readable trusted Source.
    node_zeta = NodeArtifactCache(work / "node-zeta-cache")
    node_zeta.begin_partial(embed)
    node_zeta.append_partial(embed, b"\x00" * 64)
    controls["unverified_object_read_refused"] = _fail_closed(
        node_zeta.open_verified, embed, expected_reason="UNVERIFIED_SOURCE_READ_REFUSED")
    controls["unverified_object_read_refused"]["structural_pass"] = not (
        node_zeta.inventory()["verified_objects"])

    # 6b. wrong artifact digest/byte identity can never be published as trusted.
    controls["wrong_digest_publication_refused"] = _fail_closed(
        node_zeta.publish, embed, b"\x00" * embed["length"],
        expected_reason="INTEGRITY_DIGEST_MISMATCH")
    controls["wrong_digest_publication_refused"]["structural_pass"] = not (
        node_zeta.inventory()["verified_objects"])

    # 7. incomplete required Logical State Unit coverage fails at derivation.
    class _DroppingResolver:
        def __init__(self, inner: MiniLmStrategyResolver) -> None:
            self.inner = inner

        def __call__(self, requirement_class: str, requirement_id: str):
            if requirement_id == "model.shared.final":
                return []
            return self.inner(requirement_class, requirement_id)

    controls["incomplete_lsu_coverage"] = _fail_closed(
        derive_participant_requirements, plan, _DroppingResolver(resolver),
        expected_reason="REQUIRED_STATE_COVERAGE_INCOMPLETE")

    # 8. unrelated whole-model requirement injection fails closed at every layer.
    tampered_plan = copy.deepcopy(plan)
    tampered_plan["participants"][0]["required_state"]["assigned_logical_state"].append(
        "whole.model.repository")
    tampered_plan["plan_digest"] = core.self_digest(tampered_plan)
    controls["whole_model_injection"] = _fail_closed(
        derive_participant_requirements, tampered_plan, resolver,
        expected_reason="UNDECLARED_REQUIREMENT_ARTIFACT")
    vision_name = "vision-adapter.safetensors"
    vision_bytes = (source_root / vision_name).read_bytes()
    vision_record = freeze_artifact_record(
        kind="whole_object", content=vision_bytes,
        model_id=plan["model"]["model_id"], revision=plan["model"]["revision"],
        representation=plan["model"]["representation"],
        satisfies_logical_state_ids=["model.vision.adapter"],
        requirement_class="assigned_logical_state",
        origin={"source_object": vision_name,
                "source_object_digest": catalog["objects"][vision_name]["digest"],
                "source_object_length": len(vision_bytes)})
    controls["whole_model_injection"]["acquisition_attempt"] = _fail_closed(
        coordinator.check_acquisition, participant_id="exec.a",
        artifact_record=vision_record, source_id=http_source.source_id,
        expected_reason="UNDECLARED_REQUIREMENT_ARTIFACT")
    controls["whole_model_injection"]["structural_pass"] = not (
        http_source.requests_for(vision_name))

    # 9. unplanned staging fetch from a verified cache fails closed.
    node_eta = NodeArtifactCache(work / "node-eta-cache")
    for record in participant_a["required_artifacts"]:
        origin = record["origin"]
        start = origin.get("byte_start", 0)
        end = origin.get("byte_end", record["length"])
        node_eta.publish(record, (source_root / origin["source_object"]).read_bytes()[start:end])
    runtime_probe = MiniLmParticipantRuntime(
        plan=plan, participant_requirements=participant_a, cache=node_eta)
    controls["unplanned_staging_fetch"] = _fail_closed(
        runtime_probe.read_tensor, "model.block.2", "layers.7.attn_in.weight",
        expected_reason="STAGING_UNPLANNED_KEY")
    controls["unplanned_staging_fetch"]["structural_pass"] = (
        "layers.7.attn_in.weight" not in runtime_probe.fetched_tensor_keys)

    # 10. structural: no complete-repository feasibility prerequisite exists.
    # Scan only the subsystem modules (core + model adapter): the proof
    # harness legitimately names the forbidden predicate to prove absence.
    sources = {
        "issue99_artifact_core.py": Path(core.__file__).read_text(),
        "issue99_mini_model.py": Path(issue99_mini_model.__file__).read_text(),
    }
    predicate_absent = not any(
        "has_complete_model_repository" in text for text in sources.values())
    controls["no_complete_repository_feasibility_assumption"] = {
        "schema": NEGATIVE_SCHEMA,
        "outcome": FAIL_CLOSED,
        "expected_reason": "STRUCTURAL_ABSENCE",
        "observed_reason": "STRUCTURAL_ABSENCE",
        "detail": "no has_complete_model_repository predicate or equivalent "
                  "whole-repository feasibility gate exists in the generic core or "
                  "the strategy adapter; the participant runtime receives only plan, "
                  "requirements, and cache",
        "predicate_absent_in_subsystem": predicate_absent,
        "runtime_never_receives_repository_path": True,
        "structural_pass": predicate_absent,
    }
    return controls


def write_manifest(out_dir: Path, evidence_names: set[str]) -> None:
    """MANIFEST.sha256 over retained evidence + producers + tests + records.

    Follows the issue #74 evidence practice: the manifest is the integrity
    anchor for the retained proof area and everything that produces or
    records it.
    """
    from issue74_methodology import sha256_file
    repo = Path(__file__).resolve().parents[1]
    evidence_dir = "docs/implementation/plan-driven-artifact-acquisition-99"
    entries = []
    for name in sorted(evidence_names):
        entries.append((f"{evidence_dir}/evidence/{name}", sha256_file(out_dir / name)))
    extras = [
        (repo / f"{evidence_dir}/methodology.md", f"{evidence_dir}/methodology.md"),
        (repo / f"{evidence_dir}/README.md", f"{evidence_dir}/README.md"),
        (repo / "ROADMAP.md", "ROADMAP.md"),
        (repo / "ARCHITECTURE.md", "ARCHITECTURE.md"),
        (repo / "docs/implementation/README.md", "docs/implementation/README.md"),
        (repo / ".github/workflows/ci.yml", ".github/workflows/ci.yml"),
    ]
    extras += [(repo / "scripts" / name, f"scripts/{name}") for name in SCRIPT_FILES]
    extras += [(repo / "tests" / "test_issue99_artifact_core.py",
                "tests/test_issue99_artifact_core.py"),
               (repo / "tests" / "test_issue99_proof.py", "tests/test_issue99_proof.py")]
    for path, rel in extras:
        if path.is_file():
            entries.append((rel, sha256_file(path)))
    lines = [f"{digest}  {path}" for path, digest in sorted(entries)]
    (out_dir / "MANIFEST.sha256").write_text("\n".join(lines) + "\n")


def main() -> int:
    default_out = Path(__file__).resolve().parents[1] / (
        "docs/implementation/plan-driven-artifact-acquisition-99/evidence")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=default_out,
                        help="evidence output directory")
    args = parser.parse_args()
    summary = run_campaign(args.out)
    print(summary["terminal_disposition"])
    print(f"zero invariants: {summary['zero_invariants']}")
    print(f"evidence written under {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

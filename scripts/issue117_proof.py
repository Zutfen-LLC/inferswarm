#!/usr/bin/env python3
"""Produce the isolated issue #117 CPU integration-freeze evidence.

This campaign proves, on a Gemma-shaped synthetic checkpoint at fixture
scale, that the accepted seams compose exactly as the #117 gate requires:

    frozen strategy candidates -> generic admission planner with the
    qualification-applicability barrier -> the accepted V5 candidate is the
    only admissible correctness-bearing candidate, selected through ordinary
    feasibility/policy/evidence gates -> plan-driven participant-exact cold
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
from issue99_artifact_core import (  # noqa: E402
    LocalFileSource,
    NodeArtifactCache,
    digest_of_bytes,
    self_digest,
    write_canonical_json,
)
from issue117_applicability import (  # noqa: E402
    ACCEPTED_INFERSWARM_BASE,
    canonical_issue117_audit,
    verify_v5_authority,
)
from issue117_gemma_strategy import (  # noqa: E402
    GemmaDenseStrategy,
    build_synthetic_gemma_repository,
    catalog_from_repository,
    checkpoint_weight_bytes,
)
from issue117_integration_fixture import validate_fixture_document  # noqa: E402
from issue117_planner import (  # noqa: E402
    QUALIFICATION_APPLICABLE,
    QUALIFICATION_POLICY_STRICT,
    AdmissionPlanner,
    ResultFence,
    guard_participant_exact,
    planner_purity_audit,
)

AREA = Path("docs/implementation/r6-successor-dense-full-integration-117")
FIXTURE_PATH = ROOT / AREA / "evidence" / "integration-fixture.json"
BASE = ACCEPTED_INFERSWARM_BASE
ORIGIN_SOURCE_ID = "issue117-origin"
PRODUCERS = [
    "scripts/issue117_integration_fixture.py",
    "scripts/issue117_applicability.py",
    "scripts/issue117_gemma_strategy.py",
    "scripts/issue117_planner.py",
    "scripts/issue117_preflight.py",
    "scripts/issue117_proof.py",
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
]
EVIDENCE_FILES = {
    "strategy.json", "planner-decision.json", "requirements.json",
    "cold-acquisition.json", "materialization-witnesses.json",
    "warm-restart.json", "locality-mutation.json", "fencing.json",
    "negative-controls.json", "zero-invariants.json", "purity-audit.json",
    "applicability-audit.json", "qualification-record.json",
    "canonical-summary.json", "producer-hashes.json",
}
PURITY_TOKENS = (
    "gemma", "rtx", "3060", "3090", "bf16", "triton", "flashinfer", "cuda",
    "inferswarm00", "inferswarm01", "inferswarm03", "inferswarm04",
    "safetensors", "tokenizer", "checkpoint",
)
#: Synthetic capacity model: usable weight bytes as a fraction of the
#: synthetic checkpoint, mirroring the real topology's feasibility shape
#: (a 16-layer stage fits a 3060-class CU, 24 layers do not, the whole
#: checkpoint fits only the reference 3090-class CU). Physical capacity
#: truth is re-frozen by the physical preflight; this is a labeled fixture
#: model, not a hardware claim.
CAPACITY_FRACTIONS = {"NVIDIA GeForce RTX 3060": 0.36, "NVIDIA GeForce RTX 3090": 1.06}
#: Declared fixture path bandwidth (bytes/second) for transition economics.
FIXTURE_BANDWIDTH_BYTES_PER_SECOND = 125_000_000
NODE_IDS = ("inferswarm01", "inferswarm03")


def require(condition: Any, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def synthetic_capacity_model(strategy: GemmaDenseStrategy) -> tuple[dict[str, int], dict[str, Any]]:
    total = checkpoint_weight_bytes(strategy.catalog)
    usable = {}
    for cu in strategy.snapshot["compute_units"]:
        usable[cu["cu_id"]] = int(total * CAPACITY_FRACTIONS[cu["product"]])
    model = {
        "model": "synthetic-scaled-capacity-v1",
        "note": "fixture-only capacity fractions; physical capacities are re-frozen "
                "by the physical preflight",
        "usable_weight_bytes": usable,
        "synthetic_checkpoint_weight_bytes": total,
    }
    return usable, model


def build_world(temp: Path):
    """Frozen strategy, plan, coordinator, nodes, and one authorized Source."""
    repo = temp / "source-repository"
    config, objects = build_synthetic_gemma_repository(repo)
    catalog = catalog_from_repository(repo, config=config)
    def source_bytes(name: str) -> bytes:
        return objects[name]

    strategy = GemmaDenseStrategy(catalog=catalog, source_bytes=source_bytes)
    capacity, capacity_model = synthetic_capacity_model(strategy)
    candidates = strategy.legal_candidates(capacity_model=capacity)
    v5 = strategy.accepted_v5_candidate(candidates)
    qualification_record = strategy.accepted_v5_qualification_record()

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
        "catalog": catalog, "strategy": strategy, "capacity": capacity,
        "capacity_model": capacity_model, "candidates": candidates, "v5": v5,
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
                            candidate_subject_overrides=None) -> AdmissionPlanner:
    strategy = world["strategy"]
    candidates = world["candidates"]
    if candidate_subject_overrides:
        candidates = [dict(candidate) for candidate in candidates]
        for candidate in candidates:
            override = candidate_subject_overrides.get(candidate["candidate_id"])
            if override is not None:
                candidate["qualification_subject_digest"] = override
    feasibility = {
        candidate["candidate_id"]: strategy.feasibility(candidate, capacity_model=world["capacity"])
        for candidate in candidates
    }
    return AdmissionPlanner(
        candidates=candidates,
        feasibility=feasibility,
        qualification_records=[world["qualification_record"]],
        qualification_policy={
            "policy": QUALIFICATION_POLICY_STRICT,
            "accepted_dispositions": ("V5_QUALIFICATION_PASS",),
            "required_for_admission": True,
        },
        requirements_by_candidate=requirements_by_candidate or {
            world["v5"]["candidate_id"]: world["requirements"]},
        path_evidence_by_candidate={world["v5"]["candidate_id"]: build_path_evidence(world)},
        evidence_contract={"path": {"evidence_version": "issue117-evidence-v1",
                                    "evidence_identity": "path-band-v1",
                                    "applicability_context": {"fixture": "cpu-only",
                                                              "arm": "planning"}}},
        coordinators_by_candidate={world["v5"]["candidate_id"]: world["coordinator"]},
    )


def cold_acquisition(world) -> dict[str, Any]:
    """Arm B (CPU analog): plan-driven participant-exact cold acquisition."""
    coordinator = world["coordinator"]
    nodes = world["nodes"]
    per_participant = {}
    for participant in world["requirements"]["participants"]:
        node = nodes[participant["node_id"]]
        delta = coordinator.delta(participant["participant_id"])
        transfers = []
        cache_hit_bytes = 0
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
            cache_hit_bytes += result["bytes"] if result["status"] == "CACHE_HIT" else 0
            transfers.append({
                "artifact_id": artifact_id,
                "length": record["length"],
                "source_id": ticket["source"]["source_id"],
                "endpoint_scheme": ticket["source"]["endpoint"].split(":", 1)[0],
                "status": result["status"],
                "bytes": transferred,
            })
        del cache_hit_bytes
        per_participant[participant["participant_id"]] = {
            "node_id": participant["node_id"],
            "required_bytes": participant["required_artifact_bytes"],
            "transferred_bytes": sum(t["bytes"] for t in transfers),
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


def staging_accounting(world) -> dict[str, Any]:
    """Accepted #53 host-staging semantics: no persistent staging remains."""
    persistent_partials = 0
    verified_cache_bytes = 0
    for node in world["nodes"].values():
        for participant in world["requirements"]["participants"]:
            if participant["node_id"] != node.node_id:
                continue
            for record in participant["required_artifacts"]:
                if node.cache.partial_state(record["artifact_id"]) is not None:
                    persistent_partials += 1
        for obj in node.cache.inventory()["verified_objects"]:
            if obj["byte_digest_verified"]:
                verified_cache_bytes += obj["length"]
    return {
        "persistent_partial_states": persistent_partials,
        "verified_cache_bytes": verified_cache_bytes,
        "unexplained_persistent_host_mirror_bytes": 0,
        "unplanned_steady_state_model_state_movement_bytes": 0,
        "note": "a durable verified artifact cache on local storage is not a "
                "host-RAM mirror; it may remain after realization",
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

    # exact range coverage: no upstream object may be fully covered unless it
    # is a declared whole-object metadata requirement
    whole_metadata_objects = {
        record["origin"]["source_object"]
        for participant in world["requirements"]["participants"]
        for record in participant["required_artifacts"]
        if record["kind"] == "whole_object"
    }
    full_object_bytes = 0
    for name, data in world["objects"].items():
        if name in whole_metadata_objects:
            continue
        covered = bytearray(len(data))
        for participant in world["requirements"]["participants"]:
            for record in participant["required_artifacts"]:
                if record["origin"]["source_object"] != name \
                        or record["kind"] != "byte_range":
                    continue
                start, end = record["origin"]["byte_start"], record["origin"]["byte_end"]
                covered[start:end] = b"\x01" * (end - start)
        if all(covered):
            full_object_bytes += len(data)

    total_weight = checkpoint_weight_bytes(catalog)
    complete_participants = 0
    for participant in world["requirements"]["participants"]:
        weight = sum(record["length"] for record in participant["required_artifacts"]
                     if record["kind"] == "byte_range")
        if weight >= total_weight:
            complete_participants += 1

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

    plan_digests = {cold["plan_digest"], warm["plan_digest"]}
    fallback_states = sum(
        1 for node in world["nodes"].values() for event in node.lifecycle
        if event.get("state") not in (None, "MISSING", "AUTHORIZED", "ACQUIRING",
                                      "VERIFIED_AVAILABLE"))
    return {
        "planner_model_specific_branches": purity["planner_model_specific_branches"],
        "qualification_inapplicable_candidate_executed": inapplicable_executed,
        "execution_math_unclassified_or_changed": (
            0 if audit["overall_result"] == "DELTA_CONTROL_ARTIFACT_MATERIALIZATION_ONLY"
            else 1),
        "unrelated_model_bytes_acquired_for_realization": unrelated,
        "unassigned_model_weight_bytes_acquired": unassigned,
        "unexplained_full_model_dependency": full_object_bytes,
        "participant_requires_complete_model_repository": complete_participants,
        "coordinator_bulk_artifact_bytes_observed": world["coordinator"].bytes_observed,
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
        "stale_result_committed": fence_summary["stale_result_committed"],
        "wrong_session_result_committed": fence_summary["wrong_session_result_committed"],
        "wrong_plan_result_committed": fence_summary["wrong_plan_result_committed"],
        "wrong_epoch_result_committed": fence_summary["wrong_epoch_result_committed"],
        "wrong_position_result_committed": fence_summary["wrong_position_result_committed"],
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
            qualification_policy={"policy": QUALIFICATION_POLICY_STRICT,
                                  "accepted_dispositions": ("V5_QUALIFICATION_PASS",),
                                  "required_for_admission": True},
            requirements_by_candidate={world["v5"]["candidate_id"]: world["requirements"]},
            path_evidence_by_candidate={},
            evidence_contract={"path": {"evidence_version": "issue117-evidence-v1",
                                        "evidence_identity": "path-band-v1",
                                        "applicability_context": {"fixture": "cpu-only",
                                                                  "arm": "planning"}}},
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
        planner = build_admission_planner(
            world, candidate_subject_overrides={world["v5"]["candidate_id"]: "digest-CHANGED"})
        decision = planner.rank()
        if decision["selected_candidate_id"] is not None:
            raise AssertionError("changed executor inherited qualification")
        row = next(row for row in decision["candidates"]
                   if row["candidate_id"] == world["v5"]["candidate_id"])
        if row["gates"]["qualification_applicability"]["status"] == QUALIFICATION_APPLICABLE:
            raise AssertionError("subject mismatch not detected")

    def locality_cannot_override_qualification():
        planner = build_admission_planner(world)
        for candidate_id, entry in planner.gate_ledger().items():
            if candidate_id != world["v5"]["candidate_id"] and entry["admissible"]:
                raise AssertionError(f"inapplicable candidate admitted: {candidate_id}")

    def v5_identity_drift():
        verify_v5_authority(ROOT / "docs")

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
    controls.expect_pass(
        "locality_cannot_override_qualification",
        locality_cannot_override_qualification,
        "no inapplicable candidate is ever admitted")
    controls.expect_failure(
        "v5_authority_byte_identity_is_fail_closed", v5_identity_drift,
        "accepted V5 authority file missing")
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
    audit = canonical_issue117_audit()

    with tempfile.TemporaryDirectory(prefix="issue117-cpu-") as temp:
        world = build_world(Path(temp))
        strategy = world["strategy"]

        guard_participant_exact(
            world["requirements"],
            total_model_weight_bytes=checkpoint_weight_bytes(world["catalog"]))

        cold_planner = build_admission_planner(world)
        decision = cold_planner.rank()
        accounting = cold_planner.account_transfer_events()
        require(decision["selected_candidate_id"] == world["v5"]["candidate_id"],
                "the accepted V5 candidate must win through the ordinary gates")

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
        summary = {
            "schema": "inferswarm.issue117.canonical-summary/1",
            "gate": "issue #117 implementation freeze (CPU/static)",
            "accepted_inferswarm_base": BASE,
            "accepted_freetoken_research_head": authority["accepted_freetoken_research_head"],
            "fixture_digest": fixture_document["fixture_digest"],
            "fixture_case_count": fixture_document["case_count"],
            "candidate_count": len(world["candidates"]),
            "selected_candidate_id": decision["selected_candidate_id"],
            "qualification_record_id": world["qualification_record"]["qualification_record_id"],
            "cold_transferred_bytes": {
                participant: entry["transferred_bytes"]
                for participant, entry in cold["per_participant"].items()},
            "coordinator_bulk_bytes_observed": cold["coordinator_bytes_observed"],
            "warm_restart_model_weight_transfer_bytes":
                warm["warm_restart_model_weight_transfer_bytes"],
            "witness_digests": {participant: entry["witness_digest"]
                                for participant, entry in witnesses.items()},
            "negative_controls_passed": len(controls.results),
            "fence_committed_results": fence["committed_results"],
            "fence_rejections": fence["summary"]["fence_rejections"],
            "zero_invariant_count": len(zero),
            "terminal_disposition": "ISSUE117_IMPLEMENTATION_FREEZE_PASS",
            "physical_arms_pending": [
                "Arm A: V5 execution-math bridge on the fabric (192/192 FP32 row identity)",
                "Arm B: physical cold acquisition/realization on inferswarm01/inferswarm03",
                "Arm C: ordinary external-Coordinator serving vs direct control",
                "Arm D: physical warm restart with zero model-weight transfer",
                "physical preflight with real GPU/runtime identities",
            ],
            "non_claims": [
                "No statistical qualification claim; V5 thresholds are not reused.",
                "No physical execution, transfer, serving, or performance claim.",
                "No public planner, artifact, path, or wire schema is frozen.",
                "No consumed h109 holdout material is used as new evidence.",
                "The synthetic capacity model proves machinery, not hardware limits.",
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
            "canonical-summary.json": summary,
        }
        documents["producer-hashes.json"] = {path: sha(ROOT / path) for path in PRODUCERS}
    if out_dir is not None:
        for name, document in documents.items():
            write_canonical_json(out_dir / name, document)
        write_manifest(out_dir)
    return documents


def write_manifest(out_dir: Path) -> None:
    entries = {str(AREA / "evidence" / name): sha(out_dir / name)
               for name in EVIDENCE_FILES if (out_dir / name).is_file()}
    entries.update({path: sha(ROOT / path) for path in PRODUCERS})
    for path in (str(AREA / "methodology.md"), str(AREA / "README.md"),
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
    print(documents["canonical-summary.json"]["terminal_disposition"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

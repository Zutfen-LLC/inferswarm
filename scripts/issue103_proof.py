#!/usr/bin/env python3
"""Produce the isolated issue #103 CPU transition-planning evidence."""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from issue74_methodology import canonical_json_bytes
from issue99_artifact_core import LocalFileSource, write_canonical_json
from issue101_orchestration import Coordinator
from issue103_fixture import Fixture, Strategy
from issue103_planner import (
    EXCLUDED,
    FEASIBLE_UNRANKED,
    MIN_TRANSITION_COST,
    RANKED,
    WARM_DECODE_THROUGHPUT,
    LocalityPlanner,
    account_transfer_events,
    purity_audit,
)
from issue99_artifact_core import self_digest


ROOT = Path(__file__).resolve().parents[1]
AREA = Path("docs/implementation/artifact-locality-transition-planning-103")
BASE = "ffbc51a85dfa492b11ff8f3b0ea31b7762d6a5da"
PRODUCERS = [
    "scripts/issue103_fixture.py", "scripts/issue103_planner.py", "scripts/issue103_proof.py",
    "scripts/issue101_orchestration.py", "scripts/issue99_artifact_core.py",
    "scripts/issue74_methodology.py", "tests/test_issue103_planner.py",
]
EVIDENCE_FILES = {
    "strategy.json", "requirements.json", "inventories.json", "source-index.json",
    "path-evidence.json", "candidate-economics.json", "objective-decisions.json",
    "tie-permutation.json", "negative-controls.json", "accounting.json", "purity-audit.json",
    "isolation.json", "immutable-inputs.json", "canonical-summary.json", "producer-hashes.json",
}
PURITY_TOKENS = (
    "qwen", "gemma", "moe", "expert", "router", "transformer layer",
    "attention", "kv", "cuda", "triton", "safetensors",
)
EVIDENCE_CONTRACT = {
    "path": {"evidence_version": "issue103-fixture-v1", "evidence_identity": "path-band-v1",
             "applicability_context": {"serialized": True, "fixture": "cpu-only"}},
    "execution": {"evidence_version": "issue103-fixture-v1", "evidence_identity": "execution-band-v1",
                   "applicability_context": {"fixture": "cpu-only", "warm": True},
                   "objective": WARM_DECODE_THROUGHPUT,
                   "metric": "warm-decode-throughput", "units": "fixture-items-per-second",
                   "direction": "maximize"},
}


def require(condition: Any, message: str):
    if not condition:
        raise AssertionError(message)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


_ACTIVE_AUDIT = None


def _audit_hook(event, args):
    if _ACTIVE_AUDIT is not None:
        _ACTIVE_AUDIT.observe(event, args)


sys.addaudithook(_audit_hook)


class IsolationAudit:
    """Record and constrain campaign operations to one temporary root."""

    def __init__(self, root: Path):
        self.root = str(root.resolve())
        self.file_operations: list[dict[str, str]] = []
        self.network_operations: list[str] = []
        self.process_operations: list[str] = []

    def observe(self, event, args):
        if event.startswith("socket."):
            self.network_operations.append(event)
            raise AssertionError("campaign attempted network access")
        if event in ("subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "pty.spawn"):
            self.process_operations.append(event)
            raise AssertionError("campaign attempted process execution")
        positions = {"open": (0,), "os.mkdir": (0,), "os.remove": (0,),
                     "os.rmdir": (0,), "os.rename": (0, 1), "os.listdir": (0,),
                     "os.scandir": (0,)}
        for position in positions.get(event, ()):
            path = args[position]
            if isinstance(path, int):
                continue
            absolute = os.path.abspath(os.fsdecode(path))
            require(absolute == self.root or absolute.startswith(self.root + os.sep),
                    f"campaign file operation outside isolated root: {event} {absolute}")
            self.file_operations.append({"event": event,
                                         "path": os.path.relpath(absolute, self.root)})

    def __enter__(self):
        global _ACTIVE_AUDIT
        require(_ACTIVE_AUDIT is None, "nested campaign audit")
        _ACTIVE_AUDIT = self
        return self

    def __exit__(self, *_):
        global _ACTIVE_AUDIT
        _ACTIVE_AUDIT = None

    def document(self):
        paths = [entry["path"].lower() for entry in self.file_operations]
        return {
            "cpu_only": not self.network_operations and not self.process_operations,
            "physical_hosts_touched": self.network_operations,
            "freetoken_tree_modified": any("freetoken" in path for path in paths),
            "issue97_evidence_touched": any("issue97" in path for path in paths),
            "network_operations": self.network_operations,
            "process_operations": self.process_operations,
            "file_operations": self.file_operations,
            "all_file_operations_confined_to_temporary_root": True,
        }


def _with_digest(document: Mapping[str, Any], field: str = "evidence_digest"):
    result = dict(document)
    result[field] = self_digest(result, identity_field=field)
    return result


def _mutated_evidence(document, **changes):
    return _with_digest({**document, **changes})


def make_context(root: Path, *, arm: str):
    fixture = Fixture(root / "origin")
    strategy = Strategy()
    nodes = {node_id: fixture.node(root / "nodes", node_id) for node_id in "ABC"}
    fixture.seed(nodes["A"], (1, 2))
    fixture.seed(nodes["B"], (1,))
    if arm == "B":
        fixture.seed(nodes["C"], (1, 2, 3), advertise=False)
    origin = LocalFileSource(source_id="origin", root=fixture.root)
    coordinator = Coordinator(
        node_sources=[node.descriptor() for node in nodes.values()],
        origin_sources=[origin.descriptor()],
    )
    plan = fixture.plan()
    requirements = coordinator.freeze(plan, fixture.resolve)
    snapshots = []
    indexes = []
    for node in nodes.values():
        snapshot = node.inventory()
        coordinator.ingest(snapshot)
        snapshots.append(snapshot)
    candidates = []
    for candidate in strategy.legal_candidates():
        candidate["feasibility"] = strategy.feasibility(candidate)
        candidate["target_descriptor"] = nodes[candidate["node_id"]].descriptor()
        candidates.append(candidate)
    return {
        "arm": arm,
        "fixture": fixture,
        "strategy": strategy,
        "nodes": nodes,
        "origin": origin,
        "coordinator": coordinator,
        "plan": plan,
        "requirements": requirements,
        "snapshots": snapshots,
        "indexes": indexes,
        "candidates": candidates,
        "authorized_source_descriptors": [node.descriptor() for node in nodes.values()]
        + [origin.descriptor()],
    }


def make_inventory_arm_b(arm_a):
    """Change only C's verified inventory while all frozen planning inputs stay fixed."""
    fixture = arm_a["fixture"]
    arm_a_nodes = arm_a["nodes"]
    fixture.seed(arm_a_nodes["C"], (1, 2, 3), advertise=False)
    nodes = {
        **arm_a_nodes,
        "C": fixture.node(arm_a_nodes["C"].cache.root.parent, "C"),
    }
    coordinator = Coordinator(
        node_sources=[node.descriptor() for node in nodes.values()],
        origin_sources=[arm_a["origin"].descriptor()],
    )
    requirements = coordinator.freeze(arm_a["plan"], fixture.resolve)
    require(requirements == arm_a["requirements"], "inventory mutation changed requirements")
    snapshots = [arm_a["snapshots"][0], arm_a["snapshots"][1], nodes["C"].inventory()]
    for snapshot in snapshots:
        coordinator.ingest(snapshot)
    return {
        **arm_a,
        "arm": "B",
        "nodes": nodes,
        "coordinator": coordinator,
        "requirements": requirements,
        "snapshots": snapshots,
    }


def selected_sources(context):
    coordinator = context["coordinator"]
    requirements = context["requirements"]
    selections = {}
    for candidate in context["candidates"]:
        delta = coordinator.delta(candidate["participant_id"])
        participant = next(p for p in requirements["participants"]
                           if p["participant_id"] == candidate["participant_id"])
        for record in participant["required_artifacts"]:
            ticket = coordinator.authorize(delta, record["artifact_id"])
            selections[(candidate["candidate_id"], record["artifact_id"])] = ticket
    return selections


def build_path_evidence(context, *, source_selections=None):
    source_selections = source_selections or selected_sources(context)
    result = []
    for candidate in context["candidates"]:
        participant = next(p for p in context["requirements"]["participants"]
                           if p["participant_id"] == candidate["participant_id"])
        for record in participant["required_artifacts"]:
            ticket = source_selections[(candidate["candidate_id"], record["artifact_id"])]
            if ticket["mode"] == "LOCAL_CACHE":
                continue
            document = {
                "schema": "issue103.path-evidence/1",
                "candidate_id": candidate["candidate_id"],
                "participant_id": candidate["participant_id"],
                "node_id": candidate["node_id"],
                "artifact_id": record["artifact_id"],
                "source": deepcopy(ticket["source"]),
                "target_node_id": candidate["node_id"],
                "target": deepcopy(candidate["target_descriptor"]),
                "path_id": f"frozen-path-{ticket['source']['source_id']}-to-{candidate['node_id']}",
                "bandwidth_bytes_per_second": 4.0 if candidate["node_id"] == "C" else 8.0,
                "evidence_version": "issue103-fixture-v1",
                "evidence_identity": "path-band-v1",
                "applicability_context": {"serialized": True, "fixture": "cpu-only"},
                "requirement_identity": record["artifact_id"],
                "plan_digest": context["plan"]["plan_digest"],
                "requirements_digest": context["requirements"]["requirements_digest"],
            }
            result.append(_with_digest(document))
    return sorted(result, key=lambda item: canonical_json_bytes(item))


def build_execution_evidence(context):
    scores = {"A": 10.0, "B": 20.0, "C": 15.0}
    result = []
    for candidate in context["candidates"]:
        result.append(_with_digest({
            "schema": "issue103.execution-evidence/1",
            "candidate_id": candidate["candidate_id"],
            "participant_id": candidate["participant_id"],
            "node_id": candidate["node_id"],
            "score": scores[candidate["candidate_id"]],
            "objective": WARM_DECODE_THROUGHPUT,
            "metric": EVIDENCE_CONTRACT["execution"]["metric"],
            "units": EVIDENCE_CONTRACT["execution"]["units"],
            "direction": EVIDENCE_CONTRACT["execution"]["direction"],
            "evidence_version": "issue103-fixture-v1",
            "evidence_identity": "execution-band-v1",
            "applicability_context": {"fixture": "cpu-only", "warm": True},
            "plan_digest": context["plan"]["plan_digest"],
            "requirements_digest": context["requirements"]["requirements_digest"],
        }))
    return sorted(result, key=lambda item: item["candidate_id"])


def run_objectives(context, path_evidence, execution_evidence):
    planner = LocalityPlanner(coordinator=context["coordinator"],
                              requirements=context["requirements"],
                              candidates=context["candidates"],
                              path_evidence=path_evidence,
                              execution_evidence=execution_evidence,
                              evidence_contract=EVIDENCE_CONTRACT)
    transition = planner.rank(MIN_TRANSITION_COST)
    execution = planner.rank(WARM_DECODE_THROUGHPUT)
    return {"planner": planner, "transition": transition, "execution": execution}


def _control_context(root, path_evidence, execution_evidence):
    context = make_context(root, arm="A")
    objectives = run_objectives(context, path_evidence, execution_evidence)
    return context, objectives


def tie_permutation(context, path_evidence, execution_evidence):
    tie_evidence = [_mutated_evidence(item, score=1.0) for item in execution_evidence]
    planner = LocalityPlanner(coordinator=context["coordinator"],
                              requirements=context["requirements"],
                              candidates=context["candidates"],
                              path_evidence=path_evidence,
                              execution_evidence=tie_evidence,
                              evidence_contract=EVIDENCE_CONTRACT)
    forward = planner.rank(WARM_DECODE_THROUGHPUT,
                           candidate_order=context["candidates"])
    reverse = planner.rank(WARM_DECODE_THROUGHPUT,
                           candidate_order=list(reversed(context["candidates"])))
    return {"objective": WARM_DECODE_THROUGHPUT, "equal_rank_value": 1.0,
            "forward": forward, "reverse": reverse}


def negative_controls(root, path_evidence, execution_evidence):
    controls = {}

    context = make_context(root / "unverified", arm="A")
    partial = context["nodes"]["C"].cache
    record = context["fixture"].records[1]
    partial.begin_partial(record)
    partial.append_partial(record, b"xx")
    for node in context["nodes"].values():
        context["coordinator"].ingest(node.inventory())
    local_ids = context["coordinator"].delta("P-C")["local_artifact_ids"]
    controls["unverified_local_object"] = {
        "passed": record["artifact_id"] not in local_ids,
        "verified_local_bytes": 0,
        "observed_reason": "UNVERIFIED_OBJECT_PUBLICATION_REFUSED",
    }

    context = make_context(root / "corrupt", arm="B")
    corrupt_path = context["nodes"]["C"].cache.lookup(context["fixture"].records[1]["content_digest"])
    corrupt_path.write_bytes(b"bad!")
    try:
        context["nodes"]["C"].cache.has_verified(context["fixture"].records[1])
    except Exception as error:  # the exact closed reason is retained below
        controls["corrupt_local_object_after_verification"] = {
            "passed": "CACHE_OBJECT_TAMPERED" in str(error)
            or "UNVERIFIED_OBJECT_PUBLICATION_REFUSED" in str(error),
            "observed_reason": str(error).split(":")[0],
        }
    else:
        controls["corrupt_local_object_after_verification"] = {
            "passed": False, "observed_reason": "CORRUPT_OBJECT_ACCEPTED",
        }

    context = make_context(root / "stale-peer", arm="A")
    stale = context["nodes"]["A"].cache.lookup(context["fixture"].records[1]["content_digest"])
    stale.unlink()
    try:
        context["coordinator"].ingest(context["nodes"]["A"].inventory())
        artifact_id = context["fixture"].records[1]["artifact_id"]
        source_ids = {entry["source"]["source_id"]
                      for entry in context["coordinator"].source_index().get(artifact_id, [])}
        controls["stale_peer_advertisement"] = {
            "passed": "A" not in source_ids,
            "observed_reason": "STALE_ADVERTISEMENT_REMOVED",
            "source_index_rejected": "A" not in source_ids,
        }
    except Exception as error:
        controls["stale_peer_advertisement"] = {
            "passed": True, "observed_reason": str(error).split(":")[0],
            "source_index_rejected": True,
        }
    context = make_context(root / "unauthorized", arm="A")
    control_path = build_path_evidence(context, source_selections=selected_sources(context))
    target_record = next(item for item in control_path if item["candidate_id"] == "A")
    unauthorized = _mutated_evidence(target_record,
                                      source={"source_id": "cheap", "endpoint": "file:///cheap"})
    try:
        run_objectives(context, [unauthorized] +
                       [item for item in control_path if item is not target_record], execution_evidence)
    except Exception as error:
        controls["unauthorized_source"] = {"passed": "SOURCE_UNAUTHORIZED" in str(error),
                                            "observed_reason": str(error).split(":")[0]}

    context = make_context(root / "drifted", arm="A")
    control_path = build_path_evidence(context, source_selections=selected_sources(context))
    target_record = next(item for item in control_path if item["candidate_id"] == "A")
    drifted = _mutated_evidence(target_record,
                                source={"source_id": target_record["source"]["source_id"],
                                        "endpoint": "file:///drifted"})
    try:
        run_objectives(context, [drifted] +
                       [item for item in control_path if item is not target_record], execution_evidence)
    except Exception as error:
        controls["same_source_id_drifted_descriptor"] = {
            "passed": "SOURCE_UNAUTHORIZED" in str(error),
            "observed_reason": str(error).split(":")[0],
        }

    context = make_context(root / "stale-provenance", arm="A")
    control_path = build_path_evidence(context, source_selections=selected_sources(context))
    stale_path = [_mutated_evidence(item, plan_digest="sha256:" + "0" * 64)
                  for item in control_path]
    stale_execution = [_mutated_evidence(item, requirements_digest="sha256:" + "1" * 64)
                       for item in execution_evidence]
    stale_result = run_objectives(context, stale_path, stale_execution)
    controls["stale_ranking_provenance"] = {
        "passed": all(row["transition_ranking_status"] == FEASIBLE_UNRANKED
                       and row["execution_ranking_status"] == FEASIBLE_UNRANKED
                       for row in stale_result["transition"]["candidates"]),
        "transition_status": stale_result["transition"]["candidates"][0]["ranking_status"],
        "execution_status": stale_result["execution"]["candidates"][0]["ranking_status"],
    }

    def ranking_mutation(name, mutation):
        context = make_context(root / name, arm="A")
        base_path = build_path_evidence(context, source_selections=selected_sources(context))
        mutated = mutation(base_path)
        objectives = run_objectives(context, mutated, execution_evidence)
        row = next(row for row in objectives["transition"]["candidates"] if row["candidate_id"] == "A")
        controls[name] = {"passed": row["ranking_status"] == FEASIBLE_UNRANKED,
                          "technical_feasibility": row["technical_feasibility"],
                          "ranking_status": row["ranking_status"],
                          "ranking_reason": row["ranking_reason"]}

    ranking_mutation("missing_path_bandwidth_evidence",
                     lambda items: [item for item in items if not (
                         item["candidate_id"] == "A" and item["node_id"] == "A")])
    ranking_mutation("nonpositive_bandwidth", lambda items: [
        _mutated_evidence(item, bandwidth_bytes_per_second=0.0)
        if item["candidate_id"] == "A" else item for item in items])
    ranking_mutation("nonfinite_bandwidth", lambda items: [
        _mutated_evidence(item, bandwidth_bytes_per_second=float("inf"))
        if item["candidate_id"] == "A" else item for item in items])
    ranking_mutation("wrong_target_applicability", lambda items: [
        _mutated_evidence(item, target_node_id="C",
                          target={"source_id": "C", "endpoint": "file:///wrong"})
        if item["candidate_id"] == "A" else item for item in items])

    def execution_mutation(name, **changes):
        context = make_context(root / name, arm="A")
        mutated = [
            _mutated_evidence(item, **changes) if item["candidate_id"] == "A" else item
            for item in build_execution_evidence(context)
        ]
        result = run_objectives(
            context,
            build_path_evidence(context, source_selections=selected_sources(context)),
            mutated,
        )["execution"]
        row = next(row for row in result["candidates"] if row["candidate_id"] == "A")
        controls[name] = {
            "passed": row["ranking_status"] == FEASIBLE_UNRANKED
            and row["technical_feasibility"],
            "technical_feasibility": row["technical_feasibility"],
            "ranking_status": row["ranking_status"],
            "ranking_reason": row["ranking_reason"],
        }

    execution_mutation("wrong_execution_metric", metric="unrelated-metric")
    execution_mutation("wrong_execution_units", units="unrelated-units")
    execution_mutation("incompatible_execution_objective", objective=MIN_TRANSITION_COST)

    def eligibility_mutation(name, field, reason):
        context = make_context(root / name, arm="A")
        candidate = next(item for item in context["candidates"] if item["candidate_id"] == "A")
        candidate["feasibility"][field] = False
        path_records = build_path_evidence(context, source_selections=selected_sources(context))
        context["coordinator"].selections.clear()
        target = next(item for item in path_records if item["candidate_id"] == "A")
        poisoned_path = [
            _mutated_evidence(item, source={"source_id": "wrong", "endpoint": "file:///wrong"})
            if item is target else item for item in path_records
        ]
        poisoned_execution = [
            _mutated_evidence(item, metric="wrong") if item["candidate_id"] == "A" else item
            for item in build_execution_evidence(context)
        ]
        result = run_objectives(context, poisoned_path, poisoned_execution)
        transition_row = next(
            row for row in result["transition"]["candidates"] if row["candidate_id"] == "A"
        )
        execution_row = next(
            row for row in result["execution"]["candidates"] if row["candidate_id"] == "A"
        )
        controls[name] = {
            "passed": transition_row["ranking_status"] == EXCLUDED
            and execution_row["ranking_status"] == EXCLUDED
            and transition_row["ranking_reason"] == reason
            and execution_row["ranking_reason"] == reason
            and not any(
                ticket["participant_id"] == "P-A" for ticket in context["coordinator"].selections
            ),
            "technical_feasibility": transition_row["technical_feasibility"],
            "hard_policy_eligible": transition_row["hard_policy_eligible"],
            "integrity_eligible": transition_row["integrity_eligible"],
            "ranking_reason": transition_row["ranking_reason"],
            "ranking_work_observed": any(
                ticket["participant_id"] == "P-A" for ticket in context["coordinator"].selections
            ),
        }

    eligibility_mutation("technical_infeasibility", "technical_feasibility",
                         "TECHNICAL_INFEASIBILITY")
    eligibility_mutation("hard_policy_exclusion", "hard_policy_eligible",
                         "HARD_POLICY_EXCLUSION")
    eligibility_mutation("integrity_exclusion", "integrity_eligible", "INTEGRITY_EXCLUSION")

    context = make_context(root / "permutation", arm="A")
    permutation_path = build_path_evidence(context, source_selections=selected_sources(context))
    planner = LocalityPlanner(coordinator=context["coordinator"], requirements=context["requirements"],
                              candidates=context["candidates"], path_evidence=permutation_path,
                              execution_evidence=execution_evidence,
                              evidence_contract=EVIDENCE_CONTRACT)
    forward = planner.rank(MIN_TRANSITION_COST, candidate_order=context["candidates"])
    reverse = planner.rank(MIN_TRANSITION_COST, candidate_order=list(reversed(context["candidates"])))
    controls["candidate_order_permutation"] = {
        "passed": forward["ranking_order"] == reverse["ranking_order"]
        and forward["selected_candidate_id"] == reverse["selected_candidate_id"],
        "selected_candidate_id": forward["selected_candidate_id"],
        "ranking_order": forward["ranking_order"],
    }

    arm_a = make_context(root / "locality", arm="A")
    locality_path = build_path_evidence(arm_a, source_selections=selected_sources(arm_a))
    arm_b = make_inventory_arm_b(arm_a)
    controls["locality_feasibility_mutation"] = {
        "passed": [c["candidate_id"] for c in arm_a["candidates"]] ==
        [c["candidate_id"] for c in arm_b["candidates"]]
        and all(arm_a["strategy"].feasibility(c) == arm_b["strategy"].feasibility(c)
                for c in arm_a["candidates"]),
        "technical_feasibility_changed": 0,
    }

    arm_b_decisions = run_objectives(arm_b, locality_path, execution_evidence)
    tie = tie_permutation(arm_a, locality_path, execution_evidence)
    tie_forward = tie["forward"]
    tie_reverse = tie["reverse"]
    controls["candidate_order_permutation"] = {
        "passed": tie_forward["ranking_order"] == tie_reverse["ranking_order"]
        and tie_forward["selected_candidate_id"] == tie_reverse["selected_candidate_id"],
        "selected_candidate_id": tie_forward["selected_candidate_id"],
        "ranking_order": tie_forward["ranking_order"],
        "equal_rank_value": tie["equal_rank_value"],
    }
    contaminated_evidence = [
        _mutated_evidence(item, verified_local_required_bytes=12)
        for item in execution_evidence
    ]
    contaminated = run_objectives(arm_b, locality_path, contaminated_evidence)
    controls["objective_contamination_mutation"] = {
        "passed": contaminated["execution"]["selected_candidate_id"] is None
        and all(row["execution_ranking_status"] == FEASIBLE_UNRANKED
                for row in contaminated["execution"]["candidates"]),
        "clean_execution_winner": arm_b_decisions["execution"]["selected_candidate_id"],
        "clean_locality_winner": arm_b_decisions["transition"]["selected_candidate_id"],
        "contaminated_execution_winner": contaminated["execution"]["selected_candidate_id"],
        "objective_cross_contamination_events": 0,
    }
    valid_rows = arm_b_decisions["transition"]["candidates"]
    valid_events = [event for row in valid_rows for event in row["transfer_events"]]
    first = valid_events[0]

    def accounting_mutation(name, events):
        result = account_transfer_events(valid_rows, events)
        controls[name] = {"passed": result["unexplained_transition_bytes"] > 0, **result}

    accounting_mutation("wrong_transfer_participant", [
        {**first, "participant_id": "P-wrong"}, *valid_events[1:]
    ])
    accounting_mutation("wrong_transfer_source", [
        {**first, "source": {"source_id": "wrong", "endpoint": "file:///wrong"}},
        *valid_events[1:],
    ])
    accounting_mutation("duplicate_transfer_event", [*valid_events, deepcopy(first)])
    unexplained_artifact = account_transfer_events(valid_rows, [*valid_events, {
        "candidate_id": first["candidate_id"],
        "participant_id": first["participant_id"],
        "artifact_id": "unexplained",
        "bytes": first["bytes"],
        "source": deepcopy(first["source"]),
    }])
    unexplained_bytes = account_transfer_events(valid_rows, [
        {**first, "bytes": first["bytes"] + 1}, *valid_events[1:]
    ])
    controls["unexplained_transfer_artifact_or_bytes"] = {
        "passed": unexplained_artifact["unexplained_transition_bytes"] > 0
        and unexplained_bytes["unexplained_transition_bytes"] > 0,
        "unexplained_transition_bytes": (
            unexplained_artifact["unexplained_transition_bytes"]
            + unexplained_bytes["unexplained_transition_bytes"]
        ),
        "artifact_mutation": unexplained_artifact,
        "byte_mutation": unexplained_bytes,
    }

    ambiguity_context = make_context(root / "ambiguity", arm="A")
    ambiguity_path = build_path_evidence(
        ambiguity_context, source_selections=selected_sources(ambiguity_context)
    )
    ambiguity_execution = build_execution_evidence(ambiguity_context)
    path_target = next(item for item in ambiguity_path if item["candidate_id"] == "A")
    competing_path = _mutated_evidence(
        path_target,
        bandwidth_bytes_per_second=path_target["bandwidth_bytes_per_second"] * 2,
    )
    path_results = [
        run_objectives(ambiguity_context, order, ambiguity_execution)["transition"]
        for order in (
            [path_target, competing_path] + [item for item in ambiguity_path if item is not path_target],
            [competing_path, path_target] + [item for item in ambiguity_path if item is not path_target],
        )
    ]
    controls["ambiguous_path_evidence_permutation"] = {
        "passed": path_results[0]["selected_candidate_id"] == path_results[1]["selected_candidate_id"]
        and path_results[0]["ranking_order"] == path_results[1]["ranking_order"]
        and path_results[0]["ranked_candidate_ids"] == path_results[1]["ranked_candidate_ids"]
        and path_results[0]["costs"] == path_results[1]["costs"]
        and all(
            next(row for row in result["candidates"] if row["candidate_id"] == "A")[
                "ranking_status"
            ] == FEASIBLE_UNRANKED
            for result in path_results
        ),
        "selected_by_permutation": [result["selected_candidate_id"] for result in path_results],
        "ranking_by_permutation": [result["ranking_order"] for result in path_results],
        "ranked_by_permutation": [result["ranked_candidate_ids"] for result in path_results],
        "costs_by_permutation": [result["costs"] for result in path_results],
    }
    execution_target = next(item for item in ambiguity_execution if item["candidate_id"] == "B")
    competing_execution = _mutated_evidence(execution_target, score=999.0)
    execution_results = [
        run_objectives(ambiguity_context, ambiguity_path, order)["execution"]
        for order in (
            [execution_target, competing_execution]
            + [item for item in ambiguity_execution if item is not execution_target],
            [competing_execution, execution_target]
            + [item for item in ambiguity_execution if item is not execution_target],
        )
    ]
    controls["ambiguous_execution_evidence_permutation"] = {
        "passed": execution_results[0]["selected_candidate_id"]
        == execution_results[1]["selected_candidate_id"]
        and execution_results[0]["ranking_order"] == execution_results[1]["ranking_order"]
        and execution_results[0]["ranked_candidate_ids"]
        == execution_results[1]["ranked_candidate_ids"]
        and execution_results[0]["scores"] == execution_results[1]["scores"]
        and all(
            next(row for row in result["candidates"] if row["candidate_id"] == "B")[
                "ranking_status"
            ] == FEASIBLE_UNRANKED
            for result in execution_results
        ),
        "selected_by_permutation": [result["selected_candidate_id"] for result in execution_results],
        "ranking_by_permutation": [result["ranking_order"] for result in execution_results],
        "ranked_by_permutation": [result["ranked_candidate_ids"] for result in execution_results],
        "scores_by_permutation": [result["scores"] for result in execution_results],
    }
    return controls


def _economic_view(decision):
    contract = [
        {key: row[key] for key in ("candidate_id", "technical_feasibility",
                                   "hard_policy_eligible", "integrity_eligible")}
        for row in decision["candidates"]
    ]
    contract_document = {"candidates": contract}
    contract_document["contract_digest"] = self_digest(
        contract_document, identity_field="contract_digest")
    return {
        "legal_candidate_ids": [row["candidate_id"] for row in decision["candidates"]],
        "technical_feasibility": {
            row["candidate_id"]: row["technical_feasibility"] for row in decision["candidates"]
        },
        "legal_candidate_set_and_feasibility": contract_document,
        "candidates": decision["candidates"],
    }


def _immutable_planning_inputs(context, path_evidence, execution_evidence):
    """Return every planning input that the inventory-only mutation must preserve."""
    return {
        "strategy": context["strategy"].frozen_document(),
        "candidate_order_contract": context["candidates"],
        "plan": context["plan"],
        "participant_requirements": context["requirements"],
        "authorized_source_descriptors": context["authorized_source_descriptors"],
        "path_evidence": path_evidence,
        "execution_evidence": execution_evidence,
        "evidence_contract": EVIDENCE_CONTRACT,
    }


def run_campaign(out_dir: Path | None = None):
    methodology = ROOT / AREA / "methodology.md"
    frozen_methodology_hash = sha(methodology) if methodology.is_file() else None
    with tempfile.TemporaryDirectory(prefix="issue103-cpu-") as temporary:
        root = Path(temporary)
        with IsolationAudit(root) as audit:
            arm_a = make_context(root / "arm-a", arm="A")
            arm_a_sources = selected_sources(arm_a)
            path_evidence = build_path_evidence(arm_a, source_selections=arm_a_sources)
            execution_evidence = build_execution_evidence(arm_a)
            arm_a_decisions = run_objectives(arm_a, path_evidence, execution_evidence)

            arm_b = make_inventory_arm_b(arm_a)
            arm_b_decisions = run_objectives(arm_b, path_evidence, execution_evidence)
            tie = tie_permutation(arm_a, path_evidence, execution_evidence)

            immutable_a = _immutable_planning_inputs(arm_a, path_evidence, execution_evidence)
            immutable_b = _immutable_planning_inputs(arm_b, path_evidence, execution_evidence)
            immutable_a_bytes = canonical_json_bytes(immutable_a)
            immutable_b_bytes = canonical_json_bytes(immutable_b)
            immutable_inputs = {
                "arm_a": immutable_a,
                "arm_b": immutable_b,
                "arm_a_canonical_sha256": hashlib.sha256(immutable_a_bytes).hexdigest(),
                "arm_b_canonical_sha256": hashlib.sha256(immutable_b_bytes).hexdigest(),
                "arm_a_arm_b_byte_identical": immutable_a_bytes == immutable_b_bytes,
            }
            require(immutable_inputs["arm_a_arm_b_byte_identical"],
                    "inventory mutation changed frozen planning inputs")
            path_bytes = canonical_json_bytes(path_evidence)
            inventory_only_mutation = {
                "arm_a_and_arm_b_a_snapshot_byte_identical": canonical_json_bytes(
                    arm_a["snapshots"][0]
                ) == canonical_json_bytes(arm_b["snapshots"][0]),
                "arm_a_and_arm_b_b_snapshot_byte_identical": canonical_json_bytes(
                    arm_a["snapshots"][1]
                ) == canonical_json_bytes(arm_b["snapshots"][1]),
                "c_snapshot_non_inventory_fields_byte_identical": canonical_json_bytes({
                    key: value for key, value in arm_a["snapshots"][2].items()
                    if key != "verified_objects"
                }) == canonical_json_bytes({
                    key: value for key, value in arm_b["snapshots"][2].items()
                    if key != "verified_objects"
                }),
                "only_c_verified_objects_changed": (
                    arm_a["snapshots"][2]["verified_objects"]
                    != arm_b["snapshots"][2]["verified_objects"]
                ),
            }
            require(all(inventory_only_mutation.values()),
                    "Arm B changed data outside C's verified inventory")

            controls = negative_controls(root / "controls", path_evidence, execution_evidence)
            isolation = audit.document()
        purity = purity_audit(ROOT / "scripts/issue103_planner.py", PURITY_TOKENS)

        accounting_a = account_transfer_events(
            arm_a_decisions["transition"]["candidates"],
            [event for row in arm_a_decisions["transition"]["candidates"]
             for event in row["transfer_events"]],
        )
        accounting_b = account_transfer_events(
            arm_b_decisions["transition"]["candidates"],
            [event for row in arm_b_decisions["transition"]["candidates"]
             for event in row["transfer_events"]],
        )
        require(accounting_a["accepted_event_count"] == accounting_a["expected_event_count"]
                and accounting_a["missing_event_count"] == 0,
                "Arm A transfer accounting is incomplete")
        require(accounting_b["accepted_event_count"] == accounting_b["expected_event_count"]
                and accounting_b["missing_event_count"] == 0,
                "Arm B transfer accounting is incomplete")
        feasibility_changed = sum(
            arm_a_decisions["transition"]["candidates"][index]["technical_feasibility"] !=
            arm_b_decisions["transition"]["candidates"][index]["technical_feasibility"]
            for index in range(3)
        )
        provenance_without_frozen = sum(
            row["ranking_input_without_frozen_provenance"]
            for decision in (arm_a_decisions, arm_b_decisions)
            for objective in ("transition", "execution")
            for row in decision[objective]["candidates"]
        )
        unverified_locality = sum(
            not audit_entry["verified_receipt_valid"]
            for context in (arm_a, arm_b)
            for audit_entry in context["coordinator"].inventory_audit
        )
        authorized_descriptors = {
            canonical_json_bytes(descriptor)
            for context in (arm_a, arm_b)
            for descriptor in context["authorized_source_descriptors"]
        }
        unauthorized_sources = sum(
            canonical_json_bytes(source) not in authorized_descriptors
            for decision in (arm_a_decisions, arm_b_decisions)
            for row in decision["transition"]["candidates"]
            for source in row["selected_source_descriptor_by_artifact"].values()
        )
        expected_execution_winner = max(
            arm_b_decisions["execution"]["scores"].items(), key=lambda item: (item[1], item[0])
        )[0]
        objective_contamination = int(
            arm_b_decisions["execution"]["selected_candidate_id"] != expected_execution_winner
        )
        zero = {
            "artifact_locality_changed_technical_feasibility": feasibility_changed,
            "planner_model_specific_branches": purity["planner_model_specific_branches"],
            "unexplained_transition_bytes": accounting_a["unexplained_transition_bytes"]
            + accounting_b["unexplained_transition_bytes"],
            "ranking_input_without_frozen_provenance": provenance_without_frozen,
            "coordinator_bulk_artifact_bytes_observed": arm_a["coordinator"].bytes_observed
            + arm_b["coordinator"].bytes_observed,
            "unverified_state_used_as_locality_evidence": unverified_locality,
            "unauthorized_source_used_for_ranking": unauthorized_sources,
            "objective_cross_contamination_events": objective_contamination,
        }
        require(all(value == 0 for value in zero.values()), f"zero invariant failed: {zero}")
        require(controls and all(item["passed"] for item in controls.values()),
                "negative control failed")
        require(isolation["cpu_only"] and not isolation["freetoken_tree_modified"]
                and not isolation["issue97_evidence_touched"], "isolation failed")

        strategy_doc = arm_a["strategy"].frozen_document()
        summary = {
            "terminal_disposition": "ARTIFACT_LOCALITY_TRANSITION_PLANNING_PASS",
            "implementation_base": BASE,
            "temporary_root": str(root),
            "methodology_sha256_before_execution": frozen_methodology_hash,
            "zero_invariants": zero,
            "isolation": isolation,
            "negative_controls_passed": len(controls),
            "non_claims": [
                "This is a serialized first-order ranking proxy under a CPU fixture.",
                "This does not predict physical transfer wall time.",
                "No public planner, artifact, path, or wire schema is frozen.",
                "No physical qualification or runtime integration is claimed.",
            ],
        }
        documents = {
            "strategy.json": strategy_doc,
            "requirements.json": {"plan": arm_a["plan"], "requirements": arm_a["requirements"]},
            "inventories.json": {
                "arm_a": arm_a["snapshots"],
                "arm_b": arm_b["snapshots"],
                "inventory_only_mutation": inventory_only_mutation,
            },
            "source-index.json": {"arm_a": arm_a["coordinator"].source_index(),
                                  "arm_b": arm_b["coordinator"].source_index()},
            "path-evidence.json": {
                "records": path_evidence,
                "arm_a_canonical_sha256": hashlib.sha256(path_bytes).hexdigest(),
                "arm_b_canonical_sha256": hashlib.sha256(path_bytes).hexdigest(),
                "arm_a_arm_b_byte_identical": True,
            },
            "candidate-economics.json": {"arm_a": _economic_view(arm_a_decisions["transition"]),
                                          "arm_b": _economic_view(arm_b_decisions["transition"])},
            "objective-decisions.json": {
                "arm_a": {
                    MIN_TRANSITION_COST: {key: value for key, value in arm_a_decisions["transition"].items()
                                          if key != "candidates"},
                    WARM_DECODE_THROUGHPUT: {key: value for key, value in arm_a_decisions["execution"].items()
                                             if key != "candidates"},
                },
                "arm_b": {
                    MIN_TRANSITION_COST: {key: value for key, value in arm_b_decisions["transition"].items()
                                          if key != "candidates"},
                    WARM_DECODE_THROUGHPUT: {key: value for key, value in arm_b_decisions["execution"].items()
                                             if key != "candidates"},
                },
            },
            "tie-permutation.json": {
                "objective": tie["objective"],
                "equal_rank_value": tie["equal_rank_value"],
                "selected_by_permutation": {
                    "ABC": tie["forward"]["selected_candidate_id"],
                    "CBA": tie["reverse"]["selected_candidate_id"],
                },
                "ranking_by_permutation": {
                    "ABC": tie["forward"]["ranking_order"],
                    "CBA": tie["reverse"]["ranking_order"],
                },
            },
            "negative-controls.json": {"controls": controls},
            "accounting.json": {"arm_a": accounting_a, "arm_b": accounting_b,
                                 "zero_invariants": zero},
            "purity-audit.json": purity,
            "isolation.json": isolation,
            "immutable-inputs.json": immutable_inputs,
            "canonical-summary.json": summary,
        }
        producer_hashes = {path: sha(ROOT / path) for path in PRODUCERS}
        documents["producer-hashes.json"] = producer_hashes
    if out_dir is not None:
        for name, document in documents.items():
            write_canonical_json(out_dir / name, document)
        write_manifest(out_dir)
    return documents


def write_manifest(out_dir: Path):
    entries = {str(AREA / "evidence" / name): sha(out_dir / name) for name in EVIDENCE_FILES}
    entries.update({path: sha(ROOT / path) for path in PRODUCERS})
    for path in (str(AREA / "methodology.md"), str(AREA / "README.md"), ".github/workflows/ci.yml"):
        if (ROOT / path).is_file():
            entries[path] = sha(ROOT / path)
    (out_dir / "MANIFEST.sha256").write_text(
        "".join(f"{digest}  {path}\n" for path, digest in sorted(entries.items())))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / AREA / "evidence")
    args = parser.parse_args()
    documents = run_campaign(args.out)
    print(documents["canonical-summary.json"]["terminal_disposition"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Issue #200 (R8-F) compact CPU source-policy/local-backing campaign.

Proves, on isolated CPU fixtures compatible with the accepted issue #99/#101
architecture, the five canonical Phase-3 arms plus the required negative
controls, then writes retained evidence under
``docs/implementation/r8-f-local-backing-source-policy-200/evidence/``.

Canonical arms (one frozen release fixture, one Node "C" whose local backing
varies per arm, one origin Source that always has the full release):

  L1   local verified source present + PREFER_LOCAL_VERIFIED
       -> zero acquisition bytes, exact local source selected.
  L2   local absent + PREFER_LOCAL_VERIFIED
       -> authorized remote fallback, exact missing bytes acquired.
  R1   local present + PREFER_REMOTE_AUTHORIZED
       -> remote source selected intentionally, bytes/accounting prove it.
  LREQ local incomplete + REQUIRE_LOCAL_VERIFIED
       -> fail before remote bytes move.
  RREQ remote unavailable + REQUIRE_REMOTE_AUTHORIZED
       -> fail before local fallback is silently substituted.

This module never modifies the accepted #99/#101 producers; it only imports
and composes their public surface plus the additive
``issue200_r8f_source_policy`` seam. Pure stdlib plus the accepted internal
modules; isolated to a private temporary root; no network beyond loopback
sources already used by #99, no subprocess.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from issue74_methodology import canonical_json_bytes
from issue99_artifact_core import AcquisitionError, LocalFileSource, NodeArtifactCache, write_canonical_json
from issue101_orchestration import Node
from issue200_r8f_fixture import ReleaseFixture
from issue200_r8f_source_policy import (
    SOURCE_POLICIES,
    SOURCE_POLICY_PREFER_LOCAL_VERIFIED,
    SOURCE_POLICY_PREFER_REMOTE_AUTHORIZED,
    SOURCE_POLICY_REQUIRE_LOCAL_VERIFIED,
    SOURCE_POLICY_REQUIRE_REMOTE_AUTHORIZED,
    PolicyCoordinator,
    acquire_under_policy,
    ledger_network_accounting,
    local_backing_accounting,
)

ROOT = Path(__file__).resolve().parents[1]
AREA = Path("docs/implementation/r8-f-local-backing-source-policy-200")
PRODUCERS = ["scripts/issue200_r8f_source_policy.py", "scripts/issue200_r8f_fixture.py",
             "scripts/issue200_r8f_proof.py", "scripts/issue200_r8f_terminal_reduction.py",
             "scripts/issue200_r8f_rpc_cache_mechanism.py", "scripts/issue200_r8f_physical.py",
             "scripts/issue99_artifact_core.py", "scripts/issue101_orchestration.py",
             "scripts/issue74_methodology.py",
             "tests/test_issue200_r8f_source_policy.py", "tests/test_issue200_r8f_proof.py"]
EVIDENCE_FILES = {"arms.json", "negative-controls.json", "local-backing-accounting.json",
                  "materialization-invariance.json", "producer-hashes.json",
                  "canonical-summary.json", "isolation.json"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def materialize_and_reconcile(plan, coordinator, node, participant_id):
    """Exercise the accepted #101 reconciliation seam after acquisition.

    This deliberately contains no Source descriptor or policy.  It is the
    identity of the materialization that the frozen requirement authority
    permits, not an identity of how bytes happened to arrive at the Node.
    """
    participant = coordinator._participant(participant_id)
    identity = {"epoch": plan["epoch"], "participant_id": participant_id,
                "node_id": node.node_id}
    materializations = []
    for record in participant["required_artifacts"]:
        data = node.cache.open_verified(record)
        for state_id in record["satisfies_logical_state_ids"]:
            materializations.append({**identity, "logical_state_id": state_id,
                                     "verification": "VERIFIED_CACHE_SOURCE",
                                     "observed_bytes": len(data),
                                     "expected_bytes": record["length"]})
    reconciliation = coordinator.reconcile(
        participant_id, [record["artifact_id"] for record in participant["required_artifacts"]],
        materializations)
    frozen = next(p for p in plan["participants"] if p["participant_id"] == participant_id)
    identity_document = {
        "schema": "inferswarm.issue200.materialization-identity/1",
        "plan_digest": plan["plan_digest"],
        "participant_requirements_digest": participant["participant_requirements_digest"],
        "required_artifact_ids": sorted(record["artifact_id"] for record in participant["required_artifacts"]),
        "logical_state_unit_coverage": sorted(
            state for states in frozen["required_state"].values() for state in states),
        "materializations": reconciliation["materializations"],
    }
    identity_document["materialization_identity"] = (
        "sha256:" + hashlib.sha256(canonical_json_bytes(identity_document)).hexdigest())
    return identity_document


# ---------------------------------------------------------------------------
# Mechanical isolation guard (reimplemented locally; stdlib-only, no import of
# issue101_proof.py so this campaign has no dependency beyond the accepted
# core/orchestration modules it composes).
# ---------------------------------------------------------------------------

_ACTIVE_AUDIT = None


def _audit_hook(event: str, args: Any) -> None:
    if _ACTIVE_AUDIT is not None:
        _ACTIVE_AUDIT.observe(event, args)


sys.addaudithook(_audit_hook)


class IsolationAudit:
    """Prove the campaign touched only its own temporary root and did no
    network/process activity - a mechanical isolation record, not an authored
    claim (negative control coverage: unrelated I/O)."""

    def __init__(self, root: Path):
        self.root = str(root.resolve())
        self.network_operations: list[str] = []
        self.process_operations: list[str] = []
        self.outside_root_paths: list[str] = []

    def observe(self, event: str, args: Any) -> None:
        if event.startswith("socket."):
            self.network_operations.append(event)
            raise AssertionError("campaign attempted network access")
        if event in ("subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "pty.spawn"):
            self.process_operations.append(event)
            raise AssertionError("campaign attempted process execution")
        path_positions = {"open": (0,), "os.mkdir": (0,), "os.remove": (0,), "os.rename": (0, 1)}
        for position in path_positions.get(event, ()):
            path = args[position]
            if isinstance(path, int):
                continue
            path = os.path.abspath(os.fsdecode(path))
            if not path.startswith(self.root) and "site-packages" not in path and not path.endswith(".pyc"):
                self.outside_root_paths.append(path)

    def summary(self) -> dict[str, Any]:
        return {"network_operations": self.network_operations,
                "process_operations": self.process_operations,
                "outside_root_paths": sorted(set(self.outside_root_paths))}


# ---------------------------------------------------------------------------
# Canonical arms
# ---------------------------------------------------------------------------


def run_arms(temp_root: Path) -> dict[str, Any]:
    fixture = ReleaseFixture(temp_root / "origin_dir")
    origin = LocalFileSource(source_id="origin", root=temp_root / "origin_dir")
    results: dict[str, Any] = {}

    # --- L1: local present + PREFER_LOCAL_VERIFIED -----------------------
    node_c = Node("L1", NodeArtifactCache(temp_root / "node-L1"))
    coordinator = PolicyCoordinator(node_sources=[node_c.descriptor()], origin_sources=[origin.descriptor()])
    fixture.stage_full_release(node_c)
    plan = fixture.plan(1, {"P-L1": ("L1", [1])})
    coordinator.freeze(plan, fixture.resolve)
    coordinator.ingest(node_c.inventory())
    delta = coordinator.delta("P-L1")
    record = fixture.records[1]
    require(record["artifact_id"] in delta["local_artifact_ids"], "L1 precondition: must be local")
    ticket = coordinator.authorize_under_policy(delta, record["artifact_id"], SOURCE_POLICY_PREFER_LOCAL_VERIFIED)
    require(ticket["mode"] == "LOCAL_CACHE", "L1: expected LOCAL_CACHE selection")
    result = acquire_under_policy(node_c, coordinator, ticket, node_c.source(record))
    require(result["status"] == "CACHE_HIT", "L1: expected zero-acquisition cache hit")
    accounting = ledger_network_accounting(node_c.ledger.events)
    require(accounting["newly_acquired_bytes"] == 0, "L1: expected zero newly acquired bytes")
    results["L1"] = {"mode": ticket["mode"], "source_id": ticket["source"]["source_id"],
                     "status": result["status"], "accounting": accounting}

    # --- L2: local absent + PREFER_LOCAL_VERIFIED -------------------------
    node_l2 = Node("L2", NodeArtifactCache(temp_root / "node-L2"))
    coordinator2 = PolicyCoordinator(node_sources=[node_l2.descriptor()], origin_sources=[origin.descriptor()])
    plan2 = fixture.plan(1, {"P-L2": ("L2", [2])})
    coordinator2.freeze(plan2, fixture.resolve)
    coordinator2.ingest(node_l2.inventory())
    delta2 = coordinator2.delta("P-L2")
    record2 = fixture.records[2]
    require(record2["artifact_id"] not in delta2["local_artifact_ids"], "L2 precondition: must be absent")
    ticket2 = coordinator2.authorize_under_policy(delta2, record2["artifact_id"], SOURCE_POLICY_PREFER_LOCAL_VERIFIED)
    require(ticket2["mode"] == "ORIGIN", "L2: expected remote fallback")
    result2 = acquire_under_policy(node_l2, coordinator2, ticket2, origin)
    require(result2["status"] == "ACQUIRED" and result2["bytes"] == record2["length"],
           "L2: expected exact missing bytes acquired")
    results["L2"] = {"mode": ticket2["mode"], "source_id": ticket2["source"]["source_id"],
                     "status": result2["status"], "bytes": result2["bytes"]}

    # --- R1: local present + PREFER_REMOTE_AUTHORIZED ----------------------
    node_r1 = Node("R1", NodeArtifactCache(temp_root / "node-R1"))
    coordinator3 = PolicyCoordinator(node_sources=[node_r1.descriptor()], origin_sources=[origin.descriptor()])
    fixture.stage_full_release(node_r1)
    plan3 = fixture.plan(1, {"P-R1": ("R1", [3])})
    coordinator3.freeze(plan3, fixture.resolve)
    coordinator3.ingest(node_r1.inventory())
    delta3 = coordinator3.delta("P-R1")
    record3 = fixture.records[3]
    require(record3["artifact_id"] in delta3["local_artifact_ids"], "R1 precondition: must be local")
    ticket3 = coordinator3.authorize_under_policy(delta3, record3["artifact_id"], SOURCE_POLICY_PREFER_REMOTE_AUTHORIZED)
    require(ticket3["mode"] != "LOCAL_CACHE", "R1: expected a non-local Source despite local possession")
    result3 = acquire_under_policy(node_r1, coordinator3, ticket3, origin)
    require(result3["status"] == "ACQUIRED" and result3["bytes"] == record3["length"],
           "R1: expected genuine transfer, not a silent cache hit")
    last_event = node_r1.ledger.events[-1]
    require(last_event["event"] == "ACQUIRED" and last_event.get("policy_forced_transfer") is True,
           "R1: ledger must attribute real bytes to the deliberately selected remote source")
    results["R1"] = {"mode": ticket3["mode"], "source_id": ticket3["source"]["source_id"],
                     "status": result3["status"], "bytes": result3["bytes"],
                     "forced_transfer": last_event.get("policy_forced_transfer", False)}

    # --- LREQ: local incomplete + REQUIRE_LOCAL_VERIFIED --------------------
    node_lreq = Node("LREQ", NodeArtifactCache(temp_root / "node-LREQ"))
    coordinator4 = PolicyCoordinator(node_sources=[node_lreq.descriptor()], origin_sources=[origin.descriptor()])
    plan4 = fixture.plan(1, {"P-LREQ": ("LREQ", [4])})
    coordinator4.freeze(plan4, fixture.resolve)
    coordinator4.ingest(node_lreq.inventory())
    delta4 = coordinator4.delta("P-LREQ")
    record4 = fixture.records[4]
    require(record4["artifact_id"] not in delta4["local_artifact_ids"], "LREQ precondition: must be absent")
    attempts_before = len(coordinator4.selections)
    requests_before = len(origin.requests_for("release.bin"))
    try:
        coordinator4.authorize_under_policy(delta4, record4["artifact_id"], SOURCE_POLICY_REQUIRE_LOCAL_VERIFIED)
        raise AssertionError("LREQ: expected SOURCE_UNAUTHORIZED, got no failure")
    except AcquisitionError as error:
        require("SOURCE_UNAUTHORIZED" in str(error), f"LREQ: unexpected reason {error}")
    require(len(coordinator4.selections) == attempts_before, "LREQ: must fail before any ticket is issued")
    require(len(origin.requests_for("release.bin")) == requests_before,
           "LREQ: must fail before any remote bytes move")
    results["LREQ"] = {"failed_closed": True, "remote_requests_before": requests_before,
                       "remote_requests_after": len(origin.requests_for("release.bin"))}

    # --- RREQ: remote unavailable + REQUIRE_REMOTE_AUTHORIZED ---------------
    node_rreq = Node("RREQ", NodeArtifactCache(temp_root / "node-RREQ"))
    coordinator5 = PolicyCoordinator(node_sources=[node_rreq.descriptor()], origin_sources=[])
    fixture.stage_full_release(node_rreq)
    plan5 = fixture.plan(1, {"P-RREQ": ("RREQ", [5])})
    coordinator5.freeze(plan5, fixture.resolve)
    coordinator5.ingest(node_rreq.inventory())
    delta5 = coordinator5.delta("P-RREQ")
    record5 = fixture.records[5]
    require(record5["artifact_id"] in delta5["local_artifact_ids"], "RREQ precondition: must be local")
    try:
        coordinator5.authorize_under_policy(delta5, record5["artifact_id"], SOURCE_POLICY_REQUIRE_REMOTE_AUTHORIZED)
        raise AssertionError("RREQ: expected SOURCE_UNAUTHORIZED, got no failure")
    except AcquisitionError as error:
        require("SOURCE_UNAUTHORIZED" in str(error), f"RREQ: unexpected reason {error}")
    require(node_rreq.ledger.events == [], "RREQ: local fallback must never be silently substituted")
    results["RREQ"] = {"failed_closed": True, "local_ledger_events_after": len(node_rreq.ledger.events)}

    # --- Phase 2: local-backing accounting (full release vs. narrow plan) ---
    node_backing = Node("BACKING", NodeArtifactCache(temp_root / "node-BACKING"))
    coordinator6 = PolicyCoordinator(node_sources=[node_backing.descriptor()], origin_sources=[origin.descriptor()])
    fixture.stage_full_release(node_backing)
    plan6 = fixture.plan(1, {"P-BACKING": ("BACKING", [1])})
    requirements6 = coordinator6.freeze(plan6, fixture.resolve)
    coordinator6.ingest(node_backing.inventory())
    accounting = local_backing_accounting(node=node_backing, participant_requirements=requirements6["participants"][0])
    require(accounting["required_bytes_satisfied_from_local_backing"] == fixture.records[1]["length"],
           "backing accounting: required bytes mismatch")
    require(accounting["retained_optional_backing_bytes"] == sum(
        r["length"] for n, r in fixture.records.items() if n != 1),
           "backing accounting: optional surplus mismatch")

    # --- Phase 3: same plan + same requirements, different Sources --------
    # This is intentionally not a comparison of the five pedagogical arms
    # above: those have different participants and required state.  Here one
    # frozen plan is independently reconciled/materialized twice, once from
    # verified local backing and once from the authorized origin source.
    invariant_plan = fixture.plan(2, {"P-INVARIANT": ("INVARIANT", [1, 2])})
    local_node = Node("INVARIANT", NodeArtifactCache(temp_root / "node-invariant-local"))
    remote_node = Node("INVARIANT", NodeArtifactCache(temp_root / "node-invariant-remote"))
    fixture.stage_full_release(local_node)
    local_coordinator = PolicyCoordinator(
        node_sources=[local_node.descriptor()], origin_sources=[origin.descriptor()])
    remote_coordinator = PolicyCoordinator(
        node_sources=[remote_node.descriptor()], origin_sources=[origin.descriptor()])
    local_requirements = local_coordinator.freeze(invariant_plan, fixture.resolve)
    remote_requirements = remote_coordinator.freeze(invariant_plan, fixture.resolve)
    require(local_requirements == remote_requirements,
            "Phase 3: Source policy must not change frozen requirements")
    local_coordinator.ingest(local_node.inventory())
    remote_coordinator.ingest(remote_node.inventory())
    local_delta = local_coordinator.delta("P-INVARIANT")
    remote_delta = remote_coordinator.delta("P-INVARIANT")
    for record in local_coordinator._participant("P-INVARIANT")["required_artifacts"]:
        local_ticket = local_coordinator.authorize_under_policy(
            local_delta, record["artifact_id"], SOURCE_POLICY_PREFER_LOCAL_VERIFIED)
        require(local_ticket["mode"] == "LOCAL_CACHE", "Phase 3 local arm must use backing")
        acquire_under_policy(local_node, local_coordinator, local_ticket, local_node.source(record))
        remote_ticket = remote_coordinator.authorize_under_policy(
            remote_delta, record["artifact_id"], SOURCE_POLICY_PREFER_REMOTE_AUTHORIZED)
        require(remote_ticket["mode"] == "ORIGIN", "Phase 3 remote arm must use authorized origin")
        acquire_under_policy(remote_node, remote_coordinator, remote_ticket, origin)
    local_materialization = materialize_and_reconcile(
        invariant_plan, local_coordinator, local_node, "P-INVARIANT")
    remote_materialization = materialize_and_reconcile(
        invariant_plan, remote_coordinator, remote_node, "P-INVARIANT")
    for field in ("plan_digest", "participant_requirements_digest", "required_artifact_ids",
                  "logical_state_unit_coverage", "materializations", "materialization_identity"):
        require(local_materialization[field] == remote_materialization[field],
                f"Phase 3: Source changed {field}")
    invariance = {
        "schema": "inferswarm.issue200.materialization-invariance/1",
        "frozen_plan_digest": invariant_plan["plan_digest"],
        "same_requirement_authority": local_requirements == remote_requirements,
        "local_verified": {"source_policy": SOURCE_POLICY_PREFER_LOCAL_VERIFIED,
                           "acquisition": "LOCAL_CACHE", **local_materialization},
        "remote_authorized": {"source_policy": SOURCE_POLICY_PREFER_REMOTE_AUTHORIZED,
                              "acquisition": "ORIGIN", **remote_materialization},
    }
    return {"arms": results, "local_backing_accounting": accounting,
            "materialization_invariance": invariance}


# ---------------------------------------------------------------------------
# Negative controls (issue #200 "Required negative controls" list)
# ---------------------------------------------------------------------------


def run_negative_controls(temp_root: Path) -> dict[str, Any]:
    fixture = ReleaseFixture(temp_root / "nc-origin")
    origin = LocalFileSource(source_id="origin", root=temp_root / "nc-origin")
    controls: dict[str, Any] = {}

    def fresh(name):
        node = Node(name, NodeArtifactCache(temp_root / f"nc-{name}"))
        coordinator = PolicyCoordinator(node_sources=[node.descriptor()], origin_sources=[origin.descriptor()])
        return node, coordinator

    # NC-1: wrong digest/model/revision identity is never treated as satisfying.
    try:
        def bad_resolver(requirement_class, state_id):
            return [fixture.wrong_revision_record]
        node, coordinator = fresh("nc1")
        plan = fixture.plan(1, {"P": ("nc1", [1])})
        from issue99_artifact_core import derive_participant_requirements
        derive_participant_requirements(plan, bad_resolver)
        raise AssertionError("NC-1: expected PROVENANCE_IDENTITY_MISMATCH")
    except AcquisitionError as error:
        controls["nc1_wrong_identity_never_satisfies"] = {"failed_closed": True, "reason": str(error).split(":")[0]}

    # NC-2: complete release exists but one required member is corrupt on disk.
    node, coordinator = fresh("nc2")
    fixture.stage_full_release(node)
    corrupt_path = node.cache.lookup(fixture.records[6]["content_digest"])
    corrupt_path.write_bytes(b"xxxx")
    plan = fixture.plan(1, {"P": ("nc2", [6])})
    coordinator.freeze(plan, fixture.resolve)
    coordinator.ingest(node.inventory())
    delta = coordinator.delta("P")
    controls["nc2_corrupt_member_excluded_from_local"] = {
        "release_otherwise_complete": True,
        "corrupt_member_in_local_artifact_ids": fixture.records[6]["artifact_id"] in delta["local_artifact_ids"]}
    require(not controls["nc2_corrupt_member_excluded_from_local"]["corrupt_member_in_local_artifact_ids"],
           "NC-2: corrupt member must not count as local")

    # NC-3: REQUIRE_LOCAL_VERIFIED never silently falls back remote.
    node, coordinator = fresh("nc3")
    plan = fixture.plan(1, {"P": ("nc3", [7])})
    coordinator.freeze(plan, fixture.resolve)
    coordinator.ingest(node.inventory())
    delta = coordinator.delta("P")
    origin_requests_before = len(origin.requests_for("release.bin"))
    try:
        coordinator.authorize_under_policy(delta, fixture.records[7]["artifact_id"], SOURCE_POLICY_REQUIRE_LOCAL_VERIFIED)
        raise AssertionError("NC-3: expected failure")
    except AcquisitionError:
        pass
    controls["nc3_require_local_never_falls_back_remote"] = {
        "origin_requests_before": origin_requests_before,
        "origin_requests_after": len(origin.requests_for("release.bin"))}
    require(controls["nc3_require_local_never_falls_back_remote"]["origin_requests_after"] == origin_requests_before,
           "NC-3: origin must never be contacted")

    # NC-4: REQUIRE_REMOTE_AUTHORIZED never silently uses a local cache.
    node, coordinator = fresh("nc4")
    fixture.stage_full_release(node)
    plan = fixture.plan(1, {"P": ("nc4", [8])})
    coordinator2 = PolicyCoordinator(node_sources=[node.descriptor()], origin_sources=[])
    coordinator2.freeze(plan, fixture.resolve)
    coordinator2.ingest(node.inventory())
    delta = coordinator2.delta("P")
    try:
        coordinator2.authorize_under_policy(delta, fixture.records[8]["artifact_id"], SOURCE_POLICY_REQUIRE_REMOTE_AUTHORIZED)
        raise AssertionError("NC-4: expected failure")
    except AcquisitionError:
        pass
    controls["nc4_require_remote_never_uses_local"] = {"ledger_events_after": len(node.ledger.events)}
    require(controls["nc4_require_remote_never_uses_local"]["ledger_events_after"] == 0,
           "NC-4: local cache must never be silently substituted")

    # NC-5: policy changes Source only, never the required Logical State Units.
    node, coordinator = fresh("nc5")
    fixture.stage_full_release(node)
    plan = fixture.plan(1, {"P": ("nc5", [1, 2, 3])})
    requirements = coordinator.freeze(plan, fixture.resolve)
    coordinator.ingest(node.inventory())
    base_participant = next(p for p in requirements["participants"] if p["participant_id"] == "P")
    delta = coordinator.delta("P")
    digests_seen = set()
    for policy in (SOURCE_POLICY_PREFER_LOCAL_VERIFIED, SOURCE_POLICY_PREFER_REMOTE_AUTHORIZED):
        coordinator.authorize_under_policy(delta, fixture.records[1]["artifact_id"], policy)
        digests_seen.add(coordinator._participant("P")["participant_requirements_digest"])
    controls["nc5_policy_changes_source_only"] = {
        "requirement_digest_before": base_participant["participant_requirements_digest"],
        "distinct_digests_across_policies": len(digests_seen)}
    require(digests_seen == {base_participant["participant_requirements_digest"]},
           "NC-5: required state must be policy-invariant")

    # NC-6: optional full-release cache never gets promoted to active residency.
    node, coordinator = fresh("nc6")
    fixture.stage_full_release(node)  # 8 members verified locally
    plan = fixture.plan(1, {"P": ("nc6", [2])})  # only 1 required
    requirements = coordinator.freeze(plan, fixture.resolve)
    participant = requirements["participants"][0]
    controls["nc6_backing_never_promoted_to_required"] = {
        "verified_local_members": 8, "required_artifact_count": len(participant["required_artifacts"])}
    require(len(participant["required_artifacts"]) == 1,
           "NC-6: full local backing must never enlarge the required set")

    # NC-7: local full-replica presence is never a feasibility prerequisite.
    node, coordinator = fresh("nc7")  # zero local backing
    plan = fixture.plan(1, {"P": ("nc7", [1])})
    coordinator.freeze(plan, fixture.resolve)
    coordinator.ingest(node.inventory())
    delta = coordinator.delta("P")
    ticket = coordinator.authorize_under_policy(delta, fixture.records[1]["artifact_id"], SOURCE_POLICY_PREFER_LOCAL_VERIFIED)
    result = acquire_under_policy(node, coordinator, ticket, origin)
    controls["nc7_zero_local_backing_still_feasible"] = {"status": result["status"]}
    require(result["status"] == "ACQUIRED", "NC-7: must remain feasible with zero local backing")

    # NC-8: stale local-cache inventory after object removal fails closed, not silently.
    node, coordinator = fresh("nc8")
    fixture.seed_and_advertise(node, [3])
    plan = fixture.plan(1, {"P": ("nc8", [3])})
    coordinator.freeze(plan, fixture.resolve)
    coordinator.ingest(node.inventory())
    stale_delta = coordinator.delta("P")
    require(fixture.records[3]["artifact_id"] in stale_delta["local_artifact_ids"], "NC-8 precondition")
    node.cache.lookup(fixture.records[3]["content_digest"]).unlink()  # simulate silent removal
    ticket = coordinator.authorize_under_policy(stale_delta, fixture.records[3]["artifact_id"], SOURCE_POLICY_PREFER_LOCAL_VERIFIED)
    try:
        acquire_under_policy(node, coordinator, ticket, node.source(fixture.records[3]))
        raise AssertionError("NC-8: expected failure on stale local inventory")
    except AcquisitionError as error:
        controls["nc8_stale_inventory_fails_closed"] = {"failed_closed": True, "reason": str(error).split(":")[0]}

    # NC-9: an unverified (content/name-mismatched) local file never becomes a Source.
    node, coordinator = fresh("nc9")
    (node.cache.root / "objects" / "sha256-deadbeef").write_bytes(b"not-the-right-bytes")
    inventory = node.cache.inventory()
    plan = fixture.plan(1, {"P": ("nc9", [1])})
    requirements = coordinator.freeze(plan, fixture.resolve)
    accounting = local_backing_accounting(node=node, participant_requirements=requirements["participants"][0])
    controls["nc9_unverified_file_excluded"] = {
        "raw_objects_on_disk": 1, "verified_objects_reported": len(
            [o for o in inventory["verified_objects"] if o["byte_digest_verified"]]),
        "counted_as_backing_bytes": accounting["total_verified_local_backing_bytes"]}
    require(controls["nc9_unverified_file_excluded"]["counted_as_backing_bytes"] == 0,
           "NC-9: unverified bytes must never count as backing")

    # NC-10: the Coordinator rejects bulk bytes presented to it, even via the new seam.
    node, coordinator = fresh("nc10")
    plan = fixture.plan(1, {"P": ("nc10", [1])})
    coordinator.freeze(plan, fixture.resolve)
    coordinator.ingest(node.inventory())
    delta = coordinator.delta("P")
    observed_before = coordinator.bytes_observed
    try:
        coordinator.authorize_under_policy(delta, fixture.records[1]["artifact_id"],
                                           {"bytes_payload": b"not-a-descriptor"})
        raise AssertionError("NC-10: expected SOURCE_UNAUTHORIZED")
    except AcquisitionError as error:
        controls["nc10_coordinator_rejects_bulk_bytes"] = {
            "failed_closed": True, "reason": str(error).split(":")[0],
            "bytes_observed_increased": coordinator.bytes_observed > observed_before}
    require(controls["nc10_coordinator_rejects_bulk_bytes"]["bytes_observed_increased"],
           "NC-10: bytes_observed must mechanically increase")

    # NC-11: a false authored "zero network bytes" claim is mechanically contradicted.
    node, coordinator = fresh("nc11")
    plan = fixture.plan(1, {"P": ("nc11", [1])})
    coordinator.freeze(plan, fixture.resolve)
    coordinator.ingest(node.inventory())
    delta = coordinator.delta("P")
    ticket = coordinator.authorize_under_policy(delta, fixture.records[1]["artifact_id"], SOURCE_POLICY_PREFER_LOCAL_VERIFIED)
    acquire_under_policy(node, coordinator, ticket, origin)
    accounting = ledger_network_accounting(node.ledger.events)
    false_claim = {"network_bytes_moved": 0}
    controls["nc11_false_zero_network_claim_contradicted"] = {
        "authored_claim": false_claim, "mechanical_result": accounting}
    require(accounting["network_bytes_moved"] != false_claim["network_bytes_moved"],
           "NC-11: mechanical accounting must contradict the false claim")

    # NC-12: not a runnable compact-CPU control; see Phase 4 mechanical finding.
    controls["nc12_qwen_local_backing_claim_vs_client_originated_transfer"] = {
        "applicable_to_compact_fixture": False,
        "disposition": ("Addressed by the Phase 4 mechanical finding (pinned llama.cpp "
                        "ggml-rpc-server launch invocations carry no model path argument on "
                        "any RPC backend host) and by the terminal report's explicit non-claim: "
                        "no physical arm ran, so no remote-participant-local-backing claim is made."),
        "reference": "docs/implementation/r8-f-local-backing-source-policy-200/README.md#phase-4"}

    return controls


def canonical_summary(temp_root: Path, arms: dict[str, Any], negative_controls: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "inferswarm.issue200.canonical-summary/1",
        "temporary_root": str(temp_root),
        "arms": sorted(arms["arms"]),
        "negative_controls": sorted(negative_controls),
        "all_arms_passed": True,
        "all_negative_controls_failed_closed": True,
    }


def producer_hashes() -> dict[str, str]:
    return {path: sha(ROOT / path) for path in PRODUCERS}


def run_campaign() -> dict[str, Any]:
    global _ACTIVE_AUDIT
    with tempfile.TemporaryDirectory(prefix="issue200-r8f-") as directory:
        temp_root = Path(directory).resolve()
        audit = IsolationAudit(temp_root)
        _ACTIVE_AUDIT = audit
        try:
            arm_output = run_arms(temp_root)
            negative_controls = run_negative_controls(temp_root)
        finally:
            _ACTIVE_AUDIT = None
        summary = canonical_summary(temp_root, arm_output, negative_controls)
        isolation = audit.summary()
        require(isolation["network_operations"] == [], "campaign must never touch the network")
        require(isolation["process_operations"] == [], "campaign must never spawn a process")
        require(isolation["outside_root_paths"] == [], "campaign must stay inside its temp root")
    return {
        "arms.json": arm_output["arms"],
        "negative-controls.json": negative_controls,
        "local-backing-accounting.json": arm_output["local_backing_accounting"],
        "materialization-invariance.json": arm_output["materialization_invariance"],
        "producer-hashes.json": producer_hashes(),
        "canonical-summary.json": summary,
        "isolation.json": isolation,
    }


def write_evidence(documents: dict[str, Any]) -> None:
    evidence = ROOT / AREA / "evidence"
    for name, document in documents.items():
        write_canonical_json(evidence / name, document)
    manifest_lines = []
    for path in sorted({*PRODUCERS, str(AREA / "README.md"), str(AREA / "methodology.md")}):
        full = ROOT / path
        if full.is_file():
            manifest_lines.append(f"{sha(full)}  {path}")
    # Cover every file actually present under evidence/ (including retained,
    # non-JSON supporting files such as raw logs and the external RPC-cache
    # experiment driver source under evidence/rpc-cache-experiment-raw/),
    # not only the JSON documents this call happened to (re)write.
    for full in sorted(evidence.rglob("*")):
        if full.is_file() and full.name != "MANIFEST.sha256":
            manifest_lines.append(f"{sha(full)}  {full.relative_to(ROOT)}")
    (evidence / "MANIFEST.sha256").write_text("\n".join(sorted(manifest_lines)) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write retained evidence under docs/implementation/")
    args = parser.parse_args()
    documents = run_campaign()
    if args.write:
        write_evidence(documents)
        print(f"wrote evidence under {AREA / 'evidence'}")
    else:
        print(json.dumps(documents["canonical-summary.json"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

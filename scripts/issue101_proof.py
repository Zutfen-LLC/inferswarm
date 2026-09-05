#!/usr/bin/env python3
"""Produce the isolated issue #101 CPU orchestration evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from issue74_methodology import canonical_json_bytes
from issue99_artifact_core import (
    AcquisitionError, LocalFileSource, NodeArtifactCache, self_digest, write_canonical_json,
)
from issue101_fixture import Fixture, execute
from issue101_orchestration import Coordinator, Node

ROOT = Path(__file__).resolve().parents[1]
AREA = Path("docs/implementation/plan-driven-artifact-orchestration-101")
BASE = "53fb8f4c7ba3108a21f983712e5cbdb747a26600"
PRODUCERS = ["scripts/issue101_orchestration.py", "scripts/issue101_fixture.py",
             "scripts/issue101_proof.py", "scripts/issue99_artifact_core.py",
             "scripts/issue74_methodology.py", "tests/test_issue101_orchestration.py",
             "tests/test_issue101_proof.py"]
NEGATIVE_REASONS = {
    "stale_inventory_advertisement": "UNVERIFIED_SOURCE_READ_REFUSED",
    "same_source_identity_drifted_descriptor": "SOURCE_UNAUTHORIZED",
    "corrupt_advertised_peer_object": "INTEGRITY_DIGEST_MISMATCH",
    "partial_state_offered_as_source": "UNVERIFIED_OBJECT_PUBLICATION_REFUSED",
    "unauthorized_fallback": "SOURCE_UNAUTHORIZED",
    "stale_plan_authorization": "RECONCILIATION_MISMATCH",
    "unrequired_artifact_injection": "UNDECLARED_REQUIREMENT_ARTIFACT",
    "coordinator_bulk_byte_injection": "SOURCE_UNAUTHORIZED",
    "cache_integrity_drift_after_inventory": "CACHE_OBJECT_TAMPERED",
    "replacement_plan_stale_delta": "RECONCILIATION_MISMATCH",
}
EVIDENCE_FILES = {"fixture.json", "epochs.json", "inventories.json", "source-index.json",
                  "authorizations.json", "acquisition-ledger.json", "peer-reuse.json",
                  "negative-controls.json", "isolation.json", "canonical-summary.json",
                  "producer-hashes.json"}


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


_ACTIVE_AUDIT = None


def _audit_hook(event, args):
    if _ACTIVE_AUDIT is not None:
        _ACTIVE_AUDIT.observe(event, args)


sys.addaudithook(_audit_hook)


class IsolationAudit:
    """Constrain campaign file operations and reject network or process activity."""

    def __init__(self, root):
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
        path_positions = {"open": (0,), "os.mkdir": (0,), "os.remove": (0,),
                          "os.rmdir": (0,), "os.rename": (0, 1), "os.listdir": (0,),
                          "os.scandir": (0,)}
        for position in path_positions.get(event, ()):
            path = args[position]
            if isinstance(path, int):
                continue
            path = os.path.abspath(os.fsdecode(path))
            require(path == self.root or path.startswith(self.root + os.sep),
                    f"campaign file operation outside isolated root: {event} {path}")
            self.file_operations.append({"event": event, "path": os.path.relpath(path, self.root)})

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
        return {"cpu_only": not self.network_operations and not self.process_operations,
                "physical_hosts_touched": self.network_operations,
                "freetoken_tree_modified": any("freetoken" in path for path in paths),
                "issue97_evidence_directories_touched": [p for p in paths if "issue97" in p],
                "network_operations": self.network_operations,
                "process_operations": self.process_operations,
                "file_operations": self.file_operations,
                "all_file_operations_confined_to_temporary_root": True}


class MeteredSource:
    """Record actual data-plane reads, including failed verification inputs."""

    def __init__(self, source, record, reads, *, corrupt=False):
        self.source = source
        self.source_id = source.source_id
        self.record = record
        self.reads = reads
        self.corrupt = corrupt

    def descriptor(self):
        return self.source.descriptor()

    def read(self, origin, offset, length):
        data = self.source.read(origin, offset, length)
        if self.corrupt:
            data = bytes([data[0] ^ 255]) + data[1:]
        self.reads.append({"artifact_id": self.record["artifact_id"],
                           "source": self.descriptor(), "offset": offset, "bytes": len(data)})
        return data


class Campaign:
    def __init__(self, root):
        self.fixture = Fixture(root / "origin")
        self.nodes = {name: Node(name, NodeArtifactCache(root / name)) for name in "ABC"}
        self.fixture.seed(self.nodes["A"], [1, 2])
        self.fixture.seed(self.nodes["B"], [2, 3])
        self.origin = LocalFileSource(source_id="origin", root=self.fixture.root)
        self.coordinator = Coordinator(node_sources=[n.descriptor() for n in self.nodes.values()],
                                       origin_sources=[self.origin.descriptor()])
        self.reads: list[dict[str, Any]] = []
        self.inventories: list[dict[str, Any]] = []
        self.indexes: list[dict[str, Any]] = []
        self.realizations: list[dict[str, Any]] = []
        self.plans: list[dict[str, Any]] = []
        self.requirements: list[dict[str, Any]] = []
        self.transfers: list[dict[str, Any]] = []
        self.report("initial")

    def report(self, step):
        snapshots = [node.inventory() for node in self.nodes.values()]
        for snapshot in snapshots:
            self.coordinator.ingest(snapshot)
        self.inventories.append({"step": step, "snapshots": snapshots})
        self.indexes.append({"step": step, "index": self.coordinator.source_index()})

    def freeze(self, epoch, assignments):
        plan = self.fixture.plan(epoch, assignments)
        requirements = self.coordinator.freeze(plan, self.fixture.resolve)
        self.plans.append(plan)
        self.requirements.append(requirements)
        return plan, requirements

    def record(self, artifact_id):
        return next(r for r in self.fixture.records.values() if r["artifact_id"] == artifact_id)

    def source(self, ticket, *, corrupt=False):
        record = self.record(ticket["artifact_id"])
        source_id = ticket["source"]["source_id"]
        source = self.origin if source_id == "origin" else self.nodes[source_id].source(record)
        return MeteredSource(source, record, self.reads, corrupt=corrupt)

    def realize(self, node_id):
        node = self.nodes[node_id]
        delta = self.coordinator.delta(node_id)
        before = node.inventory()
        ledger_start = len(node.ledger.events)
        publication_start = len(node.publications)
        for artifact_id in delta["required_artifact_ids"]:
            ticket = self.coordinator.authorize(delta, artifact_id)
            read_start = len(self.reads)
            result = node.acquire(self.coordinator, ticket, self.source(ticket))
            self.transfers.append({"epoch": self.plans[-1]["epoch"], "node_id": node_id,
                                   "ticket": ticket, "result": result,
                                   "reads": deepcopy(self.reads[read_start:])})
        participant = next(p for p in self.requirements[-1]["participants"] if p["node_id"] == node_id)
        execution = execute(self.plans[-1], participant, node, self.coordinator)
        require(execution["matches_reference"], "execution differs from independent reference")
        events = [{k: v for k, v in e.items() if k != "wall_time_seconds"}
                  for e in node.ledger.events[ledger_start:]]
        self.realizations.append({"epoch": self.plans[-1]["epoch"], "node_id": node_id,
                                  "delta": delta, "inventory_before": before,
                                  "inventory_after": node.inventory(), "ledger": events,
                                  "new_publications": deepcopy(node.publications[publication_start:]),
                                  "execution": execution})
        self.report(f"epoch-{self.plans[-1]['epoch']}-after-{node_id}")


def expect_failure(caller, expected):
    try:
        caller()
    except AcquisitionError as error:
        reason = str(error).split(":")[0]
        require(reason == expected, f"expected {expected}, got {reason}")
        return {"reason": reason, "failed_closed": True}
    raise AssertionError(f"negative control did not fail: {expected}")


def cached_path(node, record):
    path = node.cache.lookup(record["content_digest"])
    if path is None:
        raise AssertionError("negative control requires a published cache object")
    return path


def negative_control(name, root):
    campaign = Campaign(root)
    campaign.freeze(1, {"C": [1, 3, 4]})
    c = campaign.coordinator
    node = campaign.nodes["C"]
    record = campaign.fixture.records[1]
    delta = c.delta("C")
    ticket = c.authorize(delta, record["artifact_id"])
    expected = NEGATIVE_REASONS[name]
    extra = {}
    if name == "stale_inventory_advertisement":
        cached_path(campaign.nodes["A"], record).unlink()
        result = expect_failure(lambda: node.acquire(c, ticket, campaign.source(ticket)), expected)
        require(not node.cache.has_verified(record), "stale advertisement became trusted")
        c.reject_source(ticket, result["reason"])
        fresh = c.authorize(delta, record["artifact_id"])
        require(fresh["source"]["source_id"] == "origin", "fallback was not origin")
        extra["fresh_authorization"] = fresh
        extra["fallback_result"] = node.acquire(c, fresh, campaign.source(fresh))
    elif name == "same_source_identity_drifted_descriptor":
        source = LocalFileSource(source_id="A", root=campaign.fixture.root)
        result = expect_failure(lambda: node.acquire(c, ticket, source), expected)
        require(not source.access_log, "drifted source read")
    elif name == "corrupt_advertised_peer_object":
        result = expect_failure(lambda: node.acquire(c, ticket, campaign.source(ticket, corrupt=True)), expected)
        require(not node.cache.has_verified(record), "corrupt bytes published")
        require(not node.inventory()["entries"], "corrupt bytes advertised")
        cached_path(campaign.nodes["A"], record).write_bytes(b"xxxx")
        extra["corrupt_stored_peer"] = expect_failure(
            lambda: node.acquire(c, ticket, campaign.source(ticket)), "CACHE_OBJECT_TAMPERED")
        extra["corrupt_peer_readvertisement"] = expect_failure(
            campaign.nodes["A"].inventory, "CACHE_OBJECT_TAMPERED")
    elif name == "partial_state_offered_as_source":
        node.cache.begin_partial(record)
        node.cache.append_partial(record, b"\x01\x00")
        result = expect_failure(lambda: node.publish(record), expected)
        forged = dict(node.inventory())
        forged["entries"] = [{"artifact_id": record["artifact_id"], "record": record}]
        extra["coordinator_rejection"] = expect_failure(lambda: c.ingest(forged), expected)
        require(not any(e["node_id"] == "C" for e in c.source_index().get(record["artifact_id"], [])),
                "partial entered source index")
    elif name == "unauthorized_fallback":
        cached_path(campaign.nodes["A"], record).unlink()
        extra["selected_source_failure"] = expect_failure(
            lambda: node.acquire(c, ticket, campaign.source(ticket)), "UNVERIFIED_SOURCE_READ_REFUSED")
        result = expect_failure(lambda: node.acquire(c, ticket, campaign.origin), expected)
        require(not campaign.origin.access_log, "unauthorized fallback read")
    elif name == "stale_plan_authorization":
        campaign.freeze(2, {"C": [1, 4, 5]})
        result = expect_failure(lambda: node.acquire(c, ticket, campaign.source(ticket)), expected)
    elif name == "unrequired_artifact_injection":
        result = expect_failure(lambda: c.authorize(delta, campaign.fixture.records[6]["artifact_id"]), expected)
    elif name == "coordinator_bulk_byte_injection":
        entry_points = {}
        for payload in (b"artifact", bytearray(b"artifact")):
            calls = {
                "constructor": lambda: Coordinator(node_sources=[payload], origin_sources=[]),
                "freeze": lambda: c.freeze({"payload": payload}, campaign.fixture.resolve),
                "resolver": lambda: c.freeze(campaign.plans[0], lambda *_: [payload]),
                "ingest": lambda: c.ingest({"payload": payload}),
                "delta": lambda: c.delta(payload),
                "authorize": lambda: c.authorize(delta, payload),
                "validate_attempt": lambda: c.validate_attempt(ticket, "C", {"payload": payload}),
                "reject_source": lambda: c.reject_source(ticket, payload),
                "reconcile": lambda: c.reconcile("C", [payload], []),
            }
            for entry, caller in calls.items():
                entry_points[f"{type(payload).__name__}:{entry}"] = expect_failure(caller, expected)
        result = {"reason": expected, "failed_closed": all(r["failed_closed"] for r in entry_points.values())}
        extra["entry_points"] = entry_points
    elif name == "cache_integrity_drift_after_inventory":
        campaign.fixture.seed(node, [1])
        campaign.report("verified-local-before-drift")
        local = c.authorize(c.delta("C"), record["artifact_id"])
        cached_path(node, record).write_bytes(b"xxxx")
        result = expect_failure(lambda: node.acquire(c, local, campaign.source(local)), expected)
        require(not any(e["event"] == "CACHE_HIT" for e in node.ledger.events), "corrupt local hit counted")
    elif name == "replacement_plan_stale_delta":
        campaign.freeze(2, {"C": [1, 4, 5]})
        changed = c.delta("C")
        changed["missing_artifact_ids"] = []
        changed["delta_digest"] = self_digest(changed, identity_field="delta_digest")
        result = expect_failure(lambda: c.authorize(changed, record["artifact_id"]), expected)
        requirement = c.delta("C")
        requirement["participant_requirements_digest"] = "sha256:" + "0" * 64
        requirement["delta_digest"] = self_digest(requirement, identity_field="delta_digest")
        extra["changed_requirement"] = expect_failure(lambda: c.authorize(requirement, record["artifact_id"]), expected)
    else:
        raise AssertionError(name)
    unverified = sum(not p["verified_local_object_available"] for p in node.publications)
    if name not in ("stale_inventory_advertisement", "corrupt_advertised_peer_object"):
        require(not campaign.reads, f"negative control moved bytes: {name}")
    return {**result, **extra, "authorizations": c.selections,
            "unverified_publications": unverified,
            "source_reads": campaign.reads, "data_plane_bytes": sum(r["bytes"] for r in campaign.reads),
            "local_verified_cache_hit_bytes": sum(e["bytes"] for e in node.ledger.events if e["event"] == "CACHE_HIT"),
            "node_failures": node.failures, "source_rejections": c.rejections,
            "coordinator_rejected_payload_bytes": c.bytes_observed}


def accounting(campaign):
    transfers = campaign.transfers
    actual = [read for transfer in transfers for read in transfer["reads"]]
    by_source: dict[str, dict[str, Any]] = {}
    for read in actual:
        key = json.dumps(read["source"], sort_keys=True)
        entry = by_source.setdefault(key, {"source": read["source"], "bytes": 0})
        entry["bytes"] += read["bytes"]
    unrequired = sum(read["bytes"] for transfer in transfers for read in transfer["reads"]
                     if read["artifact_id"] not in next(
                         [record["artifact_id"] for record in participant["required_artifacts"]]
                         for plan, requirements in zip(campaign.plans, campaign.requirements)
                         if plan["epoch"] == transfer["epoch"]
                         for participant in requirements["participants"]
                         if participant["node_id"] == transfer["node_id"]))
    reacquired = sum(read["bytes"] for transfer in transfers if transfer["epoch"] == 2
                     for read in transfer["reads"] if read["artifact_id"] in next(
                         [entry["artifact_id"] for entry in r["inventory_before"]["entries"]]
                         for r in campaign.realizations
                         if r["epoch"] == 2 and r["node_id"] == transfer["node_id"]))
    unverified = sum(not p["verified_local_object_available"]
                     for node in campaign.nodes.values() for p in node.publications)
    unverified += sum(len(a["snapshot"]["entries"]) for a in campaign.coordinator.inventory_audit
                      if not a["verified_receipt_valid"])
    optional = 0
    for realization in campaign.realizations:
        if realization["epoch"] != 2:
            continue
        before = {e["artifact_id"] for e in realization["inventory_before"]["entries"]}
        required = set(realization["delta"]["required_artifact_ids"])
        optional += sum(e["length"] for e in realization["inventory_after"]["entries"]
                        if e["artifact_id"] in before - required)
    zero = {"unrequired_artifact_bytes_acquired": unrequired,
            "coordinator_bulk_artifact_bytes_observed": campaign.coordinator.bytes_observed,
            "replacement_plan_reacquired_already_verified_required_bytes": reacquired,
            "unverified_state_advertised_as_source": unverified}
    totals = {"bytes_by_source_descriptor": list(by_source.values()),
              "peer_cache_bytes": sum(r["bytes"] for t in transfers if t["ticket"]["mode"] == "PEER_CACHE" for r in t["reads"]),
              "origin_bytes": sum(r["bytes"] for t in transfers if t["ticket"]["mode"] == "ORIGIN" for r in t["reads"]),
              "local_verified_cache_hit_bytes": sum(e["bytes"] for r in campaign.realizations
                                                     for e in r["ledger"] if e["event"] == "CACHE_HIT"),
              "optional_cached_bytes_surviving_replacement": optional,
              "resume_reused_prefix_bytes": sum(e["bytes"] for r in campaign.realizations
                                                 for e in r["ledger"] if e["event"] == "RESUME_REUSED_PREFIX"),
              "total_data_plane_bytes": sum(r["bytes"] for r in actual)}
    require(all(value == 0 for value in zero.values()), "nonzero acceptance invariant")
    return zero, totals


def peer_reuse(campaign):
    reuses = []
    for transfer in campaign.transfers:
        if transfer["ticket"]["mode"] != "PEER_CACHE":
            continue
        aid = transfer["ticket"]["artifact_id"]
        source_id = transfer["ticket"]["source"]["source_id"]
        earlier = next((t for t in campaign.transfers[:campaign.transfers.index(transfer)]
                        if t["node_id"] == source_id and t["ticket"]["artifact_id"] == aid
                        and t["result"]["status"] == "ACQUIRED"), None)
        if earlier is None:
            continue
        initial = campaign.inventories[0]["snapshots"]
        require(not any(e["artifact_id"] == aid for s in initial
                        if s["node_id"] == transfer["node_id"] for e in s["entries"]),
                "later target initially had peer reuse artifact")
        publication = next(a for a in campaign.coordinator.inventory_audit
                           if a["snapshot"]["node_id"] == source_id
                           and any(e["artifact_id"] == aid for e in a["snapshot"]["entries"]))
        require(all(r["source"]["source_id"] == source_id for r in transfer["reads"]),
                "origin contacted during peer reuse")
        reuses.append({"artifact_id": aid, "content_digest": campaign.record(aid)["content_digest"],
                       "earlier_acquisition": earlier, "verified_inventory_ingested": publication,
                       "later_acquisition": transfer})
    require(bool(reuses), "no newly published peer reused")
    return {"reuses": reuses}


def run_campaign(out_dir: Path | None = None):
    methodology = ROOT / AREA / "methodology.md"
    frozen_methodology_hash = sha(methodology)
    producer_hashes = {path: sha(ROOT / path) for path in PRODUCERS}
    with tempfile.TemporaryDirectory(prefix="issue101-cpu-") as temporary:
        root = Path(temporary)
        with IsolationAudit(root) as audit:
            campaign = Campaign(root / "valid")
            campaign.freeze(1, {"C": [1, 3, 4]})
            campaign.realize("C")
            campaign.freeze(2, {"A": [1, 4, 5], "C": [1, 4, 5]})
            campaign.realize("A")
            campaign.realize("C")
            zero, totals = accounting(campaign)
            reuse = peer_reuse(campaign)
            negatives = {name: negative_control(name, root / "negative" / name) for name in NEGATIVE_REASONS}
            final_inventories = [node.inventory() for node in campaign.nodes.values()]
            require(all(len(s["entries"]) < len(campaign.fixture.records) for s in final_inventories),
                    "participant owns full fixture repository")
        isolation = audit.document()
        require(isolation["cpu_only"] and not isolation["freetoken_tree_modified"]
                and not isolation["issue97_evidence_directories_touched"], "isolation failed")
        summary = {"terminal_disposition": "PLAN_DRIVEN_ARTIFACT_ORCHESTRATION_PASS",
                   "implementation_base": BASE, "temporary_root": str(root),
                   "methodology_sha256_before_execution": frozen_methodology_hash,
                   "zero_invariants": zero, "accounting": totals,
                   "whole_repository_feasibility_prerequisite": False,
                   "final_inventory_artifact_counts": {s["node_id"]: len(s["entries"]) for s in final_inventories},
                   "fixture_artifact_count": len(campaign.fixture.records),
                   "negative_controls_passed": len(negatives),
                   "non_claims": ["No physical runtime integration or performance claim.",
                                  "No public API, protocol, digest, or storage layout is frozen."]}
        documents = {
            "fixture.json": campaign.fixture.identity,
            "epochs.json": {"plans": campaign.plans, "requirements": campaign.requirements,
                            "realizations": campaign.realizations},
            "inventories.json": {"steps": campaign.inventories,
                                 "publication_audit": {n: node.publications for n, node in campaign.nodes.items()}},
            "source-index.json": {"steps": campaign.indexes},
            "authorizations.json": {"attempts": campaign.coordinator.selections},
            "acquisition-ledger.json": {"transfers": campaign.transfers,
                                        "lifecycle": {n: node.lifecycle for n, node in campaign.nodes.items()}},
            "peer-reuse.json": reuse, "negative-controls.json": negatives,
            "isolation.json": isolation, "canonical-summary.json": summary,
            "producer-hashes.json": producer_hashes,
        }
    require(sha(methodology) == frozen_methodology_hash, "methodology changed during execution")
    if out_dir is not None:
        for name, document in documents.items():
            write_canonical_json(out_dir / name, document)
        write_manifest(out_dir)
    return documents


def write_manifest(out_dir):
    extras = [*PRODUCERS, str(AREA / "methodology.md"), str(AREA / "README.md"), ".github/workflows/ci.yml"]
    entries = {str(AREA / "evidence" / name): sha(out_dir / name) for name in EVIDENCE_FILES}
    entries.update({path: sha(ROOT / path) for path in extras})
    (out_dir / "MANIFEST.sha256").write_text("".join(f"{digest}  {path}\n" for path, digest in sorted(entries.items())))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / AREA / "evidence")
    args = parser.parse_args()
    documents = run_campaign(args.out)
    print(documents["canonical-summary.json"]["terminal_disposition"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

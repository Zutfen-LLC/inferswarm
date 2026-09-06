"""Internal CPU orchestration around the unchanged verified acquisition core.

Control objects contain descriptors only. Nodes own cache verification and reads.
Snapshots use trusted in-process receipts. This is not a public wire protocol.
"""
from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from issue74_methodology import canonical_json_bytes
from issue99_artifact_core import (
    AcquisitionError, AcquisitionLedger, CoordinatorAuthority, NodeArtifactCache,
    acquire_artifact, fail, self_digest, validate_artifact_record, validate_self_identity,
)

ROLES = ("OPTIONAL_CACHE_SOURCE", "REQUIRED_REPLICA_SOURCE")
_SNAPSHOT_ISSUER = object()


def _source_key(artifact_id, descriptor):
    return artifact_id, canonical_json_bytes(descriptor)


class VerifiedInventory(dict):
    """A Node-issued snapshot receipt for the trusted in-process boundary."""

    def __init__(self, document, issuer):
        if issuer is not _SNAPSHOT_ISSUER:
            raise fail("UNVERIFIED_OBJECT_PUBLICATION_REFUSED", "snapshot issuer")
        super().__init__(deepcopy(document))
        self._issued = canonical_json_bytes(document)

    def validate(self):
        if canonical_json_bytes(self) != self._issued:
            raise fail("UNVERIFIED_OBJECT_PUBLICATION_REFUSED", "snapshot changed after verification")


class PeerSource:
    """Read one artifact directly from a verified Node cache."""

    def __init__(self, node, record):
        self.node = node
        self.record = deepcopy(record)
        self.source_id = node.node_id
        self.access_log: list[dict[str, Any]] = []

    def descriptor(self):
        return self.node.descriptor()

    def read(self, origin, offset, length):
        if origin != self.record["origin"]:
            raise fail("PROVENANCE_IDENTITY_MISMATCH", "peer read origin")
        data = self.node.cache.open_verified(self.record)
        base = origin["byte_start"] if self.record["kind"] == "byte_range" else 0
        start = offset - base
        if start < 0 or start + length > len(data):
            raise fail("SOURCE_OBJECT_UNAVAILABLE", "peer range")
        result = data[start:start + length]
        self.access_log.append({"artifact_id": self.record["artifact_id"],
                                "offset": start, "bytes": len(result)})
        return result


class Node:
    """Own verified cache publication and direct acquisition for one Node."""

    def __init__(self, node_id: str, cache: NodeArtifactCache):
        self.node_id = node_id
        self.cache = cache
        self._published: dict[str, dict[str, Any]] = {}
        self._sequence = 0
        self.publications: list[dict[str, Any]] = []
        self.lifecycle: list[dict[str, Any]] = []
        self.failures: list[dict[str, Any]] = []
        self.ledger = AcquisitionLedger()

    def descriptor(self):
        return {"source_id": self.node_id, "endpoint": self.cache.root.resolve().as_uri()}

    def publish(self, record, role="OPTIONAL_CACHE_SOURCE", *, realization=None):
        record = validate_artifact_record(record)
        if role not in ROLES:
            raise fail("UNVERIFIED_OBJECT_PUBLICATION_REFUSED", "availability role")
        verified = self.cache.has_verified(record)
        if not verified:
            raise fail("UNVERIFIED_OBJECT_PUBLICATION_REFUSED", "object is not verified locally")
        entry = {"node_id": self.node_id, "artifact_id": record["artifact_id"],
                 "content_digest": record["content_digest"], "length": record["length"],
                 "role": role, "source": self.descriptor(), "record": deepcopy(record)}
        self._published[record["artifact_id"]] = entry
        self.publications.append({**(realization or {}), "node_id": self.node_id,
                                  "artifact_id": record["artifact_id"],
                                  "verified_local_object_available": verified,
                                  "content_digest": record["content_digest"],
                                  "length": record["length"]})

    def inventory(self):
        # Re-verify durable content independently of peer advertisement policy.
        objects = [obj for obj in self.cache.inventory()["verified_objects"]
                   if obj["byte_digest_verified"]]
        entries = []
        for entry in self._published.values():
            if self.cache.has_verified(entry["record"]):
                entries.append(entry)
        self._sequence += 1
        return VerifiedInventory({"node_id": self.node_id, "sequence": self._sequence,
                                  "source": self.descriptor(),
                                  "verified_objects": objects,
                                  "entries": sorted(entries, key=lambda e: e["artifact_id"])},
                                 _SNAPSHOT_ISSUER)

    def source(self, record):
        return PeerSource(self, record)

    def acquire(self, coordinator, ticket, source):
        authority, record = coordinator.validate_attempt(ticket, self.node_id, source.descriptor())
        identity = {"attempt_digest": ticket["attempt_digest"], "artifact_id": record["artifact_id"],
                    "participant_id": ticket["participant_id"], "node_id": self.node_id,
                    "epoch": ticket["epoch"],
                    "plan_digest": ticket["plan_digest"]}
        ledger_start = len(self.ledger.events)
        try:
            local = self.cache.has_verified(record)
            if not local:
                for state in ("MISSING", "AUTHORIZED", "ACQUIRING"):
                    self.lifecycle.append({**identity, "state": state})
            result = acquire_artifact(cache=self.cache, source=source, record=record,
                                      authorization=authority, participant_id=ticket["participant_id"],
                                      ledger=self.ledger)
        except AcquisitionError as error:
            self.failures.append({**identity, "reason": str(error).split(":")[0]})
            raise
        finally:
            for event in self.ledger.events[ledger_start:]:
                event.update(identity)
        if result["status"] == "INTERRUPTED":
            self.failures.append({**identity, "reason": "TRANSFER_INTERRUPTED"})
            return result
        self.lifecycle.append({**identity, "state": "VERIFIED_AVAILABLE"})
        return result


class AttemptAuthorization:
    """Keep the acquisition core bound to one currently issued attempt."""

    def __init__(self, coordinator, ticket):
        self._coordinator = coordinator
        self._ticket = deepcopy(ticket)

    def check_acquisition(self, *, participant_id, artifact_record, source_descriptor):
        c = self._coordinator
        c._guard(participant_id, artifact_record, source_descriptor)
        _, expected = c._check_attempt(self._ticket, self._ticket["node_id"], source_descriptor)
        if participant_id != self._ticket["participant_id"]:
            raise fail("SOURCE_UNAUTHORIZED", "participant outside exact attempt")
        if artifact_record.get("artifact_id") != expected["artifact_id"]:
            raise fail("UNDECLARED_REQUIREMENT_ARTIFACT", "artifact outside exact attempt")
        if artifact_record != expected:
            raise fail("PROVENANCE_IDENTITY_MISMATCH", "attempt artifact changed")


class Coordinator:
    """Own frozen requirements, snapshot inventory, and exact acquisition attempts."""

    def __init__(self, *, node_sources, origin_sources):
        self.bytes_observed = 0
        self._guard(node_sources, origin_sources)
        for descriptor in [*node_sources, *origin_sources]:
            if (set(descriptor) != {"source_id", "endpoint"}
                    or not all(isinstance(v, str) and v for v in descriptor.values())
                    or not descriptor["endpoint"].startswith("file://")):
                raise fail("SOURCE_UNAUTHORIZED", "unsupported source descriptor")
        descriptors = [*node_sources, *origin_sources]
        if len({s["source_id"] for s in descriptors}) != len(descriptors):
            raise fail("SOURCE_UNAUTHORIZED", "duplicate source identity")
        self._nodes = {s["source_id"]: deepcopy(s) for s in node_sources}
        self._origins = sorted(deepcopy(origin_sources), key=canonical_json_bytes)
        self._snapshots: dict[str, dict[str, Any]] = {}
        self._generation = 0
        self._attempts: dict[str, tuple[dict[str, Any], CoordinatorAuthority]] = {}
        self._deltas: dict[str, dict[str, Any]] = {}
        self._excluded: set[tuple[str, bytes]] = set()
        self._requirements: dict[str, Any] = {}
        self._plan: dict[str, Any] = {}
        self.selections: list[dict[str, Any]] = []
        self.rejections: list[dict[str, Any]] = []
        self.inventory_audit: list[dict[str, Any]] = []

    def _guard(self, *values):
        def walk(value):
            if isinstance(value, (bytes, bytearray)):
                self.bytes_observed += len(value)
                raise fail("SOURCE_UNAUTHORIZED", "bulk bytes presented to Coordinator")
            if isinstance(value, dict):
                for key, item in value.items():
                    walk(key)
                    walk(item)
            elif isinstance(value, (list, tuple, set)):
                for item in value:
                    walk(item)
        for value in values:
            walk(value)

    def freeze(self, plan, resolver):
        from issue99_artifact_core import derive_participant_requirements
        self._guard(plan)

        def checked_resolver(requirement_class, state_id):
            records = resolver(requirement_class, state_id)
            self._guard(records)
            return records

        requirements = derive_participant_requirements(plan, checked_resolver)
        self._guard(requirements)
        if any(p["node_id"] not in self._nodes for p in requirements["participants"]):
            raise fail("SOURCE_UNAUTHORIZED", "unregistered participant Node")
        self._plan = deepcopy(plan)
        self._requirements = deepcopy(requirements)
        self._generation += 1
        self._attempts.clear()
        self._deltas.clear()
        self._excluded.clear()
        return deepcopy(requirements)

    def ingest(self, snapshot):
        self._guard(snapshot)
        if not isinstance(snapshot, VerifiedInventory):
            raise fail("UNVERIFIED_OBJECT_PUBLICATION_REFUSED", "missing Node verification receipt")
        snapshot.validate()
        node_id = snapshot["node_id"]
        if self._nodes.get(node_id) != snapshot["source"]:
            raise fail("SOURCE_UNAUTHORIZED", "inventory source descriptor")
        previous = self._snapshots.get(node_id)
        if previous and snapshot["sequence"] <= previous["sequence"]:
            raise fail("RECONCILIATION_MISMATCH", "stale inventory sequence")
        local = {(obj["content_digest"], obj["length"]) for obj in snapshot["verified_objects"]
                 if obj["byte_digest_verified"]}
        if len(local) != len(snapshot["verified_objects"]):
            raise fail("UNVERIFIED_OBJECT_PUBLICATION_REFUSED", "unverified local inventory")
        for entry in snapshot["entries"]:
            record = validate_artifact_record(entry["record"])
            if (entry["source"] != snapshot["source"] or entry["node_id"] != node_id
                    or entry["role"] not in ROLES
                    or (record["content_digest"], record["length"]) not in local
                    or any(entry[k] != record[k] for k in ("artifact_id", "content_digest", "length"))):
                raise fail("UNVERIFIED_OBJECT_PUBLICATION_REFUSED", "inventory identity")
        copied = json.loads(canonical_json_bytes(snapshot))
        self._snapshots[node_id] = copied
        self.inventory_audit.append({"snapshot": copied, "verified_receipt_valid": True})

    def source_index(self):
        self._guard(self._snapshots)
        index: dict[str, list[dict[str, Any]]] = {}
        for snapshot in self._snapshots.values():
            for entry in snapshot["entries"]:
                if _source_key(entry["artifact_id"], entry["source"]) not in self._excluded:
                    index.setdefault(entry["artifact_id"], []).append(deepcopy(entry))
        return {aid: sorted(entries, key=lambda e: canonical_json_bytes(e["source"]))
                for aid, entries in sorted(index.items())}

    def _participant(self, participant_id):
        for participant in self._requirements.get("participants", []):
            if participant["participant_id"] == participant_id:
                return participant
        raise fail("SOURCE_UNAUTHORIZED", "participant outside frozen plan")

    def delta(self, participant_id):
        self._guard(participant_id)
        participant = self._participant(participant_id)
        snapshot = self._snapshots.get(participant["node_id"])
        if snapshot is None:
            raise fail("RECONCILIATION_MISMATCH", "target inventory missing")
        local = {(obj["content_digest"], obj["length"]) for obj in snapshot["verified_objects"]}
        required = participant["required_artifacts"]
        document = {"epoch": self._plan["epoch"],
                    "generation": self._generation, "plan_digest": self._plan["plan_digest"],
                    "participant_id": participant_id, "node_id": participant["node_id"],
                    "participant_requirements_digest": participant["participant_requirements_digest"],
                    "inventory_sequence": snapshot["sequence"],
                    "required_artifact_ids": sorted(r["artifact_id"] for r in required),
                    "local_artifact_ids": sorted(r["artifact_id"] for r in required
                                                 if (r["content_digest"], r["length"]) in local),
                    "missing_artifact_ids": sorted(r["artifact_id"] for r in required
                                                   if (r["content_digest"], r["length"]) not in local)}
        document["delta_digest"] = self_digest(document, identity_field="delta_digest")
        self._deltas[document["delta_digest"]] = deepcopy(document)
        return document

    def authorize(self, delta, artifact_id):
        self._guard(delta, artifact_id)
        validate_self_identity(delta, identity_field="delta_digest")
        if self._deltas.get(delta["delta_digest"]) != delta:
            raise fail("RECONCILIATION_MISMATCH", "unissued or stale delta")
        if self._snapshots[delta["node_id"]]["sequence"] != delta["inventory_sequence"]:
            raise fail("RECONCILIATION_MISMATCH", "target inventory changed; derive a fresh delta")
        participant = self._participant(delta["participant_id"])
        records = {r["artifact_id"]: r for r in participant["required_artifacts"]}
        if artifact_id not in records:
            raise fail("UNDECLARED_REQUIREMENT_ARTIFACT", "artifact outside frozen requirement")
        record = records[artifact_id]
        candidates = []
        if artifact_id in delta["local_artifact_ids"]:
            source = self._nodes[delta["node_id"]]
            mode = "LOCAL_CACHE"
        else:
            candidates = [e["source"] for e in self.source_index().get(artifact_id, [])
                          if e["record"] == record and e["node_id"] != delta["node_id"]]
            mode = "PEER_CACHE" if candidates else "ORIGIN"
            if not candidates:
                candidates = [s for s in self._origins
                              if _source_key(artifact_id, s) not in self._excluded]
            if not candidates:
                raise fail("SOURCE_UNAUTHORIZED", "no authorized source")
            source = candidates[0]
        authority = CoordinatorAuthority(plan=self._plan, requirements=self._requirements,
                                         eligible_sources=[source])
        ticket = {"epoch": self._plan["epoch"],
                  "plan_digest": self._plan["plan_digest"], "generation": self._generation,
                  "participant_id": delta["participant_id"], "node_id": delta["node_id"],
                  "participant_requirements_digest": participant["participant_requirements_digest"],
                  "delta_digest": delta["delta_digest"], "artifact_id": artifact_id,
                  "source": deepcopy(source), "mode": mode, "candidates": deepcopy(candidates),
                  "attempt_number": len(self.selections) + 1,
                  "authorization": deepcopy(authority.authorization)}
        ticket["attempt_digest"] = self_digest(ticket, identity_field="attempt_digest")
        self._attempts[ticket["attempt_digest"]] = (deepcopy(ticket), authority)
        self.selections.append(deepcopy(ticket))
        return ticket

    def validate_attempt(self, ticket, node_id, source_descriptor):
        _, record = self._check_attempt(ticket, node_id, source_descriptor)
        return AttemptAuthorization(self, ticket), record

    def _check_attempt(self, ticket, node_id, source_descriptor):
        self._guard(ticket, node_id, source_descriptor)
        validate_self_identity(ticket, identity_field="attempt_digest")
        issued = self._attempts.get(ticket["attempt_digest"])
        if issued is None or ticket != issued[0]:
            raise fail("RECONCILIATION_MISMATCH", "stale or changed authorization")
        if node_id != ticket["node_id"] or source_descriptor != ticket["source"]:
            raise fail("SOURCE_UNAUTHORIZED", "exact source or target changed")
        if (ticket["mode"] != "LOCAL_CACHE"
                and _source_key(ticket["artifact_id"], source_descriptor) in self._excluded):
            raise fail("SOURCE_UNAUTHORIZED", "source attempt rejected")
        participant = self._participant(ticket["participant_id"])
        record = next(r for r in participant["required_artifacts"] if r["artifact_id"] == ticket["artifact_id"])
        authority = issued[1]
        authority.check_acquisition(participant_id=ticket["participant_id"], artifact_record=record,
                                    source_descriptor=source_descriptor)
        return authority, deepcopy(record)

    def reject_source(self, ticket, reason):
        self._guard(ticket, reason)
        if reason not in ("SOURCE_OBJECT_UNAVAILABLE", "UNVERIFIED_SOURCE_READ_REFUSED",
                          "CACHE_OBJECT_TAMPERED", "INTEGRITY_DIGEST_MISMATCH"):
            raise fail("SOURCE_UNAUTHORIZED", "unsupported source rejection reason")
        self.validate_attempt(ticket, ticket["node_id"], ticket["source"])
        self._excluded.add(_source_key(ticket["artifact_id"], ticket["source"]))
        self.rejections.append({"attempt_digest": ticket["attempt_digest"], "reason": reason,
                                "epoch": ticket["epoch"], "participant_id": ticket["participant_id"],
                                "node_id": ticket["node_id"],
                                "artifact_id": ticket["artifact_id"], "source": deepcopy(ticket["source"])})

    def reconcile(self, participant_id, used_artifact_ids, materializations):
        self._guard(participant_id, used_artifact_ids, materializations)
        participant = self._participant(participant_id)
        for materialization in materializations:
            if (materialization.get("participant_id") != participant_id
                    or materialization.get("node_id") != participant["node_id"]
                    or materialization.get("epoch") != self._plan["epoch"]):
                raise fail("RECONCILIATION_MISMATCH", "materialization realization identity")
        authority = CoordinatorAuthority(plan=self._plan, requirements=self._requirements,
                                         eligible_sources=[])
        result = authority.reconcile(participant_id=participant_id,
                                     used_artifact_ids=used_artifact_ids,
                                     materializations=materializations)
        self.bytes_observed += authority.bytes_observed
        result.update(epoch=self._plan["epoch"], node_id=participant["node_id"])
        return result

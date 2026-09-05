"""Behavior checks at the issue #101 public orchestration boundaries."""
import sys
from copy import deepcopy
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from issue99_artifact_core import AcquisitionError, LocalFileSource, NodeArtifactCache, TransferInterrupted, self_digest, acquire_artifact
from issue101_fixture import Fixture, execute
from issue101_orchestration import Coordinator, Node


class InventoryTests(unittest.TestCase):
    def test_only_verified_published_artifacts_enter_complete_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = Fixture(root / "origin")
            node = Node("A", NodeArtifactCache(root / "A"))
            record = fixture.records[1]
            node.cache.begin_partial(record)
            node.cache.append_partial(record, b"\x01\x00")
            with self.assertRaisesRegex(AcquisitionError, "UNVERIFIED_OBJECT_PUBLICATION_REFUSED"):
                node.publish(record)
            self.assertEqual(node.inventory()["entries"], [])
            fixture.seed(node, [1, 2])
            snapshot = node.inventory()
            self.assertEqual(len(snapshot["entries"]), 2)
            self.assertEqual({e["artifact_id"] for e in snapshot["entries"]},
                             {fixture.records[n]["artifact_id"] for n in (1, 2)})
            self.assertTrue(all(e["role"] == "OPTIONAL_CACHE_SOURCE" for e in snapshot["entries"]))


class OrchestrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.fixture = Fixture(root / "origin")
        self.nodes = {name: Node(name, NodeArtifactCache(root / name)) for name in "ABC"}
        self.fixture.seed(self.nodes["A"], [1, 2])
        self.fixture.seed(self.nodes["B"], [2, 3])
        self.origin = LocalFileSource(source_id="origin", root=self.fixture.root)
        self.coordinator = Coordinator(
            node_sources=[node.descriptor() for node in self.nodes.values()],
            origin_sources=[self.origin.descriptor()])
        self.plan = self.fixture.plan(1, {"C": [1, 3, 4]})
        self.coordinator.freeze(self.plan, self.fixture.resolve)
        for node in self.nodes.values():
            self.coordinator.ingest(node.inventory())

    def test_deterministic_peer_selection_origin_fallback_and_verified_publication(self):
        delta = self.coordinator.delta("C")
        self.assertEqual(set(delta["missing_artifact_ids"]),
                         {self.fixture.records[n]["artifact_id"] for n in (1, 3, 4)})
        for number, source_id in ((1, "A"), (3, "B"), (4, "origin")):
            record = self.fixture.records[number]
            ticket = self.coordinator.authorize(delta, record["artifact_id"])
            self.assertEqual(ticket["source"]["source_id"], source_id)
            source = self.origin if source_id == "origin" else self.nodes[source_id].source(record)
            result = self.nodes["C"].acquire(self.coordinator, ticket, source)
            self.assertEqual(result["status"], "ACQUIRED")
        self.coordinator.ingest(self.nodes["C"].inventory())
        self.assertEqual(self.coordinator.delta("C")["missing_artifact_ids"], [])
        self.assertEqual(self.coordinator.bytes_observed, 0)
        self.assertEqual([e["state"] for e in self.nodes["C"].lifecycle[:4]],
                         ["MISSING", "AUTHORIZED", "ACQUIRING", "VERIFIED_AVAILABLE"])

    def realize(self, node_id):
        delta = self.coordinator.delta(node_id)
        tickets = []
        for aid in delta["required_artifact_ids"]:
            record = next(r for r in self.fixture.records.values() if r["artifact_id"] == aid)
            ticket = self.coordinator.authorize(delta, aid)
            source_id = ticket["source"]["source_id"]
            source = self.origin if source_id == "origin" else self.nodes[source_id].source(record)
            self.nodes[node_id].acquire(self.coordinator, ticket, source)
            tickets.append(ticket)
        self.coordinator.ingest(self.nodes[node_id].inventory())
        return delta, tickets

    def test_replacement_reuses_new_peer_publication_and_retains_optional_cache(self):
        _, old_tickets = self.realize("C")
        plan = self.fixture.plan(2, {"A": [1, 4, 5], "C": [1, 4, 5]})
        requirements = self.coordinator.freeze(plan, self.fixture.resolve)
        delta, tickets = self.realize("A")
        modes = {t["artifact_id"]: (t["mode"], t["source"]["source_id"]) for t in tickets}
        self.assertEqual(modes[self.fixture.records[1]["artifact_id"]], ("LOCAL_CACHE", "A"))
        self.assertEqual(modes[self.fixture.records[4]["artifact_id"]], ("PEER_CACHE", "C"))
        self.assertEqual(modes[self.fixture.records[5]["artifact_id"]], ("ORIGIN", "origin"))
        self.assertEqual(len(delta["missing_artifact_ids"]), 2)
        c_delta, c_tickets = self.realize("C")
        self.assertEqual(c_delta["missing_artifact_ids"], [self.fixture.records[5]["artifact_id"]])
        self.assertEqual(next(t for t in c_tickets if t["mode"] == "PEER_CACHE")["source"]["source_id"], "A")
        self.assertEqual(sum(e["bytes"] for e in self.nodes["A"].ledger.events if e["event"] == "ACQUIRED"), 8)
        self.assertTrue(self.nodes["C"].cache.has_verified(self.fixture.records[3]))
        self.assertTrue(self.nodes["A"].cache.has_verified(self.fixture.records[2]))
        for participant in requirements["participants"]:
            result = execute(plan, participant, self.nodes[participant["node_id"]], self.coordinator)
            self.assertEqual(result["output"], 29)
            self.assertTrue(result["matches_reference"])
        with self.assertRaisesRegex(AcquisitionError, "RECONCILIATION_MISMATCH"):
            self.nodes["C"].acquire(self.coordinator, old_tickets[0], self.origin)

    def test_snapshot_replacement_removes_unavailable_entries_and_rejects_forgery(self):
        old = self.nodes["A"].inventory()
        self.coordinator.ingest(old)
        record = self.fixture.records[1]
        self.nodes["A"].cache.lookup(record["content_digest"]).unlink()
        self.coordinator.ingest(self.nodes["A"].inventory())
        self.assertNotIn(record["artifact_id"], self.coordinator.source_index())
        with self.assertRaisesRegex(AcquisitionError, "RECONCILIATION_MISMATCH"):
            self.coordinator.ingest(old)
        forged = self.nodes["C"].inventory()
        forged["entries"] = old["entries"]
        with self.assertRaisesRegex(AcquisitionError, "UNVERIFIED_OBJECT_PUBLICATION_REFUSED"):
            self.coordinator.ingest(forged)

    def test_drifted_descriptor_and_unapproved_fallback_move_zero_bytes(self):
        record = self.fixture.records[1]
        ticket = self.coordinator.authorize(self.coordinator.delta("C"), record["artifact_id"])
        drifted = LocalFileSource(source_id="A", root=self.fixture.root)
        for source in (drifted, self.origin):
            with self.assertRaisesRegex(AcquisitionError, "SOURCE_UNAUTHORIZED"):
                self.nodes["C"].acquire(self.coordinator, ticket, source)
            self.assertEqual(source.access_log, [])
        self.assertEqual(self.nodes["C"].inventory()["entries"], [])

    def test_changed_delta_and_unrequired_artifact_fail_before_acquisition(self):
        delta = self.coordinator.delta("C")
        changed = deepcopy(delta)
        changed["missing_artifact_ids"] = []
        with self.assertRaisesRegex(AcquisitionError, "RECONCILIATION_MISMATCH"):
            self.coordinator.authorize(changed, self.fixture.records[1]["artifact_id"])
        with self.assertRaisesRegex(AcquisitionError, "UNDECLARED_REQUIREMENT_ARTIFACT"):
            self.coordinator.authorize(delta, self.fixture.records[6]["artifact_id"])
        self.assertEqual(self.origin.access_log, [])

    def test_local_integrity_drift_is_retained_as_failure_without_cache_hit(self):
        self.realize("C")
        record = self.fixture.records[1]
        ticket = self.coordinator.authorize(self.coordinator.delta("C"), record["artifact_id"])
        self.nodes["C"].cache.lookup(record["content_digest"]).write_bytes(b"xxxx")
        with self.assertRaisesRegex(AcquisitionError, "CACHE_OBJECT_TAMPERED"):
            self.nodes["C"].acquire(self.coordinator, ticket, self.nodes["C"].source(record))
        self.assertEqual(self.nodes["C"].failures[-1]["reason"], "CACHE_OBJECT_TAMPERED")
        self.assertFalse(any(e["event"] == "CACHE_HIT" for e in self.nodes["C"].ledger.events))

    def test_interruption_stays_unadvertised_and_resumes_under_exact_authorization(self):
        record = self.fixture.records[1]
        ticket = self.coordinator.authorize(self.coordinator.delta("C"), record["artifact_id"])
        peer = self.nodes["A"].source(record)

        class InterruptedTransport:
            source_id = peer.source_id

            def descriptor(self):
                return peer.descriptor()

            def read(self, origin, offset, length):
                raise TransferInterrupted("controlled interruption", peer.read(origin, offset, 2))

        result = self.nodes["C"].acquire(self.coordinator, ticket, InterruptedTransport())
        self.assertEqual(result, {"status": "INTERRUPTED", "retained_bytes": 2})
        self.assertEqual(self.nodes["C"].inventory()["entries"], [])
        result = self.nodes["C"].acquire(self.coordinator, ticket, peer)
        self.assertEqual(result, {"status": "ACQUIRED", "bytes": 2})
        self.assertTrue(self.nodes["C"].cache.has_verified(record))
        self.assertEqual(sum(e["bytes"] for e in self.nodes["C"].ledger.events
                             if e["event"] == "RESUME_REUSED_PREFIX"), 2)

    def test_canonical_order_ignores_inventory_arrival_order_and_no_source_fails_closed(self):
        plan = self.fixture.plan(2, {"C": [2]})
        self.coordinator.freeze(plan, self.fixture.resolve)
        for name in ("B", "A"):
            self.coordinator.ingest(self.nodes[name].inventory())
        record = self.fixture.records[2]
        delta = self.coordinator.delta("C")
        for expected in ("A", "B", "origin"):
            ticket = self.coordinator.authorize(delta, record["artifact_id"])
            self.assertEqual(ticket["source"]["source_id"], expected)
            self.coordinator.reject_source(ticket, "SOURCE_OBJECT_UNAVAILABLE")
        with self.assertRaisesRegex(AcquisitionError, "SOURCE_UNAUTHORIZED"):
            self.coordinator.authorize(delta, record["artifact_id"])

    def test_content_dedup_preserves_distinct_artifact_inventory_identities(self):
        original = self.fixture.records[1]
        alias = deepcopy(original)
        alias["satisfies_logical_state_ids"] = ["coefficient.2"]
        alias["artifact_id"] = self_digest(alias, identity_field="artifact_id")
        node = self.nodes["C"]
        node.cache.publish(original, bytes([1, 0, 0, 0]))
        node.publish(original)
        node.publish(alias, role="REQUIRED_REPLICA_SOURCE")
        snapshot = node.inventory()
        self.assertEqual({e["artifact_id"] for e in snapshot["entries"]},
                         {original["artifact_id"], alias["artifact_id"]})
        self.assertEqual(node.cache.inventory()["verified_bytes"], 4)
        self.coordinator.ingest(snapshot)
        self.assertEqual(len(self.coordinator.source_index()[alias["artifact_id"]]), 1)

    def test_acquisition_core_cannot_reuse_an_attempt_for_another_artifact_or_epoch(self):
        record = self.fixture.records[1]
        ticket = self.coordinator.authorize(self.coordinator.delta("C"), record["artifact_id"])
        authorization, _ = self.coordinator.validate_attempt(ticket, "C", ticket["source"])
        another = self.fixture.records[3]
        peer = self.nodes["A"].source(another)
        with self.assertRaisesRegex(AcquisitionError, "UNDECLARED_REQUIREMENT_ARTIFACT"):
            acquire_artifact(cache=self.nodes["C"].cache, source=peer, record=another,
                             authorization=authorization, participant_id="C", ledger=self.nodes["C"].ledger)
        self.coordinator.freeze(self.fixture.plan(2, {"C": [1, 4, 5]}), self.fixture.resolve)
        with self.assertRaisesRegex(AcquisitionError, "RECONCILIATION_MISMATCH"):
            acquire_artifact(cache=self.nodes["C"].cache, source=self.nodes["A"].source(record),
                             record=record, authorization=authorization, participant_id="C",
                             ledger=self.nodes["C"].ledger)


if __name__ == "__main__":
    unittest.main()

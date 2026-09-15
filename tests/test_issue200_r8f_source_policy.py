"""Unit-level behavior checks for the issue #200 (R8-F) Source-policy seam."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from issue99_artifact_core import AcquisitionError, LocalFileSource, NodeArtifactCache
from issue101_orchestration import Coordinator, Node
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


class PolicyCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.fixture = ReleaseFixture(self.root / "origin")
        self.origin = LocalFileSource(source_id="origin", root=self.root / "origin")

    def make(self, name):
        node = Node(name, NodeArtifactCache(self.root / name))
        coordinator = PolicyCoordinator(node_sources=[node.descriptor()], origin_sources=[self.origin.descriptor()])
        return node, coordinator

    def test_default_policy_matches_accepted_authorize_local_then_remote_order(self):
        """A PolicyCoordinator is still an accepted #101 Coordinator: its
        inherited, unmodified ``authorize`` behaves byte-for-byte identically
        to plain #101 usage, and ``authorize_under_policy`` under the default
        policy selects the same Source ``authorize`` would."""
        node, coordinator = self.make("A")
        self.fixture.seed_and_advertise(node, [1])
        plan = self.fixture.plan(1, {"P": ("A", [1, 2])})
        coordinator.freeze(plan, self.fixture.resolve)
        coordinator.ingest(node.inventory())
        delta = coordinator.delta("P")
        legacy_ticket = coordinator.authorize(delta, self.fixture.records[2]["artifact_id"])
        policy_ticket = coordinator.authorize_under_policy(
            delta, self.fixture.records[1]["artifact_id"], SOURCE_POLICY_PREFER_LOCAL_VERIFIED)
        self.assertEqual(legacy_ticket["mode"], "ORIGIN")
        self.assertEqual(policy_ticket["mode"], "LOCAL_CACHE")

    def test_l1_local_present_prefer_local_zero_acquisition(self):
        node, coordinator = self.make("A")
        self.fixture.stage_full_release(node)
        plan = self.fixture.plan(1, {"P": ("A", [1])})
        coordinator.freeze(plan, self.fixture.resolve)
        coordinator.ingest(node.inventory())
        delta = coordinator.delta("P")
        record = self.fixture.records[1]
        ticket = coordinator.authorize_under_policy(delta, record["artifact_id"], SOURCE_POLICY_PREFER_LOCAL_VERIFIED)
        self.assertEqual(ticket["mode"], "LOCAL_CACHE")
        result = acquire_under_policy(node, coordinator, ticket, node.source(record))
        self.assertEqual(result, {"status": "CACHE_HIT", "bytes": record["length"]})
        self.assertEqual(ledger_network_accounting(node.ledger.events)["newly_acquired_bytes"], 0)

    def test_l2_local_absent_prefer_local_falls_back_remote(self):
        node, coordinator = self.make("A")
        plan = self.fixture.plan(1, {"P": ("A", [2])})
        coordinator.freeze(plan, self.fixture.resolve)
        coordinator.ingest(node.inventory())
        delta = coordinator.delta("P")
        record = self.fixture.records[2]
        ticket = coordinator.authorize_under_policy(delta, record["artifact_id"], SOURCE_POLICY_PREFER_LOCAL_VERIFIED)
        self.assertEqual(ticket["mode"], "ORIGIN")
        result = acquire_under_policy(node, coordinator, ticket, self.origin)
        self.assertEqual(result, {"status": "ACQUIRED", "bytes": record["length"]})

    def test_r1_local_present_prefer_remote_forces_real_transfer(self):
        node, coordinator = self.make("A")
        self.fixture.stage_full_release(node)
        plan = self.fixture.plan(1, {"P": ("A", [3])})
        coordinator.freeze(plan, self.fixture.resolve)
        coordinator.ingest(node.inventory())
        delta = coordinator.delta("P")
        record = self.fixture.records[3]
        self.assertIn(record["artifact_id"], delta["local_artifact_ids"])
        ticket = coordinator.authorize_under_policy(delta, record["artifact_id"], SOURCE_POLICY_PREFER_REMOTE_AUTHORIZED)
        self.assertEqual(ticket["mode"], "ORIGIN")
        result = acquire_under_policy(node, coordinator, ticket, self.origin)
        self.assertEqual(result, {"status": "ACQUIRED", "bytes": record["length"]})
        event = node.ledger.events[-1]
        self.assertEqual(event["event"], "ACQUIRED")
        self.assertTrue(event["policy_forced_transfer"])
        self.assertEqual(event["source_id"], "origin")

    def test_r1_peer_variant_also_forces_real_transfer(self):
        """PREFER_REMOTE_AUTHORIZED must equally prefer a PEER_CACHE Source
        over local possession, not only ORIGIN."""
        peer, coordinator = self.make("PEER")
        node, _ = self.make("A")
        coordinator = PolicyCoordinator(node_sources=[peer.descriptor(), node.descriptor()],
                                        origin_sources=[self.origin.descriptor()])
        self.fixture.seed_and_advertise(peer, [4])
        self.fixture.stage_full_release(node)
        plan = self.fixture.plan(1, {"P": ("A", [4])})
        coordinator.freeze(plan, self.fixture.resolve)
        coordinator.ingest(peer.inventory())
        coordinator.ingest(node.inventory())
        delta = coordinator.delta("P")
        record = self.fixture.records[4]
        ticket = coordinator.authorize_under_policy(delta, record["artifact_id"], SOURCE_POLICY_PREFER_REMOTE_AUTHORIZED)
        self.assertEqual(ticket["mode"], "PEER_CACHE")
        self.assertEqual(ticket["source"]["source_id"], "PEER")
        result = acquire_under_policy(node, coordinator, ticket, peer.source(record))
        self.assertEqual(result["status"], "ACQUIRED")
        self.assertTrue(node.ledger.events[-1]["policy_forced_transfer"])

    def test_lreq_incomplete_local_fails_before_any_remote_read(self):
        node, coordinator = self.make("A")
        plan = self.fixture.plan(1, {"P": ("A", [5])})
        coordinator.freeze(plan, self.fixture.resolve)
        coordinator.ingest(node.inventory())
        delta = coordinator.delta("P")
        record = self.fixture.records[5]
        with self.assertRaisesRegex(AcquisitionError, "SOURCE_UNAUTHORIZED"):
            coordinator.authorize_under_policy(delta, record["artifact_id"], SOURCE_POLICY_REQUIRE_LOCAL_VERIFIED)
        self.assertEqual(self.origin.requests_for("release.bin"), [])
        self.assertEqual(coordinator.selections, [])

    def test_rreq_no_remote_fails_before_local_substitution(self):
        node, coordinator = self.make("A")
        coordinator = PolicyCoordinator(node_sources=[node.descriptor()], origin_sources=[])
        self.fixture.stage_full_release(node)
        plan = self.fixture.plan(1, {"P": ("A", [6])})
        coordinator.freeze(plan, self.fixture.resolve)
        coordinator.ingest(node.inventory())
        delta = coordinator.delta("P")
        record = self.fixture.records[6]
        self.assertIn(record["artifact_id"], delta["local_artifact_ids"])
        with self.assertRaisesRegex(AcquisitionError, "SOURCE_UNAUTHORIZED"):
            coordinator.authorize_under_policy(delta, record["artifact_id"], SOURCE_POLICY_REQUIRE_REMOTE_AUTHORIZED)
        self.assertEqual(node.ledger.events, [])

    def test_unsupported_policy_rejected(self):
        node, coordinator = self.make("A")
        plan = self.fixture.plan(1, {"P": ("A", [1])})
        coordinator.freeze(plan, self.fixture.resolve)
        coordinator.ingest(node.inventory())
        delta = coordinator.delta("P")
        with self.assertRaisesRegex(AcquisitionError, "SOURCE_UNAUTHORIZED"):
            coordinator.authorize_under_policy(delta, self.fixture.records[1]["artifact_id"], "NOT_A_POLICY")

    def test_policy_never_changes_required_artifact_set(self):
        node, coordinator = self.make("A")
        self.fixture.stage_full_release(node)
        plan = self.fixture.plan(1, {"P": ("A", [1, 2, 3])})
        requirements = coordinator.freeze(plan, self.fixture.resolve)
        coordinator.ingest(node.inventory())
        before = requirements["participants"][0]["participant_requirements_digest"]
        delta = coordinator.delta("P")
        for policy in SOURCE_POLICIES:
            try:
                coordinator.authorize_under_policy(delta, self.fixture.records[1]["artifact_id"], policy)
            except AcquisitionError:
                pass
            self.assertEqual(coordinator._participant("P")["participant_requirements_digest"], before)

    def test_coordinator_rejects_bulk_bytes_through_the_new_seam(self):
        node, coordinator = self.make("A")
        plan = self.fixture.plan(1, {"P": ("A", [1])})
        coordinator.freeze(plan, self.fixture.resolve)
        coordinator.ingest(node.inventory())
        delta = coordinator.delta("P")
        before = coordinator.bytes_observed
        with self.assertRaisesRegex(AcquisitionError, "SOURCE_UNAUTHORIZED"):
            coordinator.authorize_under_policy(delta, self.fixture.records[1]["artifact_id"],
                                               {"payload": b"bulk-bytes"})
        self.assertGreater(coordinator.bytes_observed, before)


class LocalBackingAccountingTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.fixture = ReleaseFixture(self.root / "origin")

    def test_full_release_backing_distinguishes_required_from_optional(self):
        node = Node("A", NodeArtifactCache(self.root / "A"))
        coordinator = PolicyCoordinator(node_sources=[node.descriptor()], origin_sources=[])
        self.fixture.stage_full_release(node)
        plan = self.fixture.plan(1, {"P": ("A", [1])})
        requirements = coordinator.freeze(plan, self.fixture.resolve)
        accounting = local_backing_accounting(node=node, participant_requirements=requirements["participants"][0])
        self.assertEqual(accounting["required_bytes_satisfied_from_local_backing"],
                         self.fixture.records[1]["length"])
        expected_optional = sum(r["length"] for n, r in self.fixture.records.items() if n != 1)
        self.assertEqual(accounting["retained_optional_backing_bytes"], expected_optional)

    def test_full_release_never_enlarges_required_artifact_set(self):
        node = Node("A", NodeArtifactCache(self.root / "A"))
        coordinator = PolicyCoordinator(node_sources=[node.descriptor()], origin_sources=[])
        self.fixture.stage_full_release(node)  # 8 verified members
        plan = self.fixture.plan(1, {"P": ("A", [2])})  # only 1 required
        requirements = coordinator.freeze(plan, self.fixture.resolve)
        self.assertEqual(len(requirements["participants"][0]["required_artifacts"]), 1)

    def test_unverified_file_never_counts_as_backing(self):
        node = Node("A", NodeArtifactCache(self.root / "A"))
        coordinator = PolicyCoordinator(node_sources=[node.descriptor()], origin_sources=[])
        (node.cache.root / "objects" / "sha256-deadbeef").write_bytes(b"not-the-right-bytes")
        plan = self.fixture.plan(1, {"P": ("A", [1])})
        requirements = coordinator.freeze(plan, self.fixture.resolve)
        accounting = local_backing_accounting(node=node, participant_requirements=requirements["participants"][0])
        self.assertEqual(accounting["total_verified_local_backing_bytes"], 0)

    def test_evicting_optional_backing_does_not_corrupt_required_realization(self):
        node = Node("A", NodeArtifactCache(self.root / "A"))
        coordinator = PolicyCoordinator(node_sources=[node.descriptor()], origin_sources=[])
        self.fixture.stage_full_release(node)
        plan = self.fixture.plan(1, {"P": ("A", [1])})
        coordinator.freeze(plan, self.fixture.resolve)
        # Evict every member except the one actually required.
        for number, record in self.fixture.records.items():
            if number != 1:
                node.cache.lookup(record["content_digest"]).unlink()
        coordinator.ingest(node.inventory())
        delta = coordinator.delta("P")
        self.assertEqual(delta["local_artifact_ids"], [self.fixture.records[1]["artifact_id"]])
        ticket = coordinator.authorize_under_policy(
            delta, self.fixture.records[1]["artifact_id"], SOURCE_POLICY_PREFER_LOCAL_VERIFIED)
        self.assertEqual(ticket["mode"], "LOCAL_CACHE")


class StaticDisciplineTests(unittest.TestCase):
    def test_no_frozen_producer_bytes_changed(self):
        """R8-F must never modify the hash-pinned #99/#101 producers; it may
        only add new files that compose their public surface."""
        import hashlib
        pinned = {
            "scripts/issue99_artifact_core.py": "8b88af5b2f738c2a7428c9538cf76a14f889cb573a1722122951c45fc5965321",
            "scripts/issue101_orchestration.py": "37027a7d5ebed8505d50a4a060f36bfe0330d3473175d63147db3e1986089860",
        }
        for path, digest in pinned.items():
            self.assertEqual(hashlib.sha256((ROOT / path).read_bytes()).hexdigest(), digest,
                             f"{path} must remain byte-identical to the accepted #99/#101 evidence")

    def test_no_forbidden_model_or_vendor_nouns_in_generic_seam(self):
        """Only the generic Source-policy/fixture seam must stay
        model-independent. ``issue200_r8f_proof.py`` legitimately documents
        NC-12 (the Qwen physical-arm negative control) and Phase 4's
        llama.cpp/ggml-rpc finding by name, which is evidence reporting, not
        the generic planner/seam learning a model noun."""
        for name in ("issue200_r8f_source_policy.py", "issue200_r8f_fixture.py"):
            text = (ROOT / "scripts" / name).read_text().lower()
            for forbidden in ("qwen", "gguf", "moe", "cuda", "vulkan", "pcie", "gemma", "safetensors",
                              "llama.cpp", "ggml", "rpc"):
                self.assertNotIn(forbidden, text, f"{forbidden!r} must not appear in {name}")

    def test_proof_stack_imports_only_stdlib_and_accepted_modules(self):
        import ast
        allowed = set(sys.stdlib_module_names) | {
            "issue74_methodology", "issue99_artifact_core", "issue101_orchestration",
            "issue200_r8f_source_policy", "issue200_r8f_fixture", "issue200_r8f_proof"}
        for name in ("issue200_r8f_source_policy.py", "issue200_r8f_fixture.py", "issue200_r8f_proof.py"):
            tree = ast.parse((ROOT / "scripts" / name).read_text())
            modules = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules.update(alias.name.split(".")[0] for alias in node.names)
                if isinstance(node, ast.ImportFrom) and node.module:
                    modules.add(node.module.split(".")[0])
            self.assertTrue(modules <= allowed, modules - allowed)
            self.assertFalse(modules & {"socket", "subprocess", "torch", "triton"})


if __name__ == "__main__":
    unittest.main()

"""Retained-byte reducer CPU-only fixtures (never physical authority)."""
from __future__ import annotations
import json
import shutil
import unittest
from pathlib import Path

from tests.test_issue252_physical import FixtureMixin, git, sha, A, C, D
import issue252_terminal as T


class TerminalTests(FixtureMixin, unittest.TestCase):
    def setUp(self):
        self.fixture()
        self.write_json(self.evidence / "authority.json", {
            "repo_root": str(self.repo), "dispatch": self.authority()})

    def verdict(self):
        return T.derive_terminal(self.evidence, {})

    def deterministic(self, arm="A1", n=5):
        for i in range(1, n + 1):
            self.retain(arm, i)

    def variable(self, arm="A1"):
        self.retain(arm, 1)
        self.retain(arm, 2, bytes([1]) * D.ROW_BYTES)

    def trace(self):
        self.write_json(self.evidence / "mechanism-trace.json", {
            "schema": "inferswarm.issue252.queue-order-observation/1",
            "before": [{"event": "vkQueueSubmit", "sequence": i} for i in (2, 1)],
            "after": [{"event": "vkQueueSubmit", "sequence": i} for i in (1, 2)]})

    def test_five_identical_rows_not_validated_without_fix(self):
        self.deterministic()
        self.trace()
        self.assertEqual(self.verdict(), C.NOT_VALIDATED_TERMINAL)

    def test_mismatch_at_unit_two_valid_variable_stop_unresolved_when_all_arms_complete(self):
        for arm in A.ARMS:
            if arm != "A1":
                self.write_json(self.evidence / f"authority-{arm}.json", self.authority(arm))
            self.variable(arm)
        self.assertEqual(self.verdict(), C.UNRESOLVED_TERMINAL)

    def test_three_identical_are_screening_only(self):
        self.deterministic(n=3)
        self.assertEqual(self.verdict(), T.BLOCKED)

    def test_gap_in_prefix_blocks(self):
        self.retain("A1", 1)
        self.retain("A1", 3, bytes([1]) * D.ROW_BYTES)
        self.assertEqual(self.verdict(), T.BLOCKED)

    def test_cherry_picked_subset_blocks(self):
        self.retain("A1", 2)
        self.retain("A1", 3, bytes([1]) * D.ROW_BYTES)
        self.assertEqual(self.verdict(), T.BLOCKED)

    def test_execution_past_first_mismatch_blocks(self):
        self.variable()
        self.retain("A1", 3, bytes([2]) * D.ROW_BYTES)
        self.assertEqual(self.verdict(), T.BLOCKED)

    def test_arm_receipt_geometry_mismatch_blocks(self):
        unit = self.retain("A1", 1)
        self.retain("A1", 2, bytes([1]) * D.ROW_BYTES)
        rec = json.loads((unit / "unit.json").read_bytes())
        rec["server_env"]["GGML_VK_SERIALIZE_SUBMISSIONS"] = "0"
        self.write_json(unit / "unit.json", rec)
        self.assertEqual(self.verdict(), T.BLOCKED)

    def test_response_and_row_byte_mutations_block(self):
        unit = self.retain("A1", 1)
        self.retain("A1", 2, bytes([1]) * D.ROW_BYTES)
        (unit / "response.json.raw").write_bytes(b"{}")
        self.assertEqual(self.verdict(), T.BLOCKED)
        # Restore response, then corrupt a full row independently.
        rec = json.loads((unit / "unit.json").read_bytes())
        (unit / "response.json.raw").write_bytes(json.dumps({"tokens": list(range(D.DECISIONS))}).encode())
        assert sha((unit / "response.json.raw").read_bytes()) == rec["response_raw_sha256"]
        (unit / "obs.row0.f32").write_bytes(b"damaged")
        self.assertEqual(self.verdict(), T.BLOCKED)

    def test_caller_boolean_cannot_decide_terminal(self):
        self.deterministic()
        self.assertEqual(T.derive_terminal(self.evidence, {"fix_implemented": True,
                         "vulkan_participation_proven": True}), T.BLOCKED)

    def test_five_identical_without_trace_cannot_localize(self):
        self.deterministic()
        self.assertEqual(self.verdict(), T.BLOCKED)

    def test_fix_commit_without_retained_dispatch_blocks(self):
        self.deterministic(); self.trace()
        self.write_json(self.evidence / "fix.json", {"commit": "f" * 40})
        self.assertEqual(self.verdict(), T.BLOCKED)

    def test_all_three_terminals_reachable_accepted_with_bound_fix(self):
        self.deterministic(); self.trace()
        # A source-code change in a clean local fixture repo supplies a Git
        # object; it proves the reducer's binding only, never a real fix.
        path = self.repo / "ggml/src/ggml-vulkan/ggml-vulkan.cpp"
        path.parent.mkdir(parents=True)
        path.write_text("int synthetic_vk_fix(void) { return 1; }\n")
        git(self.repo, "add", "ggml/src/ggml-vulkan/ggml-vulkan.cpp")
        git(self.repo, "commit", "-qm", "synthetic Vulkan code change")
        commit = git(self.repo, "rev-parse", "HEAD")
        auth = self.authority(head=commit)
        raw = json.dumps(auth, sort_keys=True).encode()
        (self.evidence / "fix-dispatch.json").write_bytes(raw)
        self.write_json(self.evidence / "fix.json", {
            "repo_root": str(self.repo), "commit": commit,
            "dispatch": auth, "authority_sha256": sha(raw)})
        for i in range(1, 6):
            self.retain("A1", i, authority=auth, namespace="fixed/" + A.ARMS["A1"]["namespace"],
                        fix_commit=commit, binary_sha256="a" * 64)
        self.assertEqual(self.verdict(), C.ACCEPTED_TERMINAL)


if __name__ == "__main__":
    unittest.main()

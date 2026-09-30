"""Retained-byte reducer CPU-only fixtures (never physical authority).

Adversarial matrix discipline: each forged-authority case mutates ONE
independent field of a wholly valid fixture, and every case is judged
through the REDUCER's derive_terminal (BLOCKED), never a helper in
isolation. The positive path first proves the valid fixture reaches a
terminal, so the rejections are not vacuous.
"""
from __future__ import annotations
import copy
import json
import unittest
from pathlib import Path

from tests.test_issue252_physical import FixtureMixin, git, sha, A, C, D, CAP
import issue252_terminal as T
import issue252_mechanism as M


MECH_A2_LOG = (
    "ggml_vulkan: Found 1 Vulkan devices:\n"
    "ggml_vulkan: 0 = NVIDIA GeForce RTX 3060 (NVIDIA) | uma: 0 | fp16: 1 | bf16: 0"
    " | fp4: 0 | warp size: 32 | shared memory: 49152 | int dot: 1 | matrix cores: none\n"
    "ggml_vulkan: memory: NVIDIA GeForce RTX 3060: +4.00 MiB device at 0x1. Total device: 4.00 MiB, total host: 0 B\n"
    "ggml_vulkan: memory: NVIDIA GeForce RTX 3060: +16.00 MiB host at 0x2. Total device: 4.00 MiB, total host: 16.00 MiB\n"
)
MECH_A3_LOG = (
    "ggml_vulkan: WARNING: Async execution disabled on certain Intel devices.\n"
    "ggml_vulkan: 0 = NVIDIA GeForce RTX 3060 (NVIDIA) | matrix cores: NV_coopmat2\n"
)
MECH_A4_LOG = (
    "ggml_vulkan: 0 = NVIDIA GeForce RTX 3060 (NVIDIA) | matrix cores: NV_coopmat2\n"
    "ggml_vulkan memory: NVIDIA GeForce RTX 3060: +4.00 MiB device at 0x1. Total device: 4.00 MiB, total host: 0 B\n"
    "ggml_vulkan memory: NVIDIA GeForce RTX 3060: +16.00 MiB host at 0x2. Total device: 4.00 MiB, total host: 16.00 MiB\n"
)
MECH_A5_LOG = (
    "ggml_vulkan: 0 = NVIDIA GeForce RTX 3060 (NVIDIA) | matrix cores: NV_coopmat2\n"
    "ggml_vulkan memory: ggml_vk_ensure_sync_staging_buffer(4096)\n"
    "ggml_vulkan memory: NVIDIA GeForce RTX 3060: +4.00 MiB device at 0x1. Total device: 4.00 MiB, total host: 0 B\n"
)
ARM_LOGS = {"A2": MECH_A2_LOG, "A3": MECH_A3_LOG, "A4": MECH_A4_LOG, "A5": MECH_A5_LOG}


class TerminalTests(FixtureMixin, unittest.TestCase):
    def setUp(self):
        self.fixture()
        self.arm = "A4"  # a terminal-capable arm with a real mechanism seam
        self.write_json(self.evidence / "authority.json", {
            "repo_root": str(self.repo),
            "dispatch_capture": self.authority("A4")})

    def verdict(self, arm=None):
        arm = arm or self.arm
        return T.derive_terminal(self.evidence, {}, fetch=self.fetcher(arm))

    def deterministic(self, arm="A4", n=5):
        for i in range(1, n + 1):
            self.retain(arm, i, server_log=ARM_LOGS[arm])

    def variable(self, arm="A4"):
        self.retain(arm, 1, server_log=ARM_LOGS[arm])
        self.retain(arm, 2, bytes([1]) * D.ROW_BYTES, server_log=ARM_LOGS[arm])

    # ---------- positive path ----------

    def test_five_identical_rows_not_validated_without_fix(self):
        self.deterministic()
        self.assertEqual(self.verdict(), C.NOT_VALIDATED_TERMINAL)

    def test_all_three_terminals_reachable_accepted_with_bound_fix(self):
        self.deterministic()
        path = self.repo / "ggml/src/ggml-vulkan/ggml-vulkan.cpp"
        path.parent.mkdir(parents=True)
        path.write_text("int synthetic_vk_fix(void) { return 1; }\n")
        git(self.repo, "add", "ggml/src/ggml-vulkan/ggml-vulkan.cpp")
        git(self.repo, "commit", "-qm", "synthetic Vulkan code change")
        commit = git(self.repo, "rev-parse", "HEAD")
        capture = self.capture("A4", head=commit)
        raw = json.dumps(capture, sort_keys=True).encode()
        (self.evidence / "fix-dispatch.json").write_bytes(raw)
        self.write_json(self.evidence / "fix.json", {
            "repo_root": str(self.repo), "commit": commit,
            "dispatch_capture": capture, "authority_sha256": sha(raw)})
        fixed_ns = "fixed/" + A.ARMS["A4"]["namespace"]
        for i in range(1, 6):
            self.retain("A4", i, authority=capture, namespace=fixed_ns,
                        fix_commit=commit, binary_sha256="a" * 64,
                        server_log=ARM_LOGS["A4"])
        self.assertEqual(
            T.derive_terminal(self.evidence, {}, fetch=self.fetcher("A4", head=commit)),
            C.ACCEPTED_TERMINAL)

    def test_mismatch_at_unit_two_variable_all_arms_complete_unresolved(self):
        for arm in A.ARMS:
            log = ARM_LOGS.get(arm, MECH_A4_LOG)
            if arm != self.arm:
                self.write_json(self.evidence / f"authority-{arm}.json",
                                {"repo_root": str(self.repo),
                                 "dispatch_capture": self.authority(arm)})
            self.retain(arm, 1, server_log=log)
            self.retain(arm, 2, bytes([1]) * D.ROW_BYTES, server_log=log)
        self.assertEqual(self.verdict(), C.UNRESOLVED_TERMINAL)

    # ---------- prefix/custody regression (retained from round 1) ----------

    def test_three_identical_are_screening_only(self):
        self.deterministic(n=3)
        self.assertEqual(self.verdict(), T.BLOCKED)

    def test_gap_in_prefix_blocks(self):
        self.retain(self.arm, 1, server_log=ARM_LOGS[self.arm])
        self.retain(self.arm, 3, bytes([1]) * D.ROW_BYTES, server_log=ARM_LOGS[self.arm])
        self.assertEqual(self.verdict(), T.BLOCKED)

    def test_cherry_picked_subset_blocks(self):
        self.retain(self.arm, 2, server_log=ARM_LOGS[self.arm])
        self.retain(self.arm, 3, bytes([1]) * D.ROW_BYTES, server_log=ARM_LOGS[self.arm])
        self.assertEqual(self.verdict(), T.BLOCKED)

    def test_execution_past_first_mismatch_blocks(self):
        self.variable()
        self.retain(self.arm, 3, bytes([2]) * D.ROW_BYTES, server_log=ARM_LOGS[self.arm])
        self.assertEqual(self.verdict(), T.BLOCKED)

    def test_arm_receipt_geometry_mismatch_blocks(self):
        unit = self.retain(self.arm, 1, server_log=ARM_LOGS[self.arm])
        self.retain(self.arm, 2, bytes([1]) * D.ROW_BYTES, server_log=ARM_LOGS[self.arm])
        rec = json.loads((unit / "unit.json").read_bytes())
        rec["server_env"][A.ARMS[self.arm]["control"]["name"]] = "0"
        self.write_json(unit / "unit.json", rec)
        self.assertEqual(self.verdict(), T.BLOCKED)

    def test_response_and_row_byte_mutations_block(self):
        unit = self.retain(self.arm, 1, server_log=ARM_LOGS[self.arm])
        self.retain(self.arm, 2, bytes([1]) * D.ROW_BYTES, server_log=ARM_LOGS[self.arm])
        (unit / "response.json.raw").write_bytes(b"{}")
        self.assertEqual(self.verdict(), T.BLOCKED)
        rec = json.loads((unit / "unit.json").read_bytes())
        (unit / "response.json.raw").write_bytes(
            json.dumps({"tokens": list(range(D.DECISIONS))}).encode())
        assert sha((unit / "response.json.raw").read_bytes()) == rec["response_raw_sha256"]
        (unit / "obs.row0.f32").write_bytes(b"damaged")
        self.assertEqual(self.verdict(), T.BLOCKED)

    def test_caller_boolean_cannot_decide_terminal(self):
        self.deterministic()
        self.assertEqual(T.derive_terminal(self.evidence, {"fix_implemented": True,
                         "vulkan_participation_proven": True}, fetch=self.fetcher()),
                         T.BLOCKED)

    def test_five_identical_without_mechanism_observations_cannot_localize(self):
        # Retained server logs lack every mechanism marker: five matching rows
        # alone must stay BLOCKED.
        for i in range(1, 6):
            self.retain(self.arm, i, server_log="no vulkan markers here\n")
        self.assertEqual(self.verdict(), T.BLOCKED)

    def test_fix_commit_without_retained_dispatch_blocks(self):
        self.deterministic()
        self.write_json(self.evidence / "fix.json", {"commit": "f" * 40})
        self.assertEqual(self.verdict(), T.BLOCKED)

    # ---------- A1 non-terminal-capable ----------

    def test_a1_deterministic_cannot_localize(self):
        for i in range(1, 6):
            self.retain("A1", i)
        self.assertEqual(self.verdict("A1"), T.BLOCKED)

    def test_a1_mechanism_status_non_capable(self):
        status = M.mechanism_status(self.evidence, "A1", A.ARMS["A1"]["namespace"])
        self.assertFalse(status["capable"])
        self.assertIn("no retained submission-serialization observable",
                      status["reason"])

    # ---------- mechanism contracts per arm ----------

    def test_a2_dead_control_on_nv_coopmat2_subject_blocks(self):
        log = ("ggml_vulkan: 0 = NVIDIA GeForce RTX 3060 (NVIDIA) | matrix cores: NV_coopmat2\n")
        for i in range(1, 6):
            self.retain("A2", i, server_log=log)
        self.write_json(self.evidence / "authority.json", {
            "repo_root": str(self.repo), "dispatch_capture": self.authority("A2")})
        self.assertEqual(self.verdict("A2"), T.BLOCKED)

    def test_a2_khr_active_blocks(self):
        log = ("ggml_vulkan: 0 = NVIDIA GeForce RTX 3060 (NVIDIA) | matrix cores: KHR_coopmat\n")
        for i in range(1, 6):
            self.retain("A2", i, server_log=log)
        self.write_json(self.evidence / "authority.json", {
            "repo_root": str(self.repo), "dispatch_capture": self.authority("A2")})
        self.assertEqual(self.verdict("A2"), T.BLOCKED)

    def test_a3_marker_missing_blocks(self):
        log = "ggml_vulkan: 0 = NVIDIA GeForce RTX 3060 (NVIDIA) | matrix cores: none\n"
        for i in range(1, 6):
            self.retain("A3", i, server_log=log)
        self.write_json(self.evidence / "authority.json", {
            "repo_root": str(self.repo), "dispatch_capture": self.authority("A3")})
        self.assertEqual(self.verdict("A3"), T.BLOCKED)

    def test_a4_no_host_allocation_blocks(self):
        log = ("ggml_vulkan: 0 = NVIDIA GeForce RTX 3060 (NVIDIA) | matrix cores: NV_coopmat2\n"
               "ggml_vulkan memory: NVIDIA GeForce RTX 3060: +4.00 MiB device at 0x1."
               " Total device: 4.00 MiB, total host: 0 B\n")
        for i in range(1, 6):
            self.retain("A4", i, server_log=log)
        self.assertEqual(self.verdict("A4"), T.BLOCKED)

    def test_a5_host_allocation_blocks(self):
        log = ("ggml_vulkan: 0 = NVIDIA GeForce RTX 3060 (NVIDIA) | matrix cores: NV_coopmat2\n"
               "ggml_vulkan memory: NVIDIA GeForce RTX 3060: +16.00 MiB host at 0x2."
               " Total device: 0 B, total host: 16.00 MiB\n"
               "ggml_vulkan memory: ggml_vk_ensure_sync_staging_buffer(4096)\n")
        for i in range(1, 6):
            self.retain("A5", i, server_log=log)
        self.write_json(self.evidence / "authority.json", {
            "repo_root": str(self.repo), "dispatch_capture": self.authority("A5")})
        self.assertEqual(self.verdict("A5"), T.BLOCKED)

    def test_a5_staging_line_missing_blocks(self):
        log = ("ggml_vulkan: 0 = NVIDIA GeForce RTX 3060 (NVIDIA) | matrix cores: NV_coopmat2\n"
               "ggml_vulkan memory: NVIDIA GeForce RTX 3060: +4.00 MiB device at 0x1."
               " Total device: 4.00 MiB, total host: 0 B\n")
        for i in range(1, 6):
            self.retain("A5", i, server_log=log)
        self.write_json(self.evidence / "authority.json", {
            "repo_root": str(self.repo), "dispatch_capture": self.authority("A5")})
        self.assertEqual(self.verdict("A5"), T.BLOCKED)

    # ---------- forged-authority adversarial matrix ----------

    def _valid_authority_file(self, arm="A4"):
        self.deterministic(arm)

    def _authority_doc(self):
        return json.loads((self.evidence / "authority.json").read_bytes())

    def _mutate_authority(self, mutate):
        doc = self._authority_doc()
        mutate(doc)
        self.write_json(self.evidence / "authority.json", doc)

    def _forged_rejected(self, mutate, arm="A4"):
        self._valid_authority_file(arm)
        self._mutate_authority(mutate)
        self.assertEqual(self.verdict(arm), T.BLOCKED)

    def test_forged_owner_member_value_rejected(self):
        # Fabricated MEMBER value, internally consistent (digest untouched:
        # the digest covers raw comment bytes, not this field).
        self._forged_rejected(
            lambda d: d["dispatch_capture"].__setitem__("author_association", "FIRST_TIMER"))

    def test_forged_comment_id_rejected(self):
        # Different comment ID: the re-fetch finds no such comment.
        self._forged_rejected(
            lambda d: d["dispatch_capture"].__setitem__("comment_id", 999999))

    def test_forged_body_with_recomputed_digest_rejected(self):
        # Competent forgery: change the body AND recompute the internal
        # digest over forged raw bytes. Still rejected: the re-fetched REAL
        # comment's canonical bytes hash differently.
        def mutate(d):
            cap = d["dispatch_capture"]
            forged_comment = dict(self.comment(cap["arm"], cap["head_sha"]))
            forged_comment["body"] = (
                f"{C.DISPATCH_PHRASE_FORMAT}\nhead={cap['head_sha']}\narm=A2")
            cap["body"] = forged_comment["body"]
            cap["arm"] = "A2"
            cap["namespace"] = A.ARMS["A2"]["namespace"]
            cap["raw_comment_sha256"] = sha(CAP.canonical_bytes(forged_comment))
        self._forged_rejected(mutate)

    def test_issue252_comment_substituted_for_pr_comment_rejected(self):
        # Comment whose issue_url targets ISSUE 252, not the PR conversation.
        def mutate(d):
            cap = d["dispatch_capture"]
            forged = dict(self.comment(cap["arm"], cap["head_sha"]))
            forged["issue_url"] = (
                "https://api.github.com/repos/Zutfen-LLC/inferswarm/issues/252")
            forged["html_url"] = (
                "https://github.com/Zutfen-LLC/inferswarm/issues/252#issuecomment-12")
            cap["raw_comment_sha256"] = sha(CAP.canonical_bytes(forged))
        self._forged_rejected(mutate)

    def test_wrong_repository_rejected(self):
        def mutate(d):
            cap = d["dispatch_capture"]
            forged = dict(self.comment(cap["arm"], cap["head_sha"]))
            forged["issue_url"] = (
                "https://api.github.com/repos/evil/org/issues/253")
            forged["html_url"] = (
                "https://github.com/evil/org/pull/253#issuecomment-12")
            cap["raw_comment_sha256"] = sha(CAP.canonical_bytes(forged))
        self._forged_rejected(mutate)

    def test_wrong_pr_rejected(self):
        def mutate(d):
            cap = d["dispatch_capture"]
            forged = dict(self.comment(cap["arm"], cap["head_sha"]))
            forged["issue_url"] = (
                "https://api.github.com/repos/Zutfen-LLC/inferswarm/issues/999")
            forged["html_url"] = (
                "https://github.com/Zutfen-LLC/inferswarm/pull/999#issuecomment-12")
            cap["pr_number"] = 999
            cap["raw_comment_sha256"] = sha(CAP.canonical_bytes(forged))
        self._forged_rejected(mutate)

    def test_wrong_head_rejected(self):
        self._forged_rejected(
            lambda d: d["dispatch_capture"].__setitem__("head_sha", "e" * 40))

    def test_moved_head_capture_rejected(self):
        # Capture bound to a different (stale/advanced) head than the retained
        # units' receipts authenticate against.
        def mutate(d):
            cap = d["dispatch_capture"]
            forged = dict(self.comment(cap["arm"], "f" * 40))
            cap["head_sha"] = "f" * 40
            cap["body"] = forged["body"]
            cap["raw_comment_sha256"] = sha(CAP.canonical_bytes(forged))
        self._forged_rejected(mutate)

    def test_altered_retained_raw_comment_bytes_rejected(self):
        # The fetcher serves the REAL comment; the retained capture's digest
        # was recomputed over ALTERED raw bytes: byte inequality rejects.
        def mutate(d):
            cap = d["dispatch_capture"]
            forged = dict(self.comment(cap["arm"], cap["head_sha"]))
            forged["created_at"] = "2020-01-01T00:00:00Z"
            cap["raw_comment_sha256"] = sha(CAP.canonical_bytes(forged))
        self._forged_rejected(mutate)

    def test_locally_generated_self_consistent_authority_object_rejected(self):
        # A caller-constructed dict with every field internally consistent
        # (including recomputed digests and execution-time state) but whose
        # comment_id has no real GitHub comment behind it.
        def mutate(d):
            cap = d["dispatch_capture"]
            forged = dict(self.comment(cap["arm"], cap["head_sha"]))
            forged["id"] = 424242
            forged["html_url"] = (f"https://github.com/Zutfen-LLC/inferswarm/pull/"
                                  f"{C.CAMPAIGN_PR}#issuecomment-424242")
            cap["comment_id"] = 424242
            cap["raw_comment_sha256"] = sha(CAP.canonical_bytes(forged))
        self._forged_rejected(mutate)

    def test_legacy_self_consistent_dispatch_dict_rejected(self):
        # The OLD round-1 authority shape (body_sha256 field, no capture
        # schema, no re-fetch binding) must be refused outright.
        def mutate(d):
            cap = d["dispatch_capture"]
            d["dispatch_capture"] = {
                "head_sha": cap["head_sha"], "arm": cap["arm"],
                "namespace": cap["namespace"], "comment_id": 12,
                "body": cap["body"], "body_sha256": sha(cap["body"].encode()),
                "author_association": "OWNER", "issue_number": C.ISSUE,
                "pr_number": C.CAMPAIGN_PR,
                "parent_terminalization_head": C.ACCEPTED_TERMINALIZATION_HEAD}
        self._forged_rejected(mutate)

    def test_fetcher_serving_forged_comment_rejected(self):
        # Even a fetcher that serves a matching forged comment is rejected
        # when the forged comment violates the immutable comment law (a
        # CONTRIBUTOR association cannot be authority regardless of bytes).
        self._valid_authority_file()
        real = self.comment(self.arm)

        def forged_fetch(url):
            served = dict(real)
            served["author_association"] = "CONTRIBUTOR"
            return served
        self.assertEqual(T.derive_terminal(self.evidence, {}, fetch=forged_fetch),
                         T.BLOCKED)

    def test_authentic_synthetic_authority_fixture_succeeds(self):
        # Positive control for the whole matrix: the unmutated capture built
        # from the same authority factory as the receipts localizes.
        self.deterministic()
        self.assertEqual(self.verdict(), C.NOT_VALIDATED_TERMINAL)


if __name__ == "__main__":
    unittest.main()

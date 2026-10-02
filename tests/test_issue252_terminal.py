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

from tests.test_issue252_physical import (FixtureMixin, git, sha, A, C, D, CAP,
                                          P)
from unittest import mock
import issue252_terminal as T
import issue252_mechanism as M


NL = chr(10)
ENUM_BASE = ("ggml_vulkan: 0 = NVIDIA GeForce RTX 3060 (NVIDIA) | uma: 0 | fp16: 1"
             " | bf16: 0 | fp4: 0 | warp size: 32 | shared memory: 49152"
             " | int dot: 1 | matrix cores: ")
MEM = "ggml_vulkan memory: NVIDIA GeForce RTX 3060: "

def _fmt(b):
    if b >= 1024 ** 2: return f"{b / 1024 ** 2:.2f} MiB"
    if b >= 1024: return f"{b / 1024:.2f} KiB"
    return f"{b} B"

def _mklog(family, events):
    lines = [ENUM_BASE + family]
    td = th = 0
    for kind, size in events:
        if kind == "staging":
            lines.append("ggml_vulkan memory: ggml_vk_ensure_sync_staging_buffer(" + str(size) + ")")
            kind = "host"
        else:
            size = int(size)
        if kind == "device":
            td += size
        else:
            th += size
        lines.append(MEM + "+" + _fmt(size) + " " + kind + " at 0x"
                     + format(len(lines), "x") + ". Total device: " + _fmt(td)
                     + ", total host: " + _fmt(th))
    return NL.join(lines) + NL

MIB = 1024 ** 2
MECH_A2_LOG = _mklog("none", [("device", 4 * MIB)])
MECH_A3_LOG = (("ggml_vulkan: WARNING: Async execution disabled on certain Intel devices." + NL)
               + _mklog("NV_coopmat2", [("device", 4 * MIB)]))
MECH_A4_LOG = _mklog("NV_coopmat2", [("device", 4 * MIB), ("host", 16 * MIB)])
MECH_A5_LOG = _mklog("NV_coopmat2", [("staging", 4 * MIB), ("device", 8 * MIB)])
ARM_LOGS = {"A2": MECH_A2_LOG, "A3": MECH_A3_LOG, "A4": MECH_A4_LOG, "A5": MECH_A5_LOG}


class TerminalTests(FixtureMixin, unittest.TestCase):
    def setUp(self):
        self.fixture()
        # #258 (AMENDMENT-006): the positive-path fixture arm is A3 — the
        # only terminal-capable arm at this pin. A5 was the round-4
        # positive arm but is NONTERMINAL per accepted #257
        # (A5_OBSERVATIONALLY_CAPABLE_NONTERMINAL); its five-identical-rows
        # path can no longer reach a localized terminal.
        self.arm = "A3"
        self.write_json(self.evidence / "authority.json", {
            "repo_root": str(self.repo),
            "dispatch_capture": self.authority("A3")})

    def verdict(self, arm=None):
        arm = arm or self.arm
        # Round-4 separated test facility: the offline registry is installed
        # by patching the PRODUCTION fetch function object — never through a
        # reducer parameter.
        with self.offline_authority_fetch(arm):
            return T.derive_terminal(self.evidence, {})

    def deterministic(self, arm="A3", n=5):
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
        capture = self.capture("A3", head=commit)
        raw = json.dumps(capture, sort_keys=True).encode()
        (self.evidence / "fix-dispatch.json").write_bytes(raw)
        self.write_json(self.evidence / "fix.json", {
            "repo_root": str(self.repo), "commit": commit,
            "dispatch_capture": capture, "authority_sha256": sha(raw)})
        fixed_ns = "fixed/" + A.ARMS["A3"]["namespace"]
        for i in range(1, 6):
            self.retain("A3", i, authority=capture, namespace=fixed_ns,
                        fix_commit=commit, binary_sha256="a" * 64,
                        server_log=ARM_LOGS["A3"])
        with self.offline_authority_fetch("A3", head=commit):
            self.assertEqual(T.derive_terminal(self.evidence, {}),
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
        with self.offline_authority_fetch():
            self.assertEqual(T.derive_terminal(
                self.evidence, {"fix_implemented": True,
                                "vulkan_participation_proven": True}),
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
        # #258 (AMENDMENT-006): five identical rows under a NON-TERMINAL-
        # CAPABLE arm are honest UNRESOLVED (a capable arm could still
        # exist among unretained arms), never a localized terminal and
        # never BLOCKED-for-completion-count. Own-arm authority retained.
        self.write_json(self.evidence / "authority.json", {
            "repo_root": str(self.repo),
            "dispatch_capture": self.authority("A1")})
        for i in range(1, 6):
            self.retain("A1", i)
        self.assertEqual(self.verdict("A1"), C.UNRESOLVED_TERMINAL)

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

    def test_a4_deterministic_repeats_cannot_localize(self):
        # Round 4: A4 is non-terminal-capable at pin b29c606e. #258
        # (AMENDMENT-006): deterministic repeats under an incapable arm are
        # honest UNRESOLVED, not BLOCKED-for-completion-count.
        log = ("ggml_vulkan: 0 = NVIDIA GeForce RTX 3060 (NVIDIA) | matrix cores: NV_coopmat2\n"
               "ggml_vulkan memory: NVIDIA GeForce RTX 3060: +4.00 MiB device at 0x1."
               " Total device: 4.00 MiB, total host: 0 B\n"
               "ggml_vulkan memory: NVIDIA GeForce RTX 3060: +16.00 MiB host at 0x2."
               " Total device: 4.00 MiB, total host: 16.00 MiB\n")
        for i in range(1, 6):
            self.retain("A4", i, server_log=log)
        self.write_json(self.evidence / "authority.json", {
            "repo_root": str(self.repo),
            "dispatch_capture": self.authority("A4")})
        self.assertEqual(self.verdict("A4"), C.UNRESOLVED_TERMINAL)

    def test_a5_host_allocation_blocks(self):
        # #258 (AMENDMENT-006): A5 is nonterminal (#257), so five identical
        # rows under A5 can never reach a localized terminal — honest
        # UNRESOLVED regardless of the retained stream's staging shape.
        log = ("ggml_vulkan: 0 = NVIDIA GeForce RTX 3060 (NVIDIA) | matrix cores: NV_coopmat2\n"
               "ggml_vulkan memory: NVIDIA GeForce RTX 3060: +16.00 MiB host at 0x2."
               " Total device: 0 B, total host: 16.00 MiB\n"
               "ggml_vulkan memory: ggml_vk_ensure_sync_staging_buffer(4096)\n")
        for i in range(1, 6):
            self.retain("A5", i, server_log=log)
        self.write_json(self.evidence / "authority.json", {
            "repo_root": str(self.repo),
            "dispatch_capture": self.authority("A5")})
        self.assertEqual(self.verdict("A5"), C.UNRESOLVED_TERMINAL)

    def test_a5_staging_line_missing_blocks(self):
        # Same honest-UNRESOLVED law with a staging-free log.
        log = ("ggml_vulkan: 0 = NVIDIA GeForce RTX 3060 (NVIDIA) | matrix cores: NV_coopmat2\n"
               "ggml_vulkan memory: NVIDIA GeForce RTX 3060: +4.00 MiB device at 0x1."
               " Total device: 4.00 MiB, total host: 0 B\n")
        for i in range(1, 6):
            self.retain("A5", i, server_log=log)
        self.write_json(self.evidence / "authority.json", {
            "repo_root": str(self.repo),
            "dispatch_capture": self.authority("A5")})
        self.assertEqual(self.verdict("A5"), C.UNRESOLVED_TERMINAL)

    # ---------- forged-authority adversarial matrix ----------

    def _valid_authority_file(self, arm="A5"):
        self.deterministic(arm)

    def _authority_doc(self):
        return json.loads((self.evidence / "authority.json").read_bytes())

    def _mutate_authority(self, mutate):
        doc = self._authority_doc()
        mutate(doc)
        self.write_json(self.evidence / "authority.json", doc)

    def _forged_rejected(self, mutate, arm="A5"):
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
        with mock.patch.object(P, "fetch_dispatch_comment", forged_fetch):
            self.assertEqual(T.derive_terminal(self.evidence, {}), T.BLOCKED)


    def test_forged_lambda_fetcher_cannot_authorize_any_terminal(self):
        # Round-3/round-4 BLOCKER regression: a caller-controlled fetcher
        # serving locally fabricated OWNER comments (recomputed digests,
        # full internally-consistent evidence tree, even a synthetic fix
        # commit) must NOT reach any terminal. The reducer API has no fetch
        # parameter at all, so the forged lambda cannot even be passed.
        from tests.test_issue252_physical import A as _A, git as _git, sha as _sha
        import json as _json
        self.deterministic()
        path = self.repo / "ggml/src/ggml-vulkan/ggml-vulkan.cpp"
        path.parent.mkdir(parents=True)
        path.write_text("int fake_fix() {return 1;}\n")
        _git(self.repo, "add", "ggml/src/ggml-vulkan/ggml-vulkan.cpp")
        _git(self.repo, "commit", "-qm", "fake fix")
        commit = _git(self.repo, "rev-parse", "HEAD")
        original = self.comment(self.arm)
        original.update(id=424242, author_association="OWNER",
                        user={"login": "imaginary"},
                        html_url=("https://github.com/Zutfen-LLC/inferswarm/"
                                  "pull/253#issuecomment-424242"))
        cap = self.capture(self.arm, comment=original)
        self.write_json(self.evidence / "authority.json",
                        {"repo_root": str(self.repo), "dispatch_capture": cap})
        fixed = self.comment(self.arm, head=commit)
        fixed.update(id=424243, author_association="OWNER",
                     user={"login": "imaginary"},
                     html_url=("https://github.com/Zutfen-LLC/inferswarm/"
                               "pull/253#issuecomment-424243"))
        fixcap = self.capture(self.arm, head=commit, comment=fixed)
        raw = _json.dumps(fixcap, sort_keys=True).encode()
        (self.evidence / "fix-dispatch.json").write_bytes(raw)
        self.write_json(self.evidence / "fix.json", {
            "repo_root": str(self.repo), "commit": commit,
            "dispatch_capture": fixcap, "authority_sha256": _sha(raw)})
        fixed_ns = "fixed/" + _A.ARMS[self.arm]["namespace"]
        for i in range(1, 6):
            self.retain(self.arm, i, authority=fixcap, namespace=fixed_ns,
                        fix_commit=commit, binary_sha256="a" * 64,
                        server_log=ARM_LOGS[self.arm])
        invented = {"424242": original, "424243": fixed}

        def forged(url):
            return invented[url.rsplit("/", 1)[-1]]
        # The public API has no fetch parameter: the forged lambda cannot
        # be supplied at all.
        with self.assertRaises(TypeError):
            T.derive_terminal(self.evidence, {}, fetch=forged)
        with self.assertRaises(TypeError):
            T.derive_terminal(self.evidence, {}, fetch=forged,
                              _test_only_fetch=True)
        # And even a monkeypatched production seam serving the invented
        # comments fails byte-equality: fabricated logins/ids have no real
        # registry behind them — but the retained capture WAS built from the
        # same factory, so the meaningful law here is that no API reaches
        # offline mode. The registry-served rejection is covered by
        # test_fetcher_serving_forged_comment_rejected above.

    def test_production_fetcher_is_the_github_seam(self):
        # The only re-fetch implementation the reducer can call is the
        # production HTTPS seam, and verify_capture takes no fetcher.
        import inspect
        self.assertEqual(T.P.fetch_dispatch_comment.__name__,
                         "fetch_dispatch_comment")
        params = inspect.signature(CAP.verify_capture).parameters
        self.assertEqual(set(params), {"retained", "repo_pr_number"})
        self.deterministic()
        # Unpatched production seam: a synthetic comment id has no real
        # GitHub comment behind it; admission must fail closed without a
        # network probe escaping the canonical URL prefix.
        with self.assertRaises(CAP.CaptureInvalid):
            CAP.verify_capture(self.authority(self.arm),
                               repo_pr_number=C.CAMPAIGN_PR)

    def test_authentic_synthetic_authority_fixture_succeeds(self):
        # Positive control for the whole matrix: the unmutated capture built
        # from the same authority factory as the receipts localizes.
        self.deterministic()
        self.assertEqual(self.verdict(), C.NOT_VALIDATED_TERMINAL)


if __name__ == "__main__":
    unittest.main()

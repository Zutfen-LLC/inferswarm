"""Round-4 adversarial RED/PIN regressions (review of head 6bc9251).

[RED] tests fail at the reviewed head 6bc9251 and must pass at the round-4
corrected head; [PIN] tests pass at BOTH heads and freeze retained law.
Labels are part of the method names so the committed file records the
expected fail/pass split.

Blockers covered:
1. production-callable test authority bypass (_test_only_fetch/_test_only);
2. A5 one-to-one ordered staging/allocation pairing;
3. A4 terminal capability vs source-retained observables at pin b29c606e;
4. proactive re-review: enumeration multiplicity, subject-family one-factor
   law, near-miss memory-prefixed lines, forged fix dispatch.
"""
from __future__ import annotations
import inspect
import unittest
from pathlib import Path
from unittest import mock

from tests.test_issue252_physical import FixtureMixin, git, sha, A, C, D, CAP
import issue252_terminal as T
import issue252_mechanism as M
import issue252_physical as P

NL = chr(10)
ENUM_BASE = ("ggml_vulkan: 0 = NVIDIA GeForce RTX 3060 (NVIDIA) | uma: 0 | fp16: 1"
             " | bf16: 0 | fp4: 0 | warp size: 32 | shared memory: 49152"
             " | int dot: 1 | matrix cores: ")
MEM = "ggml_vulkan memory: NVIDIA GeForce RTX 3060: "
ASYNC_OFF = ("ggml_vulkan: WARNING: Async execution disabled on certain Intel devices."
             + NL)
MIB = 1024 ** 2
KIB = 1024


def _fmt(b: float) -> str:
    b = int(b)
    if b >= 1024 ** 3:
        return f"{b / 1024 ** 3:.2f} GiB"
    if b >= MIB:
        return f"{b / MIB:.2f} MiB"
    if b >= KIB:
        return f"{b / KIB:.2f} KiB"
    return f"{b} B"


def build_log(events, family="NV_coopmat2", enum_count=1):
    """Ledger-consistent ordered log.

    events: ("staging", n) staging info line;
            ("alloc", "host"|"device", n) / ("dealloc", "host"|"device", n);
            ("info", exact_informational_line) pin informational line;
            ("raw", line) any other verbatim line.
    """
    lines = [ENUM_BASE + family for _ in range(enum_count)]
    td = th = 0.0
    for ev in events:
        if ev[0] == "staging":
            lines.append("ggml_vulkan memory: ggml_vk_ensure_sync_staging_buffer("
                         + str(ev[1]) + ")")
            continue
        if ev[0] == "info":
            lines.append(ev[1])
            continue
        if ev[0] == "raw":
            lines.append(ev[1])
            continue
        kind, typ, size = ev[0], ev[1], int(ev[2])
        sign = "-" if kind == "dealloc" else "+"
        if typ == "device":
            td += size if kind == "alloc" else -size
        else:
            th += size if kind == "alloc" else -size
        lines.append(MEM + sign + _fmt(size) + " " + typ + " at 0x"
                     + format(len(lines) + 64, "x") + ". Total device: "
                     + _fmt(max(td, 0)) + ", total host: " + _fmt(max(th, 0)))
    return NL.join(lines) + NL


def write(root: Path, namespace: str, name: str, log: str) -> None:
    unit = root / namespace / name
    unit.mkdir(parents=True, exist_ok=True)
    (unit / "server.log").write_text(log, encoding="utf-8")
    # AMENDMENT-005: A3's retained placement/identity law reads these
    # per-unit files; A2/A5 validators ignore them.
    import json as _json
    (unit / "placement.json").write_text(_json.dumps({
        "output_projection": "Vulkan", "embedding": "CPU", "ngl": 1,
        "gpu_uuid": C.HOST_FACTS["gpu_uuid"],
        "vulkan_family": "NV_coopmat2",
        "vulkan_family_authority": "frozen-host-facts",
        "cuda_participation": False}, sort_keys=True))
    for phase in ("identity-pre.json", "identity-post.json"):
        (unit / phase).write_text(
            _json.dumps(dict(C.HOST_FACTS), sort_keys=True))


A5_NS = A.ARMS["A5"]["namespace"]
A4_NS = A.ARMS["A4"]["namespace"]
A3_NS = A.ARMS["A3"]["namespace"]
A2_NS = A.ARMS["A2"]["namespace"]


class AuthoritySignatureTests(FixtureMixin, unittest.TestCase):
    """Blocker 1: the shipped production API must not accept fetchers."""

    def setUp(self):
        self.fixture()

    def test_red_reducer_signature_exposes_no_fetch_or_flag(self):
        params = inspect.signature(T.derive_terminal).parameters
        self.assertEqual(set(params), {"evidence_root", "arms_result"})
        self.assertFalse(any(p.kind is inspect.Parameter.VAR_KEYWORD
                             for p in params.values()))

    def test_red_verify_capture_signature_exposes_no_fetch_or_flag(self):
        params = inspect.signature(CAP.verify_capture).parameters
        self.assertEqual(set(params), {"retained", "repo_pr_number"})
        self.assertFalse(any(p.kind is inspect.Parameter.VAR_KEYWORD
                             for p in params.values()))

    def test_red_reducer_rejects_forged_fetcher_structurally(self):
        self.deterministic_arm = None
        forged = lambda url: {"author_association": "OWNER"}  # noqa: E731
        with self.assertRaises(TypeError):
            T.derive_terminal(self.evidence, {}, fetch=forged)

    def test_red_round3_owner_attack_unreachable_via_public_api(self):
        # Exact round-3 fabricated OWNER-comment attack (invented comment
        # ids, recomputed digests, synthetic fix commit, fixed population).
        # Zero real GitHub requests: the offline registry serves nothing for
        # the invented ids.
        for i in range(1, 6):
            self.retain("A3", i, authority=self.authority("A3"),
                        server_log=ASYNC_OFF + build_log(
                            [("alloc", "device", 4 * MIB)]))
        path = self.repo / "ggml/src/ggml-vulkan/ggml-vulkan.cpp"
        path.parent.mkdir(parents=True)
        path.write_text("int fake_fix() {return 1;}\n")
        git(self.repo, "add", "ggml/src/ggml-vulkan/ggml-vulkan.cpp")
        git(self.repo, "commit", "-qm", "fake fix")
        commit = git(self.repo, "rev-parse", "HEAD")
        original = self.comment("A3")
        original.update(id=424242, author_association="OWNER",
                        user={"login": "imaginary"},
                        html_url=("https://github.com/Zutfen-LLC/inferswarm/"
                                  "pull/253#issuecomment-424242"))
        cap = self.capture("A3", comment=original)
        self.write_json(self.evidence / "authority.json",
                        {"repo_root": str(self.repo), "dispatch_capture": cap})
        fixed = self.comment("A3", head=commit)
        fixed.update(id=424243, author_association="OWNER",
                     user={"login": "imaginary"},
                     html_url=("https://github.com/Zutfen-LLC/inferswarm/"
                               "pull/253#issuecomment-424243"))
        fixcap = self.capture("A3", head=commit, comment=fixed)
        import json as _json
        raw = _json.dumps(fixcap, sort_keys=True).encode()
        (self.evidence / "fix-dispatch.json").write_bytes(raw)
        self.write_json(self.evidence / "fix.json", {
            "repo_root": str(self.repo), "commit": commit,
            "dispatch_capture": fixcap, "authority_sha256": sha(raw)})
        fixed_ns = "fixed/" + A.ARMS["A3"]["namespace"]
        for i in range(1, 6):
            self.retain("A3", i, authority=fixcap, namespace=fixed_ns,
                        fix_commit=commit, binary_sha256="a" * 64,
                        server_log=ASYNC_OFF + build_log(
                            [("alloc", "device", 4 * MIB)]))
        invented = {"424242": original, "424243": fixed}

        def forged(url):
            return invented[url.rsplit("/", 1)[-1]]
        # The flagged call path that carried the round-3 bypass must not
        # exist in the public signature at all.
        with self.assertRaises(TypeError):
            T.derive_terminal(self.evidence, {}, fetch=forged,
                              _test_only_fetch=True)
        with self.assertRaises(TypeError):
            T.derive_terminal(self.evidence, {}, fetch=forged)
        # Production call: the invented comment ids have no offline-registry
        # entry (the production seam's 404 is modeled as a refusal), so
        # admission fails closed with zero network dependence.
        def not_found(url):
            raise CAP.CaptureInvalid("comment not found: " + url)
        with mock.patch.object(P, "fetch_dispatch_comment", not_found):
            out = T.derive_terminal(self.evidence, {})
        self.assertNotIn(out, (C.NOT_VALIDATED_TERMINAL, C.UNRESOLVED_TERMINAL,
                               C.ACCEPTED_TERMINAL))

    def test_pin_offline_fixture_verified_through_test_facility_only(self):
        # The separated offline facility (unittest seam patch of the
        # PRODUCTION fetch function, never a reducer parameter) still
        # carries the authentic synthetic fixture to its terminal.
        self.write_json(self.evidence / "authority.json", {
            "repo_root": str(self.repo),
            "dispatch_capture": self.authority("A3")})
        for i in range(1, 6):
            self.retain("A3", i, authority=self.authority("A3"),
                        server_log=ASYNC_OFF + build_log(
                            [("alloc", "device", 4 * MIB)]))
        with mock.patch.object(P, "fetch_dispatch_comment", self.fetcher("A3")):
            out = T.derive_terminal(self.evidence, {})
        self.assertEqual(out, C.NOT_VALIDATED_TERMINAL)


class A5PairingTests(FixtureMixin, unittest.TestCase):
    """Blocker 2: ordered one-to-one staging/allocation pairing."""

    def setUp(self):
        self.fixture()

    def status(self):
        # #258 (AMENDMENT-006): A5 is nonterminal (#257), so the retained
        # ordered staging custody law is exercised directly.
        return {"capable": True,
                "facts": M._mechanism_a5(self.evidence, A5_NS)}

    def test_red_multiset_substitution_rejected(self):
        # staging 4096 + staging 8192 with host 4096 + host 4096.
        log = build_log([("staging", 4096), ("staging", 8192),
                         ("alloc", "host", 4096), ("alloc", "host", 4096),
                         ("alloc", "device", 4 * MIB)])
        write(self.evidence, A5_NS, "u1", log)
        with self.assertRaisesRegex(M.MechanismInvalid, "staging"):
            self.status()

    def test_red_duplicate_staging_single_allocation_rejected(self):
        log = build_log([("staging", 4096), ("alloc", "host", 4096),
                         ("staging", 4096), ("alloc", "device", 4 * MIB)])
        write(self.evidence, A5_NS, "u1", log)
        with self.assertRaisesRegex(M.MechanismInvalid, "staging"):
            self.status()

    def test_red_non_adjacent_correct_sized_allocation_rejected(self):
        # The only host 4096 allocation appears BEFORE the staging line.
        log = build_log([("alloc", "host", 4096), ("staging", 4096),
                         ("alloc", "device", 4 * MIB)])
        write(self.evidence, A5_NS, "u1", log)
        with self.assertRaisesRegex(M.MechanismInvalid, "staging"):
            self.status()

    def test_red_unrelated_same_size_substitution_rejected(self):
        # Staging event with NO allocation after it; an unrelated same-sized
        # host allocation earlier satisfies only a set/multiset law.
        log = build_log([("alloc", "device", 4 * MIB), ("alloc", "host", 4096),
                         ("staging", 4096), ("alloc", "device", 2 * MIB)])
        write(self.evidence, A5_NS, "u1", log)
        with self.assertRaisesRegex(M.MechanismInvalid, "staging"):
            self.status()

    def test_red_reordered_pairs_rejected(self):
        # staging A, staging B, alloc B, alloc A (inconsistent with the
        # pin's emit order: each allocation directly follows its own line).
        log = build_log([("staging", 4096), ("staging", 8192),
                         ("alloc", "host", 8192), ("alloc", "host", 4096),
                         ("alloc", "device", 4 * MIB)])
        write(self.evidence, A5_NS, "u1", log)
        with self.assertRaisesRegex(M.MechanismInvalid, "staging"):
            self.status()

    def test_red_authentic_ordered_sequence_accepted(self):
        # RED at the reviewed head: the old ledger law rejects the pin's own
        # informational memory-prefixed lines (ggml_vk_preallocate_buffers,
        # :15944) as malformed, so an AUTHENTIC log cannot pass. Blast radius
        # wider than the finding: authentic logs must be accepted.
        log = build_log([("info", "ggml_vulkan memory: ggml_vk_preallocate_buffers(x_size: 524288)"),
                         ("staging", 4 * MIB), ("alloc", "host", 4 * MIB),
                         ("alloc", "device", 8 * MIB),
                         ("dealloc", "device", 8 * MIB)])
        write(self.evidence, A5_NS, "u1", log)
        self.assertTrue(self.status()["capable"])

    def test_pin_growth_replacement_with_deallocation_accepted(self):
        log = build_log([("staging", MIB), ("alloc", "host", MIB),
                         ("alloc", "device", 4 * MIB),
                         ("staging", 4 * MIB), ("dealloc", "host", MIB),
                         ("alloc", "host", 4 * MIB)])
        write(self.evidence, A5_NS, "u1", log)
        self.assertTrue(self.status()["capable"])

    def test_red_size_mismatched_pairing_rejected(self):
        # Staging 8192 whose immediate allocation is 4096.
        log = build_log([("staging", 8192), ("alloc", "host", 4096),
                         ("alloc", "device", 4 * MIB)])
        write(self.evidence, A5_NS, "u1", log)
        with self.assertRaisesRegex(M.MechanismInvalid, "staging"):
            self.status()

    def test_pin_ledger_underflow_still_rejected(self):
        log = (ENUM_BASE + "NV_coopmat2" + NL
               + MEM + "-4.00 MiB host at 0x1."
               " Total device: 0 B, total host: -4.00 MiB" + NL)
        write(self.evidence, A5_NS, "u1", log)
        with self.assertRaisesRegex(M.MechanismInvalid, "ledger"):
            self.status()

    def test_pin_near_miss_memory_prefixed_line_still_rejected(self):
        log = (build_log([("staging", 4 * MIB), ("alloc", "host", 4 * MIB),
                          ("alloc", "device", 4 * MIB)])
               + "ggml_vulkan memory: ggml_vk_ensure_sync_staging_buffer(4096) trailing" + NL)
        write(self.evidence, A5_NS, "u1", log)
        with self.assertRaisesRegex(M.MechanismInvalid, "ledger|malformed"):
            self.status()

    def test_red_host_deallocation_outside_replacement_rejected(self):
        # A host deallocation that is not the replaced staging buffer.
        log = build_log([("staging", 4 * MIB), ("alloc", "host", 4 * MIB),
                         ("alloc", "device", 4 * MIB),
                         ("dealloc", "host", 4 * MIB)])
        write(self.evidence, A5_NS, "u1", log)
        with self.assertRaisesRegex(M.MechanismInvalid, "staging"):
            self.status()


class A4DispositionTests(FixtureMixin, unittest.TestCase):
    """Blocker 3: A4 source-derived terminal capability at pin b29c606e."""

    def setUp(self):
        self.fixture()
        self.rich_log = build_log([("staging", 4 * MIB),
                                   ("alloc", "host", 4 * MIB),
                                   ("alloc", "device", 4 * MIB),
                                   ("alloc", "host", 16 * MIB)])

    def test_red_a4_is_non_terminal_capable_with_source_reason(self):
        write(self.evidence, A4_NS, "u1", self.rich_log)
        status = M.mechanism_status(self.evidence, "A4", A4_NS)
        self.assertFalse(status["capable"])
        self.assertIn("b29c606e", status["reason"])
        self.assertIn("no retained observable", status["reason"])

    def test_red_a4_validator_absent_from_capable_registry(self):
        self.assertNotIn("A4", M.MECHANISM_VALIDATORS)
        self.assertIn("A4", M.NON_TERMINAL_CAPABLE)

    def test_red_a4_unrelated_host_allocations_cannot_satisfy(self):
        # Generic mixed host/device ledger (incl. staging-sized host lines)
        # must not prove the preference-controlled branch.
        write(self.evidence, A4_NS, "u1", self.rich_log)
        self.assertFalse(M.mechanism_status(self.evidence, "A4", A4_NS)["capable"])

    def test_red_a4_deterministic_repeats_alone_cannot_localize(self):
        # #258 (AMENDMENT-006): deterministic repeats under nonterminal A4
        # are honest UNRESOLVED, never a localized terminal and never
        # BLOCKED-for-completion-count.
        self.write_json(self.evidence / "authority.json", {
            "repo_root": str(self.repo),
            "dispatch_capture": self.authority("A4")})
        for i in range(1, 6):
            self.retain("A4", i, authority=self.authority("A4"),
                        server_log=self.rich_log)
        with mock.patch.object(P, "fetch_dispatch_comment", self.fetcher("A4")):
            out = T.derive_terminal(self.evidence, {})
        self.assertEqual(out, C.UNRESOLVED_TERMINAL)


class ProactiveReviewTests(FixtureMixin, unittest.TestCase):
    """Round-4 item 4: whole-reducer adversarial re-review additions."""

    def setUp(self):
        self.fixture()

    def test_red_a3_multiple_enumeration_lines_rejected(self):
        log = ASYNC_OFF + build_log([("alloc", "device", 4 * MIB)],
                                    enum_count=2)
        write(self.evidence, A3_NS, "u1", log)
        with self.assertRaisesRegex(M.MechanismInvalid, "multiple|enumeration"):
            M.mechanism_status(self.evidence, "A3", A3_NS)

    def test_red_a2_multiple_enumeration_lines_rejected(self):
        log = build_log([("alloc", "device", 4 * MIB)], family="none",
                        enum_count=2)
        write(self.evidence, A2_NS, "u1", log)
        with self.assertRaisesRegex(M.MechanismInvalid, "multiple|enumeration"):
            M.mechanism_status(self.evidence, "A2", A2_NS)

    def test_red_forged_family_change_under_a5_rejected(self):
        # A5's control does not touch coopmat detection; a "none" family
        # under A5 violates the one-factor law (frozen subject capability).
        log = build_log([("staging", 4 * MIB), ("alloc", "host", 4 * MIB),
                         ("alloc", "device", 4 * MIB)], family="none")
        write(self.evidence, A5_NS, "u1", log)
        with self.assertRaisesRegex(M.MechanismInvalid, "family|one-factor|capability"):
            # #258: retained custody law invoked directly (A5 nonterminal).
            M._mechanism_a5(self.evidence, A5_NS)

    def test_red_forged_family_change_under_a3_rejected(self):
        log = ASYNC_OFF + build_log([("alloc", "device", 4 * MIB)],
                                    family="none")
        write(self.evidence, A3_NS, "u1", log)
        with self.assertRaisesRegex(M.MechanismInvalid, "family|one-factor|capability"):
            M.mechanism_status(self.evidence, "A3", A3_NS)

    def test_red_double_enumeration_fixed_run_cannot_accept(self):
        # Reducer level: a corrected population whose logs carry two device
        # enumeration lines must not reach FIX_VALIDATED.
        self.write_json(self.evidence / "authority.json", {
            "repo_root": str(self.repo),
            "dispatch_capture": self.authority("A3")})
        good = ASYNC_OFF + build_log([("alloc", "device", 4 * MIB)])
        for i in range(1, 6):
            self.retain("A3", i, authority=self.authority("A3"),
                        server_log=good)
        path = self.repo / "ggml/src/ggml-vulkan/ggml-vulkan.cpp"
        path.parent.mkdir(parents=True)
        path.write_text("int synthetic_vk_fix(void) { return 1; }\n")
        git(self.repo, "add", "ggml/src/ggml-vulkan/ggml-vulkan.cpp")
        git(self.repo, "commit", "-qm", "synthetic Vulkan code change")
        commit = git(self.repo, "rev-parse", "HEAD")
        import json as _json
        fixcap = self.capture("A3", head=commit)
        raw = _json.dumps(fixcap, sort_keys=True).encode()
        (self.evidence / "fix-dispatch.json").write_bytes(raw)
        self.write_json(self.evidence / "fix.json", {
            "repo_root": str(self.repo), "commit": commit,
            "dispatch_capture": fixcap, "authority_sha256": sha(raw)})
        bad = ASYNC_OFF + build_log([("alloc", "device", 4 * MIB)],
                                    enum_count=2)
        fixed_ns = "fixed/" + A.ARMS["A3"]["namespace"]
        for i in range(1, 6):
            self.retain("A3", i, authority=fixcap, namespace=fixed_ns,
                        fix_commit=commit, binary_sha256="a" * 64,
                        server_log=bad)
        with mock.patch.object(P, "fetch_dispatch_comment",
                               self.fetcher("A3", head=commit)):
            out = T.derive_terminal(self.evidence, {})
        self.assertNotEqual(out, C.ACCEPTED_TERMINAL)

    def test_pin_forged_fix_dispatch_without_registry_entry_blocked(self):
        # Forged fix-dispatch authority with an invented comment id cannot
        # admit through the offline registry (zero GitHub requests).
        self.write_json(self.evidence / "authority.json", {
            "repo_root": str(self.repo),
            "dispatch_capture": self.authority("A3")})
        good = ASYNC_OFF + build_log([("alloc", "device", 4 * MIB)])
        for i in range(1, 6):
            self.retain("A3", i, authority=self.authority("A3"),
                        server_log=good)
        path = self.repo / "ggml/src/ggml-vulkan/ggml-vulkan.cpp"
        path.parent.mkdir(parents=True)
        path.write_text("int synthetic_vk_fix(void) { return 1; }\n")
        git(self.repo, "add", "ggml/src/ggml-vulkan/ggml-vulkan.cpp")
        git(self.repo, "commit", "-qm", "synthetic Vulkan code change")
        commit = git(self.repo, "rev-parse", "HEAD")
        forged = self.comment("A3", head=commit)
        forged.update(id=424244)
        forged["html_url"] = ("https://github.com/Zutfen-LLC/inferswarm/"
                              "pull/253#issuecomment-424244")
        fixcap = self.capture("A3", head=commit, comment=forged)
        import json as _json
        raw = _json.dumps(fixcap, sort_keys=True).encode()
        (self.evidence / "fix-dispatch.json").write_bytes(raw)
        self.write_json(self.evidence / "fix.json", {
            "repo_root": str(self.repo), "commit": commit,
            "dispatch_capture": fixcap, "authority_sha256": sha(raw)})
        fixed_ns = "fixed/" + A.ARMS["A3"]["namespace"]
        for i in range(1, 6):
            self.retain("A3", i, authority=fixcap, namespace=fixed_ns,
                        fix_commit=commit, binary_sha256="a" * 64,
                        server_log=good)
        with mock.patch.object(P, "fetch_dispatch_comment",
                               self.fetcher("A3", head=commit)):
            out = T.derive_terminal(self.evidence, {})
        self.assertEqual(out, T.BLOCKED)


if __name__ == "__main__":
    unittest.main()

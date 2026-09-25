#!/usr/bin/env python3
"""Issue #250 (R8-I3B) — diagnostic-only tests.

CPU-only, fake-runner tests: no physical execution, no GPU, no model
reads. Mutation controls must assert the probe list is EMPTY when a
gate denies, custody forgery is caught, and every terminal path of
the frozen decision tree is exercised by direct reducer invocation
with retained-byte fixtures (never by asserting on vocabulary alone).
"""
from __future__ import annotations

import importlib.util
import json
import struct
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(
        name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


P0 = _load("issue250_phase0", "scripts/issue250_phase0.py")
D = _load("issue250_diagnostic", "scripts/issue250_diagnostic.py")


def make_authority(head: str = "f" * 40, namespace: str = "d250-arm-a",
                   arm: str = "A-vulkan-necessity", **over):
    body_lines = [
        D.DIAGNOSTIC_DISPATCH_PHRASE,
        f"head={head}",
        f"diagnostic-namespace={namespace}",
        f"arm={arm}",
    ]
    doc = {
        "comment_id": 1,
        "issue_url": f"https://api.github.com/repos/x/y/issues/{D.DIAGNOSTIC_PR_NUMBER}",
        "author_association": "MEMBER",
        "created_at": "2026-09-25T00:00:00Z",
        "body": "\n".join(body_lines),
        "head_sha": head,
        "open_pr": True,
        "issue_open": True,
        "namespace": namespace,
    }
    doc.update(over)
    return doc


class NamespaceTests(unittest.TestCase):
    def test_valid_namespaces(self):
        for ns in ("d250-arm-a", "d250-arm-b2", "d250-x0y"):
            self.assertEqual(D.validate_namespace(ns), ns)

    def test_invalid_shape(self):
        for ns in ("d248-arm-a", "x250-a", "d250-", "d250-a-", "d250-A",
                   "d250 arm", "campaign-250", "c237-250", "phase-1",
                   "qualification", "issue241-x", "issue248-x", ""):
            with self.assertRaises(D.DiagnosticError):
                D.validate_namespace(ns)

    def test_namespace_dir_gates(self):
        with self.assertRaises(D.DiagnosticError):
            D.namespace_dir(Path("/tmp"), "d248-ref-repeats")


class ContractTests(unittest.TestCase):
    def test_accepted_contract_ok(self):
        self.assertEqual(
            D.validate_request_contract(dict(D.REQUEST_CONTRACT)),
            D.REQUEST_CONTRACT)

    def test_contract_mutations_rejected(self):
        base = dict(D.REQUEST_CONTRACT)
        for mut in ({**base, "top_k": 2}, {**base, "temperature": 0.1},
                    {**base, "seed": 1}, {**base, "n_predict": 4},
                    {**base, "cache_prompt": True},
                    {**base, "samplers": ["top_p"]},
                    {**base, "extra_key": 1},
                    {k: v for k, v in base.items() if k != "seed"},
                    {**base, "id_slot": 3}):
            with self.assertRaises(D.DiagnosticError):
                D.validate_request_contract(mut)

    def test_arm_b_extension_declared_only(self):
        ok = D.validate_request_contract(
            dict(D.ARM_B_CONTRACT), extra_keys=frozenset({"id_slot"}))
        self.assertEqual(ok["id_slot"], 3)
        # the same key without declaration is rejected
        with self.assertRaises(D.DiagnosticError):
            D.validate_request_contract(dict(D.ARM_B_CONTRACT))
        # wrong value for the declared key
        with self.assertRaises(D.DiagnosticError):
            D.validate_request_contract(
                {**D.ARM_B_CONTRACT, "id_slot": 0},
                extra_keys=frozenset({"id_slot"}))
        # undisclosed extra keys cannot pass via extra_keys
        with self.assertRaises(D.DiagnosticError):
            D.validate_request_contract(
                {**D.ARM_B_CONTRACT, "id_slot": 3, "n_predict2": 1},
                extra_keys=frozenset({"id_slot", "n_predict2"}))

    def test_contract_digest_binding(self):
        # The frozen digest of the accepted contract must be stable.
        self.assertEqual(
            D.canonical_request_digest(D.REQUEST_CONTRACT),
            D.canonical_request_digest({
                "seed": 0, "samplers": ["top_k"], "top_k": 1,
                "temperature": 0.0, "n_predict": 8, "stream": False,
                "return_tokens": True, "cache_prompt": False}))


class AuthorityTests(unittest.TestCase):
    HEAD = "a" * 40

    def test_valid_authority(self):
        a = make_authority(head=self.HEAD)
        out = D.validate_authority_payload(a, self.HEAD)
        self.assertEqual(out["namespace"], "d250-arm-a")
        self.assertEqual(out["arm"], "A-vulkan-necessity")

    def test_phrase_not_in_prose(self):
        # the phrase must be an exact stripped LINE, not prose
        a = make_authority(head=self.HEAD)
        a["body"] = ("please run " + D.DIAGNOSTIC_DISPATCH_PHRASE +
                     " now\nhead=" + self.HEAD +
                     "\ndiagnostic-namespace=d250-arm-a\narm=A-vulkan-necessity")
        with self.assertRaises(D.DiagnosticError):
            D.validate_authority_payload(a, self.HEAD)

    def test_state_gates(self):
        for over, why in (
                ({"open_pr": False}, "pr merged"),
                ({"issue_open": False}, "issue closed"),
                ({"author_association": "CONTRIBUTOR"}, "non-member"),
                ({"head_sha": "b" * 40}, "head drift"),
                ({"created_at": ""}, "review-shaped")):
            with self.assertRaises(D.DiagnosticError, msg=why):
                D.validate_authority_payload(
                    make_authority(head=self.HEAD, **over), self.HEAD)

    def test_248_dispatch_cannot_authorize_250(self):
        # a d248- namespace in a #250-shaped comment is refused
        a = make_authority(head=self.HEAD, namespace="d248-ref-repeats")
        with self.assertRaises(D.DiagnosticError):
            D.validate_authority_payload(a, self.HEAD)

    def test_case_4096_line_is_protocol_error(self):
        a = make_authority(head=self.HEAD)
        a["body"] += "\ncase-4096: because"
        with self.assertRaises(D.DiagnosticError):
            D.validate_authority_payload(a, self.HEAD)

    def test_unknown_arm_refused(self):
        a = make_authority(head=self.HEAD, arm="A-vulkan-necessity-v2")
        with self.assertRaises(D.DiagnosticError):
            D.validate_authority_payload(a, self.HEAD)

    def test_missing_arm_refused(self):
        a = make_authority(head=self.HEAD)
        a["body"] = (f"{D.DIAGNOSTIC_DISPATCH_PHRASE}\nhead={self.HEAD}"
                     "\ndiagnostic-namespace=d250-arm-a")
        with self.assertRaises(D.DiagnosticError):
            D.validate_authority_payload(a, self.HEAD)

    def test_binding_two_observations(self):
        a = make_authority(head=self.HEAD)
        b = make_authority(head=self.HEAD)
        self.assertEqual(D.bind_authority_observations(a, b)["comment_id"], 1)
        b2 = make_authority(head=self.HEAD)
        b2["body"] += "\nextra"
        with self.assertRaises(D.DiagnosticError):
            D.bind_authority_observations(a, b2)

    def test_authority_digest_binds_body(self):
        a = make_authority(head=self.HEAD)
        b = make_authority(head=self.HEAD)
        b["body"] += "\nextra line"
        self.assertNotEqual(D.authority_digest(a), D.authority_digest(b))


class ArmPlanTests(unittest.TestCase):
    def test_arm_a_uses_dev_none_not_ngl0(self):
        units = D.probe_list_for("A-vulkan-necessity")
        self.assertEqual(len(units), 5)
        for u in units:
            self.assertEqual(u["argv_delta"], ("-dev", "none"))
            self.assertNotIn(("-ngl", "0"), [tuple(u["argv_delta"])])

    def test_arm_c_single_thread_regime(self):
        units = D.probe_list_for("C-cpu-threads")
        thr1 = [u for u in units if "-thr1-" in u["tag"]]
        thr14 = [u for u in units if "-thr14-" in u["tag"]]
        self.assertEqual(len(thr1), 5)
        self.assertEqual(len(thr14), 2)
        for u in thr1:
            self.assertEqual(tuple(u["argv_delta"]),
                             ("-t", "1", "-tb", "1"))
        for u in thr14:
            self.assertEqual(u["argv_delta"], ())

    def test_arm_d_ladder_predeclared(self):
        units = D.probe_list_for("D-context-transition")
        lengths = sorted({u["ladder_length"] for u in units})
        self.assertEqual(lengths, [1024, 1536, 2048, 2304, 2560, 3072])
        for length in lengths:
            self.assertEqual(
                len([u for u in units if u["ladder_length"] == length]), 2)

    def test_arm_b_same_process_units_declared(self):
        units = D.probe_list_for("B-process-init")
        same = [u for u in units if u.get("same_process")]
        fresh = [u for u in units if not u.get("same_process")]
        self.assertEqual(len(same), 5)
        self.assertEqual(len(fresh), 5)
        for u in same:
            self.assertEqual(u["request"], "arm-b")

    def test_unknown_arm_refused(self):
        with self.assertRaises(D.DiagnosticError):
            D.probe_list_for("A-vulkan-necessity-v2")

    def test_no_case_4096_anywhere(self):
        for arm in D.ARM_PLANS:
            for u in D.probe_list_for(arm):
                self.assertNotIn("4096", u["tag"])

    def test_no_4096_ladder_lengths(self):
        # D ladder never includes 4096.
        for u in D.probe_list_for("D-context-transition"):
            self.assertNotEqual(u["ladder_length"], 4096)


class DeterminismTests(unittest.TestCase):
    def test_first_mismatch_suffices(self):
        out = D.judge_repeat_determinism(["a", "a", "b"])
        self.assertFalse(out["deterministic"])
        self.assertFalse(out["deterministic_claim_valid"])

    def test_deterministic_claim_needs_five(self):
        three = D.judge_repeat_determinism(["a", "a", "a"])
        self.assertTrue(three["strictly_identical"])
        self.assertFalse(three["deterministic_claim_valid"])
        five = D.judge_repeat_determinism(["a"] * 5)
        self.assertTrue(five["deterministic_claim_valid"])
        self.assertTrue(five["deterministic"])

    def test_row_digest_geometry(self):
        row = bytes(D.ROW_BYTES)
        self.assertEqual(D.row_digest(row), D.row_digest(bytes(D.ROW_BYTES)))
        with self.assertRaises(D.DiagnosticError):
            D.row_digest(row[:-1])

    def test_token_digest(self):
        toks = [328, 760, 324, 55965, 51624, 29014, 34227, 18030]
        self.assertEqual(D.canonical_token_digest(toks),
                         D.canonical_token_digest(list(toks)))
        with self.assertRaises(D.DiagnosticError):
            D.canonical_token_digest(toks[:7])


class TerminalTests(unittest.TestCase):
    """Direct reducer-invocation tests over the frozen decision tree."""

    def _red(self, complete=True, arms=None, required=None):
        return {
            "complete": complete,
            "arms": arms or {},
            "required_arms": required or D.REQUIRED_ARMS,
        }

    def test_incomplete_fails_closed(self):
        self.assertEqual(D.derive_terminal(self._red(complete=False)),
                         D.REDUCER_BLOCKED)

    def test_missing_arm_fails_closed(self):
        self.assertEqual(
            D.derive_terminal(self._red(arms={})), D.REDUCER_BLOCKED)

    def test_cpu_only_deterministic_localizes(self):
        arms = {"A-vulkan-necessity": {"condition_determinism": {
            "cpu_only_devnone": {"deterministic": True},
            "accepted_ngl8": {"deterministic": False}}}}
        self.assertEqual(
            D.derive_terminal(self._red(arms=arms)),
            "R8I3B_REFERENCE_RUNTIME_BOUNDARY_LOCALIZED")

    def test_cpu_only_varies_unresolved(self):
        arms = {"A-vulkan-necessity": {"condition_determinism": {
            "cpu_only_devnone": {"deterministic": False},
            "accepted_ngl8": {"deterministic": False}}}}
        self.assertEqual(
            D.derive_terminal(self._red(arms=arms)),
            "R8I3B_REFERENCE_RUNTIME_UNRESOLVED")

    def test_reproduction_failure_unresolved(self):
        arms = {"A-vulkan-necessity": {"condition_determinism": {
            "cpu_only_devnone": {"deterministic": True},
            "accepted_ngl8": {"deterministic": True}}}}
        self.assertEqual(
            D.derive_terminal(self._red(arms=arms)),
            "R8I3B_REFERENCE_RUNTIME_UNRESOLVED")

    def test_missing_condition_fails_closed(self):
        arms = {"A-vulkan-necessity": {"condition_determinism": {
            "cpu_only_devnone": {"deterministic": True}}}}
        self.assertEqual(
            D.derive_terminal(self._red(arms=arms)), D.REDUCER_BLOCKED)

    def test_terminal_vocabulary_frozen(self):
        self.assertEqual(
            D.terminal_vocabulary(),
            ("R8I3B_REFERENCE_RUNTIME_BOUNDARY_LOCALIZED",
             "R8I3B_REFERENCE_RUNTIME_UNRESOLVED",
             "R8I3B_REDUCER_BLOCKED_INCOMPLETE"))


class Phase0Tests(unittest.TestCase):
    def test_bindings_verify_on_this_tree(self):
        out = P0.verify_bindings(REPO)
        self.assertEqual(out["problems"], [], out["problems"])
        self.assertEqual(out["facts"]["committed_terminal"],
                         "R8I3_REF_NONDETERMINISM_UNRESOLVED")
        self.assertEqual(
            out["facts"]["fixture_ladder_sha256"],
            P0.FIXTURE_LADDER_SHA256)

    def test_bindings_fail_on_ladder_mutation(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            (tdp / "scripts").mkdir()
            (tdp / "scripts/issue248_diagnostic.py").write_text(
                "ok = 1\n")
            ladder_rel = Path(P0.FIXTURE_LADDER_REL)
            dst = tdp / ladder_rel
            dst.parent.mkdir(parents=True)
            dst.write_bytes((REPO / ladder_rel).read_bytes()[:-1] + b" ")
            out = P0.verify_bindings(tdp)
            self.assertFalse(out["ok"])
            self.assertTrue(any("ladder digest drift" in p
                                for p in out["problems"]))

    def test_ladder_case_lengths(self):
        out = P0.verify_bindings(REPO)
        self.assertEqual(
            out["facts"]["ladder_case_lengths"],
            {"case-256": 256, "case-1024": 1022,
             "case-3072": 3077, "case-4096": 4097})

    def test_phase0_doc_deterministic(self):
        d1 = P0.derive_phase0(REPO)
        d2 = P0.derive_phase0(REPO)
        self.assertEqual(json.dumps(d1, sort_keys=True),
                         json.dumps(d2, sort_keys=True))

    def test_reconstruction_has_all_six(self):
        for key in ("R1_prompt_ingestion", "R2_first_generation_step",
                    "R3_threadpool_threads", "R4_cpu_kernels",
                    "R5_vulkan_at_ngl1", "R6_process_init"):
            self.assertIn(key, P0.RECONSTRUCTION)
            self.assertTrue(P0.RECONSTRUCTION[key]["summary"])
            self.assertTrue(P0.RECONSTRUCTION[key]["evidence"])

    def test_pinned_controls_proven(self):
        for name, ctl in P0.PINNED_CONTROLS.items():
            self.assertTrue(ctl["flag"], name)
            self.assertTrue(ctl["provenance"], name)
        self.assertIn("-dev none", P0.PINNED_CONTROLS[
            "cpu_only_no_device"]["flag"])
        # -ngl 0 must carry the not-pure-CPU caveat
        self.assertIn("NOT a pure CPU control",
                      P0.PINNED_CONTROLS["cpu_only_zero_layers"]["caveat"])

    def test_hypotheses_have_probes(self):
        ids = [h["id"] for h in P0.HYPOTHESES]
        self.assertEqual(ids, ["H1", "H2", "H3", "H4", "H5"])
        for h in P0.HYPOTHESES:
            self.assertTrue(h["smallest_probe"], h["id"])

    def test_constants_crosscheck_with_accepted_248(self):
        # Self-containment: frozen constants equal the merged #248
        # tooling constants (byte-level presence, no imports).
        src = (REPO / "scripts/issue248_diagnostic.py").read_text()
        for digest in D.SERVER_BINARIES.values():
            self.assertIn(digest, src)
        self.assertIn(D.FIXTURE_LADDER_SHA256, src)
        for member, digest in D.MODEL_MEMBER_SHA256.items():
            self.assertIn(digest, src)
        # and NOT imported at runtime
        self.assertNotIn("import issue248", Path(REPO / "scripts/issue250_diagnostic.py").read_text())
        self.assertNotIn("issue248_diagnostic import",
                         Path(REPO / "scripts/issue250_diagnostic.py").read_text())

    def test_phase0_json_committed_and_matching(self):
        p = (REPO / "docs/investigations/qwen38-flash-next-r8-i3b-"
             "ref-runtime-boundary/evidence/phase0/phase0-analysis.json")
        self.assertTrue(p.is_file(), "committed phase0 analysis missing")
        committed = json.loads(p.read_bytes())
        fresh = P0.derive_phase0(REPO)
        self.assertEqual(committed, fresh)


class SelfContainmentImportScan(unittest.TestCase):
    """The diagnostic module must not import campaign/unmerged modules."""

    def test_no_forbidden_imports(self):
        src = (REPO / "scripts/issue250_diagnostic.py").read_text()
        for bad in ("import issue241", "from issue241",
                    "import issue248", "from issue248"):
            self.assertNotIn(bad, src)
        src0 = (REPO / "scripts/issue250_phase0.py").read_text()
        for bad in ("import issue241", "from issue241",
                    "import issue248", "from issue248"):
            self.assertNotIn(bad, src0)


if __name__ == "__main__":
    unittest.main()

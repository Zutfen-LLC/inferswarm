#!/usr/bin/env python3
"""Issue #250 (R8-I3B) — diagnostic-only tests (correction pass 2).

CPU-only, fake-runner tests: no physical execution, no GPU, no model
reads. Mutation controls must assert the probe list is EMPTY when a
gate denies, custody forgery is caught, and every terminal path of
the frozen sequential law is exercised by direct retained-byte
reducer invocation (never by asserting on vocabulary alone).
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
    sys.modules[name] = mod
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


class NamespaceArmBindingTests(unittest.TestCase):
    """Correction pass 2, blocker 5: exact namespace<->arm pairing."""

    def test_exact_pairs_pass(self):
        for ns, arm in D.NAMESPACE_ARM_BINDING.items():
            self.assertEqual(
                D.validate_namespace_arm_binding(ns, arm), arm)

    def test_cross_pairs_rejected(self):
        # every mismatched (namespace, arm) combination is refused
        namespaces = sorted(D.NAMESPACE_ARM_BINDING)
        arms = sorted(D.ARM_NAMESPACE_BINDING)
        for ns in namespaces:
            for arm in arms:
                if D.NAMESPACE_ARM_BINDING[ns] == arm:
                    continue
                with self.assertRaises(D.DiagnosticError):
                    D.validate_namespace_arm_binding(ns, arm)

    def test_unknown_arm_rejected(self):
        with self.assertRaises(D.DiagnosticError):
            D.validate_namespace_arm_binding("d250-arm-a", "A-vulkan-necessity-v2")

    def test_unknown_namespace_rejected(self):
        with self.assertRaises(D.DiagnosticError):
            D.validate_namespace_arm_binding("d250-arm-z", "A-vulkan-necessity")

    def test_binding_is_exact_mapping(self):
        self.assertEqual(
            D.NAMESPACE_ARM_BINDING,
            {"d250-arm-a": "A-vulkan-necessity",
             "d250-arm-b": "B-process-init",
             "d250-arm-c": "C-cpu-threads",
             "d250-arm-d": "D-context-transition"})
        # injective in both directions (no duplicate namespace/arm)
        self.assertEqual(len(set(D.NAMESPACE_ARM_BINDING)),
                         len(D.NAMESPACE_ARM_BINDING))
        self.assertEqual(len(set(D.ARM_NAMESPACE_BINDING)),
                         len(D.ARM_NAMESPACE_BINDING))


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

    def test_namespace_arm_cross_pair_refused_in_payload(self):
        # d250-arm-a + arm=C (the maintainer's demonstrated forgery)
        a = make_authority(head=self.HEAD, namespace="d250-arm-a",
                           arm="C-cpu-threads")
        with self.assertRaises(D.DiagnosticError):
            D.validate_authority_payload(a, self.HEAD)
        # every cross pair is refused at the payload validator too
        for ns, arm in (("d250-arm-a", "B-process-init"),
                        ("d250-arm-a", "C-cpu-threads"),
                        ("d250-arm-a", "D-context-transition"),
                        ("d250-arm-b", "A-vulkan-necessity"),
                        ("d250-arm-b", "C-cpu-threads"),
                        ("d250-arm-c", "A-vulkan-necessity"),
                        ("d250-arm-d", "B-process-init")):
            with self.assertRaises(D.DiagnosticError):
                D.validate_authority_payload(
                    make_authority(head=self.HEAD, namespace=ns, arm=arm),
                    self.HEAD)

    def test_duplicate_arm_lines_refused(self):
        a = make_authority(head=self.HEAD)
        a["body"] += "\narm=A-vulkan-necessity"
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

    def test_arm_a_declares_no_fresh_vulkan_units(self):
        # blocker 3: the nonzero-Vulkan side is retained #248
        # evidence only; the frozen plan carries NO fresh ngl units.
        units = D.probe_list_for("A-vulkan-necessity")
        for u in units:
            self.assertEqual(u["ngl"], 0)
        self.assertNotIn("ngl8", json.dumps(units))
        self.assertNotIn("accepted-condition", json.dumps(units))

    def test_arm_b_is_cpu_only(self):
        # blocker 2: B inherits the CPU-only condition; no ngl=8.
        units = D.probe_list_for("B-process-init")
        fresh = [u for u in units if not u.get("same_process")]
        same = [u for u in units if u.get("same_process")]
        self.assertEqual(len(fresh), 5)
        self.assertEqual(len(same), 5)
        for u in units:
            self.assertEqual(tuple(u["argv_delta"]), ("-dev", "none"))
            self.assertEqual(u["ngl"], 0)
        for u in same:
            self.assertEqual(u["request"], "arm-b")

    def test_arm_c_is_cpu_only_single_thread_regime(self):
        units = D.probe_list_for("C-cpu-threads")
        thr1 = [u for u in units if "thr1" in u["tag"]]
        default = [u for u in units if "thr-default" in u["tag"]]
        self.assertEqual(len(thr1), 5)
        self.assertEqual(len(default), 2)
        for u in thr1:
            self.assertEqual(tuple(u["argv_delta"]),
                             ("-dev", "none", "-t", "1", "-tb", "1"))
        for u in default:
            self.assertEqual(tuple(u["argv_delta"]), ("-dev", "none"))
        for u in units:
            self.assertEqual(u["ngl"], 0)

    def test_arm_d_ladder_predeclared(self):
        units = D.probe_list_for("D-context-transition")
        lengths = sorted({u["ladder_length"] for u in units})
        self.assertEqual(lengths, [1024, 1536, 2048, 2304, 2560, 3072])
        for length in lengths:
            self.assertEqual(
                len([u for u in units if u["ladder_length"] == length]), 2)
        # ladder runs at the accepted placement; factor = length
        for u in units:
            self.assertEqual(u["argv_delta"], ())
            self.assertEqual(u["ngl"], D.ACCEPTED_MATCHED_NGL)

    def test_arm_d_sentence_repeats_predeclared(self):
        self.assertEqual(
            sorted(D.ARM_D_LADDER_SENTENCE_REPEATS),
            [1024, 1536, 2048, 2304, 2560, 3072])

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

    def test_contrast_constants_frozen(self):
        # blocker 3: the contrast rule is the accepted #248 retained
        # ngl=1 result, consumed read-only.
        self.assertEqual(D.CONTRAST_PROVENANCE,
                         "accepted_248_retained_ngl1_readonly")
        self.assertEqual(D.CONTRAST_NGL, 1)
        self.assertEqual(
            D.CONTRAST_UNITS,
            ("case-3072-B-ngl1-001", "case-3072-B-ngl1-002"))
        self.assertFalse(D.CONTRAST_EXPECTED_ROW_DETERMINISTIC)


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


class TerminalModuleMovedTests(unittest.TestCase):
    """The caller-supplied-boolean terminal path is GONE (blocker 4).

    The retained-byte reducer lives in scripts/issue250_terminal.py
    (tested directly in test_issue250_terminal.py); the diagnostic
    spine exports no terminal-derivation function that accepts a
    reduction dict.
    """

    def test_no_caller_dict_terminal_in_diagnostic_module(self):
        self.assertFalse(hasattr(D, "derive_terminal"))
        self.assertFalse(hasattr(D, "REQUIRED_ARMS"))

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
    """The diagnostic/phase-0 modules must not import #248 modules;
    the physical/terminal modules reuse them deliberately (declared,
    maintainer-authorized reuse of the accepted implementations)."""

    def test_no_forbidden_imports(self):
        src = (REPO / "scripts/issue250_diagnostic.py").read_text()
        for bad in ("import issue241", "from issue241",
                    "import issue248", "from issue248"):
            self.assertNotIn(bad, src)
        src0 = (REPO / "scripts/issue250_phase0.py").read_text()
        for bad in ("import issue241", "from issue241",
                    "import issue248", "from issue248"):
            self.assertNotIn(bad, src0)

    def test_physical_module_declared_reuse(self):
        # The physical producer's #248 reuse is the two ACCEPTED raw
        # evidence helpers only (health + identity), plus the #250
        # spine; never the #248 authority model.
        src = (REPO / "scripts/issue250_physical.py").read_text()
        self.assertIn("import issue250_diagnostic as D", src)
        self.assertIn("import issue248_health as H", src)
        self.assertIn("import issue248_identity as I", src)
        for bad in ("import issue248_diagnostic",
                    "import issue248_physical",
                    "import issue248_terminal",
                    "import issue241"):
            self.assertNotIn(bad, src)
        src_t = (REPO / "scripts/issue250_terminal.py").read_text()
        for bad in ("import issue248_diagnostic",
                    "import issue248_physical",
                    "import issue248_terminal",
                    "import issue241"):
            self.assertNotIn(bad, src_t)


OLD_HEAD = "ac589445a31adcf34ef7c8f23d3abd509b7a0806"
OLD_REVIEWED_HEAD_COMMENT = "PR #251 comment 5840630050"


class OldDefectProofs(unittest.TestCase):
    """Old-defect proofs for the reviewed ac58944 head (NO-GO 5840630050).

    Each test first PROVES the defect existed at the old head (from
    retained git bytes, fail-safe if the object is unreachable), then
    proves the corrected head REFUSES the defect.
    """

    def _old_source(self, relpath: str) -> str:
        import subprocess
        try:
            out = subprocess.run(
                ["git", "show", f"{OLD_HEAD}:{relpath}"],
                cwd=REPO, capture_output=True, text=True, check=True)
            return out.stdout
        except subprocess.CalledProcessError:
            self.skipTest(f"old head object {OLD_HEAD[:7]} unreachable")

    def test_old_defect_1_no_physical_execution_entrypoint(self):
        # OLD: no producer module existed; the diagnostic module had
        # no execution entrypoint (zero run_* functions).
        old = self._old_source("scripts/issue250_diagnostic.py")
        self.assertNotIn("def run_diagnostic_unit", old)
        self.assertNotIn("def run_same_process_lifecycle", old)
        # CORRECTED: the dedicated physical producer exists.
        src = (REPO / "scripts" / "issue250_physical.py").read_text()
        self.assertIn("def run_diagnostic_unit", src)
        self.assertIn("def run_same_process_lifecycle", src)

    def test_old_defect_2_b_and_c_used_matched_ngl8(self):
        # OLD: B and C units carried ACCEPTED_MATCHED_NGL = 8.
        old = self._old_source("scripts/issue250_diagnostic.py")
        self.assertIn("ACCEPTED_MATCHED_NGL = 8", old)
        old_b = None
        for line in old.splitlines():
            if "B-process-init" in line or old_b:
                old_b = (old_b or "") + line + "\n"
                if "return" in line and old_b.count("return") > 1:
                    break
        # the old plan bound matched ngl=8 to every B/C unit
        self.assertIn('"ngl": ACCEPTED_MATCHED_NGL', old)
        # CORRECTED: every B and C unit is CPU-only -dev none; no
        # ngl=8 anywhere in #250 tooling.
        for unit in D.probe_list_for("B-process-init"):
            self.assertEqual(
                tuple(unit["argv_delta"]), ("-dev", "none"))
            self.assertEqual(unit["ngl"], 0)
        for unit in D.probe_list_for("C-cpu-threads"):
            if "thr1" not in unit["tag"]:
                self.assertEqual(
                    tuple(unit["argv_delta"]), ("-dev", "none"))
                self.assertEqual(unit["ngl"], 0)
            else:
                # serial adds ONLY -t 1 -tb 1 on the CPU-only base
                self.assertEqual(
                    tuple(unit["argv_delta"]),
                    ("-dev", "none", "-t", "1", "-tb", "1"))
                self.assertEqual(unit["ngl"], 0)
        # CORRECTED head: no plan unit carries ngl=8; the only
        # accepted-placement ngl is the Arm-D ladder (declared,
        # length factor). The module docstring's prohibition sentence
        # may NAME ngl=8 as excluded; the plan geometry must not use it.
        for arm in ("A-vulkan-necessity", "B-process-init",
                    "C-cpu-threads"):
            for unit in D.probe_list_for(arm):
                self.assertNotEqual(unit["ngl"], 8)
        meth = (REPO / "docs" / "investigations" /
                "qwen38-flash-next-r8-i3b-ref-runtime-boundary" /
                "METHODOLOGY.md").read_text()
        # ngl=8 may appear ONLY inside the prohibition sentence; no
        # line may PLAN fresh ngl=8 reproduction (the old defect)
        ngl8_lines = [ln for ln in meth.splitlines() if "ngl=8" in ln]
        self.assertTrue(ngl8_lines)
        for ln in ngl8_lines:
            self.assertIn("no `ngl=8`", ln)

    def test_old_defect_3_arm_a_plan_lacked_expected_contrast(self):
        # OLD: derive_terminal expected accepted_ngl8 while the Arm-A
        # plan contained ONLY -dev none units (no ngl=1 contrast).
        old = self._old_source("scripts/issue250_diagnostic.py")
        self.assertIn('det_map.get("accepted_ngl8")', old)
        # the old head planned ONLY -dev none units for Arm A (the
        # expected contrast condition was never declared as units) and
        # had no retained-contrast constants at all
        self.assertIn("-B-devnone-00", old)      # devnone units planned
        self.assertNotIn("CONTRAST_PROVENANCE", old)
        self.assertNotIn("CONTRAST_UNITS", old)
        self.assertNotIn("ngl1", old)
        # CORRECTED: the contrast is the retained #248 ngl=1 evidence,
        # declared read-only in the plan and consumed by the reducer.
        src = (REPO / "scripts" / "issue250_diagnostic.py").read_text()
        self.assertIn("CONTRAST_PROVENANCE", src)
        self.assertIn("d248-placement-rungs", src)
        self.assertIn("ngl1", src)
        plan_a = [u for u in D.probe_list_for("A-vulkan-necessity")]
        self.assertTrue(plan_a)
        self.assertTrue(all(u["ngl"] == 0 and
                            tuple(u["argv_delta"]) == ("-dev", "none")
                            for u in plan_a))
        # and the reducer consumes the contrast via retained bytes
        src_t = (REPO / "scripts" / "issue250_terminal.py").read_text()
        self.assertIn("verify_historical_contrast", src_t)
        self.assertIn("CONTRAST_AUTHORITY_HEAD", src_t)

    def test_old_defect_4_caller_supplied_reduction_terminal(self):
        # OLD: derive_terminal(reduction) trusted caller booleans and
        # could emit a terminal from caller-supplied "deterministic".
        old = self._old_source("scripts/issue250_diagnostic.py")
        self.assertIn('reduction.get("complete")', old)
        self.assertIn('cpu["deterministic"]', old)
        # CORRECTED: the corrected module has no derive_terminal and
        # accepts no reduction dict; the retained-byte reducer has no
        # such parameter. (Lazy load: this file is frozen import-free
        # of #248 modules, and issue250_terminal pulls 248 helpers.)
        src = (REPO / "scripts" / "issue250_diagnostic.py").read_text()
        self.assertNotIn("def derive_terminal", src)
        import inspect
        # issue250_terminal imports the physical module (which imports
        # the accepted 248 helpers) by exact module names; wire the
        # whole dependency chain under those names, then load the
        # terminal module. This test method is the ONLY place this
        # file loads #248-dependent modules (the module-level frozen
        # import-free boundary applies to module scope).
        for _dep in ("issue248_diagnostic", "issue248_health",
                     "issue248_identity"):
            if _dep not in sys.modules:
                _load(_dep, f"scripts/{_dep}.py")
        if "issue250_physical" not in sys.modules:
            _load("issue250_physical", "scripts/issue250_physical.py")
        sys.modules.pop("issue250_terminal", None)
        terminal = _load("issue250_terminal", "scripts/issue250_terminal.py")
        params = inspect.signature(terminal.derive_terminal).parameters
        for banned in ("reduction", "terminal", "deterministic",
                       "localized_factor", "condition_summary"):
            self.assertNotIn(banned, params)
        # and a caller-constructed dict CANNOT produce a terminal
        self.assertFalse(hasattr(D, "derive_terminal"))

    def test_old_defect_5_premature_unresolved_on_cpu_only_variation(self):
        # OLD: CPU-only variation immediately returned UNRESOLVED.
        old = self._old_source("scripts/issue250_diagnostic.py")
        self.assertIn(
            "CPU-only varies: Vulkan participation NOT necessary", old)
        # CORRECTED: A-variation makes B REQUIRED (never early
        # UNRESOLVED); the premature path is gone from the reducer —
        # the direct behavioral proof is the terminal matrix
        # (test_cpu_only_variation_requires_b_not_unresolved in
        # tests/test_issue250_terminal.py).
        import inspect
        src_t = (REPO / "scripts" / "issue250_terminal.py").read_text()
        # the corrected reducer makes B REQUIRED (pass-through, no
        # terminal) when CPU-only varies — the premature UNRESOLVED
        # path is structurally gone
        self.assertIn("Arm B becomes REQUIRED; no terminal is emitted",
                      src_t)

    def test_old_defect_6_namespace_arm_cross_pair_accepted(self):
        # OLD: validate_authority_payload validated namespace and arm
        # independently; d250-arm-a + arm=C passed structural checks.
        old = self._old_source("scripts/issue250_diagnostic.py")
        self.assertIn("arms[0] not in ARM_PLANS", old)
        # prove the cross-pair passed at the old head: old validation
        # never compared namespace to arm
        self.assertNotIn("NAMESPACE_ARM_PAIRS", old)
        self.assertNotIn("validate_namespace_arm_binding", old)
        # CORRECTED: the exact pair is required.
        self.assertTrue(hasattr(D, "validate_namespace_arm_binding"))
        with self.assertRaises(D.DiagnosticError):
            D.validate_namespace_arm_binding("d250-arm-a", "C-cpu-threads")
        with self.assertRaises(D.DiagnosticError):
            D.validate_namespace_arm_binding("d250-arm-a", "B-process-init")
        with self.assertRaises(D.DiagnosticError):
            D.validate_namespace_arm_binding("d250-arm-b", "A-vulkan-necessity")
        for ns, arm in D.NAMESPACE_ARM_BINDING.items():
            D.validate_namespace_arm_binding(ns, arm)  # exact pairs pass


if __name__ == "__main__":
    unittest.main()

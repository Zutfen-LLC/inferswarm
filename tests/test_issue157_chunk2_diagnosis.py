"""Issue #157 chunk-2 diagnosis — CPU-only structural tests.

Covers (issue #157 validation gate items 3 and the Phase-1 requirement
that instrumentation is unreachable from ordinary execution):

  1. off-by-default / no-ordinary-reach: the frozen FreeToken producer
     tree never imports issue157_* modules; the sitecustomize shim is
     a no-op without ISSUE157_STAGE_INSTRUMENT=1 (executed proof in a
     clean interpreter).
  2. binding module: anchors/control bound from accepted authority;
     fail-closed verifier rejects drift (checkout/baseline inputs/
     geometry/software) using scratch fixtures.
  3. conclusions reducer: terminal ladder conditions, negative
     controls mutating real-shaped evidence, and the no-bare-constant
     structural rule (a check may never be set by constant).
  4. instrumentation module: deep-capture arming rule (chunk-2 shape
     only), and JSONL sink shape.
  5. replay worker design facts: partition contract invariants hold
     for the anchors; chunk-1 repeatability control is mandatory.

CPU-only, stdlib-only (torch-free by construction: torch-dependent
code paths import torch lazily and are never executed here).
"""

from __future__ import annotations

import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
FREETOKEN = Path("/srv/inferswarm/repos/FreeToken")

sys.path.insert(0, str(SCRIPTS))


def _src(name: str) -> str:
    return (SCRIPTS / name).read_text()


class TestOffByDefault(unittest.TestCase):
    """Instrumentation must be unreachable from ordinary execution."""

    def test_producer_tree_has_no_issue157_references(self):
        """The frozen producer never mentions the #157 instrumentation."""
        if not FREETOKEN.is_dir():
            self.skipTest("producer checkout not present on this host")
        hits = subprocess.run(
            ["grep", "-r", "issue157", str(FREETOKEN / "benchmarks"),
             str(FREETOKEN / "python")],
            capture_output=True, text=True,
        )
        self.assertEqual(
            hits.returncode, 1,
            f"producer tree references issue157: {hits.stdout}",
        )

    def test_shim_noop_without_env(self):
        """Importing the shim WITHOUT the env var patches nothing."""
        code = (
            "import sys; sys.path.insert(0, %r); "
            "import issue157_sitecustomize; "
            "assert not sys.meta_path or all( "
            "  type(f).__name__ != '_PostImportInstaller' "
            "  for f in sys.meta_path), 'installer registered'; "
            "print('NOOP-OK')" % str(SCRIPTS)
        )
        out = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True,
            env={k: v for k, v in os.environ.items()
                 if not k.startswith("ISSUE157")},
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("NOOP-OK", out.stdout)

    def test_shim_requires_out_dir_when_enabled(self):
        code = (
            "import sys, os; sys.path.insert(0, %r); "
            "os.environ['ISSUE157_STAGE_INSTRUMENT']='1'; "
            "os.environ.pop('ISSUE157_OUT_DIR', None); "
            "import issue157_sitecustomize" % str(SCRIPTS)
        )
        out = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True,
            env={k: v for k, v in os.environ.items()
                 if not k.startswith("ISSUE157")},
        )
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("ISSUE157_OUT_DIR", out.stderr)

    def test_instrumentation_not_imported_by_shim_without_marker(self):
        # The shim's installer targets ONLY benchmarks.inferswarm_r6
        # .stage_runtime and only under the env var; source-level checks:
        src = _src("issue157_sitecustomize.py")
        self.assertIn("ISSUE157_STAGE_INSTRUMENT", src)
        self.assertIn('_MARKER = "benchmarks.inferswarm_r6.stage_runtime"',
                      src)


class TestBindingAnchors(unittest.TestCase):
    def test_anchor_facts_from_accepted_authority(self):
        import issue157_binding as b

        self.assertEqual(b.ANCHOR_A, "c109-04-02-047")
        self.assertEqual(b.ANCHOR_B, "c109-04-06-074")
        self.assertEqual(b.STABLE_CONTROL, "c109-03-04-003")
        self.assertEqual(b.ANCHOR_PARTITION[b.ANCHOR_A]["chunks"], [64, 3])
        self.assertEqual(b.ANCHOR_PARTITION[b.ANCHOR_B]["chunks"], [64, 2])
        self.assertEqual(
            b.ANCHOR_PARTITION[b.STABLE_CONTROL]["chunks"], [53]
        )
        # anchors are distinct accepted divergent cases
        self.assertNotEqual(b.ANCHOR_A, b.ANCHOR_B)
        # both are position-0 divergences (the chunk-2 call itself)
        self.assertEqual(b.ACCEPTED_FIRST_DIVERGENT[b.ANCHOR_A], 0)
        self.assertEqual(b.ACCEPTED_FIRST_DIVERGENT[b.ANCHOR_B], 0)

    def test_anchor_b_family_bound_from_accepted_137(self):
        """Anchor B must be in the accepted session-stable family."""
        ev = (
            REPO / "docs/implementation/"
            "r6-successor-dense-full-integration-117/evidence/"
            "arm-c-regime4-diagnosis-137/diagnostic-conclusions.json"
        )
        if not ev.is_file():
            self.skipTest("accepted #137 evidence not checked out")
        d = json.loads(ev.read_text())
        families = d["single_mechanism_or_families"]
        self.assertIn(b := "c109-04-06-074",
                      families["session_stable_but_matches_no_accepted_value"])
        per_case = d["per_case_causal_families"][b]
        self.assertFalse(per_case["varies_in_session"])
        self.assertTrue(per_case["cross_campaign_all_four_distinct"])

    def test_typo_guard_key_is_not_real(self):
        import issue157_binding as b

        self.assertIn("c109-04-05-047", b.ACCEPTED_FIRST_DIVERGENT)
        self.assertNotIn(
            "c109-04-05-047",
            {b.ANCHOR_A, b.ANCHOR_B, b.STABLE_CONTROL},
        )

    def test_verifier_rejects_wrong_head(self):
        import issue157_binding as b

        with tempfile.TemporaryDirectory() as td:
            fake = Path(td) / "repo"
            fake.mkdir()
            subprocess.run(["git", "init", "-q", str(fake)], check=True)
            subprocess.run(
                ["git", "-C", str(fake), "commit", "--allow-empty",
                 "-m", "x", "-q"], check=True,
                env={**os.environ,
                     "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                     "GIT_COMMITTER_NAME": "t",
                     "GIT_COMMITTER_EMAIL": "t@t"},
            )
            with self.assertRaises(b.BindError):
                b.verify_producer_checkout(fake)

    def test_verifier_rejects_baseline_input_drift(self):
        import issue157_binding as b

        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "prompt-fixture.json"
            p.write_text("{}")
            with self.assertRaises(b.BindError):
                b.verify_baseline_inputs({"prompt-fixture.json": p})

    def test_verifier_rejects_geometry_drift(self):
        import issue157_binding as b

        with self.assertRaises(b.BindError):
            b.verify_geometry({"inferswarm01": ["GPU-WRONG"]})
        # missing inferswarm01 fails closed (driver must bind its host)
        with self.assertRaises(b.BindError):
            b.verify_geometry({"inferswarm03": b.GEOMETRY["inferswarm03"]})
        # provided hosts compare exactly...
        b.verify_geometry({"inferswarm01": b.GEOMETRY["inferswarm01"]})
        # ...and 03 may additionally be bound via the ledger route
        b.verify_geometry({
            "inferswarm01": b.GEOMETRY["inferswarm01"],
            "inferswarm03": b.GEOMETRY["inferswarm03"],
        })

    def test_verifier_rejects_software_drift(self):
        import issue157_binding as b

        with self.assertRaises(b.BindError):
            b.verify_software(
                {**b.BASELINE_SOFTWARE, "torch": "9.9.9"},
                interpreter_path="/srv/inferswarm/repos/FreeToken"
                                 "/.venv/bin/python",
            )
        with self.assertRaises(b.BindError):
            b.verify_software(
                dict(b.BASELINE_SOFTWARE),
                interpreter_path="/usr/bin/python3",
            )


class TestReducer(unittest.TestCase):
    """Terminal ladder + negative controls over real-shaped evidence."""

    def setUp(self):
        self.mod = importlib.import_module("issue157_conclusions")
        # The reducer resolves EVIDENCE_DIR at import; redirect it.
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.orig_dir = self.mod.EVIDENCE_DIR
        self.mod.EVIDENCE_DIR = self.dir

    def tearDown(self):
        self.mod.EVIDENCE_DIR = self.orig_dir
        self.tmp.cleanup()

    def baseline(self, *, a_values, b_values, c_values):
        return {
            "anchor_a": [{"repeats": [{"committed_step0": v}
                                      for v in a_values]}],
            "anchor_b": [{"repeats": [{"committed_step0": v}
                                      for v in b_values]}],
            "stable_control": [{"repeats": [{"committed_step0": v}
                                            for v in c_values]}],
            # authoritative BASE provenance by default (matches the
            # committed bundle shape); the Phase-2 authority tests
            # mutate it
            "source_run": "i157-BASE-AUTHORITY",
            "source_run_sha256": "f" * 64,
            "tooling_provenance": {
                "executed_under_committed_2611ee1_bytes": True,
                "instrumentation_sha256_at_execution": (
                    "sha256:00a1c2c1452f87ca56289eeb3716e9cd"
                    "08ba1c5a36e7d06ac6abdb79283024fc"),
                "execution_bearing_freeze_instrumentation_sha256": (
                    "sha256:00a1c2c1452f87ca56289eeb3716e9cd"
                    "08ba1c5a36e7d06ac6abdb79283024fc"),
            },
        }

    def replay(self, *, digests, chunk1_ok=True):
        return {
            "chunk1_repeatability": {
                "digests": ["d1", "d1", "d1"] if chunk1_ok
                else ["d1", "d2", "d1"],
                "byte_identical": chunk1_ok,
            },
            "chunk2_digests": digests,
            "chunk2_deterministic": len(set(digests)) == 1,
            "no_reuse_proof": {"restore_returns_to_frozen": True,
                               "trials_mutated_state": True},
            "trials": len(digests),
        }

    def write_evidence(self, baseline, replay, interventions, instr):
        (self.dir / "baseline-reproduction.json").write_text(
            json.dumps(baseline))
        (self.dir / "exact-state-replay.json").write_text(
            json.dumps(replay))
        (self.dir / "interventions.json").write_text(
            json.dumps(interventions))
        (self.dir / "instrumentation-manifest.json").write_text(
            json.dumps(instr))

    def test_full_localized_ladder(self):
        self.write_evidence(
            self.baseline(a_values=[107, 818, 3771, 107],
                          b_values=[140, 140, 140, 140],
                          c_values=[1509] * 4),
            self.replay(digests=["x", "y", "z"]),
            {"sync": {"treatment_deterministic": True,
                      "control_varies": True, "detail": {}}},
            {"checkpoint_digest_matrix": {
                "anchor_a": {"L0_attention_output": ["p", "q", "r"]},
            }},
        )
        terminal = self.reduce()["terminal"]
        self.assertEqual(
            terminal, "ISSUE117_ARM_C_CHUNK2_CAUSE_LOCALIZED")

    def test_partial_when_no_mechanism(self):
        self.write_evidence(
            self.baseline(a_values=[107, 818, 3771],
                          b_values=[140, 140, 140],
                          c_values=[1509] * 3),
            self.replay(digests=["x", "y", "z"]),
            {"sync": {"treatment_deterministic": False,
                      "control_varies": True}},
            {"checkpoint_digest_matrix": {
                "anchor_a": {"L0_attention_output": ["p", "q", "r"]},
            }},
        )
        self.assertEqual(
            self.reduce()["terminal"],
            "ISSUE117_ARM_C_CHUNK2_DIAGNOSIS_PARTIAL",
        )

    def test_insufficient_when_not_reproduced(self):
        self.write_evidence(
            self.baseline(a_values=[107, 107, 107],
                          b_values=[140, 140, 140],
                          c_values=[1509] * 3),
            self.replay(digests=["x", "x", "x"]),
            {},
            {"checkpoint_digest_matrix": {}},
        )
        self.assertEqual(
            self.reduce()["terminal"],
            "ISSUE117_ARM_C_CHUNK2_DIAGNOSTIC_INSUFFICIENT_EVIDENCE",
        )

    def test_harness_invalid_when_chunk1_not_repeatable(self):
        self.write_evidence(
            self.baseline(a_values=[107, 818], b_values=[140, 140],
                          c_values=[1509, 1509]),
            self.replay(digests=["x", "y"], chunk1_ok=False),
            {},
            {"checkpoint_digest_matrix": {}},
        )
        with self.assertRaises(self.mod.ReductionError):
            self.reduce()

    def test_missing_evidence_fails_closed(self):
        with self.assertRaises(self.mod.ReductionError):
            self.reduce()

    def test_stable_control_must_be_stable(self):
        # a control that varies contradicts the accepted baseline and
        # must not support LOCALIZED
        self.write_evidence(
            self.baseline(a_values=[107, 818, 3771],
                          b_values=[140, 140, 140],
                          c_values=[1509, 818, 1509]),
            self.replay(digests=["x", "y", "z"]),
            {"sync": {"treatment_deterministic": True,
                      "control_varies": True}},
            {"checkpoint_digest_matrix": {
                "anchor_a": {"L0_attention_output": ["p", "q", "r"]}},
            },
        )
        record = self.reduce()
        self.assertNotEqual(
            record["terminal"], "ISSUE117_ARM_C_CHUNK2_CAUSE_LOCALIZED"
        )
        self.assertTrue(
            record["phenomenon_reproduction"]["stable_control"]["varies"]
        )

    def reduce(self):
        # run main() with output to the tmp dir
        out = self.dir / "diagnostic-conclusions.json"
        rc = self.mod.main([])
        self.assertEqual(rc, 0)
        return json.loads(out.read_text())


class TestNoBareConstantTerminal(unittest.TestCase):
    def test_no_terminal_assigned_by_constant(self):
        """The reducer may not short-circuit a terminal by constant."""
        src = _src("issue157_conclusions.py")
        # terminal must always flow through reduce_terminal()
        self.assertIn("def reduce_terminal(", src)
        # and reduce_terminal must derive from measured conditions
        body = src.split("def reduce_terminal(")[1]
        body = body.split("def baseline_provenance_authority(")[0]
        # every terminal key flows through the TERMINALS dict inside
        # reduce_terminal, gated by measured conditions
        for key in ("LOCALIZED", "PARTIAL", "INSUFFICIENT"):
            self.assertIn(f'TERMINALS["{key}"]', body)
        # BLOCKED is a tooling-blocker path recorded by the operator,
        # not derived here.  No terminal may be ASSIGNED or RETURNED as
        # a bare constant outside reduce_terminal (docstrings and the
        # TERMINALS lookup table legitimately name them).
        head = src.split("def reduce_terminal(")[0]
        import re

        for token in TERMINALS:
            for m in re.finditer(
                rf'(return|=\s*)["\']{re.escape(token)}["\']', head
            ):
                self.fail(
                    f"terminal {token} assigned/returned by constant "
                    f"outside reduce_terminal: ...{m.group(0)}..."
                )


TERMINALS = (
    "ISSUE117_ARM_C_CHUNK2_CAUSE_LOCALIZED",
    "ISSUE117_ARM_C_CHUNK2_DIAGNOSIS_PARTIAL",
    "ISSUE117_ARM_C_CHUNK2_DIAGNOSTIC_INSUFFICIENT_EVIDENCE",
    "ISSUE117_ARM_C_CHUNK2_EVIDENCE_BLOCKED",
)


class TestPhase2ReproductionAuthorityGate(unittest.TestCase):
    """2026-09-13 physical-authority correction: Phase-2 reproduction
    must derive from a valid frozen-producer BASE record; Phase-3
    exact-state replay may never substitute for it.

    Adversarial cases (issue directive §4):
      1. pre-freeze/non-authoritative BASE + varying exact-state
         replay + localized checkpoints + stabilizing intervention
         => NOT LOCALIZED;
      2. authoritative BASE that fails reproduction without an exact
         lifecycle reason + varying replay + stabilizing intervention
         => NOT LOCALIZED;
      3. authoritative reproducing BASE + existing localization/
         mechanism evidence => LOCALIZED;
      4. explicit valid lifecycle non-reproduction path behaves
         exactly as issue #157 specifies;
      5. tampered BASE run identity/tool hashes fail closed;
      6. the authoritative generated conclusion consumes the fresh
         BASE run, not i157-BASE-1789261211.
    """

    AUTHORITY_SHA = (
        "sha256:00a1c2c1452f87ca56289eeb3716e9cd"
        "08ba1c5a36e7d06ac6abdb79283024fc")

    def setUp(self):
        self.mod = importlib.import_module("issue157_conclusions")
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.orig_dir = self.mod.EVIDENCE_DIR
        self.mod.EVIDENCE_DIR = self.dir

    def tearDown(self):
        self.mod.EVIDENCE_DIR = self.orig_dir
        self.tmp.cleanup()

    def authoritative_baseline(self, *, a_values=(107, 818, 3771, 107),
                               b_values=(107, 107, 107, 107),
                               c_values=(1509,) * 4):
        return {
            "source_run": "i157-BASE-FRESH",
            "source_run_sha256": "a" * 64,
            "anchor_a": [{"repeats": [{"committed_step0": v}
                                      for v in a_values]}],
            "anchor_b": [{"repeats": [{"committed_step0": v}
                                      for v in b_values]}],
            "stable_control": [{"repeats": [{"committed_step0": v}
                                            for v in c_values]}],
            "tooling_provenance": {
                "executed_under_committed_2611ee1_bytes": True,
                "instrumentation_sha256_at_execution":
                    self.AUTHORITY_SHA,
                "execution_bearing_freeze_instrumentation_sha256":
                    self.AUTHORITY_SHA,
            },
        }

    def pre_freeze_baseline(self):
        # the exact committed shape of the superseded
        # i157-BASE-1789261211 record: anchor A VARIES (would satisfy
        # reproduction on content) but the run executed under the
        # PRE-FREEZE instrumentation bytes (98fa2a80...) — content
        # identical to the retained historical record
        b = self.authoritative_baseline(
            a_values=(107, 818, 3771, 107, 107, 818, 3771, 1437, 107))
        b["source_run"] = "i157-BASE-1789261211"
        b["tooling_provenance"] = {
            "executed_under_committed_2611ee1_bytes": False,
            "instrumentation_sha256_at_execution": (
                "sha256:98fa2a80d893dcae20f373d94064d55c9ab2314"
                "cb868fbe9000e166d667d8d77"),
            "execution_bearing_freeze_instrumentation_sha256":
                self.AUTHORITY_SHA,
        }
        return b

    def varying_replay(self):
        return {
            "chunk1_repeatability": {"byte_identical": True,
                                     "digests": ["d1"] * 3},
            "chunk2_digests": ["x", "y", "z", "x", "y", "w"],
            "chunk2_deterministic": False,
            "no_reuse_proof": {"restore_returns_to_frozen": True,
                               "trials_mutated_state": True},
            "trials": 6,
        }

    def stabilizing_interventions(self):
        # the retained correction-pass SWA-ALLOC shape: control
        # varies, treatment deterministic on both anchors
        def digests(n_distinct, trials=6):
            vals = [f"d{i}" for i in range(n_distinct)]
            return [vals[i % len(vals)] for i in range(trials)]

        return {"swa_alloc": {
            "anchor_a": {
                "control_chunk2_digests": digests(3),
                "treatment_chunk2_digests": ["t"] * 6,
                "control_chunk1_digests": ["c1"] * 6,
                "treatment_chunk1_digests": ["c1"] * 6,
            },
            "anchor_b": {
                "control_chunk2_digests": digests(6),
                "treatment_chunk2_digests": ["t"] * 6,
                "control_chunk1_digests": ["c1"] * 6,
                "treatment_chunk1_digests": ["c1"] * 6,
            },
        }}

    def localized_checkpoints(self):
        return {"checkpoint_digest_matrix": {
            "anchor_a": {"L0_kv_slice_post_write": ["p", "q", "r"],
                         "L0_attention_output": ["p", "q", "r"]},
            "anchor_b": {"L0_kv_slice_post_write": ["p", "q", "r"]},
        }}

    def write_and_reduce(self, baseline, *, replay=None,
                         interventions=None, instr=None):
        (self.dir / "baseline-reproduction.json").write_text(
            json.dumps(baseline))
        (self.dir / "exact-state-replay.json").write_text(
            json.dumps(replay or self.varying_replay()))
        (self.dir / "interventions.json").write_text(
            json.dumps(interventions or self.stabilizing_interventions()))
        (self.dir / "instrumentation-manifest.json").write_text(
            json.dumps(instr or self.localized_checkpoints()))
        out = self.dir / "diagnostic-conclusions.json"
        rc = self.mod.main([])
        self.assertEqual(rc, 0)
        return json.loads(out.read_text())

    def test_1_pre_freeze_base_plus_replay_evidence_not_localized(self):
        """Case 1: non-authoritative BASE + varying replay + localized
        checkpoints + stabilizing intervention => NOT LOCALIZED (the
        replay cannot substitute for Phase-2 authority)."""
        record = self.write_and_reduce(self.pre_freeze_baseline())
        self.assertNotEqual(
            record["terminal"],
            "ISSUE117_ARM_C_CHUNK2_CAUSE_LOCALIZED")
        reasons = record["terminal_requirements"]
        self.assertFalse(reasons["phenomenon_reproduced"])
        self.assertFalse(
            reasons["phase2_baseline_execution_provenance_valid"])
        self.assertEqual(reasons["phenomenon_reproduction_source"],
                         "none_non_authoritative_baseline")
        # the replay variation is still retained as localization
        # evidence — separation, not erasure
        self.assertTrue(
            reasons[
                "phase3_exact_state_varies_retained_as_"
                "localization_evidence"])
        self.assertFalse(
            reasons["phase3_exact_state_substitutes_for_phase2"])
        # non-authoritative BASE with no other reproduction lands on
        # INSUFFICIENT, not LOCALIZED/PARTIAL
        self.assertEqual(
            record["terminal"],
            "ISSUE117_ARM_C_CHUNK2_DIAGNOSTIC_INSUFFICIENT_EVIDENCE")

    def test_2_authoritative_base_fails_reproduction_not_localized(self):
        """Case 2: authoritative BASE that does NOT reproduce (neither
        anchor varies, no lifecycle reason) + varying replay +
        stabilizing intervention => NOT LOCALIZED (INSUFFICIENT), even
        though provenance is valid."""
        baseline = self.authoritative_baseline(
            a_values=(107,) * 4, b_values=(107,) * 4)
        record = self.write_and_reduce(baseline)
        self.assertEqual(
            record["terminal"],
            "ISSUE117_ARM_C_CHUNK2_DIAGNOSTIC_INSUFFICIENT_EVIDENCE")
        reasons = record["terminal_requirements"]
        self.assertTrue(
            reasons["phase2_baseline_execution_provenance_valid"])
        self.assertFalse(reasons["phenomenon_reproduced"])
        self.assertEqual(reasons["phenomenon_reproduction_source"],
                         "none_baseline_did_not_vary")

    def test_3_authoritative_reproducing_base_localized(self):
        """Case 3: authoritative reproducing BASE + existing
        localization + mechanism evidence => LOCALIZED."""
        record = self.write_and_reduce(
            self.authoritative_baseline())
        self.assertEqual(
            record["terminal"],
            "ISSUE117_ARM_C_CHUNK2_CAUSE_LOCALIZED")
        reasons = record["terminal_requirements"]
        self.assertTrue(
            reasons["phase2_baseline_execution_provenance_valid"])
        self.assertTrue(reasons["phenomenon_reproduced"])
        self.assertEqual(reasons["phenomenon_reproduction_source"],
                         "phase2_baseline_anchor_a")

    def test_4_lifecycle_non_reproduction_path(self):
        """Case 4: an explicit lifecycle reason in an AUTHORITATIVE
        BASE that does not reproduce => PARTIAL (issue #157 terminal
        exception); the same reason in a NON-authoritative BASE, or
        manufactured from exact-state variability, stays
        INSUFFICIENT."""
        # 4a: authoritative + explicit lifecycle reason => PARTIAL
        baseline = self.authoritative_baseline(
            a_values=(107,) * 4, b_values=(107,) * 4)
        baseline["anchor_a"][0]["non_reproduction_lifecycle_reason"] = (
            "exact demonstrated lifecycle cause: chunk-2 prefill "
            "unreachable in this substrate because <demonstrated "
            "mechanism>; observed directly, not inferred from absence")
        record = self.write_and_reduce(baseline)
        self.assertEqual(
            record["terminal"],
            "ISSUE117_ARM_C_CHUNK2_DIAGNOSIS_PARTIAL")
        self.assertTrue(record["terminal_requirements"][
            "exact_lifecycle_non_reproduction_reason"])
        # 4b: identical lifecycle reason but NON-authoritative BASE
        # => the exception does not apply => INSUFFICIENT
        baseline_pf = self.pre_freeze_baseline()
        baseline_pf["anchor_a"][0]["non_reproduction_lifecycle_reason"] = (
            baseline["anchor_a"][0]["non_reproduction_lifecycle_reason"])
        record_pf = self.write_and_reduce(baseline_pf)
        self.assertEqual(
            record_pf["terminal"],
            "ISSUE117_ARM_C_CHUNK2_DIAGNOSTIC_INSUFFICIENT_EVIDENCE")
        # 4c: no lifecycle reason anywhere, only exact-state
        # variability => INSUFFICIENT (never manufactured)
        baseline_nl = self.authoritative_baseline(
            a_values=(107,) * 4, b_values=(107,) * 4)
        record_nl = self.write_and_reduce(baseline_nl)
        self.assertFalse(record_nl["terminal_requirements"][
            "exact_lifecycle_non_reproduction_reason"])
        self.assertEqual(
            record_nl["terminal"],
            "ISSUE117_ARM_C_CHUNK2_DIAGNOSTIC_INSUFFICIENT_EVIDENCE")

    def test_5_tampered_base_identity_fails_closed(self):
        """Case 5: tampered BASE run identity/tool hashes fail
        closed — each single-field tamper strips Phase-2 authority
        even when the observational content would reproduce."""
        def tampered(**changes):
            b = self.authoritative_baseline()
            for path, value in changes.items():
                if path == "source_run":
                    b["source_run"] = value
                elif path == "source_run_sha256":
                    b["source_run_sha256"] = value
                elif path == "at_execution":
                    b["tooling_provenance"][
                        "instrumentation_sha256_at_execution"] = value
                elif path == "freeze_pin":
                    b["tooling_provenance"][
                        "execution_bearing_freeze_instrumentation_"
                        "sha256"] = value
                elif path == "flag":
                    b["tooling_provenance"][
                        "executed_under_committed_2611ee1_bytes"] = value
                elif path == "drop_provenance":
                    b.pop("tooling_provenance", None)
            return b

        tamper_matrix = [
            {"source_run": ""},
            {"source_run": None},
            {"source_run_sha256": ""},
            {"at_execution": "sha256:" + "0" * 64},
            {"at_execution": None},
            {"freeze_pin": "sha256:" + "0" * 64},
            {"flag": False},          # flipped boolean alone
            {"flag": None},
            {"flag": "yes"},          # non-boolean truthy (Lane A P2)
            {"flag": 1},
            {"drop_provenance": True},
            # identity substitution (Lane B P1): otherwise-valid
            # provenance naming the OLD superseded pre-freeze run
            {"source_run": "i157-BASE-1789261211"},
        ]
        for changes in tamper_matrix:
            with self.subTest(**changes):
                record = self.write_and_reduce(tampered(**changes))
                reasons = record["terminal_requirements"]
                self.assertFalse(
                    reasons["phase2_baseline_execution_provenance_valid"],
                    f"tamper {changes} must strip Phase-2 authority")
                self.assertFalse(reasons["phenomenon_reproduced"])
                self.assertNotEqual(
                    record["terminal"],
                    "ISSUE117_ARM_C_CHUNK2_CAUSE_LOCALIZED")

    def test_5b_identity_substitution_vs_manifest_pin(self):
        """Lane B P1 (manifest cross-check): an otherwise-valid record
        whose source_run_sha256 does NOT equal the instrumentation
        manifest's retained_run_records pin for the named run must
        fail closed when the manifest pins are available."""
        baseline = self.authoritative_baseline()
        baseline["source_run"] = "i157-BASE-1789309328"
        baseline["source_run_sha256"] = "b" * 64  # wrong pin
        instr = self.localized_checkpoints()
        instr["retained_run_records"] = {
            "i157-BASE-1789309328": "a" * 64,  # the true pin
        }
        record = self.write_and_reduce(baseline, instr=instr)
        reasons = record["terminal_requirements"]
        self.assertFalse(
            reasons["phase2_baseline_execution_provenance_valid"])
        self.assertNotEqual(
            record["terminal"],
            "ISSUE117_ARM_C_CHUNK2_CAUSE_LOCALIZED")
        # and the MATCHING pin keeps authority
        baseline_ok = self.authoritative_baseline()
        baseline_ok["source_run"] = "i157-BASE-1789309328"
        baseline_ok["source_run_sha256"] = "a" * 64
        record_ok = self.write_and_reduce(baseline_ok, instr=instr)
        self.assertTrue(record_ok["terminal_requirements"][
            "phase2_baseline_execution_provenance_valid"])
        # an unknown run id (not in the manifest pins) also fails
        baseline_unknown = self.authoritative_baseline()
        baseline_unknown["source_run"] = "i157-BASE-NOT-PINNED"
        record_unknown = self.write_and_reduce(
            baseline_unknown, instr=instr)
        self.assertFalse(record_unknown["terminal_requirements"][
            "phase2_baseline_execution_provenance_valid"])

    def test_6_generated_conclusion_consumes_fresh_base(self):
        """Case 6: the authoritative generated conclusion must consume
        the FRESH committed-bytes BASE run — never
        i157-BASE-1789261211 (the superseded pre-freeze run)."""
        record = self.write_and_reduce(
            self.authoritative_baseline())
        authority = record["phase2_reproduction_authority"]
        self.assertEqual(authority["source_run"], "i157-BASE-FRESH")
        self.assertNotEqual(authority["source_run"],
                            "i157-BASE-1789261211")
        self.assertTrue(authority["executed_under_committed_2611ee1_bytes"])

        # and against the COMMITTED bundle: the generated record must
        # name the fresh committed-bytes BASE run, never the old
        # pre-freeze run
        bundle = (
            REPO / "docs/implementation/"
            "r6-successor-dense-full-integration-117/evidence/"
            "arm-c-chunk2-diagnosis-157"
        )
        committed = json.loads(
            (bundle / "diagnostic-conclusions.json").read_text())
        committed_auth = committed.get("phase2_reproduction_authority")
        self.assertIsNotNone(committed_auth)
        self.assertNotEqual(
            committed_auth.get("source_run"), "i157-BASE-1789261211")
        self.assertTrue(
            committed_auth.get("executed_under_committed_2611ee1_bytes"))
        # the fresh BASE is ledgered
        ledger = json.loads(
            (bundle / "launch-ledger.json").read_text())
        ids = {e.get("run_id") for e in ledger["launches"]}
        self.assertIn(committed_auth.get("source_run"), ids)


class TestDerivedCountsFollowEvidence(unittest.TestCase):
    """Adversarial regression (maintainer NO-GO item 1): every
    observational count in the generated conclusion summary must
    follow the retained evidence bytes mechanically — a mutated
    digest list or trial count must change the summary, and a
    hard-coded expected count string must fail the negative control.
    """

    def setUp(self):
        self.mod = importlib.import_module("issue157_conclusions")
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.orig_dir = self.mod.EVIDENCE_DIR
        self.mod.EVIDENCE_DIR = self.dir
        # real-shaped retained evidence, copied from the bundle and
        # mutated per test
        src = (
            REPO / "docs/implementation/"
            "r6-successor-dense-full-integration-117/evidence/"
            "arm-c-chunk2-diagnosis-157"
        )
        for name in self.mod.CONSUMED:
            shutil.copy(src / name, self.dir / name)
        self.baseline_d = json.loads(
            (self.dir / "baseline-reproduction.json").read_text())
        self.replay_d = json.loads(
            (self.dir / "exact-state-replay.json").read_text())
        self.iv_d = json.loads(
            (self.dir / "interventions.json").read_text())
        self.instr_d = json.loads(
            (self.dir / "instrumentation-manifest.json").read_text())

    def tearDown(self):
        self.mod.EVIDENCE_DIR = self.orig_dir
        self.tmp.cleanup()

    def _write_mutated(self, *, baseline=None, replay=None,
                       interventions=None):
        # rewrite ONLY mutated inputs: untouched files keep their
        # original bytes so the reducer's input-hash map is stable
        # for the byte-identity regression
        if baseline is not None:
            (self.dir / "baseline-reproduction.json").write_text(
                json.dumps(baseline))
        if replay is not None:
            (self.dir / "exact-state-replay.json").write_text(
                json.dumps(replay))
        if interventions is not None:
            (self.dir / "interventions.json").write_text(
                json.dumps(interventions))
        out = self.dir / "diagnostic-conclusions.json"
        rc = self.mod.main([])
        self.assertEqual(rc, 0)
        return json.loads(out.read_text())

    def test_committed_bundle_regenerates_byte_identically(self):
        """The committed diagnostic-conclusions.json must be exactly
        what the reducer produces from the committed evidence bytes."""
        committed = (
            REPO / "docs/implementation/"
            "r6-successor-dense-full-integration-117/evidence/"
            "arm-c-chunk2-diagnosis-157/diagnostic-conclusions.json"
        )
        self._write_mutated()
        regenerated = (self.dir / "diagnostic-conclusions.json").read_text()
        self.assertEqual(
            committed.read_text(), regenerated,
            "committed conclusions are not the byte-identical "
            "reduction of the committed evidence",
        )

    def test_anchor_b_control_distinct_follows_digests(self):
        """Mutating only the anchor-B control digests (3 distinct while
        trials stay six) must change the derived prose AND the
        structured counts."""
        record = self._mutations_b_control_3_distinct()
        ctrl = record["interventions"]["swa_alloc"]["detail"][
            "per_anchor"]["anchor_b"]["control_chunk2"]
        self.assertEqual(ctrl["trials"], 6)
        self.assertEqual(ctrl["distinct"], 3)
        note = record["per_anchor"]["anchor_b"]["exact_state_level"]["note"]
        self.assertIn("(3 distinct chunk-2 digests / 6 trials)", note)
        # the negative control: the previously hard-coded string must
        # NOT survive a mutation that changes the underlying bytes
        self.assertNotIn("5 distinct", note)
        self.assertNotIn("(6 distinct chunk-2 digests / 6 trials)", note)

    def _mutations_b_control_3_distinct(self):
        iv = json.loads(json.dumps(self.iv_d))
        d = iv["swa_alloc"]["anchor_b"]["control_chunk2_digests"]
        iv["swa_alloc"]["anchor_b"]["control_chunk2_digests"] = [
            d[0], d[1], d[2], d[0], d[1], d[2],
        ]
        return self._write_mutated(interventions=iv)

    def test_anchor_a_control_distinct_follows_digests(self):
        iv = json.loads(json.dumps(self.iv_d))
        d = iv["swa_alloc"]["anchor_a"]["control_chunk2_digests"]
        iv["swa_alloc"]["anchor_a"]["control_chunk2_digests"] = [d[0]] * len(d)
        record = self._write_mutated(interventions=iv)
        ctrl = record["interventions"]["swa_alloc"]["detail"][
            "per_anchor"]["anchor_a"]["control_chunk2"]
        self.assertEqual(ctrl["distinct"], 1)
        self.assertFalse(ctrl["varies"])
        # a non-varying control removes the causal demonstration:
        # the terminal must drop off LOCALIZED, not stay on a literal
        self.assertNotEqual(
            record["terminal"],
            "ISSUE117_ARM_C_CHUNK2_CAUSE_LOCALIZED",
        )

    def test_treatment_trial_count_follows_digests(self):
        iv = json.loads(json.dumps(self.iv_d))
        t = iv["swa_alloc"]["anchor_b"]["treatment_chunk2_digests"]
        iv["swa_alloc"]["anchor_b"]["treatment_chunk2_digests"] = t[:4]
        record = self._write_mutated(interventions=iv)
        trt = record["interventions"]["swa_alloc"]["detail"][
            "per_anchor"]["anchor_b"]["treatment_chunk2"]
        self.assertEqual(trt["trials"], 4)
        self.assertEqual(trt["distinct"], 1)

    def test_replay_distinct_count_follows_digests(self):
        replay = json.loads(json.dumps(self.replay_d))
        d = replay["chunk2_digests"]
        replay["chunk2_digests"] = [
            d[0], d[1], d[0], d[1], d[0], d[1],
        ]
        record = self._write_mutated(replay=replay)
        level = record["per_anchor"]["anchor_a"]["exact_state_level"]
        self.assertEqual(level["distinct_digests"], 2)
        self.assertEqual(level["trials"], 6)
        self.assertIn("(2 distinct digests / 6 trials)", level["note"])
        self.assertNotIn("(6 distinct digests / 6 trials)", level["note"])

    def test_baseline_observation_count_follows_bytes(self):
        baseline = json.loads(json.dumps(self.baseline_d))
        baseline["anchor_b"] = baseline["anchor_b"][:2]  # 2 realizations
        record = self._write_mutated(baseline=baseline)
        obs = record["phenomenon_reproduction"]["anchor_b"]["observations"]
        self.assertEqual(obs, 6)  # 2 realizations x 3 repeats
        note = record["per_anchor"]["anchor_b"]["committed_token_level"][
            "note"]
        self.assertIn("across all 6 baseline observations", note)
        self.assertNotIn("across all 9 baseline observations", note)

    def test_reducer_source_carries_no_observational_count_literals(
            self):
        """Structural negative control: the reducer source may not
        contain the historic hard-coded count strings at all."""
        src = _src("issue157_conclusions.py")
        for banned in (
            "5 distinct", "6 distinct digests / 6 trials",
            "all 9 baseline",
            # retired false-statement shape (second NO-GO): the
            # reducer must never again assert absence from EVERY
            # retained observation — recurrence is Anchor-A-scoped
            "absent from every retained observation",
        ):
            self.assertNotIn(
                banned, src,
                f"reducer source carries observational literal: {banned}",
            )


class TestInstrumentationArming(unittest.TestCase):
    def test_deep_capture_rule_is_chunk2_shape_only(self):
        import issue157_instrumentation as instr

        self.assertEqual(instr.CHUNK_ROWS, 64)
        self.assertEqual(instr.CHUNK2_MAX_ROWS, 8)
        # arming predicate: start >= 64 and 1 <= rows <= 8, role first
        import types

        sink = types.SimpleNamespace(write=lambda *a, **k: None)
        obs = instr.Chunk2Observer(sink)
        self.assertTrue(obs.begin_call(
            role="first", start=64, rows=3, token_ids=None, hidden=None))
        self.assertFalse(obs.begin_call(
            role="first", start=0, rows=64, token_ids=None, hidden=None))
        self.assertFalse(obs.begin_call(
            role="first", start=64, rows=9, token_ids=None, hidden=None))
        self.assertFalse(obs.begin_call(
            role="middle", start=64, rows=3, token_ids=None, hidden=None))

    def test_records_only_while_armed(self):
        import types

        import issue157_instrumentation as instr

        sink_rows = []
        sink2 = types.SimpleNamespace(
            write=lambda kind, payload: sink_rows.append((kind, payload)))
        obs2 = instr.Chunk2Observer(sink2)
        obs2.begin_call(role="first", start=64, rows=3, token_ids=None,
                        hidden=None)
        obs2.raw("x", 1)
        obs2.end_call({})
        self.assertEqual(len(sink_rows), 1)
        # payload carries the call identity and its records
        self.assertEqual(sink_rows[0][1]["call"]["rows"], 3)
        self.assertEqual(sink_rows[0][1]["records"][0]["checkpoint"], "x")
        # disarmed observers record nothing further
        obs2.raw("y", 2)
        self.assertEqual(len(sink_rows), 1)


class TestCrossAnchorRecurrenceControls(unittest.TestCase):
    """Adversarial regression (second maintainer NO-GO, recurrence
    block): the Anchor-A recurrence must derive from the retained
    ANCHOR-A observations only.  Mutating Anchor B must never change
    it; mutating Anchor A must; a binding that disagrees with the
    independently derived recurrence must fail the reduction closed;
    and the generated record may never again state that a value is
    absent from every retained observation while it exists in the
    retained Anchor-A observations.
    """

    def setUp(self):
        self.mod = importlib.import_module("issue157_conclusions")
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.orig_dir = self.mod.EVIDENCE_DIR
        self.mod.EVIDENCE_DIR = self.dir
        src = (
            REPO / "docs/implementation/"
            "r6-successor-dense-full-integration-117/evidence/"
            "arm-c-chunk2-diagnosis-157"
        )
        for name in self.mod.CONSUMED:
            shutil.copy(src / name, self.dir / name)
        self.baseline_d = json.loads(
            (self.dir / "baseline-reproduction.json").read_text())

    def tearDown(self):
        self.mod.EVIDENCE_DIR = self.orig_dir
        self.tmp.cleanup()

    def _reduce(self, baseline):
        (self.dir / "baseline-reproduction.json").write_text(
            json.dumps(baseline))
        rc = self.mod.main([])
        self.assertEqual(rc, 0)
        return json.loads(
            (self.dir / "diagnostic-conclusions.json").read_text())

    def _recurrence(self, record):
        return record["per_anchor"]["anchor_a"][
            "committed_token_level"]["accepted_value_recurrence"]

    def _note(self, record):
        return record["per_anchor"]["anchor_a"][
            "committed_token_level"]["note"]

    @staticmethod
    def _set_anchor_values(baseline, anchor, values):
        rows = baseline[anchor]
        # distribute the values across the retained repeats in order,
        # keeping the realizations/repeats structure intact
        flat = list(values)
        i = 0
        for realization in rows:
            for repeat in realization.get("repeats", []):
                if i < len(flat):
                    repeat["committed_step0"] = flat[i]
                    i += 1
        assert i == len(flat), "value count exceeds retained repeats"

    def test_recurrence_reflects_retained_bytes(self):
        """The committed evidence's derived recurrence is exactly the
        expected reduction of the retained Anchor-A bytes (fresh
        authoritative BASE i157-BASE-1789309328): {107, 818} recur,
        {1437, 3771} accepted-but-not-observed, {6455, 9366, 14937}
        other observed."""
        record = self._reduce(json.loads(json.dumps(self.baseline_d)))
        rec = self._recurrence(record)
        self.assertEqual(rec["accepted_values"], [107, 818, 1437, 3771])
        self.assertEqual(rec["recurring_values"], [107, 818])
        self.assertEqual(rec["accepted_values_not_observed"],
                         [1437, 3771])
        self.assertEqual(rec["other_observed_values"],
                         [6455, 9366, 14937])

    def test_control_a_anchor_a_recurrence_ignores_anchor_b(self):
        """Control A: accepted Anchor-A values include X and Y, Anchor
        A observes both, Anchor B observes only X (and could never
        supply Y) — the recurrence must contain both X and Y."""
        baseline = json.loads(json.dumps(self.baseline_d))
        # accepted X=107, Y=818 (retained binding unchanged); Anchor A
        # observes both; Anchor B observes ONLY X=107 everywhere.
        self._set_anchor_values(baseline, "anchor_a",
                                [107, 107, 818, 107, 818, 107, 107,
                                 818, 107])
        self._set_anchor_values(baseline, "anchor_b",
                                [107] * 9)
        # binding must agree with the derived Anchor-A recurrence
        record = self._reduce(baseline)
        rec = self._recurrence(record)
        self.assertIn(107, rec["recurring_values"])
        self.assertIn(818, rec["recurring_values"])
        self.assertNotIn(818, rec["accepted_values_not_observed"])
        self.assertNotIn("818", [
            str(v) for v in rec["accepted_values_not_observed"]])

    def test_control_b_anchor_b_mutation_cannot_change_recurrence(self):
        """Control B: Anchor A and the accepted binding fixed, Anchor
        B values changed radically — the structured recurrence fields
        and the generated prose must remain unchanged."""
        first = self._reduce(json.loads(json.dumps(self.baseline_d)))
        baseline = json.loads(json.dumps(self.baseline_d))
        self._set_anchor_values(
            baseline, "anchor_b",
            [424242, 424242, 999999, 7, 7, 424242, 999999, 7, 12345])
        second = self._reduce(baseline)
        self.assertEqual(self._recurrence(first), self._recurrence(second))
        self.assertEqual(self._note(first), self._note(second))

    def test_control_c_anchor_a_mutation_changes_recurrence(self):
        """Control C: remove one accepted recurring value (818) from
        the Anchor-A observations — the derived recurrence must drop
        it (to accepted-but-not-observed)."""
        baseline = json.loads(json.dumps(self.baseline_d))
        # original Anchor-A values: [107, 258882, 107, 107, 236774,
        # 107, 107, 818, 100]; replace every 818 with a non-accepted
        # value
        self._set_anchor_values(baseline, "anchor_a",
                                [107, 258882, 107, 107, 236774,
                                 107, 107, 236774, 100])
        # keep the retained binding consistent with the new derived
        # recurrence ([107] only) so this control isolates the
        # recurrence derivation, not the binding cross-check
        baseline["accepted_137_binding"][
            "recurred_in_this_baseline"] = [107]
        record = self._reduce(baseline)
        rec = self._recurrence(record)
        self.assertEqual(rec["recurring_values"], [107])
        self.assertIn(818, rec["accepted_values_not_observed"])

    def test_control_d_binding_disagreement_fails_closed(self):
        """Control D: mutate accepted_137_binding.
        recurred_in_this_baseline so it disagrees with the
        independently derived Anchor-A recurrence — the reducer must
        fail, not silently choose either side."""
        baseline = json.loads(json.dumps(self.baseline_d))
        baseline["accepted_137_binding"][
            "recurred_in_this_baseline"] = [107]
        (self.dir / "baseline-reproduction.json").write_text(
            json.dumps(baseline))
        with self.assertRaises(self.mod.ReductionError) as ctx:
            self.mod.main([])
        self.assertIn("cross-check failed", str(ctx.exception))

    def test_control_e_no_false_absence_statement(self):
        """Control E (historical regression, structural): the
        generated conclusion may never contain a statement equivalent
        to '818 absent from every retained observation' while 818
        exists in the retained Anchor-A observations — asserted
        structurally, not by matching one exact prose sentence."""
        baseline = json.loads(json.dumps(self.baseline_d))
        # 818 IS in the retained Anchor-A observations
        a_values = [
            r["committed_step0"]
            for realization in baseline["anchor_a"]
            for r in realization.get("repeats", [])
        ]
        self.assertIn(818, a_values)
        record = self._reduce(baseline)
        note = self._note(record)
        rec = self._recurrence(record)
        # 818 recurs, so it can never be listed as absent
        self.assertIn(818, rec["recurring_values"])
        self.assertNotIn("818", [
            str(v) for v in rec["accepted_values_not_observed"]])
        # the historic false claim shape is gone: no value present in
        # the Anchor-A observations may be described as absent from
        # every retained observation
        self.assertNotIn("absent from every retained observation", note)
        # and every value named in the not-observed list must actually
        # be absent from the retained Anchor-A observations
        observed = set(a_values)
        for v in rec["accepted_values_not_observed"]:
            self.assertNotIn(v, observed)

    def test_control_e_committed_record_carries_structured_recurrence(
            self):
        """The committed bundle must carry the structured recurrence
        fields (prose is never the only authority)."""
        committed = (
            REPO / "docs/implementation/"
            "r6-successor-dense-full-integration-117/evidence/"
            "arm-c-chunk2-diagnosis-157/diagnostic-conclusions.json"
        )
        record = json.loads(committed.read_text())
        rec = record["per_anchor"]["anchor_a"][
            "committed_token_level"]["accepted_value_recurrence"]
        self.assertEqual(rec["recurring_values"], [107, 818])
        self.assertEqual(rec["accepted_values_not_observed"],
                         [1437, 3771])
        self.assertEqual(rec["other_observed_values"],
                         [6455, 9366, 14937])
        note = record["per_anchor"]["anchor_a"][
            "committed_token_level"]["note"]
        self.assertNotIn("absent from every retained observation", note)


class TestBaseArmProvenanceRecord(unittest.TestCase):
    """BASE-arm provenance authority (2026-09-13 physical-authority
    correction): the fresh Phase-2 BASE run i157-BASE-1789309328
    executed under the committed 2611ee1 bytes and is the Phase-2
    authority; the pre-freeze i157-BASE-1789261211 is superseded,
    retained as historical evidence only, and every corroboration
    claim binds to bytes that exist in the retained committed runs."""

    BUNDLE = REPO / (
        "docs/implementation/r6-successor-dense-full-integration-117/"
        "evidence/arm-c-chunk2-diagnosis-157")

    def _load(self):
        return json.loads(
            (self.BUNDLE / "baseline-reproduction.json").read_text())

    def test_base_tooling_provenance_disclosed(self):
        b = self._load()
        tp = b["tooling_provenance"]
        self.assertIsInstance(tp, dict)
        self.assertTrue(tp["executed_under_committed_2611ee1_bytes"])
        self.assertEqual(
            tp["instrumentation_sha256_at_execution"],
            "sha256:00a1c2c1452f87ca56289eeb3716e9cd"
            "08ba1c5a36e7d06ac6abdb79283024fc")
        self.assertEqual(
            tp["execution_bearing_freeze_instrumentation_sha256"],
            "sha256:00a1c2c1452f87ca56289eeb3716e9cd"
            "08ba1c5a36e7d06ac6abdb79283024fc")
        # the superseded pre-freeze run is disclosed, never concealed
        sup = tp["superseded_run"]
        self.assertEqual(sup["run_id"], "i157-BASE-1789261211")
        self.assertIn("sha256:98fa2a80",
                      sup["instrumentation_sha256_at_execution"])
        self.assertEqual(b["source_run"], "i157-BASE-1789309328")

    def test_corroboration_digests_match_committed_runs(self):
        b = self._load()
        iv = json.loads((self.BUNDLE / "interventions.json").read_text())
        rp = json.loads((self.BUNDLE / "exact-state-replay.json").read_text())
        # anchor-A chunk-1 digest of the FRESH BASE must appear in the
        # committed REPLAY boundary and in the committed SWA-ALLOC
        # chunk-1 digests (chunk-1 is deterministic across runs)
        a = b["anchor_a_chunk1_boundary_digests"][0]
        self.assertEqual(len(set(b["anchor_a_chunk1_boundary_digests"])), 1)
        self.assertIn(a, set(iv["swa_alloc"]["anchor_a"]
                                 ["control_chunk1_digests"]
                                 + iv["swa_alloc"]["anchor_a"]
                                 ["treatment_chunk1_digests"]))
        self.assertIn(a, json.dumps(rp))
        # anchor-B chunk-1 digest must appear in the committed
        # SWA-ALLOC anchor-B chunk-1 digests
        bb = b["anchor_b_chunk1_boundary_digests"][0]
        self.assertEqual(len(set(b["anchor_b_chunk1_boundary_digests"])), 1)
        self.assertIn(bb, set(iv["swa_alloc"]["anchor_b"]
                                  ["control_chunk1_digests"]
                                  + iv["swa_alloc"]["anchor_b"]
                                  ["treatment_chunk1_digests"]))
        # every cited run id must exist in the retained ledger
        ledger = json.loads((self.BUNDLE / "launch-ledger.json").read_text())
        ids = {e.get("run_id") for e in ledger["launches"]}
        self.assertIn("i157-REPLAY-1789269282", ids)
        self.assertIn("i157-IV-SWA-ALLOC-1789269642", ids)
        self.assertIn("i157-BASE-1789309328", ids)
        # the controls actually vary as claimed (retained bytes)
        ca = iv["swa_alloc"]["anchor_a"]["control_chunk2_digests"]
        cb = iv["swa_alloc"]["anchor_b"]["control_chunk2_digests"]
        self.assertEqual(len(set(ca)), 3)
        self.assertEqual(len(set(cb)), 6)

    def test_ledger_and_authority_claims_are_truthful(self):
        ledger = json.loads((self.BUNDLE / "launch-ledger.json").read_text())
        by_id = {}
        for e in ledger["launches"]:
            by_id.setdefault(e.get("run_id"), []).append(e)
        # BOTH BASE runs are ledgered: the old run preserved...
        self.assertEqual(len(by_id["i157-BASE-1789261211"]), 1)
        self.assertNotIn("superseded by the correction-pass-1 rerun",
                         by_id["i157-BASE-1789261211"][0]["tooling_note"])
        # ...and explicitly superseded for Phase-2 authority only
        self.assertEqual(
            by_id["i157-BASE-1789261211"][0].get(
                "superseded_for_phase2_authority_by"),
            "i157-BASE-1789309328")
        # ...by the fresh run, which exists exactly once
        self.assertEqual(len(by_id["i157-BASE-1789309328"]), 1)
        auth = json.loads(
            (self.BUNDLE / "physical-diagnostic-authority.json").read_text())
        note = auth["instrumentation"]["hash_history"][
            "correction_pass_1_commit_2611ee1"]["note"]
        # the false blanket claim must not be asserted as fact; the
        # only permitted occurrence is inside the correction sentence
        # that quotes it as the corrected-away inaccuracy
        self.assertNotIn(
            "ALL evidence-bearing arms were RERUN under the "
            "committed bytes", note)
        self.assertIn("NOT rerun", note)
        # the fresh BASE supersession is recorded in the authority
        pac = auth["instrumentation"]["hash_history"].get(
            "physical_authority_correction_2026_09_13")
        self.assertIsNotNone(pac)
        self.assertEqual(pac["authoritative_base_run"],
                         "i157-BASE-1789309328")
        self.assertEqual(pac["superseded_run"], "i157-BASE-1789261211")

    def test_observation_bytes_follow_fresh_run_record(self):
        # the committed Phase-2 observations must be byte-derived from
        # the retained fresh run record (hash-pinned in the
        # instrumentation manifest), not from the old pre-freeze run
        import hashlib
        b = self._load()
        im = json.loads(
            (self.BUNDLE / "instrumentation-manifest.json").read_text())
        pinned = im["retained_run_records"]["i157-BASE-1789309328"]
        self.assertEqual(pinned, b["source_run_sha256"])
        # anchor observations derive mechanically from the run rows:
        # 9 observations per case, 3 realizations x 3 repeats
        for case in ("anchor_a", "anchor_b", "stable_control"):
            rows = b[case]
            self.assertEqual(len(rows), 3)
            for row in rows:
                self.assertEqual(len(row["repeats"]), 3)


class TestPostProcessingPinCurrency(unittest.TestCase):
    """Recurrence prevention for the stale post-processing self-pin.

    The authority record's instrumentation.post_processing_files pin for
    scripts/issue157_conclusions.py drifted stale once already (the
    adversarial-review round-2 reducer correction at 0ecdb1c changed the
    reducer without refreshing the pin).  This test recomputes the pin
    from the CURRENT reducer bytes every run, so any future reducer
    correction that does not update the pin fails here.
    """

    REDUCER = SCRIPTS / "issue157_conclusions.py"
    BUNDLE = REPO / (
        "docs/implementation/r6-successor-dense-full-integration-117/"
        "evidence/arm-c-chunk2-diagnosis-157")

    def test_current_reducer_pin_matches_actual_bytes(self):
        import hashlib
        actual = "sha256:" + hashlib.sha256(
            self.REDUCER.read_bytes()).hexdigest()
        auth = json.loads(
            (self.BUNDLE / "physical-diagnostic-authority.json").read_text())
        pinned = auth["instrumentation"]["post_processing_files"][
            "scripts/issue157_conclusions.py"]
        self.assertEqual(
            pinned, actual,
            "physical-diagnostic-authority.json post_processing_files pin "
            "for scripts/issue157_conclusions.py is stale: the reducer "
            "changed without updating the current post-processing pin "
            "(append a post_evidence_reducer_amendments entry and refresh "
            "the pin in the same change)")

    def test_latest_amendment_pins_current_reducer(self):
        import hashlib
        actual = hashlib.sha256(
            self.REDUCER.read_bytes()).hexdigest()
        auth = json.loads(
            (self.BUNDLE / "physical-diagnostic-authority.json").read_text())
        amendments = auth["instrumentation"][
            "post_evidence_reducer_amendments"]
        self.assertGreaterEqual(len(amendments), 1)
        self.assertEqual(
            amendments[-1]["corrected_reducer_sha256"], actual,
            "the newest post_evidence_reducer_amendments entry must "
            "document the reducer bytes currently at head")


class TestPartitionContract(unittest.TestCase):
    def test_anchor_partitions_satisfy_coverage_invariants(self):
        sys.path.insert(0, str(SCRIPTS))
        import issue157_binding as b

        for case, spec in b.ANCHOR_PARTITION.items():
            chunks = spec["chunks"]
            self.assertEqual(sum(chunks), spec["prompt_len"], case)
            self.assertEqual(chunks[0], 64) if len(chunks) > 1 else None
            offset = 0
            for count in chunks:
                self.assertGreaterEqual(count, 1)
                offset += count
            self.assertEqual(offset, spec["prompt_len"], case)
            for count in chunks[1:]:
                self.assertLessEqual(count, 64)
                self.assertGreaterEqual(count, 1)


if __name__ == "__main__":
    unittest.main()

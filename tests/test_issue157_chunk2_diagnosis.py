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
        body = body.split("def baseline_reproduces(")[0]
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

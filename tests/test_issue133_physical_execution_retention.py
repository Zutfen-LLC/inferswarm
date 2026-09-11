"""Issue #133 physical-execution retention tests — correction round for
maintainer review 5172615768.

Three test families:

* ``PhysicalEvidenceSet`` / ``TerminalReductionDerivations`` — the
  retained evidence set and the re-derived terminal document (asserts
  the CORRECTED derivation results, not authored ones).
* ``PristineReducerRuns`` — executes the corrected reducers against the
  pristine retained evidence through explicit paths.
* ``MutationControls`` — REAL isolated mutation tests.  Every control
  copies the evidence tree to a scratch directory, mutates exactly one
  thing, re-runs the reducer(s) against the COPY, and asserts the
  terminal/equality derivation fails or changes appropriately.  The
  pristine repository evidence is never read by a mutation control.

Covered mutations (review-mandated list):

1.  one ordinary committed token changed;
2.  one direct committed token changed;
3.  one ordinary base prompt token changed;
4.  one pre-divergence replay prefix differs (direct transcript);
5.  one runtime session id differs;
6.  one runtime plan digest differs;
7.  one accepted commit uses the wrong position;
8.  one Source open injected into the strace audit;
9.  one participant substrate file digest drifts;
10. tokenizer render equality becomes 23/24;
11. a prelaunch verdict becomes false;
12. driver post-run identity differs (repo driver bytes vs freeze pin);
13. Coordinator CUDA evidence becomes nonzero;
14. Coordinator weight/bulk evidence becomes nonzero;
15. Launch 1 changed to contain a correctness-bearing observation;
16. one controlled fencing injection becomes accepted;
17. equality artifact forged to claim 24/24 despite raw mismatch.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EV = ROOT / ("docs/implementation/r6-successor-dense-full-integration-117"
             "/evidence/arm-c-retry")
PE = EV / "physical-execution"
VENV_PY = os.environ.get("ARM_C_RETRY_TEST_PYTHON")  # tokenizer-capable

# The equality reducer needs transformers; skip those controls when the
# campaign venv is unavailable (plain python3 runs the terminal reducer,
# which is pure stdlib).


def _venv() -> str:
    global VENV_PY
    if VENV_PY:
        return VENV_PY
    for cand in ("/tmp/is133-venv/bin/python",):
        if Path(cand).is_file():
            VENV_PY = cand
            return cand
    VENV_PY = ""
    return ""


def load(rel: str) -> dict:
    return json.loads((PE / rel).read_text())


def edit_json(path: Path, fn) -> None:
    doc = json.loads(path.read_text())
    fn(doc)
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")


class ScratchEvidence:
    """Isolated copy of the retained evidence tree for mutation tests."""

    repo_root: Path | None = None

    def __init__(self, testcase: unittest.TestCase):
        self.tmp = tempfile.mkdtemp(prefix="armc2-mut-")
        testcase.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.root = Path(self.tmp)
        # evidence tree only (no git history needed by the reducers)
        shutil.copytree(
            EV, self.root / "arm-c-retry",
            ignore=shutil.ignore_patterns("__pycache__"))
        self.pe = self.root / "arm-c-retry/physical-execution"

    def run_terminal(self) -> dict:
        env = dict(os.environ)
        env["ARM_C_RETRY_REPO_ROOT"] = str(ROOT)
        # driver post-run identity: point the reducer's repo-root seam at
        # a scratch copy when the control mutates repo files; otherwise
        # the REAL frozen driver pin is exactly what we check against.
        if getattr(self, "repo_root", None):
            env["ARM_C_RETRY_REPO_ROOT"] = str(self.repo_root)
        proc = subprocess.run(
            [sys.executable,
             str(ROOT / "scripts/issue133_terminal_reduction.py"),
             str(self.pe)],
            capture_output=True, text=True, env=env)
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError:
            return {"terminal": "REDUCER_CRASH", "stderr": proc.stderr,
                    "problems": ["reducer crashed"]}

    def run_equality(self) -> dict:
        py = _venv()
        if not py:
            raise unittest.SkipTest("tokenizer venv unavailable")
        proc = subprocess.run(
            [py, str(ROOT / "scripts/issue133_equality_reduction.py"),
             str(self.pe / "direct"),
             str(self.pe / "ordinary-http/ordinary-campaign.json"),
             str(self.pe / "ordinary-http/serving-report.json"),
             str(self.root / "arm-c-retry/frozen-tokenizer/assets"),
             str(self.pe / "equality-reduction.json")],
            capture_output=True, text=True)
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError:
            return {"passed": None, "problems": ["reducer crashed"],
                    "stderr": proc.stderr}


class PhysicalEvidenceSet(unittest.TestCase):
    def test_required_files_present(self) -> None:
        required = [
            "terminal-reduction.json", "equality-reduction.json",
            "strace-audit.json", "strace-raw-pins.json",
            "substrate-reconciliation-01.json",
            "substrate-reconciliation-03.json",
            "last-stage-direct.json", "last-stage-ordinary.json",
            "attempts/armc-retry-physical-1.json",
            "attempts/launch1-failure.log",
            "attempts/execution-plan.launch1.json",
            "direct/direct-run.json",
            "ordinary-http/ordinary-campaign.json",
            "ordinary-http/serving-report.json",
            "ordinary-http/fencing-arm.json",
            "ordinary-http/coordinator-observation-pre.json",
            "ordinary-http/coordinator-observation-post.json",
            "ordinary-http/coordinator-config.json",
            "ordinary-http/serving-evidence.json",
            "preflight/prelaunch-verdict-run1.json",
            "preflight/prelaunch-verdict-immediate-prelaunch.json",
            "preflight/tokenizer-deployment-proof.json",
            "preflight/host-preflight-01.json",
            "preflight/host-preflight-03.json",
            "../execution-freeze.json", "../physical-campaign-authority.json",
            "../prompt-fixture.json", "../gpu-identity-observation.json",
            "../integrity.json",
        ]
        for rel in required:
            self.assertTrue((PE / rel).is_file(), rel)

    def test_24_cases_each_arm(self) -> None:
        self.assertEqual(
            len(list((PE / "direct").glob("direct-c109-*.json"))), 24)
        self.assertEqual(
            len(list((PE / "ordinary-http").glob("ordinary-c109-*.json"))),
            24)


class TerminalReductionDerivations(unittest.TestCase):
    def setUp(self) -> None:
        self.terminal = load("terminal-reduction.json")

    def test_schema_is_corrected_v3(self) -> None:
        self.assertEqual(
            self.terminal["schema"],
            "inferswarm.issue133.arm-c-retry.terminal-reduction/3")

    def test_terminal_is_semantic_fail(self) -> None:
        self.assertEqual(
            self.terminal["terminal"], "ISSUE117_ARM_C_ORDINARY_SERVING_FAIL")

    def test_no_infrastructure_problems(self) -> None:
        self.assertEqual(self.terminal["problems"], [])

    def test_equality_18_of_24_all_regime4(self) -> None:
        eq = self.terminal["equality"]
        self.assertEqual(eq["equal"], 18)
        self.assertEqual(eq["of"], 24)
        self.assertEqual(len(eq["mismatched_cases"]), 6)
        self.assertTrue(all(
            c.startswith("c109-04") for c in eq["mismatched_cases"]))
        self.assertTrue(eq["all_mismatches_regime_4"])

    def test_first_divergence_positions_derived(self) -> None:
        fdiv = self.terminal["equality"]["first_divergent_positions"]
        self.assertEqual(len(fdiv), 6)
        self.assertEqual(fdiv["c109-04-01-026"], 4)
        self.assertEqual(fdiv["c109-04-02-047"], 0)
        self.assertEqual(fdiv["c109-04-03-040"], 2)
        self.assertEqual(fdiv["c109-04-04-024"], 3)
        self.assertEqual(fdiv["c109-04-05-043"], 0)
        self.assertEqual(fdiv["c109-04-06-074"], 0)

    def test_pre_divergence_invocation_equivalence_proven(self) -> None:
        self.assertTrue(
            self.terminal["equality"]
            ["pre_divergence_invocation_equivalence"])

    def test_http_content_characterized(self) -> None:
        http = self.terminal["http_content"]
        self.assertTrue(http["all_bind_frozen_incremental_decode"])
        self.assertEqual(
            sorted(http["cases_differing_from_one_shot_decode"]),
            ["c109-04-02-047", "c109-04-03-040",
             "c109-04-04-024", "c109-04-05-043"])
        self.assertIn("non-prefix-stable", http["classification"])

    def test_launch1_derived_pre_observation(self) -> None:
        lin = self.terminal["launch_lineage"]
        self.assertTrue(lin["launch1_dependency_failure"])
        self.assertEqual(lin["launch1_case_observations"], [])
        self.assertEqual(
            lin["launch1_derived_classification"],
            "PRE_OBSERVATION_INFRASTRUCTURE")

    def test_all_zero_invariants_hold(self) -> None:
        z = self.terminal["zero_invariants"]
        for key in ("stale_session_commits", "wrong_session_commits",
                    "stale_plan_commits", "wrong_plan_commits",
                    "stale_epoch_commits", "wrong_epoch_commits",
                    "wrong_position_commits",
                    "unattributed_correctness_bearing_commits",
                    "coordinator_cuda_initialized",
                    "coordinator_model_weight_bytes_received",
                    "coordinator_model_weight_bytes_materialized",
                    "coordinator_bulk_artifact_bytes_observed"):
            self.assertEqual(z[key], 0, key)
        self.assertGreaterEqual(
            z["controlled_fencing_injections_rejected"], 2)

    def test_zero_invariant_evidence_ladder_documented(self) -> None:
        lad = self.terminal["invariant_evidence"]
        for key in ("fencing_attribution", "coordinator", "substrate",
                    "tokenizer", "prelaunch"):
            self.assertIn(key, lad)


class PristineReducerRuns(unittest.TestCase):
    """Corrected reducers against the pristine retained evidence."""

    def test_terminal_reducer_pristine(self) -> None:
        env = dict(os.environ)
        env["ARM_C_RETRY_REPO_ROOT"] = str(ROOT)
        proc = subprocess.run(
            [sys.executable,
             str(ROOT / "scripts/issue133_terminal_reduction.py"),
             str(PE)],
            capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        doc = json.loads(proc.stdout)
        self.assertEqual(doc["terminal"],
                         "ISSUE117_ARM_C_ORDINARY_SERVING_FAIL")
        self.assertEqual(doc["problems"], [])

    def test_equality_reducer_pristine(self) -> None:
        if not _venv():
            self.skipTest("tokenizer venv unavailable")
        proc = subprocess.run(
            [_venv(), str(ROOT / "scripts/issue133_equality_reduction.py"),
             str(PE / "direct"),
             str(PE / "ordinary-http/ordinary-campaign.json"),
             str(PE / "ordinary-http/serving-report.json"),
             str(EV / "frozen-tokenizer/assets")],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1)  # FAIL path: 18/24
        doc = json.loads(proc.stdout)
        self.assertEqual(doc["equal_count"], 18)
        self.assertEqual(doc["problems"], [])
        self.assertTrue(doc["invocation_equivalence"]["holds"])


def _mut(rel: str, fn):
    """Build a ScratchEvidence mutation helper closure."""
    def apply(scratch: ScratchEvidence):
        edit_json(scratch.pe / rel, fn)
    return apply


class MutationControls(unittest.TestCase):
    """Every control mutates an isolated COPY and re-runs the reducer."""

    SEMANTIC = "ISSUE117_ARM_C_ORDINARY_SERVING_FAIL"

    def _terminal_changes(self, mutate, *, expect_not=None) -> dict:
        scratch = ScratchEvidence(self)
        mutate(scratch)
        doc = scratch.run_terminal()
        if expect_not is not None:
            self.assertNotEqual(doc.get("terminal"), expect_not,
                                json.dumps(doc.get("problems"))[:400])
        self.assertNotEqual(doc.get("terminal"), "REDUCER_CRASH")
        return doc

    # 1. ordinary committed token changed (request + ledger + events +
    #    runtime session all carry the id; mutate the request record)
    def test_control_ordinary_committed_token(self) -> None:
        def mutate(scratch):
            def fn(doc):
                doc["coordinator_scope"]["requests"][0][
                    "generated_token_ids"][0] += 1
            edit_json(scratch.pe / "ordinary-http/serving-report.json", fn)
        doc = self._terminal_changes(mutate, expect_not=self.SEMANTIC)
        self.assertTrue(doc["problems"])

    # 2. direct committed token changed (per-case file + direct-run
    #    results)
    def test_control_direct_committed_token(self) -> None:
        def mutate(scratch):
            def fn(doc):
                doc["results"][0]["generated_token_ids"][0] += 1
            edit_json(scratch.pe / "direct/direct-run.json", fn)
            def fn2(doc):
                doc["generated_token_ids"][0] += 1
            edit_json(scratch.pe / "direct/direct-c109-01-01-045.json", fn2)
        # direct-side mutation alone must at minimum surface as an
        # attribution/consistency problem or changed equality verdict
        doc = self._terminal_changes(mutate, expect_not=self.SEMANTIC)
        self.assertTrue(doc["problems"])

    # 3. ordinary base prompt token changed (request + fixture binding)
    def test_control_ordinary_prompt_token(self) -> None:
        def mutate(scratch):
            def fn(doc):
                doc["coordinator_scope"]["requests"][0][
                    "prompt_token_ids"][0] += 1
            edit_json(scratch.pe / "ordinary-http/serving-report.json", fn)
        doc = self._terminal_changes(mutate, expect_not=self.SEMANTIC)
        self.assertTrue(any("prompt" in p for p in doc["problems"]))

    # 4. pre-divergence replay prefix differs (direct transcript call 0
    #    input); needs the equality reducer to re-derive
    def test_control_pre_divergence_prefix(self) -> None:
        if not _venv():
            self.skipTest("tokenizer venv unavailable")
        scratch = ScratchEvidence(self)

        def fn(doc):
            doc["invocation_transcript"][0]["calls"][0][
                "prompt_token_ids"][0] += 1
        edit_json(scratch.pe / "direct/direct-run.json", fn)
        eq = scratch.run_equality()
        self.assertFalse(eq["invocation_equivalence"]["holds"])

    # 5. runtime session id differs
    def test_control_runtime_session_id(self) -> None:
        def mutate(scratch):
            def fn(doc):
                doc["epochs"][0]["runtime_sessions"][8][
                    "session_id"] += 1
            edit_json(scratch.pe / "ordinary-http/serving-report.json", fn)
        doc = self._terminal_changes(mutate, expect_not=self.SEMANTIC)
        self.assertTrue(doc["problems"])

    # 6. runtime plan digest differs
    def test_control_runtime_plan_digest(self) -> None:
        def mutate(scratch):
            def fn(doc):
                doc["epochs"][0]["runtime_sessions"][0][
                    "plan_digest"] = "sha256:" + "0" * 64
            edit_json(scratch.pe / "ordinary-http/serving-report.json", fn)
        doc = self._terminal_changes(mutate, expect_not=self.SEMANTIC)
        self.assertTrue(doc["problems"])

    # 7. accepted commit uses the wrong position
    def test_control_wrong_position_commit(self) -> None:
        def mutate(scratch):
            def fn(doc):
                doc["coordinator_scope"]["requests"][0][
                    "token_events"][3]["position"] = 6
            edit_json(scratch.pe / "ordinary-http/serving-report.json", fn)
        doc = self._terminal_changes(mutate, expect_not=self.SEMANTIC)
        z = doc["zero_invariants"]
        self.assertEqual(z["wrong_position_commits"], 1)

    # 8. one Source open injected into the strace audit
    def test_control_source_open_injected(self) -> None:
        def mutate(scratch):
            def fn(doc):
                t = doc["traces"]["direct-01"]
                t["source_models_opens"] = 1
            edit_json(scratch.pe / "strace-audit.json", fn)
        doc = self._terminal_changes(mutate, expect_not=self.SEMANTIC)
        self.assertTrue(any("Source opens != 0" in p
                            for p in doc["problems"]))

    # 9. participant substrate file digest drifts
    def test_control_substrate_digest_drift(self) -> None:
        def mutate(scratch):
            def fn(doc):
                doc["rows"][0]["sha256_ok"] = False
            edit_json(scratch.pe / "substrate-reconciliation-01.json", fn)
        doc = self._terminal_changes(mutate, expect_not=self.SEMANTIC)
        self.assertTrue(any("substrate" in p for p in doc["problems"]))

    # 10. tokenizer render equality 23/24
    def test_control_tokenizer_render_23(self) -> None:
        def mutate(scratch):
            def fn(doc):
                doc["equal_count"] = 23
            edit_json(
                scratch.pe / "preflight/tokenizer-deployment-proof.json",
                fn)
        doc = self._terminal_changes(mutate, expect_not=self.SEMANTIC)
        self.assertTrue(any("tokenizer" in p for p in doc["problems"]))

    # 11. prelaunch verdict becomes false
    def test_control_prelaunch_false(self) -> None:
        def mutate(scratch):
            def fn(doc):
                doc["pass"] = False
            edit_json(
                scratch.pe /
                "preflight/prelaunch-verdict-immediate-prelaunch.json",
                fn)
        doc = self._terminal_changes(mutate, expect_not=self.SEMANTIC)
        self.assertTrue(any("prelaunch" in p for p in doc["problems"]))

    # 12. driver post-run identity differs (scratch repo copy mutated)
    def test_control_driver_post_run_identity(self) -> None:
        scratch = ScratchEvidence(self)
        repo = Path(scratch.tmp) / "repo"
        repo.mkdir()
        shutil.copytree(ROOT / "scripts", repo / "scripts")
        (repo / "scripts/issue133_arm_c_retry_direct.py").write_text(
            "# mutated post-run driver bytes\n")
        scratch.repo_root = repo
        doc = scratch.run_terminal()
        self.assertTrue(
            any("driver" in p for p in doc["problems"]),
            json.dumps(doc["problems"])[:300])

    # 13. coordinator CUDA evidence nonzero
    def test_control_coordinator_cuda(self) -> None:
        def mutate(scratch):
            def fn(doc):
                doc["processes"][0]["cuda_env_keys"] = ["CUDA_VISIBLE_DEVICES"]
            edit_json(
                scratch.pe /
                "ordinary-http/coordinator-observation-pre.json", fn)
        doc = self._terminal_changes(mutate, expect_not=self.SEMANTIC)
        self.assertGreater(
            doc["zero_invariants"]["coordinator_cuda_initialized"], 0)

    # 14. coordinator weight/bulk evidence nonzero: a classified
    #     artifact payload leaf injected into a retained wire result
    #     (500 MiB base64 blob inside a GENERATE response)
    def test_control_coordinator_bulk_bytes(self) -> None:
        def mutate(scratch):
            def fn(doc):
                doc["epochs"][0]["runtime_sessions"][0][
                    "artifact_payload"] = "QUFB" * (500 * 1024 * 1024 // 4)
            edit_json(scratch.pe / "ordinary-http/serving-report.json", fn)
        doc = self._terminal_changes(mutate, expect_not=self.SEMANTIC)
        z = doc["zero_invariants"]
        self.assertGreaterEqual(
            z["coordinator_bulk_artifact_bytes_observed"], 500 * 1024 * 1024)
        self.assertGreater(
            z["coordinator_model_weight_bytes_received"], 0)

    # 14b. 64 MiB classified artifact payload (below any historical
    #      GiB threshold; must still be counted, never absorbed)
    def test_control_coordinator_bulk_bytes_64mib(self) -> None:
        def mutate(scratch):
            def fn(doc):
                doc["epochs"][0]["runtime_sessions"][0][
                    "artifact_payload"] = "QUFB" * (64 * 1024 * 1024 // 4)
            edit_json(scratch.pe / "ordinary-http/serving-report.json", fn)
        doc = self._terminal_changes(mutate, expect_not=self.SEMANTIC)
        self.assertGreaterEqual(
            doc["zero_invariants"]
            ["coordinator_bulk_artifact_bytes_observed"], 64 * 1024 * 1024)

    # 14c. artifact payload received then deleted: census entry gone in
    #      post but the wire payload was received (deleted state is a
    #      defect independent of the payload accounting)
    def test_control_artifact_received_then_deleted(self) -> None:
        def mutate(scratch):
            def fn_post(doc):
                doc["state_census"].pop(
                    "/srv/inferswarm/state/arm-c-retry-ordinary/"
                    "serving-evidence.json", None)
            edit_json(
                scratch.pe /
                "ordinary-http/coordinator-observation-post.json", fn_post)
        doc = self._terminal_changes(mutate, expect_not=self.SEMANTIC)
        self.assertTrue(any("deleted during window" in p
                            for p in doc["problems"]))

    # 14d. unclassified coordinator-bound payload: a >512-char string
    #      leaf in a wire result must count as unknown potentially-bulk
    #      and fail the authoritative-terminal requirement
    def test_control_unclassified_wire_payload(self) -> None:
        def mutate(scratch):
            def fn(doc):
                doc["epochs"][0]["runtime_sessions"][0][
                    "mystery_blob"] = ("mystery-" * 512) + "?"
            edit_json(scratch.pe / "ordinary-http/serving-report.json", fn)
        doc = self._terminal_changes(mutate, expect_not=self.SEMANTIC)
        self.assertGreater(
            doc["zero_invariants"]
            ["coordinator_unclassified_wire_bytes"], 0)

    # 14e. model/artifact response envelope injected: an extra wire
    #      result carrying a base64 tensor field (session-count and
    #      logical-grouping checks fire independently; the payload
    #      classification must ALSO see the blob)
    def test_control_artifact_envelope_injected(self) -> None:
        def mutate(scratch):
            def fn(doc):
                sess = doc["epochs"][0]["runtime_sessions"]
                plan = sess[0]["plan_digest"]
                sess.append({
                    "session_id": sess[-1]["session_id"] + 1,
                    "plan_digest": plan,
                    "prompt_len": 0,
                    "generated_token_ids": [0, 0],
                    "hidden_state_b64":
                        "AAAA" * (16 * 1024 * 1024 // 4),
                })
            edit_json(scratch.pe / "ordinary-http/serving-report.json", fn)
        doc = self._terminal_changes(mutate, expect_not=self.SEMANTIC)
        self.assertGreater(
            doc["zero_invariants"]
            ["coordinator_model_weight_bytes_received"], 0)

    # 14f. transient receive with no persistent state file: a numeric
    #      tensor-scale array (>4096 floats) inside a wire result
    def test_control_transient_receive_no_state_file(self) -> None:
        def mutate(scratch):
            def fn(doc):
                doc["epochs"][0]["runtime_sessions"][0]["logits"] = [
                    0.5] * 262144
            edit_json(scratch.pe / "ordinary-http/serving-report.json", fn)
        doc = self._terminal_changes(mutate, expect_not=self.SEMANTIC)
        self.assertGreater(
            doc["zero_invariants"]
            ["coordinator_unclassified_wire_bytes"], 0)

    # 14g. static protocol/source identity drift: one byte flipped in a
    #      pinned boundary source file
    def test_control_boundary_source_drift(self) -> None:
        def mutate(scratch):
            p = (scratch.root / "arm-c-retry/frozen-source/924cd22e/"
                 "benchmarks/inferswarm_r6/node_agent.py")
            text = p.read_text().replace(
                "send_exact(self._conn, encode_frame(response))",
                "send_exact(self._conn, encode_frame(responsX))", 1)
            p.write_text(text)
        doc = self._terminal_changes(mutate, expect_not=self.SEMANTIC)
        self.assertTrue(any("boundary source drift" in p
                            for p in doc["problems"]))

    # 14h. pinned producer identity drift: the pins document names a
    #      different producer
    def test_control_boundary_producer_drift(self) -> None:
        def mutate(scratch):
            def fn(doc):
                doc["frozen_producer"] = "0" * 40
            edit_json(scratch.pe / "coordinator-boundary-source-pins.json",
                      fn)
        doc = self._terminal_changes(mutate, expect_not=self.SEMANTIC)
        self.assertTrue(any("frozen producer" in p for p in doc["problems"]))

    # 14i. receive-site mutation: an extra send_exact site appended to
    #      the pinned node agent (negative control for the structural
    #      proof: the AST site-set assertion must trip)
    def test_control_receive_surface_mutation(self) -> None:
        def mutate(scratch):
            p = (scratch.root / "arm-c-retry/frozen-source/924cd22e/"
                 "benchmarks/inferswarm_r6/node_agent.py")
            p.write_text(p.read_text() + "\n\ndef _leak(site=None):\n"
                         "    send_exact(site, b'')\n")
            # also update the pin so ONLY the AST assertion can catch it
            import hashlib
            def fn(doc):
                doc["files"][
                    "benchmarks/inferswarm_r6/node_agent.py"][
                    "file_sha256"] = hashlib.sha256(
                        p.read_bytes()).hexdigest()
            edit_json(scratch.pe / "coordinator-boundary-source-pins.json",
                      fn)
        doc = self._terminal_changes(mutate, expect_not=self.SEMANTIC)
        self.assertTrue(any("send_exact site set" in p
                            for p in doc["problems"]))

    # 14j. coordinator materialization evidence nonzero: libtorch mapped
    def test_control_coordinator_materialization(self) -> None:
        def mutate(scratch):
            def fn(doc):
                doc["processes"][0]["maps_libtorch"] = 3
            edit_json(
                scratch.pe /
                "ordinary-http/coordinator-observation-post.json", fn)
        doc = self._terminal_changes(mutate, expect_not=self.SEMANTIC)
        self.assertGreater(
            doc["zero_invariants"]
            ["coordinator_model_weight_bytes_materialized"], 0)

    # 14k. required transport evidence absent: final runtime report
    #      replaced by a failure marker
    def test_control_transport_evidence_absent(self) -> None:
        def mutate(scratch):
            def fn(doc):
                doc["epochs"][0]["final_runtime_report"] = {}
                doc["epochs"][0]["runtime_report_failure"] = \
                    "RuntimeError: participant vanished"
            edit_json(scratch.pe / "ordinary-http/serving-report.json", fn)
        doc = self._terminal_changes(mutate, expect_not=self.SEMANTIC)
        self.assertTrue(any("REPORT transport evidence" in p
                            for p in doc["problems"]))

    # 14l. unclassified census file: an artifact-named state file below
    #      any GiB threshold (500 MiB weights.bin must be a defect, and
    #      so must a 1 KB unknown file — classification is by name)
    def test_control_unclassified_census_file(self) -> None:
        def mutate(scratch):
            def fn(doc):
                doc["state_census"][
                    "/srv/inferswarm/state/arm-c-retry-ordinary/"
                    "weights.bin"] = {"size": 524288000}
            edit_json(
                scratch.pe /
                "ordinary-http/coordinator-observation-post.json", fn)
        doc = self._terminal_changes(mutate, expect_not=self.SEMANTIC)
        self.assertGreater(
            doc["zero_invariants"]
            ["coordinator_unclassified_census_entries"], 0)

    # 14m. weights blob smuggled through the HTTP ingress: a base64
    #      payload inside an (otherwise consistent) ordinary request body
    #      must be classified as model payload, never ingress metadata
    def test_control_http_ingress_payload_blob(self) -> None:
        def mutate(scratch):
            blob = "QUFB" * (2 * 1024 * 1024 // 4)
            def fn(doc):
                doc["records"][0]["request_body"][
                    "smuggled_weights_b64"] = blob
            edit_json(
                scratch.pe / "ordinary-http/ordinary-campaign.json", fn)
            def fn2(doc):
                doc["request_body"]["smuggled_weights_b64"] = blob
            edit_json(
                scratch.pe / "ordinary-http/ordinary-c109-01-01-045.json",
                fn2)
        doc = self._terminal_changes(mutate, expect_not=self.SEMANTIC)
        self.assertGreater(
            doc["zero_invariants"]
            ["coordinator_model_weight_bytes_received"], 0)

    # 14n. bulk data hidden under an allowed census name: a 500 MiB
    #      coordinator.log in both censuses must fail the size cap
    def test_control_census_bulk_under_allowed_name(self) -> None:
        def mutate(scratch):
            for ph in ("pre", "post"):
                def fn(doc, _ph=ph):
                    doc["state_census"][
                        "/srv/inferswarm/state/arm-c-retry-ordinary/"
                        "coordinator.log"] = {"size": 524288000}
                edit_json(
                    scratch.pe /
                    f"ordinary-http/coordinator-observation-{ph}.json",
                    fn)
        doc = self._terminal_changes(mutate, expect_not=self.SEMANTIC)
        self.assertTrue(any("code-derived cap" in p for p in doc["problems"]))

    # 14o. numeric payload chunked into nested sub-4096 lists
    #      (review finding F1): the aggregate numeric-leaf count must
    #      trip the unknown rule even when no single list exceeds 4096
    def test_control_nested_numeric_chunks(self) -> None:
        def mutate(scratch):
            def fn(doc):
                doc["epochs"][0]["runtime_sessions"][0][
                    "weights_chunked"] = [list(range(4096))
                                          for _ in range(25)]
            edit_json(scratch.pe / "ordinary-http/serving-report.json", fn)
        doc = self._terminal_changes(mutate, expect_not=self.SEMANTIC)
        self.assertGreater(
            doc["zero_invariants"]
            ["coordinator_unclassified_wire_bytes"], 0)

    # 14p. payload hidden as base64-charset dict KEYS (review finding
    #      F2): keys are classified, not ignored
    def test_control_payload_as_dict_keys(self) -> None:
        def mutate(scratch):
            def fn(doc):
                sess = doc["epochs"][0]["runtime_sessions"][0]
                for i in range(64):
                    sess["QUFB" * 100 + str(i)] = 0
            edit_json(scratch.pe / "ordinary-http/serving-report.json", fn)
        doc = self._terminal_changes(mutate, expect_not=self.SEMANTIC)
        self.assertGreater(
            doc["zero_invariants"]
            ["coordinator_model_weight_bytes_received"], 0)

    # 15. Launch 1 contains a correctness-bearing observation
    def test_control_launch1_correctness_bearing(self) -> None:
        def mutate(scratch):
            def fn(doc):
                doc["attempt_id"] = "armc-retry-physical-1-launch1"
            edit_json(scratch.pe / "direct/direct-c109-01-01-045.json", fn)
        doc = self._terminal_changes(mutate, expect_not=self.SEMANTIC)
        self.assertTrue(
            any("launch-1" in p for p in doc["problems"]))

    # 15b. direct case attempt_id = null (review 5173318161 P2)
    def test_control_direct_case_null_attempt(self) -> None:
        def mutate(scratch):
            def fn(doc):
                doc["attempt_id"] = None
            edit_json(scratch.pe / "direct/direct-c109-01-01-045.json", fn)
        doc = self._terminal_changes(mutate, expect_not=self.SEMANTIC)
        self.assertTrue(
            any("authorized attempt" in p for p in doc["problems"]))

    # 15c. direct case missing attempt_id entirely: content binding must
    #      still hold; removing the field alone (schema carries none) is
    #      legal, so this control instead breaks content identity —
    #      covered by 2d below.  Here: wrong (non-null) attempt id.
    # 15d. wrong attempt id on a direct case
    def test_control_direct_case_wrong_attempt(self) -> None:
        def mutate(scratch):
            def fn(doc):
                doc["attempt_id"] = "armc-retry-physical-2"
            edit_json(scratch.pe / "direct/direct-c109-01-01-045.json", fn)
        doc = self._terminal_changes(mutate, expect_not=self.SEMANTIC)
        self.assertTrue(
            any("authorized attempt" in p or "unexpected attempt" in p
                for p in doc["problems"]))

    # 15e. direct-run.json attempt attribution null
    def test_control_direct_run_null_attempt(self) -> None:
        def mutate(scratch):
            def fn(doc):
                doc["attempt_id"] = None
            edit_json(scratch.pe / "direct/direct-run.json", fn)
        doc = self._terminal_changes(mutate, expect_not=self.SEMANTIC)
        self.assertTrue(
            any("direct run attempt attribution" in p
                for p in doc["problems"]))

    # 15f. ordinary campaign attribution wrong
    def test_control_ordinary_campaign_wrong_attempt(self) -> None:
        def mutate(scratch):
            def fn(doc):
                doc["attempt_id"] = "armc-retry-physical-1-direct"
            edit_json(
                scratch.pe / "ordinary-http/ordinary-campaign.json", fn)
        doc = self._terminal_changes(mutate, expect_not=self.SEMANTIC)
        self.assertTrue(
            any("ordinary campaign attempt attribution" in p
                for p in doc["problems"]))

    # 15g. direct case file content no longer binds to the attributed
    #      aggregate (a case observation with no attribution path)
    def test_control_direct_case_content_unbound(self) -> None:
        def mutate(scratch):
            def fn(doc):
                doc["wall_ns"] = 42
            edit_json(scratch.pe / "direct/direct-c109-01-01-045.json", fn)
        doc = self._terminal_changes(mutate, expect_not=self.SEMANTIC)
        self.assertTrue(
            any("does not bind" in p for p in doc["problems"]))

    # 15h. ordinary case file content no longer binds
    def test_control_ordinary_case_content_unbound(self) -> None:
        def mutate(scratch):
            def fn(doc):
                doc["wall_ns"] = 7
            edit_json(
                scratch.pe / "ordinary-http/ordinary-c109-01-01-045.json",
                fn)
        doc = self._terminal_changes(mutate, expect_not=self.SEMANTIC)
        self.assertTrue(
            any("does not bind" in p for p in doc["problems"]))

    # 16. controlled fencing injection becomes accepted
    def test_control_fencing_injection_accepted(self) -> None:
        def mutate(scratch):
            def fn(doc):
                doc["coordinator_scope"]["requests"][24][
                    "fencing_arm_injections"][0]["accepted"] = True
            edit_json(scratch.pe / "ordinary-http/serving-report.json", fn)
        doc = self._terminal_changes(mutate, expect_not=self.SEMANTIC)
        self.assertTrue(
            any("injection" in p.lower() for p in doc["problems"]))

    # 17. equality artifact forged to claim 24/24 despite raw mismatch
    def test_control_forged_equality_24(self) -> None:
        scratch = ScratchEvidence(self)

        def fn(doc):
            doc["equal_count"] = 24
            doc["passed"] = True
            for r in doc["rows"]:
                r["committed_ids_equal"] = True
        edit_json(scratch.pe / "equality-reduction.json", fn)
        # terminal must not become a PASS: the mismatched ids are
        # re-derived from raw bytes by the terminal reducer itself; a
        # forged verdict field is an invariant failure, never authority.
        doc = scratch.run_terminal()
        self.assertNotEqual(doc.get("terminal"), self.SEMANTIC)
        self.assertNotEqual(
            doc.get("terminal"), "ISSUE117_ARM_C_ORDINARY_SERVING_PASS")
        self.assertTrue(
            any("contradicts raw committed ids" in p
                for p in doc["problems"]))
        # and the /2 equality reducer re-derives the true counts from
        # raw bytes, proving the forgery detectable at that layer too
        eq = scratch.run_equality()
        self.assertEqual(eq["equal_count"], 18)  # re-derived, not forged
        self.assertFalse(eq["passed"])


class EqualityRejectionControls(unittest.TestCase):
    def test_mismatched_rows_carry_both_sides(self) -> None:
        eq = load("equality-reduction.json")
        for row in eq["rows"]:
            if not row["committed_ids_equal"]:
                self.assertIn("direct_committed_token_ids", row)
                self.assertIn("ordinary_committed_token_ids", row)
                self.assertEqual(
                    len(row["direct_committed_token_ids"]), 8)

    def test_row_count_and_equal_count_consistent(self) -> None:
        eq = load("equality-reduction.json")
        self.assertEqual(len(eq["rows"]), 24)
        self.assertEqual(
            eq["equal_count"],
            sum(1 for r in eq["rows"] if r["committed_ids_equal"]))

    def test_http_content_binding_recorded_per_row(self) -> None:
        eq = load("equality-reduction.json")
        for row in eq["rows"]:
            http = row["http_content"]
            self.assertTrue(http["binds_frozen_incremental_decode"])
            self.assertIn("binds_one_shot_full_decode", http)

    def test_invocation_seam_recorded_per_row(self) -> None:
        eq = load("equality-reduction.json")
        for row in eq["rows"]:
            seam = row["invocation_seam"]
            self.assertEqual(len(seam), 8)
            fdiv = row["first_divergent_position"]
            checked = 8 if fdiv is None else fdiv + 1
            for s in seam[:checked]:
                self.assertTrue(s["inputs_equal"])
                self.assertTrue(s["session_ids_equal"])
                self.assertTrue(s["commit_step_zero_semantics"])
                self.assertTrue(s["discard_step_one_semantics"])


class AttemptStateMachine(unittest.TestCase):
    def test_attempt_identity(self) -> None:
        attempt = load("attempts/armc-retry-physical-1.json")
        f = attempt["facts"]
        self.assertEqual(f["campaign_id"], "armc-retry-afcdc4428f95d50c")
        self.assertEqual(
            f["execution_freeze_identity"],
            "88389598ac485f82aa3ec00caadcebcb3cafb56cf967751262e8ab5bc9bf9a1c")
        self.assertEqual(
            attempt["classification_final"], "TERMINAL_CAMPAIGN_ATTEMPT")
        self.assertFalse(f["stop_occurred"])

    def test_launch1_was_pre_observation(self) -> None:
        log = (PE / "attempts/launch1-failure.log").read_text()
        self.assertIn("ModuleNotFoundError", log)
        self.assertIn("tvm_ffi", log)
        self.assertTrue(
            (PE / "attempts/execution-plan.launch1.json").is_file())


class PrelaunchGateEvidence(unittest.TestCase):
    def test_both_prelaunch_runs_accepted_materialization(self) -> None:
        for rel in ("preflight/prelaunch-verdict-run1.json",
                    "preflight/prelaunch-verdict-immediate-prelaunch.json"):
            v = load(rel)
            self.assertTrue(v["pass"], rel)
            self.assertEqual(v["source_mode"], "accepted_git_materialization")
            self.assertEqual(
                v["accepted_authority_commit"],
                "c42a0ea3f12532ab74c4e79772e1a126b5028514")
            self.assertEqual(
                v["execution_freeze_identity"],
                "88389598ac485f82aa3ec00caadcebcb3cafb56cf967751262e8ab5bc9bf9a1c")

    def test_tokenizer_deployment_proof_24_of_24(self) -> None:
        proof = load("preflight/tokenizer-deployment-proof.json")
        self.assertTrue(proof["passed"])
        self.assertEqual(proof["equal_count"], 24)
        self.assertEqual(proof["forbidden_source_opens"], [])


class DataPathInvariants(unittest.TestCase):
    def test_strace_audit_all_zero(self) -> None:
        audit = load("strace-audit.json")
        self.assertTrue(audit["passed"])
        for name, t in audit["traces"].items():
            self.assertEqual(t["source_models_opens"], 0, name)
            self.assertEqual(t["materialized_writes"], 0, name)

    def test_substrate_reconciliations_pass(self) -> None:
        for host in ("01", "03"):
            rec = load(f"substrate-reconciliation-{host}.json")
            self.assertTrue(rec["passed"], host)
            self.assertEqual(rec["problems"], [], host)


if __name__ == "__main__":
    unittest.main()

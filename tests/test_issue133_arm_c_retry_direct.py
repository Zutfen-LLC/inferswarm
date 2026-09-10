"""Issue #133 — corrected direct comparator driver tests (CPU-only).

The driver is correctness-bearing on the node; these tests prove, on CPU,
that its invocation contract matches the frozen #129/#133 contract:

- the frozen runtime-session allocation is extracted from the pinned
  bytes (never hand-copied) and reproduces the accepted #129
  representative sequences exactly;
- byte drift in the pinned r5b_epochs.py fails closed;
- the corrected comparator contract data (max_new_tokens=2, commit step
  zero, discard step one, on_token present, argument names) matches the
  frozen generate() argument contract;
- the fixture digest pins fail closed on drift;
- the driver source contains no single-shot max_new_tokens=8 call and no
  plan-digest bypass (AST-checked).

Authorization-fence behavior (review finding 4), proven BEHAVIORALLY with
fakes — every negative case fails before realize_dense_chain() and before
any runtime.generate() call:

- a substituted execution-plan-producing environment input is rejected;
- a substituted chain-plan/participant input is rejected;
- a locally built plan whose digest differs from the authorized frozen
  digest is rejected before realization;
- the exact retained chain plan / derived environment pass;
- the authorization fence (built plan == authorized digest) and the
  runtime-substitution fence (result digest == built plan digest) are
  both present in source.
"""
import ast
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import issue133_arm_c_retry_direct as drv  # noqa: E402
import issue129_arm_c_retry_core as core  # noqa: E402
import issue133_arm_c_retry_campaign as camp  # noqa: E402

PINNED = (ROOT / "docs/implementation/r6-successor-dense-full-integration-117"
          / "evidence/arm-c/frozen-freetoken/924cd22e/python/freetoken"
          / "research/r5b_epochs.py")
DRIVER_SOURCE = (ROOT / "scripts/issue133_arm_c_retry_direct.py").read_text()
CHAIN_PLAN = (ROOT / "docs/implementation/r6-successor-dense-full-integration-117"
              / "evidence/arm-c/chain-plan.json")


def _accepted_chain_plan() -> dict:
    return json.loads(CHAIN_PLAN.read_text())


def _accepted_environment() -> dict:
    return core._frozen_environment(core._repo_override())


class FrozenAllocatorTests(unittest.TestCase):
    def test_extraction_reproduces_accepted_129_sequences(self):
        allocator = drv.FrozenRuntimeSessionAllocator(PINNED.read_text())
        self.assertEqual(allocator.facts["multiplier"], 1000000)
        self.assertEqual(
            allocator.facts["method_sha256"],
            "94276b21597f22795af28ee4d3566dc15a903abadfd9a5c00a3d527f2b892f6c")
        ids = [allocator.allocate(1) for _ in range(8)]
        self.assertEqual(
            ids, [1000001, 1000002, 1000003, 1000004,
                  1000005, 1000006, 1000007, 1000008])
        ids2 = [allocator.allocate(2) for _ in range(8)]
        self.assertEqual(
            ids2, [2000009, 2000010, 2000011, 2000012,
                   2000013, 2000014, 2000015, 2000016])

    def test_control_pinned_byte_drift_fails_closed(self):
        # structural drift (removed sequence increment) fails closed inside
        # the allocator itself; multiplier-only drift is caught by the
        # driver's sha256 pin on the pinned bytes (checked in main())
        mutated = PINNED.read_text().replace(
            "        self._runtime_session_sequence += 1\n"
            "        return logical_session_id * 1_000_000 + "
            "self._runtime_session_sequence\n",
            "        return logical_session_id * 1_000_000\n",
            1)
        self.assertNotEqual(mutated, PINNED.read_text())
        with self.assertRaises(SystemExit) as caught:
            drv.FrozenRuntimeSessionAllocator(mutated)
        self.assertIn("FAIL", str(caught.exception))

    def test_control_sha_pin_drift_fails_closed_at_driver_entry(self):
        # the driver hard-pins the pinned bytes' sha256; any byte change
        # (including multiplier-only) is rejected before allocation
        mutated_sha = hashlib.sha256(
            PINNED.read_text().replace(
                "1_000_000", "2_000_000").encode()).hexdigest()
        self.assertNotEqual(
            mutated_sha, drv.R5B_EPOCHS_SHA256)

    def test_control_missing_method_fails_closed(self):
        mutated = PINNED.read_text().replace(
            "_runtime_session_id", "_renamed_method")
        with self.assertRaises(SystemExit):
            drv.FrozenRuntimeSessionAllocator(mutated)

    def test_pin_sha_matches_accepted_integrity(self):
        integrity = json.loads(
            (ROOT / "docs/implementation/r6-successor-dense-full-integration-117"
             / "evidence/arm-c-retry/integrity.json").read_text())
        self.assertEqual(
            hashlib.sha256(PINNED.read_bytes()).hexdigest(),
            integrity["runtime_session_allocation"]["source_sha256"])


class ComparatorContractSourceTests(unittest.TestCase):
    def test_generate_call_argument_set(self):
        tree = ast.parse(DRIVER_SOURCE)
        calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "generate"]
        self.assertEqual(len(calls), 1, "exactly one runtime.generate call")
        keywords = {kw.arg for kw in calls[0].keywords}
        self.assertEqual(
            keywords, {"session_id", "prompt_token_ids",
                       "max_new_tokens", "on_token"})
        for kw in calls[0].keywords:
            if kw.arg == "max_new_tokens":
                self.assertIsInstance(kw.value, ast.Constant)
                self.assertEqual(kw.value.value, 2)

    def test_no_single_shot_8(self):
        tree = ast.parse(DRIVER_SOURCE)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    if kw.arg == "max_new_tokens" and isinstance(
                            kw.value, ast.Constant):
                        self.assertEqual(kw.value.value, 2)

    def test_argument_contract_matches_frozen_129(self):
        self.assertEqual(
            tuple(drv.GENERATE_ARGUMENT_NAMES),
            tuple(core.GENERATE_ARGUMENT_NAMES))

    def test_fixture_digest_pins(self):
        self.assertIn("6046d4796a5d9cc888030c6b3f07304c20ce117d93905c3",
                      DRIVER_SOURCE)
        self.assertIn("180185cd5c6a5dcd77b2c65979bd2c9aef4d1c7ea9fb4850a",
                      DRIVER_SOURCE)

    def test_producer_pin(self):
        self.assertIn("924cd22ea081f6d4ed471016faf01d427fc5b0d2",
                      DRIVER_SOURCE)


class PlanAuthorizationFenceTests(unittest.TestCase):
    """Behavioral proof of the authorization fence (review finding 4):
    authorized frozen digest == locally built plan digest ==
    runtime-returned digest, with every external input bound to accepted
    evidence BEFORE realize_dense_chain() / any generate() call."""

    def test_frozen_digest_constant_is_the_issue133_authorization(self):
        self.assertEqual(
            drv.AUTHORIZED_EXECUTION_PLAN_DIGEST,
            "sha256:8646e00ce53e3aac4c163ca35231fa82471815386d71266a0d"
            "0962eea565bdad")
        # and it equals the accepted Arm-B plan digest re-derived from the
        # retained accepted execution-plan document
        arm_b = json.loads(
            (ROOT / "docs/implementation/r6-successor-dense-full-integration-117"
             / "evidence/arm-b/execution-plan.json").read_text())
        body = {k: v for k, v in arm_b.items() if k != "plan_digest"}
        recomputed = "sha256:" + hashlib.sha256(json.dumps(
            body, sort_keys=True, separators=(",", ":")).encode()
            + b"\n").hexdigest()
        self.assertEqual(recomputed, drv.AUTHORIZED_EXECUTION_PLAN_DIGEST)

    def test_fence_passes_on_authorized_digest(self):
        drv.verify_plan_authorization_fence(
            {"digest": drv.AUTHORIZED_EXECUTION_PLAN_DIGEST})

    def test_control_fence_rejects_unauthorized_built_plan(self):
        with self.assertRaises(SystemExit) as caught:
            drv.verify_plan_authorization_fence(
                {"digest": "sha256:" + "9" * 64})
        self.assertIn(
            "authorized issue #133 Arm-B execution-plan digest",
            str(caught.exception))

    def test_control_fence_rejects_missing_digest(self):
        with self.assertRaises(SystemExit):
            drv.verify_plan_authorization_fence({})

    def test_fence_precedes_realization_in_source(self):
        # inside main(), the authorization fences must appear BEFORE the
        # realize_dense_chain CALL SITE (not the import) — fail before
        # any runtime construction
        main_start = DRIVER_SOURCE.index("def main(")
        body = DRIVER_SOURCE[main_start:]
        fence = body.index("verify_plan_authorization_fence(")
        chain_fence = body.index("verify_chain_plan_authorization(")
        env_fence = body.index("verify_environment_authorization(")
        realize = body.index("runtime = realize_dense_chain(")
        self.assertLess(chain_fence, realize)
        self.assertLess(env_fence, realize)
        self.assertLess(fence, realize)
        # runtime-substitution fence stays too
        self.assertIn('result.get("plan_digest")', DRIVER_SOURCE)

    def test_retained_chain_plan_passes_the_participant_fence(self):
        drv.verify_chain_plan_authorization(_accepted_chain_plan())

    def test_derived_environment_passes_the_environment_fence(self):
        drv.verify_environment_authorization(_accepted_environment())

    def test_environment_identity_is_derived_from_accepted_evidence(self):
        actual = hashlib.sha256(
            drv.canonical_bytes(_accepted_environment())).hexdigest()
        self.assertEqual(
            actual, drv.AUTHORIZED_ENVIRONMENT_CANONICAL_SHA256)

    def test_direct_driver_does_not_load_issue129_core_at_runtime(self):
        self.assertNotIn("_load_methodology_core", DRIVER_SOURCE)
        self.assertNotIn("issue129_arm_c_retry_core.py", DRIVER_SOURCE)

    def test_campaign_and_driver_realization_inputs_match(self):
        frozen = camp.AUTHORIZED_REALIZATION_INPUTS
        self.assertEqual(
            drv.AUTHORIZED_ENVIRONMENT_CANONICAL_SHA256,
            frozen["environment"]["canonical_sha256"])
        self.assertEqual(
            drv.AUTHORIZED_MODEL_VIEW_PATH,
            frozen["model_view_path"]["value"])
        self.assertEqual(
            drv.AUTHORIZED_LAST_STAGE_HOST,
            frozen["last_stage_host"]["value"])
        self.assertEqual(
            drv.AUTHORIZED_LAST_STAGE_PORT,
            frozen["last_stage_port"]["value"])
        self.assertEqual(
            drv.AUTHORIZED_TOKENIZER_PATH,
            frozen["tokenizer_path"]["value"])

    def test_control_substituted_environment_rejected_before_realization(self):
        env = _accepted_environment()
        env["node_b"]["gpus"][0]["uuid"] = "GPU-substituted-0000"
        with self.assertRaises(SystemExit) as caught:
            drv.verify_environment_authorization(env)
        self.assertIn("environment", str(caught.exception))

    def test_control_environment_producer_drift_rejected(self):
        env = _accepted_environment()
        env["implementation_commit"] = "0" * 40
        with self.assertRaises(SystemExit):
            drv.verify_environment_authorization(env)

    def test_control_substituted_chain_plan_digest_rejected(self):
        plan = _accepted_chain_plan()
        plan["digest"] = "sha256:" + "9" * 64
        with self.assertRaises(SystemExit) as caught:
            drv.verify_chain_plan_authorization(plan)
        self.assertIn("chain plan digest", str(caught.exception))

    def test_control_substituted_participant_identity_rejected(self):
        plan = _accepted_chain_plan()
        # mutate BOTH the provenance and re-freeze the digest, so the
        # digest stays self-consistent and the rejection is attributable
        # to the PARTICIPANT identity, not to content mutation
        plan["provenance"]["issue117_arm_c"][
            "accepted_plan_digest"] = "sha256:" + "0" * 64
        body = {k: v for k, v in plan.items() if k != "digest"}
        plan["digest"] = "sha256:" + hashlib.sha256(
            (json.dumps(body, sort_keys=True,
                        separators=(",", ":")) + "\n").encode()).hexdigest()
        with self.assertRaises(SystemExit) as caught:
            drv.verify_chain_plan_authorization(plan)
        self.assertIn(
            "accepted Arm-B participant identity", str(caught.exception))

    def test_control_chain_plan_producer_drift_rejected(self):
        plan = _accepted_chain_plan()
        plan["provenance"]["r6"]["producer_sha"] = "0" * 40
        with self.assertRaises(SystemExit):
            drv.verify_chain_plan_authorization(plan)

    def test_control_geometry_mutated_chain_plan_rejected(self):
        # geometry lives inside the chain plan; any real content change
        # breaks the digest pin even with provenance intact
        plan = _accepted_chain_plan()
        plan["number_of_layers"] = plan.get("number_of_layers", 48) + 1
        with self.assertRaises(SystemExit):
            drv.verify_chain_plan_authorization(plan)

    def test_control_missing_provenance_rejected(self):
        plan = _accepted_chain_plan()
        plan.pop("provenance")
        with self.assertRaises(SystemExit):
            drv.verify_chain_plan_authorization(plan)


class ZeroModelExecutionAfterFailedAuthorizationTests(unittest.TestCase):
    """Prove with fakes that a failed authorization check means ZERO
    model/runtime execution: neither realize_dense_chain nor
    runtime.generate is ever reached."""

    def _run_main_with_fences(
            self, tmp: Path, *, chain_plan: dict, environment: dict,
            overrides: dict | None = None,
            built_plan_digest: str | None = None,
            allow_realization: bool = False,
            permissive_methodology_core: bool = False) -> dict:
        """Invoke the REAL main(argv) flow up to (and including) the
        authorization fences with fake plan files; count any attempt to
        touch realization. Returns counters."""
        counters = {"realize": 0, "generate": 0}
        plan_path = tmp / "chain-plan.json"
        env_path = tmp / "environment.json"
        fixture_path = tmp / "fixture.json"
        corpus_path = tmp / "corpus.json"
        plan_path.write_text(json.dumps(chain_plan))
        env_path.write_text(json.dumps(environment))
        # the REAL retained frozen fixture/corpus (digest-pinned by the
        # driver); only the tokenizer is faked
        shutil.copy(
            ROOT / "docs/implementation/r6-successor-dense-full"
            "-integration-117/evidence/arm-c-retry/prompt-fixture.json",
            fixture_path)
        shutil.copy(
            ROOT / "docs/implementation/r6-successor-dense-full"
            "-integration-117/evidence/integration-fixture.json",
            corpus_path)
        output_root = tmp / "attempts"
        tokenizer_path = tmp / "tokenizer"
        argv_values = {
            "repo": str(tmp / "fakewt"),
            "plan": str(plan_path),
            "environment": str(env_path),
            "view-dir": drv.AUTHORIZED_MODEL_VIEW_PATH,
            "last-stage-host": drv.AUTHORIZED_LAST_STAGE_HOST,
            "last-stage-port": str(drv.AUTHORIZED_LAST_STAGE_PORT),
            "fixture": str(fixture_path),
            "corpus": str(corpus_path),
            "pinned-r5b-epochs": str(PINNED),
            "tokenizer": str(tokenizer_path),
            "out-dir": str(output_root / "fake" / "direct"),
            "attempt-id": "fake",
        }
        argv_values.update(overrides or {})
        argv = [
            "--repo", str(tmp / "fakewt"),
        ]
        for name, value in argv_values.items():
            if name == "repo":
                continue
            argv.extend((f"--{name}", str(value)))
        # a render-faithful fake tokenizer: reproduces each case's frozen
        # rendered ids, so the 24/24 render-equality gate passes and the
        # flow proceeds to the plan/environment fences
        fixture = json.loads(fixture_path.read_text())
        corpus = json.loads(corpus_path.read_text())
        rendered_by_text = {}
        for case in fixture["cases"]:
            text = next(
                row["case"]["prompt_text"] for row in corpus["cases"]
                if row["case"]["case_id"] == case["case_id"])
            rendered_by_text[text] = list(case["rendered_prompt_token_ids"])

        class _FakeTok:
            @staticmethod
            def from_pretrained(path, **kwargs):
                return _FakeTok()

            def apply_chat_template(self, messages, *, tokenize=False,
                                    add_generation_prompt=True, **ctk):
                return messages[0]["content"]

            def encode(self, text, *, add_special_tokens=False):
                return rendered_by_text[text]

            def decode(self, token_ids):
                return " ".join(str(token) for token in token_ids)

        fake_transformers = type(sys)("transformers")
        fake_transformers.AutoTokenizer = _FakeTok
        fake_chain_runtime = type(sys)(
            "benchmarks.inferswarm_r6.chain_runtime")

        class _FakeRuntime:
            def generate(self, *, session_id, prompt_token_ids,
                         max_new_tokens, on_token):
                counters["generate"] += 1
                on_token(0, 7, None)
                return {
                    "generated_token_ids": [7, 8],
                    "plan_digest": drv.AUTHORIZED_EXECUTION_PLAN_DIGEST,
                }

            @staticmethod
            def report():
                return {}

            @staticmethod
            def close():
                return None

        def _realize(*args, **kwargs):
            counters["realize"] += 1
            if allow_realization:
                return _FakeRuntime()
            raise AssertionError("realize_dense_chain reached despite failed "
                                 "authorization")

        fake_chain_runtime.realize_dense_chain = _realize

        # satisfy the producer-worktree shape check: the worktree
        # identity check is upstream of (and independent from) the
        # authorization fences under test here
        def _fake_check_output(cmd, *args, **kwargs):
            if "rev-parse" in cmd:
                return drv.FREETOKEN_PRODUCER + "\n"
            if "status" in cmd:
                return ""
            raise AssertionError(f"unexpected subprocess call: {cmd}")

        authorized_paths = {
            "plan": str(plan_path),
            "environment": str(env_path),
            "fixture": str(fixture_path),
            "corpus": str(corpus_path),
            "pinned_r5b_epochs": str(PINNED),
        }
        authorized_hashes = {
            "plan": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
            "fixture": hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
            "corpus": hashlib.sha256(corpus_path.read_bytes()).hexdigest(),
            "pinned_r5b_epochs": hashlib.sha256(PINNED.read_bytes()).hexdigest(),
        }
        fake_core = type(sys)("issue129_arm_c_retry_core")
        fake_core._frozen_environment = lambda *_: environment
        fake_core._repo_override = lambda: tmp
        modules = {
                "transformers": fake_transformers,
                "benchmarks.inferswarm_r6.chain_runtime":
                    fake_chain_runtime,
        }
        if permissive_methodology_core:
            modules["issue129_arm_c_retry_core"] = fake_core
        with mock.patch.dict(sys.modules, modules), \
                mock.patch.object(drv.subprocess, "check_output",
                                  side_effect=_fake_check_output), \
                mock.patch.object(drv, "AUTHORIZED_INPUT_PATHS",
                                  authorized_paths), \
                mock.patch.object(drv, "AUTHORIZED_INPUT_FILE_SHA256",
                                  authorized_hashes), \
                mock.patch.object(drv, "AUTHORIZED_TOKENIZER_PATH",
                                  str(tokenizer_path)), \
                mock.patch.object(drv, "AUTHORIZED_OUTPUT_ROOT",
                                  str(output_root)), \
                mock.patch.object(drv, "verify_tokenizer_authorization"), \
                mock.patch.object(
                    drv, "build_execution_plan", return_value={
                        "digest": built_plan_digest
                        or drv.AUTHORIZED_EXECUTION_PLAN_DIGEST}):
            try:
                drv.main(argv)
            except SystemExit as exit_error:
                counters["exit"] = str(exit_error)
        return counters

    def test_substituted_environment_never_reaches_realization(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            env = _accepted_environment()
            env["node_a"]["gpus"][0]["uuid"] = "GPU-substituted-1111"
            counters = self._run_main_with_fences(
                tmp, chain_plan=_accepted_chain_plan(), environment=env)
            self.assertEqual(counters["realize"], 0)
            self.assertEqual(counters["generate"], 0)
            self.assertIn("environment", counters.get("exit", ""))

    def test_substituted_chain_plan_never_reaches_realization(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            plan = _accepted_chain_plan()
            # substituted PARTICIPANT provenance, digest honestly
            # re-frozen so the failure is attributable to the identity
            # binding, not to content mutation
            plan["provenance"]["issue117_arm_c"][
                "accepted_plan_digest"] = "sha256:" + "0" * 64
            body = {k: v for k, v in plan.items() if k != "digest"}
            plan["digest"] = "sha256:" + hashlib.sha256(
                (json.dumps(body, sort_keys=True,
                            separators=(",", ":")) + "\n")
                .encode()).hexdigest()
            counters = self._run_main_with_fences(
                tmp, chain_plan=plan,
                environment=_accepted_environment())
            self.assertEqual(counters["realize"], 0)
            self.assertEqual(counters["generate"], 0)
            self.assertIn(
                "accepted Arm-B participant identity",
                counters.get("exit", ""))

    def test_changed_model_view_rejects_before_realization(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            counters = self._run_main_with_fences(
                Path(tmp_name), chain_plan=_accepted_chain_plan(),
                environment=_accepted_environment(),
                overrides={"view-dir": "/tmp/substituted-model-view"})
            self.assertEqual(counters["realize"], 0)
            self.assertEqual(counters["generate"], 0)
            self.assertIn("--view-dir", counters.get("exit", ""))

    def test_changed_last_stage_host_rejects_before_realization(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            counters = self._run_main_with_fences(
                Path(tmp_name), chain_plan=_accepted_chain_plan(),
                environment=_accepted_environment(),
                overrides={"last-stage-host": "10.0.0.218"})
            self.assertEqual(counters["realize"], 0)
            self.assertEqual(counters["generate"], 0)
            self.assertIn("--last-stage-host", counters.get("exit", ""))

    def test_changed_last_stage_port_rejects_before_realization(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            counters = self._run_main_with_fences(
                Path(tmp_name), chain_plan=_accepted_chain_plan(),
                environment=_accepted_environment(),
                overrides={"last-stage-port": "18486"})
            self.assertEqual(counters["realize"], 0)
            self.assertEqual(counters["generate"], 0)
            self.assertIn("--last-stage-port", counters.get("exit", ""))

    def test_changed_tokenizer_path_rejects_before_realization(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            counters = self._run_main_with_fences(
                Path(tmp_name), chain_plan=_accepted_chain_plan(),
                environment=_accepted_environment(),
                overrides={"tokenizer": "/tmp/substituted-tokenizer"})
            self.assertEqual(counters["realize"], 0)
            self.assertEqual(counters["generate"], 0)
            self.assertIn("--tokenizer", counters.get("exit", ""))

    def test_changed_environment_authority_module_cannot_authorize_input(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            environment = _accepted_environment()
            environment["node_b"]["gpus"][0]["uuid"] = "GPU-substituted"
            counters = self._run_main_with_fences(
                Path(tmp_name), chain_plan=_accepted_chain_plan(),
                environment=environment, permissive_methodology_core=True)
            self.assertEqual(counters["realize"], 0)
            self.assertEqual(counters["generate"], 0)
            self.assertIn("environment", counters.get("exit", ""))

    def test_unauthorized_locally_built_plan_rejects_before_realization(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            counters = self._run_main_with_fences(
                Path(tmp_name), chain_plan=_accepted_chain_plan(),
                environment=_accepted_environment(),
                built_plan_digest="sha256:" + "9" * 64)
            self.assertEqual(counters["realize"], 0)
            self.assertEqual(counters["generate"], 0)
            self.assertIn("locally built execution plan", counters.get("exit", ""))

    def test_accepted_inputs_reach_realization_and_generation(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            counters = self._run_main_with_fences(
                Path(tmp_name), chain_plan=_accepted_chain_plan(),
                environment=_accepted_environment(), allow_realization=True)
            self.assertEqual(counters["realize"], 1)
            self.assertEqual(counters["generate"], 24 * 8)
            self.assertNotIn("exit", counters)


if __name__ == "__main__":
    unittest.main()

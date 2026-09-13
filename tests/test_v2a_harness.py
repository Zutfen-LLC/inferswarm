"""Issue #163 CPU-only adversarial genericity controls for the V2-A harness.

Covers the fifteen adversarial controls the issue requires, CPU-only:
synthetic subjects, selector/BDF handling, wrong identities, staleness,
hash mismatches, self-authorization, proof attribution, planner
genericity, and the retained AMD/NV replay semantics.
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import v2a_harness as harness  # noqa: E402
import v2a_authority as authority_contract  # noqa: E402
import v1a_execution_participant as participant  # noqa: E402
import v1a_vulkan_adapter as adapter  # noqa: E402
import v1c_accounting as accounting  # noqa: E402

# Accepted retained raw evidence (immutable inputs; read-only).
V1A_STDERR = ROOT / "docs/investigations/vulkan-v1-a/raw/v1a-amd-a-canonical-01/stderr.txt"
V1A_STDOUT = ROOT / "docs/investigations/vulkan-v1-a/raw/v1a-amd-a-canonical-01/stdout.txt"
V1C_STDERR = ROOT / "docs/investigations/vulkan-v1-c/raw/v1c-nv-a-canonical-01/stderr.txt"
V1C_STDOUT = ROOT / "docs/investigations/vulkan-v1-c/raw/v1c-nv-a-canonical-01/stdout.txt"
V1A_AUTHORITY = json.loads(
    (ROOT / "docs/investigations/vulkan-v1-a/PHYSICAL-AUTHORITY.json").read_text(encoding="utf-8"))
V1C_AUTHORITY = json.loads(
    (ROOT / "docs/investigations/vulkan-v1-c/PHYSICAL-AUTHORITY.json").read_text(encoding="utf-8"))

PROMPT = V1A_AUTHORITY["frozen"]["prompt"]
AMD_SELECTOR = V1A_AUTHORITY["frozen"]["selector"]
AMD_BDF = V1A_AUTHORITY["frozen"]["physical_device_bdf"]
NV_SELECTOR = V1C_AUTHORITY["frozen"]["selector"]
NV_BDF = V1C_AUTHORITY["frozen"]["physical_device_bdf"]
AMD_REFERENCE = (ROOT / V1A_AUTHORITY["frozen"]["reference_output"]).read_bytes()
NV_REFERENCE = (ROOT / V1C_AUTHORITY["frozen"]["reference_output"]).read_bytes()


class RetainedReplayTests(unittest.TestCase):
    """Phase 6 retained-evidence replay, both subjects, same code."""

    def test_amd_retained_transcript_replays_cleanly(self):
        result = harness.replay_retained(
            V1A_STDERR.read_text(encoding="utf-8"), selector=AMD_SELECTOR, expected_bdf=AMD_BDF,
            expected_prompt=PROMPT, reference=AMD_REFERENCE, stdout=V1A_STDOUT.read_bytes())
        self.assertEqual(result["result"], "PASS")
        self.assertEqual(result["accounting_three_tuple"], [0, 0, 0])
        self.assertTrue(result["byte_exact_visible_output"])

    def test_nv_retained_transcript_replays_cleanly(self):
        result = harness.replay_retained(
            V1C_STDERR.read_text(encoding="utf-8"), selector=NV_SELECTOR, expected_bdf=NV_BDF,
            expected_prompt=PROMPT, reference=NV_REFERENCE, stdout=V1C_STDOUT.read_bytes())
        self.assertEqual(result["result"], "PASS")
        self.assertEqual(result["accounting_three_tuple"], [0, 0, 0])
        self.assertTrue(result["byte_exact_visible_output"])

    def test_no_subject_specific_harness_code_between_replays(self):
        # Both replays above run through the SAME harness function; the
        # reusable sources must additionally carry no subject literal.
        for path in harness.HARNESS_SOURCES:
            text = (ROOT / path).read_text(encoding="utf-8").lower()
            for token in ("amd", "radeon", "geforce", "ga104", "nvidia", "vulkan1", "vulkan3",
                          "02:00.0", "04:00.0"):
                self.assertNotIn(token, text, f"{path} contains subject literal {token!r}")

    def test_replay_with_wrong_selector_fails_closed(self):
        with self.assertRaises((accounting.AccountingError, adapter.AdapterError)):
            harness.replay_retained(
                V1A_STDERR.read_text(encoding="utf-8"), selector=NV_SELECTOR,
                expected_bdf=AMD_BDF, expected_prompt=PROMPT, reference=AMD_REFERENCE,
                stdout=V1A_STDOUT.read_bytes())

    def test_replay_with_wrong_bdf_fails_closed(self):
        with self.assertRaises(adapter.AdapterError):
            harness.replay_retained(
                V1A_STDERR.read_text(encoding="utf-8"), selector=AMD_SELECTOR,
                expected_bdf=NV_BDF, expected_prompt=PROMPT, reference=AMD_REFERENCE,
                stdout=V1A_STDOUT.read_bytes())

    def test_replay_with_tampered_reference_fails_byte_exact(self):
        with self.assertRaises(harness.HarnessError):
            harness.replay_retained(
                V1A_STDERR.read_text(encoding="utf-8"), selector=AMD_SELECTOR,
                expected_bdf=AMD_BDF, expected_prompt=PROMPT, reference=b"tampered reference\n",
                stdout=V1A_STDOUT.read_bytes())


def _synthetic_authority(selector: str, bdf: str, *, namespace_ok: bool = True) -> dict:
    """Build a minimal synthetic V2-A authority-shaped mapping (tests only)."""
    return {
        "schema": authority_contract.SCHEMA,
        "frozen": {
            "hostname": "node-synth", "node_id": "node-synth", "compute_unit_id": "cu-synth",
            "memory_resource_id": "mr-synth", "memory_bytes": 8589934592,
            "physical_device_bdf": bdf, "selector": selector,
            "execution_unit_id": "unit-synth", "execution_contract_id": "contract-synth",
            "implementation_id": "impl-synth", "logical_state_id": "state-synth",
            "required_representation": "rep-synth", "required_features": ["compute"],
            "required_memory_bytes": 1000, "required_headroom_bytes": 100,
            "required_integrity_status": "QUALIFIED",
            "correctness_policy": authority_contract.ACCEPTED_COMPARATOR_POLICY,
            "objective": "MIN_OBJECTIVE_VALUE", "prompt": "prompt-synth",
            "runtime_source": "/src", "runtime_source_commit": "c" * 40,
            "executable": "/bin/x", "executable_sha256": "a" * 64,
            "model": "/m.gguf", "model_sha256": "b" * 64, "model_bytes": 10,
            "qualification_evidence_id": "v2a-synth-qualification-01",
            "canonical_execution_evidence_id": "v2a-synth-canonical-01",
            "runtime_identity": {"selector": selector},
        },
        "correctness": {
            "comparator_policy": authority_contract.ACCEPTED_COMPARATOR_POLICY,
            "reference_sha256": "d" * 64, "reference_path": "some/reference.txt",
            "reference_provenance": "accepted pre-existing evidence",
            "no_recalibration": authority_contract.NO_RECALIBRATION,
        },
        "evidence": {"evidence_namespace": "vulkan-synth" if namespace_ok else "",
                     "plan_evidence_id": "v2a-synth-plan-01",
                     "capability_evidence_id": "v2a-synth-capability-01"},
        "nonclaims": ["synthetic"],
    }


def synthetic_transcript(selector: str) -> str:
    """Full runtime accounting grammar (mirrors the accepted V1-C fixture)."""
    lines = [
        f"0.01 I cmn  common_param:   - {selector} : SyntheticDevice (8438 MiB, 8122 MiB free)",
        "0.01 I common_memory_breakdown_print: | memory breakdown [MiB]    | total   free    self   model   context   compute    unaccounted |",
        f"0.01 I common_memory_breakdown_print: |   - {selector} (Dev) |  8438 = 8099 + (3091 =  1834 +    1152 +     104) +       -2752 |",
        "0.01 I common_memory_breakdown_print: |   - Host                  |                  283 =   243 +       0 +      40                |",
        f"using device {selector} (synthetic accelerator) (0000:{BDF_SYNTH})",
        "offloaded 12/12 layers to GPU",
        "0.02 I load_tensors:   CPU_Mapped model buffer size =   243.43 MiB",
        f"0.02 I load_tensors:      {selector} model buffer size =  1834.82 MiB",
        "0.12 I llama_context: Vulkan_Host  output buffer size =     0.58 MiB",
        f"0.12 I llama_kv_cache:    {selector} KV buffer size =  1152.00 MiB",
        f"0.12 I sched_reserve:    {selector} compute buffer size =   104.51 MiB",
        "0.12 I sched_reserve: Vulkan_Host compute buffer size =    40.02 MiB",
        "0.12 I slot   operator(): id  0 | task 0 | cached n_tokens = 0, memory_seq_rm [0, end)",
        "0.13 I common_memory_breakdown_print: | memory breakdown [MiB]    | total   free    self   model   context   compute    unaccounted |",
        f"0.13 I common_memory_breakdown_print: |   - {selector} (Dev) |  8438 = 4532 + (3091 =  1834 +  1152 +     104) +         814 |",
        "0.13 I common_memory_breakdown_print: |   - Host                  |                  283 =   243 +       0 +      40                |",
    ]
    return "\n".join(lines) + "\n"


BDF_SYNTH = "01:00.0"


def _synthetic_plan(authority: dict) -> dict:
    """Build a frozen plan for the synthetic subject via the accepted planner."""
    frozen = authority["frozen"]
    unit = {"execution_unit_id": frozen["execution_unit_id"],
            "execution_contract_id": frozen["execution_contract_id"],
            "logical_state_id": frozen["logical_state_id"],
            "required_representation": frozen["required_representation"],
            "required_features": frozen["required_features"],
            "required_memory_bytes": frozen["required_memory_bytes"],
            "required_headroom_bytes": frozen["required_headroom_bytes"],
            "required_integrity_status": frozen["required_integrity_status"],
            "correctness_policy": frozen["correctness_policy"]}
    capability = {
        "bound_node_id": frozen["node_id"], "bound_compute_unit_id": frozen["compute_unit_id"],
        "bound_memory_resource_id": frozen["memory_resource_id"],
        "bound_execution_unit_id": frozen["execution_unit_id"],
        "execution_contract_id": frozen["execution_contract_id"],
        "implementation_id": frozen["implementation_id"],
        "evidence_id": frozen["qualification_evidence_id"],
        "qualification_evidence_id": frozen["qualification_evidence_id"],
        "qualification_digest": "q" * 64, "physical_device_bdf": frozen["physical_device_bdf"],
        "runtime_identity": frozen["runtime_identity"], "representations": ["rep-synth"],
        "required_features": ["compute"], "integrity_status": "QUALIFIED",
        "evidence_fresh": True, "economics": {"objective_value": 1.0},
    }
    resource = {"node_id": frozen["node_id"], "compute_unit_id": frozen["compute_unit_id"],
                "physical_device_bdf": frozen["physical_device_bdf"],
                "memory_resource": {"memory_resource_id": frozen["memory_resource_id"],
                                    "bytes": frozen["memory_bytes"]},
                "capabilities": [capability]}
    decision = participant.plan_execution_unit(execution_unit=unit, compute_units=[resource],
                                               objective="MIN_OBJECTIVE_VALUE")
    return participant.freeze_plan(decision=decision, execution_unit=unit)


class GenericityControlsTests(unittest.TestCase):
    """The issue's fifteen adversarial CPU controls."""

    def _execute_with(self, authority: dict, plan: dict | None = None,
                      stderr: str | None = None, reference: bytes | None = None,
                      stdout: bytes | None = None):
        frozen = authority["frozen"]
        plan = plan if plan is not None else _synthetic_plan(authority)
        stderr = stderr if stderr is not None else synthetic_transcript(frozen["selector"])
        # The accepted comparator isolates the reply between the echoed
        # prompt line and the timing marker; the synthetic transcript
        # follows that frozen grammar.
        response = b"synthetic visible output"
        stdout = stdout if stdout is not None else (
            b"> " + frozen["prompt"].encode() + b"\n" + response + b"\n\n[ Prompt: 0.00 tokens]\n")
        reference = reference if reference is not None else response
        import tempfile
        temp = tempfile.mkdtemp()
        run = {"exit_code": 0, "stdout": stdout, "stderr": stderr}
        # The accepted _execute is physical; controls exercise the
        # post-execution reduction path with a stubbed execution.
        original = harness.accepted_runner._execute

        def stub_execute(f, out):
            return run
        harness.accepted_runner._execute = stub_execute
        try:
            # reference bytes resolved via the authority contract path
            authority = copy.deepcopy(authority)
            (Path(temp) / "ref").write_bytes(reference)
            authority["correctness"]["reference_path"] = str(Path(temp) / "ref")
            authority["correctness"]["reference_sha256"] = hashlib.sha256(reference).hexdigest()
            return harness.execute_canonical(authority, plan, {}, Path(temp) / "out")
        finally:
            harness.accepted_runner._execute = original

    # Control 1: two synthetic subjects with completely different opaque IDs.
    def test_control_1_same_harness_accepts_two_opaque_subjects(self):
        first = _synthetic_authority("Vulkan2", BDF_SYNTH)
        second = _synthetic_authority("Vulkan9", BDF_SYNTH)
        second["frozen"].update({"node_id": "node-other", "compute_unit_id": "cu-other",
                                 "memory_resource_id": "mr-other",
                                 "execution_contract_id": "contract-other",
                                 "implementation_id": "impl-other",
                                 "qualification_evidence_id": "q-other",
                                 "canonical_execution_evidence_id": "c-other"})
        self.assertEqual(self._execute_with(first)["receipt"]["plan_digest"],
                         _synthetic_plan(first)["plan_digest"])
        self.assertEqual(self._execute_with(second)["receipt"]["plan_digest"],
                         _synthetic_plan(second)["plan_digest"])

    # Control 3: wrong selector/BDF fails.
    def test_control_3_wrong_selector_or_bdf_fails(self):
        authority = _synthetic_authority("Vulkan2", BDF_SYNTH)
        wrong_selector = synthetic_transcript("Vulkan8")
        with self.assertRaises(adapter.AdapterError):
            self._execute_with(authority, stderr=wrong_selector)
        wrong_bdf = synthetic_transcript("Vulkan2").replace(
            "using device Vulkan2 (synthetic accelerator) (0000:" + BDF_SYNTH + ")",
            "using device Vulkan2 (synthetic accelerator) (0000:09:09.9)")
        with self.assertRaises(adapter.AdapterError):
            self._execute_with(authority, stderr=wrong_bdf)

    # Control 4: wrong Node/CU/MR fails (planner binding).
    def test_control_4_wrong_node_cu_mr_fails(self):
        authority = _synthetic_authority("Vulkan2", BDF_SYNTH)
        other = copy.deepcopy(authority)
        other["frozen"]["compute_unit_id"] = "cu-someone-else"
        with self.assertRaises(harness.HarnessError):
            self._execute_with(authority, plan=_synthetic_plan(other))

    # Control 5: wrong execution contract/implementation fails.
    def test_control_5_wrong_contract_fails(self):
        authority = _synthetic_authority("Vulkan2", BDF_SYNTH)
        other = _synthetic_authority("Vulkan2", BDF_SYNTH)
        other["frozen"]["execution_contract_id"] = "contract-other"
        with self.assertRaises(harness.HarnessError):
            self._execute_with(authority, plan=_synthetic_plan(other))

    # Control 6: stale qualification/inventory fails (EVIDENCE_STALE).
    def test_control_6_stale_qualification_fails_planning(self):
        authority = _synthetic_authority("Vulkan2", BDF_SYNTH)
        frozen = authority["frozen"]
        unit = {"execution_unit_id": frozen["execution_unit_id"],
                "execution_contract_id": frozen["execution_contract_id"],
                "logical_state_id": frozen["logical_state_id"],
                "required_representation": frozen["required_representation"],
                "required_features": frozen["required_features"],
                "required_memory_bytes": frozen["required_memory_bytes"],
                "required_headroom_bytes": frozen["required_headroom_bytes"],
                "required_integrity_status": frozen["required_integrity_status"],
                "correctness_policy": frozen["correctness_policy"]}
        stale_capability = {
            "bound_node_id": frozen["node_id"], "bound_compute_unit_id": frozen["compute_unit_id"],
            "bound_memory_resource_id": frozen["memory_resource_id"],
            "bound_execution_unit_id": frozen["execution_unit_id"],
            "execution_contract_id": frozen["execution_contract_id"],
            "implementation_id": frozen["implementation_id"],
            "evidence_id": frozen["qualification_evidence_id"],
            "qualification_evidence_id": frozen["qualification_evidence_id"],
            "qualification_digest": "q" * 64, "physical_device_bdf": frozen["physical_device_bdf"],
            "runtime_identity": frozen["runtime_identity"], "representations": ["rep-synth"],
            "required_features": ["compute"], "integrity_status": "QUALIFIED",
            "evidence_fresh": False, "economics": {"objective_value": 1.0},
        }
        resource = {"node_id": frozen["node_id"], "compute_unit_id": frozen["compute_unit_id"],
                    "physical_device_bdf": frozen["physical_device_bdf"],
                    "memory_resource": {"memory_resource_id": frozen["memory_resource_id"],
                                        "bytes": frozen["memory_bytes"]},
                    "capabilities": [stale_capability]}
        decision = participant.plan_execution_unit(execution_unit=unit, compute_units=[resource],
                                                   objective="MIN_OBJECTIVE_VALUE")
        self.assertIsNone(decision["selected_candidate"])
        reasons = {row["reason"] for row in decision["explanations"]}
        self.assertIn("EVIDENCE_STALE", reasons)

    # Control 7: wrong runtime/model hash fails (authority loader pins).
    def test_control_7_wrong_runtime_model_hash_fails_at_load(self):
        with self.assertRaises(authority_contract.AuthorityError):
            authority_contract.load_authority({
                **_synthetic_authority("Vulkan2", BDF_SYNTH),
                "frozen": {**_synthetic_authority("Vulkan2", BDF_SYNTH)["frozen"],
                           "model_sha256": "not-a-hash"}})

    # Control 8: missing correctness provenance fails (loader contract).
    def test_control_8_missing_provenance_fails_at_load(self):
        document = _synthetic_authority("Vulkan2", BDF_SYNTH)
        del document["correctness"]["reference_provenance"]
        with self.assertRaises(authority_contract.AuthorityError):
            authority_contract.load_authority(document)

    # Control 9: caller cannot replace the reference after qualification.
    def test_control_9_reference_replacement_fails(self):
        authority = _synthetic_authority("Vulkan2", BDF_SYNTH)
        with self.assertRaises(harness.HarnessError):
            self._execute_with(authority, reference=b"different bytes entirely\n")

    # Control 10: qualification evidence cannot substitute for canonical proof.
    def test_control_10_qualification_evidence_is_not_canonical_proof(self):
        authority = _synthetic_authority("Vulkan2", BDF_SYNTH)
        plan = _synthetic_plan(authority)
        observation = adapter.parse_backend_observation(
            stderr=synthetic_transcript(authority["frozen"]["selector"]),
            selector=authority["frozen"]["selector"],
            expected_bdf=authority["frozen"]["physical_device_bdf"],
            node_id=authority["frozen"]["node_id"],
            compute_unit_id=authority["frozen"]["compute_unit_id"],
            memory_resource_id=authority["frozen"]["memory_resource_id"],
            execution_unit_id=authority["frozen"]["execution_unit_id"],
            execution_contract_id=authority["frozen"]["execution_contract_id"],
            implementation_id=authority["frozen"]["implementation_id"],
            evidence_id=authority["frozen"]["qualification_evidence_id"],
            runtime_identity=authority["frozen"]["runtime_identity"])
        with self.assertRaises(adapter.AdapterError):
            adapter.seal_canonical_execution_proof(
                observation=observation, plan_digest=plan["plan_digest"],
                candidate_id=plan["candidate"]["candidate_id"],
                execution_contract_id=plan["candidate"]["execution_contract_id"],
                execution_evidence_id=authority["frozen"]["qualification_evidence_id"],
                stdout=b"x", stderr=observation.stderr_sha256, exit_code=1)

    # Control 11: canonical proof from another subject/plan fails.
    def test_control_11_foreign_proof_fails(self):
        first = _synthetic_authority("Vulkan2", BDF_SYNTH)
        second = _synthetic_authority("Vulkan9", BDF_SYNTH)
        second["frozen"].update({"node_id": "node-other", "compute_unit_id": "cu-other",
                                 "memory_resource_id": "mr-other"})
        plan_second = _synthetic_plan(second)
        with self.assertRaises((harness.HarnessError, participant.ParticipantError)):
            self._execute_with(first, plan=plan_second)

    # Control 12: accounting selector comes from the frozen authority only.
    def test_control_12_accounting_selector_from_authority_only(self):
        authority = _synthetic_authority("Vulkan2", BDF_SYNTH)
        result = self._execute_with(authority)
        self.assertEqual(result["accounting"]["selected_resource"], "Vulkan2")

    # Control 13: the generic planner has no vendor/backend branch.
    def test_control_13_planner_has_no_vendor_branch(self):
        source = (ROOT / "scripts/v1a_execution_participant.py").read_text(encoding="utf-8").lower()
        for token in ("amd", "nvidia", "radeon", "geforce", "cuda", "vulkan1", "vulkan3"):
            self.assertNotIn(token, source)
        harness_source = (ROOT / "scripts/v2a_harness.py").read_text(encoding="utf-8").lower()
        for token in ("amd", "nvidia", "radeon", "geforce", "cuda"):
            self.assertNotIn(token, harness_source)

    # Control 14: evidence IDs from another campaign fail attribution.
    def test_control_14_foreign_evidence_ids_fail(self):
        authority = _synthetic_authority("Vulkan2", BDF_SYNTH)
        plan = _synthetic_plan(authority)
        result = self._execute_with(authority, plan=plan)
        receipt = result["receipt"]
        other = _synthetic_authority("Vulkan9", BDF_SYNTH)
        other_plan = _synthetic_plan(other)
        self.assertNotEqual(receipt["candidate_id"], other_plan["candidate"]["candidate_id"])
        # A proof sealed for the other plan cannot be attributed here.
        with self.assertRaises(participant.ParticipantError):
            participant.execution_receipt(plan=other_plan, output=b"x",
                                          canonical_proof=result["proof"])

    # Control 15: no implicit default proving resource exists.
    def test_control_15_no_implicit_default_proving_resource(self):
        authority = _synthetic_authority("Vulkan2", BDF_SYNTH)
        frozen = authority["frozen"]
        unit = {"execution_unit_id": frozen["execution_unit_id"],
                "execution_contract_id": frozen["execution_contract_id"],
                "required_representation": frozen["required_representation"],
                "required_features": frozen["required_features"],
                "required_memory_bytes": frozen["required_memory_bytes"],
                "required_headroom_bytes": frozen["required_headroom_bytes"],
                "required_integrity_status": frozen["required_integrity_status"],
                "correctness_policy": frozen["correctness_policy"],
                "logical_state_id": frozen["logical_state_id"]}
        decision = participant.plan_execution_unit(execution_unit=unit, compute_units=[],
                                                   objective="MIN_OBJECTIVE_VALUE")
        self.assertIsNone(decision["selected_candidate"])
        self.assertEqual(decision["explanations"], [])


class PortabilityAuditTests(unittest.TestCase):
    def _campaign(self, selector: str, bdf: str, passed: bool = True) -> dict:
        authority = _synthetic_authority(selector, bdf)
        return {
            "authority": authority,
            "qualification": {"result": "PASS" if passed else "FAIL"},
            "canonical": {"result": "PASS" if passed else "FAIL",
                          "correctness": {"byte_exact_visible_output": passed},
                          "accounting": {"unexplained_persistent_host_mirror_bytes": 0,
                                         "source_fetches_after_ready": 0,
                                         "unplanned_state_movements": 0}},
            "harness_source_hashes": {path: harness._sha256_file(ROOT / path)
                                      for path in harness.HARNESS_SOURCES},
        }

    def test_audit_passes_on_data_only_differences(self):
        audit = harness.build_portability_audit(
            [self._campaign("Vulkan2", "01:00.0"), self._campaign("Vulkan9", "0b:02.4")])
        self.assertEqual(audit["result"], "PASS")
        self.assertFalse(audit["subject_specific_code_required"])
        by_aspect = {row["aspect"]: row["classification"] for row in audit["classifications"]}
        self.assertEqual(by_aspect["subject/resource identity, selector, and evidence IDs"],
                         "AUTHORITY_DATA_ONLY")

    def test_audit_fails_on_harness_drift_between_campaigns(self):
        first = self._campaign("Vulkan2", "01:00.0")
        second = self._campaign("Vulkan9", "0b:02.4")
        second["harness_source_hashes"] = {k: "0" * 64 for k in second["harness_source_hashes"]}
        audit = harness.build_portability_audit([first, second])
        self.assertEqual(audit["result"], "FAIL")
        self.assertTrue(audit["subject_specific_code_required"])

    def test_audit_fails_on_falsified_invariant(self):
        audit = harness.build_portability_audit(
            [self._campaign("Vulkan2", "01:00.0"),
             self._campaign("Vulkan9", "0b:02.4", passed=False)])
        self.assertEqual(audit["result"], "FAIL")
        self.assertTrue(audit["foundational_invariant_falsified"])


if __name__ == "__main__":
    unittest.main()

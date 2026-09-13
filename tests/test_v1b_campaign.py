"""Issue #158 CPU-only contract tests for the V1-B second-subject campaign."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import v1b_campaign as campaign  # noqa: E402
import v1a_vulkan_adapter as adapter  # noqa: E402

V1B_AUTHORITY = json.loads(
    (ROOT / "docs/investigations/vulkan-v1-b/PHYSICAL-AUTHORITY.json").read_text(encoding="utf-8"))
V1A_AUTHORITY = json.loads(
    (ROOT / "docs/investigations/vulkan-v1-a/PHYSICAL-AUTHORITY.json").read_text(encoding="utf-8"))

# Accepted retained V0-A second-subject (NV-A / Vulkan3) transcript bytes.
NV_RAW = ROOT / "docs/investigations/vulkan-v0-a/correctness/correction-cor-nvavk-01"

STDERR_NV = """0.01.320.799 I cmn  common_param: device_info:
0.01.323.006 I cmn  common_param:   - Vulkan3 : NVIDIA GeForce RTX 3060 Ti (8438 MiB, 8122 MiB free)
0.02.000.159 I llama_prepare_model_devices: using device Vulkan3 (NVIDIA GeForce RTX 3060 Ti) (0000:04:00.0) - 8099 MiB free
0.02.446.338 I load_tensors: offloading 35 repeating layers to GPU
0.02.446.339 I load_tensors: offloaded 37/37 layers to GPU
"""


class V1BCampaignTests(unittest.TestCase):
    def test_accepted_adapter_parses_second_subject_transcript(self):
        observation = adapter.parse_backend_observation(
            stderr=STDERR_NV, selector="Vulkan3", expected_bdf="04:00.0", node_id="node-inferswarm02",
            compute_unit_id="cu-nv-a", memory_resource_id="mr-nv-a-vram",
            execution_unit_id="unit-q4km-whole-model", execution_contract_id="contract-s2-opaque-v1",
            implementation_id="impl-portable-nv-a", evidence_id="v1b-nv-a-qualification-01",
            runtime_identity=V1B_AUTHORITY["frozen"]["runtime_identity"])
        self.assertEqual(observation.offloaded_layers, (37, 37))
        self.assertEqual(observation.backend_selector, "Vulkan3")
        self.assertEqual(observation.physical_device_bdf, "04:00.0")

    def test_accepted_accounting_reducer_fails_closed_on_second_subject_transcript(self):
        # Mechanical second-subject blocker: the accepted V0-C accounting
        # reducer pins the first subject's selector label and cannot reduce
        # a Vulkan3 transcript. This is the retained finding, not a bypass.
        import v0c_canonical_run as v0c
        stderr = (NV_RAW / "stderr.txt").read_text(encoding="utf-8")
        with self.assertRaises(v0c.AccountingError):
            v0c.parse_accounting(stderr)

    def test_stability_reduction_passes_on_byte_exact_second_subject_output(self):
        stdout = (NV_RAW / "stdout.txt").read_bytes()
        run = {"exit_code": 0, "stdout": stdout, "stderr": STDERR_NV,
               "started_utc": "2026-01-01T00:00:00+00:00", "wall_seconds": 1.0,
               "argv": [], "stdout_sha256": "0" * 64, "stderr_sha256": "0" * 64}
        record = campaign.reduce_stability_execution(
            V1B_AUTHORITY, "v1b-nv-a-stability-01", {"hostname": "inferswarm02"}, run)
        self.assertEqual(record["result"], "PASS")
        self.assertEqual(record["offloaded_layers"], [37, 37])
        self.assertTrue(record["correctness"]["byte_exact_visible_output"])

    def test_stability_reduction_fails_on_dirty_output(self):
        stdout = (NV_RAW / "stdout.txt").read_bytes().replace(b"pangram", b"PANGRAM")
        run = {"exit_code": 0, "stdout": stdout, "stderr": STDERR_NV,
               "started_utc": "2026-01-01T00:00:00+00:00", "wall_seconds": 1.0,
               "argv": [], "stdout_sha256": "0" * 64, "stderr_sha256": "0" * 64}
        record = campaign.reduce_stability_execution(
            V1B_AUTHORITY, "v1b-nv-a-stability-01", {"hostname": "inferswarm02"}, run)
        self.assertEqual(record["result"], "FAIL")

    def test_canonical_reduction_records_fail_closed_accounting_verbatim(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            raw = Path(temp)
            (raw / "stdout.txt").write_bytes((NV_RAW / "stdout.txt").read_bytes())
            (raw / "stderr.txt").write_bytes((NV_RAW / "stderr.txt").read_bytes())
            (raw / "exit-code.txt").write_text("0\n")
            plan = {"plan_digest": "d" * 64, "candidate": {
                "candidate_id": "c" * 64, "node_id": "node-inferswarm02", "compute_unit_id": "cu-nv-a",
                "memory_resource_id": "mr-nv-a-vram", "execution_unit_id": "unit-q4km-whole-model",
                "execution_contract_id": "contract-s2-opaque-v1", "implementation_id": "impl-portable-nv-a",
                "evidence_id": "v1b-nv-a-qualification-01",
                "runtime_identity": V1B_AUTHORITY["frozen"]["runtime_identity"]}}
            record = campaign.reduce_canonical_attempt(V1B_AUTHORITY, plan, raw, runner_exit=1)
        self.assertEqual(record["result"], "FAIL")
        self.assertEqual(record["accounting"]["disposition"], "FAIL_CLOSED")
        self.assertEqual(record["accounting_classification"], "GENERIC_SEAM_CHANGE_REQUIRED")
        self.assertTrue(record["correctness"]["byte_exact_visible_output"])

    def test_cross_subject_audit_classifies_only_accounting_as_seam_change(self):
        qualification = {"schema": "inferswarm.v1a.qualification/1",
                         "attempt": {"wall_seconds": 17.63}}
        candidate_set = {"explanations": [{"candidate_id": "x", "disposition": "SELECTED",
                                           "reason": "SELECTED_BY_OBJECTIVE"}]}
        canonical_attempt = {"accounting_classification": "GENERIC_SEAM_CHANGE_REQUIRED",
                             "accounting": {"error": "missing or ambiguous direct accounting line: Vulkan1 model buffer size"}}
        audit = campaign.build_cross_subject_audit(V1A_AUTHORITY, V1B_AUTHORITY, qualification,
                                                   candidate_set, canonical_attempt)
        self.assertTrue(audit["generic_seam_change_required"])
        self.assertFalse(audit["foundational_invariant_falsified"])
        by_aspect = {row["aspect"]: row for row in audit["classifications"]}
        self.assertEqual(by_aspect["generic participant (eligibility/ranking/plan validation/proof/observation/receipt semantics)"]["classification"],
                         "AUTHORITY_DATA_ONLY")
        self.assertEqual(by_aspect["accepted V0-C materialization/residency accounting reducer"]["classification"],
                         "GENERIC_SEAM_CHANGE_REQUIRED")
        for row in audit["identical_reusable_semantics"]["accepted_source_hashes"].values():
            self.assertTrue(row["identical"])

    def test_v1b_authority_pins_the_same_accepted_sources_as_v1a(self):
        self.assertEqual(V1A_AUTHORITY["frozen"]["v1a_sources"],
                         V1B_AUTHORITY["frozen"]["v1a_sources"])
        self.assertEqual(V1B_AUTHORITY["frozen"]["v1a_sources"],
                         V1B_AUTHORITY["accepted_source_pins"])

    def test_v1b_reference_is_the_accepted_v0a_nv_vk_visible_bytes(self):
        import hashlib
        reference = (ROOT / V1B_AUTHORITY["frozen"]["reference_output"]).read_bytes()
        visible_expected = (
            b"The sentence \"The quick brown fox jumps over the lazy dog\" is a well-known pangram, "
            b"and after this sentence, the next sentence could be anything, as there is no specific "
            b"rule or context provided for what comes next.")
        self.assertEqual(reference, visible_expected)
        self.assertEqual(hashlib.sha256(reference).hexdigest(),
                         "9013db8fb38982f9085754e69fa3feb2f74c7372360da686fe90a3444f26182d")

    def test_wrapper_source_contains_no_subject_special_case(self):
        source = (ROOT / "scripts" / "v1b_campaign.py").read_text(encoding="utf-8").lower()
        for forbidden in ("nvidia", "radeon", "02:00.0", "04:00.0", "vulkan1", "vulkan3"):
            self.assertNotIn(forbidden, source, f"subject special case {forbidden!r} in wrapper")

    def test_wrapper_source_contains_no_ssh_client_usage(self):
        source = (ROOT / "scripts" / "v1b_campaign.py").read_text(encoding="utf-8")
        for forbidden in ("import paramiko", 'subprocess.run(["ssh"', "ssh "):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()

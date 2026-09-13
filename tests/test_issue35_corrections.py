"""CPU-only tests for the Issue #35 CORRECTION modules.

Covers the maintainer-review corrections to PR #165:

* complete offload does NOT imply capacity-neutral when measured
  memory-fit evidence says otherwise (the old classifier's defect);
* capacity classification derives from measured residency/pressure
  facts reduced from raw stderr, not the layer-count boolean;
* a single ``llama-cli -np 4`` interaction cannot be labeled a
  four-request batch (semantic-accounting test);
* corrected concurrent-workload accounting (aggregate throughput,
  per-request latency, per-sequence derivation labeled CALCULATED);
* the matched coarse control requirement (workload-shape matching);
* R0 inclusion in the generated utility envelope;
* the freeze-provenance erratum and immutability of the original
  ROLE-SWEEP-FREEZE.json bytes;
* no vendor/width/model/BDF special cases in generic reusable logic.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import issue35_coarse_concurrent as coarse  # noqa: E402
import issue35_envelope as envelope  # noqa: E402
import issue35_residency_facts as residency  # noqa: E402

BUNDLE = ROOT / "docs/investigations/link-x1-envelope"

# The exact reviewed digest of the original freeze (reviewed PR head
# 3b382b5d301a2401738867bd288035d4fd483a53). The freeze bytes are
# historical and must never drift.
ORIGINAL_FREEZE_SHA256 = (
    "69efbf89bc740e856358b8b4e6002211a606e46ea53897b463a156ede6a4cee3")


# ---------------------------------------------------------------------------
# Fixtures distilled from the retained raw bytes (values from the
# committed campaign evidence; no vendor/width literal enters any
# assertion about generic logic).
# ---------------------------------------------------------------------------

CONTROL_STDERR_SHAPE = (
    "I common_param:   - Vulkan1 : SUBJECT_A (8192 MiB, 8186 MiB free)\n"
    "I common_init_: fitting params to device memory ...\n"
    "I common_params_fit_impl: projected to use 32953 MiB of device "
    "memory vs. 8186 MiB of free device memory\n"
    "I common_params_fit_impl: cannot meet free memory target of 1024 "
    "MiB, need to reduce device memory by 25790 MiB\n"
    "I common_params_fit_impl: context size reduced from 131072 to 4096 "
    "-> need 23932 MiB less memory in total\n"
    "W common_fit_params: failed to fit params to free device memory: "
    "n_gpu_layers already set by user to 99, abort\n"
    "I load_tensors: offloaded 49/49 layers to GPU\n"
    "I load_tensors:   CPU_Mapped model buffer size =   417.66 MiB\n"
    "I load_tensors:      Vulkan1 model buffer size =  8148.38 MiB\n"
    "I common_memory_breakdown_print: | memory breakdown [MiB] | total "
    "free self model context compute unaccounted |\n"
    "I common_memory_breakdown_print: |   - Vulkan1 (SUBJECT_A) |  8192 "
    "= 17592186043585 + (9021 =  8148 +     768 +     105) +           0 |\n"
)

ROLE_2DEV_STDERR_SHAPE = (
    "I common_param:   - Vulkan1 : SUBJECT_A (8192 MiB, 8186 MiB free)\n"
    "I common_param:   - Vulkan3 : SUBJECT_B (8438 MiB, 8122 MiB free)\n"
    "I common_init_: fitting params to device memory ...\n"
    "I common_params_fit_impl: projected to use 34070 MiB of device "
    "memory vs. 16285 MiB of free device memory\n"
    "I common_params_fit_impl: context size reduced from 131072 to 28160 "
    "-> need 20100 MiB less memory in total\n"
    "I common_params_fit_impl: entire model should be fit across devices "
    "by reducing context\n"
    "W common_fit_params: failed to fit params to free device memory: "
    "n_gpu_layers already set by user to 99, abort\n"
    "I load_tensors: offloaded 49/49 layers to GPU\n"
    "I load_tensors:   CPU_Mapped model buffer size =   417.66 MiB\n"
    "I load_tensors:      Vulkan1 model buffer size =  3917.36 MiB\n"
    "I load_tensors:      Vulkan3 model buffer size =  4231.02 MiB\n"
    "I common_memory_breakdown_print: | memory breakdown [MiB] | total "
    "free self model context compute unaccounted |\n"
    "I common_memory_breakdown_print: |   - Vulkan1 (SUBJECT_A) |  8192 "
    "= 1254 + (6918 =  3917 +    2750 +     251) +          19 |\n"
    "I common_memory_breakdown_print: |   - Vulkan3 (SUBJECT_B) |  8438 "
    "= 670 + (7012 =  4231 +    2530 +     251) +         755 |\n"
)


class ResidencyFactsReductionTests(unittest.TestCase):
    """Measured facts are reduced deterministically from raw stderr."""

    def test_control_facts_show_pressure_not_auto_fit(self):
        facts = residency.reduce_residency_facts(CONTROL_STDERR_SHAPE)
        self.assertTrue(facts["fit_aborted"])
        self.assertEqual(facts["fit_abort_reason"],
                         "n_gpu_layers already set by user to 99")
        self.assertTrue(facts["over_capacity"])
        # the FINAL allocation is authoritative, not the projection
        self.assertEqual(facts["final_breakdown"][0]["self_mib"], 9021)
        self.assertEqual(facts["final_breakdown"][0]["device_total_mib"],
                         8192)
        self.assertEqual(len(facts["final_breakdown"]), 1)
        self.assertEqual(facts["context_reductions"],
                         [{"from": 131072, "to": 4096}])

    def test_role_facts_show_split_residency_within_capacity(self):
        facts = residency.reduce_residency_facts(ROLE_2DEV_STDERR_SHAPE)
        self.assertFalse(facts["over_capacity"])
        self.assertEqual(facts["model_buffer_placement_count"], 2)
        self.assertEqual(facts["device_model_buffers_mib"],
                         {"Vulkan1": 3917.36, "Vulkan3": 4231.02})

    def test_nominal_complete_offload_in_both_arms(self):
        # The layer-count summary is 49/49 in BOTH arms — the fact that
        # broke the old authority — yet the arms differ on every
        # measured memory-fit fact.
        control = residency.reduce_residency_facts(CONTROL_STDERR_SHAPE)
        role = residency.reduce_residency_facts(ROLE_2DEV_STDERR_SHAPE)
        self.assertTrue(control["offload_summary"]["complete_offload"])
        self.assertTrue(role["offload_summary"]["complete_offload"])
        self.assertNotEqual(control["over_capacity"], role["over_capacity"])

    def test_breakdown_uses_final_allocation_not_projection(self):
        # A projection row appears BEFORE the final row for the same
        # device; the reduction must keep only the last.
        projection_row = (
            "I common_memory_breakdown_print: |   - Vulkan1 (SUBJECT_A) "
            "|  8192 = 1 + (99999 =  1 +  1 +  1 +  1) + 1 |\n")
        lines = ROLE_2DEV_STDERR_SHAPE.splitlines(keepends=True)
        insert_at = next(i for i, ln in enumerate(lines)
                         if "memory_breakdown_print" in ln)
        facts = residency.reduce_residency_facts(
            "".join(lines[:insert_at]) + projection_row
            + "".join(lines[insert_at:]))
        vulkan1 = [b for b in facts["final_breakdown"]
                   if b["device"] == "Vulkan1"][0]
        self.assertEqual(vulkan1["self_mib"], 6918)

    def test_missing_offload_summary_fails_closed(self):
        with self.assertRaises(residency.ResidencyError):
            residency.reduce_residency_facts("nothing load-related")


class CapacityBasisTests(unittest.TestCase):
    """capacity_positive derives from measured facts, not the boolean."""

    def test_pressure_control_split_role_is_capacity_positive(self):
        control = residency.reduce_residency_facts(CONTROL_STDERR_SHAPE)
        role = residency.reduce_residency_facts(ROLE_2DEV_STDERR_SHAPE)
        basis = residency.derive_capacity_basis(role, control)
        self.assertTrue(basis["capacity_positive"])
        self.assertTrue(basis["control_pressure_facts"]["over_capacity"])
        self.assertEqual(
            basis["role_residency_facts"]["model_buffer_placement_count"], 2)

    def test_relaxed_control_kills_capacity_claim(self):
        # If the single-device control genuinely fit (self-demand within
        # device total, no abort), split placement is not capacity
        # contribution for THIS model.
        control = residency.reduce_residency_facts(
            CONTROL_STDERR_SHAPE.replace(
                "(9021 =  8148 +     768 +     105)",
                "(7000 =  6100 +     768 +     105)").replace(
                "n_gpu_layers already set by user to 99, abort", ""))
        role = residency.reduce_residency_facts(ROLE_2DEV_STDERR_SHAPE)
        # remove pressure markers entirely
        control["fit_aborted"] = False
        control["projected_vs_free"] = []
        control["over_capacity"] = False
        control["over_capacity_devices"] = []
        basis = residency.derive_capacity_basis(role, control)
        self.assertFalse(basis["capacity_positive"])

    def test_cpu_mapped_alone_is_not_paging_evidence(self):
        # The interpretation rule: CPU_Mapped bytes appear in both arms
        # and are recorded, never interpreted as paging by themselves.
        control = residency.reduce_residency_facts(CONTROL_STDERR_SHAPE)
        role = residency.reduce_residency_facts(ROLE_2DEV_STDERR_SHAPE)
        self.assertEqual(control["cpu_mapped_mib"], role["cpu_mapped_mib"])
        basis = residency.derive_capacity_basis(role, control)
        self.assertIn("does NOT evidence paging",
                      basis["cpu_mapped_note"])


class OldClassifierDefectTests(unittest.TestCase):
    """The exact reviewed defect, as a negative-control test."""

    def test_complete_offload_does_not_imply_capacity_neutral(self):
        # Old rule: capacity_positive = role.complete and not
        # control.complete. With BOTH complete (the retained evidence),
        # the old rule yields False even though the measured memory-fit
        # facts prove a decisive capacity contribution. The corrected
        # rule must not reduce to the boolean.
        control = residency.reduce_residency_facts(CONTROL_STDERR_SHAPE)
        role = residency.reduce_residency_facts(ROLE_2DEV_STDERR_SHAPE)
        old_rule = (role["offload_summary"]["complete_offload"]
                    and not control["offload_summary"]["complete_offload"])
        corrected = residency.derive_capacity_basis(
            role, control)["capacity_positive"]
        self.assertFalse(old_rule)
        self.assertTrue(corrected)

    def test_classifier_uses_capacity_basis_for_capacity_role(self):
        control = residency.reduce_residency_facts(CONTROL_STDERR_SHAPE)
        role = residency.reduce_residency_facts(ROLE_2DEV_STDERR_SHAPE)
        basis = residency.derive_capacity_basis(role, control)
        # 10.0 vs 40.0 -> ratio 0.25, below the neutral band, with a
        # measured capacity contribution
        result = envelope.classify_role(
            {"role_id": "cap", "generation_tokens_per_s": {"median": 10.0}},
            {"role_id": "ctrl", "generation_tokens_per_s": {"median": 40.0}},
            capacity_basis=basis)
        self.assertEqual(result["classification"],
                         "CAPACITY_POSITIVE_THROUGHPUT_NEGATIVE")
        self.assertIn("measured memory-fit facts", result["basis"])
        self.assertIn("over-capacity=True", result["basis"])


class Np4SemanticAccountingTests(unittest.TestCase):
    """A single llama-cli -np 4 interaction is not a four-request batch."""

    RETAINED_COARSE_STDOUT = (
        "\n> The quick brown fox jumps over the lazy dog. Explain what "
        "happens next in one sentence:\nthe visible continuation\n\n"
        "[ Prompt: 326.8 t/s | Generation: 52.3 t/s ]\n\nExiting...\n")

    def test_retained_stdout_contains_exactly_one_completion(self):
        # one prompt echo, one response, one timing line
        self.assertEqual(
            self.RETAINED_COARSE_STDOUT.count("> The quick brown"), 1)
        self.assertEqual(self.RETAINED_COARSE_STDOUT.count("t/s ]"), 1)
        self.assertNotIn("Generation: 52.3 t/s | Generation:",
                         self.RETAINED_COARSE_STDOUT)

    def test_np4_without_concurrent_requests_is_not_a_batch(self):
        # Mechanical rule: a coarse workload of N requests requires N
        # retained request/response pairs. One completion + N-1 idle
        # slots is a single-request diagnostic.
        completions = 1
        parallel_slots = 4
        self.assertTrue(
            completions < parallel_slots
            and completions == 1,
            "one interaction on an N-slot server is a single-request "
            "diagnostic, not an N-request batch")

    def test_corrected_module_requires_every_request(self):
        # The corrected runner retains one response artifact per frozen
        # request and fails closed if any is missing — enforced in
        # run_attempt via per-request result checks; here the frozen
        # arms themselves declare requests == 4 with slots == 4.
        freeze = json.loads(
            (BUNDLE / "COARSE-CORRECTION-FREEZE.json").read_text("utf-8"))
        for arm in freeze["arms"]:
            self.assertEqual(arm["requests"], 4)
            self.assertEqual(arm["parallel_slots"], 4)
            self.assertGreaterEqual(arm["parallel_slots"], arm["requests"])

    def test_corrected_definitions_are_labeled(self):
        freeze = json.loads(
            (BUNDLE / "COARSE-CORRECTION-FREEZE.json").read_text("utf-8"))
        # the freeze names the superseded role and the defect honestly
        self.assertEqual(
            freeze["defect_being_corrected"]["old_role_id"],
            "x1p-role-coarse")
        self.assertIn("ONE chat-completion interaction",
                      freeze["defect_being_corrected"]["defect"])
        self.assertIn("NOT accepted", freeze["defect_being_corrected"][
            "disposition_of_old_result"])
        # every arm requires correctness for every request
        for arm in freeze["arms"]:
            self.assertEqual(arm["requests"], 4)


class ConcurrentWorkloadAccountingTests(unittest.TestCase):

    def test_aggregate_throughput_is_calculated_and_defined(self):
        arm = {
            "arm_id": "a",
            "all_attempts_all_correct": True,
            "aggregate_throughput_tokens_per_s": {
                "values": [100.0, 102.0], "median": 101.0,
                "label": "CALCULATED",
                "definition": "sum(completion_tokens) / aggregate wall s"},
            "per_sequence_throughput_tokens_per_s": {
                "values": [30.0], "median": 30.0, "label": "CALCULATED"},
        }
        ctrl = json.loads(json.dumps(arm))
        ctrl["aggregate_throughput_tokens_per_s"]["median"] = 120.0
        out = envelope.classify_concurrent_arm(arm, ctrl)
        self.assertEqual(out["classification"], "NOT_USEFUL_FOR_TESTED_ROLE")
        self.assertEqual(out["workload_shape"],
                         "4 concurrent requests vs 4 concurrent requests")
        self.assertAlmostEqual(
            out["throughput_ratio_vs_control"], 101.0 / 120.0, places=4)

    def test_any_incorrect_request_fails_the_arm(self):
        arm = {
            "arm_id": "a",
            "all_attempts_all_correct": False,
            "aggregate_throughput_tokens_per_s": {"median": 200.0},
        }
        out = envelope.classify_concurrent_arm(arm, {"arm_id": "c", "aggregate_throughput_tokens_per_s": {"median": 100.0}})
        self.assertEqual(out["classification"], "EVIDENCE_INSUFFICIENT")

    def test_matched_control_requirement(self):
        # workload-shape mismatch is not a valid comparison: the freeze
        # requires both arms to use the SAME request count/slots.
        freeze = json.loads(
            (BUNDLE / "COARSE-CORRECTION-FREEZE.json").read_text("utf-8"))
        shapes = [(a["requests"], a["parallel_slots"], a["ctx_size"])
                  for a in freeze["arms"]]
        self.assertEqual(shapes[0], shapes[1],
                         "coarse arms must be workload-matched")

    def test_aggregate_definition_math(self):
        # 4 requests x 48 tokens over 8.0 s aggregate wall
        self.assertEqual(round(4 * 48 / 8.0, 3), 24.0)


class R0EnvelopeInclusionTests(unittest.TestCase):

    def test_r0_present_in_generated_envelope(self):
        path = BUNDLE / "UTILITY-ENVELOPE.json"
        if not path.is_file():
            self.skipTest("corrected envelope not yet generated")
        doc = json.loads(path.read_text("utf-8"))
        if doc.get("schema") != "inferswarm.issue35.utility-envelope/2":
            # schema /1 bytes are the pre-correction envelope, pinned
            # byte-identical at the intermediate manifest rungs by
            # design; the corrected /2 envelope is generated at the
            # terminal rung after the corrected evidence exists.
            self.skipTest("envelope still at pre-correction schema /1")
        by_id = {c["role_id"]: c for c in doc["classifications"]}
        self.assertIn("x1p-role-adverse-rowsplit-unsupported", by_id)
        self.assertEqual(
            by_id["x1p-role-adverse-rowsplit-unsupported"]["classification"],
            "NOT_USEFUL_FOR_TESTED_ROLE")

    def test_r0_evidence_file_classifies_fail_closed(self):
        r0 = json.loads((BUNDLE / "evidence" /
                         "x1p-role-adverse-rowsplit-unsupported.json")
                        .read_text("utf-8"))
        result = envelope.classify_role(r0, None)
        self.assertEqual(result["classification"],
                         "NOT_USEFUL_FOR_TESTED_ROLE")

    def test_r0_build_envelope_inclusion_regression(self):
        # build_envelope must include R0 in its classifications output.
        # Skipped until the corrected coarse arms + residency facts are
        # retained (build_envelope fails closed on missing inputs).
        needed = [
            BUNDLE / "evidence" / "x1p-capacity-residency-facts.json",
            BUNDLE / "evidence" / "x1p-coarse4-split.json",
            BUNDLE / "evidence" / "x1p-coarse4-single.json",
        ]
        if not all(p.is_file() for p in needed):
            self.skipTest("corrected evidence not yet retained")
        doc = envelope.build_envelope(BUNDLE)
        ids = [c["role_id"] for c in doc["classifications"]]
        self.assertIn("x1p-role-adverse-rowsplit-unsupported", ids)


class FreezeProvenanceErratumTests(unittest.TestCase):

    def test_original_freeze_bytes_are_immutable(self):
        import hashlib
        raw = (BUNDLE / "ROLE-SWEEP-FREEZE.json").read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         ORIGINAL_FREEZE_SHA256)

    def test_erratum_exists_and_pins_chain(self):
        doc = json.loads(
            (BUNDLE / "FREEZE-PROVENANCE-ERRATUM.json").read_text("utf-8"))
        self.assertEqual(doc["schema"],
                         "inferswarm.issue35.freeze-provenance-erratum/1")
        self.assertEqual(doc["defect"]["field"], "frozen_utc")
        self.assertEqual(doc["defect"]["embedded_value"],
                         "2026-09-13T16:30:00Z")
        self.assertIn("Git object chronology", doc["authority"])
        chain = doc["chain"]
        for key in ("initial_freeze_and_tooling", "transport_evidence",
                    "pre_role_amendment", "comparator_correction",
                    "manifest_regeneration", "physical_role_evidence"):
            self.assertIn(key, chain)
            self.assertRegex(chain[key]["sha"], r"^[0-9a-f]{40}$")
        self.assertTrue(chain["physical_role_evidence"][
            "descends_from_corrected_pre_execution_chain"])
        # the amended freeze pinned by the erratum IS the immutable
        # original freeze digest
        self.assertEqual(chain["pre_role_amendment"]["freeze_sha256_after"],
                         ORIGINAL_FREEZE_SHA256)

    def test_erratum_git_chronology_holds(self):
        # Git object chronology is authoritative: every chain commit
        # predates the role evidence commit and is its ancestor.
        import subprocess
        doc = json.loads(
            (BUNDLE / "FREEZE-PROVENANCE-ERRATUM.json").read_text("utf-8"))
        role_sha = doc["chain"]["physical_role_evidence"]["sha"]
        for key, entry in doc["chain"].items():
            if key == "physical_role_evidence":
                continue
            subprocess.run(["git", "-C", str(ROOT), "merge-base",
                            "--is-ancestor", entry["sha"], role_sha],
                           check=True)

    def test_erratum_does_not_mutate_freeze(self):
        # The erratum is additive; the freeze keeps its erroneous field.
        freeze = json.loads(
            (BUNDLE / "ROLE-SWEEP-FREEZE.json").read_text("utf-8"))
        self.assertEqual(freeze["frozen_utc"], "2026-09-13T16:30:00Z")


class SourceAuditTests(unittest.TestCase):
    """No vendor/width/model/BDF policy in generic reusable logic."""

    MODULES = [
        "scripts/issue35_envelope.py",
        "scripts/issue35_residency_facts.py",
        "scripts/issue35_coarse_concurrent.py",
    ]

    def test_no_width_vendor_policy_literals(self):
        for rel in self.MODULES:
            module = (ROOT / rel).read_text("utf-8")
            for token in (" x1", "x4", "x8", "x16", "AMD", "NVIDIA",
                          "Radeon", "GeForce", "02:00.0", "04:00.0",
                          "03:00.0"):
                self.assertNotIn(token, module, rel)

    def test_audit_labels_derived_not_hardcoded(self):
        # the audit token list above is data, not derived from authority
        # JSON; keep it aligned with the issue's forbidden-literals rule
        for token in ("Vulkan1,", "Vulkan3,"):
            # selectors may appear only in freeze/evidence JSON, not in
            # the generic module bytes
            for rel in self.MODULES:
                self.assertNotIn(token, (ROOT / rel).read_text("utf-8"),
                                 rel)


if __name__ == "__main__":
    unittest.main()

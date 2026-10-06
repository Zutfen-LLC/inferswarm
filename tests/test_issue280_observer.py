"""CPU recording fixtures exercise the Issue #280 collector, not proof dicts."""
from pathlib import Path
import importlib.util
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/issue280_observer.py"
INSTR = ROOT / "docs/investigations/vulkan-same-request-280/instrumentation"
FIXTURES = ROOT / "docs/investigations/vulkan-same-request-280/fixtures"


class CollectorRecordingTests(unittest.TestCase):
    def collect(self, case, contract=None):
        self.assertTrue(SCRIPT.is_file(), "real Issue #280 collector is missing")
        spec = importlib.util.spec_from_file_location("issue280_observer", SCRIPT)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as td:
            binary = Path(td) / "cpu-recording"
            subprocess.run(["c++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                            "-I", str(INSTR), str(FIXTURES / "recording.cpp"),
                            "-o", str(binary)], check=True, capture_output=True, text=True)
            raw = subprocess.run([str(binary), case], check=True,
                                 capture_output=True, text=True).stdout
            return module.collect(raw, contract or module.fixture_contract()), raw

    def test_prefill_then_decode_eos_recording(self):
        result, raw = self.collect("positive")
        self.assertIn("I280 ", raw)
        self.assertTrue(result["ok"], result["problems"])
        self.assertEqual(result["claim"], "CPU_RECORDING_REPLAY_ONLY")
        self.assertEqual(result["physical_runner"], "HELD_UNAVAILABLE")
        self.assertEqual(len(result["graphs"]), 3)
        self.assertEqual(result["sampled_tokens"], 3)
        self.assertEqual(result["non_eos_tokens"], 2)
        self.assertEqual(result["logical_boundary_bytes"], 96)
        self.assertEqual(result["host_leg_bytes"], 192)
        self.assertEqual(result["boundary_elapsed_ns"], 90)
        self.assertIsNone(result["pcie_wire_bytes"])

    def test_empty_submit_does_not_prove_compute(self):
        result, _ = self.collect("empty-submit")
        self.assertFalse(result["ok"])
        self.assertIn("graph 0: no completed nonempty compute on 0000:02:00.0", result["problems"])

    def test_missing_completion(self):
        result, _ = self.collect("missing-completion")
        self.assertFalse(result["ok"])
        self.assertIn("unfinished compute submissions", "\n".join(result["problems"]))

    def test_missing_host_leg(self):
        result, _ = self.collect("missing-host-leg")
        self.assertFalse(result["ok"])
        self.assertIn("host staging legs", "\n".join(result["problems"]))

    def test_request_mismatch(self):
        result, _ = self.collect("wrong-request")
        self.assertFalse(result["ok"])
        self.assertIn("request mismatch", "\n".join(result["problems"]))

    def test_output_length_mismatch(self):
        result, _ = self.collect("wrong-output")
        self.assertFalse(result["ok"])
        self.assertIn("response sampled count", "\n".join(result["problems"]))

    def test_boundary_byte_mismatch(self):
        result, _ = self.collect("wrong-bytes")
        self.assertFalse(result["ok"])
        self.assertIn("expected logical bytes", "\n".join(result["problems"]))

    def test_nested_leg_time_not_added_to_outer_elapsed(self):
        result, _ = self.collect("positive")
        self.assertEqual(result["boundary_elapsed_ns"], 90)

    def test_completion_cannot_precede_submit(self):
        result, _ = self.collect("early-completion")
        self.assertFalse(result["ok"])
        self.assertIn("completion has no pending submission", "\n".join(result["problems"]))

    def test_no_decode_for_first_sample_or_terminal_eos(self):
        result, _ = self.collect("eos-first")
        self.assertTrue(result["ok"], result["problems"])
        self.assertEqual(len(result["graphs"]), 1)
        self.assertEqual(result["sampled_tokens"], 1)
        self.assertEqual(result["non_eos_tokens"], 0)

    def test_source_shaped_staging_and_timeline_completion(self):
        result, _ = self.collect("native-path")
        self.assertTrue(result["ok"], result["problems"])
        self.assertEqual(result["logical_boundary_bytes"], 96)

    def test_timeline_completion_cannot_claim_unrecorded_value(self):
        result, _ = self.collect("timeline-stale")
        self.assertFalse(result["ok"])
        self.assertIn("timeline completion identity", "\n".join(result["problems"]))

    def test_source_log_cannot_be_promoted_to_physical_evidence(self):
        result, _ = self.collect("source-identity")
        self.assertTrue(result["ok"], result["problems"])
        self.assertEqual(result["claim"], "SOURCE_LOG_REPLAY_ONLY_NOT_PHYSICAL_PROOF")
        self.assertEqual(result["physical_runner"], "HELD_UNAVAILABLE")

    def test_non_eos_limit_uses_actual_sample_count(self):
        result, _ = self.collect("limit")
        self.assertTrue(result["ok"], result["problems"])
        self.assertEqual(result["non_eos_tokens"], 3)

    def test_schema_duplicate_fields_refused(self):
        result, raw = self.collect("positive")
        spec = importlib.util.spec_from_file_location("observer_duplicate", SCRIPT)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        broken = raw.replace('"tokens":4', '"tokens":4,"tokens":4', 1)
        out = module.collect(broken, module.fixture_contract())
        self.assertFalse(out["ok"])
        self.assertIn("duplicate field", "\n".join(out["problems"]))

    def test_missing_preexecution_boundary_manifest(self):
        result, _ = self.collect("missing-manifest")
        self.assertFalse(result["ok"])
        self.assertIn("boundary manifest", "\n".join(result["problems"]))

    def test_prefill_microbatch_graphs_use_actual_token_count(self):
        result, _ = self.collect("microbatch")
        self.assertTrue(result["ok"], result["problems"])
        self.assertEqual(len(result["graphs"]), 4)
        self.assertEqual(result["sampled_tokens"], 3)
        self.assertEqual(result["logical_boundary_bytes"], 96)

    def test_abort_retains_pending_work_without_success(self):
        result, _ = self.collect("abort")
        self.assertFalse(result["ok"])
        self.assertTrue(result["graphs"])
        self.assertIn("unfinished compute submissions", result["problems"])
        self.assertEqual(result["sampled_tokens"], 0)

    def test_disabled_emitter_is_inert(self):
        _, raw = self.collect("disabled")
        self.assertEqual(raw, "")

    def test_native_zero_first_use_is_admitted(self):
        """Review finding 1: native first-use zero is valid, not invalid use."""
        result, _ = self.collect("native-zero-first-use")
        self.assertTrue(result["ok"], result["problems"])
        self.assertEqual(result["graphs"][0]["completed_compute"]["0000:01:00.0"][0]["command"],
                         ["cmd0", 0])

    def test_repeated_successful_timeline_wait_is_idempotent(self):
        """Review finding 2: repeat wait preserves the completed command set."""
        result, _ = self.collect("repeated-successful-timeline-wait")
        self.assertTrue(result["ok"], result["problems"])
        self.assertEqual(len(result["graphs"][0]["completed_compute"]["0000:01:00.0"]), 1)

    def test_unsubmitted_compute_recording_is_rejected(self):
        """Review finding 3: recorded compute without a submit must be named."""
        result, _ = self.collect("unsubmitted-compute-recording")
        self.assertIn("unsubmitted compute", "\n".join(result["problems"]))

    def test_copy_manifest_shape_range_is_recomputed(self):
        """Review finding 4: bytes must agree with the manifest shape range."""
        result, _ = self.collect("inconsistent-shape-bytes")
        self.assertIn("range", "\n".join(result["problems"]))

    def test_decode_consumed_token_must_match_previous_sample(self):
        """Review finding 5: bind token IDs; target rejection contains 'decode token'."""
        result, _ = self.collect("decode-token-mismatch")
        self.assertIn("decode token", "\n".join(result["problems"]))

    def test_decode_absolute_position_must_advance_by_one(self):
        """Review finding 6: target rejection for a bad absolute position is 'decode position'."""
        result, _ = self.collect("wrong-absolute-decode-position")
        self.assertIn("decode position", "\n".join(result["problems"]))

    def test_single_die_completed_compute_is_admitted(self):
        """Review finding 7 (Arm A): one-BDF compute is a valid baseline."""
        die = "0000:01:00.0"
        contract = {"kind": "CPU_FIXTURE", "dies": [die],
                    "layers": {die: [0]}, "boundaries": []}
        result, _ = self.collect("single-die-baseline", contract)
        self.assertTrue(result["ok"], result["problems"])
        self.assertTrue(result["graphs"][0]["completed_compute"][die])

    def test_two_sequential_requests_have_independent_framing(self):
        """Review finding 8: request 7 then fresh request 8 are both admitted."""
        result, _ = self.collect("two-sequential-requests")
        self.assertTrue(result["ok"], result["problems"])
        self.assertEqual([request["request"] for request in result["requests"]], [7, 8])

    def test_warm_request_attribution_cannot_cross_request_boundary(self):
        """Review finding 9: target rejection for inherited frame ownership is 'cross-request'."""
        result, _ = self.collect("warm-request-no-inheritance")
        self.assertIn("cross-request", "\n".join(result["problems"]))

    def test_abort_preserves_completed_work_and_is_structured(self):
        """Review finding 10: abort exposes disposition and retains prior work, never success."""
        result, _ = self.collect("abort-preserves-work")
        self.assertEqual(result.get("disposition"), "ABORTED",
                         "abort must expose structured ABORTED disposition")
        self.assertFalse(result["ok"])
        self.assertEqual(result["sampled_tokens"], 1)
        self.assertEqual(result["logical_boundary_bytes"], 16)
        self.assertTrue(result["graphs"][0]["completed_compute"]["0000:01:00.0"])

    def test_abort_accounts_for_unsubmitted_compute(self):
        """Review finding 11: abort accounting explicitly lists unsubmitted compute."""
        result, _ = self.collect("abort-unsubmitted-accounting")
        accounting = result.get("abort_accounting", {})
        self.assertTrue(accounting.get("unsubmitted_compute"),
                        "unsubmitted compute must be explicitly listed in abort accounting")

    def test_missing_declared_placement_category_is_rejected(self):
        """Review finding 12: unexplained state ownership must fail with 'placement'."""
        die0, die1 = "0000:01:00.0", "0000:02:00.0"
        contract = {"kind": "CPU_FIXTURE", "dies": [die0, die1],
                    "layers": {die0: [0], die1: [1]},
                    "boundaries": [{"tensor": "ffn_out-0", "src": die0,
                                    "dst": die1, "bytes_per_token": 16}],
                    "placement": {"required_categories": ["weights", "kv_cache"]}}
        result, _ = self.collect("placement-ownership-unexplained", contract)
        self.assertIn("placement", "\n".join(result["problems"]))

    def test_repeat_copy_occurrences_are_distinct_and_reconciled(self):
        spec = importlib.util.spec_from_file_location("observer_repeat_copy", SCRIPT)
        assert spec is not None and spec.loader is not None
        contract = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(contract)
        expected = contract.fixture_contract()
        expected["boundaries"][0]["occurrences"] = 2
        result, _ = self.collect("repeat-copy", expected)
        self.assertTrue(result["ok"], result["problems"])
        self.assertEqual([copy["occ"] for copy in result["graphs"][0]["boundaries"]], [0, 1])
        self.assertEqual(result["logical_boundary_bytes"], 192)
        self.assertEqual(result["host_leg_bytes"], 384)

    def test_conflicting_open_timeline_identity_fails_closed(self):
        result, _ = self.collect("conflicting-wait")
        self.assertFalse(result["ok"])
        self.assertIn("timeline record", "\n".join(result["problems"]))

    def test_abort_preserves_incomplete_copy_as_unknown(self):
        result, _ = self.collect("abort-incomplete-copy")
        self.assertFalse(result["ok"])
        self.assertEqual(result["requests"][0]["incomplete_copies"], 1)
        self.assertEqual(result["requests"][0]["incomplete_copy_intervals"][0]["interval_status"], "UNKNOWN")
        self.assertEqual(result["incomplete_boundary"]["elapsed_ns"], None)

    def test_abort_completed_copy_aggregates_are_request_scoped(self):
        result, _ = self.collect("abort-preserves-work")
        self.assertEqual(result["requests"][0]["logical_boundary_bytes"], 16)
        self.assertEqual(result["requests"][0]["host_leg_bytes"], 32)
        self.assertEqual(result["requests"][0]["boundary_elapsed_ns"], 30)
        self.assertEqual(result["requests"][0]["completed_copies"][0]["bytes"], 16)

    def test_planned_unaccepted_request_is_not_attempted(self):
        spec = importlib.util.spec_from_file_location("observer_planned", SCRIPT)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        contract = module.fixture_contract()
        contract["requests"] = {"planned": 2}
        result, _ = self.collect("abort-second-not-attempted", contract)
        self.assertEqual([request["disposition"] for request in result["requests"]],
                         ["aborted", "not_attempted"])
        self.assertEqual(result["requests"][1]["ordinal"], 2)
        self.assertFalse(result["ok"])

    def test_cross_request_evidence_alias_is_rejected(self):
        spec = importlib.util.spec_from_file_location("observer_alias", SCRIPT)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        contract = module.fixture_contract()
        contract["requests"] = {"planned": 2}
        result, _ = self.collect("cross-request-alias", contract)
        self.assertIn("cross-request", "\n".join(result["problems"]))

    def test_copy_type_and_range_checks_fail_closed(self):
        for mode, expected in (("unsupported-type", "unsupported tensor type"),
                               ("range-overflow", "range overflow")):
            with self.subTest(mode=mode):
                result, _ = self.collect(mode)
                self.assertFalse(result["ok"])
                self.assertIn(expected, "\n".join(result["problems"]))

    def test_two_requests_reuse_timeline_identity_in_independent_namespaces(self):
        spec = importlib.util.spec_from_file_location("observer_namespaces", SCRIPT)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        contract = module.fixture_contract()
        contract["requests"] = {"planned": 2}
        result, _ = self.collect("two-requests", contract)
        self.assertTrue(result["ok"], result["problems"])
        self.assertEqual([request["request"] for request in result["requests"]], [7, 8])
        self.assertEqual(len(result["requests"][0]["completed_submissions"]),
                         len(result["requests"][1]["completed_submissions"]))

    def test_request_accept_and_end_framing_is_mandatory(self):
        result, raw = self.collect("positive")
        self.assertTrue(result["ok"], result["problems"])
        spec = importlib.util.spec_from_file_location("observer_framing", SCRIPT)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        without_accept = "\n".join(line for line in raw.splitlines()
                                     if '"event":"request_accept"' not in line)
        missing_accept = module.collect(without_accept, module.fixture_contract())
        self.assertIn("request framing", "\n".join(missing_accept["problems"]))
        without_end = "\n".join(line for line in raw.splitlines()
                                  if '"event":"request_end"' not in line)
        missing_end = module.collect(without_end, module.fixture_contract())
        self.assertIn("request framing", "\n".join(missing_end["problems"]))

    def test_placement_inventory_is_separate_from_dispatch_operands(self):
        result, _ = self.collect("positive")
        self.assertTrue(result["ok"], result["problems"])
        self.assertEqual(result["placement_denominator_bytes"], 2048)
        self.assertEqual(result["placement"]["placement_denominator_bytes"], 2048)
        self.assertEqual(result["placement"]["dies"]["0000:01:00.0"]["placement_numerator_bytes"], 1024)
        self.assertEqual(result["placement"]["dies"]["0000:02:00.0"]["placement_numerator_bytes"], 1024)

    def test_repeated_wait_is_counted_without_duplicate_compute(self):
        result, _ = self.collect("repeat-wait")
        self.assertTrue(result["ok"], result["problems"])
        self.assertEqual(result["repeated_waits"], 6)
        self.assertEqual(len(result["graphs"][0]["completed_compute"]["0000:01:00.0"]), 1)

    def test_word_stop_completed_request_is_accepted(self):
        """Emitter alignment: STOP_TYPE_WORD terminal is a completed request.

        The pinned release() hook emits stop_reason "word" for STOP_TYPE_WORD;
        the collector must classify it completed, not abort it.
        """
        result, _ = self.collect("word-stop-full-request")
        self.assertTrue(result["ok"], result["problems"])
        self.assertEqual(result["requests"][0]["stop_reason"], "word")
        self.assertEqual(result["requests"][0]["disposition"], "completed")

    def test_none_stop_after_response_is_completed(self):
        """Emitter alignment: response + stop_reason "none" (release() without a
        set stop_type) is a completed request, not an aborted one."""
        result, _ = self.collect("none-stop-after-response")
        self.assertTrue(result["ok"], result["problems"])
        self.assertEqual(result["requests"][0]["stop_reason"], "none")
        self.assertEqual(result["requests"][0]["disposition"], "completed")

    def test_cpu_named_inventory_is_cpu_owned_not_die_credited(self):
        """Emitter alignment: the pinned hooks fall back to the backend NAME
        ("CPU") when a buffer's device exposes no BDF; those rows are CPU-owned
        state — in the denominator, never in a candidate-die numerator."""
        contract = {"kind": "CPU_FIXTURE", "dies": ["0000:01:00.0", "0000:02:00.0"],
                    "layers": {"0000:01:00.0": [0], "0000:02:00.0": [1]},
                    "boundaries": [{"tensor": "ffn_out-0", "src": "0000:01:00.0",
                                    "dst": "0000:02:00.0", "bytes_per_token": 16}]}
        import os
        os.environ["I280_CPU_ONLY_INVENTORY"] = "1"
        try:
            result, _ = self.collect("positive", contract)
        finally:
            del os.environ["I280_CPU_ONLY_INVENTORY"]
        self.assertTrue(result["ok"], result["problems"])
        self.assertEqual(result["placement"]["cpu_weight_bytes"], 300)
        self.assertEqual(result["placement_denominator_bytes"], 2348)
        self.assertEqual(result["placement"]["die_numerators_sum_bytes"], 2048)
        self.assertEqual(result["placement"]["denominator_relation"],
                         "die_numerators_sum_bytes + cpu_weight_bytes == placement_denominator_bytes")
        for die in ("0000:01:00.0", "0000:02:00.0"):
            self.assertEqual(result["placement"]["dies"][die]["placement_numerator_bytes"], 1024)

    def test_swapped_inventory_layers_are_rejected(self):
        """Review finding E2: inventory must cover the layers each die's own
        dispatched compute reads; swapped ownership cannot pass."""
        result, _ = self.collect("placement-swapped-layers")
        self.assertFalse(result["ok"])
        joined = "\n".join(result["problems"])
        self.assertTrue("absent from its weight inventory" in joined
                        or "layer ownership disagrees with contract" in joined,
                        f"no E2 rejection in {result['problems']}")

    def test_staging_buffer_cannot_double_as_weights(self):
        """Review finding E3: one buffer identity cannot be declared in two
        placement categories; staging bytes never enter weight numerators."""
        result, _ = self.collect("staging-as-weights")
        self.assertFalse(result["ok"])
        joined = "\n".join(result["problems"])
        self.assertTrue("declared as both" in joined
                        or "duplicate weight inventory row" in joined,
                        f"no E3 rejection in {result['problems']}")

    def test_unbacked_copy_range_fails_closed_on_success(self):
        """Review finding B13: a consumed copy occurrence with no declared
        backing-buffer bounds is unprovable and fails a successful request."""
        result, _ = self.collect("missing-bounds")
        self.assertFalse(result["ok"])
        joined = "\n".join(result["problems"])
        self.assertIn("without any backing buffer bounds", joined)


if __name__ == "__main__":
    unittest.main()

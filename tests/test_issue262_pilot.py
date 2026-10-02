"""Issue #262 pilot producer: offline law tests (no physical execution)."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import issue262_pilot as P
import issue262_h5 as H

ROUTE_LINE = (
    "0.05.069.746 I ggml_vk_i262:v1|route|id=1|graph=1|weight=output.weight"
    "|node=result.output|side=0|route=mat-vec"
    "|pipe=mul_mat_vec_q4_k_f32_f32|family=mmv|quant_y=0|split_k=0"
    "|64b=0|dims=2560x248320:2560x1->248320x1|types=q4_K*f32->f32\n")


def i260_log(arm="BASE"):
    p = "ggml_vk_i260:v1|"
    submit = p + "submit|graph=1|id=1|phase=submit|path=normal\n"
    memory = p + "memory|role=backend|buffer=1|branch=default|type=0|flags=0xf\n"
    tensor = (p + "tensor|name=output.weight|buffer=1|offset=8|bytes=16"
              "|allocation_size=64\n")
    return (p + "graph|id=1|phase=begin\n" + submit
            + p + "graph|id=1|phase=end|compute_submits=1\n"
            + memory + tensor + ROUTE_LINE)


class GeometryTests(unittest.TestCase):
    def test_arm_env_single_factor_law(self):
        self.assertEqual(P.ARM_ENV["BASE"], {})
        for arm, env in P.ARM_ENV.items():
            if arm == "BASE":
                continue
            self.assertEqual(len(env), 1, f"{arm} must be one-factor")
            key = next(iter(env))
            self.assertEqual(env[key], "1")
        self.assertEqual(
            next(iter(P.ARM_ENV["A1"])), "GGML_VK_SERIALIZE_SUBMISSIONS")
        self.assertEqual(
            next(iter(P.ARM_ENV["A5"])), "GGML_VK_DISABLE_HOST_VISIBLE_VIDMEM")
        self.assertEqual(
            next(iter(P.ARM_ENV["A4"])), "GGML_VK_PREFER_HOST_MEMORY")
        self.assertEqual(
            next(iter(P.ARM_ENV["H5_CANDIDATE"])), "GGML_VK_DISABLE_COOPMAT2")

    def test_launch_env_carries_frozen_observer_and_placement_law(self):
        env = P.launch_env("A1", Path("/tmp/x/obs"))
        self.assertEqual(env["CUDA_VISIBLE_DEVICES"], "-1")
        self.assertEqual(env["VK_ICD_FILENAMES"],
                         "/usr/share/vulkan/icd.d/nvidia_icd.json")
        self.assertEqual(env["GGML_VK_VISIBLE_DEVICES"], "0")
        self.assertEqual(env["LLAMA_OBSERVE_CAPTURE"], "8")
        self.assertEqual(env["LLAMA_OBSERVE_OUT"], "/tmp/x/obs")
        self.assertEqual(env["GGML_VK_SERIALIZE_SUBMISSIONS"], "1")
        base = P.launch_env("BASE", Path("/tmp/x/obs"))
        self.assertNotIn("GGML_VK_SERIALIZE_SUBMISSIONS", base)

    def test_launch_argv_is_frozen_case3072_shape(self):
        argv = P.launch_argv(Path("/bin/llama-server"))
        self.assertEqual(argv[1:5], ["--model",
                                     "/srv/models/qwen38-ud-iq1-s/"
                                     "Qwen3.8-Flash-Next-UD-IQ1_S-00001-of-00003.gguf",
                                     "-ngl", "1"])
        self.assertIn("8192", argv)
        self.assertIn("19000", argv)

    def test_unknown_arm_refused(self):
        with self.assertRaises(P.PilotError):
            P.launch_env("A6", Path("/tmp/x"))
        with self.assertRaises(P.PilotError):
            P.launch_env("H5_CANDIDATE_X", Path("/tmp/x"))


class MarkerParsingTests(unittest.TestCase):
    def test_baseline_log_parses_h2h3_and_h5(self):
        markers = P.parse_unit_markers(i260_log("BASE").encode(), "BASE")
        self.assertEqual(markers["h2h3"]["submission"], "normal")
        self.assertEqual(markers["h5"]["routes"]["mat-vec"]["family"], "mmv")

    def test_missing_h5_marker_fails_closed(self):
        log = i260_log("BASE").replace(ROUTE_LINE, "")
        with self.assertRaises(H.RouteError):
            P.parse_unit_markers(log.encode(), "BASE")

    def test_h5_candidate_parsed_with_baseline_h2_law(self):
        # H5_CANDIDATE differs from BASE only by the env factor; its H2/H3
        # parse mapping is the BASE law.
        markers = P.parse_unit_markers(i260_log("BASE").encode(),
                                       "H5_CANDIDATE")
        self.assertEqual(markers["h2h3"]["submission"], "normal")

    def test_a1_serialized_law_enforced(self):
        # A serialized submit without wait must fail the #260 A1 law.
        bad = i260_log("A1").replace(
            "ggml_vk_i260:v1|submit|graph=1|id=1|phase=submit|path=normal",
            "ggml_vk_i260:v1|submit|graph=1|id=1|phase=submit"
            "|path=serialized")
        with self.assertRaises(Exception):
            P.parse_unit_markers(bad.encode(), "A1")


class AuthorityTests(unittest.TestCase):
    def test_comparator_digest_is_required_and_exact(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "llama-server"
            binary.write_bytes(b"fake")
            with mock.patch.dict("os.environ", {}, clear=False):
                import os
                for key in ("ISSUE262_COMPARATOR_SHA256",):
                    if key in os.environ:
                        del os.environ[key]
                with self.assertRaises(P.PilotError):
                    P.verify_comparator262(binary)
                os.environ["ISSUE262_COMPARATOR_SHA256"] = (
                    "aaaa" * 16)
                with self.assertRaises(P.PilotError):
                    P.verify_comparator262(binary)
                os.environ["ISSUE262_COMPARATOR_SHA256"] = __import__(
                    "hashlib").sha256(b"fake").hexdigest()
                self.assertTrue(P.verify_comparator262(binary))

    def test_subject_verification_uses_frozen_uuid(self):
        import issue252_constants as C
        facts = C.HOST_FACTS
        good = subprocess_good = (
            f"NVIDIA GeForce RTX 3060, {facts['gpu_uuid']}, "
            f"{facts['bdf'].upper()}, {facts['driver']}\n")
        with mock.patch.object(P.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=0, stdout=good)
            subject = P.verify_subject()
        self.assertEqual(subject["binding"], "historical-A3/A5-subject-reused")
        bad = "NVIDIA GeForce RTX 4090, GPU-other, 00000000:01:00.0, 610.57.04\n"
        with mock.patch.object(P.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=0, stdout=bad)
            with self.assertRaises(P.PilotError):
                P.verify_subject()


class ScreeningLawTests(unittest.TestCase):
    def unit(self, digest):
        return {"row_digest": digest}

    def test_classification_law(self):
        self.assertEqual(P.screen_class(
            [self.unit("a"), self.unit("a")]),
            "matching-prefix (need one more for stable)")
        self.assertEqual(P.screen_class(
            [self.unit("a"), self.unit("b")]), "screening-variable")
        self.assertEqual(P.screen_class(
            [self.unit("a"), self.unit("a"), self.unit("a")]),
            "screening-stable")
        self.assertEqual(P.screen_class(
            [self.unit("a"), self.unit("a"), self.unit("b")]),
            "screening-variable")


class RetainedReportTests(unittest.TestCase):
    def test_reducer_requires_authenticated_retained_unit_directory(self):
        import issue262_report as R
        with self.assertRaises(R.ReportError):
            R.reduce_evidence(Path("/definitely/missing"))

    @unittest.skipUnless(Path("/home/zutfen/.hermes/cache/scratch/pr263-correction/remote-copy").is_dir(),
                         "authenticated retained evidence not staged in this session")
    def test_real_raw_logs_supply_h3_target_missing_from_old_summary(self):
        import issue262_report as R
        root = Path("/home/zutfen/.hermes/cache/scratch/pr263-correction/remote-copy")
        self.assertTrue(R._inventory(root))
        item = R._unit_dir(root / "d262-base/base-001", "BASE")
        target = item["markers"]["h2h3"]["target"]
        self.assertEqual((target["buffer"], target["type"], target["flags"]), (2, 1, 1))
        # Use parsed raw bytes for allocation identity; summary JSON is not input.
        self.assertEqual(item["markers"]["h2h3"]["target"]["offset"], 7004160)

    @unittest.skipUnless(Path("/home/zutfen/.hermes/cache/scratch/pr263-correction/remote-copy").is_dir(),
                         "authenticated retained evidence not staged in this session")
    def test_real_retained_root_reports_a4_as_required_intermediate(self):
        import issue262_report as R
        root = Path("/home/zutfen/.hermes/cache/scratch/pr263-correction/remote-copy")
        report = R.reduce_evidence(root)
        self.assertEqual(report["h3"]["a5_target_choice_contrast"], False)
        self.assertTrue(report["h3"]["a4_required"])
        self.assertFalse(report["h3"]["a4_executed"])
        self.assertEqual(report["h3"]["status"], "awaiting-required-A4")
        self.assertEqual(len(report["h3"]["a5_comparison_pairs"]), 2)
        self.assertTrue(all(len(pair["comparison_sha256"]) == 64
                            for pair in report["h3"]["a5_comparison_pairs"]))
        for arm in ("BASE", "A1", "A5"):
            self.assertEqual(report["arms"][arm]["classification"], "screening-variable")
        self.assertFalse(report["h5"]["candidate_eligible"])
        self.assertEqual(report["quarantined_units"], 3)

    def test_first_two_distinct_row_digests_are_screening_variable(self):
        import issue262_report as R
        units = [{"unit_index": 1, "row_digest": "a"}, {"unit_index": 2, "row_digest": "b"}]
        self.assertEqual(R.classify_units(units), "screening-variable")

    def test_h3_comparison_requires_target_type_and_flags(self):
        import issue262_report as R
        base = {"target": {"branch": "default", "buffer": 1}}
        a5 = {"target": {"branch": "disable_host_visible", "buffer": 2}}
        with self.assertRaises(R.ReportError):
            R.compare_memory_choices(base, a5)

    def test_a4_required_only_without_a5_contrast(self):
        import issue262_report as R
        self.assertTrue(R.a4_required(False))
        self.assertFalse(R.a4_required(True))

    def test_mm_vq_baseline_disallows_h5_candidate(self):
        import issue262_report as R
        self.assertFalse(R.h5_candidate_eligibility({"routes": {"mat-vec": {"family": "mmv"}}})[0])

    def test_final_reducer_rejects_wrong_screen_unit_count_and_order(self):
        import issue262_report as R
        for units in ([], [{"row_digest": "a"}],
                      [{"row_digest": "a"}, {"row_digest": "a"}, {"row_digest": "a"}, {"row_digest": "a"}],
                      [{"row_digest": "a"}, {"row_digest": "a"}, {"row_digest": "b"}],
                      [{"row_digest": "a"}, {"row_digest": "a"}, {"row_digest": "a"}][::-1]):
            with self.subTest(units=units), self.assertRaises(R.ReportError):
                R.validate_screen_units(units)

    def test_final_reducer_h5_uses_real_observation_predicate(self):
        import issue262_report as R
        self.assertFalse(R.h5_candidate_eligibility({"routes": {"mat-vec": {"family": "mmv"}}})[0])


class IdentityLawTests(unittest.TestCase):
    def test_260_parser_accepts_262_tree_and_rejects_others(self):
        import issue260_instrumentation as I
        self.assertIn(P.INSTRUMENTED262_TREE,
                      {I.INSTRUMENTED_TREE, I.INSTRUMENTED262_TREE})
        # The frozen #260 tree remains accepted (historical law intact).
        log = ("ggml_vk_i260:v1|graph|id=1|phase=begin\n"
               "ggml_vk_i260:v1|submit|graph=1|id=1|phase=submit"
               "|path=serialized\n"
               "ggml_vk_i260:v1|submit|graph=1|id=1|phase=wait"
               "|path=serialized|wait=success\n"
               "ggml_vk_i260:v1|graph|id=1|phase=end|compute_submits=1\n")
        self.assertEqual(
            I.parse_unit(log, arm="A1", source_tree=I.INSTRUMENTED_TREE)
            ["submission"], "serialized")
        with self.assertRaises(I.ObservationError):
            I.parse_unit(log, arm="A1", source_tree="0" * 40)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Focused CPU-only Issue #241 (R8-I3) campaign tests.

Covers the mandatory negative controls and positive contracts of the
dormant R8-I3 slice. No physical execution, no SSH, no accelerator
queries, no holdout decrypt (no decrypt path exists in this import
graph). Holdout content assertions use PUBLIC committed bytes only.
"""
from __future__ import annotations

import copy
import hashlib
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import issue241_campaign as campaign
import issue241_census as census
import issue241_comparator as cmp2
import issue241_constants as C
import issue241_dispatch as dispatch
import issue241_observer_patch as opatch
import issue241_placement as placement
import issue241_practicality as prac
import issue241_supersession as supersession
from issue241_phase0 import audit_phase0


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_census(**overrides) -> dict:
    doc = {
        "schema": census.CENSUS_SCHEMA,
        "host": "inferswarm01",
        "campaign": C.CAMPAIGN_ID,
        "cpu": [{"model": "Intel Xeon E5-2680 v4"}],
        "mem_total_kib": 128 * 1024 * 1024,
        "gpus": [
            {
                "bdf": C.REFERENCE_ARM["bdf"],
                "vendor_id": "10de", "device_id": "2504",
                "driver_in_use": "nvidia",
                "gpu_uuid": C.REFERENCE_ARM["gpu_uuid"],
                "vulkan_icd": C.REFERENCE_ARM["icd"],
                "vulkan_device_name": "NVIDIA GeForce RTX 3060",
                "link_width": "x16",
            },
            {
                "bdf": C.CANDIDATE_ARM["bdf"],
                "vendor_id": "1002", "device_id": "67df",
                "pci_id": "1002:67df",
                "driver_in_use": "amdgpu",
                "vram_mib": 8192,
                "vulkan_icd": C.CANDIDATE_ARM["icd"],
                "vulkan_device_name": "AMD Radeon RX 580 Series (RADV POLARIS10)",
                "link_width": "x16",
            },
        ],
        "model_backing": {
            member: {"bytes": 1, "sha256": digest}
            for member, digest in C.MODEL_MEMBER_SHA256.items()
        },
        "power_thermal": {"sensors_available": True},
    }
    doc.update(overrides)
    return doc


def make_rung(arm: str, ngl: int, **overrides) -> dict:
    authority = C.REFERENCE_ARM if arm == "B" else C.CANDIDATE_ARM
    doc = {
        "schema": placement.RUNG_SCHEMA,
        "campaign": C.CAMPAIGN_ID, "arm": arm,
        "host": authority["host"], "ngl": ngl,
        "loaded": True,
        "placement": {
            "alloc_failures": 0, "fallback_markers": 0,
            "offloaded_layers": [str(ngl), "49"],
            "buffer_records": (
                [{"device": "Vulkan0", "kind": "model",
                  "mib": C.model_buffer_mib(ngl)}]
                if arm == "C" else []),
        },
        "excluded_device_residency_mib": {
            bdf: 1 for bdf in C.EXCLUDED_BY_ARM[arm]
        },
    }
    doc.update(overrides)
    return doc


def make_run_receipt(arm: str, case_id: str = "case-256",
                     rows_digest: str | None = None) -> dict:
    authority = C.REFERENCE_ARM if arm == "B" else C.CANDIDATE_ARM
    winners = [11, 22, 33, 44, 55, 66, 77, 88]
    return {
        "schema": cmp2.RUN_SCHEMA,
        "campaign": C.CAMPAIGN_ID, "arm": arm,
        "host": "inferswarm01", "case_id": case_id,
        "selector": dict(authority["selector"]),
        "icd": authority["icd"],
        "cuda_visible_devices": "-1",
        "sampled_winners": list(winners),
        "forced_tokens": list(winners) if arm == "C" else [],
        "meta_rows": [{"pos": d, "forced_token": (winners[d] if arm == "C" else -1)}
                      for d in range(8)],
        "rows": {
            str(d): {"path": f"{arm}-{d}.f32", "bytes": C.ROW_BYTES,
                     "sha256": rows_digest or sha256_bytes(struct.pack(
                         f"<{C.N_VOCAB}f", *([0.5] * C.N_VOCAB)))}
            for d in range(8)
        },
    }


class TestConstants(unittest.TestCase):
    def test_model_member_hashes_frozen(self):
        self.assertEqual(len(C.MODEL_MEMBER_SHA256), 3)
        self.assertEqual(C.MODEL_TOTAL_BYTES, 72546461344)

    def test_fixture_ladder_hash_contract(self):
        data = (REPO / C.FIXTURE_LADDER_REL).read_bytes()
        self.assertEqual(sha256_bytes(data), C.FIXTURE_LADDER_SHA256)
        fixtures = C.load_fixtures(REPO)
        self.assertEqual(sorted(fixtures), sorted(C.FIXTURE_CASES))

    def test_ladder_derivation_pure_arithmetic(self):
        self.assertEqual(C.derive_ladder(), (1, 2, 4, 6, 8))
        self.assertLessEqual(
            C.model_buffer_mib(C.MAX_RUNG_NGL), C.CANDIDATE_MODEL_BUDGET_MIB)
        self.assertGreater(
            C.model_buffer_mib(C.MAX_RUNG_NGL + 1), C.CANDIDATE_MODEL_BUDGET_MIB)

    def test_budget_is_prospective_policy_not_measured_capacity(self):
        self.assertEqual(C.CANDIDATE_MODEL_BUDGET_MIB, 6656)
        self.assertEqual(
            C.CANDIDATE_VRAM_CENSUS_MIB - C.HBM_RESERVE_MIB,
            C.CANDIDATE_MODEL_BUDGET_MIB)

    def test_statistical_authority_immutable(self):
        self.assertEqual(sum(C.R8J_REALIZED_REGIME_COUNTS.values()), 1416)
        self.assertEqual(C.R8J_SELECTED_STRESS_COUNT, 8)

    def test_predictive_namespace_rejected(self):
        for bad in ("c237-01-01-001", "h237-02-05-001", "p237-03-01-001"):
            with self.assertRaises(RuntimeError):
                C.assert_historical_only(bad)
        for good in C.FIXTURE_CASES:
            C.assert_historical_only(good)

    def test_disposition_vocabulary_frozen(self):
        self.assertEqual(C.DISPOSITION_PRACTICAL,
                         "R8I3_RX580_COMPARATOR_V2_PRACTICAL")
        self.assertEqual(C.DISPOSITION_INFRA,
                         "R8I3_RX580_INFRASTRUCTURE_BLOCKED")
        self.assertEqual(C.DISPOSITION_RUNTIME,
                         "R8I3_RX580_RUNTIME_BLOCKED")
        self.assertEqual(C.DISPOSITION_V2_BLOCKED,
                         "R8I3_COMPARATOR_V2_BLOCKED")
        self.assertEqual(len(C.DISPOSITIONS), 4)

    def test_same_host_subject(self):
        self.assertEqual(C.REFERENCE_ARM["host"], C.CANDIDATE_ARM["host"])
        self.assertNotEqual(C.REFERENCE_ARM["bdf"], C.CANDIDATE_ARM["bdf"])
        # sequential exclusion sets are complementary single devices
        self.assertEqual(C.EXCLUDED_BY_ARM["B"], {C.CANDIDATE_ARM["bdf"]})
        self.assertEqual(C.EXCLUDED_BY_ARM["C"], {C.REFERENCE_ARM["bdf"]})

    def test_comparator_v2_identity_frozen(self):
        self.assertEqual(C.COMPARATOR_V2_ID,
                         "inferswarm.qwen38-vulkan-comparator/2")
        self.assertEqual(C.V2_OBSERVER["requests_per_case"], 1)
        self.assertEqual(C.V2_OBSERVER["decisions"], 8)

    def test_r8h_sentinels_are_diagnostic_only(self):
        # The remaining 3060 is a DIFFERENT physical card from R8-H's
        # reference; sentinels must be labeled diagnostic, never authority.
        self.assertIn("NOT byte-authority", C.R8H_SENTINELS_AUTHORITY)
        self.assertTrue(hasattr(C, "R8H_ARM_B_SENTINELS_DIAGNOSTIC"))


class TestPhase0Preservation(unittest.TestCase):
    def test_accepted_r8i_bytes_preserved_live(self):
        report = audit_phase0(REPO)
        self.assertTrue(report["clean"], report["problems"])
        self.assertEqual(report["r8i_files_preserved"],
                         report["r8i_files_total"])

    def test_holdout_ciphertext_unchanged(self):
        report = audit_phase0(REPO)
        self.assertEqual(report["holdout_ciphertext_sha256"],
                         "3786bfcdd284cb20fb33deb603276a958d7a3ebfdcc6454df9dee64488f0531a")

    def test_drift_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            sandbox = Path(tmp)
            # minimal fake repo with the accepted area + real git history
            import subprocess as sp
            def g(*args):
                sp.run(["git", "-C", str(sandbox), *args], check=True,
                       capture_output=True)
            g("init", "--quiet")
            g("config", "user.name", "t")
            g("config", "user.email", "t@example.invalid")
            area = sandbox / C.R8I_AREA_REL
            (area / "sealed").mkdir(parents=True)
            (area / "sealed" / "holdout.cms").write_bytes(b"cipher-bytes")
            g("add", "-A")
            g("commit", "--quiet", "-m", "accepted")
            accepted = sp.run(
                ["git", "-C", str(sandbox), "rev-parse", "HEAD"],
                capture_output=True, text=True).stdout.strip()
            # mutate one evidence byte after the accepted commit
            (area / "sealed" / "holdout.cms").write_bytes(b"cipher-bytes-X")
            with mock.patch.object(C, "ROOT", sandbox), \
                 mock.patch.object(C, "ACCEPTED_MAIN", accepted), \
                 mock.patch.object(
                     C, "accepted_r8i_file_digest",
                     return_value={C.R8I_HOLDOUT_REL:
                                   sha256_bytes(b"cipher-bytes")}):
                report = audit_phase0(sandbox)
            self.assertFalse(report["clean"])
            self.assertTrue(any("drift" in p for p in report["problems"]))


class TestCensus(unittest.TestCase):
    def test_valid_census_passes(self):
        verdict = census.validate_census(make_census())
        self.assertTrue(verdict["validated"])
        self.assertEqual(verdict["reference_bdf"], C.REFERENCE_ARM["bdf"])
        self.assertEqual(verdict["candidate_bdf"], C.CANDIDATE_ARM["bdf"])
        self.assertTrue(verdict["same_host"])

    def test_radeon_legacy_driver_rejected(self):
        doc = make_census()
        doc["gpus"][1]["driver_in_use"] = "radeon"
        with self.assertRaises(ValueError):
            census.validate_census(doc)

    def test_wrong_reference_uuid_rejected(self):
        doc = make_census()
        doc["gpus"][0]["gpu_uuid"] = "GPU-1fc28f83-1d45-926e-54d0-ba1e835ef099"
        with self.assertRaises(ValueError):
            census.validate_census(doc)

    def test_short_bdf_rejected(self):
        doc = make_census()
        doc["gpus"][1]["bdf"] = "02:00.0"
        with self.assertRaises(ValueError):
            census.validate_census(doc)

    def test_wrong_vram_rejected(self):
        doc = make_census()
        doc["gpus"][1]["vram_mib"] = 4096  # 4GB subsystem trap
        with self.assertRaises(ValueError):
            census.validate_census(doc)

    def test_model_member_drift_rejected(self):
        doc = make_census()
        member = C.MODEL_MEMBERS[0]
        doc["model_backing"][member]["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            census.validate_census(doc)

    def test_missing_second_gpu_rejected(self):
        doc = make_census()
        doc["gpus"] = doc["gpus"][:1]
        with self.assertRaises(ValueError):
            census.validate_census(doc)

    def test_low_ram_host_rejected(self):
        doc = make_census(mem_total_kib=8 * 1024 * 1024)
        with self.assertRaises(ValueError):
            census.validate_census(doc)

    def test_wrong_radv_device_rejected(self):
        doc = make_census()
        doc["gpus"][1]["vulkan_device_name"] = "llvmpipe (LLVM 19.1.7)"
        with self.assertRaises(ValueError):
            census.validate_census(doc)


class TestPlacement(unittest.TestCase):
    def test_matched_rung_selection(self):
        rungs = {
            "B": [make_rung("B", n) for n in C.LADDER_NGLS],
            "C": [make_rung("C", n) for n in C.LADDER_NGLS],
        }
        verdict = placement.select_matched_rung(rungs)
        self.assertEqual(verdict["matched_ngl"], 8)
        self.assertFalse(verdict["placement_blocked"])

    def test_reference_must_match_candidate_placement(self):
        rungs = {
            "B": [make_rung("B", n) for n in C.LADDER_NGLS],
            "C": [make_rung("C", 1)] +
                 [make_rung("C", n, loaded=False) for n in (2, 4, 6, 8)],
        }
        verdict = placement.select_matched_rung(rungs)
        self.assertEqual(verdict["matched_ngl"], 1)

    def test_no_valid_rung_blocks(self):
        rungs = {
            "B": [make_rung("B", 1, loaded=False)],
            "C": [make_rung("C", 1, loaded=False)],
        }
        verdict = placement.select_matched_rung(rungs)
        self.assertTrue(verdict["placement_blocked"])
        self.assertIsNone(verdict["matched_ngl"])

    def test_excluded_device_residency_rejected(self):
        rung = make_rung("C", 1, excluded_device_residency_mib={
            C.REFERENCE_ARM["bdf"]: 512})
        verdict = placement.judge_rung(rung)
        self.assertFalse(verdict["valid"])
        self.assertTrue(any("excluded device" in p for p in verdict["problems"]))

    def test_vulkan_host_lines_not_silent_fallback(self):
        log = ("cannot be used with preferred buffer type Vulkan_Host, "
               "using CPU instead\n" * 10)
        parsed = placement.parse_placement(log)
        self.assertEqual(parsed["fallback_markers"], 0)

    def test_device_side_demotion_is_silent_fallback(self):
        log = "layer 3: cannot use preferred buffer type Vulkan0, using CPU"
        parsed = placement.parse_placement(log)
        self.assertGreaterEqual(parsed["fallback_markers"], 1)
        verdict = placement.judge_rung(make_rung(
            "C", 1, placement={
                "alloc_failures": 0, "fallback_markers": 1,
                "offloaded_layers": ["1", "49"], "buffer_records": []}))
        self.assertFalse(verdict["valid"])

    def test_candidate_budget_violation_rejected(self):
        rung = make_rung("C", 1, placement={
            "alloc_failures": 0, "fallback_markers": 0,
            "offloaded_layers": ["1", "49"],
            "buffer_records": [{"device": "Vulkan0", "kind": "model",
                                "mib": C.CANDIDATE_MODEL_BUDGET_MIB + 100}]})
        verdict = placement.judge_rung(rung)
        self.assertFalse(verdict["valid"])
        self.assertTrue(any("budget" in p for p in verdict["problems"]))

    def test_numerical_agreement_cannot_enter_selection(self):
        # the judge/rung schema has NO candidate-output field; injecting
        # one must not change the verdict shape
        rung = make_rung("C", 1)
        rung["candidate_output_agreement"] = "100%"
        verdict = placement.judge_rung(rung)
        self.assertTrue(verdict["valid"])
        self.assertNotIn("candidate_output_agreement", verdict)

    def test_offloaded_mismatch_rejected(self):
        rung = make_rung("C", 4, placement={
            "alloc_failures": 0, "fallback_markers": 0,
            "offloaded_layers": ["2", "49"], "buffer_records": []})
        verdict = placement.judge_rung(rung)
        self.assertFalse(verdict["valid"])
        self.assertTrue(any("placement mismatch" in p for p in verdict["problems"]))


class TestComparatorV2(unittest.TestCase):
    def _reader(self, receipts_dir: Path, receipt: dict):
        def read(path: str) -> bytes:
            data = (receipts_dir / path).read_bytes()
            self.assertEqual(len(data), C.ROW_BYTES)
            return data
        return read

    def _stage_rows(self, tmp: Path, receipt: dict, value: float = 0.5) -> None:
        for d, entry in receipt["rows"].items():
            raw = struct.pack(f"<{C.N_VOCAB}f", *([value] * C.N_VOCAB))
            (tmp / entry["path"]).write_bytes(raw)

    def test_valid_pair_passes(self):
        ref = make_run_receipt("B")
        cand = make_run_receipt("C")
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            self._stage_rows(t, ref, 0.25)
            self._stage_rows(t, cand, 0.5)
            out = cmp2.validate_pair(ref, cand, self._reader(t, ref))
            self.assertTrue(out["validated"], out["problems"])
            self.assertEqual(len(out["reference"]["problems"]), 0)
            self.assertEqual(len(out["candidate"]["problems"]), 0)

    def test_missing_decision_fails(self):
        ref = make_run_receipt("B")
        cand = make_run_receipt("C")
        del cand["rows"]["7"]
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            self._stage_rows(t, ref)
            self._stage_rows(t, cand)
            out = cmp2.validate_pair(ref, cand, self._reader(t, ref))
            self.assertFalse(out["validated"])
            self.assertTrue(any("row decisions" in p or "!= 8" in p
                                for p in out["problems"]))

    def test_candidate_prefix_must_be_reference_winners(self):
        ref = make_run_receipt("B")
        cand = make_run_receipt("C")
        cand["forced_tokens"][3] = 999  # candidate token enters prefix
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            self._stage_rows(t, ref)
            self._stage_rows(t, cand)
            out = cmp2.validate_pair(ref, cand, self._reader(t, ref))
            self.assertFalse(out["validated"])
            self.assertTrue(any("forced prefix" in p for p in out["problems"]))

    def test_reference_arm_must_not_force(self):
        ref = make_run_receipt("B")
        ref["forced_tokens"] = [11, 22, 33, 44, 55, 66, 77, 88]
        cand = make_run_receipt("C")
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            self._stage_rows(t, ref)
            self._stage_rows(t, cand)
            out = cmp2.validate_pair(ref, cand, self._reader(t, ref))
            self.assertFalse(out["validated"])
            self.assertTrue(any("must not force" in p for p in out["problems"]))

    def test_cuda_participation_fails(self):
        ref = make_run_receipt("B")
        ref["cuda_visible_devices"] = "0"
        cand = make_run_receipt("C")
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            self._stage_rows(t, ref)
            self._stage_rows(t, cand)
            out = cmp2.validate_pair(ref, cand, self._reader(t, ref))
            self.assertFalse(out["validated"])
            self.assertTrue(any("CUDA" in p for p in out["problems"]))

    def test_predictive_case_fails(self):
        ref = make_run_receipt("B", case_id="c237-01-01-001")
        cand = make_run_receipt("C", case_id="c237-01-01-001")
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            self._stage_rows(t, ref)
            self._stage_rows(t, cand)
            with self.assertRaises(RuntimeError):
                cmp2.validate_pair(ref, cand, self._reader(t, ref))

    def test_nonfinite_row_fails(self):
        ref = make_run_receipt("B")
        cand = make_run_receipt("C")
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            self._stage_rows(t, ref)
            self._stage_rows(t, cand)
            raw = bytearray(struct.pack(f"<{C.N_VOCAB}f", *([0.5] * C.N_VOCAB)))
            struct.pack_into("<f", raw, 400, float("nan"))
            (t / ref["rows"]["3"]["path"]).write_bytes(bytes(raw))
            out = cmp2.validate_pair(ref, cand, self._reader(t, ref))
            self.assertFalse(out["validated"])
            self.assertTrue(any("non-finite" in p for p in out["problems"]))

    def test_wrong_host_fails(self):
        ref = make_run_receipt("B")
        ref["host"] = "inferswarm02"
        cand = make_run_receipt("C")
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            self._stage_rows(t, ref)
            self._stage_rows(t, cand)
            out = cmp2.validate_pair(ref, cand, self._reader(t, ref))
            self.assertFalse(out["validated"])
            self.assertTrue(any("same host" in p for p in out["problems"]))

    def test_determinism(self):
        a = make_run_receipt("C")
        b = make_run_receipt("C")
        self.assertTrue(cmp2.validate_determinism(a, b)["deterministic"])
        b["rows"]["5"]["sha256"] = "0" * 64
        verdict = cmp2.validate_determinism(a, b)
        self.assertFalse(verdict["deterministic"])

    def test_inertness(self):
        tokens = [1, 2, 3, 4, 5, 6, 7, 8]
        self.assertTrue(cmp2.validate_inertness(tokens, list(tokens))["inert"])
        self.assertFalse(
            cmp2.validate_inertness(tokens, tokens[:-1] + [9])["inert"])

    def test_row_bytes_constant(self):
        self.assertEqual(C.ROW_BYTES, 248320 * 4)


class TestObserverPatch(unittest.TestCase):
    def _r8e_source(self) -> str:
        # Minimal synthetic source carrying the exact accepted anchors.
        return (
            "#include <fstream>\n"
            "// fix problem with std::min and std::max\n"
            "                id = common_sampler_sample(slot.smpl.get(), slot.ctx_tgt, tok_idx);\n"
            "                // R8-E observation-only (Issue #199): reads the same\n"
            "                // logits row the sampler consumed; no state writes.\n"
            "                r8e_observe_logits(slot.ctx_tgt, tok_idx,\n"
            "                                   (int) slot.stats.n_gen, id);\n"
            "            }\n"
        )

    def test_r8e_patch_constant(self):
        p = REPO / opatch.R8E_ACCEPTED_PATCH_REL
        self.assertTrue(p.is_file())
        opatch.verify_r8e_patch(p)  # accepted bytes unchanged

    def test_apply_adds_hook(self):
        out = opatch.apply(self._r8e_source())
        self.assertIn("r8i3_capture_and_force", out)
        self.assertIn("#include <filesystem>", out)

    def test_double_apply_rejected(self):
        once = opatch.apply(self._r8e_source())
        with self.assertRaises(RuntimeError):
            opatch.apply(once)

    def test_capture_must_precede_force(self):
        hook = opatch.HOOK_FUNCTION.replace(
            "f.write((const char *) logits", "f_write_removed(")
        with self.assertRaises(RuntimeError):
            opatch.validate_capture_force_order(hook, opatch.WIRE_NEW)

    def test_wire_order_sample_observe_force(self):
        wire = opatch.WIRE_NEW.replace("r8e_observe_logits", "zre_observe")
        with self.assertRaises(RuntimeError):
            opatch.validate_capture_force_order(opatch.HOOK_FUNCTION, wire)

    def test_patched_sha_deterministic(self):
        src = self._r8e_source()
        self.assertEqual(opatch.patched_source_sha256(src),
                         opatch.patched_source_sha256(src))

    def test_anchor_drift_fails_closed(self):
        with self.assertRaises(RuntimeError):
            opatch.apply(self._r8e_source().replace("#include <fstream>", ""))


class TestPracticality(unittest.TestCase):
    def test_projection_from_measured_walls(self):
        walls = {"case-256": 10.0, "case-1024": 20.0,
                 "case-3072": 40.0, "case-4096": 60.0}
        out = prac.project_arm(walls)
        expected = (338 * 10.0 + 366 * 20.0 + 363 * 40.0 + 349 * 60.0)
        self.assertAlmostEqual(out["central_s"], round(expected, 1))
        self.assertLess(out["low_s"], out["central_s"])
        self.assertGreater(out["high_s"], out["central_s"])

    def test_missing_measured_wall_rejected(self):
        walls = {"case-256": 10.0}
        with self.assertRaises(ValueError):
            prac.project_arm(walls)

    def test_zero_wall_rejected(self):
        walls = {"case-256": 0.0, "case-1024": 1.0,
                 "case-3072": 1.0, "case-4096": 1.0}
        with self.assertRaises(ValueError):
            prac.project_arm(walls)

    def test_disposition_practical_within_bound(self):
        proj = {"central_s": 3600.0}
        out = prac.derive_disposition(
            census_valid=True,
            placement={"placement_blocked": False, "matched_ngl": 8},
            comparator_v2={"validated": True},
            candidate_projection=proj)
        self.assertEqual(out["disposition"], C.DISPOSITION_PRACTICAL)

    def test_disposition_infra_over_bound(self):
        proj = {"central_s": C.PRACTICAL_CANDIDATE_PHASE_A_BOUND_S + 1}
        out = prac.derive_disposition(
            census_valid=True,
            placement={"placement_blocked": False, "matched_ngl": 8},
            comparator_v2={"validated": True},
            candidate_projection=proj)
        self.assertEqual(out["disposition"], C.DISPOSITION_INFRA)
        self.assertIn("~24 h", out["reason"])

    def test_disposition_infra_on_census_invalid(self):
        out = prac.derive_disposition(
            census_valid=False, census_problems=["uuid drift"],
            placement=None, comparator_v2=None, candidate_projection=None)
        self.assertEqual(out["disposition"], C.DISPOSITION_INFRA)

    def test_disposition_infra_on_stability_blocker(self):
        out = prac.derive_disposition(
            census_valid=True,
            infrastructure_blockers=["host power-loss crash history"],
            placement=None, comparator_v2=None, candidate_projection=None)
        self.assertEqual(out["disposition"], C.DISPOSITION_INFRA)

    def test_disposition_runtime_on_placement_blocked(self):
        out = prac.derive_disposition(
            census_valid=True,
            placement={"placement_blocked": True},
            comparator_v2=None, candidate_projection=None)
        self.assertEqual(out["disposition"], C.DISPOSITION_RUNTIME)

    def test_disposition_v2_blocked_on_observer(self):
        out = prac.derive_disposition(
            census_valid=True,
            placement={"placement_blocked": False, "matched_ngl": 1},
            comparator_v2={"validated": False},
            candidate_projection=None)
        self.assertEqual(out["disposition"], C.DISPOSITION_V2_BLOCKED)

    def test_stress_bound_uses_worst_regime(self):
        walls = {"case-256": 10.0, "case-1024": 20.0,
                 "case-3072": 40.0, "case-4096": 60.0}
        out = prac.project_stress(walls)
        self.assertEqual(out["bound_case"], "case-4096")
        self.assertAlmostEqual(out["projected_s"], 8 * 60.0)


class TestSupersession(unittest.TestCase):
    def test_requires_terminal_from_vocabulary(self):
        with self.assertRaises(ValueError):
            supersession.build_supersession(phase4_terminal="WHATEVER")

    def test_dormant_until_practical_terminal(self):
        out = supersession.build_supersession(
            phase4_terminal=C.DISPOSITION_RUNTIME)
        self.assertIn("PROSPECTIVE", out["status"])
        self.assertFalse(out.get("supersession_blocked", False))

    def test_holdout_reuse_binding_check_live(self):
        check = supersession.check_holdout_reuse(REPO)
        # committed seal carries no superseded identity markers
        self.assertEqual(check["binding_markers_present"], [])
        self.assertTrue(check["reuse_valid"])
        # advisory scan still surfaces v1-area markers for adjudication
        advisory = check["advisory_v1_area_markers"]
        self.assertTrue(any(v for v in advisory.values()))

    def test_blocked_when_commitment_binds_superseded_identity(self):
        fake = {
            "docs/qualification/qwen38-vulkan-v1/manifests/"
            "sealed-holdout-commitment.json":
                json.dumps({"contract_id": "x-inferswarm02-comparator/1"}),
        }
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            for rel, content in fake.items():
                p = t / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content)
            for rel in supersession.ADVISORY_APPLICABILITY_RELS:
                p = t / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("{}")
            check = supersession.check_holdout_reuse(t)
            self.assertFalse(check["reuse_valid"])
            self.assertIn("inferswarm02", check["binding_markers_present"])
            out = supersession.build_supersession(
                phase4_terminal=C.DISPOSITION_PRACTICAL)
            # (builder uses live root; the fake sandbox only proves the check)

    def test_superseded_and_preserved_named_mechanically(self):
        out = supersession.build_supersession(
            phase4_terminal=C.DISPOSITION_PRACTICAL)
        joined = "\n".join(out["superseded"])
        for marker in ("V340L", "ngl=1", "comparator/1"):
            self.assertIn(marker, joined)
        preserved = "\n".join(out["preserved"])
        for marker in ("M=3, H=24, alpha=0.05, N=1416",
                       "exact model bytes", "sealed holdout bytes"):
            self.assertIn(marker, preserved)


class TestDispatchAuthority(unittest.TestCase):
    HEAD = "b" * 40

    def _pr(self, **over):
        doc = {
            "state": "open", "merged_at": None, "number": 300,
            "base": {"ref": "main"}, "head": {"sha": self.HEAD},
        }
        doc.update(over)
        return doc

    def _review(self, **over):
        doc = {
            "id": 55, "state": "APPROVED",
            "author_association": "OWNER", "commit_id": self.HEAD,
            "user": {"login": "maintainer"},
            "submitted_at": "2026-09-23T12:00:00Z",
            "body": f"R8I3 PHYSICAL DISPATCH #241\nhead={self.HEAD}",
        }
        doc.update(over)
        return doc

    def test_valid_dispatch(self):
        authority = dispatch.validate_dispatch_authority(
            self._pr(), {"number": 241, "state": "open"},
            [self._review()], self.HEAD)
        self.assertEqual(authority["head_sha"], self.HEAD)
        self.assertEqual(authority["dispatch_phrase"],
                         "R8I3 PHYSICAL DISPATCH #241")

    def test_wrong_head_rejected(self):
        with self.assertRaises(ValueError):
            dispatch.validate_dispatch_authority(
                self._pr(), {"number": 241, "state": "open"},
                [self._review()], "c" * 40)

    def test_missing_phrase_rejected(self):
        review = self._review(body="head=" + self.HEAD)
        with self.assertRaises(ValueError):
            dispatch.validate_dispatch_authority(
                self._pr(), {"number": 241, "state": "open"},
                [review], self.HEAD)

    def test_non_owner_rejected(self):
        with self.assertRaises(ValueError):
            dispatch.validate_dispatch_authority(
                self._pr(), {"number": 241, "state": "open"},
                [self._review(author_association="CONTRIBUTOR")], self.HEAD)

    def test_merged_pr_rejected(self):
        with self.assertRaises(ValueError):
            dispatch.validate_dispatch_authority(
                self._pr(merged_at="2026-09-23T00:00:00Z"),
                {"number": 241, "state": "open"},
                [self._review()], self.HEAD)

    def test_closed_issue_rejected(self):
        with self.assertRaises(ValueError):
            dispatch.validate_dispatch_authority(
                self._pr(), {"number": 241, "state": "closed"},
                [self._review()], self.HEAD)

    def test_stale_review_commit_rejected(self):
        with self.assertRaises(ValueError):
            dispatch.validate_dispatch_authority(
                self._pr(), {"number": 241, "state": "open"},
                [self._review(commit_id="d" * 40)], self.HEAD)


class TestCampaignDormancy(unittest.TestCase):
    def test_all_physical_phases_dormant(self):
        status = campaign.campaign_status(REPO)
        self.assertFalse(status["physical_execution_performed"])
        self.assertFalse(status["holdout_access_performed"])
        self.assertFalse(status["predictive_execution_performed"])
        for phase in status["phases"]:
            if phase["phase"] in campaign.PHYSICAL_PHASES:
                self.assertIn("DORMANT", phase["state"])

    def test_phase0_clean_in_status(self):
        status = campaign.campaign_status(REPO)
        self.assertTrue(status["phase0"]["clean"])

    def test_no_decrypt_path_in_module_graph(self):
        for mod in (campaign, cmp2, placement, prac, supersession,
                    opatch, census):
            src = Path(sys.modules[mod.__name__].__file__).read_text()
            lowered = src.lower()
            self.assertNotIn("openssl", lowered, mod.__name__)
            # a decrypt CALL path; prose mentions of "no decrypt path"
            # in module docstrings are the contract statement itself.
            import re as _re
            calls = _re.findall(
                r"(?<!no )(?:openssl|cms|decrypt)\s*(?:dgst|dec|\(|smime)",
                lowered)
            self.assertEqual(calls, [], f"{mod.__name__}: {calls}")

    def test_producers_exist_for_every_phase(self):
        for name in ("issue241_phase0", "issue241_census",
                     "issue241_placement", "issue241_comparator",
                     "issue241_practicality", "issue241_supersession",
                     "issue241_dispatch", "issue241_observer_patch"):
            self.assertTrue((REPO / "scripts" / f"{name}.py").is_file())


if __name__ == "__main__":
    unittest.main()

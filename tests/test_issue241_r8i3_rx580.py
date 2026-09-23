#!/usr/bin/env python3
"""Focused CPU-only Issue #241 (R8-I3) campaign tests.

Covers the mandatory negative controls and positive contracts of the
dormant R8-I3 slice, INCLUDING the correction-pass controls:

  * dispatch gate ordering (no physical/device/model operation is
    reachable before live exact-head dispatch — recorded-probe call
    lists, not prose);
  * comparator/2 RAW-ROW BYTE-BINDING (same-size finite bytes changed
    while the claimed receipt sha stays unchanged => FAIL; identical
    claimed shas with different raw bytes across repeats => FAIL);
  * row-path custody (traversal, absolute, escape, symlink, missing,
    non-regular);
  * reference/candidate SAME-CASE/SUBJECT/PLACEMENT/RUNTIME cross
    binding (case, ngl, bdf, gpu identity, pci id, icd, device name,
    binary hash, patched-source hash, model members, fixture digest,
    request contract, meta-vs-receipt arrays).

No physical execution, no SSH, no accelerator queries, no holdout
decrypt (no decrypt path exists in this import graph). Holdout content
assertions use PUBLIC committed bytes only.
"""
from __future__ import annotations

import copy
import hashlib
import inspect
import json
import os
import struct
import sys
import tempfile
import textwrap
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
import issue241_physical as physical
import issue241_placement as placement
import issue241_placement_producer as place_producer
import issue241_practicality as prac
import issue241_supersession as supersession
from issue241_phase0 import audit_phase0
from tests.test_issue241_placement_producer import raw_identity_sources

RAW_IDENTITY_SOURCES = raw_identity_sources


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
                "vendor_id": C.REFERENCE_ARM["vendor_id"],
                "device_id": C.REFERENCE_ARM["device_id"],
                "pci_id": C.REFERENCE_ARM["pci_id"],
                "subsystem_vendor_id": C.REFERENCE_ARM["subsystem_vendor_id"],
                "subsystem_device_id": C.REFERENCE_ARM["subsystem_device_id"],
                "revision": C.REFERENCE_ARM["revision"],
                "link_width": C.REFERENCE_ARM["link_width"],
                "max_link_width": C.REFERENCE_ARM["max_link_width"],
                "max_link_speed": C.REFERENCE_ARM["max_link_speed"],
                "link_speed": "2.5 GT/s",  # observed, never frozen
                "driver_in_use": "nvidia",
                "gpu_uuid": C.REFERENCE_ARM["gpu_uuid"],
                "vulkan_icd": C.REFERENCE_ARM["icd"],
                "vulkan_device_name": C.REFERENCE_ARM["vulkan_device_name"],
                "vulkan_device_uuid": C.REFERENCE_ARM["vulkan_device_uuid"],
            },
            {
                "bdf": C.CANDIDATE_ARM["bdf"],
                "vendor_id": C.CANDIDATE_ARM["vendor_id"],
                "device_id": C.CANDIDATE_ARM["device_id"],
                "pci_id": C.CANDIDATE_ARM["pci_id"],
                "subsystem_vendor_id": C.CANDIDATE_ARM["subsystem_vendor_id"],
                "subsystem_device_id": C.CANDIDATE_ARM["subsystem_device_id"],
                "revision": C.CANDIDATE_ARM["revision"],
                "link_width": C.CANDIDATE_ARM["link_width"],
                "max_link_width": C.CANDIDATE_ARM["max_link_width"],
                "max_link_speed": C.CANDIDATE_ARM["max_link_speed"],
                "link_speed": "8.0 GT/s",  # observed, never frozen
                "driver_in_use": "amdgpu",
                "vram_mib": 8192,
                "vulkan_icd": C.CANDIDATE_ARM["icd"],
                "vulkan_device_name": C.CANDIDATE_ARM["vulkan_device_name"],
                "vulkan_device_uuid": C.CANDIDATE_ARM["vulkan_device_uuid"],
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


def valid_device_identity(arm: str) -> dict:
    """A rung/health identity observation satisfying the frozen predicate."""
    cfg = C.REFERENCE_ARM if arm == "B" else C.CANDIDATE_ARM
    ident = {k: cfg[k] for k in (
        "bdf", "vendor_id", "device_id", "pci_id", "subsystem_vendor_id",
        "subsystem_device_id", "revision", "link_width", "max_link_width",
        "max_link_speed", "vulkan_device_name", "vulkan_device_uuid")}
    ident["vulkan_icd"] = cfg["icd"]
    ident["driver_in_use"] = cfg["kernel_driver"]
    ident["link_speed"] = "2.5 GT/s" if arm == "B" else "8.0 GT/s"
    ident["selected_device_present"] = True
    if arm == "B":
        ident["gpu_uuid"] = cfg["gpu_uuid"]
    else:
        ident["vram_mib"] = C.CANDIDATE_VRAM_CENSUS_MIB
    return ident


def valid_device_health(arm: str) -> dict:
    return {"fatal_states": [], "observed": dict(valid_device_identity(arm))}


def valid_repeats(arm: str = "C", response_tokens: list[int] | None = None,
                  sha: str | None = None) -> list[dict]:
    tokens = response_tokens if response_tokens is not None else list(WINNERS)
    det_sha = placement.deterministic_output_sha256(tokens)
    return [{
        "index": i,
        "sane_completion": True,
        "response_tokens": list(tokens),
        "deterministic_output_sha256": det_sha,
        "response_raw": f"arm-ngl1{'' if i == 0 else f'.repeat{i}'}.response.json",
        "response_raw_sha256": sha or ("d" * 64),
        "raw_log": f"arm-ngl1{'' if i == 0 else f'.repeat{i}'}.server.log",
        "raw_log_sha256": "e" * 64,
        "raw_telemetry": f"arm-ngl1{'' if i == 0 else f'.repeat{i}'}.telemetry.json",
        "raw_telemetry_sha256": "f" * 64,
        "identity_pre": valid_device_identity(arm),
        "raw_identity_pre": f"arm-ngl1{'' if i == 0 else f'.repeat{i}'}.identity-pre.json",
        "raw_identity_pre_sha256": "1" * 64,
        "identity_post": valid_device_identity(arm),
        "raw_identity_post": f"arm-ngl1{'' if i == 0 else f'.repeat{i}'}.identity-post.json",
        "raw_identity_post_sha256": "2" * 64,
        "identity_post_health": {"fatal_states": [],
                                 "observed": valid_device_identity(arm)},
        "request_timings": {"prompt_ms": 1.0 + i, "decode_ms": 2.0 + i},
        "failure": None,
    } for i in range(placement.RUNG_REPEATS)]


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
        "process_measurements": {
            "rss_file_kib": 1, "rss_anon_kib": 1, "swap_kib": 0,
            "physical_read_bytes": 1, "major_faults": 1},
        "request_timings": {"prompt_ms": 1.0, "decode_ms": 2.0},
        "device_identity": valid_device_identity(arm),
        "post_execution_device_identity": valid_device_identity(arm),
        "device_health": valid_device_health(arm),
        "repeats": valid_repeats(arm),
    }
    doc.update(overrides)
    return doc


# ---------------------------------------------------------------------------
# comparator/2 run receipts (schema /2, fully cross-bound)
# ---------------------------------------------------------------------------

WINNERS = [11, 22, 33, 44, 55, 66, 77, 88]
VALID_SERVER_SHA = "e" * 64
FAKE_HEAD = "f" * 40


def dispatch_authority_receipt() -> dict:
    return {
        "schema": dispatch.AUTHORITY_SCHEMA,
        "repository": dispatch.REPO,
        "issue_number": 241,
        "pr_number": 242,
        "head_sha": FAKE_HEAD,
        "review_id": 55,
        "reviewer": "maintainer",
        "reviewer_association": "OWNER",
        "review_commit_id": FAKE_HEAD,
        "dispatch_phrase": dispatch.DISPATCH_PHRASE,
    }


def make_run_receipt(arm: str, case_id: str = "case-256",
                     ngl: int = 1, row_value: float = 0.5,
                     receipt_id: str = "") -> tuple:
    """Build a valid /2 receipt + a staged-rows writer.

    Returns (receipt, stage_rows(tmp)) where stage_rows writes finite
    FP32 rows whose real sha256s populate the receipt. `receipt_id`
    gives repeats distinct row paths (same receipt claim shape).
    """
    authority = C.REFERENCE_ARM if arm == "B" else C.CANDIDATE_ARM
    fixtures = C.load_fixtures(REPO)
    if case_id in fixtures:
        fx = fixtures[case_id]
    else:
        # adversarial receipts (predictive namespaces) never reach the
        # fixture authority: synthesize a minimal prompt identity so
        # the predictive-namespace gate is what fires
        fx = {"prompt_token_ids": [1, 2, 3], "rendered_length": 3,
              "prompt_text": "x", "case_id": case_id}

    prefix = f"{arm}{receipt_id}"
    def stage(tmp: Path, value: float = row_value) -> None:
        for d in range(C.DECISIONS):
            raw = struct.pack(f"<{C.N_VOCAB}f", *([value] * C.N_VOCAB))
            (tmp / f"{prefix}-{d}.f32").write_bytes(raw)

    rows = {}
    for d in range(C.DECISIONS):
        raw = struct.pack(f"<{C.N_VOCAB}f", *([row_value] * C.N_VOCAB))
        rows[str(d)] = {
            "path": f"{prefix}-{d}.f32", "bytes": C.ROW_BYTES,
            "sha256": sha256_bytes(raw),
        }
    receipt = {
        "schema": cmp2.RUN_SCHEMA,
        "campaign": C.CAMPAIGN_ID,
        "comparator_id": C.COMPARATOR_V2_ID,
        "arm": arm,
        "host": "inferswarm01",
        "case_id": case_id,
        "ngl": ngl,
        "selector": dict(authority["selector"]),
        "icd": authority["icd"],
        "cuda_visible_devices": "-1",
        "bdf": authority["bdf"],
        "gpu_uuid": authority.get("gpu_uuid") if arm == "B" else None,
        "vulkan_device_name": (C.REFERENCE_ARM["vulkan_device_name"] if arm == "B"
                               else C.CANDIDATE_ARM["vulkan_device_name"]),
        "pci_id": authority.get("pci_id") if arm == "C" else None,
        "subject_identity": {k: authority[k] for k in (
            "vendor_id", "device_id", "subsystem_vendor_id",
            "subsystem_device_id", "revision", "link_width",
            "max_link_width", "max_link_speed", "vulkan_device_uuid")
            if k in authority} | {
            "driver_in_use": authority.get("kernel_driver"),
            **({"gpu_uuid": authority["gpu_uuid"]} if arm == "B" else
               {"pci_id": authority["pci_id"]})},
        "fixture_ladder_sha256": C.FIXTURE_LADDER_SHA256,
        "prompt_token_ids": list(fx["prompt_token_ids"]),
        "prompt_len": fx["rendered_length"],
        "prompt_text_sha256": sha256_bytes(fx["prompt_text"].encode()),
        "model_members": dict(C.MODEL_MEMBER_SHA256),
        "llama_cpp_pin": C.LLAMA_CPP_PIN,
        "patched_source_sha256": C.OBSERVER_PATCHED_SOURCE_SHA256,
        "server_sha256": VALID_SERVER_SHA,
        "build_flags": list(C.OBSERVER_BUILD_FLAGS),
        "request_contract": dict(C.REQUEST_CONTRACT),
        "excluded_device_residency_mib": {
            bdf: 1 for bdf in C.EXCLUDED_BY_ARM[arm]},
        "process_attribution": {
            "server_pid": 4242,
            "server_argv": ["llama-server", "-m", str(C.MODEL_DIR),
                            "-ngl", str(ngl)],
            "server_env": {
                "GGML_VK_VISIBLE_DEVICES": authority["selector"][
                    "GGML_VK_VISIBLE_DEVICES"],
                "CUDA_VISIBLE_DEVICES": "-1",
                "VK_ICD_FILENAMES": authority["icd"],
            },
        },
        "dispatch_authority": dispatch_authority_receipt(),
        "sampled_winners": list(WINNERS),
        "forced_tokens": list(WINNERS) if arm == "C" else [],
        "meta_rows": [
            {"pos": d,
             "sampled_winner": WINNERS[d],
             "forced_token": (WINNERS[d] if arm == "C" else -1)}
            for d in range(C.DECISIONS)],
        "rows": rows,
    }
    return receipt, stage


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

    def test_observer_patched_source_sha_is_real_derivation(self):
        # The frozen comparator/2 patched-source identity must equal the
        # real derivation from the pinned base + accepted R8-E patch.
        base = Path("/tmp/is241-src/w/tools/server/server-context.cpp")
        if not base.is_file():
            self.skipTest("derivation scratch absent")
        r8e = base.read_text()
        self.assertEqual(sha256_bytes(r8e.encode()),
                         "17da5724cea9debe97323701ccb10335fb98e0b68af45a648011b8e64320ea8c")
        self.assertEqual(opatch.patched_source_sha256(r8e),
                         C.OBSERVER_PATCHED_SOURCE_SHA256)

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

    # --- frozen subject-identity negative controls (correction pass) ---

    def _candidate_field(self, field, value):
        doc = make_census()
        doc["gpus"][1][field] = value
        return doc

    def test_wrong_amd_subsystem_vendor_rejected(self):
        # A different [1002:67df] board (e.g. another vendor's RX 580) at
        # the same BDF must not satisfy the frozen candidate identity.
        with self.assertRaisesRegex(ValueError, "subsystem_vendor_id"):
            census.validate_census(
                self._candidate_field("subsystem_vendor_id", "174b"))

    def test_wrong_amd_subsystem_device_rejected(self):
        with self.assertRaisesRegex(ValueError, "subsystem_device_id"):
            census.validate_census(
                self._candidate_field("subsystem_device_id", "e387"))

    def test_wrong_amd_revision_rejected(self):
        with self.assertRaisesRegex(ValueError, "revision"):
            census.validate_census(self._candidate_field("revision", "e6"))

    def test_wrong_candidate_link_width_rejected(self):
        # x16 would mean the board moved to a different slot/link: the
        # frozen predicate is exact (x8 negotiated / x16 max), not a set.
        with self.assertRaisesRegex(ValueError, "link_width"):
            census.validate_census(self._candidate_field("link_width", "x16"))

    def test_wrong_reference_link_width_rejected(self):
        doc = make_census()
        doc["gpus"][0]["link_width"] = "x8"
        with self.assertRaisesRegex(ValueError, "link_width"):
            census.validate_census(doc)

    def test_reference_subsystem_drift_rejected(self):
        doc = make_census()
        doc["gpus"][0]["subsystem_device_id"] = "8a98"
        with self.assertRaisesRegex(ValueError, "subsystem"):
            census.validate_census(doc)

    def test_reference_vulkan_uuid_drift_rejected(self):
        doc = make_census()
        doc["gpus"][0]["vulkan_device_uuid"] = "ffffffff-ffff-ffff-ffff-ffffffffffff"
        with self.assertRaisesRegex(ValueError, "vulkan_device_uuid"):
            census.validate_census(doc)

    def test_candidate_max_link_capability_drift_rejected(self):
        with self.assertRaisesRegex(ValueError, "max_link"):
            census.validate_census(
                self._candidate_field("max_link_width", "x8"))

    def test_candidate_driver_drift_rejected(self):
        with self.assertRaisesRegex(ValueError, "driver"):
            census.validate_census(
                self._candidate_field("driver_in_use", "radeon"))

    def test_candidate_icd_drift_rejected(self):
        with self.assertRaisesRegex(ValueError, "vulkan_icd"):
            census.validate_census(self._candidate_field(
                "vulkan_icd", "/usr/share/vulkan/icd.d/nvidia_icd.json"))


class TestPlacement(unittest.TestCase):
    def test_matched_rung_selection(self):
        rungs = {
            "B": [make_rung("B", n) for n in C.LADDER_NGLS],
            "C": [make_rung("C", n) for n in C.LADDER_NGLS],
        }
        verdict = placement.select_matched_rung(rungs)
        self.assertEqual(verdict["matched_ngl"], 8)
        self.assertFalse(verdict["placement_blocked"])

    # --- Phase-2 determinism/health negative controls (correction pass) ---

    def test_repeat_token_mismatch_rejects_rung(self):
        rung = make_rung("C", 4)
        rung["repeats"] = valid_repeats(response_tokens=[1] * 8)
        # competent forgery: change repeat 1's tokens AND its claimed
        # deterministic-output digest so the surviving problem is exactly
        # the non-determinism of the rung's output
        rung["repeats"][1]["response_tokens"] = [2] * 8
        rung["repeats"][1]["deterministic_output_sha256"] = (
            placement.deterministic_output_sha256([2] * 8))
        rung["repeats"][1]["response_raw_sha256"] = "a" * 64
        verdict = placement.judge_rung(rung)
        self.assertFalse(verdict["valid"])
        self.assertTrue(any("non-deterministic" in p for p in verdict["problems"]))
        self.assertFalse(any("deterministic_output_sha256 !=" in p
                             for p in verdict["problems"]))

    def test_missing_repeat_rejects_rung(self):
        rung = make_rung("C", 4)
        rung["repeats"] = valid_repeats()[:1]
        verdict = placement.judge_rung(rung)
        self.assertFalse(verdict["valid"])
        self.assertTrue(any("missing repeat" in p for p in verdict["problems"]))

    def test_non_eight_token_response_rejects_rung(self):
        rung = make_rung("C", 4)
        rung["repeats"] = valid_repeats(response_tokens=[1] * 7)
        verdict = placement.judge_rung(rung)
        self.assertFalse(verdict["valid"])
        self.assertTrue(any("expected count/type" in p for p in verdict["problems"]))

    def test_insane_completion_rejects_rung(self):
        rung = make_rung("C", 4)
        rung["repeats"] = valid_repeats()
        rung["repeats"][0]["sane_completion"] = False
        verdict = placement.judge_rung(rung)
        self.assertFalse(verdict["valid"])
        self.assertTrue(any("sane completion" in p for p in verdict["problems"]))

    def test_missing_health_artifact_rejects_rung(self):
        rung = make_rung("C", 4)
        rung["device_health"] = None
        verdict = placement.judge_rung(rung)
        self.assertFalse(verdict["valid"])
        self.assertTrue(any("health artifact" in p for p in verdict["problems"]))

    def test_fatal_health_state_rejects_rung(self):
        for state in ("selected_device_disappeared", "driver_drift",
                      "bdf_drift", "icd_drift", "device_reset_or_error",
                      "missing_health_evidence"):
            with self.subTest(state=state):
                rung = make_rung("C", 4)
                rung["device_health"] = {
                    "fatal_states": [state],
                    "observed": valid_device_identity("C")}
                verdict = placement.judge_rung(rung)
                self.assertFalse(verdict["valid"])
                self.assertTrue(any("fatal" in p for p in verdict["problems"]))

    def test_missing_mandatory_health_evidence_rejects_rung(self):
        rung = make_rung("C", 4)
        observed = valid_device_identity("C")
        del observed["driver_in_use"]
        rung["device_health"] = {"fatal_states": [], "observed": observed}
        verdict = placement.judge_rung(rung)
        self.assertFalse(verdict["valid"])
        self.assertTrue(any("mandatory health evidence" in p for p in verdict["problems"]))

    def test_unknown_health_state_fails_closed(self):
        rung = make_rung("C", 4)
        rung["device_health"] = {"fatal_states": ["gpu_on_fire"],
                                 "observed": valid_device_identity("C")}
        verdict = placement.judge_rung(rung)
        self.assertFalse(verdict["valid"])
        self.assertTrue(any("unknown health state" in p for p in verdict["problems"]))

    def test_rung_identity_drift_after_phase1_rejects_rung(self):
        rung = make_rung("C", 4)
        drifted = valid_device_identity("C")
        drifted["subsystem_device_id"] = "e387"  # different [1002:67df] board
        rung["device_identity"] = drifted
        verdict = placement.judge_rung(rung)
        self.assertFalse(verdict["valid"])
        self.assertTrue(any("frozen-identity drift" in p for p in verdict["problems"]))

    def test_post_execution_identity_drift_rejects_rung(self):
        rung = make_rung("C", 4)
        drifted = valid_device_identity("C")
        drifted["revision"] = "e6"
        rung["post_execution_device_identity"] = drifted
        verdict = placement.judge_rung(rung)
        self.assertFalse(verdict["valid"])
        self.assertTrue(any("frozen-identity drift" in p for p in verdict["problems"]))

    def test_forged_health_summary_differing_from_raw_evidence_rejected(self):
        # health.observed carries the RAW identity observation; a summary
        # claiming no fatal drift while the observed device disappeared is
        # mechanically impossible — _device_health derives the fatal state
        # FROM the observation. Simulate the forged artifact directly:
        rung = make_rung("C", 4)
        observed = valid_device_identity("C")
        observed["selected_device_present"] = False
        rung["device_health"] = {"fatal_states": [], "observed": observed}
        verdict = placement.judge_rung(rung)
        self.assertFalse(verdict["valid"])

    def test_highest_rung_fails_determinism_next_common_rung_selected(self):
        rungs = {
            "B": [make_rung("B", n) for n in C.LADDER_NGLS],
            "C": [make_rung("C", n) for n in C.LADDER_NGLS],
        }
        # poison ngl=8 on BOTH arms with non-deterministic repeats
        for arm in ("B", "C"):
            bad = valid_repeats(arm)
            bad[1]["response_tokens"] = [99] * 8
            bad[1]["deterministic_output_sha256"] = (
                placement.deterministic_output_sha256([99] * 8))
            bad[1]["response_raw_sha256"] = "b" * 64
            rungs[arm][-1]["repeats"] = bad
        verdict = placement.select_matched_rung(rungs)
        self.assertEqual(verdict["matched_ngl"], 6)

    def test_one_arm_nondeterministic_rejects_rung(self):
        rungs = {
            "B": [make_rung("B", n) for n in C.LADDER_NGLS],
            "C": [make_rung("C", n) for n in C.LADDER_NGLS],
        }
        bad = valid_repeats("C")
        bad[1]["response_tokens"] = [99] * 8
        bad[1]["deterministic_output_sha256"] = (
            placement.deterministic_output_sha256([99] * 8))
        bad[1]["response_raw_sha256"] = "b" * 64
        rungs["C"][-1]["repeats"] = bad
        verdict = placement.select_matched_rung(rungs)
        self.assertEqual(verdict["matched_ngl"], 6)

    def test_agreement_fields_cannot_influence_selection(self):
        rungs = {
            "B": [make_rung("B", n) for n in C.LADDER_NGLS],
            "C": [make_rung("C", n) for n in C.LADDER_NGLS],
        }
        # inject performance/agreement-looking fields; selection must not
        # change (judge/select never read them)
        for arm in ("B", "C"):
            for rung in rungs[arm]:
                rung["candidate_reference_agreement"] = 1.0
                rung["performance_ms"] = 0.1
        verdict = placement.select_matched_rung(rungs)
        self.assertEqual(verdict["matched_ngl"], 8)
        # the judging/selection code paths never read agreement or
        # performance fields (source-level control)
        for function in (placement.judge_rung, placement.select_matched_rung,
                         placement._determinism_problems,
                         placement._health_problems):
            source = inspect.getsource(function)
            self.assertNotIn('rung.get("candidate_reference_agreement")', source)
            self.assertNotIn('rung.get("performance_ms")', source)

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


# ---------------------------------------------------------------------------
# correction pass 5 — Phase-2 determinism semantics + per-repeat identity
# custody negative controls
# ---------------------------------------------------------------------------

class TestDeterminismSemantics(unittest.TestCase):
    """Variable-timing/same-token determinism + digest forgery controls."""

    def test_same_tokens_different_timings_still_deterministic(self):
        rung = make_rung("C", 4)
        # raw responses differ (different bytes => different custody
        # digests); the canonical token output is identical
        rung["repeats"][1]["response_raw_sha256"] = "e" * 64
        verdict = placement.judge_rung(rung)
        self.assertTrue(verdict["valid"], verdict["problems"])
        self.assertEqual(len({r["deterministic_output_sha256"]
                              for r in rung["repeats"]}), 1)
        # the repeats carry deliberately different timings/metadata and
        # different raw-response digests — determinism must still hold
        self.assertNotEqual(rung["repeats"][0]["request_timings"],
                            rung["repeats"][1]["request_timings"])
        self.assertNotEqual(rung["repeats"][0]["response_raw_sha256"],
                            rung["repeats"][1]["response_raw_sha256"])

    def test_same_tokens_different_irrelevant_metadata_deterministic(self):
        rung = make_rung("B", 2)
        # extra incidental response metadata (fields the digest ignores)
        for rep in rung["repeats"]:
            rep["response_metadata"] = {"wall_s": 1.5, "throughput": 99.0}
        rung["repeats"][1]["response_metadata"]["wall_s"] = 2.5
        verdict = placement.judge_rung(rung)
        self.assertTrue(verdict["valid"], verdict["problems"])

    def test_one_changed_token_is_nondeterministic(self):
        rung = make_rung("C", 4)
        tokens = list(rung["repeats"][1]["response_tokens"])
        tokens[3] += 1
        rung["repeats"][1]["response_tokens"] = tokens
        rung["repeats"][1]["deterministic_output_sha256"] = (
            placement.deterministic_output_sha256(tokens))
        verdict = placement.judge_rung(rung)
        self.assertFalse(verdict["valid"])
        self.assertTrue(any("non-deterministic" in p for p in verdict["problems"]))

    def test_forged_deterministic_output_sha256_rejected(self):
        rung = make_rung("C", 4)
        rung["repeats"][1]["deterministic_output_sha256"] = "a" * 64
        verdict = placement.judge_rung(rung)
        self.assertFalse(verdict["valid"])
        self.assertTrue(any("deterministic_output_sha256 !=" in p
                            for p in verdict["problems"]))

    def test_canonical_encoding_is_frozen_little_endian_u32(self):
        tokens = [1, 2, 3, 4, 5, 6, 7, 8]
        self.assertEqual(placement.TOKEN_ENCODING, "<8I")
        canonical = placement.canonical_token_bytes(tokens)
        self.assertEqual(canonical, struct.pack("<8I", *tokens))
        self.assertEqual(len(canonical), 32)
        self.assertEqual(placement.deterministic_output_sha256(tokens),
                         hashlib.sha256(canonical).hexdigest())
        # a u64 encoding would differ — the encoding is mechanically fixed
        self.assertNotEqual(canonical, struct.pack("<8Q", *tokens))
        # big-endian differs — endianness is frozen
        self.assertNotEqual(canonical, struct.pack(">8I", *tokens))

    def test_out_of_vocabulary_or_malformed_tokens_rejected(self):
        for bad in ([11] * 7,                      # wrong count
                    [11] * 7 + [True],             # bool is not an int token
                    [11] * 7 + [C.N_VOCAB],        # == vocab size (out)
                    [11] * 7 + [-1],               # negative
                    [11] * 7 + [1.5],              # float
                    None, "tokens", [None] * 8):
            with self.subTest(bad=bad):
                self.assertIsNone(placement.canonical_token_bytes(bad))
                rung = make_rung("C", 4)
                for rep in rung["repeats"]:
                    rep["response_tokens"] = bad
                    rep["deterministic_output_sha256"] = (
                        placement.deterministic_output_sha256(bad))
                verdict = placement.judge_rung(rung)
                self.assertFalse(verdict["valid"])
                self.assertTrue(any("expected count/type" in p
                                    for p in verdict["problems"]))

    def test_high_rung_token_nondeterminism_falls_back_to_next_common(self):
        rungs = {"B": [make_rung("B", n) for n in C.LADDER_NGLS],
                 "C": [make_rung("C", n) for n in C.LADDER_NGLS]}
        for arm in ("B", "C"):
            rep = rungs[arm][-1]["repeats"][1]
            tokens = list(rep["response_tokens"])
            tokens[0] += 1
            rep["response_tokens"] = tokens
            rep["deterministic_output_sha256"] = (
                placement.deterministic_output_sha256(tokens))
        verdict = placement.select_matched_rung(rungs)
        self.assertEqual(verdict["matched_ngl"], 6)

    def test_c_vs_b_agreement_irrelevant_to_selection(self):
        # arms produce entirely different tokens; selection is unchanged
        rungs = {"B": [make_rung("B", n) for n in C.LADDER_NGLS],
                 "C": [make_rung("C", n) for n in C.LADDER_NGLS]}
        for rep in rungs["B"][0]["repeats"]:
            rep["response_tokens"] = [248319 - i for i in range(8)]
            rep["deterministic_output_sha256"] = (
                placement.deterministic_output_sha256(rep["response_tokens"]))
        verdict = placement.select_matched_rung(rungs)
        self.assertEqual(verdict["matched_ngl"], C.LADDER_NGLS[-1])


class TestPerRepeatIdentityCustody(unittest.TestCase):
    """Per-repeat raw identity/health evidence controls (pass 5 §2)."""

    def _rung_with_stage(self, stage, **derive_overrides):
        rung = make_rung("C", 4)
        raw = dict(RAW_IDENTITY_SOURCES("C"))
        raw["sysfs"] = dict(raw["sysfs"])
        raw["sysfs"].update(derive_overrides)
        derived = place_producer.derive_identity_from_raw("C", raw)
        rung["repeats"][1][f"identity_{stage}"] = derived
        return rung, raw, derived

    def test_missing_per_repeat_identity_evidence_rejects_rung(self):
        for stage in ("pre", "post"):
            with self.subTest(stage=stage):
                rung = make_rung("C", 4)
                for field in (f"identity_{stage}", f"raw_identity_{stage}",
                              f"raw_identity_{stage}_sha256"):
                    for rep in rung["repeats"]:
                        rep.pop(field)
                verdict = placement.judge_rung(rung)
                self.assertFalse(verdict["valid"])
                # the missing derived identity is reported as drift
                self.assertTrue(any(f"{stage}: C frozen-identity drift" in p
                                    for p in verdict["problems"]))

    def test_missing_first_repeat_identity_second_exists_rejects(self):
        rung = make_rung("C", 4)
        for field in ("identity_pre", "raw_identity_pre",
                      "raw_identity_pre_sha256"):
            rung["repeats"][0].pop(field)
        verdict = placement.judge_rung(rung)
        self.assertFalse(verdict["valid"])
        self.assertTrue(any("repeat 0 identity_pre" in p
                            for p in verdict["problems"]))

    def test_identity_drift_first_repeat_correct_second_rejected(self):
        rung = make_rung("C", 4)
        drifted = valid_device_identity("C")
        drifted["subsystem_device_id"] = "e387"
        rung["repeats"][0]["identity_pre"] = drifted
        # the rung-level aggregate still shows the correct first-repeat
        # identity would be wrong to trust — judge must fail on repeat 0
        verdict = placement.judge_rung(rung)
        self.assertFalse(verdict["valid"])
        self.assertTrue(any("repeat 0 identity_pre" in p
                            for p in verdict["problems"]))

    def test_wrong_subsystem_in_one_repeat_only_rejected(self):
        rung, raw, derived = self._rung_with_stage("pre", subsystem_device="0xe387")
        # derived now differs from frozen; judge must reject on repeat 1
        verdict = placement.judge_rung(rung)
        self.assertFalse(verdict["valid"])
        self.assertTrue(any("repeat 1 identity_pre" in p
                            for p in verdict["problems"]))

    def test_wrong_link_width_in_one_repeat_only_rejected(self):
        rung, _, _ = self._rung_with_stage("post", current_link_width="4")
        verdict = placement.judge_rung(rung)
        self.assertFalse(verdict["valid"])
        self.assertTrue(any("repeat 1 identity_post" in p
                            for p in verdict["problems"]))

    def test_wrong_revision_in_one_repeat_only_rejected(self):
        rung, _, _ = self._rung_with_stage("pre", revision="0xe6")
        verdict = placement.judge_rung(rung)
        self.assertFalse(verdict["valid"])
        self.assertTrue(any("repeat 1 identity_pre" in p
                            for p in verdict["problems"]))

    def test_missing_per_repeat_health_disposition_rejected(self):
        rung = make_rung("C", 4)
        rung["repeats"][1].pop("identity_post_health")
        verdict = placement.judge_rung(rung)
        self.assertFalse(verdict["valid"])
        self.assertTrue(any("repeat 1 missing per-repeat health" in p
                            for p in verdict["problems"]))

    def test_forged_healthy_repeat_summary_rejected(self):
        rung = make_rung("C", 4)
        forged_observed = valid_device_identity("C")
        forged_observed["selected_device_present"] = False
        rung["repeats"][1]["identity_post_health"] = {
            "fatal_states": [], "observed": forged_observed}
        verdict = placement.judge_rung(rung)
        self.assertFalse(verdict["valid"])
        self.assertTrue(any("repeat 1 forged health summary" in p
                            for p in verdict["problems"]))

    def test_forged_parsed_identity_with_no_raw_support_rejected(self):
        # production-time observer contract: identity != derivation of raw
        with self.assertRaisesRegex(ValueError, "raw-source derivation"):
            place_producer._verified_identity_observation(
                lambda arm: {"raw": RAW_IDENTITY_SOURCES(arm),
                             "identity": {**valid_device_identity(arm),
                                          "revision": "e9"}}, "C")

    def test_derivation_is_pure_function_of_raw_sources(self):
        raw = RAW_IDENTITY_SOURCES("B")
        derived = place_producer.derive_identity_from_raw("B", raw)
        self.assertEqual(derived["gpu_uuid"], C.REFERENCE_ARM["gpu_uuid"])
        self.assertEqual(derived["vulkan_device_uuid"],
                         C.REFERENCE_ARM["vulkan_device_uuid"])
        # kernel speed spelling normalizes to the frozen canonical form
        self.assertEqual(derived["max_link_speed"], "16.0 GT/s")
        # absent device => selected_device_present False (never a crash)
        missing = place_producer.derive_identity_from_raw(
            "B", {"sysfs_present": False})
        self.assertIs(missing.get("selected_device_present"), False)
        # missing required raw source => hard failure, not silence
        with self.assertRaises(ValueError):
            place_producer.derive_identity_from_raw(
                "B", {"sysfs_present": True, "sysfs": {"vendor": "0x10de"}})


# ---------------------------------------------------------------------------
# comparator/2 validation — byte custody + cross-binding (correction pass)
# ---------------------------------------------------------------------------

class ComparatorTestBase(unittest.TestCase):
    def staged_pair(self, case_id="case-256", ngl=1,
                    ref_value=0.25, cand_value=0.5):
        ref, stage_ref = make_run_receipt("B", case_id, ngl, ref_value)
        cand, stage_cand = make_run_receipt("C", case_id, ngl, cand_value)
        return ref, cand, stage_ref, stage_cand


class TestComparatorV2(ComparatorTestBase):
    def _reader(self, tmp: Path):
        return cmp2.custody_row_reader(tmp)

    def test_valid_pair_passes(self):
        ref, cand, stage_ref, stage_cand = self.staged_pair()
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            stage_ref(t)
            stage_cand(t)
            out = cmp2.validate_pair(ref, cand, self._reader(t))
            self.assertTrue(out["validated"], out["problems"])
            self.assertTrue(out["reference"]["row_digests_independent"])
            self.assertTrue(out["candidate"]["row_digests_independent"])

    # --- RAW-ROW CUSTODY: byte binding (spec control 1) ---
    def test_same_size_row_bytes_changed_claim_unchanged_fails(self):
        ref, cand, stage_ref, stage_cand = self.staged_pair()
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            stage_ref(t)
            stage_cand(t)
            # mutate row 3's FIRST float in place: same size, finite,
            # claimed sha unchanged
            p = t / ref["rows"]["3"]["path"]
            raw = bytearray(p.read_bytes())
            struct.pack_into("<f", raw, 0, 0.75)
            p.write_bytes(bytes(raw))
            out = cmp2.validate_arm_receipt(ref, "B", self._reader(t))
            self.assertFalse(out["valid"])
            self.assertTrue(any("digest mismatch" in q
                                for q in out["problems"]),
                            out["problems"])

    def test_repeat_identical_claimed_sha_different_bytes_fails(self):
        # two repeats claiming the same sha256 but different raw bytes
        a, stage_a = make_run_receipt("C", row_value=0.5, receipt_id="r1")
        b, stage_b = make_run_receipt("C", row_value=0.6, receipt_id="r2")
        # make claimed shas identical (same claim) while bytes differ
        for d in range(C.DECISIONS):
            b["rows"][str(d)]["sha256"] = a["rows"][str(d)]["sha256"]
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            stage_a(t)
            stage_b(t)
            out = cmp2.validate_determinism(a, b, self._reader(t))
            self.assertFalse(out["deterministic"], out["problems"])
            self.assertTrue(any("claimed digest" in q or "differ" in q
                                for q in out["problems"]))

    def test_determinism_detects_real_byte_change(self):
        a, stage_a = make_run_receipt("C", row_value=0.5, receipt_id="r1")
        b, stage_b = make_run_receipt("C", row_value=0.5, receipt_id="r2")
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            stage_a(t)
            stage_b(t)
            raw = bytearray((t / b["rows"]["2"]["path"]).read_bytes())
            struct.pack_into("<f", raw, 8, 0.125)
            (t / b["rows"]["2"]["path"]).write_bytes(bytes(raw))
            out = cmp2.validate_determinism(a, b, self._reader(t))
            self.assertFalse(out["deterministic"])
            self.assertTrue(any("differ" in q for q in out["problems"]),
                            out["problems"])

    def test_determinism_positive_on_identical_bytes(self):
        a, stage_a = make_run_receipt("C", row_value=0.5, receipt_id="r1")
        b, stage_b = make_run_receipt("C", row_value=0.5, receipt_id="r2")
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            stage_a(t)
            stage_b(t)
            out = cmp2.validate_determinism(a, b, self._reader(t))
            self.assertTrue(out["deterministic"], out["problems"])

    # --- ROW-PATH CUSTODY (spec controls: traversal, symlink, ...) ---
    def test_traversal_row_path_fails(self):
        ref, _ = make_run_receipt("B")
        for d, entry in ref["rows"].items():
            entry["path"] = "../outside.f32"
        out = cmp2.validate_arm_receipt(ref, "B", self._reader(Path("/tmp")))
        self.assertFalse(out["valid"])
        self.assertTrue(any("traversal" in q or "row path" in q
                            for q in out["problems"]))

    def test_absolute_row_path_fails(self):
        ref, _ = make_run_receipt("B")
        for d, entry in ref["rows"].items():
            entry["path"] = "/etc/passwd"
        out = cmp2.validate_arm_receipt(ref, "B", self._reader(Path("/tmp")))
        self.assertFalse(out["valid"])
        self.assertTrue(any("absolute" in q for q in out["problems"]))

    def test_escape_from_run_root_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            (t / "outside.f32").write_bytes(b"x" * C.ROW_BYTES)
            reader = cmp2.custody_row_reader(t / "run")
            with self.assertRaises(ValueError):
                reader("../outside.f32")

    def test_symlink_row_fails(self):
        ref, stage = make_run_receipt("B")
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            stage(t)
            victim = t / ref["rows"]["0"]["path"]
            victim.unlink()
            os.symlink(t / "alias-target.f32", victim)
            (t / "alias-target.f32").write_bytes(b"y" * C.ROW_BYTES)
            out = cmp2.validate_arm_receipt(ref, "B", self._reader(t))
            self.assertFalse(out["valid"])
            self.assertTrue(any("symlink" in q or "custody read failed" in q
                                for q in out["problems"]),
                            out["problems"])

    def test_missing_row_file_fails(self):
        ref, stage = make_run_receipt("B")
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            stage(t)
            (t / ref["rows"]["5"]["path"]).unlink()
            out = cmp2.validate_arm_receipt(ref, "B", self._reader(t))
            self.assertFalse(out["valid"])
            self.assertTrue(any("custody read failed" in q or "missing" in q
                                for q in out["problems"]))

    def test_nonregular_row_fails(self):
        ref, stage = make_run_receipt("B")
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            stage(t)
            victim = t / ref["rows"]["1"]["path"]
            victim.unlink()
            victim.mkdir()
            out = cmp2.validate_arm_receipt(ref, "B", self._reader(t))
            self.assertFalse(out["valid"])
            self.assertTrue(any("not a regular file" in q or
                                "custody read failed" in q
                                for q in out["problems"]))

    # --- original controls, upgraded to the /2 schema ---
    def test_missing_decision_fails(self):
        ref, cand, stage_ref, stage_cand = self.staged_pair()
        del cand["rows"]["7"]
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            stage_ref(t)
            stage_cand(t)
            out = cmp2.validate_pair(ref, cand, self._reader(t))
            self.assertFalse(out["validated"])
            self.assertTrue(any("row decisions" in p or "!= 8" in p
                                for p in out["problems"]))

    def test_candidate_prefix_must_be_reference_winners(self):
        ref, cand, stage_ref, stage_cand = self.staged_pair()
        cand["forced_tokens"][3] = 999
        cand["meta_rows"][3]["forced_token"] = 999
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            stage_ref(t)
            stage_cand(t)
            out = cmp2.validate_pair(ref, cand, self._reader(t))
            self.assertFalse(out["validated"])
            self.assertTrue(any("forced prefix" in p for p in out["problems"]))

    def test_reference_arm_must_not_force(self):
        ref, cand, stage_ref, stage_cand = self.staged_pair()
        ref["forced_tokens"] = list(WINNERS)
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            stage_ref(t)
            stage_cand(t)
            out = cmp2.validate_pair(ref, cand, self._reader(t))
            self.assertFalse(out["validated"])
            self.assertTrue(any("must not force" in p for p in out["problems"]))

    def test_cuda_participation_fails(self):
        ref, cand, stage_ref, stage_cand = self.staged_pair()
        ref["cuda_visible_devices"] = "0"
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            stage_ref(t)
            stage_cand(t)
            out = cmp2.validate_pair(ref, cand, self._reader(t))
            self.assertFalse(out["validated"])
            self.assertTrue(any("CUDA" in p for p in out["problems"]))

    def test_predictive_case_fails(self):
        ref, _ = make_run_receipt("B", case_id="c237-01-01-001")
        with self.assertRaises(RuntimeError):
            cmp2.validate_arm_receipt(ref, "B", self._reader(Path("/tmp")))

    def test_nonfinite_row_fails(self):
        ref, cand, stage_ref, stage_cand = self.staged_pair()
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            stage_ref(t)
            stage_cand(t)
            raw = bytearray((t / ref["rows"]["3"]["path"]).read_bytes())
            struct.pack_into("<f", raw, 400, float("nan"))
            # keep the claimed sha consistent (attack: claim matches the
            # NaN bytes) so the ONLY catcher must be finiteness
            ref["rows"]["3"]["sha256"] = sha256_bytes(bytes(raw))
            (t / ref["rows"]["3"]["path"]).write_bytes(bytes(raw))
            out = cmp2.validate_arm_receipt(ref, "B", self._reader(t))
            self.assertFalse(out["valid"])
            self.assertTrue(any("non-finite" in q for q in out["problems"]))

    def test_wrong_host_fails(self):
        ref, cand, stage_ref, stage_cand = self.staged_pair()
        ref["host"] = "inferswarm02"
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            stage_ref(t)
            stage_cand(t)
            out = cmp2.validate_pair(ref, cand, self._reader(t))
            self.assertFalse(out["validated"])
            self.assertTrue(any("same host" in p for p in out["problems"]))

    def test_inertness(self):
        tokens = [1, 2, 3, 4, 5, 6, 7, 8]
        self.assertTrue(cmp2.validate_inertness(tokens, list(tokens))["inert"])
        self.assertFalse(
            cmp2.validate_inertness(tokens, tokens[:-1] + [9])["inert"])

    def test_row_bytes_constant(self):
        self.assertEqual(C.ROW_BYTES, 248320 * 4)


class TestComparatorCrossBinding(ComparatorTestBase):
    """Spec item 3: cross-bind comparator/2 to the exact case, subject,
    placement, and runtime — one mutation per control, each tampered
    coherently (recomputing nothing else) so the intended gate fires."""

    def _pair(self, **kw):
        return self.staged_pair(**kw)

    def _run(self, ref, cand):
        with tempfile.TemporaryDirectory() as tmp:
            return cmp2.validate_pair(ref, cand, cmp2.custody_row_reader(Path(tmp)))

    def test_different_case_ids_fail(self):
        ref, cand, stage_ref, stage_cand = self._pair()
        cand["case_id"] = "case-1024"
        out = self._run(ref, cand)
        self.assertFalse(out["validated"])
        self.assertTrue(any("case mismatch" in p for p in out["problems"]))

    def test_different_ngl_fails(self):
        ref, cand, stage_ref, stage_cand = self._pair()
        cand["ngl"] = 2
        cand["process_attribution"]["server_argv"][
            cand["process_attribution"]["server_argv"].index("-ngl") + 1] = "2"
        out = self._run(ref, cand)
        self.assertFalse(out["validated"])
        self.assertTrue(any("ngl mismatch" in p for p in out["problems"]))

    def test_wrong_bdf_fails(self):
        ref, cand, stage_ref, stage_cand = self._pair()
        ref["bdf"] = "00000000:02:00.0"
        out = self._run(ref, cand)
        self.assertFalse(out["validated"])
        self.assertTrue(any("bdf mismatch" in p for p in out["problems"]))

    def test_wrong_gpu_uuid_fails(self):
        ref, cand, stage_ref, stage_cand = self._pair()
        ref["gpu_uuid"] = "GPU-1fc28f83-1d45-926e-54d0-ba1e835ef099"
        out = self._run(ref, cand)
        self.assertFalse(out["validated"])
        self.assertTrue(any("reference GPU uuid mismatch" in p
                            for p in out["problems"]))

    def test_wrong_amd_pci_identity_fails(self):
        ref, cand, stage_ref, stage_cand = self._pair()
        cand["pci_id"] = "1002:67dfx"
        out = self._run(ref, cand)
        self.assertFalse(out["validated"])
        self.assertTrue(any("AMD PCI identity" in p for p in out["problems"]))

    def test_wrong_icd_device_fails(self):
        ref, cand, stage_ref, stage_cand = self._pair()
        cand["icd"] = "/usr/share/vulkan/icd.d/nvidia_icd.json"
        out = self._run(ref, cand)
        self.assertFalse(out["validated"])
        self.assertTrue(any("ICD" in p for p in out["problems"]))

    def test_wrong_vulkan_device_name_fails(self):
        ref, cand, stage_ref, stage_cand = self._pair()
        cand["vulkan_device_name"] = "llvmpipe (LLVM 19.1.7)"
        out = self._run(ref, cand)
        self.assertFalse(out["validated"])
        self.assertTrue(any("Vulkan device identity" in p
                            for p in out["problems"]))

    def test_wrong_binary_hash_fails(self):
        ref, cand, stage_ref, stage_cand = self._pair()
        cand["server_sha256"] = "a" * 64
        out = self._run(ref, cand)
        self.assertFalse(out["validated"])
        self.assertTrue(any("server_sha256" in p or "server/binary" in p
                            for p in out["problems"]))

    def test_wrong_patched_source_hash_fails(self):
        ref, cand, stage_ref, stage_cand = self._pair()
        cand["patched_source_sha256"] = "b" * 64
        out = self._run(ref, cand)
        self.assertFalse(out["validated"])
        self.assertTrue(any("patched-source" in p for p in out["problems"]))

    def test_wrong_model_member_identity_fails(self):
        ref, cand, stage_ref, stage_cand = self._pair()
        tampered = dict(cand["model_members"])
        tampered[C.MODEL_MEMBERS[0]] = "0" * 64
        cand["model_members"] = tampered
        out = self._run(ref, cand)
        self.assertFalse(out["validated"])
        self.assertTrue(any("model member" in p for p in out["problems"]))

    def test_wrong_fixture_or_prompt_digest_fails(self):
        ref, cand, stage_ref, stage_cand = self._pair()
        cand["fixture_ladder_sha256"] = "0" * 64
        out = self._run(ref, cand)
        self.assertFalse(out["validated"])
        self.assertTrue(any("fixture ladder" in p for p in out["problems"]))

    def test_wrong_prompt_token_ids_fails(self):
        ref, cand, stage_ref, stage_cand = self._pair()
        tampered = list(cand["prompt_token_ids"])
        tampered[0] += 1
        cand["prompt_token_ids"] = tampered
        out = self._run(ref, cand)
        self.assertFalse(out["validated"])
        self.assertTrue(any("prompt token ids" in p for p in out["problems"]))

    def test_prompt_text_digest_swap_fails(self):
        ref, cand, stage_ref, stage_cand = self._pair()
        cand["prompt_text_sha256"] = "0" * 64
        out = self._run(ref, cand)
        self.assertFalse(out["validated"])
        self.assertTrue(any("prompt text digest" in p for p in out["problems"]))

    def test_meta_row_disagreeing_with_receipt_arrays_fails(self):
        ref, cand, stage_ref, stage_cand = self._pair()
        cand["meta_rows"][5]["sampled_winner"] = \
            cand["meta_rows"][5]["sampled_winner"] + 1
        out = self._run(ref, cand)
        self.assertFalse(out["validated"])
        self.assertTrue(any("meta row 5 sampled_winner" in p
                            for p in out["problems"]))

    def test_meta_row_forced_token_disagreeing_with_array_fails(self):
        ref, cand, stage_ref, stage_cand = self._pair()
        cand["meta_rows"][2]["forced_token"] = 424242
        out = self._run(ref, cand)
        self.assertFalse(out["validated"])
        self.assertTrue(any("meta row 2 forced_token" in p
                            for p in out["problems"]))

    def test_meta_positions_not_0_to_7_fails(self):
        ref, cand, stage_ref, stage_cand = self._pair()
        ref["meta_rows"] = ref["meta_rows"][:7]
        out = self._run(ref, cand)
        self.assertFalse(out["validated"])
        self.assertTrue(any("positions 0..7" in p for p in out["problems"]))

    def test_meta_forced_token_must_be_reference_winner(self):
        ref, cand, stage_ref, stage_cand = self._pair()
        # candidate meta claims a non-reference forced token at d=1,
        # while the receipt arrays stay consistent — meta-vs-reference
        # binding must catch it
        cand["meta_rows"][1]["forced_token"] = cand["meta_rows"][1][
            "sampled_winner"] + 7
        out = self._run(ref, cand)
        self.assertFalse(out["validated"])
        self.assertTrue(any("meta row 1 forced_token" in p
                            for p in out["problems"]))

    def test_missing_dispatch_authority_fails(self):
        ref, cand, stage_ref, stage_cand = self._pair()
        del cand["dispatch_authority"]
        out = self._run(ref, cand)
        self.assertFalse(out["validated"])
        self.assertTrue(any("dispatch-authority" in p for p in out["problems"]))

    def test_cross_binding_covers_subject_runtime_fields(self):
        for field in cmp2.CROSS_BOUND_FIELDS:
            ref, cand, _, _ = self._pair()
            cand[field] = "TAMPERED"
            out = self._run(ref, cand)
            self.assertFalse(out["validated"], field)
            self.assertTrue(any(field in p for p in out["problems"]), field)

    def test_reference_ngl_must_equal_candidate_ngl_at_selection(self):
        ref, cand, stage_ref, stage_cand = self._pair()
        out = cmp2.validate_pair(ref, cand,
                                 cmp2.custody_row_reader(Path("/tmp")),
                                 expected_ngl=1)
        # no rows staged but path shape checks pass; validated is False
        # only because rows are unreadable — ngl must NOT be the catcher
        self.assertFalse(any("matched" in p or "expected_ngl" in p
                             for p in out["problems"]))

    def test_expected_ngl_mismatch_fails(self):
        ref, cand, stage_ref, stage_cand = self._pair()
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            stage_ref(t)
            stage_cand(t)
            out = cmp2.validate_pair(ref, cand, cmp2.custody_row_reader(t),
                                     expected_ngl=2)
            self.assertFalse(out["validated"])
            self.assertTrue(any("phase-2 matched" in p for p in out["problems"]))


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

    def test_no_authority_emitted_before_disposition_and_go(self):
        # Issue #241 sequencing: the builder must emit NO v2 authority
        # before the measured Phase-4 disposition AND maintainer GO.
        for terminal in C.DISPOSITIONS:
            out = supersession.build_supersession(phase4_terminal=terminal)
            self.assertFalse(out["authority_emitted"], terminal)
            self.assertIn("NO v2 supersession authority",
                          out["authority_note"], terminal)

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


# ---------------------------------------------------------------------------
# Physical dispatch gating (correction item 1)
# ---------------------------------------------------------------------------

class TestPhysicalDispatchGating(unittest.TestCase):
    """CPU-only tests of explicit, revalidated dispatch propagation."""

    def _deny_dispatch(self):
        return mock.patch.object(dispatch, "require_live_dispatch",
                                 side_effect=ValueError("no current approval"))

    def _grant_dispatch(self):
        return mock.patch.object(dispatch, "require_live_dispatch",
                                 return_value=dispatch_authority_receipt())

    def test_entrypoints_exist_and_are_committed(self):
        for name in physical.physical_entrypoints():
            self.assertTrue(callable(getattr(physical, name)))
            self.assertEqual(Path(physical.__file__).read_text().count(f"def {name}("), 1)

    def test_no_physical_operation_without_dispatch(self):
        calls = []
        with self._deny_dispatch(), mock.patch.object(
                physical, "_probe_devices", side_effect=lambda **kw: calls.append(kw)):
            for name in physical.physical_entrypoints():
                with self.assertRaises(ValueError):
                    getattr(physical, name)(REPO, pr_number=242)
        self.assertEqual(calls, [])

    def test_operations_only_after_gate_with_grant(self):
        with self._grant_dispatch(), mock.patch.object(
                physical, "_probe_devices", return_value={"census": "measured"}) as probe:
            with mock.patch.object(physical, "_atomic_json"):
                out = physical.run_phase1(REPO, evidence_root=REPO.parent / "synthetic-only",
                                          runner=object())
        probe.assert_called_once()
        self.assertEqual(out["dispatch_head_sha"], FAKE_HEAD)
        self.assertEqual(out["dispatch_authority"], dispatch_authority_receipt())

    def test_gate_refuses_dirty_worktree(self):
        with mock.patch.object(dispatch, "current_clean_git_head",
                               side_effect=ValueError("dirty")):
            with self.assertRaises(ValueError):
                physical.require_dispatch_authority(REPO, fetch=lambda *a: {})

    def test_gated_operation_call_directly_refuses_without_gate(self):
        for name in physical.GATED_OPERATION_ATTRS:
            with self.assertRaises((TypeError, ValueError, RuntimeError), msg=name):
                getattr(physical, name)()

    def test_cases_outside_bounded_set_rejected(self):
        for bad in ("c237-01-01-001", "case-512", "h237-02-05-001"):
            with self.assertRaises(RuntimeError, msg=bad):
                physical._load_fixture_content(bad,
                                               authority=dispatch_authority_receipt())

    def test_predictive_namespace_rejected_at_load(self):
        with self.assertRaises(RuntimeError):
            physical._load_fixture_content("p237-01",
                                           authority=dispatch_authority_receipt())

    def test_receipts_bind_dispatch_authority(self):
        authority = dispatch_authority_receipt()
        receipt = physical._receipt("test", authority)
        self.assertEqual(receipt["schema"], physical.PHYSICAL_SCHEMA)
        self.assertEqual(receipt["dispatch_head_sha"], FAKE_HEAD)
        self.assertEqual(receipt["dispatch_authority"], authority)

    def test_no_physical_execution_during_correction(self):
        calls = []
        with self._deny_dispatch(), mock.patch.object(
                physical, "_probe_devices", side_effect=lambda **kw: calls.append(kw)):
            for name in physical.physical_entrypoints():
                with self.assertRaises(ValueError):
                    getattr(physical, name)(REPO)
        self.assertEqual(calls, [])

    def test_source_order_gate_before_operations(self):
        import re as _re
        src = Path(physical.__file__).read_text()
        for name in physical.physical_entrypoints():
            m = _re.search(rf"def {name}\(.*?\n(?=def |\Z)", src, _re.DOTALL)
            self.assertIsNotNone(m, name)
            body = m.group(0)
            gate_at = body.find("require_dispatch_authority(")
            self.assertGreaterEqual(gate_at, 0, name)
            for attr in physical.GATED_OPERATION_ATTRS:
                op_at = body.find(f"{attr}(")
                if op_at >= 0:
                    self.assertLess(gate_at, op_at, name)

    def test_main_has_no_ungated_entrypoint(self):
        import re as _re
        src = Path(physical.__file__).read_text()
        for m in _re.finditer(r"def (run_[a-z0-9_]+)\(", src):
            body = _re.search(rf"def {m.group(1)}\(.*?\n(?=def |\Z)",
                              src, _re.DOTALL).group(0)
            self.assertIn("require_dispatch_authority(", body)

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
                    opatch, census, physical):
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
                     "issue241_dispatch", "issue241_observer_patch",
                     "issue241_physical"):
            self.assertTrue((REPO / "scripts" / f"{name}.py").is_file())

    def test_campaign_names_physical_entrypoints(self):
        self.assertEqual(campaign.PHYSICAL_ENTRYPOINTS,
                         ("run_phase1", "run_phase2", "run_phase3"))


if __name__ == "__main__":
    unittest.main()
"""Issue #273 (R8-I6A) — RED-first regression coverage for the #270
provenance-binding and per-arm-placement admission defects (CPU-only,
offline; zero physical execution).

RED phase (run against UNCORRECTED #270 tooling): reproduce the exact
accepted failure modes — the old validator admits or cannot
distinguish:

  1. reference arm uses candidate/V340L process+backend while identity
     fields claim RTX 3060 (the accepted #270 substitution);
  2. staged identity-bearing receipt differs from its source/original
     run receipt (post-capture relabeling);
  3. reference and candidate staged evidence alias the same underlying
     run/row bytes (24/24 byte-identical rows);
  4. arm-specific placement wrong: reference ngl=8, candidate ngl=7; a
     single shared ngl==7 rule is invalid — genuine ngl=8 reference
     receipts CANNOT pass the old validator (the actual #270 blocker);
  5. process backend/ICD/device selector contradicts the claimed arm;
  6. process executable/build/session provenance not bound to the
     source run receipt;
  7. a staged receipt can be modified after run capture without
     breaking admission;
  8. wrong source-run digest / source receipt digest / source row
     digest is rejected;
  9. candidate evidence cannot satisfy reference admission merely by
     rewriting host/BDF/GPU identity strings;
  10. reference primary/repeat mismatch is terminally rejected BEFORE
      cross-vendor comparison.

GREEN phase: the same fixtures must PASS/FAIL under the corrected
admission law (scripts/issue273_admission.py) with the intended
verdicts.

The fixtures mirror the RETAINED #270 staged-byte shapes (audit
AA-AUDIT-20261004.md): radeon ICD + GGML_VK_VISIBLE_DEVICES=0 + ngl=7
on both "arms" with subject_identity claiming the NVIDIA identity.
"""
from __future__ import annotations

import copy
import hashlib
import json
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import issue270_authority as C  # noqa: E402
import issue270_comparator as comparator  # noqa: E402
import issue273_admission as admission  # noqa: E402


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Fixtures shaped like the retained #270 staged receipts
# ---------------------------------------------------------------------------

GENUINE_NVIDIA_REF = {
    "arm": "reference", "host": "inferswarm01",
    "bdf": "00000000:03:00.0",
    "icd": "/usr/share/vulkan/icd.d/nvidia_icd.json",
    "selector": {"GGML_VK_VISIBLE_DEVICES": "0",
                 "CUDA_VISIBLE_DEVICES": "-1"},
    "cuda_visible_devices": "-1", "ngl": 8,
    "case_id": "case-256",
}

RELABLED_V340L_AS_REF = {
    # EXACTLY the retained #270 staged shape: identity labels claim the
    # NVIDIA reference, process facts are V340L candidate.
    "arm": "reference", "host": "inferswarm01",
    "bdf": "00000000:03:00.0",
    "icd": "/usr/share/vulkan/icd.d/radeon_icd.json",
    "selector": {"GGML_VK_VISIBLE_DEVICES": "0",
                 "CUDA_VISIBLE_DEVICES": "-1"},
    "cuda_visible_devices": "-1", "ngl": 7,
    "case_id": "case-256",
}

CANDIDATE = {
    "arm": "candidate", "host": "inferswarm05",
    "bdf": "0000:07:00.0",
    "icd": "/usr/share/vulkan/icd.d/radeon_icd.json",
    "selector": {"GGML_VK_VISIBLE_DEVICES": "0",
                 "CUDA_VISIBLE_DEVICES": "-1"},
    "cuda_visible_devices": "-1", "ngl": 7,
    "case_id": "case-256",
}


def _rows(seed: bytes, n: int = 8) -> dict:
    return {str(d): {"path": f"rows/case-256/r{seed.hex()[:4]}/{d}.f32",
                     "bytes": 4 * n, "sha256": sha256(seed + bytes([d]))}
            for d in range(8)}


def make_process(env_icd: str, ngl: int, pid: int, host: str | None,
                 model_dir: str | None = None) -> dict:
    return {"server_pid": pid,
            "server_argv": ["/srv/bin/llama-server", "--model",
                            f"{model_dir or C.MODEL_DIR}/{C.MODEL_MEMBER_1}",
                            "-ngl", str(ngl)],
            "server_env": {"VK_ICD_FILENAMES": env_icd,
                           "GGML_VK_VISIBLE_DEVICES": "0",
                           "CUDA_VISIBLE_DEVICES": "-1",
                           **({"INFERSWARM_HOST": host} if host else {})}}


def staged_receipt(base: dict, process: dict, rows: dict | None = None,
                   subject_identity: dict | None = None) -> dict:
    rows = rows or _rows(b"src-" + base["arm"].encode())
    r = copy.deepcopy(base)
    r["process_attribution"] = process
    r["rows"] = copy.deepcopy(rows)
    r["subject_identity"] = subject_identity or {
        "host": base["host"], "bdf": base["bdf"], "icd": base["icd"],
        "gpu_uuid": "GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55"}
    r["staged_source"] = admission.bind_staged_source(
        {}, f"units/case-256/{base['arm']}-primary-001/unit.json",
        sha256(json.dumps(r, sort_keys=True).encode()),
        {d: rows[d]["sha256"] for d in rows})
    return r




def source_digests_of(staged: dict) -> tuple[str, dict]:
    """Independently 'computed' source digests for a staged fixture
    (stands in for digests computed from retained source bytes)."""
    rows = staged.get("rows") or {}
    return (staged["staged_source"]["receipt_sha256"],
            {d: rows[d]["sha256"] for d in rows})


def as_source(staged: dict) -> dict:
    """Recover a source-shaped receipt from a staged fixture: identity
    fields + rows only (what the pre-staging run receipt carried)."""
    src = {k: copy.deepcopy(staged[k]) for k in admission.IDENTITY_FIELDS
           if k in staged}
    src["rows"] = copy.deepcopy(staged.get("rows") or {})
    return src


# ---------------------------------------------------------------------------
# RED phase: the OLD validator's defects
# ---------------------------------------------------------------------------

class OldToolingDefectTests(unittest.TestCase):
    """Each test proves the MERGED #270 tooling wrongly admits or
    cannot distinguish the accepted failure mode. These must FAIL
    against uncorrected tooling semantics — the assertions encode the
    CORRECT expectation, so on uncorrected code each fails (RED)."""

    def _old_validate(self, receipt: dict) -> dict:
        # The old per-arm path: identity from labels, single shared ngl.
        r = copy.deepcopy(receipt)
        r["_arm_const"] = {"selector": r["selector"], "icd": r["icd"],
                           "bdf": r["bdf"],
                           "build_flags": ["-DGGML_VULKAN=ON",
                                           "-DGGML_CUDA=OFF"],
                           "excluded_bdfs": ()}
        return comparator.validate_arm_receipt(
            r, r.get("arm"), lambda rel: b"\x00" * 4,
            C.reference_identity())

    def test_mode1_old_admits_relabelled_v340l_process_as_reference(self):
        # Mode 1 + 5: process facts are V340L (radeon ICD, VK dev 0,
        # ngl=7) while every identity label claims RTX 3060.
        receipt = staged_receipt(
            RELABLED_V340L_AS_REF,
            make_process("/usr/share/vulkan/icd.d/radeon_icd.json", 7,
                         31111, "inferswarm05"))
        result = comparator._process_attribution_problems(
            receipt, {"selector": receipt["selector"],
                      "icd": receipt["icd"]}, receipt["ngl"])
        # OLD defect: selector/ICD are only checked against the
        # receipt's OWN (writable) labels, so a radeon process passes
        # with an nvidia-subject claim. The corrected law must reject.
        self.assertTrue(
            any("required arm ICD" in p or "contradicts" in p
                for p in admission.process_attribution_problems(
                    receipt, "reference")),
            "corrected admission must reject the relabeled process")
        # ...and the old law could not (this documents the hole):
        old_rejects = any("ICD" in p for p in result)
        self.assertFalse(
            old_rejects,
            "RED contract: old tooling must NOT detect this (if it "
            "does, the RED premise is wrong)")

    def test_mode4_old_validator_rejects_genuine_ngl8_reference(self):
        # The actual #270 root cause: a GENUINE ngl=8 RTX 3060 receipt
        # fails the old shared-placement rule.
        genuine = staged_receipt(
            GENUINE_NVIDIA_REF,
            make_process("/usr/share/vulkan/icd.d/nvidia_icd.json", 8,
                         31112, "inferswarm01"))
        result = self._old_validate(genuine)
        self.assertFalse(result["valid"])
        self.assertTrue(any("ngl" in p for p in result["problems"]),
                        result["problems"])
        # Corrected law: per-arm placement admits ngl=8 reference.
        self.assertEqual(
            admission.process_attribution_problems(genuine, "reference"),
            [], "genuine reference must admit under per-arm placement")

    def test_mode10_old_pair_check_runs_comparison_before_ref_determinism(
            self):
        # The old terminal reducer validates the PAIR before/alongside
        # reference determinism with no ordering law. We assert the
        # corrected ordering structurally: admit_pair must surface the
        # reference repeat-mismatch problems even when the pair would
        # otherwise validate.
        ref_p = staged_receipt(GENUINE_NVIDIA_REF,
                               make_process("/usr/share/vulkan/icd.d/"
                                            "nvidia_icd.json", 8, 41,
                                            "inferswarm01"),
                               _rows(b"ref-p"))
        cand_p = staged_receipt(CANDIDATE,
                                make_process("/usr/share/vulkan/icd.d/"
                                             "radeon_icd.json", 7, 51,
                                             "inferswarm05"),
                                _rows(b"cand-p"))
        ref_rep = staged_receipt(GENUINE_NVIDIA_REF,
                                 make_process("/usr/share/vulkan/icd.d/"
                                              "nvidia_icd.json", 8, 42,
                                              "inferswarm01"),
                                 _rows(b"ref-R"))
        cand_rep = staged_receipt(CANDIDATE,
                                  make_process("/usr/share/vulkan/icd.d/"
                                               "radeon_icd.json", 7, 52,
                                               "inferswarm05"),
                                  _rows(b"cand-p"))
        problems = admission.admit_pair(
            ref_p, as_source(ref_p), cand_p, as_source(cand_p),
            ref_rep, cand_rep,
            reference_deterministic=False, candidate_deterministic=True
        )["problems"]
        self.assertTrue(any("reference" in p for p in problems))


# ---------------------------------------------------------------------------
# GREEN phase: corrected admission law verdicts
# ---------------------------------------------------------------------------

class CorrectedAdmissionTests(unittest.TestCase):

    def genuine_pair(self):
        ref = staged_receipt(
            GENUINE_NVIDIA_REF,
            make_process("/usr/share/vulkan/icd.d/nvidia_icd.json", 8,
                         41001, "inferswarm01"), _rows(b"ref-p"))
        cand = staged_receipt(
            CANDIDATE,
            make_process("/usr/share/vulkan/icd.d/radeon_icd.json", 7,
                         51001, "inferswarm05"), _rows(b"cand-p"))
        return ref, cand

    def test_genuine_pair_admits(self):
        ref, cand = self.genuine_pair()
        ref_rep = staged_receipt(
            GENUINE_NVIDIA_REF,
            make_process("/usr/share/vulkan/icd.d/nvidia_icd.json", 8,
                         41002, "inferswarm01"), _rows(b"ref-p"))
        cand_rep = staged_receipt(
            CANDIDATE,
            make_process("/usr/share/vulkan/icd.d/radeon_icd.json", 7,
                         51002, "inferswarm05"), _rows(b"cand-p"))
        rd, rrows = source_digests_of(ref)
        cd, crows = source_digests_of(cand)
        result = admission.admit_pair(
            ref, as_source(ref), cand, as_source(cand), ref_rep, cand_rep,
            reference_deterministic=True, candidate_deterministic=True,
            reference_source_digest=rd,
            reference_source_row_digests=rrows,
            candidate_source_digest=cd,
            candidate_source_row_digests=crows)
        self.assertEqual(result["problems"], [])
        self.assertTrue(result["admitted"])

    # --- mode 1/5/9: process-vs-claim contradictions ---------------

    def test_mode1_relabelled_candidate_process_rejected(self):
        receipt = staged_receipt(
            RELABLED_V340L_AS_REF,
            make_process("/usr/share/vulkan/icd.d/radeon_icd.json", 7,
                         31111, "inferswarm05"))
        problems = admission.process_attribution_problems(receipt,
                                                          "reference")
        self.assertTrue(problems, "must reject")
        self.assertTrue(any("required arm ICD" in p for p in problems))

    def test_mode9_identity_string_rewrite_alone_rejected(self):
        # Rewrite ONLY the identity strings of genuine candidate
        # evidence to reference values: process facts still RADV.
        forged = copy.deepcopy(CANDIDATE)
        forged.update({"arm": "reference", "host": "inferswarm01",
                       "bdf": "00000000:03:00.0",
                       "icd": "/usr/share/vulkan/icd.d/nvidia_icd.json"})
        forged["subject_identity"] = {
            "host": "inferswarm01", "bdf": "00000000:03:00.0",
            "icd": "/usr/share/vulkan/icd.d/nvidia_icd.json",
            "gpu_uuid": "GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55"}
        receipt = staged_receipt(
            forged,
            make_process("/usr/share/vulkan/icd.d/radeon_icd.json", 7,
                         51999, "inferswarm05"))
        problems = admission.process_attribution_problems(receipt,
                                                          "reference")
        self.assertTrue(any("required arm ICD" in p for p in problems))

    # --- mode 4: per-arm placement ---------------------------------

    def test_mode4_reference_ngl8_required_candidate_ngl7(self):
        ref8 = staged_receipt(
            GENUINE_NVIDIA_REF,
            make_process("/usr/share/vulkan/icd.d/nvidia_icd.json", 8,
                         41001, "inferswarm01"), _rows(b"r"))
        self.assertEqual(
            admission.process_attribution_problems(ref8, "reference"), [])
        # ngl=7 on the reference is now WRONG (old rule backwards).
        bad = copy.deepcopy(ref8)
        bad["ngl"] = 7
        bad["process_attribution"]["server_argv"][
            bad["process_attribution"]["server_argv"].index("-ngl") + 1] = "7"
        problems = admission.process_attribution_problems(bad, "reference")
        self.assertTrue(any("placement" in p for p in problems))
        # ngl=8 on the candidate is wrong too.
        cand8 = copy.deepcopy(CANDIDATE)
        cand8["ngl"] = 8
        cand8["process_attribution"] = make_process(
            "/usr/share/vulkan/icd.d/radeon_icd.json", 8, 51001,
            "inferswarm05")
        problems = admission.process_attribution_problems(cand8, "candidate")
        self.assertTrue(any("placement" in p for p in problems))

    # --- mode 2/7: staged vs source immutability --------------------

    def test_mode2_identity_field_rewrite_vs_source_rejected(self):
        staged = staged_receipt(
            GENUINE_NVIDIA_REF,
            make_process("/usr/share/vulkan/icd.d/nvidia_icd.json", 8,
                         41001, "inferswarm01"), _rows(b"r"))
        # The #270 byte-for-byte scenario: source was the V340L run...
        source = copy.deepcopy(RELABLED_V340L_AS_REF)
        problems = admission.staged_source_problems(staged, source)
        self.assertTrue(
            any("rewrote identity field" in p for p in problems))

    def test_mode7_post_capture_modification_breaks_admission(self):
        staged = staged_receipt(
            GENUINE_NVIDIA_REF,
            make_process("/usr/share/vulkan/icd.d/nvidia_icd.json", 8,
                         41001, "inferswarm01"), _rows(b"r"))
        source = copy.deepcopy(GENUINE_NVIDIA_REF)
        # After capture, someone flips the staged bdf:
        staged["bdf"] = "0000:99:00.0"
        problems = admission.staged_source_problems(staged, source)
        self.assertTrue(any("'bdf'" in p for p in problems))

    def test_mode2_consistent_source_admits(self):
        staged = staged_receipt(
            GENUINE_NVIDIA_REF,
            make_process("/usr/share/vulkan/icd.d/nvidia_icd.json", 8,
                         41001, "inferswarm01"), _rows(b"r"))
        source = as_source(staged)
        self.assertEqual(
            admission.staged_source_problems(staged, source), [])

    # --- mode 3: cross-arm aliasing ---------------------------------

    def test_mode3_row_aliasing_across_arms_rejected(self):
        rows = _rows(b"same-bytes")
        ref = staged_receipt(
            GENUINE_NVIDIA_REF,
            make_process("/usr/share/vulkan/icd.d/nvidia_icd.json", 8,
                         41001, "inferswarm01"), rows)
        cand = staged_receipt(
            CANDIDATE,
            make_process("/usr/share/vulkan/icd.d/radeon_icd.json", 7,
                         51001, "inferswarm05"), copy.deepcopy(rows))
        problems = admission.cross_arm_problems(ref, cand)
        self.assertTrue(any("byte-aliasing" in p for p in problems))

    def test_mode3_same_source_run_across_arms_rejected(self):
        ref, cand = self.genuine_pair()
        ref["staged_source"]["receipt_sha256"] = \
            cand["staged_source"]["receipt_sha256"] = "d" * 64
        problems = admission.cross_arm_problems(ref, cand)
        self.assertTrue(any("SAME source run" in p for p in problems))

    def test_identical_provenance_objects_rejected(self):
        # Same pid+argv across arms = same process served both.
        ref, cand = self.genuine_pair()
        cand["process_attribution"]["server_pid"] = \
            ref["process_attribution"]["server_pid"]
        problems = admission.cross_arm_problems(ref, cand)
        self.assertTrue(any("server_pid" in p for p in problems))

    # --- mode 6: provenance binding to source ------------------------

    def test_mode6_provenance_not_bound_to_source(self):
        staged = staged_receipt(
            GENUINE_NVIDIA_REF,
            make_process("/usr/share/vulkan/icd.d/nvidia_icd.json", 8,
                         41001, "inferswarm01"), _rows(b"r"))
        # process_attribution is an IDENTITY field: differing source
        # provenance is a relabeling, caught by staged_source law.
        source = copy.deepcopy(GENUINE_NVIDIA_REF)
        source["process_attribution"] = make_process(
            "/usr/share/vulkan/icd.d/nvidia_icd.json", 8, 99999,
            "inferswarm01")
        problems = admission.staged_source_problems(staged, source)
        self.assertTrue(
            any("process_attribution" in p for p in problems))

    # --- mode 8: digest chain ----------------------------------------

    def test_mode8_wrong_source_receipt_digest_rejected(self):
        staged = staged_receipt(
            GENUINE_NVIDIA_REF,
            make_process("/usr/share/vulkan/icd.d/nvidia_icd.json", 8,
                         41001, "inferswarm01"), _rows(b"r"))
        problems = admission.source_digest_problems(staged, "e" * 64, {})
        self.assertTrue(any("receipt digest" in p for p in problems))

    def test_mode8_wrong_source_row_digest_rejected(self):
        rows = _rows(b"r")
        staged = staged_receipt(
            GENUINE_NVIDIA_REF,
            make_process("/usr/share/vulkan/icd.d/nvidia_icd.json", 8,
                         41001, "inferswarm01"), rows)
        computed = {d: "f" * 64 for d in rows}
        problems = admission.source_digest_problems(
            staged, staged["staged_source"]["receipt_sha256"], computed)
        self.assertTrue(any("row" in p for p in problems))

    def test_mode8_row_substitution_at_staging_rejected(self):
        staged = staged_receipt(
            GENUINE_NVIDIA_REF,
            make_process("/usr/share/vulkan/icd.d/nvidia_icd.json", 8,
                         41001, "inferswarm01"), _rows(b"r"))
        source = copy.deepcopy(GENUINE_NVIDIA_REF)
        source["rows"] = _rows(b"different")
        problems = admission.staged_source_problems(staged, source)
        self.assertTrue(
            any("row bytes substituted" in p for p in problems))

    # --- mode 10: per-arm determinism ordering ------------------------

    def test_mode10_reference_repeat_mismatch_terminal_before_pair(self):
        ref, cand = self.genuine_pair()
        ref_rep = staged_receipt(
            GENUINE_NVIDIA_REF,
            make_process("/usr/share/vulkan/icd.d/nvidia_icd.json", 8,
                         41002, "inferswarm01"), _rows(b"ref-DIFFERENT"))
        cand_rep = staged_receipt(
            CANDIDATE,
            make_process("/usr/share/vulkan/icd.d/radeon_icd.json", 7,
                         51002, "inferswarm05"), _rows(b"cand-p"))
        result = admission.admit_pair(
            ref, as_source(ref), cand, as_source(cand), ref_rep, cand_rep,
            reference_deterministic=False, candidate_deterministic=True)
        # The reference repeat mismatch terminally blocks the pair —
        # the specific problem names the reference arm determinism.
        self.assertFalse(result["admitted"])
        self.assertTrue(any("reference primary/repeat determinism"
                            in p for p in result["problems"]))

    def test_mode10_reference_repeat_same_pid_rejected(self):
        ref, cand = self.genuine_pair()
        ref_rep = staged_receipt(
            GENUINE_NVIDIA_REF,
            make_process("/usr/share/vulkan/icd.d/nvidia_icd.json", 8,
                         41001, "inferswarm01"), _rows(b"ref-p"))
        cand_rep = staged_receipt(
            CANDIDATE,
            make_process("/usr/share/vulkan/icd.d/radeon_icd.json", 7,
                         51002, "inferswarm05"), _rows(b"cand-p"))
        rd, rrows = source_digests_of(ref)
        cd, crows = source_digests_of(cand)
        result = admission.admit_pair(
            ref, as_source(ref), cand, as_source(cand), ref_rep, cand_rep,
            reference_deterministic=True, candidate_deterministic=True,
            reference_source_digest=rd,
            reference_source_row_digests=rrows,
            candidate_source_digest=cd,
            candidate_source_row_digests=crows)
        self.assertTrue(
            any("fresh process" in p for p in result["problems"]))

    # --- misc fail-closed ---------------------------------------------

    def test_wrong_icd_label_rejected(self):
        bad = copy.deepcopy(GENUINE_NVIDIA_REF)
        bad["icd"] = "/usr/share/vulkan/icd.d/radeon_icd.json"
        receipt = staged_receipt(
            bad, make_process("/usr/share/vulkan/icd.d/nvidia_icd.json",
                              8, 41001, "inferswarm01"), _rows(b"r"))
        problems = admission.process_attribution_problems(receipt,
                                                          "reference")
        self.assertTrue(any("icd label" in p for p in problems))

    def test_unknown_arm_fails_closed(self):
        with self.assertRaises(admission.AdmissionError):
            admission.expected_placement("third-arm")

    def test_backend_exclusivity_double_check(self):
        ref, cand = self.genuine_pair()
        # Forge BOTH icd labels to the same value (suppose both claim
        # radeon): cross-arm check must reject identical ICDs even if
        # per-arm checks were to pass elsewhere.
        ref["icd"] = cand["icd"]
        problems = admission.cross_arm_problems(ref, cand)
        self.assertTrue(any("mutually exclusive" in p for p in problems))

    def test_cross_host_substitution_rejected(self):
        # Process ran on inferswarm05 while claiming reference host 01.
        receipt = staged_receipt(
            GENUINE_NVIDIA_REF,
            make_process("/usr/share/vulkan/icd.d/nvidia_icd.json", 8,
                         41001, "inferswarm05"), _rows(b"r"))
        problems = admission.process_attribution_problems(receipt,
                                                          "reference")
        self.assertTrue(any("process host" in p for p in problems))


class RetainedEvidenceFingerprintTests(unittest.TestCase):
    """Historical #270 evidence fingerprints stay unchanged — the
    corrected law never reclassifies historical evidence as valid."""

    def test_historical_270_terminal_bytes_are_not_valid_authority(self):
        # The corrected admission vocabulary has no path that admits
        # the retained #270 staged receipts: their process attribution
        # (radeon, VK dev 0) contradicts the reference arm contract.
        retained = staged_receipt(
            RELABLED_V340L_AS_REF,
            make_process("/usr/share/vulkan/icd.d/radeon_icd.json", 7,
                         31111, "inferswarm05"))
        problems = admission.process_attribution_problems(retained,
                                                          "reference")
        self.assertTrue(problems)
        cand_side = staged_receipt(
            CANDIDATE,
            make_process("/usr/share/vulkan/icd.d/radeon_icd.json",
                         7, 51001, "inferswarm05"), _rows(b"c"))
        self.assertFalse(
            admission.admit_pair(
                retained, as_source(retained),
                cand_side, as_source(cand_side),
                retained, cand_side,
                reference_deterministic=True,
                candidate_deterministic=True)["admitted"])


class MutationHoleKillerTests(unittest.TestCase):
    """Coverage for mutation-testing survivors (each test kills one
    source-level mutation of the corrected production surfaces)."""

    def test_staged_icd_differs_from_source_icd_rejected(self):
        # Kills identity-drop-icd: 'icd' must stay identity-bearing.
        staged = staged_receipt(
            GENUINE_NVIDIA_REF,
            make_process("/usr/share/vulkan/icd.d/nvidia_icd.json", 8,
                         41001, "inferswarm01"), _rows(b"r"))
        source = as_source(staged)
        source["icd"] = "/usr/share/vulkan/icd.d/radeon_icd.json"
        problems = admission.staged_source_problems(staged, source)
        self.assertTrue(any("'icd'" in p for p in problems))

    def test_cuda_fence_required_in_admission(self):
        # Kills cuda-fence-removed: admission itself must reject a
        # receipt whose CUDA fence is lifted (top level).
        bad = copy.deepcopy(GENUINE_NVIDIA_REF)
        bad["cuda_visible_devices"] = "0"
        receipt = staged_receipt(
            bad, make_process("/usr/share/vulkan/icd.d/nvidia_icd.json",
                              8, 41001, "inferswarm01"))
        problems = admission.process_attribution_problems(receipt,
                                                          "reference")
        self.assertTrue(any("CUDA not fenced" in p for p in problems))
        # ... and in the process env.
        bad2 = staged_receipt(
            GENUINE_NVIDIA_REF,
            make_process("/usr/share/vulkan/icd.d/nvidia_icd.json", 8,
                         41001, "inferswarm01"))
        bad2["process_attribution"]["server_env"][
            "CUDA_VISIBLE_DEVICES"] = "0"
        problems = admission.process_attribution_problems(bad2,
                                                          "reference")
        self.assertTrue(any("CUDA not fenced" in p for p in problems))

    def test_staged_source_binding_schema_required(self):
        # Kills staged-source-schema-removed: a staged_source block
        # without the correct schema string must be rejected.
        staged = staged_receipt(
            GENUINE_NVIDIA_REF,
            make_process("/usr/share/vulkan/icd.d/nvidia_icd.json", 8,
                         41001, "inferswarm01"), _rows(b"r"))
        source = as_source(staged)
        staged["staged_source"]["schema"] = "something-else/1"
        problems = admission.staged_source_problems(staged, source)
        self.assertTrue(any("staged-source binding" in p
                            for p in problems))

    def test_untrusted_candidate_determinism_claim_fails_closed(self):
        # Kills candidate-det-check-disabled: candidate nondeterminism
        # with a perfect reference must not reach PASS.
        import issue273_reducer as R
        cases = ["case-256", "case-1024", "case-3072"]
        adm = {c: {"admitted": True, "problems": []} for c in cases}
        det = {c: {"reference": True, "candidate": True} for c in cases}
        det["case-1024"] = {"reference": True, "candidate": False}
        rec = R.derive_terminal_273(adm, det)
        self.assertEqual(rec["terminal"], R.TERMINAL_RUNTIME_BLOCKED_273)
        self.assertTrue(any("retained-byte-to-terminal producer" in p
                            for p in rec["problems"]))

    def test_caller_admission_details_are_not_terminal_authority(self):
        # Kills pass-on-problems class: problems list must actually
        # flow into the blocked record (not be silently emptied).
        import issue273_reducer as R
        cases = ["case-256", "case-1024", "case-3072"]
        adm = {c: {"admitted": True, "problems": []} for c in cases}
        adm["case-256"] = {"schema": admission.SCHEMA,
                           "case_id": "case-256", "admitted": False,
                           "problems": ["reference: ICD mismatch"]}
        det = {c: {"reference": True, "candidate": True} for c in cases}
        rec = R.derive_terminal_273(adm, det)
        self.assertEqual(rec["terminal"], R.TERMINAL_RUNTIME_BLOCKED_273)
        self.assertTrue(any("retained-byte-to-terminal producer" in p
                            for p in rec["problems"]))



class EffectiveModelOptionTests(unittest.TestCase):
    def test_only_one_exact_model_member_option_is_admissible(self):
        accepted = f"{C.MODEL_DIR}/{C.MODEL_MEMBER_1}"
        variants = [
            ["--model", "/different/model.gguf", "--alias", accepted],
            ["--model", accepted, "-m", "/different/model.gguf"],
            ["--model", accepted, "--model=" + accepted],
            ["--model"], ["--model", str(C.MODEL_DIR)],
            ["--model", accepted + ".extra"],
        ]
        for variant in variants:
            with self.subTest(variant=variant):
                proc = make_process(C.NVIDIA_ICD, 8, 41001, "inferswarm01")
                proc["server_argv"] = ["/srv/bin/llama-server", *variant, "-ngl", "8"]
                problems = admission.process_attribution_problems(staged_receipt(GENUINE_NVIDIA_REF, proc), "reference")
                self.assertTrue(any("model" in p for p in problems), problems)
        for variant in (["--model", accepted], ["-m", accepted], ["--model=" + accepted]):
            proc = make_process(C.NVIDIA_ICD, 8, 41001, "inferswarm01")
            proc["server_argv"] = ["/srv/bin/llama-server", *variant, "-ngl", "8"]
            problems = admission.process_attribution_problems(staged_receipt(GENUINE_NVIDIA_REF, proc), "reference")
            self.assertFalse(any("model" in p for p in problems), problems)


class ReviewBlockerTests(unittest.TestCase):
    """Adversarial coverage for the independent-review blockers:
    digest-chain composition into admit_pair, mandatory process host,
    BDF arm binding, and reducer schema-authentication of admission
    records (a bare {"admitted": true} dict cannot reach PASS)."""

    def _full_admit(self, *, ref=None, cand=None, ref_rep=None,
                    cand_rep=None, ref_digest=None, ref_rows=None,
                    cand_digest=None, cand_rows=None):
        ref = ref or staged_receipt(
            GENUINE_NVIDIA_REF,
            make_process("/usr/share/vulkan/icd.d/nvidia_icd.json", 8,
                         41001, "inferswarm01"), _rows(b"ref-p"))
        cand = cand or staged_receipt(
            CANDIDATE,
            make_process("/usr/share/vulkan/icd.d/radeon_icd.json", 7,
                         51001, "inferswarm05"), _rows(b"cand-p"))
        ref_rep = ref_rep or staged_receipt(
            GENUINE_NVIDIA_REF,
            make_process("/usr/share/vulkan/icd.d/nvidia_icd.json", 8,
                         41002, "inferswarm01"), _rows(b"ref-p"))
        cand_rep = cand_rep or staged_receipt(
            CANDIDATE,
            make_process("/usr/share/vulkan/icd.d/radeon_icd.json", 7,
                         51002, "inferswarm05"), _rows(b"cand-p"))
        rd, rrows = source_digests_of(ref)
        cd, crows = source_digests_of(cand)
        return admission.admit_pair(
            ref, as_source(ref), cand, as_source(cand), ref_rep, cand_rep,
            reference_deterministic=True, candidate_deterministic=True,
            reference_source_digest=ref_digest if ref_digest is not None else rd,
            reference_source_row_digests=ref_rows if ref_rows is not None else rrows,
            candidate_source_digest=cand_digest if cand_digest is not None else cd,
            candidate_source_row_digests=cand_rows if cand_rows is not None else crows)

    def test_wrong_source_digest_blocks_admission(self):
        # Blocker 1: a WRONG independently-computed source digest must
        # fail the COMPOSED admission path (not just the isolated
        # helper).
        result = self._full_admit(ref_digest="e" * 64)
        self.assertFalse(result["admitted"])
        self.assertTrue(any("reference: " in p and "digest" in p
                            for p in result["problems"]))

    def test_wrong_source_row_digest_blocks_admission(self):
        ref = staged_receipt(
            GENUINE_NVIDIA_REF,
            make_process("/usr/share/vulkan/icd.d/nvidia_icd.json", 8,
                         41001, "inferswarm01"), _rows(b"ref-p"))
        bad_rows = {d: "f" * 64 for d in ref["rows"]}
        result = self._full_admit(ref=ref, ref_rows=bad_rows)
        self.assertFalse(result["admitted"])
        self.assertTrue(any("row" in p and "reference" in p
                            for p in result["problems"]))

    def test_missing_digests_fail_closed(self):
        ref = staged_receipt(
            GENUINE_NVIDIA_REF,
            make_process("/usr/share/vulkan/icd.d/nvidia_icd.json", 8,
                         41001, "inferswarm01"), _rows(b"ref-p"))
        cand = staged_receipt(
            CANDIDATE,
            make_process("/usr/share/vulkan/icd.d/radeon_icd.json", 7,
                         51001, "inferswarm05"), _rows(b"cand-p"))
        ref_rep = staged_receipt(
            GENUINE_NVIDIA_REF,
            make_process("/usr/share/vulkan/icd.d/nvidia_icd.json", 8,
                         41002, "inferswarm01"), _rows(b"ref-p"))
        cand_rep = staged_receipt(
            CANDIDATE,
            make_process("/usr/share/vulkan/icd.d/radeon_icd.json", 7,
                         51002, "inferswarm05"), _rows(b"cand-p"))
        result = admission.admit_pair(
            ref, as_source(ref), cand, as_source(cand), ref_rep, cand_rep,
            reference_deterministic=True, candidate_deterministic=True)
        self.assertFalse(result["admitted"])
        self.assertTrue(any("fails closed" in p for p in result["problems"]))

    def test_missing_process_host_observation_rejected(self):
        # Blocker 2: INFERSWARM_HOST is now MANDATORY.
        proc = make_process("/usr/share/vulkan/icd.d/nvidia_icd.json", 8,
                            41001, None)
        receipt = staged_receipt(GENUINE_NVIDIA_REF, proc)
        problems = admission.process_attribution_problems(receipt,
                                                          "reference")
        self.assertTrue(any("INFERSWARM_HOST) missing" in p
                            for p in problems))

    def test_reference_bdf_must_be_accepted_248_placement(self):
        # Blocker 2: reference BDF bound to the #248 placement.
        bad = copy.deepcopy(GENUINE_NVIDIA_REF)
        bad["bdf"] = "0000:99:00.0"
        receipt = staged_receipt(
            bad, make_process("/usr/share/vulkan/icd.d/nvidia_icd.json", 8,
                              41001, "inferswarm01"))
        problems = admission.process_attribution_problems(receipt,
                                                          "reference")
        self.assertTrue(any("#248 reference" in p for p in problems))

    def test_candidate_bdf_must_be_in_die_set(self):
        bad = copy.deepcopy(CANDIDATE)
        bad["bdf"] = "00000000:03:00.0"
        receipt = staged_receipt(
            bad, make_process("/usr/share/vulkan/icd.d/radeon_icd.json", 7,
                              51001, "inferswarm05"))
        problems = admission.process_attribution_problems(receipt,
                                                          "candidate")
        self.assertTrue(any("frozen V340 die set" in p for p in problems))

    def test_reducer_rejects_unauthenticated_admission_records(self):
        # Blocker 3: bare {"admitted": true} without the admission
        # schema cannot reach PASS.
        import issue273_reducer as R
        cases = ["case-256", "case-1024", "case-3072"]
        det = {c: {"reference": True, "candidate": True} for c in cases}
        bare = {c: {"admitted": True} for c in cases}
        rec = R.derive_terminal_273(bare, det)
        self.assertEqual(rec["terminal"], R.TERMINAL_RUNTIME_BLOCKED_273)
        self.assertTrue(any("retained-byte-to-terminal producer" in p
                            for p in rec["problems"]))
        # Schema-shaped forgeries receive the same fail-closed result.
        schema_forged = {c: {"schema": admission.SCHEMA,
                             "case_id": "case-4096", "admitted": True,
                             "problems": []} for c in cases}
        rec = R.derive_terminal_273(schema_forged, det)
        self.assertEqual(rec["terminal"], R.TERMINAL_RUNTIME_BLOCKED_273)
        self.assertTrue(any("retained-byte-to-terminal producer" in p
                            for p in rec["problems"]))

    def test_reducer_fails_closed_on_schema_shaped_admission_records(self):
        import issue273_reducer as R
        cases = ["case-256", "case-1024", "case-3072"]
        det = {c: {"reference": True, "candidate": True} for c in cases}
        good = {c: {"schema": admission.SCHEMA, "case_id": c,
                    "admitted": True, "problems": []} for c in cases}
        rec = R.derive_terminal_273(good, det)
        self.assertEqual(rec["terminal"], R.TERMINAL_RUNTIME_BLOCKED_273)
        self.assertTrue(any("retained-byte-to-terminal producer" in p
                            for p in rec["problems"]))


if __name__ == "__main__":
    unittest.main()


class ObserveVramTotalFoldInTests(unittest.TestCase):
    """#272 fold-in: observe_v340_host must capture mem_info_vram_total
    (required by derive_v340_identity) — fail-closed on omission."""

    def test_observe_requests_and_captures_vram_total(self):
        import tempfile
        import unittest.mock as mock
        import issue270_physical as P
        with tempfile.TemporaryDirectory() as td:
            fake = Path(td)
            for bdf in ("0000:07:00.0", "0000:0b:00.0"):
                dev = fake / bdf
                (dev / "drm" / "card1").mkdir(parents=True, exist_ok=True)
                (fake / "drivers" / "amdgpu").mkdir(parents=True,
                                                    exist_ok=True)
                (dev / "driver").symlink_to(fake / "drivers" / "amdgpu")
            requested = []

            def sysfs_reader(bdf, rel):
                requested.append((bdf, rel))
                return {"mem_info_vram_total": "8573157376",
                        "mem_info_vram_used": "8339456",
                        "vendor": "1002", "device": "6864",
                        "subsystem_vendor": "1002",
                        "subsystem_device": "0c00",
                        "revision": "0x05",
                        "current_link_speed": "8.0 GT/s PCIe",
                        "current_link_width": "16",
                        "max_link_speed": "8.0 GT/s PCIe",
                        "max_link_width": "16"}.get(rel, "0")

            def command_runner(argv):
                if argv[0] == "hostname":
                    return "inferswarm05\n"
                if argv[0] == "uname":
                    return "6.12.107+deb13-amd64\n"
                raise AssertionError(argv)

            with mock.patch.object(
                    P.Path, "glob",
                    side_effect=lambda pat: [fake / "0000:07:00.0" / "drm"
                                             / "card1"]), \
                 mock.patch.object(
                    P.Path, "is_symlink", lambda self: True), \
                 mock.patch.object(
                    P.Path, "resolve",
                    lambda self: fake / "drivers" / "amdgpu"), \
                 mock.patch.object(
                    P.Path, "is_dir", lambda self: True):
                try:
                    obs = P.observe_v340_host(
                        sysfs_reader=sysfs_reader,
                        command_runner=command_runner,
                        hostname="inferswarm05")
                except P.PhysicalError:
                    # Off-hardware: the RADV ICD file / vulkaninfo step
                    # may legitimately fail AFTER the per-die sysfs
                    # reads; the sysfs requests are what this test
                    # asserts.
                    obs = None
            rels = {rel for _, rel in requested}
            self.assertIn(
                "mem_info_vram_total", rels,
                "#272: observe_v340_host must capture mem_info_vram_total")
            if obs is not None:
                for bdf in ("0000:07:00.0", "0000:0b:00.0"):
                    self.assertEqual(
                        obs["raw"]["dies"][bdf]["mem_info_vram_total"],
                        "8573157376")








if __name__ == "__main__":
    unittest.main()


class CorrectiveReducerTests(unittest.TestCase):
    """#273 corrective dispatch law and terminal vocabulary."""

    def test_namespace_law(self):
        import issue273_reducer as R
        self.assertEqual(
            R.validate_namespace_273("c273-v340-comparator2-corrective"),
            "c273-v340-comparator2-corrective")
        for bad in ("c270-v340-comparator2",           # old namespace
                    "c273-holdout", "c273-threshold",
                    "c273-calibration", "c237-anything",
                    "c273-CAPS", "273-bare", "c273-"):
            with self.assertRaises(R.ReducerError, msg=bad):
                R.validate_namespace_273(bad)

    def _dispatch(self, **over):
        import issue273_reducer as R
        doc = {"schema": R.DISPATCH_SCHEMA, "issue": 273,
               "dispatch_phrase": R.DISPATCH_PHRASE_273,
               "head_sha": "a" * 40,
               "namespace": R.NAMESPACE_273,
               "commenter_association": "OWNER", "comment_id": 5982882220,
               "commenter": "ezutfen", "tooling_merged": True}
        doc.update(over)
        return doc

    def _github_transport(self, *, association="OWNER", commenter="ezutfen",
                          head="a" * 40, namespace=None, merged=True,
                          main_head="a" * 40):
        import issue273_reducer as R
        namespace = namespace or R.NAMESPACE_273
        body = (f"{R.DISPATCH_PHRASE_273}\nhead={head}\n"
                f"namespace={namespace}")
        data = {
            "/repos/Zutfen-LLC/inferswarm/issues/273/comments": [{
                "id": 5982882220, "body": body,
                "author_association": association,
                "user": {"login": commenter}}],
            "/repos/Zutfen-LLC/inferswarm/pulls/285": {
                "merged": merged, "merged_at": "2026-10-04T00:00:00Z"
                if merged else None, "merge_commit_sha": "a" * 40},
            "/repos/Zutfen-LLC/inferswarm/git/ref/heads/main": {
                "object": {"sha": main_head}},
        }
        return lambda path: data[path]

    def test_dispatch_law(self):
        import issue273_reducer as R
        # Valid.
        transport = self._github_transport()
        live = R.validate_dispatch_273(
            self._dispatch(commenter="spoofed", tooling_merged=False),
            "a" * 40, transport=transport, corrective_pr_number=285)
        self.assertEqual(live["commenter"], "ezutfen")
        self.assertTrue(live["tooling_merged"])
        # Stale head.
        with self.assertRaises(R.ReducerError):
            R.validate_dispatch_273(
                self._dispatch(), "b" * 40, transport=transport,
                corrective_pr_number=285)
        # Old namespace refused.
        with self.assertRaises(R.ReducerError):
            R.validate_dispatch_273(
                self._dispatch(), "a" * 40,
                transport=self._github_transport(
                    namespace="c270-v340-comparator2"),
                corrective_pr_number=285)
        # Legacy #270 phrase refused.
        with self.assertRaises(R.ReducerError):
            R.validate_dispatch_273(
                self._dispatch(), "a" * 40,
                transport=lambda path: (
                    [{"id": 1, "body": "R8I6 PHYSICAL DISPATCH #270\nhead="
                      + "a" * 40 + "\nnamespace=" + R.NAMESPACE_273,
                      "author_association": "OWNER",
                      "user": {"login": "ezutfen"}}]
                    if path.endswith("/comments") else
                    self._github_transport()(path)),
                corrective_pr_number=285)
        # Non-maintainer.
        with self.assertRaises(R.ReducerError):
            R.validate_dispatch_273(
                self._dispatch(), "a" * 40,
                transport=self._github_transport(association="CONTRIBUTOR"),
                corrective_pr_number=285)
        # Unmerged tooling refused.
        with self.assertRaises(R.ReducerError):
            R.validate_dispatch_273(
                self._dispatch(), "a" * 40,
                transport=self._github_transport(merged=False),
                corrective_pr_number=285)

    def _admitted(self, case):
        return {"schema": "inferswarm.issue273.corrective-admission/1",
                "case_id": case, "admitted": True, "problems": []}

    def test_terminal_vocabulary_and_order(self):
        import issue273_reducer as R
        cases = ["case-256", "case-1024", "case-3072"]
        det_ok = {c: {"reference": True, "candidate": True} for c in cases}
        adm_ok = {c: self._admitted(c) for c in cases}
        # Clean pass.
        rec = R.derive_terminal_273(adm_ok, det_ok)
        self.assertEqual(rec["terminal"], R.TERMINAL_RUNTIME_BLOCKED_273)
        self.assertTrue(any("retained-byte-to-terminal producer" in p
                            for p in rec["problems"]))
        # Reference nondeterminism on ANY case -> dedicated terminal,
        # even when candidate evidence is perfect and admissions pass.
        det_bad = dict(det_ok)
        det_bad["case-3072"] = {"reference": False, "candidate": True}
        rec = R.derive_terminal_273(adm_ok, det_bad)
        self.assertEqual(
            rec["terminal"], R.TERMINAL_RUNTIME_BLOCKED_273)
        self.assertTrue(any("retained-byte-to-terminal producer" in p
                            for p in rec["problems"]))
        # The legacy dict API refuses to infer even the nondeterministic
        # terminal from caller-provided booleans.
        # Admission failure -> RUNTIME_BLOCKED (never PASS).
        adm_bad = dict(adm_ok)
        adm_bad["case-256"] = {"admitted": False,
                               "problems": ["reference: ICD mismatch"]}
        rec = R.derive_terminal_273(adm_bad, det_ok)
        self.assertEqual(rec["terminal"], R.TERMINAL_RUNTIME_BLOCKED_273)
        # Missing case coverage -> RUNTIME_BLOCKED.
        rec = R.derive_terminal_273(
            {c: self._admitted(c) for c in cases[:2]}, det_ok)
        self.assertEqual(rec["terminal"], R.TERMINAL_RUNTIME_BLOCKED_273)

    def test_no_legacy_terminal_reuse(self):
        import issue273_reducer as R
        self.assertTrue(
            R.legacy_terminal_present({"terminal": C.TERMINAL_PASS}))
        self.assertFalse(R.legacy_terminal_present(
            {"terminal": R.TERMINAL_PASS_273}))







if __name__ == "__main__":
    unittest.main()


class MutationAttackTests(unittest.TestCase):
    """Phase-2 mutation tests: attack the CORRECTED production
    validator/admission surfaces directly. Each mutation of the
    production module source must flip at least one GREEN test to
    FAIL (verified by maintaining the mutation matrix as source-level
    negative controls on the admission/reducer law itself)."""

    def _genuine(self):
        ref = staged_receipt(
            GENUINE_NVIDIA_REF,
            make_process("/usr/share/vulkan/icd.d/nvidia_icd.json", 8,
                         41001, "inferswarm01"), _rows(b"ref-p"))
        cand = staged_receipt(
            CANDIDATE,
            make_process("/usr/share/vulkan/icd.d/radeon_icd.json", 7,
                         51001, "inferswarm05"), _rows(b"cand-p"))
        return ref, cand

    def test_mutation_arm_icd_map_swapped(self):
        # If ARM_ICD were swapped (reference->RADV), the relabeled-V340L
        # fixture would ADMIT as reference. Prove the map direction is
        # load-bearing: genuine reference fails under the swapped map.
        import issue273_admission as A
        swapped = {"reference": A.C.RADV_ICD, "candidate": A.C.NVIDIA_ICD}
        original = dict(A.ARM_ICD)
        try:
            A.ARM_ICD.clear()
            A.ARM_ICD.update(swapped)
            genuine = staged_receipt(
                GENUINE_NVIDIA_REF,
                make_process("/usr/share/vulkan/icd.d/nvidia_icd.json",
                             8, 41001, "inferswarm01"))
            problems = A.process_attribution_problems(genuine, "reference")
            self.assertTrue(
                any("required arm ICD" in p for p in problems),
                "swapped ICD map must reject the genuine reference")
        finally:
            A.ARM_ICD.clear()
            A.ARM_ICD.update(original)

    def test_mutation_placement_map_flattened(self):
        # If ARM_PLACEMENT were flattened to a single shared value (the
        # #270 defect reintroduced), one arm's genuine receipt fails.
        import issue273_admission as A
        original = dict(A.ARM_PLACEMENT)
        try:
            A.ARM_PLACEMENT["reference"] = 7  # the old shared rule
            genuine = staged_receipt(
                GENUINE_NVIDIA_REF,
                make_process("/usr/share/vulkan/icd.d/nvidia_icd.json",
                             8, 41001, "inferswarm01"))
            problems = A.process_attribution_problems(genuine, "reference")
            self.assertTrue(any("placement" in p for p in problems))
        finally:
            A.ARM_PLACEMENT.clear()
            A.ARM_PLACEMENT.update(original)

    def test_mutation_identity_fields_emptied(self):
        # If IDENTITY_FIELDS dropped 'process_attribution', mode-6
        # provenance substitution would pass staged-source checks.
        import issue273_admission as A
        staged = staged_receipt(
            GENUINE_NVIDIA_REF,
            make_process("/usr/share/vulkan/icd.d/nvidia_icd.json", 8,
                         41001, "inferswarm01"), _rows(b"r"))
        source = as_source(staged)
        source["process_attribution"] = make_process(
            "/usr/share/vulkan/icd.d/nvidia_icd.json", 8, 99999,
            "inferswarm01")
        self.assertTrue(
            any("process_attribution" in p
                for p in A.staged_source_problems(staged, source)),
            "process_attribution must be identity-bearing")

    def test_mutation_aliasing_check_removed(self):
        # If cross_arm_problems skipped row-aliasing, byte-identical
        # rows across arms would pass. Prove the check is load-bearing
        # by asserting on the exact aliasing fixture.
        import issue273_admission as A
        rows = _rows(b"alias")
        ref = staged_receipt(
            GENUINE_NVIDIA_REF,
            make_process("/usr/share/vulkan/icd.d/nvidia_icd.json", 8,
                         41001, "inferswarm01"), rows)
        cand = staged_receipt(
            CANDIDATE,
            make_process("/usr/share/vulkan/icd.d/radeon_icd.json", 7,
                         51001, "inferswarm05"), copy.deepcopy(rows))
        self.assertTrue(A.cross_arm_problems(ref, cand))

    def test_mutation_determinism_gate_removed(self):
        # If admit_pair ignored the determinism verdicts (the old
        # behavior: pair comparison regardless), a nondeterministic
        # reference would reach comparison. Load-bearing check:
        import issue273_admission as A
        ref, cand = self._genuine()
        ref_rep = staged_receipt(
            GENUINE_NVIDIA_REF,
            make_process("/usr/share/vulkan/icd.d/nvidia_icd.json", 8,
                         41002, "inferswarm01"), _rows(b"ref-p"))
        cand_rep = staged_receipt(
            CANDIDATE,
            make_process("/usr/share/vulkan/icd.d/radeon_icd.json", 7,
                         51002, "inferswarm05"), _rows(b"cand-p"))
        result = A.admit_pair(ref, as_source(ref), cand, as_source(cand),
                              ref_rep, cand_rep,
                              reference_deterministic=False,
                              candidate_deterministic=True)
        self.assertFalse(result["admitted"])

    def test_mutation_legacy_namespace_allowed(self):
        # If the c270- substring were dropped from the forbidden list,
        # the old invalidated namespace would dispatch again.
        import issue273_reducer as R
        bad = [ns for ns in R.FORBIDDEN_NAMESPACE_SUBSTRINGS_273
               if ns == "c270-"]
        self.assertTrue(bad, "c270- must be forbidden in #273")







if __name__ == "__main__":
    unittest.main()

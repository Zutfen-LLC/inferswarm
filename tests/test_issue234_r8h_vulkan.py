#!/usr/bin/env python3
"""Focused tests for Issue #234 corrected R8-H producers (schema /2).

Covers: corrected closure doctrine, freeze binding, raw-bytes reducer
(pairwise terminals, characterization gate, repeat integrity, ladder
prefix, geometry equality, authored-field immunity, retired terminal),
and the 36-control suite count/IDs. CPU-only; no physical execution.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import issue234_receipt as rc          # noqa: E402
import issue234_reduce as red          # noqa: E402
import issue234_assemble as asm        # noqa: E402


def w(p: Path, doc) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    return p


TOKENS_A = [561, 324, 55965, 51624, 29014, 271, 248068, 271]
TOKENS_C = [561, 324, 55965, 51624, 29014, 34227, 18030, 16382]


def make_evidence(tmp: Path, *, a=TOKENS_A, b=TOKENS_A, c=TOKENS_C,
                  det_b=True, characterization=None, case="case-256",
                  drop_b_repeat=False, extra_cases=(),
                  bdf_b="00000000:02:00.0") -> Path:
    ev = tmp / "evidence"
    authority = {
        "campaign": rc.CAMPAIGN_ID,
        "runtime_authority": {"llama_cpp_pin": rc.LLAMA_CPP_PIN},
        "fixture_ladder": {
            "sha256": rc.R8D_FIXTURE_SHA256,
            "prompt_lengths": {"case-256": 256, "case-1024": 1022,
                               "case-3072": 3077, "case-4096": 4097}},
        "model_authority": {
            "official_qwen_revision": rc.OFFICIAL_QWEN_REVISION,
            "unsloth_revision": rc.UNSLOTH_REVISION,
            "members": [dict(m) for m in rc.MODEL_MEMBERS]},
    }
    w(ev / "PHYSICAL-AUTHORITY.json", authority)
    for arm in "ABC":
        w(ev / "backing" / f"arm{arm}-backing.json", {
            "members": [dict(m, sha256_ok=True) for m in rc.MODEL_MEMBERS],
            "host": f"host{arm}"})
        w(ev / "runtime" / f"arm{arm}-runtime.json", {
            "source": {"revision": rc.LLAMA_CPP_PIN, "clean": True},
            "build": {"cmake_flags": {
                "GGML_CUDA": "ON" if arm == "A" else "OFF",
                "GGML_VULKAN": "OFF" if arm == "A" else "ON"}},
            "binaries": {"llama-server": {"sha256": f"{arm}" * 8}},
            "selector": {"target_bdf": bdf_b if arm == "B"
                         else ("00000000:02:00.0" if arm == "A"
                               else "00000000:06:00.0"),
                         "target_deviceUUID": "u" * 32,
                         "value": "0",
                         "value_semantics": "nvidia-smi index of frozen "
                                            "GPU (BDF "
                                            + (bdf_b if arm == "B"
                                               else "00000000:02:00.0")
                                            + ")"},
            "raw": {"list_devices_all": "Vulkan0: dev (8000 MiB)"}})
        w(ev / "placement" / f"arm{arm}-placement.json", {
            "loaded": True,
            "geometry": {"ngl": rc.MATCHED_NGL},
            "residency": {"selected": {"delta":
                                       {"mem_used_mib": 900}},
                          "excluded": {"x": {"mem_used_mib": 0}}},
            "post_exit": {"exit_code": 0}})
    gpu = {"host": "inferswarm01", "uuid": "GPU-x", "bdf": bdf_b,
           "cuda_identity": {"selector": "CUDA_VISIBLE_DEVICES=0"},
           "vulkan_identity": {"selector": "GGML_VK_VISIBLE_DEVICES=0"}}
    gpu_a = {"host": "inferswarm01", "uuid": "GPU-x",
             "bdf": "00000000:02:00.0",
             "cuda_identity": {"selector": "CUDA_VISIBLE_DEVICES=0"}}
    w(ev / "freeze" / "campaign-freeze.json", {
        "schema": "inferswarm.r8h.freeze/2",
        "campaign": rc.CAMPAIGN_ID,
        "llama_cpp_pin": rc.LLAMA_CPP_PIN,
        "request_contract": rc.REQUEST_CONTRACT,
        "fixture_sha256": rc.R8D_FIXTURE_SHA256,
        "ngl": rc.MATCHED_NGL,
        "context": rc.CONTEXT_SETTINGS,
        "model_members": [dict(m) for m in rc.MODEL_MEMBERS],
        "rtx3060": gpu,
        "arms": {
            "A": {"gpu": gpu_a, "ngl": 1, "context": rc.CONTEXT_SETTINGS,
                  "request": rc.REQUEST_CONTRACT,
                  "fixture_sha256": rc.R8D_FIXTURE_SHA256,
                  "model_sha256": [m["sha256"] for m in rc.MODEL_MEMBERS]},
            "B": {"gpu": gpu, "ngl": 1, "context": rc.CONTEXT_SETTINGS,
                  "request": rc.REQUEST_CONTRACT,
                  "fixture_sha256": rc.R8D_FIXTURE_SHA256,
                  "model_sha256": [m["sha256"] for m in rc.MODEL_MEMBERS]},
            "C": {"gpu": {"bdf": "00000000:06:00.0",
                          "deviceUUID": "d" * 32},
                  "excluded_die": {"bdf": "00000000:09:00.0"},
                  "ngl": 1, "context": rc.CONTEXT_SETTINGS,
                  "request": rc.REQUEST_CONTRACT,
                  "fixture_sha256": rc.R8D_FIXTURE_SHA256,
                  "model_sha256": [m["sha256"] for m in rc.MODEL_MEMBERS]},
        }})
    w(ev / "freeze" / "deployed-producers.json", {
        "producers": {rel: rc.digest_file(REPO / rel)
                      for rel in rc.PHYSICAL_PRODUCERS}})
    cases = [case] + list(extra_cases)
    for cs in cases:
        for arm, toks in (("A", a), ("B", b), ("C", c)):
            reps = []
            for i in (1, 2, 3):
                t = list(toks)
                if arm == "B" and not det_b and i == 2:
                    t[0] += 1
                reps.append({
                    "repeat": i,
                    "raw_response": {"tokens": t, "stop_type": "limit"},
                    "selected_residency": {
                        "pre": {"mem_used_mib": 900},
                        "post": {"mem_used_mib": 900}},
                    "excluded_residency": {"x": {
                        "pre": {"mem_used_mib": 0},
                        "post": {"mem_used_mib": 0}}},
                    "health_window": {"stop_classes": [],
                                      "correctable_rxerr_lines": 0}})
            if arm == "B" and drop_b_repeat:
                reps = reps[:2]
            w(ev / "candidate" / f"ladder-{arm}-{cs}.json", {
                "campaign": rc.CAMPAIGN_ID, "arm": arm, "case_id": cs,
                "geometry": {"ngl": rc.MATCHED_NGL,
                             "ctx": dict(rc.CONTEXT_SETTINGS),
                             "request": dict(rc.REQUEST_CONTRACT)},
                "fixture_sha256": rc.R8D_FIXTURE_SHA256,
                "prompt_len": {"case-256": 256, "case-1024": 1022,
                               "case-3072": 3077, "case-4096": 4097}[cs],
                "model_members": [m["member"] for m in rc.MODEL_MEMBERS],
                "repeats": reps,
                "post_exit": {"exit_code": 0,
                              "journal_final_stop_classes": []}})
    if characterization is not None:
        w(ev / "candidate" /
          f"score-characterization-{case}.json", characterization)
    return ev


def char_doc(case="case-256", pos=5) -> dict:
    return {
        "case_id": case, "generated_position": pos,
        "arms": {arm: {
            "top_k": [[271, 1, 16.7], [34227, 2, 16.0]],
            "non_perturbation_identical": True}
            for arm in "ABC"},
        "sidecar_sha256": "s" * 64}


CLOSURE = {"schema": "inferswarm.r8h.producer-closure/2",
           "producer_head": "p" * 40,
           "closure_digest": "c" * 64, "sources": {}}


class TestReducerTerminals(unittest.TestCase):
    def test_backend_divergence_with_characterization(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t), b=TOKENS_C, c=TOKENS_C,
                               characterization=char_doc())
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"],
                             red.TERMINAL_BACKEND_DIV)
            self.assertEqual(doc["pairwise_map"]["case-256"],
                             "BACKEND_DIVERGENT")

    def test_divergence_without_characterization_blocks(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_BLOCKED)
            self.assertIn("score characterization",
                          " ".join(doc["terminal_basis"]))

    def test_device_divergence(self):
        with tempfile.TemporaryDirectory() as t:
            # defaults: A==B (both TOKENS_A), B!=C -> device-divergent
            ev = make_evidence(Path(t), characterization=char_doc())
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_DEVICE_DIV)

    def test_multi_axis(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t), b=[9] * 8,
                               characterization=char_doc())
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_MULTI_AXIS)

    def test_parity_all_rungs_pass(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t), a=TOKENS_A, b=TOKENS_A, c=TOKENS_A,
                               extra_cases=("case-1024", "case-3072",
                                            "case-4096"))
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_PARITY_PASS)

    def test_parity_incomplete_ladder_blocks(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t), a=TOKENS_A, b=TOKENS_A, c=TOKENS_A)
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_BLOCKED)

    def test_repeat_drop_blocks(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t), drop_b_repeat=True,
                               characterization=char_doc())
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_BLOCKED)
            self.assertTrue(any("incomplete repeats" in x
                                for x in doc["terminal_basis"]))

    def test_nondeterminism_blocks(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t), det_b=False,
                               characterization=char_doc())
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_BLOCKED)
            self.assertTrue(any("nondeterministic" in x
                                for x in doc["terminal_basis"]))

    def test_ladder_prefix_violation_raises(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t), case="case-1024")
            with self.assertRaises(red.ReduceError):
                red.derive_terminal(ev, closure=CLOSURE)

    def test_geometry_drift_raises(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            p = ev / "candidate" / "ladder-B-case-256.json"
            d = json.loads(p.read_text())
            d["geometry"]["ngl"] = 99
            p.write_text(json.dumps(d))
            with self.assertRaises(red.ReduceError):
                red.derive_terminal(ev, closure=CLOSURE)

    def test_authored_status_ignored(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            for arm in "ABC":
                p = ev / "candidate" / f"ladder-{arm}-case-256.json"
                d = json.loads(p.read_text())
                d["status"] = "PASS_ALL_EQUAL"
                for r in d["repeats"]:
                    r["comparison"] = {"exact": True}
                p.write_text(json.dumps(d))
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_BLOCKED)

    def test_legacy_greedy_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            for arm in "ABC":
                p = ev / "candidate" / f"ladder-{arm}-case-256.json"
                d = json.loads(p.read_text())
                d["geometry"]["request"]["samplers"] = ["greedy"]
                p.write_text(json.dumps(d))
            with self.assertRaises(red.ReduceError):
                red.derive_terminal(ev, closure=CLOSURE)

    def test_retired_terminal_never_emitted(self):
        self.assertNotIn(red.RETIRED_TERMINAL, red.ALL_TERMINALS)


class TestControlSuite(unittest.TestCase):
    def test_count_and_ids(self):
        self.assertEqual(len(asm.CONTROLS), 36)
        self.assertEqual(sorted(asm.CONTROLS), list(range(1, 37)))

    def test_controls_run_all_ok_on_divergent_evidence(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t), characterization=char_doc())
            receipt = asm.run_controls(ev, CLOSURE)
            self.assertEqual(receipt["count"], 36)
            self.assertTrue(receipt["all_ok"])
            self.assertEqual(receipt["control_ids"], list(range(1, 37)))
            bad = {k: v for k, v in receipt["controls"].items()
                   if not v["ok"]}
            self.assertEqual(bad, {}, f"failing controls: {bad}")

    def test_deployed_hash_mismatch_fails(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            p = ev / "freeze" / "deployed-producers.json"
            d = json.loads(p.read_text())
            k = next(iter(d["producers"]))
            d["producers"][k] = "0" * 64
            p.write_text(json.dumps(d))
            with mock.patch.object(rc, "verify_closure",
                                   return_value=CLOSURE):
                with self.assertRaises(asm.AssembleError):
                    asm.assemble(ev, repo=REPO)


class TestClosureDoctrine(unittest.TestCase):
    def test_closure_document_blobs(self):
        doc = rc.closure_document(REPO)
        self.assertEqual(doc["schema"],
                         "inferswarm.r8h.producer-closure/2")
        self.assertEqual(len(doc["sources"]), len(rc.CLOSURE_SOURCES))
        n_phys = sum(1 for v in doc["sources"].values()
                     if v["class"] == "physical")
        self.assertEqual(n_phys, len(rc.PHYSICAL_PRODUCERS))

    def test_freeze_binding_rejects_gpu_mismatch(self):
        gpu = {"host": "h", "uuid": "GPU-x", "bdf": "02:00.0",
               "cuda_identity": "c", "vulkan_identity": "v"}
        common = {"ngl": 1, "context": rc.CONTEXT_SETTINGS,
                  "request": rc.REQUEST_CONTRACT,
                  "fixture_sha256": rc.R8D_FIXTURE_SHA256,
                  "model_sha256": [m["sha256"] for m in rc.MODEL_MEMBERS]}
        doc = {"schema": "inferswarm.r8h.freeze/2",
               "campaign": rc.CAMPAIGN_ID,
               "llama_cpp_pin": rc.LLAMA_CPP_PIN,
               "request_contract": rc.REQUEST_CONTRACT,
               "fixture_sha256": rc.R8D_FIXTURE_SHA256,
               "ngl": rc.MATCHED_NGL, "context": rc.CONTEXT_SETTINGS,
               "model_members": [dict(m) for m in rc.MODEL_MEMBERS],
               "rtx3060": gpu,
               "arms": {"A": {**common, "gpu": gpu},
                        "B": {**common, "gpu": dict(gpu,
                                                    uuid="GPU-OTHER")},
                        "C": {**common,
                              "gpu": {"bdf": "06:00.0",
                                      "deviceUUID": "d"},
                              "excluded_die": {"bdf": "09:00.0"}}}}
        with self.assertRaises(rc.FreezeError):
            rc.verify_freeze_binding(doc)


class TestGeometry(unittest.TestCase):
    def test_context_settings_batch_flag(self):
        self.assertIn("batch-size", rc.CONTEXT_SETTINGS)
        self.assertNotIn("batch", rc.CONTEXT_SETTINGS)

    def test_repeat_ids(self):
        self.assertEqual(rc.REQUIRED_REPEAT_IDS, (1, 2, 3))


if __name__ == "__main__":
    unittest.main()

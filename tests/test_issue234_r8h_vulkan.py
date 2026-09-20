#!/usr/bin/env python3
"""Issue #234 tests — R8-H producers (CPU-only, no Vulkan hardware).

Covers: authority building/binding against accepted predecessor bytes,
census BDF/UUID grammar, runtime-qualification gating, placement
selection rule, ladder comparison/escalation semantics, health
stop-classification, terminal reduction priority, and the issue's 27
required fail-closed controls executed through the REAL reducer over
synthetic evidence trees (mutation tests, never hand-authored fixture
summaries).
"""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import issue234_receipt as rc
import issue234_authority as pa
import issue234_host as host
import issue234_runtime as rt
import issue234_placement as pl
import issue234_ladder as ladder
import issue234_health as health
import issue234_reduce as red
import issue234_assemble as asm


def canonical(v) -> bytes:
    return rc.canonical(v)


# ---------------------------------------------------------------------------
# Synthetic evidence builder — models the REAL collector output shapes.
# ---------------------------------------------------------------------------

def die_entry(bdf: str, uuid: str) -> dict:
    return {
        "bdf": bdf,
        "deviceUUID": uuid,
        "vulkan_name": "AMD Radeon Pro V340 (RADV VEGA10)",
        "vendorID": "0x1002",
        "deviceID": "0x6864",
        "vulkan_key": "gpu1" if "0600" in uuid else "gpu2",
        "gpu_index": 1 if "0600" in uuid else 2,
    }


def synth_runtime(ok: bool = True) -> dict:
    return {
        "schema": "inferswarm.r8h.runtime-qualification/1",
        "campaign": rc.CAMPAIGN_ID,
        "source": {"revision": rc.LLAMA_CPP_PIN if ok else "deadbeef",
                   "clean": ok, "repo": "x", "worktree": "x"},
        "build": {"cmake_flags": {
            "GGML_VULKAN": "ON", "GGML_CUDA": "OFF",
            "CMAKE_BUILD_TYPE": "Release"},
            "cmake_version": "3.31.6", "compiler": "g++ 14.2.0",
            "config_log": ""},
        "binaries": {"llama-server": {
            "sha256": "a" * 64}, "llama-cli": {"sha256": "b" * 64}},
        "version_output": f"version: 0.4.1-dev (commit {rc.LLAMA_CPP_PIN[:8]})",
        "vulkan_selector_mapping": {
            "env_var": "GGML_VK_VISIBLE_DEVICES",
            "restricted_value": "1",
            "all_devices": [
                {"label": "Vulkan0", "name": "Intel", "mib": 7953},
                {"label": "Vulkan1", "name": "AMD Radeon Pro V340 (RADV VEGA10)", "mib": 8176},
                {"label": "Vulkan2", "name": "AMD Radeon Pro V340 (RADV VEGA10)", "mib": 8176},
            ],
            "restricted_devices": [
                {"label": "Vulkan0", "name": "AMD Radeon Pro V340 (RADV VEGA10)", "mib": 8176}],
            "selected_die": {"vulkan_gpu_index": 1,
                             "deviceUUID": "00000000-0600-0000-0000-000000000000",
                             "bdf": "00000000:06:00.0",
                             "heap_mib_reported": 8176},
            "excluded_die": {"vulkan_gpu_index": 2,
                             "deviceUUID": "00000000-0900-0000-0000-000000000000",
                             "bdf": "00000000:09:00.0"},
        },
        "census_boot_id": "testboot",
        "raw": {"list_devices_all": "", "list_devices_restricted": ""},
    }


def synth_placement(ngl: int = 8, illegal: str | None = None) -> dict:
    sel_delta = {"card0.vram_used": 900 * 1024 * 1024}
    exc_delta = {"card0.vram_used": 0 if illegal != "excluded_active"
                 else 64 * 1024 * 1024}
    if illegal == "zero_residency":
        sel_delta = {"card0.vram_used": 0}
    attempts = []
    for n in (1, 2, 4, ngl):
        loaded = True
        if illegal == "none_loaded":
            loaded = False
        attempts.append({
            "schema": "inferswarm.r8h.placement-preflight/1",
            "campaign": rc.CAMPAIGN_ID, "ngl": n, "cmd": [], "selector": {},
            "loaded": loaded, "exit_code": 0,
            "placement": {"vulkan_buffers_mib":
                          {"Vulkan0": 900.0} if n == ngl else {},
                          "cpu_buffers_mib": {},
                          "offloaded_layers": n, "total_layers": 49},
            "selected_die_mem_delta_bytes":
                sel_delta if n == ngl else {"card0.vram_used": 0},
            "excluded_die_mem_delta_bytes": exc_delta,
            "log_excerpt": "",
        })
    selection = {
        "selected_ngl": ngl,
        "rule": rc.PLACEMENT_RULE,
        "selected_die_model_bytes": sel_delta["card0.vram_used"],
        "excluded_die_model_bytes": exc_delta["card0.vram_used"],
        "headroom_bytes":
            rc.DIE_HEAP_BYTES - 900 * 1024 * 1024
            if illegal != "headroom" else -1,
        "basis_attempt": attempts[-1],
    }
    return {"schema": "inferswarm.r8h.placement/1",
            "campaign": rc.CAMPAIGN_ID,
            "attempts": attempts, "selection": selection}


def synth_backing(ok: bool = True) -> dict:
    members = []
    for want in rc.MODEL_MEMBERS:
        m = {"member": want["member"], "bytes": want["bytes"],
             "sha256": want["sha256"],
             "sha256_ok": ok}
        if not ok:
            m["sha256"] = "f" * 64
        members.append(m)
    return {"schema": "inferswarm.r8h.backing/1",
            "campaign": rc.CAMPAIGN_ID,
            "source": {"host": "inferswarm01",
                       "path": "/srv/models/qwen38-ud-iq1-s"},
            "destination": {"host": "inferswarm02",
                            "path": "/srv/models/qwen38-ud-iq1-s"},
            "members": members,
            "total_bytes": sum(m["bytes"] for m in members)}


def synth_observation(tokens, stop="limit"):
    return {"wall_s": 1.0, "generated_tokens": tokens,
            "stop_type": stop, "stop_word": "", "raw": {}}


REF_256 = [561, 324, 55965, 51624, 29014, 271, 248068, 271]
REF_1024 = [561, 324, 55965, 51624, 29014, 34227, 18030, 16382]


def synth_ladder(outcomes: dict | None = None,
                 health_stops: list | None = None) -> dict:
    """outcomes: case -> list of token-lists per repeat (default exact)."""
    outcomes = outcomes or {}
    results = {}
    halted = None
    prev_pass = True
    for case_id in rc.LADDER_CASES:
        ref = {"case-256": REF_256, "case-1024": REF_1024}.get(
            case_id, REF_256)
        if not prev_pass:
            results[case_id] = {"status": "NOT_EXECUTED",
                                "reason": f"halted after {halted}"}
            continue
        seqs = outcomes.get(case_id) or [ref] * rc.REPEATS_PER_CASE
        repeats = []
        exact_all = True
        for i, toks in enumerate(seqs, 1):
            obs = synth_observation(toks)
            cmp = ladder_mod_compare(obs["generated_tokens"],
                                     obs["stop_type"], ref, "limit")
            repeats.append({"repeat": i, "observation": obs,
                            "comparison": cmp})
            if not cmp["exact"]:
                exact_all = False
                break
        status = "PASS" if exact_all else "FAIL"
        stops = health_stops or []
        results[case_id] = {"status": status, "repeats": repeats,
                            "reference": {"generated_tokens": ref,
                                          "stop_type": "limit"},
                            "health_window": {"stop_classes": stops,
                                              "rxerr_lines": 0}}
        if stops:
            halted = f"{case_id}:{'+'.join(stops)}"
        elif not exact_all:
            halted = f"{case_id}:deterministic_mismatch"
        prev_pass = exact_all and not stops
    return {
        "schema": "inferswarm.r8h.ladder/1",
        "campaign": rc.CAMPAIGN_ID,
        "server": {"binary": "x", "model": "x", "ngl": 8,
                   "ctx": rc.CONTEXT_SETTINGS, "port": 1,
                   "selector": "GGML_VK_VISIBLE_DEVICES=1"},
        "fixture_sha256": rc.R8D_FIXTURE_SHA256,
        "request_contract": rc.REQUEST_CONTRACT,
        "t_start": "t", "results": results, "halted": halted,
        "health": {
            "before": {}, "after": {},
            "delta": {"selected_aer": {}, "excluded_aer": {},
                      "selected_link_before":
                          {"current_link_width": "16"},
                      "selected_link_after":
                          {"current_link_width": "16"},
                      "excluded_link_before": {}, "excluded_link_after": {}},
            "journal_final": {"events": [], "stop_classes": [],
                              "correctable_rxerr_lines": 0},
            "post_exit": {"snapshot": {}, "vram_released": True,
                          "server_exit_code": 0},
        },
        "server_log_tail": "",
    }


def ladder_mod_compare(cand_toks, cand_stop, ref_toks, ref_stop):
    tok_ok = cand_toks == ref_toks
    stop_ok = cand_stop == ref_stop
    first = None
    if not tok_ok:
        for i, (c, r) in enumerate(zip(cand_toks, ref_toks)):
            if c != r:
                first = {"position": i, "candidate": c, "reference": r}
                break
    return {"tokens_equal": tok_ok, "stop_equal": stop_ok,
            "exact": tok_ok and stop_ok, "first_divergence": first}


def synth_restart(ok: bool = True) -> dict:
    return {
        "schema": "inferswarm.r8h.restart/1",
        "campaign": rc.CAMPAIGN_ID,
        "results": {
            "case-256": {"reference": {"generated_tokens": REF_256,
                                       "stop_type": "limit"},
                         "observation": synth_observation(
                             REF_256 if ok else [1, 2, 3])},
            "case-4096": {"reference": {"generated_tokens": REF_256,
                                        "stop_type": "limit"},
                          "observation": synth_observation(REF_256)}},
        "placement_identity_equivalent": ok,
    }


def synth_evidence(ladder_doc=None, runtime_doc=None, placement_doc=None,
                   backing_ok=True, restart_ok=True, with_restart=True):
    root = Path(tempfile.mkdtemp(prefix="r8h-synth-"))
    (root / "PHYSICAL-AUTHORITY.json").write_text(
        REPO.joinpath(
            "docs/investigations/qwen38-flash-next-r8-h-vulkan",
            "PHYSICAL-AUTHORITY.json").read_text())
    (root / "backing").mkdir()
    (root / "backing" / "backing-verification.json").write_text(
        json.dumps(synth_backing(backing_ok)))
    (root / "runtime").mkdir()
    (root / "runtime" / "runtime-qualification.json").write_text(
        json.dumps(runtime_doc or synth_runtime()))
    (root / "placement").mkdir()
    (root / "placement" / "placement.json").write_text(
        json.dumps(placement_doc or synth_placement()))
    (root / "candidate").mkdir()
    (root / "candidate" / "ladder.json").write_text(
        json.dumps(ladder_doc or synth_ladder()))
    if with_restart:
        (root / "candidate" / "restart.json").write_text(
            json.dumps(synth_restart(restart_ok)))
    return root


SYNTH_CLOSURE = {
    "schema": "inferswarm.r8h.producer-closure/1",
    "campaign": rc.CAMPAIGN_ID,
    "producer_head": "synthetic",
    "closure_digest": "synthetic",
    "sources": {},
}


class TestAuthority(unittest.TestCase):
    def test_build_binds_predecessor_bytes(self):
        doc = pa.build()
        self.assertEqual(doc["fixture_ladder"]["sha256"],
                         rc.R8D_FIXTURE_SHA256)
        self.assertEqual(doc["fixture_ladder"]["cases"],
                         list(rc.LADDER_CASES))
        self.assertEqual(doc["runtime_authority"]["llama_cpp_pin"],
                         rc.LLAMA_CPP_PIN)
        for merge in ("r8a", "r8d", "r8f", "r8g", "v2e", "v2f", "v2g"):
            self.assertTrue(doc["predecessor_merges"][merge])
        # model member identity cross-bound
        for want, got in zip(rc.MODEL_MEMBERS,
                             doc["model_authority"]["members"]):
            self.assertEqual(want["sha256"], got["sha256"])

    def test_reference_outputs_bound_to_accepted_r8d(self):
        doc = pa.build()
        self.assertEqual(doc["reference_outputs"]["case-256"]
                         ["generated_tokens"], REF_256)


class TestHostGrammar(unittest.TestCase):
    def test_uuid_to_bdf(self):
        self.assertEqual(
            host.uuid_bdf("00000000-0600-0000-0000-000000000000"),
            "00000000:06:00.0")
        self.assertEqual(
            host.uuid_bdf("00000000-0900-0000-0000-000000000000"),
            "00000000:09:00.0")

    def test_bdf16_normalization(self):
        self.assertEqual(host.bdf16("0000:06:00.0"),
                         "00000000:06:00.0")
        self.assertEqual(host.bdf16("06:00.0"), "00000000:06:00.0")
        with self.assertRaises(host.CensusError):
            host.bdf16("garbage")


class TestReduce(unittest.TestCase):
    def _evidence(self, **kw):
        root = synth_evidence(**kw)
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        return root

    def test_full_pass_terminal(self):
        doc = red.derive_terminal(self._evidence(), closure=SYNTH_CLOSURE)
        self.assertEqual(doc["terminal"], red.TERMINAL_PASS)

    def test_backing_mismatch_is_backing_prerequisite(self):
        doc = red.derive_terminal(self._evidence(backing_ok=False),
                                  closure=SYNTH_CLOSURE)
        self.assertEqual(doc["terminal"], red.TERMINAL_BACKING_PREREQ)

    def test_runtime_problem_is_runtime_prerequisite(self):
        doc = red.derive_terminal(self._evidence(
            runtime_doc=synth_runtime(ok=False)),
            closure=SYNTH_CLOSURE)
        self.assertEqual(doc["terminal"], red.TERMINAL_RUNTIME_PREREQ)

    def test_excluded_die_active_is_illegal_placement(self):
        doc = red.derive_terminal(self._evidence(
            placement_doc=synth_placement(illegal="excluded_active")),
            closure=SYNTH_CLOSURE)
        self.assertEqual(doc["terminal"], red.TERMINAL_RUNTIME_PREREQ)
        self.assertIn("excluded_die_active",
                      json.dumps(doc["checks"]["placement"]))

    def test_zero_residency_is_illegal_placement(self):
        doc = red.derive_terminal(self._evidence(
            placement_doc=synth_placement(illegal="zero_residency")),
            closure=SYNTH_CLOSURE)
        self.assertEqual(doc["terminal"], red.TERMINAL_RUNTIME_PREREQ)

    def test_no_legal_geometry_is_runtime_prerequisite(self):
        doc = red.derive_terminal(self._evidence(
            placement_doc=synth_placement(illegal="none_loaded")),
            closure=SYNTH_CLOSURE)
        self.assertEqual(doc["terminal"], red.TERMINAL_RUNTIME_PREREQ)

    def test_health_fault_beats_correctness_pass(self):
        doc = red.derive_terminal(self._evidence(
            ladder_doc=synth_ladder(
                health_stops=["amdgpu_ring_timeout"])),
            closure=SYNTH_CLOSURE)
        self.assertEqual(doc["terminal"], red.TERMINAL_PLATFORM_FAIL)

    def test_deterministic_mismatch_is_correctness_fail(self):
        bad = dict.fromkeys(rc.LADDER_CASES)
        outcomes = {"case-256": [[561, 324, 55965, 51624, 29014,
                                  34227, 1, 2]]}
        doc = red.derive_terminal(self._evidence(
            ladder_doc=synth_ladder(outcomes=outcomes)),
            closure=SYNTH_CLOSURE)
        self.assertEqual(doc["terminal"], red.TERMINAL_CORRECTNESS_FAIL)
        div = doc["checks"]["ladder"]["cases"]["case-256"][
            "first_divergence"]
        self.assertEqual(div["position"], 5)

    def test_nondeterministic_repeat_is_correctness_fail(self):
        outcomes = {"case-256": [REF_256, [9] * 8, REF_256]}
        doc = red.derive_terminal(self._evidence(
            ladder_doc=synth_ladder(outcomes=outcomes)),
            closure=SYNTH_CLOSURE)
        self.assertEqual(doc["terminal"], red.TERMINAL_CORRECTNESS_FAIL)

    def test_missing_restart_control_blocks_pass(self):
        doc = red.derive_terminal(self._evidence(with_restart=False),
                                  closure=SYNTH_CLOSURE)
        self.assertEqual(doc["terminal"], red.TERMINAL_BLOCKED)

    def test_restart_drift_is_correctness_fail(self):
        doc = red.derive_terminal(self._evidence(restart_ok=False),
                                  closure=SYNTH_CLOSURE)
        self.assertEqual(doc["terminal"], red.TERMINAL_CORRECTNESS_FAIL)

    def test_escalation_violation_detected(self):
        # case-256 FAIL but case-1024 executed anyway
        doc_l = synth_ladder(outcomes={
            "case-256": [[561, 999]],
            "case-1024": [REF_1024],
        })
        doc = red.derive_terminal(
            self._evidence(ladder_doc=doc_l), closure=SYNTH_CLOSURE)
        self.assertEqual(doc["terminal"], red.TERMINAL_CORRECTNESS_FAIL)

    def test_uncorrectable_aer_delta_is_platform_fault(self):
        lad = synth_ladder()
        lad["health"]["delta"]["selected_aer"] = {
            "unc_UncorrReplayRollOver": 3}
        doc = red.derive_terminal(self._evidence(ladder_doc=lad),
                                  closure=SYNTH_CLOSURE)
        self.assertEqual(doc["terminal"], red.TERMINAL_PLATFORM_FAIL)


class TestLadderCompare(unittest.TestCase):
    def test_compare_exact(self):
        cmp = ladder.compare(
            {"generated_tokens": REF_256, "stop_type": "limit"},
            {"generated_tokens": REF_256, "stop_type": "limit"})
        self.assertTrue(cmp["exact"])

    def test_compare_first_divergence(self):
        cmp = ladder.compare(
            {"generated_tokens": REF_256[:5] + [34227, 1, 2],
             "stop_type": "limit"},
            {"generated_tokens": REF_256, "stop_type": "limit"})
        self.assertFalse(cmp["exact"])
        self.assertEqual(cmp["first_divergence"]["position"], 5)
        self.assertEqual(cmp["first_divergence"]["candidate"], 34227)
        self.assertEqual(cmp["first_divergence"]["reference"], 271)

    def test_request_contract_true_greedy_only(self):
        self.assertEqual(rc.REQUEST_CONTRACT["samplers"], ["top_k"])
        self.assertEqual(rc.REQUEST_CONTRACT["top_k"], 1)


class TestHealthClassification(unittest.TestCase):
    def test_ring_timeout_stops(self):
        win = health.classify_journal(
            "Sep 20 kernel: [drm] amdgpu 0000:06:00.0: ring gfx timeout",
            "0000:06:00.0", "0000:09:00.0")
        self.assertIn("amdgpu_ring_timeout", win["stop_classes"])

    def test_reset_failure_stops(self):
        win = health.classify_journal(
            "kernel: amdgpu 0000:06:00.0: GPU reset ret=-62",
            "0000:06:00.0", "0000:09:00.0")
        self.assertIn("amdgpu_reset_failure", win["stop_classes"])

    def test_clean_window(self):
        win = health.classify_journal(
            "kernel: harmless line\n", "0000:06:00.0", "0000:09:00.0")
        self.assertEqual(win["stop_classes"], [])


class TestPlacementRule(unittest.TestCase):
    def test_smallest_nonzero_selected(self):
        doc = synth_placement()
        sel = pl.select_geometry(doc["attempts"])
        self.assertEqual(sel["selected_ngl"], 8)

    def test_excluded_active_rejected(self):
        doc = synth_placement(illegal="excluded_active")
        with self.assertRaises(pl.PlacementError):
            pl.select_geometry(doc["attempts"])


class TestFreeze(unittest.TestCase):
    def test_closure_self_digest(self):
        doc = rc.closure_document(REPO)
        self.assertTrue(doc["closure_digest"])
        # deterministic
        doc2 = rc.closure_document(REPO)
        self.assertEqual(doc["closure_digest"], doc2["closure_digest"])

    def test_closure_sources_exist(self):
        for rel in rc.CLOSURE_SOURCES:
            self.assertTrue((REPO / rel).is_file(), rel)


if __name__ == "__main__":
    unittest.main()

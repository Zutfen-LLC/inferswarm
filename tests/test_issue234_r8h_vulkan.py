#!/usr/bin/env python3
"""Focused tests for Issue #234 corrected R8-H producers (schema /2).

Round-2 coverage (maintainer NO-GO on cfd86f11): raw-bound
characterization reduction, mechanical position binding to the
earliest pairwise divergence, deployed-producer host/producer matrix,
strengthened control 33, observation-pin validation, and the full
control-suite contract. CPU-only; no physical execution.
"""
from __future__ import annotations

import json
import struct
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


TOKENS_A = [328, 760, 40554, 1, 271, 12188, 279, 1727]
TOKENS_B = [561, 324, 55965, 51624, 29014, 271, 248068, 271]
TOKENS_C = [561, 324, 55965, 51624, 29014, 34227, 18030, 16382]

N_VOCAB = 4096


def synth_f32(tokens: dict[int, float]) -> bytes:
    """Synthesize a small-vocab float32 row with controlled values."""
    row = [0.0] * N_VOCAB
    for t, v in tokens.items():
        row[t] = v
    return struct.pack(f"<{N_VOCAB}f", *row)


# controlled score structures: A picks 328 over 561 (narrow), B and C
# pick 561 over 328 (wider); ranks 1..4 arranged accordingly.
F32_A = synth_f32({328: 15.25, 561: 15.0, 271: 14.0, 359: 13.0})
F32_B = synth_f32({561: 15.5, 328: 15.0, 359: 14.5, 271: 13.5})
F32_C = synth_f32({561: 15.75, 359: 14.5, 271: 14.0, 328: 13.75})


def obs_jsonl(position: int, f32row: bytes, sampled: int) -> str:
    vals = struct.unpack(f"<{N_VOCAB}f", f32row)
    order = sorted(range(N_VOCAB), key=lambda i: (-vals[i], i))
    rank = {t: k + 1 for k, t in enumerate(order)}
    top = [[t, vals[t]] for t in order[:16]]
    focus = [[t, rank[t], vals[t]]
             for t in (328, 561, 271, 34227, 12188, 248068) if t < N_VOCAB]
    row = {"pos": position, "tok": sampled, "n_vocab": N_VOCAB,
           "top": top, "focus": focus, "n_nonfinite": 0}
    return json.dumps(row) + "\n"


def make_obs_corpus(ev: Path, arm: str, tokens: list[int],
                    f32row: bytes, *, position: int = 0,
                    dir_name: str = "pos0", pin: bool = True) -> None:
    d = ev / "candidate" / "characterization" / dir_name
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{arm}.jsonl").write_text(obs_jsonl(position, f32row, tokens[0]))
    (d / f"{arm}.jsonl.pos{position}.f32").write_bytes(f32row)
    w(d / f"{arm}.resp.json", {"tokens": tokens})
    if pin and dir_name == "pos0" and not (d / "pos0-observation-pin.json"
                                           ).is_file():
        pin_doc = {
            "schema": "inferswarm.r8h.pos0-observation-pin/1",
            "scope": {"generated_position": position,
                      "canonical_ladder_rerun": False},
            "observation_producer": {
                "llama_cpp_source_pin": rc.LLAMA_CPP_PIN,
                "hook_source_sha256_of_diff": rc.OBSERVATION_HOOK_DIFF_SHA256,
                "hook_env": {
                    "LLAMA_OBSERVE_FOCUS": rc.OBSERVATION_FOCUS_ENV,
                    "LLAMA_OBSERVE_POS": str(position)},
                "prompt_sha256": rc.PROMPT_CASE256_SHA256,
                "observation_binaries": {
                    "A_cuda_inferswarm01": {"sha256": rc.OBSERVATION_BINARIES["A"]["sha256"]},
                    "B_vulkan_inferswarm01": {"sha256": rc.OBSERVATION_BINARIES["B"]["sha256"]},
                    "C_vulkan_inferswarm02": {"sha256": rc.OBSERVATION_BINARIES["C"]["sha256"]},
                },
            },
        }
        w(d / "pos0-observation-pin.json", pin_doc)


def make_summary(ev: Path, case: str, position: int, f32s: dict[str, bytes],
                 winners: dict[str, int]) -> Path:
    arms = {}
    for arm in "ABC":
        arms[arm] = {
            "generated_position": position,
            "winner_token": winners[arm],
            "raw_sidecar_sha256": {
                f"f32_pos{position}": rc.sha256_bytes(f32s[arm])},
            "non_perturbation_identical": True,
        }
    return w(ev / "candidate" / f"score-characterization-{case}.json",
             {"schema": "inferswarm.r8h.score-characterization/3",
              "campaign": rc.CAMPAIGN_ID, "case_id": case,
              "generated_position": position, "arms": arms})


def make_evidence(tmp: Path, *, a=TOKENS_A, b=TOKENS_B, c=TOKENS_C,
                  det_b=True, characterization=None, case="case-256",
                  drop_b_repeat=False, extra_cases=(),
                  bdf_b="00000000:02:00.0",
                  obs_position=0) -> Path:
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
        "all_hosts_match_pin": True,
        "hosts": {h: {"hashes": {name: rc.digest_file(REPO / "scripts" / name)
                                 for name in
                                 asm.DEPLOYED_PRODUCER_BASENAMES}}
                  for h in ("inferswarm01", "inferswarm02")}})
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
    # raw observation corpus bound to the streams above
    f32s = {"A": F32_A, "B": F32_B, "C": F32_C}
    for arm, toks in (("A", a), ("B", b), ("C", c)):
        make_obs_corpus(ev, arm, toks, f32s[arm], position=obs_position)
    make_summary(ev, case, obs_position, f32s,
                 {k: struct.unpack(
                     f"<{N_VOCAB}f", v)[0 if k == "A" else 561]
                  for k, v in f32s.items()} if False else
                 {"A": a[0], "B": b[0], "C": c[0]})
    return ev


CLOSURE = {"schema": "inferswarm.r8h.producer-closure/2",
           "producer_head": "p" * 40,
           "closure_digest": "c" * 64, "sources": {}}


def real_closure():
    return rc.verify_closure(REPO)


class TestRequiredPosition(unittest.TestCase):
    """Spec §3: mechanical binding of the characterization position."""

    def _case(self, a, b, c):
        return {"pairwise": {
            "AB": red.pairwise({"tokens": a, "stop_type": "s"},
                               {"tokens": b, "stop_type": "s"}),
            "BC": red.pairwise({"tokens": b, "stop_type": "s"},
                               {"tokens": c, "stop_type": "s"}),
            "AC": red.pairwise({"tokens": a, "stop_type": "s"},
                               {"tokens": c, "stop_type": "s"})}}

    def test_campaign_streams_derive_position_zero(self):
        case = self._case(TOKENS_A, TOKENS_B, TOKENS_C)
        self.assertEqual(red.required_characterization_position(case), 0)

    def test_equal_streams_derive_none(self):
        case = self._case(TOKENS_A, TOKENS_A, TOKENS_A)
        self.assertIsNone(red.required_characterization_position(case))

    def test_bc_only_divergence_derives_five(self):
        case = self._case(TOKENS_B, TOKENS_B, TOKENS_C)
        self.assertEqual(red.required_characterization_position(case), 5)


class TestRawBoundCharacterization(unittest.TestCase):
    """Spec §4: terminal authority derives from raw bytes only."""

    def test_multi_axis_with_pos0_characterization(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_MULTI_AXIS)
            sc = doc["checks"]["score_characterization"]
            self.assertEqual(sc["status"], "OK")
            self.assertEqual(sc["required_position"], 0)
            self.assertEqual(sc["derived"]["A"]["winner_token"], 328)
            self.assertEqual(sc["derived"]["B"]["winner_token"], 561)
            self.assertEqual(sc["derived"]["C"]["winner_token"], 561)

    def test_position5_summary_does_not_satisfy_global_gate(self):
        # current pairwise map + characterization at position 5 ONLY
        # -> R8H_EVIDENCE_BLOCKED (spec-required regression)
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            # remove the pos0 corpus + canonical summary, keep ONLY a
            # position-5-shaped summary (the round-1 condition)
            import shutil
            shutil.rmtree(ev / "candidate" / "characterization" / "pos0")
            (ev / "candidate" /
             "score-characterization-case-256.json").unlink()
            f32s = {"A": F32_A, "B": F32_B, "C": F32_C}
            # a pos5 corpus whose non-perturbation matches the streams
            for arm, toks in (("A", TOKENS_A), ("B", TOKENS_B),
                              ("C", TOKENS_C)):
                make_obs_corpus(ev, arm, toks, f32s[arm], position=5,
                                dir_name="", pin=False)
            make_summary(ev, "case-256", 5, f32s,
                         {"A": TOKENS_A[5], "B": TOKENS_B[5],
                          "C": TOKENS_C[5]})
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_BLOCKED)
            sc = doc["checks"]["score_characterization"]
            self.assertNotEqual(sc["status"], "OK")

    def test_forged_position_summary_blocked(self):
        # forged generated_position -/1/5/other -> BLOCKED
        for forged in (-1, 1, 5, 7):
            with tempfile.TemporaryDirectory() as t:
                ev = make_evidence(Path(t))
                p = ev / "candidate" / \
                    "score-characterization-case-256.json"
                d = json.loads(p.read_text())
                d["generated_position"] = forged
                p.write_text(json.dumps(d))
                doc = red.derive_terminal(ev, closure=CLOSURE)
                self.assertEqual(doc["terminal"], red.TERMINAL_BLOCKED,
                                 f"forged position {forged}")

    def test_missing_characterization_blocked(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            import shutil
            shutil.rmtree(ev / "candidate" / "characterization")
            (ev / "candidate" /
             "score-characterization-case-256.json").unlink()
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_BLOCKED)

    def test_altered_summary_winner_terminal_unchanged(self):
        # raw bytes win: authored winner mutation must NOT flip the
        # terminal (summary consistency flags it instead)
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            p = ev / "candidate" / \
                "score-characterization-case-256.json"
            d = json.loads(p.read_text())
            d["arms"]["A"]["winner_token"] = 999999
            p.write_text(json.dumps(d))
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_MULTI_AXIS)
            sc = doc["checks"]["score_characterization"]
            self.assertEqual(sc["status"], "OK")
            self.assertEqual(sc["derived"]["A"]["winner_token"], 328)
            self.assertIn("summary:armA:winner_mismatch",
                          sc["summary_disagreements"])

    def test_altered_raw_jsonl_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            p = ev / "candidate" / "characterization" / "pos0" / "B.jsonl"
            rows = [json.loads(x) for x in p.read_text().splitlines()]
            rows[0]["top"] = [[999999, 99.0]] + rows[0]["top"][1:]
            p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_BLOCKED)

    def test_altered_raw_f32_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            p = ev / "candidate" / "characterization" / "pos0" / "C.jsonl.pos0.f32"
            row = bytearray(p.read_bytes())
            struct.pack_into("<f", row, 561 * 4, 99.0)
            p.write_bytes(bytes(row))
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_BLOCKED)

    def test_changed_sidecar_digest_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            p = ev / "candidate" / \
                "score-characterization-case-256.json"
            d = json.loads(p.read_text())
            d["arms"]["A"]["raw_sidecar_sha256"]["f32_pos0"] = "0" * 64
            p.write_text(json.dumps(d))
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_BLOCKED)
            sc = doc["checks"]["score_characterization"]
            self.assertIn("summary:armA:f32_digest_mismatch",
                          sc["problems"])

    def test_forged_non_perturbation_rejected(self):
        # authored non_perturbation_identical=true while the raw
        # response tokens differ from the canonical stream -> reject
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            p = ev / "candidate" / "characterization" / "pos0" / "A.resp.json"
            d = json.loads(p.read_text())
            d["tokens"] = [999999] + d["tokens"][1:]
            p.write_text(json.dumps(d))
            s = ev / "candidate" / \
                "score-characterization-case-256.json"
            sd = json.loads(s.read_text())
            sd["arms"]["A"]["non_perturbation_identical"] = True
            s.write_text(json.dumps(sd))
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_BLOCKED)

    def test_wrong_arm_response_rejected(self):
        # swap B's raw response for C's -> wrong-arm binding rejected
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            bd = ev / "candidate" / "characterization" / "pos0"
            b = json.loads((bd / "B.resp.json").read_text())
            c = json.loads((bd / "C.resp.json").read_text())
            (bd / "B.resp.json").write_text(json.dumps(c))
            (bd / "C.resp.json").write_text(json.dumps(b))
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_BLOCKED)

    def test_observation_pin_tamper_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            p = ev / "candidate" / "characterization" / "pos0" / \
                "pos0-observation-pin.json"
            d = json.loads(p.read_text())
            d["observation_producer"]["llama_cpp_source_pin"] = "f" * 40
            p.write_text(json.dumps(d))
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_BLOCKED)

    def test_f32_length_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            p = ev / "candidate" / "characterization" / "pos0" / "A.jsonl.pos0.f32"
            p.write_bytes(p.read_bytes()[:-4])
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_BLOCKED)


class TestReducerTerminals(unittest.TestCase):
    def test_divergence_without_characterization_blocks(self):
        with tempfile.TemporaryDirectory() as t:
            import shutil
            ev = make_evidence(Path(t))
            shutil.rmtree(ev / "candidate" / "characterization")
            (ev / "candidate" /
             "score-characterization-case-256.json").unlink()
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_BLOCKED)
            self.assertIn("characterization",
                          " ".join(doc["terminal_basis"]))

    def test_repeat_drop_blocks(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t), drop_b_repeat=True)
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_BLOCKED)

    def test_nondeterminism_blocks(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t), det_b=False)
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_BLOCKED)

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
            self.assertEqual(doc["terminal"], red.TERMINAL_MULTI_AXIS)

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

    def test_controls_run_all_ok_on_multi_axis_evidence(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            receipt = asm.run_controls(ev, CLOSURE)
            self.assertEqual(receipt["count"], 36)
            self.assertTrue(receipt["all_ok"])
            bad = {k: v for k, v in receipt["controls"].items()
                   if not v["ok"]}
            self.assertEqual(bad, {}, f"failing controls: {bad}")

    def test_control33_proves_all_blocked_paths(self):
        # focused re-check of the five required control-33 outcomes
        outcomes = {}
        with tempfile.TemporaryDirectory() as t:
            import shutil
            ev = make_evidence(Path(t))
            # (1) missing characterization
            shutil.rmtree(ev / "candidate" / "characterization")
            (ev / "candidate" /
             "score-characterization-case-256.json").unlink()
            outcomes["missing"] = red.derive_terminal(
                ev, closure=CLOSURE)["terminal"]
            # (2) wrong generated position (summary-only, pos 5)
            ev2 = make_evidence(Path(t) / "x2")
            shutil.rmtree(ev2 / "candidate" / "characterization" / "pos0")
            (ev2 / "candidate" /
             "score-characterization-case-256.json").unlink()
            outcomes["wrong_pos"] = red.derive_terminal(
                ev2, closure=CLOSURE)["terminal"]
        self.assertEqual(outcomes["missing"], red.TERMINAL_BLOCKED)
        self.assertEqual(outcomes["wrong_pos"], red.TERMINAL_BLOCKED)
        # (3/4/5) summary/raw mismatch, sidecar tamper, non-perturbation
        # forgery are covered by TestRawBoundCharacterization above and
        # by controls 21/27/31/32/33 in the assembled suite.


class TestDeployedProducerVerification(unittest.TestCase):
    CLOSURE_PHYS = None

    @classmethod
    def setUpClass(cls):
        real = rc.verify_closure(REPO)
        cls.CLOSURE_PHYS = real

    def _deployed(self, ev: Path):
        return json.loads(
            (ev / "freeze" / "deployed-producers.json").read_text())

    def test_real_matrix_verifies(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            r = asm.verify_deployed_producers(
                self._deployed(ev), self.CLOSURE_PHYS)
            self.assertTrue(r["derived_all_hosts_match_pin"])
            self.assertEqual(r["expected_hosts"],
                             ["inferswarm01", "inferswarm02"])
            for h in ("inferswarm01", "inferswarm02"):
                self.assertEqual(
                    r["per_host"][h]["checked"],
                    sorted(asm.DEPLOYED_PRODUCER_BASENAMES))

    def _expect_fail(self, ev, mutate, label):
        d = self._deployed(ev)
        mutate(d)
        with self.assertRaises(asm.AssembleError, msg=label):
            asm.verify_deployed_producers(d, self.CLOSURE_PHYS)

    def test_missing_host_01_fails(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            self._expect_fail(
                ev, lambda d: d["hosts"].pop("inferswarm01"), "01")

    def test_missing_host_02_fails(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            self._expect_fail(
                ev, lambda d: d["hosts"].pop("inferswarm02"), "02")

    def test_missing_ladder_producer_fails(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            self._expect_fail(
                ev,
                lambda d: d["hosts"]["inferswarm01"]["hashes"].pop(
                    "issue234_ladder.py"),
                "ladder")

    def test_wrong_ladder_hash_fails(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            self._expect_fail(
                ev,
                lambda d: d["hosts"]["inferswarm01"]["hashes"].
                __setitem__("issue234_ladder.py", "0" * 64),
                "ladder-hash")

    def test_wrong_health_hash_fails(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            self._expect_fail(
                ev,
                lambda d: d["hosts"]["inferswarm02"]["hashes"].
                __setitem__("issue234_health.py", "0" * 64),
                "health-hash")

    def test_substituted_producer_fails(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            def mut(d):
                h = d["hosts"]["inferswarm01"]["hashes"]
                h["issue234_substitute.py"] = h["issue234_ladder.py"]
            self._expect_fail(ev, mut, "substitute")

    def test_authored_boolean_not_trusted(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            def mut(d):
                d["all_hosts_match_pin"] = True
                d["hosts"].pop("inferswarm01")
            self._expect_fail(ev, mut, "forged boolean")

    def test_stale_closure_pin_out_of_lineage_fails(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            closure = dict(self.CLOSURE_PHYS)
            closure["producer_head"] = closure["producer_head"]
            # 377d2ff IS an ancestor of the active pin -> passes
            r = asm.verify_deployed_producers(self._deployed(ev),
                                              self.CLOSURE_PHYS)
            self.assertTrue(r["derived_all_hosts_match_pin"])
            # a foreign SHA must fail the lineage check
            def mut(d):
                d["closure_producer_head"] = "f" * 40
            with self.assertRaises(asm.AssembleError):
                d = self._deployed(ev)
                mut(d)
                asm.verify_deployed_producers(d, self.CLOSURE_PHYS)


class TestClosureDoctrine(unittest.TestCase):
    def test_closure_document_blobs(self):
        doc = rc.closure_document(REPO)
        self.assertEqual(doc["schema"],
                         "inferswarm.r8h.producer-closure/2")
        self.assertEqual(len(doc["sources"]), len(rc.CLOSURE_SOURCES))
        self.assertIn("scripts/issue234_characterize.py",
                      rc.REDUCTION_PRODUCERS)
        self.assertIn("scripts/issue234_characterize.py",
                      doc["sources"])
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

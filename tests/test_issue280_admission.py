"""Issue #284 round 2: observer-admission gate over retained raw bytes.

Maintainer finding (PR #285 comment 6035951310, P1): the runner admitted
candidate evidence by EVENT-NAME PRESENCE ONLY. A stream carrying every
expected name could still be causally or physically wrong.

These tests prove the corrected law end-to-end on real ``I280`` raw streams
replayed through the substantive collector laws under the frozen physical
#280 contract:

A. presence-only false positive — every expected event name present, wrong
   die BDF binding: rejected, candidate warm never invoked;
B. all names present, one candidate die without mechanically valid completed
   nonempty compute: STOP before candidate warm;
C. all names present, invalid boundary attribution (wrong src/dst and wrong
   logical bytes/manifest law): STOP before candidate warm;
D. a mechanically valid two-die stream passes and permits candidate warm.

All streams are synthetic retained-byte shapes; no GPU/model/device access.
"""
from pathlib import Path
import importlib.util
import json
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts/issue280_runner.py"

PIN = "b29c606e28a01b1bc8c1351026a0fa6e616bf6c4"
DIE_A, DIE_B = "0000:07:00.0", "0000:0b:00.0"
GOOD_TEXT = '{"service":"payments","severity":"high","status":"resolved"}'

# Manifest shape: f32, ne=[4,4,1,1], nb=[4,16,64,64] -> logical bytes
# 4 + 3*4 + 3*16 = 64 (the shape/stride law the collector recomputes).
MANIFEST_BYTES = 64


def load_runner():
    spec = importlib.util.spec_from_file_location("issue280_runner_admission", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_stream(die_b_bdf=DIE_B, drop_die_b_compute=False, boundary_bytes=None,
                 boundary_src="Vulkan0", boundary_dst="Vulkan1",
                 omit_boundary=False, single_die=False,
                 output_bdf=None, omit_output=False, baseline_upper=35,
                 kv_dies=None):
    """A mechanically valid candidate (or single-die baseline) raw stream.

    Mutations map exactly to the maintainer's false-positive channels:
    ``die_b_bdf`` (wrong BDF), ``drop_die_b_compute`` (missing real work on
    one die), ``boundary_bytes``/``boundary_src``/``boundary_dst``/``omit_\
    boundary`` (invalid boundary proof), ``output_bdf``/``omit_output``
    (frozen output-tensor ownership, round 3), ``baseline_upper`` (silently
    reduced baseline block placement, round 3), ``kv_dies`` (per-die
    KV/mutable-state ownership, round 4 — which dies carry kv_inventory
    rows; None keeps the valid default: every participating die). Defaults
    model the exact frozen #280 arms: baseline = ALL blocks 0-35 plus the
    output tensor on die A (full single-die block/output offload);
    candidate = blocks 0-18 on die A, blocks 19-35 plus output on die B.
    """
    ts = [0]

    def ev(event, **fields):
        ts[0] += 10
        row = {"schema": "issue280-raw/1", "event": event, "ts_ns": ts[0]}
        row.update(fields)
        return "I280 " + json.dumps(row)

    out = [ev("recording", kind="SOURCE_OBSERVER", source_pin=PIN, requests_planned=1)]
    layers_a = range(0, 36) if single_die else range(0, 19)
    if single_die and baseline_upper != 35:
        layers_a = range(0, baseline_upper + 1)
    layers_b = [] if single_die else range(19, 36)
    for n in layers_a:
        out.append(ev("weight_inventory", tensor=f"blk.{n}.ffn_gate.weight",
                      bdf=DIE_A, bytes=1024, layer=n, buffer=f"wa{n}"))
    for n in layers_b:
        out.append(ev("weight_inventory", tensor=f"blk.{n}.ffn_gate.weight",
                      bdf=die_b_bdf, bytes=1024, layer=n, buffer=f"wb{n}"))
    # Frozen output-layer ownership (RUN-PLAN: baseline = output on A;
    # candidate = output on B). ``output_bdf`` re-binds it (e.g. to die A in
    # a candidate stream, or an alien backend); ``omit_output`` drops it.
    output_die = DIE_A if single_die else DIE_B
    if output_bdf is not None:
        output_die = output_bdf
    if not omit_output:
        out.append(ev("weight_inventory", tensor="output.weight",
                      bdf=output_die, bytes=512, layer=-1, buffer="wout"))
    participating = [DIE_A] if single_die else [DIE_A, die_b_bdf]
    kv_targets = set(participating) if kv_dies is None else set(kv_dies)
    if DIE_A in kv_targets:
        out.append(ev("kv_inventory", tensor="blk.0.k", bdf=DIE_A, bytes=128,
                      kind="k", layer=0, buffer="kva"))
    if not single_die and die_b_bdf in kv_targets:
        out.append(ev("kv_inventory", tensor="blk.19.k", bdf=die_b_bdf,
                      bytes=128, kind="k", layer=19, buffer="kvb"))
    out.append(ev("request_accept", request=1, ordinal=1, seq=0))
    out.append(ev("batch_begin", request=1, seq=0, tokens=4, phase="prefill",
                  speculative=0, token_ids=[1, 2, 3, 4], positions=[0, 1, 2, 3]))
    out.append(ev("graph_begin", request=1, graph="g", tokens=4, seq=0, sequences=1,
                  n_seqs_unq=1, seq_ids_unq=[0], n_seq_tokens=4))
    if not single_die:
        out.append(ev("copy_manifest", request=1, tensor="ffn_out-0",
                      src=boundary_src, dst=boundary_dst,
                      input="in", copy="out", occ=0, bytes=MANIFEST_BYTES,
                      type="f32", ne0=4, ne1=4, ne2=1, ne3=1,
                      nb0=4, nb1=16, nb2=64, nb3=64,
                      view_offset=0, buffer_bytes=65536))

    def emit_die(ctx, cmd, sub, bdf, backend, layers):
        out.append(ev("vk_graph_begin", request=1, ctx=ctx, backend=backend, bdf=bdf))
        out.append(ev("ctx_create", request=1, subctx=sub, ctx=ctx))
        out.append(ev("node", request=1, ctx=ctx, cmd=cmd, use=1,
                      tensor="ffn_out-0", op="MUL_MAT"))
        for n in layers:
            out.append(ev("weight", request=1, ctx=ctx, cmd=cmd, use=1,
                          tensor=f"blk.{n}.ffn_gate.weight",
                          buffer=f"w{'a' if bdf == DIE_A else 'b'}{n}",
                          offset=0, bytes=128, buffer_bytes=4096))
        out.append(ev("dispatch", request=1, ctx=ctx, cmd=cmd, use=1,
                      pipeline="mul_mat_f32", x=1, y=1, z=1))
        if bdf == (DIE_A if single_die else die_b_bdf):
            out.append(ev("node", request=1, ctx=ctx, cmd=cmd, use=1,
                          tensor="result_output", op="MUL_MAT"))
            out.append(ev("weight", request=1, ctx=ctx, cmd=cmd, use=1,
                          tensor="output.weight", buffer="vk-output-underlying",
                          offset=0, bytes=512, buffer_bytes=4096))
            out.append(ev("dispatch", request=1, ctx=ctx, cmd=cmd, use=1,
                          pipeline="mul_mat_f32", x=1, y=1, z=1))
        out.append(ev("submit", request=1, subctx=sub, cmd=cmd, use=1))
        out.append(ev("complete", request=1, ctx=ctx, wait="fence"))
        out.append(ev("vk_graph_end", request=1, ctx=ctx))

    emit_die("ctx0", "cmd0", "sub0", DIE_A, "Vulkan0", layers_a)
    if not single_die:
        if not omit_boundary:
            bbytes = MANIFEST_BYTES if boundary_bytes is None else boundary_bytes
            out.append(ev("boundary_begin", request=1, tensor="ffn_out-0",
                          src=boundary_src, dst=boundary_dst,
                          input="in", copy="out", occ=0, bytes=bbytes))
            out.append(ev("copy_path", request=1, input="in", copy="out", occ=0,
                          src_buffer="sb", dst_buffer="db"))
            out.append(ev("host_leg", request=1, input="in", copy="out", occ=0,
                          direction="device_to_host", bytes=bbytes,
                          src_buffer="sb", dst_buffer="db"))
            out.append(ev("host_leg", request=1, input="in", copy="out", occ=0,
                          direction="host_to_device", bytes=bbytes,
                          src_buffer="sb", dst_buffer="db"))
            out.append(ev("boundary_end", request=1, input="in", copy="out",
                          occ=0, bytes=bbytes))
        if not drop_die_b_compute:
            emit_die("ctx1", "cmd1", "sub1", die_b_bdf, "Vulkan1", layers_b)
    out.append(ev("graph_end", request=1, graph="g", status=0))
    out.append(ev("batch_end", request=1, status=0))
    out.append(ev("sample", request=1, position=0, token_id=41,
                  absolute_position=4, eos=0))
    out.append(ev("response", request=1, sampled=1, prompt_processed=4,
                  prompt_cached=0, eos=0))
    out.append(ev("request_end", request=1, stop_reason="limit",
                  prompt_processed=4, prompt_cached=0))
    return "\n".join(out) + "\n"


def events_of(raw):
    names = set()
    for line in raw.splitlines():
        if "I280 " in line:
            names.add(json.loads(line.split("I280 ", 1)[1])["event"])
    return names


class AdmissionHarness(unittest.TestCase):
    def setUp(self):
        self.m = load_runner()
        self.launches = []
        self.requests = []

    def executor(self, raws):
        """raws: list of raw streams, one per planned request, in order."""
        m = self.m

        def launch(matrix_row):
            self.launches.append(matrix_row)

            def request(kind):
                self.requests.append((matrix_row["label"], kind))
                raw = raws[len(self.requests) - 1]
                record = {"launch": matrix_row["label"], "arm": matrix_row["arm"],
                          "prompt": matrix_row["prompt"], "kind": kind,
                          "text": GOOD_TEXT, "transport_ok": True}
                state = {"observer_raw": raw, "observer_events": events_of(raw),
                         "peak_rss_bytes": 1}
                return record, state

            return request

        return launch


class PresenceOnlyFalsePositiveTests(AdmissionHarness):
    def test_wrong_bdf_rejected_and_candidate_warm_never_invoked(self):
        """Case A: every expected event name present; die-B BDF is not one of
        the two frozen retained V340L BDFs. Old name logic: nothing missing.
        Corrected gate: STOP before candidate warm."""
        wrong = build_stream(die_b_bdf="0000:0c:00.0")
        # the old authority would find every required candidate name present
        missing = [n for n in self.m.CANDIDATE_EVIDENCE if n not in events_of(wrong)]
        self.assertEqual(missing, [], "old name-gate sees a complete name set")
        valid = build_stream()
        raws = [build_stream(single_die=True), build_stream(single_die=True),
                wrong, valid]
        summary = self.m.run_campaign(self.m.MINIMAL_RERUN_MATRIX, self.executor(raws))
        self.assertEqual(summary["terminal"], "STOP")
        self.assertEqual([r["disposition"] for r in summary["requests"]],
                         ["accepted", "accepted", "rejected", "not_attempted"])
        self.assertEqual(self.requests,
                         [("R1", "cold"), ("R1", "warm"), ("R2", "cold")])
        self.assertIn("observer admission failure", summary["stop_reason"])

    def test_request_graph_mismatch_rejected(self):
        """Case A variant: all names present, the completed boundary is
        attributed to a request identity that is not the admitted request."""
        raw_lines = build_stream().splitlines()
        mutated = []
        hit = False
        for line in raw_lines:
            if "I280 " in line and '"boundary_end"' in line and not hit:
                row = json.loads(line.split("I280 ", 1)[1])
                row["request"] = 2  # not the admitted request
                hit = True
                line = "I280 " + json.dumps(row)
            mutated.append(line)
        self.assertTrue(hit, "boundary_end row not found for mutation")
        raw = "\n".join(mutated) + "\n"
        valid = build_stream()
        raws = [build_stream(single_die=True), build_stream(single_die=True),
                raw, valid]
        summary = self.m.run_campaign(self.m.MINIMAL_RERUN_MATRIX, self.executor(raws))
        self.assertEqual(summary["terminal"], "STOP")
        self.assertEqual(self.requests[-1], ("R2", "cold"))
        self.assertIn("observer admission failure", summary["stop_reason"])


class MissingWorkTests(AdmissionHarness):
    def test_one_die_without_completed_compute_stops(self):
        """Case B: all names present, die B records no completed nonempty
        compute (no dispatch/submit/complete on the second die)."""
        partial = build_stream(drop_die_b_compute=True)
        missing = [n for n in self.m.CANDIDATE_EVIDENCE
                   if n not in events_of(partial)]
        # dispatch/submit/complete still appear (die A carried them): the old
        # name gate could not see the missing die-B work at all.
        self.assertEqual(
            [n for n in missing if n in ("dispatch", "submit", "complete")], [])
        raws = [build_stream(single_die=True), build_stream(single_die=True),
                partial, build_stream()]
        summary = self.m.run_campaign(self.m.MINIMAL_RERUN_MATRIX, self.executor(raws))
        self.assertEqual(summary["terminal"], "STOP")
        self.assertNotIn(("R2", "warm"), self.requests)
        self.assertEqual([r["disposition"] for r in summary["requests"]],
                         ["accepted", "accepted", "rejected", "not_attempted"])


class InvalidBoundaryTests(AdmissionHarness):
    def test_wrong_boundary_src_dst_stops(self):
        """Case C (attribution): boundary declared same-backend (not
        cross-die) despite complete name coverage."""
        raw = build_stream(boundary_src="Vulkan0", boundary_dst="Vulkan0")
        self.assertEqual(
            [n for n in self.m.CANDIDATE_EVIDENCE if n not in events_of(raw)], [])
        raws = [build_stream(single_die=True), build_stream(single_die=True),
                raw, build_stream()]
        summary = self.m.run_campaign(self.m.MINIMAL_RERUN_MATRIX, self.executor(raws))
        self.assertEqual(summary["terminal"], "STOP")
        self.assertNotIn(("R2", "warm"), self.requests)
        self.assertEqual(summary["requests"][2]["disposition"], "rejected")

    def test_wrong_logical_bytes_stops(self):
        """Case C (bytes): boundary bytes disagree with the manifest
        shape/stride law (52) — 53 fails both laws."""
        raw = build_stream(boundary_bytes=53)
        self.assertEqual(
            [n for n in self.m.CANDIDATE_EVIDENCE if n not in events_of(raw)], [])
        raws = [build_stream(single_die=True), build_stream(single_die=True),
                raw, build_stream()]
        summary = self.m.run_campaign(self.m.MINIMAL_RERUN_MATRIX, self.executor(raws))
        self.assertEqual(summary["terminal"], "STOP")
        self.assertNotIn(("R2", "warm"), self.requests)

    def test_missing_boundary_evidence_stops(self):
        """Case C (occurrence): no completed boundary at all — name coverage
        complete only because copy_manifest was emitted, never consumed."""
        raw = build_stream(omit_boundary=True)
        names = events_of(raw)
        # boundary_begin/end/host_leg/copy_path names vanish with the chain;
        # copy_manifest remains. Provide them as (lying) diagnostic metadata:
        # admission must still fail on the mechanical law, not the names.
        state_names = names | {"boundary_begin", "boundary_end",
                               "host_leg", "copy_path"}
        missing = [n for n in self.m.CANDIDATE_EVIDENCE if n not in state_names]
        self.assertEqual(missing, [])
        raws = [build_stream(single_die=True), build_stream(single_die=True),
                raw, build_stream()]

        m = self.m
        launches = []

        def launch(matrix_row):
            launches.append(matrix_row)

            def request(kind):
                self.requests.append((matrix_row["label"], kind))
                r = raws[len(self.requests) - 1]
                record = {"launch": matrix_row["label"], "arm": matrix_row["arm"],
                          "prompt": matrix_row["prompt"], "kind": kind,
                          "text": GOOD_TEXT, "transport_ok": True}
                state = {"observer_raw": r, "observer_events": state_names,
                         "peak_rss_bytes": 1}
                return record, state

            return request

        summary = m.run_campaign(m.MINIMAL_RERUN_MATRIX, launch)
        self.assertEqual(summary["terminal"], "STOP")
        self.assertNotIn(("R2", "warm"), self.requests)
        self.assertIn("boundary", summary["stop_reason"])


class ValidTwoDieTests(AdmissionHarness):
    def test_valid_two_die_stream_passes_and_permits_candidate_warm(self):
        """Case D: mechanically valid candidate stream admits and candidate
        warm executes; full matrix completes."""
        raws = [build_stream(single_die=True), build_stream(single_die=True),
                build_stream(), build_stream()]
        summary = self.m.run_campaign(self.m.MINIMAL_RERUN_MATRIX, self.executor(raws))
        self.assertEqual(summary["terminal"], "COMPLETE")
        self.assertIsNone(summary["stop_reason"])
        self.assertEqual([r["disposition"] for r in summary["requests"]],
                         ["accepted"] * 4)
        self.assertIn(("R2", "warm"), self.requests)
        verdicts = [r.get("observer_verdict") for r in summary["requests"]]
        self.assertTrue(all(v and v["ok"] for v in verdicts))

    def test_no_retained_bytes_fail_closed(self):
        raws = [build_stream(single_die=True), build_stream(single_die=True),
                None, build_stream()]
        m = self.m
        requests = []

        def launch(matrix_row):
            def request(kind):
                requests.append((matrix_row["label"], kind))
                raw = raws[len(requests) - 1]
                state = {"observer_raw": raw,
                         "observer_events": set() if raw is None else events_of(raw),
                         "peak_rss_bytes": 1}
                record = {"launch": matrix_row["label"], "arm": matrix_row["arm"],
                          "prompt": matrix_row["prompt"], "kind": kind,
                          "text": GOOD_TEXT, "transport_ok": True}
                return record, state
            return request

        summary = m.run_campaign(m.MINIMAL_RERUN_MATRIX, launch)
        self.assertEqual(summary["terminal"], "STOP")
        self.assertNotIn(("R2", "warm"), requests)
        self.assertIn("no retained observer bytes", summary["stop_reason"])


class FrozenPlacementTests(unittest.TestCase):
    """Round 3 (PR #285 maintainer finding): the PHYSICAL_280 placement
    contract must encode the FULL frozen arm placement, not a prefix.

    Frozen #280 authority (RUN-PLAN "Subject and source"): Baseline A = one
    V340L die, no split, FULL intended block/output offload (blocks 0-35 plus
    the output tensor on die A). Candidate B = blocks 0-18 on die A, blocks
    19-35 PLUS the output tensor on die B. A silently reduced baseline
    (blocks 0-18 only) or a candidate without proven output ownership must
    NOT pass observer admission.
    """

    def setUp(self):
        spec = importlib.util.spec_from_file_location(
            "issue280_observer_placement",
            ROOT / "scripts/issue280_observer.py")
        assert spec is not None and spec.loader is not None
        self.observer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.observer)
        self.contracts = self.observer.physical_280_contracts()

    def test_contract_encodes_full_frozen_placement(self):
        """The contract itself must carry the frozen identities."""
        a, b = self.contracts["A"], self.contracts["B"]
        self.assertEqual(a["dies"], ["0000:07:00.0"])
        self.assertEqual(a["layers"]["0000:07:00.0"], list(range(0, 36)))
        self.assertEqual(a["output_role"]["owner"], "0000:07:00.0")
        self.assertEqual(a["output_role"]["architecture"], "qwen2")
        self.assertEqual(b["dies"], ["0000:07:00.0", "0000:0b:00.0"])
        self.assertEqual(b["layers"]["0000:07:00.0"], list(range(0, 19)))
        self.assertEqual(b["layers"]["0000:0b:00.0"], list(range(19, 36)))
        self.assertEqual(b["output_role"]["owner"], "0000:0b:00.0")
        self.assertEqual(b["output_role"]["model_sha256"], a["output_role"]["model_sha256"])

    def test_reduced_baseline_blocks_rejected(self):
        """FP1: baseline carrying only blocks 0-k for any k < 35 is a silent
        placement reduction and must be rejected."""
        for upper in range(18, 35):
            with self.subTest(upper=upper):
                verdict = self.observer.validate_admission(
                    build_stream(single_die=True, baseline_upper=upper),
                    self.contracts["A"])
                self.assertFalse(verdict["ok"], verdict["problems"])

    def test_baseline_missing_output_rejected(self):
        verdict = self.observer.validate_admission(
            build_stream(single_die=True, omit_output=True),
            self.contracts["A"])
        self.assertFalse(verdict["ok"], verdict["problems"])

    def test_baseline_output_on_alien_backend_rejected(self):
        for alien in ("0000:0c:00.0", "CPU"):
            with self.subTest(alien=alien):
                verdict = self.observer.validate_admission(
                    build_stream(single_die=True, output_bdf=alien),
                    self.contracts["A"])
                self.assertFalse(verdict["ok"], verdict["problems"])

    def test_candidate_missing_output_rejected(self):
        """FP2: blocks 0-35 present but no frozen output-layer ownership."""
        raw = build_stream(omit_output=True)
        self.assertEqual(
            [n for n in load_runner().CANDIDATE_EVIDENCE if n not in events_of(raw)], [],
            "old name-gate sees a complete name set")
        verdict = self.observer.validate_admission(raw, self.contracts["B"])
        self.assertFalse(verdict["ok"], verdict["problems"])

    def test_candidate_output_on_die_a_rejected(self):
        verdict = self.observer.validate_admission(
            build_stream(output_bdf=DIE_A), self.contracts["B"])
        self.assertFalse(verdict["ok"], verdict["problems"])

    def test_correct_baseline_full_placement_passes(self):
        verdict = self.observer.validate_admission(
            build_stream(single_die=True), self.contracts["A"])
        self.assertTrue(verdict["ok"], verdict["problems"])
        self.assertEqual(verdict["contract_dies"], ["0000:07:00.0"])

    def test_correct_candidate_frozen_split_with_output_passes(self):
        verdict = self.observer.validate_admission(
            build_stream(), self.contracts["B"])
        self.assertTrue(verdict["ok"], verdict["problems"])


class FrozenPlacementRunnerTests(AdmissionHarness):
    """Runner-level pin: a placement/admission failure cannot be followed by
    candidate warm."""

    def test_candidate_missing_output_stops_before_candidate_warm(self):
        reduced = build_stream(omit_output=True)
        raws = [build_stream(single_die=True), build_stream(single_die=True),
                reduced, build_stream()]
        summary = self.m.run_campaign(self.m.MINIMAL_RERUN_MATRIX, self.executor(raws))
        self.assertEqual(summary["terminal"], "STOP")
        self.assertEqual([r["disposition"] for r in summary["requests"]],
                         ["accepted", "accepted", "rejected", "not_attempted"])
        self.assertNotIn(("R2", "warm"), self.requests)
        self.assertIn("observer admission failure", summary["stop_reason"])

    def test_reduced_baseline_blocks_stop_the_campaign(self):
        reduced = build_stream(single_die=True, baseline_upper=18)
        raws = [reduced, build_stream(single_die=True), build_stream(), build_stream()]
        summary = self.m.run_campaign(self.m.MINIMAL_RERUN_MATRIX, self.executor(raws))
        self.assertEqual(summary["terminal"], "STOP")
        self.assertEqual(len(self.requests), 1, "request 2 must never launch")
        self.assertEqual(summary["requests"][0]["disposition"], "rejected")
        self.assertIn("observer admission failure", summary["stop_reason"])


class KVOwnershipTests(unittest.TestCase):
    """Round 4 (PR #285 maintainer finding): PHYSICAL_280 admission must
    mechanically require per-die KV/mutable-state ownership on every
    participating die (Issue #284: admitted real-run evidence includes
    KV/mutable-state inventory/ownership where applicable).

    The collector already carried the law — per-die ``kv_bytes`` placement
    and the ``placement.required_categories`` fail-closed check — but
    ``physical_280_contracts()`` never declared the category, so admission
    never activated it. A candidate could carry ``kv_inventory`` on die A
    only (event name still present) and PASS without proven candidate-die-B
    KV ownership. The correction activates the existing single-validator
    law in the frozen contracts; no second validator exists.
    """

    def setUp(self):
        spec = importlib.util.spec_from_file_location(
            "issue280_observer_kv",
            ROOT / "scripts" / "issue280_observer.py")
        assert spec is not None and spec.loader is not None
        self.observer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.observer)
        self.contracts = self.observer.physical_280_contracts()

    def test_contracts_declare_kv_ownership_requirement(self):
        """Both frozen arms must require the kv_cache placement category on
        every participating die through the existing required_categories
        mechanism (no second validator)."""
        for arm, dies in (("A", (DIE_A,)), ("B", (DIE_A, DIE_B))):
            with self.subTest(arm=arm):
                contract = self.contracts[arm]
                self.assertEqual(
                    contract["placement"]["required_categories"], ["kv_cache"])
                self.assertEqual(contract["dies"], list(dies))

    def test_candidate_kv_only_on_die_a_rejected(self):
        """FP1: KV inventory bound to die A only; die B (blocks 19-35 plus
        output) has zero declared KV ownership. Must fail closed."""
        verdict = self.observer.validate_admission(
            build_stream(kv_dies=[DIE_A]), self.contracts["B"])
        self.assertFalse(verdict["ok"], verdict["problems"])
        self.assertTrue(any("kv_cache" in p for p in verdict["problems"]),
                        verdict["problems"])

    def test_candidate_kv_only_on_die_b_rejected(self):
        verdict = self.observer.validate_admission(
            build_stream(kv_dies=[DIE_B]), self.contracts["B"])
        self.assertFalse(verdict["ok"], verdict["problems"])
        self.assertTrue(any("kv_cache" in p for p in verdict["problems"]),
                        verdict["problems"])

    def test_candidate_no_kv_rejected(self):
        verdict = self.observer.validate_admission(
            build_stream(kv_dies=[]), self.contracts["B"])
        self.assertFalse(verdict["ok"], verdict["problems"])
        self.assertTrue(any("kv_cache" in p for p in verdict["problems"]),
                        verdict["problems"])

    def test_candidate_kv_on_both_dies_passes(self):
        verdict = self.observer.validate_admission(
            build_stream(kv_dies=[DIE_A, DIE_B]), self.contracts["B"])
        self.assertTrue(verdict["ok"], verdict["problems"])
        for die in (DIE_A, DIE_B):
            self.assertGreater(verdict["per_die"][die]["kv_bytes"], 0)

    def test_baseline_no_kv_rejected(self):
        verdict = self.observer.validate_admission(
            build_stream(single_die=True, kv_dies=[]), self.contracts["A"])
        self.assertFalse(verdict["ok"], verdict["problems"])
        self.assertTrue(any("kv_cache" in p for p in verdict["problems"]),
                        verdict["problems"])

    def test_baseline_kv_on_die_a_passes(self):
        verdict = self.observer.validate_admission(
            build_stream(single_die=True, kv_dies=[DIE_A]), self.contracts["A"])
        self.assertTrue(verdict["ok"], verdict["problems"])
        self.assertGreater(verdict["per_die"][DIE_A]["kv_bytes"], 0)

    def test_event_name_presence_cannot_override_kv_ownership(self):
        """The kv_inventory EVENT NAME present in observer_events metadata
        must not substitute for die-B KV ownership: the stream with KV on
        die A only still fails, and its name set contains kv_inventory."""
        raw = build_stream(kv_dies=[DIE_A])
        names = events_of(raw)
        self.assertIn("kv_inventory", names)
        verdict = self.observer.validate_admission(raw, self.contracts["B"])
        self.assertFalse(verdict["ok"], verdict["problems"])

    def test_candidate_warm_unreachable_after_kv_admission_failure(self):
        """Runner-level pin: a candidate-cold KV-ownership failure STOPs the
        campaign before candidate warm executes."""
        m = load_runner()
        launches = []
        requests = []

        def launch(matrix_row):
            launches.append(matrix_row)

            def request(kind):
                requests.append((matrix_row["label"], kind))
                single = matrix_row["arm"] == "A"
                raw = build_stream(single_die=single, kv_dies=[DIE_A])
                record = {"launch": matrix_row["label"], "arm": matrix_row["arm"],
                          "prompt": matrix_row["prompt"], "kind": kind,
                          "text": GOOD_TEXT, "transport_ok": True}
                state = {"observer_raw": raw, "observer_events": events_of(raw),
                         "peak_rss_bytes": 1}
                return record, state

            return request

        summary = m.run_campaign(m.MINIMAL_RERUN_MATRIX, launch)
        self.assertEqual(summary["terminal"], "STOP")
        self.assertEqual(
            [r["disposition"] for r in summary["requests"]],
            ["accepted", "accepted", "rejected", "not_attempted"])
        self.assertNotIn(("R2", "warm"), requests)
        self.assertIn("observer admission failure", summary["stop_reason"])
        self.assertIn("kv_cache", summary["stop_reason"])

    def test_cpu_fixture_contract_unchanged(self):
        """CPU_FIXTURE semantics unchanged: the synthetic fixture contract
        declares no required placement categories, so its behavior does not
        change (round-4 law is keyed on contract-declared requirements)."""
        contract = self.observer.fixture_contract()
        self.assertNotIn("placement", contract)


class DirectValidatorTests(unittest.TestCase):
    """The runner's admission path is the collector's own law set."""

    def setUp(self):
        spec = importlib.util.spec_from_file_location(
            "issue280_observer_admission",
            ROOT / "scripts/issue280_observer.py")
        assert spec is not None and spec.loader is not None
        self.observer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.observer)

    def test_validate_admission_returns_structured_verdict(self):
        verdict = self.observer.validate_admission(
            build_stream(), self.observer.physical_280_contracts()["B"])
        self.assertEqual(verdict["schema"], "issue280-observer-admission/1")
        self.assertTrue(verdict["ok"], verdict["problems"])
        self.assertEqual(verdict["contract_kind"], "PHYSICAL_280")
        self.assertEqual(verdict["contract_dies"], ["0000:07:00.0", "0000:0b:00.0"])
        per_die = verdict["per_die"]
        for die in ("0000:07:00.0", "0000:0b:00.0"):
            self.assertGreater(per_die[die]["weights_bytes"], 0)
            self.assertGreater(per_die[die]["completed_compute_commands"], 0)
        self.assertEqual(verdict["logical_boundary_bytes"], MANIFEST_BYTES)
        self.assertEqual(verdict["host_leg_bytes"], 2 * MANIFEST_BYTES)
        self.assertEqual(verdict["physical_execution"], "NONE")

    def test_baseline_contract_does_not_require_boundary(self):
        verdict = self.observer.validate_admission(
            build_stream(single_die=True),
            self.observer.physical_280_contracts()["A"])
        self.assertTrue(verdict["ok"], verdict["problems"])
        self.assertEqual(verdict["contract_dies"], ["0000:07:00.0"])

    def test_cpu_fixture_behavior_unchanged(self):
        result = self.observer.collect("not a raw stream at all",
                                       self.observer.fixture_contract())
        self.assertFalse(result["ok"])
        self.assertTrue(result["problems"])
        self.assertEqual(result["schema"], "issue280-cpu-replay/1")


if __name__ == "__main__":
    unittest.main()

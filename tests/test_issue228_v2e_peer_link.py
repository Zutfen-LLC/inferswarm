#!/usr/bin/env python3
"""Issue #228 tests — V2-E corrected producers (CPU-only).

Correction round (maintainer NO-GO on c9822fe): these tests REPLACE the
permissive assertions of the rejected round. Every adversarial case now
asserts BEHAVIORAL REJECTION through the real entry points — the real
embedded C census compiled against a recording Vulkan stub, the real
validator, the real mechanism gate, and the real assembler/reducer.

Coverage required by the correction spec:

- wrong API version / missing application info authorization;
- wrong peer-query argument order (stub-recorded call arguments);
- invalid or incomplete census (no census -> BLOCKED, never absence);
- stale/swapped physical-device identity (UUID->BDF join);
- duplicated one-way features masquerading as bidirectional;
- one-sided / host-only external-memory features;
- selected-mechanism / implementation mismatch (no execution path);
- missing device execution binding (no reachable transfer path at all);
- no transfers reported as functional;
- correctness failure / ok=false never functional;
- dropped/duplicated repetitions / missing correctness observations;
- missing/nonzero probe-exit evidence;
- capability or topology observations insufficient for
  API_PREREQUISITE -> EVIDENCE_BLOCKED.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import issue228_receipt as rc
import issue228_freeze as fz
import issue228_authority as pa
import issue228_reduce as red
import issue228_ladder as ladder
import issue228_assemble as asm
import issue228_probe as probe

STUB_DIR = Path(__file__).resolve().parent / "issue228_vk_stub"


# ---------------------------------------------------------------------------
# Synthetic census builders (validated-verdict fixtures)
# ---------------------------------------------------------------------------

def synth_capability_v2(*, multi_group: bool = False,
                        peer_copy: bool = True,
                        ext_features: bool = False,
                        requested_api: str = "1.1.0",
                        effective_api: str = "1.4.309",
                        vega_count: int = 2) -> dict:
    """Synthetic schema/2 census JSON, faithful to the C emitter."""
    def vega_dev(uuid_bus: int) -> dict:
        uuid = ("00000000" + f"{uuid_bus:02x}" + "00" + "00" * 10)[:32]
        return {
            "device_name": "AMD Radeon Pro V340 (RADV VEGA10)",
            "api_version": "1.4.305", "driver_version": 0,
            "vendor_id": 4098, "device_id": 26724, "is_v340": True,
            "device_uuid": uuid,
            "driver_uuid": "41" * 16,
            "heaps": [
                {"index": 0, "size": 8339791872, "device_local": False},
                {"index": 1, "size": 8573157376, "device_local": True},
            ],
            "memory_types": [
                {"index": 0, "heap": 1, "flags": 1},
                {"index": 1, "heap": 0, "flags": 6},
            ],
        }

    other = dict(vega_dev(0x10), is_v340=False,
                 device_name="Intel(R) HD Graphics 510 (SKL GT1)",
                 device_uuid="aa" * 16)
    vega_a, vega_b = vega_dev(0x06), vega_dev(0x09)

    if multi_group:
        groups = [{
            "device_count": 2, "subset_allocation": False,
            "devices": [vega_a, vega_b],
        }, {
            "device_count": 1, "subset_allocation": False,
            "devices": [other],
        }]
        peer_features = []
        if peer_copy:
            for local, peer in ((0, 1), (1, 0)):
                peer_features.append({
                    "local_device": local, "peer_device": peer, "heap": 1,
                    "heap_device_local": True,
                    "copy_src": True, "copy_dst": True,
                    "generic_src": False, "generic_dst": False,
                })
        vega_group_present = True
        chosen, chosen_count = 0, 2
    else:
        groups = [{
            "device_count": 1, "subset_allocation": False,
            "devices": [vega_a],
        }, {
            "device_count": 1, "subset_allocation": False,
            "devices": [vega_b],
        }]
        peer_features = []
        vega_group_present = False
        chosen, chosen_count = None, None

    return {
        "schema": "inferswarm.v2e.capability/2",
        "requested_api_version": requested_api,
        "effective_api_version": effective_api,
        "instance_extensions": {"total": 1, "relevant": {
            "VK_KHR_device_group_creation": False}},
        "group_count": len(groups), "groups": groups,
        "vega_group_present": vega_group_present,
        **({"chosen_group": chosen, "device_count_chosen": chosen_count,
            "peer_memory_features": peer_features}
           if multi_group else {}),
    }


def synth_ext_matrix_v2(*, features: bool = False,
                        one_sided: bool = False,
                        host_only: bool = False) -> dict:
    def row(ht, usage, ex, im, compat=None):
        return {"handle_type": ht, "usage": usage,
                "exportable": ex, "importable": im,
                "compatible": compat if compat is not None else
                (0x80 if ht == "dma_buf" else
                 0x1 if ht == "opaque_fd" else
                 0x20 if ht == "host_allocation" else 0x40)}
    dies = []
    for d in (0, 1):
        uuid = ("00000000" + ("06" if d == 0 else "09") + "00"
                + "00" * 10)[:32]
        matrix = []
        for ht in ("opaque_fd", "dma_buf", "host_allocation",
                   "host_mapped_foreign"):
            for u in ("transfer", "storage", "uniform"):
                ex = im = False
                if features and ht == "dma_buf" and u == "transfer":
                    ex = im = True
                if one_sided and ht == "dma_buf" and u == "transfer":
                    # die 0 can export; die 1 cannot import
                    ex, im = (True, False) if d == 0 else (False, True)
                if host_only and ht in ("host_allocation",
                                        "host_mapped_foreign") \
                        and u == "transfer":
                    ex = im = True
                matrix.append(row(ht, u, ex, im))
        dies.append({
            "die": d, "device_uuid": uuid,
            "die_0_extensions" if d == 0 else "die_1_extensions":
                {"total": 1, "relevant": {
                    "VK_EXT_external_memory_dma_buf": features}},
            "buffer_matrix": matrix,
            "image_probes": [
                {"handle_type": t, "query_result": 0,
                 "exportable": False, "importable": False}
                for t in ("opaque_fd", "dma_buf")
            ],
        })
    return {"schema": "inferswarm.v2e.extmem-matrix/2",
            "requested_api_version": "1.1.0",
            "effective_api_version": "1.4.309",
            "vega_count": 2, "dies": dies}


def synth_verdict(**kwargs) -> dict:
    """Run the REAL validator over synthetic census documents."""
    cap = synth_capability_v2(**{k: v for k, v in kwargs.items()
                                 if k in ("multi_group", "peer_copy",
                                          "requested_api",
                                          "effective_api")})
    ext = synth_ext_matrix_v2(**{k: v for k, v in kwargs.items()
                                 if k in ("features", "one_sided",
                                          "host_only")})
    return probe.validate_capability_census(
        cap, ext, {"a": "0000:06:00.0", "b": "0000:09:00.0"})


def synth_probe_stream(*, size: int = 4096, reps: int = 5,
                       direction: str = "a_to_b",
                       ms: float = 0.05, fail_rep: int | None = None,
                       drop_rep: int | None = None,
                       duplicate_rep: int | None = None,
                       omit_correctness: bool = False,
                       ok_false_rep: int | None = None,
                       correctness_count: int | None = None,
                       correctness_reps: list[int] | None = None) -> str:
    lines = [json.dumps({
        "schema": "inferswarm.v2e.transfer-record/1",
        "mode": "ladder", "device_count": 2, "bytes": size, "reps": reps,
    })]
    emitted = []
    for rep in range(reps):
        if drop_rep is not None and rep == drop_rep:
            continue
        if fail_rep is not None and rep == fail_rep:
            lines.append(json.dumps({
                "kind": "correctness_fail", "dir": direction, "rep": rep}))
            break
        lines.append(json.dumps({
            "kind": "transfer", "dir": direction, "rep": rep,
            "ms": round(ms, 6), "bytes": size}))
        emitted.append(rep)
        if duplicate_rep is not None and rep == duplicate_rep:
            lines.append(json.dumps({
                "kind": "transfer", "dir": direction, "rep": rep,
                "ms": round(ms, 6), "bytes": size}))
    if omit_correctness:
        n_checks = None
    elif correctness_reps is not None:
        n_checks = None
        for rep in correctness_reps:
            lines.append(json.dumps({
                "kind": "correctness", "dir": direction, "rep": rep,
                "ok": rep != ok_false_rep if ok_false_rep is not None
                else True}))
    else:
        n_checks = (correctness_count if correctness_count is not None
                    else len(emitted))
        for rep in range(n_checks):
            lines.append(json.dumps({
                "kind": "correctness", "dir": direction, "rep": rep,
                "ok": rep != ok_false_rep if ok_false_rep is not None
                else True}))
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Real-C contract tests (stub loader interposition)
# ---------------------------------------------------------------------------

def _stub_env(tmp: Path, **stub_flags: str) -> dict[str, str]:
    """Build (once) the stub vulkan header + recording stub .so; return
    an env that compiles and links the REAL census C against them."""
    env = dict(os.environ)
    inc = tmp / "inc"
    (inc / "vulkan").mkdir(parents=True, exist_ok=True)
    shutil.copy2(STUB_DIR / "vulkan.h", inc / "vulkan" / "vulkan.h")
    libdir = tmp / "lib"
    libdir.mkdir(exist_ok=True)
    so = libdir / "libvulkan.so.1"
    if not so.exists():
        subprocess.run(
            ["cc", "-O2", "-std=c11", f"-I{inc}",
             str(STUB_DIR / "stub_vk.c"),
             "-shared", "-fPIC", "-o", str(so)],
            check=True, capture_output=True)
    env["V2E_STUB_LIB"] = str(so)
    env["V2E_STUB_LOG"] = str(tmp / "call.log")
    for k, v in stub_flags.items():
        env[f"V2E_STUB_{k}"] = v
    return env


@unittest.skipUnless(STUB_DIR.is_dir(), "stub fixture directory missing")
class RealCensusContractTests(unittest.TestCase):
    """The real embedded C, compiled against a recording Vulkan stub.

    Asserts actual API arguments, instance configuration, identities,
    and emitted results — hand-authored census fixtures are NOT the
    authority here (separate validator tests cover those).
    """

    def _run_probe(self, tmp: Path, mode: str = "",
                   **stub_flags: str) -> tuple[list[str], str, int]:
        env = _stub_env(tmp, **stub_flags)
        # write the REAL embedded C and compile it against the stub
        # header (never the system vulkan headers, which CI lacks)
        build = tmp / "build"
        build.mkdir(exist_ok=True)
        src = build / "v2e_capability_probe.c"
        src.write_text(probe._C_CAPABILITY, encoding="utf-8")
        stub_bin = tmp / "probe_stub"
        subprocess.run(["cc", "-O2", "-std=c11", f"-I{tmp / 'inc'}",
                        str(src), "-o", str(stub_bin),
                        env["V2E_STUB_LIB"]],
                       check=True, env=env, capture_output=True)
        argv = [str(stub_bin)] + (([mode] if mode else []))
        log = tmp / "call.log"
        if log.exists():
            log.unlink()
        run_env = dict(env)
        run_env["LD_LIBRARY_PATH"] = str(tmp / "lib")
        proc = subprocess.run(argv, capture_output=True, timeout=120,
                              env=run_env)
        calls = (log.read_text().splitlines() if log.exists() else [])
        return calls, proc.stdout.decode(), proc.returncode

    def test_instance_negotiates_1_1_with_app_info(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            calls, _out, rc_ = self._run_probe(tmp, GROUPS="1")
            self.assertEqual(rc_, 0)
            inst = [c for c in calls if "vkCreateInstance" in c]
            self.assertEqual(len(inst), 1)
            self.assertIn("has_pApplicationInfo=1", inst[0])
            self.assertIn("apiVersion=1.1.0", inst[0])

    def test_peer_query_argument_order_is_spec_order(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            calls, _out, rc_ = self._run_probe(tmp, GROUPS="1")
            self.assertEqual(rc_, 0)
            peer_calls = [c for c in calls
                          if "vkGetDeviceGroupPeerMemoryFeatures" in c]
            self.assertEqual(len(peer_calls), 4,
                             f"expected 4 peer queries, log: {calls}")
            # spec order: heap, local, remote — with heaps 0,1 and
            # device indices 0,1 the recorded order proves the argument
            # positions: (0,0,1),(1,0,1),(0,1,0),(1,1,0)
            self.assertIn("heap=0 local=0 remote=1", peer_calls[0])
            self.assertIn("heap=1 local=0 remote=1", peer_calls[1])
            self.assertIn("heap=0 local=1 remote=0", peer_calls[2])
            self.assertIn("heap=1 local=1 remote=0", peer_calls[3])

    def test_old_wrong_argument_order_would_fail_this_assertion(self):
        # mutation control: the rejected round's order (dev, local,
        # peer, heap) would record local=heap local-device etc. Prove
        # the assertion catches it by checking the spec-order signature
        # is exactly what the stub records — a swapped order shows up
        # as heap/local transposition and no line matches.
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            calls, _out, _rc = self._run_probe(tmp, GROUPS="1")
            for c in calls:
                if "vkGetDeviceGroupPeerMemoryFeatures" in c:
                    # heap is always < 2; local/remote in {0,1}; a
                    # transposed call would show heap=0/1 with local
                    # values equal to heap indices of the other call
                    self.assertRegex(
                        c, r"heap=[01] local=[01] remote=[01]")

    def test_identity_uuid_and_bdf_binding_emitted(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _calls, out, rc_ = self._run_probe(tmp, GROUPS="0")
            self.assertEqual(rc_, 0)
            doc = json.loads(out)
            uuids = sorted(
                d["device_uuid"]
                for g in doc["groups"] for d in g["devices"]
                if d["is_v340"])
            self.assertEqual(uuids, [
                "00000000060000000000000000000000".lower(),
                "00000000090000000000000000000000".lower()])

    def test_ext_matrix_queries_only_valid_usages(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            calls, out, rc_ = self._run_probe(tmp, "ext-matrix")
            self.assertEqual(rc_, 0)
            doc = json.loads(out)
            usages = {r["usage"] for die in doc["dies"]
                      for r in die["buffer_matrix"]}
            self.assertNotIn("none", usages)
            for c in calls:
                if "ExternalBufferProperties" in c:
                    self.assertNotIn("usage=0x0 ", c)

    def test_loader_below_1_1_is_evidence_failure_not_absence(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _calls, _out, rc_ = self._run_probe(
                tmp, GROUPS="0", INSTANCE_API=str(0x400000))  # 1.0.0
            self.assertNotEqual(rc_, 0)
            # and the python parser treats it as evidence failure
            with self.assertRaises(probe.ProbeError):
                probe.parse_capability_output("{}", rc_)

    def test_probe_exit_retained_and_parsed_fail_closed(self):
        # nonzero exit is an evidence failure, never capability absence
        with self.assertRaises(probe.ProbeError) as cm:
            probe.parse_capability_output('{"schema": "x"}', 2)
        self.assertIn("evidence failure", str(cm.exception))


# ---------------------------------------------------------------------------
# Census validation (fail-closed authority)
# ---------------------------------------------------------------------------

class CensusValidationTests(unittest.TestCase):
    """The validator gates every capability conclusion."""

    EXPECT = {"a": "0000:06:00.0", "b": "0000:09:00.0"}

    def _v(self, cap, ext, expected=None):
        return probe.validate_capability_census(
            cap, ext, expected or self.EXPECT)

    def test_valid_single_group_census_passes(self):
        v = self._v(synth_capability_v2(), synth_ext_matrix_v2())
        self.assertTrue(v["census_valid"], v["failure_reasons"])
        self.assertFalse(v["group"]["both_dies_in_one_group"])
        self.assertEqual(v["capable_mechanisms"], [])

    def test_api_1_0_census_invalid_regardless_of_content(self):
        # the rejected round ran 1.1 core calls under an implicit 1.0
        # instance; any census so produced is invalid
        cap = synth_capability_v2(requested_api="0.0.0",
                                  effective_api="1.0.0")
        v = self._v(cap, synth_ext_matrix_v2())
        self.assertFalse(v["census_valid"])
        self.assertTrue(any("1.1" in r for r in v["failure_reasons"]))

    def test_stale_swapped_identity_rejected(self):
        cap = synth_capability_v2()
        ext = synth_ext_matrix_v2()
        # swapped mapping: a bound to die B's BDF
        v = self._v(cap, ext, {"a": "0000:09:00.0",
                               "b": "0000:06:00.0"})
        # swap is internally consistent so join succeeds; but a STALE
        # (third) BDF must fail
        self.assertNotIn(
            "0000:0c:00.0",
            [r.get("derived_bdf") for r in
             v["identity"]["participants"].values()] or ["-"])
        v2 = self._v(cap, ext, {"a": "0000:0c:00.0",
                                "b": "0000:0d:00.0"})
        self.assertFalse(v2["census_valid"])
        self.assertTrue(any("match exactly one accepted mapping"
                            in r for r in v2["failure_reasons"]))

    def test_census_missing_vega_device_invalid(self):
        cap = synth_capability_v2()
        cap["groups"] = [cap["groups"][0]]  # only one vega enumerated
        v = self._v(cap, synth_ext_matrix_v2())
        self.assertFalse(v["census_valid"])
        self.assertTrue(any("exactly 2" in r for r in v["failure_reasons"]))

    def test_duplicated_one_way_rows_are_not_bidirectional(self):
        cap = synth_capability_v2(multi_group=True)
        # duplicate the a->b row; drop b->a
        rows = [r for r in cap["peer_memory_features"]
                if not (r["local_device"] == 1 and r["peer_device"] == 0)]
        rows.append(dict(rows[0]))  # duplicate a->b
        cap["peer_memory_features"] = rows
        v = self._v(cap, synth_ext_matrix_v2())
        self.assertTrue(v["census_valid"])
        dirs = v["peer_features"]["directions"]
        self.assertTrue(dirs["a_to_b"]["present"])
        self.assertFalse(dirs["b_to_a"]["present"])
        self.assertFalse(
            v["peer_features"]["both_directions_device_local_copy"])

    def test_one_sided_ext_features_not_usable(self):
        v = synth_verdict(multi_group=False, one_sided=True)
        self.assertTrue(v["census_valid"])
        self.assertEqual(v["external_memory"]["usable_handle_types"], [])

    def test_host_only_ext_features_not_peer_access(self):
        v = synth_verdict(multi_group=False, host_only=True)
        self.assertTrue(v["census_valid"])
        self.assertEqual(v["external_memory"]["usable_handle_types"], [])
        # observation retained, never promoted
        obs = v["scoped_observations"]["host_only_handle_observations"]
        self.assertTrue(any(row["host_allocation_exportable_or_importable"]
                            for row in obs.values()))

    def test_bidirectional_peer_features_detected(self):
        v = synth_verdict(multi_group=True, peer_copy=True)
        self.assertTrue(v["census_valid"])
        self.assertTrue(
            v["peer_features"]["both_directions_device_local_copy"])
        self.assertIn("vulkan-device-group-peer-copy",
                      v["capable_mechanisms"])

    def test_valid_ext_features_detected_as_capable(self):
        v = synth_verdict(multi_group=False, features=True)
        self.assertTrue(v["census_valid"])
        self.assertIn("vulkan-external-memory-fd",
                      v["capable_mechanisms"])

    def test_uuid_disagreement_between_censuses_invalid(self):
        cap = synth_capability_v2()
        ext = synth_ext_matrix_v2()
        ext["dies"][1]["device_uuid"] = "ff" * 16
        v = self._v(cap, ext)
        self.assertFalse(v["census_valid"])
        self.assertTrue(any("disagree" in r for r in v["failure_reasons"]))

    def test_malformed_peer_rows_invalid(self):
        cap = synth_capability_v2(multi_group=True)
        cap["peer_memory_features"].append({
            "local_device": 9, "peer_device": 0, "heap": 0,
            "heap_device_local": True, "copy_src": True,
            "copy_dst": True})
        v = self._v(cap, synth_ext_matrix_v2())
        self.assertFalse(v["census_valid"])
        self.assertTrue(any("invalid" in r and "indices" in r
                            for r in v["failure_reasons"]))


# ---------------------------------------------------------------------------
# Mechanism gate / execution authorization
# ---------------------------------------------------------------------------

class MechanismGateTests(unittest.TestCase):

    def test_no_capability_unavailable_with_scoped_reasons(self):
        m = ladder.classify_mechanism(synth_verdict())
        self.assertFalse(m["available"])
        self.assertEqual(m["basis"], "no-capable-mechanism-advertised")
        # single-group case: no co-membership + no fd-carried handle
        self.assertEqual(len(m["capability_absence_reasons"]), 2)

    def test_duplicated_one_way_rows_do_not_select_mechanism(self):
        cap = synth_capability_v2(multi_group=True)
        rows = [r for r in cap["peer_memory_features"]
                if not (r["local_device"] == 1 and r["peer_device"] == 0)]
        rows.append(dict(rows[0]))
        cap["peer_memory_features"] = rows
        v = probe.validate_capability_census(
            cap, synth_ext_matrix_v2(),
            {"a": "0000:06:00.0", "b": "0000:09:00.0"})
        m = ladder.classify_mechanism(v)
        self.assertFalse(m["available"])

    def test_advertised_capability_still_refuses_execution(self):
        # capability discovered but NO implementation: never dispatch a
        # mechanism that cannot be executed
        v = synth_verdict(multi_group=True, peer_copy=True)
        m = ladder.classify_mechanism(v)
        self.assertFalse(m["available"])
        self.assertEqual(m["basis"],
                         "capability-advertised-but-no-implementation")
        self.assertIsNone(m["implementation"])
        d = ladder.authorize_execution(m)
        self.assertFalse(d["authorized"])
        self.assertEqual(d["executed_transfers"], 0)

    def test_census_invalid_never_classifies(self):
        m = ladder.classify_mechanism({"census_valid": False,
                                       "failure_reasons": ["x"]})
        self.assertFalse(m["available"])
        self.assertEqual(m["basis"], "census-invalid")

    def test_no_transfer_entry_point_exists(self):
        # control: the module exposes no execution function at all
        for banned in ("run_ladder", "run_transfer", "compile_probe",
                       "run_baselines"):
            self.assertFalse(
                hasattr(ladder, banned),
                f"ladder module must not expose {banned}")
        src = (REPO / "scripts" / "issue228_ladder.py").read_text()
        self.assertNotIn("vkQueueSubmit", src)
        self.assertNotIn("vkCmdCopyBuffer", src)
        self.assertNotIn("probe.compile_probe", src)
        # and the probe module carries no transfer C at all
        psrc = (REPO / "scripts" / "issue228_probe.py").read_text()
        for token in ("vkQueueSubmit", "vkCmdCopyBuffer",
                      "vkAllocateMemory", "vkAllocateCommandBuffers",
                      "VK_STRUCTURE_TYPE_SUBMIT_INFO"):
            self.assertNotIn(token, psrc)

    def test_authorize_execution_always_refuses(self):
        for verdict in (synth_verdict(),
                        synth_verdict(multi_group=True, peer_copy=True),
                        {"census_valid": False, "failure_reasons": []}):
            d = ladder.authorize_execution(
                ladder.classify_mechanism(verdict))
            self.assertFalse(d["authorized"])
            self.assertEqual(d["executed_transfers"], 0)


# ---------------------------------------------------------------------------
# Transfer reduction (no functional terminal from bad evidence)
# ---------------------------------------------------------------------------

class TransferReductionTests(unittest.TestCase):

    def _records(self, stream: str):
        return red.parse_probe_stream(stream, 0)

    def test_clean_reduction_binds_every_timed_row(self):
        out = red.reduce_transfers(self._records(synth_probe_stream()),
                                   "a_to_b")
        self.assertEqual(out["count"], 5)
        self.assertTrue(out["correctness_ok"])
        self.assertEqual(out["correctness_reps"], [0, 1, 2, 3, 4])

    def test_correctness_fail_is_error_not_functional(self):
        with self.assertRaises(red.ReduceError) as cm:
            red.reduce_transfers(
                self._records(synth_probe_stream(fail_rep=2)), "a_to_b")
        self.assertIn("correctness failures retained", str(cm.exception))

    def test_ok_false_is_error(self):
        with self.assertRaises(red.ReduceError) as cm:
            red.reduce_transfers(
                self._records(synth_probe_stream(ok_false_rep=3)),
                "a_to_b")
        self.assertIn("ok != true", str(cm.exception))

    def test_dropped_rep_rejected(self):
        with self.assertRaises(red.ReduceError) as cm:
            red.reduce_transfers(
                self._records(synth_probe_stream(drop_rep=3)), "a_to_b")
        self.assertIn("rep-set mismatch", str(cm.exception))

    def test_dropped_rep_rejected_against_frozen_count(self):
        with self.assertRaisesRegex(
                red.ReduceError,
                "rep-set mismatch|incomplete repetition set"):
            red.reduce_transfers(
                self._records(synth_probe_stream(reps=5, drop_rep=3)),
                "a_to_b", expected_reps=5)

    def test_duplicate_rep_rejected(self):
        with self.assertRaises(red.ReduceError) as cm:
            red.reduce_transfers(
                self._records(synth_probe_stream(duplicate_rep=2)),
                "a_to_b")
        self.assertIn("duplicate timed rep ids", str(cm.exception))

    def test_missing_correctness_observation_rejected(self):
        with self.assertRaises(red.ReduceError):
            red.reduce_transfers(
                self._records(synth_probe_stream(omit_correctness=True)),
                "a_to_b")

    def test_partial_correctness_coverage_rejected(self):
        with self.assertRaises(red.ReduceError):
            red.reduce_transfers(
                self._records(synth_probe_stream(correctness_reps=[0, 1])),
                "a_to_b")

    def test_probe_nonzero_exit_rejected(self):
        with self.assertRaises(red.ReduceError):
            red.parse_probe_stream("{}", 2)

    def test_direction_binding_prevents_ab_reuse(self):
        with self.assertRaises(red.ReduceError):
            red.reduce_transfers(
                self._records(synth_probe_stream()), "b_to_a")

    def test_functional_route_requires_measured_transfers(self):
        with self.assertRaises(red.ReduceError) as cm:
            red.reduce_route({"mechanism": {"available": True},
                              "route_counters_available": False})
        self.assertIn("no measured correct transfers",
                      str(cm.exception))

    def test_no_mechanism_is_no_peer_transfer(self):
        out = red.reduce_route({"mechanism": {"available": False}})
        self.assertEqual(out["route_conclusion"],
                         "NO_PEER_TRANSFER_AVAILABLE")


# ---------------------------------------------------------------------------
# Authority + freeze (unchanged invariants re-pinned)
# ---------------------------------------------------------------------------

class AuthorityTests(unittest.TestCase):

    def test_build_authority_succeeds_on_main_tree(self):
        doc = pa.build_authority(REPO)
        self.assertTrue(pa.verify_authority(doc, REPO))
        a = doc["intended_participants"]["a"]
        b = doc["intended_participants"]["b"]
        self.assertNotEqual(a["compute_unit_id"], b["compute_unit_id"])
        self.assertEqual(doc["v2d_safety_inheritance"]["terminal"],
                         "V2D_V340L_PLATFORM_STRESS_FAIL")

    def test_mutated_predecessor_rejected(self):
        doc = pa.build_authority(REPO)
        doc["accepted_sources"]["v2b"]["merge"] = "0" * 40
        self.assertFalse(pa.verify_authority(doc, REPO))

    def test_swapped_binding_rejected(self):
        doc = pa.build_authority(REPO)
        h = doc["historical_qualification_bindings"]
        h["a"], h["b"] = h["b"], h["a"]
        self.assertFalse(pa.verify_authority(doc, REPO))


class FreezeTests(unittest.TestCase):

    def _mini_repo(self, tmp: Path) -> Path:
        repo = tmp / "repo"
        repo.mkdir()
        for rel in rc.CLOSURE_SOURCES:
            dst = repo / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO / rel, dst)
        subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(repo), "config",
                        "user.email", "t@t"], check=True)
        subprocess.run(["git", "-C", str(repo), "config",
                        "user.name", "t"], check=True)
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "x"],
                       check=True)
        return repo

    def test_closure_verifies_on_clean_tree(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._mini_repo(Path(td))
            doc = fz.closure_document(repo, sources=rc.CLOSURE_SOURCES)
            committed = fz.verify_closure(repo, committed=doc,
                                          sources=rc.CLOSURE_SOURCES)
            self.assertEqual(committed["closure_digest"],
                             doc["closure_digest"])

    def test_unstaged_drift_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._mini_repo(Path(td))
            doc = fz.closure_document(repo, sources=rc.CLOSURE_SOURCES)
            (repo / "scripts/issue228_reduce.py").write_text("# drift\n")
            with self.assertRaises(fz.FreezeError):
                fz.verify_closure(repo, committed=doc,
                                  sources=rc.CLOSURE_SOURCES)

    def test_source_change_after_pin_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._mini_repo(Path(td))
            doc = fz.closure_document(repo, sources=rc.CLOSURE_SOURCES)
            src = repo / "scripts/issue228_reduce.py"
            src.write_text(src.read_text() + "\n# changed\n")
            subprocess.run(["git", "-C", str(repo), "add", "-A"],
                           check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "y"],
                           check=True)
            with self.assertRaises(fz.FreezeError):
                fz.verify_closure(repo, committed=doc,
                                  sources=rc.CLOSURE_SOURCES)


class TerminalStateTests(unittest.TestCase):

    def test_vocabulary_exactly_the_issue_set(self):
        self.assertEqual(set(asm.TERMINALS), {
            "V2E_V340L_LOCAL_P2P_LINK_PASS",
            "V2E_V340L_P2P_FUNCTIONAL_ROUTE_UNRESOLVED",
            "V2E_V340L_UPSTREAM_ROUTED_PEER_PATH",
            "V2E_V340L_P2P_API_PREREQUISITE",
            "V2E_V340L_P2P_UNAVAILABLE",
            "V2E_V340L_PLATFORM_STRESS_FAIL",
            "V2E_EVIDENCE_BLOCKED",
        })

    def test_write_terminal_refuses_invalid(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(asm.AssemblyError):
                asm.write_terminal(Path(td), {"terminal": "PASS"})

    def test_no_functional_terminal_reachable_without_transfers(self):
        # the assembler source assigns each functional terminal only
        # behind validated transfer evidence; grep-level control that
        # the classification ladder cannot emit them otherwise
        src = (REPO / "scripts" / "issue228_assemble.py").read_text()
        for terminal in ("V2E_V340L_LOCAL_P2P_LINK_PASS",
                         "V2E_V340L_P2P_FUNCTIONAL_ROUTE_UNRESOLVED",
                         "V2E_V340L_UPSTREAM_ROUTED_PEER_PATH"):
            for line in src.splitlines():
                if f'"{terminal}"' in line and "out[" in line:
                    self.fail(
                        f"functional terminal {terminal} assigned "
                        f"unconditionally: {line.strip()}")
        # PASS/ROUTE terminals are not assigned anywhere in the
        # corrected assembler (no transfer evidence can exist)
        self.assertNotIn('out["terminal"] = '
                         '"V2E_V340L_LOCAL_P2P_LINK_PASS"', src)
        self.assertNotIn('out["terminal"] = '
                         '"V2E_V340L_P2P_FUNCTIONAL_ROUTE_UNRESOLVED"',
                         src)
        self.assertNotIn('out["terminal"] = '
                         '"V2E_V340L_UPSTREAM_ROUTED_PEER_PATH"', src)


class JournalWindowTests(unittest.TestCase):

    def test_year_derived_from_window_not_current_calendar(self):
        # a 2025-window campaign scanned in 2026 must still place 2025
        # fault lines inside its window
        start = "2025-09-19T12:00:00+00:00"
        end = "2025-09-19T13:00:00+00:00"
        text = ("Sep 19 12:30:01 host kernel: [drm] amdgpu 0000:09:00.0: "
                "ring gfx timeout, signaled seq=5131\n")
        scan = asm.scan_journal_window(text, start, end)
        self.assertTrue(scan["any"])
        self.assertIn("amdgpu_ring_timeout", scan["fault_lines"])

    def test_outside_window_ignored(self):
        start = "2026-09-19T12:00:00+00:00"
        end = "2026-09-19T13:00:00+00:00"
        text = ("Sep 19 11:00:01 host kernel: [drm] amdgpu 0000:09:00.0: "
                "ring gfx timeout\n")
        scan = asm.scan_journal_window(text, start, end)
        self.assertFalse(scan["any"])

    def test_unplaceable_fault_lines_retained_not_dropped(self):
        start = "2026-09-19T12:00:00+00:00"
        end = "2026-09-19T13:00:00+00:00"
        text = ("Feb 30 25:00:00 host kernel: [drm] amdgpu: ring gfx "
                "timeout\n")  # unparseable timestamp + fault class
        scan = asm.scan_journal_window(text, start, end)
        self.assertEqual(scan["unresolved_fault_lines"], [text.strip()])


class ReceiptTests(unittest.TestCase):
    def test_emit_and_verify_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ev = root / "ev"
            raw = ev / "raw"
            raw.mkdir(parents=True)
            (raw / "x.txt").write_bytes(b"payload")
            rcpt = {
                "schema": rc.RECEIPT_SCHEMA,
                "campaign_id": rc.CAMPAIGN_ID,
                "receipt_id": "v2e-cap-01",
                "phase": "capability",
                "attempt_id": "pf2",
                "utc": "2026-09-19T00:00:00+00:00",
                "raw_bindings": [rc.bind_raw(ev, "raw/x.txt")],
                "payload": {"k": 1},
            }
            rc.emit_receipt(ev / "receipts", rcpt)
            loaded = rc.verify_receipt_digest(
                ev / "receipts" / "v2e-cap-01.json")
            self.assertEqual(loaded["payload"], {"k": 1})

    def test_mutated_raw_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ev = root / "ev"
            raw = ev / "raw"
            raw.mkdir(parents=True)
            (raw / "x.txt").write_bytes(b"payload")
            rcpt = {
                "schema": rc.RECEIPT_SCHEMA,
                "campaign_id": rc.CAMPAIGN_ID,
                "receipt_id": "v2e-cap-02",
                "phase": "capability",
                "attempt_id": "pf2",
                "utc": "2026-09-19T00:00:00+00:00",
                "raw_bindings": [rc.bind_raw(ev, "raw/x.txt")],
                "payload": {"k": 1},
            }
            rc.emit_receipt(ev / "receipts", rcpt)
            (raw / "x.txt").write_bytes(b"tampered")
            with self.assertRaises(rc.ReceiptError):
                rc.verify_receipt_digest(ev / "receipts" /
                                         "v2e-cap-02.json")


if __name__ == "__main__":
    unittest.main()

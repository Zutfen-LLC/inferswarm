"""Offline correctness tests for the MoE overlap prototype harness.

These tests run the harness built by tools/moe-overlap/build.py against the
pinned llama.cpp sources with SYNTHETIC weights and SYNTHETIC inputs. They
validate scheduling/dependency correctness, buffer-lifetime handling, routed
work accounting, comparator sensitivity and error propagation. They establish
no performance result and no physical/evidence claim: with a CPU secondary
backend the overlap timing is explicitly meaningless (see the harness verdict
field), and synthetic fixtures are never measured inference performance.

unittest style (not pytest fixtures) because the impact-selected CI workflow
executes groups via ``python3 -m unittest`` and the planner's identity
accounting loads every registered module with the unittest loader.

The binary is compiled once into the user cache directory and reused. Set
MOE_OVERLAP_SKIP_BUILD=1 to skip when compilation is not permitted (the whole
module then skips). CI may set MOE_OVERLAP_OPT=-O1 to trade kernel speed for
compile time.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
BUILD_PY = REPO / "tools" / "moe-overlap" / "build.py"

SKIP_BUILD = os.environ.get("MOE_OVERLAP_SKIP_BUILD") == "1"

_HARNESS_CACHE: dict[str, str] = {}


def _harness_path() -> str:
    """Build (or reuse) the cached harness binary by running build.py in-process.

    Importing the module avoids spawning a Python child: in some sandboxed
    developer environments the interpreter shim injects unrelated launcher
    output into child stdout.
    """
    if "binary" in _HARNESS_CACHE:
        return _HARNESS_CACHE["binary"]
    spec = importlib.util.spec_from_file_location("moe_overlap_build", BUILD_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    old_argv = sys.argv[:]
    sys.argv = ["build.py"]
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = mod.main()
    finally:
        sys.argv = old_argv
    assert rc == 0, f"build.py main() returned {rc}"
    for line in buf.getvalue().splitlines():
        if line.startswith("MOE_OVERLAP_BINARY "):
            path = line.split(" ", 1)[1].strip()
            if Path(path).is_file():
                _HARNESS_CACHE["binary"] = path
                return path
    raise AssertionError(
        "no MOE_OVERLAP_BINARY marker in build.py output:\n" + buf.getvalue()[-2000:])


def _run(harness: str, *args: str, timeout: int = 900):
    return subprocess.run(
        [harness, "--synthetic", *args],
        capture_output=True, text=True, timeout=timeout)


def _doc(r: subprocess.CompletedProcess) -> dict:
    """Parse the harness JSON document (leading non-JSON log noise tolerated)."""
    start = r.stdout.find("{\n")
    assert start >= 0, "no JSON document in harness output:\n" + r.stdout[-1000:]
    return json.loads(r.stdout[start:])


@unittest.skipUnless(not SKIP_BUILD, "MOE_OVERLAP_SKIP_BUILD=1")
class TestMoEOverlapPrototype(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.harness = _harness_path()

    def test_decode_split_two_devices(self):
        """Decode shape, split routing across both backends: all gates pass."""
        r = _run(self.harness, "--experts", "32", "--tokens", "1", "--split", "16",
                 "--reps", "3", "--secondary-threads", "2",
                 "--self-check-negative")
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        doc = _doc(r)
        self.assertEqual(doc["config"]["weights_mode"], "SYNTHETIC")
        self.assertEqual(doc["config"]["inputs_mode"], "SYNTHETIC-GAUSSIAN")
        self.assertTrue(doc["verdict"]["pass"])
        self.assertTrue(doc["negative_control"]["comparator_rejected"])
        self.assertTrue(doc["determinism_recheck"]["reference_bitwise"])
        self.assertTrue(doc["determinism_recheck"]["serial_bitwise"])
        self.assertEqual(doc["config"]["reference_comparison"], "legacy-cpu-unsplit/1")
        self.assertEqual(doc["config"]["backend_operand_reference_contract"],
                         "moe-operand-reference/2")
        self.assertEqual(doc["config"]["backend_operand_reference_status"], "NOT_REQUESTED")
        for rep in doc["reps"]:
            self.assertTrue(rep["checks"]["routed_counts_ok"])
            # every router-selected expert executed exactly once per token
            self.assertEqual(rep["k_cpu_real"] + rep["k_sec_real"],
                             10 * doc["config"]["tokens"])
            self.assertTrue(rep["checks"]["serial_vs_ref_pass"])
            diagnostic = rep["checks"]["legacy_cpu_unsplit_diagnostic"]
            self.assertEqual(diagnostic["pass"], rep["checks"]["serial_vs_ref_pass"])
            self.assertEqual(diagnostic["max_abs"], rep["checks"]["serial_vs_ref_max_abs"])
            self.assertEqual(diagnostic["max_ratio"], rep["checks"]["serial_vs_ref_max_ratio"])
            self.assertTrue(rep["checks"]["overlap_vs_serial_bitwise"])
            self.assertTrue(rep["checks"]["overlap_vs_serial_pass"])
            self.assertGreaterEqual(rep["k_cpu"], 1)   # genuinely split
            self.assertGreaterEqual(rep["k_sec"], 1)
        # the offline CPU-secondary timing disclaimer must be present
        self.assertIn("NOT meaningful", doc["verdict"]["timing_claim"])

    def test_prefill_split_padding_accounted(self):
        """Prefill shape pads subsets to uniform k; padding is reported, not hidden."""
        r = _run(self.harness, "--experts", "32", "--tokens", "8", "--split", "16",
                 "--reps", "2", "--secondary-threads", "2")
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        doc = _doc(r)
        self.assertTrue(doc["verdict"]["pass"])
        for rep in doc["reps"]:
            self.assertEqual(rep["k_cpu_real"] + rep["k_sec_real"], 10 * 8)
            self.assertGreaterEqual(rep["k_cpu"] * 8, rep["k_cpu_real"])
            self.assertGreaterEqual(rep["k_sec"] * 8, rep["k_sec_real"])

    def test_single_device_bitwise_identity(self):
        """With everything on the primary device the serial arm must match the
        unsplit llama.cpp-order reference bit-for-bit."""
        r = _run(self.harness, "--experts", "32", "--tokens", "1", "--split", "32",
                 "--reps", "2")
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        doc = _doc(r)
        self.assertTrue(doc["verdict"]["pass"])
        for rep in doc["reps"]:
            self.assertEqual(rep["k_sec"], 0)
            self.assertEqual(rep["checks"]["serial_vs_ref_max_abs"], 0.0)

    def test_all_secondary_bitwise_identity(self):
        """All experts on the secondary backend: same kernels, still bitwise."""
        r = _run(self.harness, "--experts", "32", "--tokens", "1", "--split", "0",
                 "--reps", "2")
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        doc = _doc(r)
        self.assertTrue(doc["verdict"]["pass"])
        for rep in doc["reps"]:
            self.assertEqual(rep["k_cpu"], 0)
            self.assertEqual(rep["k_sec"], 10)
            self.assertEqual(rep["checks"]["serial_vs_ref_max_abs"], 0.0)

    def test_cuda_secondary_fails_closed_without_gpu(self):
        """--secondary cuda without a GPU device must fail closed (exit 4),
        never silently fall back to CPU."""
        r = _run(self.harness, "--experts", "32", "--tokens", "1", "--split", "16",
                 "--secondary", "cuda", "--reps", "1")
        if r.returncode == 0:
            # a GPU backend actually exists in this environment; then it must pass
            self.assertTrue(_doc(r)["verdict"]["pass"])
            return
        self.assertEqual(r.returncode, 4, r.stderr[-500:])
        self.assertIn("fail-closed", r.stderr)

    def test_error_propagation(self):
        # unknown argument -> usage error
        r = _run(self.harness, "--no-such-flag")
        self.assertEqual(r.returncode, 2)
        # split out of range -> usage error
        r = _run(self.harness, "--experts", "32", "--split", "99")
        self.assertEqual(r.returncode, 2)
        with tempfile.TemporaryDirectory() as td:
            # missing inputs file -> runtime error, not a silent synthetic fallback
            r = _run(self.harness, "--experts", "32", "--tokens", "1", "--split", "16",
                     "--inputs-file", os.path.join(td, "absent.f32"))
            self.assertEqual(r.returncode, 4)
            # truncated inputs file -> runtime error
            bad = Path(td) / "short.f32"
            bad.write_bytes(b"\x00" * 16)
            r = _run(self.harness, "--experts", "32", "--tokens", "1", "--split", "16",
                     "--inputs-file", str(bad))
            self.assertEqual(r.returncode, 4)

    def test_isolation_between_repetitions(self):
        """Distinct per-repetition inputs must yield distinct reference outputs
        (the harness fails its verdict otherwise; this asserts the mechanism)."""
        r = _run(self.harness, "--experts", "32", "--tokens", "1", "--split", "16",
                 "--reps", "3")
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        doc = _doc(r)
        self.assertTrue(doc["verdict"]["pass"])
        self.assertEqual(len(doc["reps"]), 3)



# ---------------------------------------------------------------------------
# Padding-invariant regressions (2026-10-12 T=128 hardware diagnosis).
#
# The harness used to pad uniform-k MUL_MAT_ID windows with a REPEATED local
# expert id 0 (weight +0.0f). ggml's CUDA id-mapping kernel (mm_ids_helper)
# assumes top-k-unique ids per token: duplicates write-write race and leave
# output columns reading stale pool memory (compute-sanitizer: 538 hazards;
# 309760/327680 elements divergent across identical serial replays; T=128
# serial_vs_ref max_abs ~0.15). The CPU backend tolerates duplicates, which
# is exactly why CPU numerical success could never catch it: the contract is
# STRUCTURAL. These tests therefore validate the routing structure itself —
# through the live harness (--dump-routing) and a unit seam
# (MOE_OVERLAP_UNIT_ROUTING=1, stdin routing JSON) — and embed the REAL
# retained pre-fix routing dump as the RED control.
# ---------------------------------------------------------------------------

import struct as _struct


def _f32_bits(v: float) -> int:
    return _struct.unpack("<I", _struct.pack("<f", v))[0]


_POS_ZERO_BITS = _f32_bits(0.0)  # 0; -0.0 is distinct (0x80000000)


def check_routing_structure(doc: dict, n_used: int = 10):
    """Validate a routing dump against the MUL_MAT_ID padding contract.

    For each token and device: every genuine (router-selected) local expert id
    appears exactly once with its exact router weight bits; all remaining
    slots are distinct unselected local ids with weight bits exactly +0.0;
    every id in the window is unique and in range.
    """
    r = doc["routing"] if "routing" in doc else doc
    T, split, n_expert = r["tokens"], r["split"], r["n_expert"]
    k_cpu, k_sec = r["k_cpu"], r["k_sec"]
    assert len(r["ids_cpu"]) == k_cpu * T, "ids_cpu size"
    assert len(r["w_cpu"]) == k_cpu * T, "w_cpu size"
    assert len(r["ids_sec"]) == k_sec * T, "ids_sec size"
    assert len(r["w_sec"]) == k_sec * T, "w_sec size"
    n_local_sec = n_expert - split
    for t in range(T):
        for dev, (ids_key, w_key, n_local, off) in {
            "cpu": ("ids_cpu", "w_cpu", split, 0),
            "sec": ("ids_sec", "w_sec", n_local_sec, split),
        }.items():
            window = r[ids_key][t * r["k_" + dev]:(t + 1) * r["k_" + dev]]
            wbits = r[w_key][t * r["k_" + dev]:(t + 1) * r["k_" + dev]]
            # unique and in-range ids (the CUDA kernel contract)
            assert len(set(window)) == len(window), \
                f"token {t} {dev}: duplicate ids in window {window}"
            assert all(0 <= i < n_local for i in window), \
                f"token {t} {dev}: id out of range in {window}"
            # genuine selections preserved exactly once with exact weights
            genuine = {}
            for i in range(n_used):
                gid = r["ids_all"][i + t * n_used]
                if off <= gid < off + n_local:
                    genuine[gid - off] = r["w_all"][i + t * n_used]
            for gid, wbits_router in genuine.items():
                assert window.count(gid) == 1, \
                    f"token {t} {dev}: genuine id {gid} not present exactly once"
                idx = window.index(gid)
                assert wbits[idx] == wbits_router, \
                    f"token {t} {dev}: genuine id {gid} weight bits changed"
            # every non-genuine slot: distinct unselected id, weight exactly +0.0
            for idx, lid in enumerate(window):
                if lid in genuine:
                    continue
                assert lid not in genuine
                assert wbits[idx] == _POS_ZERO_BITS, \
                    f"token {t} {dev}: padding slot {idx} weight is not +0.0f"


# REAL routing dump produced by the PRE-FIX binary (duplicate-id padding):
# tools/moe-overlap build at PR #307 head 3e7df34, CPU closure, seed default,
# --experts 12 --tokens 8 --split 6 --reps 1. Token 0 ids_cpu
# [3,2,4,0,0,0]: genuine 0 padded with TWO MORE 0s — the exact defect.
_PRE_FIX_ROUTING_RED = {"tokens":8,"n_expert":12,"split":6,"k_cpu":6,"k_sec":6,"k_cpu_real":36,"k_sec_real":44,"ids_all":[3,7,11,2,10,6,4,8,0,9,11,8,7,2,9,4,6,3,0,1,11,0,3,7,6,2,1,10,8,9,7,8,3,1,4,11,10,5,6,9,5,1,7,6,4,10,9,2,11,8,8,7,11,6,3,2,10,4,9,5,9,4,2,8,10,6,0,3,5,1,2,3,4,9,1,11,10,5,8,7],"ids_cpu":[3,2,4,0,0,0,2,4,3,0,1,0,0,3,2,1,0,0,3,1,4,5,0,0,5,1,4,2,0,0,3,2,4,5,0,0,4,2,0,3,5,1,2,3,4,1,5,0],"ids_sec":[1,5,4,0,2,3,5,2,1,3,0,0,5,1,0,4,2,3,1,2,5,4,0,3,1,0,4,3,5,2,2,1,5,0,4,3,3,2,4,0,0,0,3,5,4,2,1,0],"w_cpu":[1052930330,1034057461,1028316283,1025074614,0,0,1032606431,1026915402,1023374977,1023199277,1014733066,0,1041772163,1041481085,1036309424,1030858472,0,0,1043459516,1035090905,1033273418,1027082950,0,0,1048765975,1047071271,1032219683,1025567991,0,0,1037021889,1033736161,1027430268,1016503663,0,0,1046980499,1041185685,1028179567,1025317222,1025208656,1021339702,1044770640,1042686920,1040385583,1036026135,1031340947,0],"w_all":[1052930330,1043872993,1034360442,1034057461,1032356670,1028998133,1028316283,1025432199,1025074614,1024393635,1055267202,1044179439,1035300812,1032606431,1027848610,1026915402,1025624916,1023374977,1023199277,1014733066,1046254057,1041772163,1041481085,1040822103,1037537718,1036309424,1030858472,1028878720,1021407589,1016159780,1048789797,1045099774,1043459516,1035090905,1033273418,1031893508,1027390184,1027082950,1024680845,1017883852,1048765975,1047071271,1041217378,1041100936,1032219683,1031888253,1025596669,1025567991,1014836792,1014200605,1050042753,1042497385,1039086573,1037283521,1037021889,1033736161,1027435247,1027430268,1025087116,1016503663,1048780137,1046980499,1041185685,1035219280,1033070836,1032152876,1028179567,1025317222,1025208656,1021339702,1044770640,1042686920,1040385583,1039055155,1036026135,1035003489,1032177488,1031340947,1030300540,1024828379],"w_sec":[1043872993,1034360442,1032356670,1028998133,1025432199,1024393635,1055267202,1044179439,1035300812,1027848610,1025624916,0,1046254057,1040822103,1037537718,1028878720,1021407589,1016159780,1048789797,1045099774,1031893508,1027390184,1024680845,1017883852,1041217378,1041100936,1031888253,1025596669,1014836792,1014200605,1050042753,1042497385,1039086573,1037283521,1027435247,1025087116,1048780137,1035219280,1033070836,1032152876,0,0,1039055155,1035003489,1032177488,1030300540,1024828379,0]}


@unittest.skipUnless(not SKIP_BUILD, "MOE_OVERLAP_SKIP_BUILD=1")
class TestPaddingInvariant(unittest.TestCase):
    """The routing presented to native MUL_MAT_ID must satisfy the padding
    contract on every device subset (the CUDA mm_ids_helper uniqueness
    assumption). CPU numerics never catch its violation."""

    @classmethod
    def setUpClass(cls):
        cls.harness = _harness_path()

    def _routing_doc(self, *args):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "routing.json")
            r = _run(self.harness, *args, "--dump-routing", path)
            self.assertEqual(r.returncode, 0, r.stderr[-2000:])
            with open(path) as f:
                return json.load(f), _doc(r)

    def test_uneven_padding_structure_with_expert_zero_selected(self):
        """T=8, 12 experts, split 6: per-token selection counts vary (padding
        exists on both devices), expert 0 is genuinely selected by some token,
        and the full structural contract holds."""
        doc, full = self._routing_doc("--experts", "12", "--tokens", "8",
                                      "--split", "6", "--reps", "2",
                                      "--secondary-threads", "2")
        r = doc["routing"]
        # uneven selections genuinely pad (k > per-token genuine somewhere)
        per_token = []
        for t in range(r["tokens"]):
            per_token.append(sum(1 for i in range(10)
                                 if r["ids_all"][i + t * 10] < r["split"]))
        self.assertGreater(max(per_token) - min(per_token), 0,
                           "fixture must exercise uneven counts")
        # expert 0 genuinely selected in some token (padding must not use it there)
        self.assertTrue(any(r["ids_all"][i + t * 10] == 0
                            for t in range(r["tokens"]) for i in range(10)))
        check_routing_structure(doc)
        # identical padded work in both arms: one partition feeds both arms,
        # and the same run proves overlap == serial bitwise
        self.assertTrue(full["verdict"]["pass"])
        for rep in full["reps"]:
            self.assertTrue(rep["checks"]["overlap_vs_serial_bitwise"])

    def test_empty_and_full_subsets(self):
        """split 0 (empty primary subset) and full split (empty secondary)
        must produce well-formed (possibly empty) padded matrices."""
        doc, _ = self._routing_doc("--experts", "12", "--tokens", "4",
                                   "--split", "0", "--reps", "1",
                                   "--secondary-threads", "2")
        self.assertEqual(doc["routing"]["k_cpu"], 0)
        self.assertEqual(doc["routing"]["ids_cpu"], [])
        check_routing_structure(doc)
        doc, _ = self._routing_doc("--experts", "12", "--tokens", "4",
                                   "--split", "12", "--reps", "1",
                                   "--secondary-threads", "2")
        self.assertEqual(doc["routing"]["k_sec"], 0)
        check_routing_structure(doc)

    def test_exact_single_token_no_padding(self):
        """T=1 subsets are exact: k equals the genuine count, no padding."""
        doc, _ = self._routing_doc("--experts", "12", "--tokens", "1",
                                   "--split", "6", "--reps", "1",
                                   "--secondary-threads", "2")
        r = doc["routing"]
        self.assertEqual(r["k_cpu"] + r["k_sec"], 10)
        check_routing_structure(doc)

    def test_pre_fix_duplicate_padding_is_rejected_by_checker(self):
        """RED control: the REAL retained pre-fix routing dump (repeated
        local id 0 padding) must fail the structural check."""
        with self.assertRaises(AssertionError) as cm:
            check_routing_structure(_PRE_FIX_ROUTING_RED)
        self.assertIn("duplicate ids", str(cm.exception))

    def test_checker_catches_weight_and_genuine_mutations(self):
        """Mutations of a VALID dump each violate exactly one contract clause."""
        doc, _ = self._routing_doc("--experts", "12", "--tokens", "8",
                                   "--split", "6", "--reps", "1",
                                   "--secondary-threads", "2")
        import copy
        # padding weight not +0.0 (set one zero-weight slot to 1.0 bits)
        d = copy.deepcopy(doc)
        r = d["routing"]
        idx = r["w_cpu"].index(0)
        r["w_cpu"][idx] = _f32_bits(1.0)
        with self.assertRaises(AssertionError) as cm:
            check_routing_structure(d)
        self.assertIn("+0.0f", str(cm.exception))
        # genuine id dropped (replaced by another unselected id)
        d = copy.deepcopy(doc)
        r = d["routing"]
        t = next(t for t in range(r["tokens"])
                 if any(r["ids_all"][i + t * 10] < r["split"] for i in range(10)))
        gid = next(r["ids_all"][i + t * 10] for i in range(10) if r["ids_all"][i + t * 10] < r["split"])
        pos = r["ids_cpu"].index(gid, t * r["k_cpu"])
        r["ids_cpu"][pos] = (gid + 1) % r["split"] if (gid + 1) % r["split"] != gid else gid + 2
        with self.assertRaises(AssertionError):
            check_routing_structure(d)
        # id out of range
        d = copy.deepcopy(doc)
        d["routing"]["ids_sec"][0] = d["routing"]["n_expert"]
        with self.assertRaises(AssertionError) as cm:
            check_routing_structure(d)
        self.assertIn("out of range", str(cm.exception))


@unittest.skipUnless(not SKIP_BUILD, "MOE_OVERLAP_SKIP_BUILD=1")
class TestRoutingUnitSeam(unittest.TestCase):
    """MOE_OVERLAP_UNIT_ROUTING=1 drives partition_routing directly over
    crafted routing (no backends): boundary geometries and the explicit
    rejection of unrepresentable/duplicate routing. The seam's cardinality
    contract is FIXED at the harness's top-10 routing (n_used == 10, matching
    the qwen4exp argsort_top_k(probs, 10) the production path feeds
    partition_routing); any other n_used is an explicit input error."""

    @classmethod
    def setUpClass(cls):
        cls.harness = _harness_path()

    def _seam(self, payload: dict):
        env = dict(os.environ, MOE_OVERLAP_UNIT_ROUTING="1")
        return subprocess.run([self.harness], input=json.dumps(payload),
                              capture_output=True, text=True, env=env, timeout=60)

    def test_crafted_routing_contract(self):
        """Uneven counts, expert 0 genuinely selected on both devices, empty
        subsets on both sides across tokens; output satisfies the contract."""
        # 12 experts, split 5; token 0: 3 primary + 7 secondary; token 1:
        # 5 primary (all) + 5 secondary; token 2: 1 primary + 9 secondary.
        ids = [
            [0, 7, 2, 8, 9, 10, 11, 3, 4, 5],    # 0 genuinely selected (primary)
            [0, 1, 2, 3, 4, 8, 9, 10, 11, 5],    # full primary subset
            [7, 0, 6, 8, 9, 10, 11, 5, 1, 4],    # 0 genuinely selected, 1 primary
        ]
        w = [[_f32_bits(0.1 * (i + 1) + 0.05) for i in range(10)] for _ in range(3)]
        payload = {"n_expert": 12, "split": 5, "tokens": 3, "n_used": 10,
                   "ids": [x for row in ids for x in row],
                   "weights": [x for row in w for x in row]}
        r = self._seam(payload)
        self.assertEqual(r.returncode, 0, r.stderr)
        doc = json.loads(r.stdout)
        rt = doc["routing"]
        self.assertEqual(rt["k_cpu"], 5)   # max primary count (token 1, full subset)
        self.assertEqual(rt["k_sec"], 7)   # max secondary count (token 2: 7 of 7)
        # mirror the router selections into the dump schema and validate
        rt["ids_all"] = payload["ids"]
        rt["w_all"] = payload["weights"]
        check_routing_structure(doc)

    def test_t1_exact_subsets_via_seam(self):
        payload = {"n_expert": 12, "split": 5, "tokens": 1, "n_used": 10,
                   "ids": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
                   "weights": [_f32_bits(0.05 * (i + 1)) for i in range(10)]}
        r = self._seam(payload)
        self.assertEqual(r.returncode, 0, r.stderr)
        doc = json.loads(r.stdout)
        self.assertEqual(doc["routing"]["k_cpu"], 5)
        self.assertEqual(doc["routing"]["k_sec"], 5)

    def test_duplicate_genuine_id_rejected_valid_geometry(self):
        """A router that selected the same expert twice in one token violates
        the top-k uniqueness contract: fail closed (exit 5), never present
        duplicate ids to the native op. The fixture carries ten valid-range
        entries (the seam's fixed top-10 contract) with one deliberate
        duplicate, and the assertion pins the DUPLICATE-specific rejection
        reason so an unrepresentable-geometry rejection cannot satisfy it."""
        ids = [0, 1, 2, 3, 4, 5, 6, 7, 8, 8]  # expert 8 twice; all in range
        payload = {"n_expert": 12, "split": 6, "tokens": 1, "n_used": 10,
                   "ids": ids,
                   "weights": [_f32_bits(0.1 * (i + 1) + 0.02) for i in range(10)]}
        r = self._seam(payload)
        self.assertEqual(r.returncode, 5)
        self.assertIn("top-k uniqueness", r.stderr)
        self.assertNotIn("unrepresentable", r.stderr)

    def test_seam_rejects_out_of_range_ids(self):
        payload = {"n_expert": 12, "split": 6, "tokens": 1, "n_used": 10,
                   "ids": [0, 1, 2, 3, 4, 5, 6, 7, 8, 12],
                   "weights": [_f32_bits(0.25)] * 10}
        r = self._seam(payload)
        self.assertEqual(r.returncode, 5)
        self.assertIn("input error", r.stderr)

    def test_seam_rejects_cardinality_below_contract(self):
        """n_used < 10 is an input contract violation: partition_routing
        indexes routing with the fixed N_USED=10 stride, so a shorter
        array would read past the caller's input. It must be rejected as
        an explicit input error BEFORE any partitioning."""
        payload = {"n_expert": 12, "split": 6, "tokens": 1, "n_used": 4,
                   "ids": [3, 3, 2, 7],
                   "weights": [_f32_bits(0.25)] * 4}
        r = self._seam(payload)
        self.assertEqual(r.returncode, 5)
        self.assertIn("input error", r.stderr)
        self.assertIn("n_used", r.stderr)

    def test_seam_rejects_cardinality_above_contract(self):
        """n_used > 10 must likewise be rejected as an explicit input error
        (with a matching-length input array) before any partitioning."""
        ids = list(range(11))  # 11 valid ids, array length matches n_used
        payload = {"n_expert": 16, "split": 8, "tokens": 1, "n_used": 11,
                   "ids": ids,
                   "weights": [_f32_bits(0.25)] * 11}
        r = self._seam(payload)
        self.assertEqual(r.returncode, 5)
        self.assertIn("input error", r.stderr)
        self.assertIn("n_used", r.stderr)


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# GGUF loader regression: real-file weights with distinct tensor contents.
#
# Builds a small authentic-geometry GGUF (n_expert = 12) whose tensors carry
# distinct, crafted contents, replays crafted activations through
# --inputs-file, and checks the harness's dumped arm outputs against an
# independent F64 block reference computed directly from the fixture bytes.
# The fixture's tensor file order is deliberately alphabetical (like a real
# GGUF), i.e. different from the loader's internal want-order, so any
# byte-to-tensor assignment mistake produces wrong routing/outputs here.
# ---------------------------------------------------------------------------

N_EMBD, N_FF, N_USED = 2560, 640, 10
FIXTURE_EXPERTS = 12  # >= N_USED; small enough to keep the test fast


def _fp16_bytes(v: float) -> bytes:
    import struct
    return struct.pack("<e", v)


def _q8_0_payload_ints(row_id: int, n_blocks: int, seed: int):
    """Deterministic small ints in [-4, 4], distinct per (row, position, seed)."""
    for b in range(n_blocks):
        block = bytearray()
        for i in range(32):
            v = ((row_id * 131 + b * 17 + i * 7 + seed * 29) % 9) - 4
            block.append(v & 0xFF)
        yield b, block


def _q8_0_tensor_bytes(shape_ne0: int, shape_ne1: int, shape_ne2: int, seed: int) -> bytes:
    import struct
    n_blocks_per_row = shape_ne0 // 32
    out = bytearray()
    n_rows = shape_ne1 * max(shape_ne2, 1)
    for row in range(n_rows):
        for _, block in _q8_0_payload_ints(row, n_blocks_per_row, seed):
            out += _fp16_bytes(1.0)  # d = 1.0 exactly representable in fp16
            out += block
    return bytes(out)


def _f32_tensor_bytes(values) -> bytes:
    import struct
    return b"".join(struct.pack("<f", v) for v in values)


def _gguf_str(b: bytes) -> bytes:
    import struct
    return struct.pack("<Q", len(b)) + b


def write_fixture_gguf(path) -> dict:
    """Write the distinct-content block fixture; returns tensor contents for
    the independent reference."""
    import struct

    router = [float(12 - e) for e in range(FIXTURE_EXPERTS) for _ in range(N_EMBD)]
    # router is [N_EMBD, experts] k-major: element (k, e) at k + e*N_EMBD
    router_vals = [0.0] * (N_EMBD * FIXTURE_EXPERTS)
    for e in range(FIXTURE_EXPERTS):
        for k in range(N_EMBD):
            router_vals[k + e * N_EMBD] = float(12 - e)
    sh_gate_w = [float((k % 7) - 3) for k in range(N_EMBD)]

    tensors = {  # rel-name -> (ggml ne, ggml_type, bytes, seed/None)
        "ffn_down_exps.weight": ([N_FF, N_EMBD, FIXTURE_EXPERTS], 8, None, 1),
        "ffn_down_shexp.weight": ([N_FF, N_EMBD], 8, None, 2),
        "ffn_gate_exps.weight": ([N_EMBD, N_FF, FIXTURE_EXPERTS], 8, None, 3),
        "ffn_gate_inp.weight": ([N_EMBD, FIXTURE_EXPERTS], 0, None, None),
        "ffn_gate_inp_shexp.weight": ([N_EMBD], 0, None, None),
        "ffn_gate_shexp.weight": ([N_EMBD, N_FF], 8, None, 4),
        "ffn_up_exps.weight": ([N_EMBD, N_FF, FIXTURE_EXPERTS], 8, None, 5),
        "ffn_up_shexp.weight": ([N_EMBD, N_FF], 8, None, 6),
    }
    blob = bytearray()
    entries = {}
    alignment = 32
    for name in sorted(tensors):  # alphabetical file order, like a real GGUF
        ne, ggml_type, _, seed = tensors[name]
        if ggml_type == 0:
            if name == "ffn_gate_inp.weight":
                data = _f32_tensor_bytes(router_vals)
            elif name == "ffn_gate_inp_shexp.weight":
                data = _f32_tensor_bytes(sh_gate_w)
            else:
                raise AssertionError(name)
        else:
            data = _q8_0_tensor_bytes(ne[0], ne[1], ne[2] if len(ne) > 2 else 1, seed)
        off = (len(blob) + alignment - 1) // alignment * alignment
        blob += b"\x00" * (off - len(blob))
        entries[name] = (ne, ggml_type, off, len(data))
        blob += data

    out = bytearray()
    out += b"GGUF"
    out += struct.pack("<I", 3)          # version
    out += struct.pack("<Q", len(entries))  # tensor count precedes KV count
    out += struct.pack("<Q", 0)          # no metadata KV pairs
    data_start = len(out) + len(entries) * 0  # patched below via full compute
    # tensor infos
    infos = bytearray()
    for name in sorted(entries):
        ne, ggml_type, off, _ = entries[name]
        infos += _gguf_str(f"blk.2.{name}".encode())
        infos += struct.pack("<I", len(ne))
        for d in ne:
            infos += struct.pack("<q", d)
        infos += struct.pack("<I", ggml_type)
        infos += struct.pack("<Q", off)
    out += infos
    data_start = (len(out) + alignment - 1) // alignment * alignment
    out += b"\x00" * (data_start - len(out))
    out += blob
    with open(path, "wb") as f:
        f.write(bytes(out))

    # decode payloads back into per-tensor int arrays for the reference
    def payload_ints(name):
        ne, ggml_type, off, size = entries[name]
        n_blocks = size // 34
        ints = []
        for b in range(n_blocks):
            base = off + b * 34
            qs = blob[base + 2: base + 34]
            ints.extend(v - 256 if v > 127 else v for v in qs)
        return ints  # d == 1.0, so dequantized weight == int value

    return {
        "entries": {k: v[0] for k, v in entries.items()},
        "router": router_vals,
        "sh_gate_w": sh_gate_w,
        "up": payload_ints("ffn_up_exps.weight"),
        "gate": payload_ints("ffn_gate_exps.weight"),
        "down": payload_ints("ffn_down_exps.weight"),
        "sh_up": payload_ints("ffn_up_shexp.weight"),
        "sh_gate": payload_ints("ffn_gate_shexp.weight"),
        "sh_down": payload_ints("ffn_down_shexp.weight"),
    }


def write_fixture_inputs(path) -> list:
    """Crafted F32 activations: every 32-element block contains one +127 so
    the harness's Q8_0 activation quantization is exact (d = 1.0, identity)."""
    import struct
    act = []
    for k in range(N_EMBD):
        act.append(127.0 if k % 32 == 0 else 1.0)
    with open(path, "wb") as f:
        f.write(b"".join(struct.pack("<f", v) for v in act))
    return act


def _f32(v: float) -> float:
    import struct
    return struct.unpack("<f", struct.pack("<f", v))[0]


def _roundf(x: float) -> float:
    import math
    return math.floor(x + 0.5) if x >= 0 else math.ceil(x - 0.5)


def _q8_quantized_dot(ints32: list, xs: list, *, mode="cpu-scalar-q8_0") -> float:
    """Independent F64 dot for the crafted d_w=1 fixture's scalar CPU mode.

    Pinned quantize_row_q8_0_ref computes d, reciprocal AND multiplication
    in F32, then roundf (ties away), with d stored in fp16. This helper is
    not an AVX or CUDA reference; those paths require different operands.
    """
    import math
    import struct
    if mode != "cpu-scalar-q8_0":
        raise ValueError(f"unsupported fixture reference mode: {mode}")
    if len(ints32) != len(xs) or not xs or len(xs) % 32:
        raise ValueError("fixture dot requires equal nonempty complete 32-block rows")
    if any(not math.isfinite(v) for v in xs):
        raise ValueError("non-finite fixture activation")
    total = 0.0
    for b in range(len(xs) // 32):
        blk = xs[b * 32:(b + 1) * 32]
        amax = max(abs(_f32(v)) for v in blk)
        d = _f32(_f32(amax) / 127.0)
        d16 = struct.unpack("<e", struct.pack("<e", d))[0]
        idv = _f32(1.0 / d) if d != 0 else 0.0
        sumi = 0
        for i, v in enumerate(blk):
            q = _roundf(_f32(_f32(v) * idv)) if d != 0 else 0
            sumi += int(ints32[b * 32 + i]) * int(q)
        total += d16 * sumi  # d_w == 1.0
    return total


def fixture_reference(fx: dict, act: list) -> list:
    """Independent F64 reference for this crafted T=1 CPU loader fixture.

    Weight scales are all 1; the input quantization is identity by construction.
    Router saturation makes most selected weights zero, so this fixture is NOT
    evidence that an arbitrary real-weight block executes all top-10 experts.
    """
    import math

    E = FIXTURE_EXPERTS
    # router logits: logits[e] = (12 - e) * sum(act)
    s_act = sum(act)
    logits = [(12.0 - e) * s_act for e in range(E)]
    mx = max(logits)
    exps = [math.exp(l - mx) for l in logits]
    z = sum(exps)
    probs = [e / z for e in exps]
    order = sorted(range(E), key=lambda e: -probs[e])[:N_USED]  # distinct logits
    wsum = sum(probs[e] for e in order)
    wn = {e: probs[e] / wsum for e in order}

    def silu(x):
        return x / (1.0 + math.exp(-x))

    def w_of(payload, ne0, k, row):
        # Q8_0 layout: rows consecutive, each ne0/32 blocks of 32 ints, d=1.0
        return payload[row * (ne0 // 32) * 32 + k]

    out = [0.0] * N_EMBD
    for e in order:  # llama.cpp sums experts in selection (descending) order
        up = [sum(w_of(fx["up"], N_EMBD, k, j + e * N_FF) * act[k] for k in range(N_EMBD))
              for j in range(N_FF)]
        g = [sum(w_of(fx["gate"], N_EMBD, k, j + e * N_FF) * act[k] for k in range(N_EMBD))
             for j in range(N_FF)]
        sw = [silu(g[j]) * up[j] for j in range(N_FF)]
        sw32 = [_f32(v) for v in sw]
        plane = [wn[e] * _q8_quantized_dot(
                     fx["down"][ (d + e * N_EMBD) * N_FF : (d + 1 + e * N_EMBD) * N_FF ],
                     sw32)
                 for d in range(N_EMBD)]
        out = [a + b for a, b in zip(out, plane)]

    sg_up = [sum(w_of(fx["sh_up"], N_EMBD, k, j) * act[k] for k in range(N_EMBD))
             for j in range(N_FF)]
    sg_g = [sum(w_of(fx["sh_gate"], N_EMBD, k, j) * act[k] for k in range(N_EMBD))
            for j in range(N_FF)]
    sg_sw = [silu(sg_g[j]) * sg_up[j] for j in range(N_FF)]
    sg32 = [_f32(v) for v in sg_sw]
    shared = [_q8_quantized_dot(fx["sh_down"][d * N_FF:(d + 1) * N_FF], sg32)
              for d in range(N_EMBD)]
    gate = 1.0 / (1.0 + math.exp(-sum(w * a for w, a in zip(fx["sh_gate_w"], act))))
    return [o + gate * s for o, s in zip(out, shared)]


def assert_fixture_output(case, got, ref):
    """Existing loader-fixture criterion, scoped to this crafted CPU fixture.

    Retained empirical thresholds for F32 nonlinear ops vs F64 reference;
    no bound for arbitrary block inputs, accumulation orders, or CUDA.
    """
    import math
    case.assertEqual(len(got), len(ref))
    case.assertTrue(all(math.isfinite(v) for v in got + ref))
    worst = max(abs(g - q) / max(1e-9, abs(q)) for g, q in zip(got, ref))
    max_abs = max(abs(g - q) for g, q in zip(got, ref))
    case.assertLess(worst, 5e-5, f"max relative deviation {worst}")
    case.assertLess(max_abs, 5e-3, f"max absolute deviation {max_abs}")


class TestFixtureReferenceOperands(unittest.TestCase):
    """Small development fixtures; no native build, GPU, or held-out seeds."""

    def test_f32_multiply_before_rounding_and_fp16_scale(self):
        # 127 * F32(0.5/127) is just below 0.5 in F64 but is 0.5 in F32.
        # Scalar roundf must therefore produce codes +1/-1, not zero.
        xs = [1.0, _f32(0.5 / 127), _f32(-0.5 / 127)] + [0.0] * 29
        weights = [0, 1, -1] + [0] * 29
        self.assertEqual(_q8_quantized_dot(weights, xs), 2 * 0.00787353515625)

    def test_zero_blocks_and_dot_cancellation(self):
        self.assertEqual(_q8_quantized_dot([1] * 32, [0.0] * 32), 0.0)
        self.assertEqual(_q8_quantized_dot([1, -1] * 16, [127.0] * 32), 0.0)

    def test_rejects_unimplemented_operand_modes(self):
        for mode in ("cpu-avx-q8_0", "cuda-mmvq-q8_1", "cuda-mmq-d4", "unknown"):
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, "unsupported"):
                _q8_quantized_dot([1] * 32, [1.0] * 32, mode=mode)

    def test_rejects_incomplete_rows_and_nonfinite_inputs(self):
        for weights, xs in (([1] * 31, [1.0] * 31), ([1] * 32, [1.0] * 64),
                            ([], []), ([1] * 32, [float("nan")] * 32)):
            with self.subTest(lengths=(len(weights), len(xs))), self.assertRaises(ValueError):
                _q8_quantized_dot(weights, xs)

    def test_small_block_reference_and_negative_controls(self):
        # Shrink only the fixture geometry, preserving 12 experts/top-10 and
        # one complete Q8 block per row. All ten route weights are nonzero.
        import copy
        import math
        import struct
        with mock.patch.multiple(sys.modules[__name__], N_EMBD=32, N_FF=32):
            def rows(values):
                return [v if k == 2 else 0 for v in values for _ in range(32) for k in range(32)]

            fx = {"up": rows(range(1, 13)), "gate": rows([1] * 12),
                  "down": rows([1] * 12), "sh_up": rows([2]),
                  "sh_gate": rows([1]), "sh_down": rows([1]), "sh_gate_w": [0.0] * 32}
            act = [127.0, -127.0, 1.0] + [0.0] * 29  # identity input quantization; sum=1
            ref = fixture_reference(fx, act)
            silu_one = 1 / (1 + math.exp(-1))

            def projected(v):
                scale = struct.unpack("<e", struct.pack("<e", _f32(_f32(v) / 127)))[0]
                return 127 * scale

            z = sum(math.exp(-e) for e in range(10))
            expected = sum(math.exp(-e) / z * projected(silu_one * (e + 1)) for e in range(10))
            expected += 0.5 * projected(2 * silu_one)
            for value in ref:
                self.assertAlmostEqual(value, expected, places=12)
            assert_fixture_output(self, ref, [expected] * 32)

            missing = copy.deepcopy(fx)
            missing["up"][:32 * 32] = [0] * (32 * 32)  # selected expert 0 omitted
            wrong_weight = copy.deepcopy(fx)
            wrong_weight["up"][2 * 32 + 2] = 4  # hidden row 2 feeds the down projection
            corrupted = ref[:]
            corrupted[0] += 1.0
            nonfinite = ref[:]
            nonfinite[0] = float("nan")
            for name, got in (("missing expert", fixture_reference(missing, act)),
                              ("wrong weight", fixture_reference(wrong_weight, act)),
                              ("corrupted output", corrupted), ("nonfinite output", nonfinite)):
                with self.subTest(control=name), self.assertRaises(AssertionError):
                    assert_fixture_output(self, got, ref)


def _operand_tools():
    import importlib
    directory = str(REPO / "tools" / "moe-overlap")
    if directory not in sys.path:
        sys.path.insert(0, directory)
    return importlib.import_module("operand_reference"), importlib.import_module("check_reference")


def _scheduling_checker():
    """Import tools/moe-overlap/check_scheduling.py as a module (mirrors
    _operand_tools; the checker shares the operand_reference import path)."""
    import importlib
    directory = str(REPO / "tools" / "moe-overlap")
    if directory not in sys.path:
        sys.path.insert(0, directory)
    return importlib.import_module("check_scheduling")


class TestBackendOperandReference(unittest.TestCase):
    """Small independent math controls; no captured or held-out inputs."""
    def test_quantizer_modes_ties_zero_and_scale_storage(self):
        import numpy as np
        ref, _ = _operand_tools()
        x = np.array([127, 0.5, -0.5, np.nextafter(np.float32(0.5), np.float32(0))] + [0] * 28, dtype=np.float32)
        for mode in ref.MODES:
            q, scale = ref.quantize(x, mode)
            self.assertEqual(q[0].tolist(), [127, 0 if mode == "cpu-avx-q8_0" else 1,
                0 if mode == "cpu-avx-q8_0" else -1, 0] + [0] * 28)
            zero, zs = ref.quantize(np.zeros(32), mode)
            self.assertFalse(zero.any()); self.assertFalse(zs.any())
        x[0] = 1; x[1:] = 0
        _, cpu = ref.quantize(x, "cpu-scalar-q8_0")
        _, cuda = ref.quantize(x, "cuda-mmq-d4")
        self.assertEqual(float(cpu[0]), 0.00787353515625)
        self.assertEqual(float(cuda[0]), float(np.float32(1) / np.float32(127)))
        self.assertNotEqual(cpu[0], cuda[0])

    def test_signed_weight_codes_and_scale_applied_once(self):
        import numpy as np
        ref, _ = _operand_tools()
        raw = _fp16_bytes(0.5) + bytes([128, 127] + [0] * 30)
        x = np.array([127, 127] + [0] * 30, dtype=np.float32)
        codes, scales = ref.decode_q8(raw, 1, 32)
        self.assertEqual(codes[0, 0, :2].tolist(), [-128, 127])
        self.assertEqual(scales[0, 0], 0.5)
        for mode in ref.MODES:
            self.assertEqual(ref.project(raw, x, 1, mode)[0], -63.5)

    def test_unknown_modes_invalid_extents_and_nonfinite_rejected(self):
        import numpy as np
        ref, _ = _operand_tools()
        with self.assertRaisesRegex(ValueError, "unsupported"):
            ref.quantize(np.ones(32), "cuda-unknown")
        with self.assertRaises(ValueError): ref.decode_q8(b"\0" * 33, 1, 32)
        with self.assertRaises(ValueError): ref.quantize(np.ones(31), ref.CPU_MODES[0])
        with self.assertRaises(ValueError): ref.quantize(np.full(32, np.nan), ref.CPU_MODES[0])

    def test_all_experts_shared_mapping_and_negative_controls(self):
        import numpy as np
        ref, _ = _operand_tools()
        def tensor(code):
            return (_fp16_bytes(1) + bytes([0, 0, code] + [0] * 29)) * 32
        data = {(k, e): tensor(e + 1 if k == "up" and e is not None else 1)
                for e in list(range(10)) + [None] for k in ("up", "gate", "down")}
        data[("shared_gate", None)] = bytes(32 * 4)
        x = np.array([[127, -127, 1] + [0] * 29] * 128, dtype=np.float32)
        ids = np.array([list(range(10)), list(reversed(range(10)))] * 64, dtype=np.int32)
        weights = np.array([[i / 55 for i in range(1, 11)]] * 128, dtype=np.float32)
        for mode in ref.MODES:
            expected, mass = ref.block(x, ids, weights, lambda k, e: data[k, e],
                split=5, n_ff=32, cpu_mode="cpu-scalar-q8_0", secondary_mode=mode)
            # Independently compute the sparse fixture's weighted scalar planes.
            g = np.float32(1) / (np.float32(1) + np.exp(np.float32(-1)))
            for t in range(128):
                for name, group in (("cpu", range(5)), ("sec", range(5, 10))):
                    total = 0.0
                    for e in group:
                        slot = ids[t].tolist().index(e)
                        h = np.float32(g * np.float32(e + 1))
                        if mode == "cuda-mmq-d4" and name == "sec":
                            s = np.float32(1) / (np.float32(127) / h)
                        else:
                            s = np.float16(h / np.float32(127)).astype(np.float32)
                        total += float(np.float32(np.float32(127 * s) * weights[t, slot]))
                    np.testing.assert_allclose(expected[name][t], total, rtol=0, atol=1e-12)
            self.assertTrue(ref.compare(expected["cpu"], expected["cpu"], mass["cpu"])["pass"])
            missing = dict(data); del missing["up", 9]
            with self.assertRaises(KeyError):
                ref.block(x, ids, weights, lambda k, e: missing[k, e], split=5, n_ff=32,
                          cpu_mode="cpu-scalar-q8_0", secondary_mode=mode)
            wrong = weights.copy(); wrong[0, 1] *= 2
            bad, _ = ref.block(x, ids, wrong, lambda k, e: data[k, e], split=5, n_ff=32,
                             cpu_mode="cpu-scalar-q8_0", secondary_mode=mode)
            self.assertFalse(ref.compare(bad["cpu"], expected["cpu"], mass["cpu"])["pass"])
            corrupted = expected["sec"].copy(); corrupted[0, 0] += 0.1
            self.assertFalse(ref.compare(corrupted, expected["sec"], mass["sec"])["pass"])
            omitted = expected["cpu"] + expected["sec"]
            full = omitted + expected["shared"]
            self.assertFalse(ref.compare(omitted, full, sum(mass.values()))["pass"])


@unittest.skipUnless(not SKIP_BUILD, "MOE_OVERLAP_SKIP_BUILD=1")
class TestMoEOverlapGGUFLoader(unittest.TestCase):
    """Real-file (fixture) weights with distinct contents: the loader's
    byte-to-tensor assignment and the complete block math are checked against
    an independent reference computed from the same fixture bytes."""

    @classmethod
    def setUpClass(cls):
        cls.harness = _harness_path()
        cls.tmp = tempfile.TemporaryDirectory()
        td = cls.tmp.name
        cls.gguf = os.path.join(td, "fixture.gguf")
        cls.inputs = os.path.join(td, "act.f32")
        cls.fx = write_fixture_gguf(cls.gguf)
        cls.act = write_fixture_inputs(cls.inputs)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _run(self, split: int):
        import struct
        serial = os.path.join(self.tmp.name, f"serial-{split}.f32")
        overlap = os.path.join(self.tmp.name, f"overlap-{split}.f32")
        r = _run(self.harness, "--gguf", self.gguf, "--layer", "2",
                 "--tokens", "1", "--split", str(split), "--secondary", "cpu",
                 "--secondary-threads", "2", "--reps", "2", "--warmup", "1",
                 "--inputs-file", self.inputs,
                 "--dump-serial", serial, "--dump-overlap", overlap)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        doc = _doc(r)
        self.assertTrue(doc["verdict"]["pass"])
        self.assertEqual(doc["config"]["weights_mode"], "GGUF")
        self.assertEqual(doc["config"]["n_expert"], FIXTURE_EXPERTS)
        self.assertEqual(doc["config"]["inputs_mode"], "CAPTURED-FILE")

        def read_f32(path):
            with open(path, "rb") as f:
                data = f.read()
            n = len(data) // 4
            return list(struct.unpack(f"<{n}f", data))

        return doc, read_f32(serial), read_f32(overlap)

    def test_loader_assignment_and_block_reference_split(self):
        """Two-device split: dumped arm outputs must match the independent
        F64 fixture reference (wrong byte assignment diverges at O(1))."""
        doc, serial, overlap = self._run(split=6)
        ref = fixture_reference(self.fx, self.act)
        self.assertEqual(len(serial), N_EMBD)
        for got in (serial, overlap):
            assert_fixture_output(self, got, ref)

    def test_loader_assignment_single_device(self):
        """All-primary variant (also exercises the exact-subset path)."""
        doc, serial, overlap = self._run(split=FIXTURE_EXPERTS)
        ref = fixture_reference(self.fx, self.act)
        worst = max(abs(g - q) / max(1e-9, abs(q)) for g, q in zip(serial, ref))
        self.assertLess(worst, 5e-5)
        for rep in doc["reps"]:
            self.assertEqual(rep["checks"]["serial_vs_ref_max_abs"], 0.0)

    def test_independent_reference_export_end_to_end_and_failure_controls(self):
        import numpy as np
        import shutil
        _, checker = _operand_tools()
        case = Path(self.tmp.name) / "reference-case"
        gguf = Path(self.tmp.name) / "reference-fixture.gguf"
        shutil.copyfile(self.gguf, gguf)
        # The original loader fixture saturates the shared gate to zero. This
        # variant sets that F32 gate to zero logits (sigmoid=1/2), ensuring the
        # required missing-shared negative control is informative.
        loader = checker.GGUFWeights(gguf, 2, FIXTURE_EXPERTS)
        row = loader.rows["blk.2.ffn_gate_inp_shexp.weight"]
        loader.close()
        with gguf.open("r+b") as f:
            f.seek(row.absolute_offset); f.write(bytes(row.encoded_bytes))
        r = _run(self.harness, "--gguf", str(gguf), "--layer", "2", "--tokens", "1",
                 "--split", "6", "--reps", "2", "--warmup", "0", "--inputs-file", self.inputs,
                 "--self-check-negative", "--dump-reference-case", str(case))
        self.assertEqual(r.returncode, 0, r.stderr[-1000:])
        result = checker.check_case(case, gguf)
        self.assertTrue(result["pass"], result)
        self.assertEqual(result["status"], "PROPOSED_EMPIRICAL_PASS")
        self.assertFalse(result["hardware_qualified"])
        self.assertEqual(len(result["reps"]), 2)
        # Wrong/corrupted backend partial fails even if the native report is green.
        file = case / "rep-0-sec.f32"
        original = file.read_bytes()
        partial = np.frombuffer(original, dtype="<f4").copy(); partial[0] += 1
        file.write_bytes(partial.tobytes())
        self.assertFalse(checker.check_case(case, gguf)["pass"])
        file.write_bytes(original)
        # Missing data and unsupported producer mode cannot silently fall back.
        file.unlink()
        with self.assertRaises(OSError): checker.check_case(case, gguf)
        file.write_bytes(original)
        meta = json.loads((case / "run.json").read_text())
        meta["config"]["reference_secondary_mode"] = "unknown"
        (case / "run.json").write_text(json.dumps(meta))
        with self.assertRaisesRegex(ValueError, "mode"): checker.check_case(case, gguf)


@unittest.skipUnless(not SKIP_BUILD, "MOE_OVERLAP_SKIP_BUILD=1")
class TestSchedulingEquivalenceContract(unittest.TestCase):
    """moe-scheduling-equivalence/1: a separately versioned verdict that the
    serial and overlapped arms executed identical work and produced
    bitwise-identical outputs. Deliberately narrow: it must PASS while the
    numerical diagnostics stay FAIL, must reject evidence gaps and execution
    failures, must never set hardware_qualified, and must never rewrite the
    retained numerical reports."""

    @classmethod
    def setUpClass(cls):
        cls.harness = _harness_path()
        cls.tmp = tempfile.TemporaryDirectory()
        td = cls.tmp.name
        cls.checker = _scheduling_checker()
        cls.gguf = os.path.join(td, "scheduling-fixture.gguf")
        cls.inputs = os.path.join(td, "act.f32")
        write_fixture_gguf(cls.gguf)
        write_fixture_inputs(cls.inputs)
        # Zero the F32 shared gate to zero logits (sigmoid=1/2) so the
        # harness's omitted-shared negative control stays informative.
        import importlib
        ref = importlib.import_module("check_reference")
        loader = ref.GGUFWeights(cls.gguf, 2, FIXTURE_EXPERTS)
        row = loader.rows["blk.2.ffn_gate_inp_shexp.weight"]
        loader.close()
        with open(cls.gguf, "r+b") as f:
            f.seek(row.absolute_offset)
            f.write(bytes(row.encoded_bytes))
        cls.case = Path(td) / "reference-case"
        r = _run(cls.harness, "--gguf", cls.gguf, "--layer", "2", "--tokens", "1",
                 "--split", "6", "--reps", "2", "--warmup", "0",
                 "--inputs-file", cls.inputs, "--self-check-negative",
                 "--dump-reference-case", str(cls.case))
        assert r.returncode == 0, r.stderr[-2000:]
        doc = _doc(r)
        assert doc["verdict"]["pass"] is True

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    _copy_seq = 0

    def _copy(self) -> Path:
        """Fresh mutable copy of the retained export (unique per call)."""
        import shutil
        type(self)._copy_seq += 1
        dst = Path(self.tmp.name) / f"case-{self._testMethodName}-{self._copy_seq}"
        shutil.copytree(self.case, dst)
        return dst

    def _edit_run_json(self, case: Path, fn) -> dict:
        meta = json.loads((case / "run.json").read_text())
        fn(meta)
        (case / "run.json").write_text(json.dumps(meta))
        return meta

    def test_scheduling_pass_with_numerical_fail_retained(self):
        """Scheduling PASS while both numerical diagnostics stay FAIL: the
        legacy comparison is the only failing native diagnostic, and a FAILed
        operand reference is retained beside it."""
        case = self._copy()

        def make_legacy_only(meta):
            meta["verdict"]["pass"] = False
            meta["verdict"]["reason"] = "validation failed"
            meta["reps"][0]["checks"]["serial_vs_ref_pass"] = False
            meta["reps"][0]["checks"]["legacy_cpu_unsplit_diagnostic"]["pass"] = False
        self._edit_run_json(case, make_legacy_only)
        (case / "reference.json").write_text(json.dumps(
            {"contract": "moe-operand-reference/2", "pass": False, "status": "FAIL",
             "reps": [{"rep": 0, "max_abs": 4.511685386133883e-05}]}))
        before = (case / "run.json").read_bytes()
        result = self.checker.check_case(case)
        self.assertEqual(result["status"], "SCHEDULING_EQUIVALENT", result["problems"])
        self.assertEqual(result["native_outcome"], "LEGACY_NUMERICAL_ONLY_FAIL")
        self.assertFalse(result["hardware_qualified"])
        # legacy FAIL preserved verbatim at both levels, never rewritten
        self.assertFalse(result["legacy_cpu_unsplit_verdict"]["pass"])
        self.assertFalse(result["reps"][0]["legacy_cpu_unsplit_diagnostic"]["pass"])
        self.assertEqual(result["moe_operand_reference_status"], "FAIL")
        # the checker is read-only: retained reports are untouched
        self.assertEqual((case / "run.json").read_bytes(), before)

    def test_rejects_changed_inputs_routing_ownership_or_incomplete_workload(self):
        import numpy as np
        case = self._copy()
        # Changed/non-finite input operands are rejected.
        cur = np.frombuffer((case / "rep-0-cur.f32").read_bytes(), dtype="<f4").copy()
        (case / "rep-0-cur.f32").write_bytes(
            np.array([np.float32("nan")] + cur[1:].tolist(), dtype="<f4").tobytes())
        result = self.checker.check_case(case)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("non-finite" in p for p in result["problems"]), result["problems"])
        (case / "rep-0-cur.f32").write_bytes(cur.tobytes())
        # Ownership split: native accounting inconsistent with routing bytes.
        def bump(meta):
            meta["reps"][0]["k_cpu_real"] += 1
        self._edit_run_json(case, bump)
        result = self.checker.check_case(case)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("ownership split inconsistent" in p for p in result["problems"]))
        def unbump(meta):
            meta["reps"][0]["k_cpu_real"] -= 1
        self._edit_run_json(case, unbump)
        self.assertEqual(self.checker.check_case(case)["status"], "SCHEDULING_EQUIVALENT")
        # Incomplete workload: dropping a genuine slot duplicates an expert id.
        ids = np.frombuffer((case / "rep-0-ids.i32").read_bytes(), dtype="<i4").copy()
        ids[0] = ids[1]
        (case / "rep-0-ids.i32").write_bytes(ids.tobytes())
        result = self.checker.check_case(case)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("duplicate selected expert" in p for p in result["problems"]))
        # Routing tampering across the ownership boundary is also caught via
        # the k_real cross-check (a moved expert changes the split accounting).
        ids2 = np.frombuffer((case / "rep-0-ids.i32").read_bytes(), dtype="<i4").copy()
        ids2[0] = (ids2[0] + 3) % 12  # rewrites a slot to another expert
        (case / "rep-0-ids.i32").write_bytes(ids2.tobytes())
        result = self.checker.check_case(case)
        self.assertIn(result["status"], ("FAIL", "INVALID_OR_INCOMPLETE"))

    def test_rejects_unequal_outputs_replay_compute_missing_shared_nonfinite_incomplete(self):
        import numpy as np
        case = self._copy()
        # 1. unequal arm outputs
        overlap = np.frombuffer((case / "rep-0-overlap.f32").read_bytes(), dtype="<f4").copy()
        mutated = overlap.copy()
        mutated[0] += 1.0
        (case / "rep-0-overlap.f32").write_bytes(mutated.tobytes())
        result = self.checker.check_case(case)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("outputs differ" in p for p in result["problems"]))
        (case / "rep-0-overlap.f32").write_bytes(overlap.tobytes())
        # 2. failed same-input replay/determinism
        def break_replay(meta):
            meta["determinism_recheck"] = {"reference_bitwise": False, "serial_bitwise": True}
        self._edit_run_json(case, break_replay)
        result = self.checker.check_case(case)
        self.assertEqual(result["native_outcome"], "EXECUTION_FAILURE")
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("replay/determinism" in p for p in result["problems"]))
        # 3. native compute/status failure (not a legacy-numerical exit)
        def compute_fail(meta):
            meta["verdict"]["pass"] = False
            meta["verdict"]["reason"] = "graph compute failed: shared"
        self._edit_run_json(case, compute_fail)
        result = self.checker.check_case(case)
        self.assertNotEqual(result["native_outcome"], "LEGACY_NUMERICAL_ONLY_FAIL")
        self.assertEqual(result["native_outcome"], "EXECUTION_FAILURE")
        self.assertEqual(result["status"], "FAIL")
        # 4. missing shared work: zeroed shared branch breaks combine identity
        def restore(meta):
            meta["verdict"]["pass"] = True
            meta["verdict"]["reason"] = "all correctness gates passed"
            meta["determinism_recheck"] = {"reference_bitwise": True, "serial_bitwise": True}
        self._edit_run_json(case, restore)
        shared = np.frombuffer((case / "rep-0-shared.f32").read_bytes(), dtype="<f4").copy()
        (case / "rep-0-shared.f32").write_bytes(np.zeros_like(shared).tobytes())
        result = self.checker.check_case(case)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("not composed of retained partials" in p for p in result["problems"]))
        (case / "rep-0-shared.f32").write_bytes(shared.tobytes())
        # 5. non-finite exported output
        serial = np.frombuffer((case / "rep-0-serial.f32").read_bytes(), dtype="<f4")
        poisoned = serial.copy()
        poisoned[0] = np.float32("inf")
        (case / "rep-0-serial.f32").write_bytes(poisoned.tobytes())
        result = self.checker.check_case(case)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("non-finite" in p for p in result["problems"]))
        (case / "rep-0-serial.f32").write_bytes(serial.tobytes())
        # 6. incomplete export: a required file is missing
        (case / "rep-1-sec.f32").unlink()
        result = self.checker.check_case(case)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("incomplete capture" in p for p in result["problems"]))

    def test_legacy_numerical_only_exit_distinguished_from_execution_failure(self):
        case = self._copy()

        def legacy_only(meta):
            meta["verdict"]["pass"] = False
            meta["verdict"]["reason"] = "validation failed"
        self._edit_run_json(case, legacy_only)
        result = self.checker.check_case(case)
        # exit-3 with the legacy comparison as the only failing diagnostic is
        # NOT an execution failure, and scheduling equivalence still holds
        self.assertEqual(result["native_outcome"], "LEGACY_NUMERICAL_ONLY_FAIL")
        self.assertEqual(result["status"], "SCHEDULING_EQUIVALENT")

        def schedule_gate_fails(meta):
            meta["verdict"]["pass"] = False
            meta["verdict"]["reason"] = "validation failed"
            meta["reps"][0]["checks"]["overlap_vs_serial_bitwise"] = False
            meta["reps"][0]["checks"]["overlap_vs_serial_pass"] = False
        case2 = self._copy()
        self._edit_run_json(case2, schedule_gate_fails)
        result = self.checker.check_case(case2)
        self.assertEqual(result["native_outcome"], "EXECUTION_FAILURE")
        self.assertEqual(result["status"], "FAIL")

        def control_fails(meta):
            meta["negative_control"] = {"comparator_rejected": False}
        case3 = self._copy()
        self._edit_run_json(case3, control_fails)
        result = self.checker.check_case(case3)
        self.assertEqual(result["native_outcome"], "EXECUTION_FAILURE")
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("negative control" in p for p in result["problems"]))

    def test_preserves_historical_reports_and_hardware_unqualified(self):
        case = self._copy()
        # A retained FAILed operand reference is preserved verbatim and a
        # scheduling PASS never upgrades it or claims hardware qualification.
        (case / "reference.json").write_text(json.dumps(
            {"contract": "moe-operand-reference/2", "pass": False, "status": "FAIL",
             "reps": [{"rep": 0, "max_abs": 6.404588930308819e-06},
                      {"rep": 0, "max_abs": 4.511685386133883e-05}]}))
        before_ref = (case / "reference.json").read_bytes()
        before_run = (case / "run.json").read_bytes()
        result = self.checker.check_case(case)
        self.assertEqual(result["status"], "SCHEDULING_EQUIVALENT")
        self.assertEqual(result["moe_operand_reference_status"], "FAIL")
        self.assertFalse(result["hardware_qualified"])
        self.assertEqual((case / "reference.json").read_bytes(), before_ref)
        self.assertEqual((case / "run.json").read_bytes(), before_run)
        # explicit scope limits in every report
        joined = " ".join(result["scope_limits"]).lower()
        for phrase in ("hardware", "numerical", "model"):
            self.assertIn(phrase, joined)
        # missing operand reference is reported as not requested, not FAIL
        (case / "reference.json").unlink()
        result = self.checker.check_case(case)
        self.assertEqual(result["moe_operand_reference_status"], "NOT_REQUESTED")


@unittest.skipUnless(not SKIP_BUILD, "MOE_OVERLAP_SKIP_BUILD=1")
class TestBuildCacheAndStatusControls(unittest.TestCase):
    """Offline demonstrations for the review corrections: stale-object
    invalidation in build.py, the compute-status failure-injection control,
    and the honored warmup count."""

    def test_object_cache_invalidates_on_stamp_mismatch(self):
        """A cached object whose stamp no longer matches (changed source,
        flags or compiler) must be rebuilt, not reused; an unchanged object
        must be reused."""
        def binary_and_obj():
            # in-process invocation: a Python child in this sandbox can boot
            # an unrelated desktop launcher whose stdout swamps the marker
            import contextlib
            import importlib.util
            import io
            spec = importlib.util.spec_from_file_location("moe_overlap_build_cached", BUILD_PY)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            old_argv = sys.argv[:]
            sys.argv = ["build.py"]
            buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(buf):
                    rc = mod.main()
            finally:
                sys.argv = old_argv
            self.assertEqual(rc, 0)
            path = None
            for line in buf.getvalue().splitlines():
                if line.startswith("MOE_OVERLAP_BINARY "):
                    path = Path(line.split(" ", 1)[1].strip())
            self.assertIsNotNone(path)
            obj = path.parent / "moe_overlap_harness.o"
            stamp = path.parent / "stamps" / "moe_overlap_harness.o.stamp"
            return path, obj, stamp

        _, obj, stamp = binary_and_obj()
        self.assertTrue(obj.is_file() and stamp.is_file())
        m1 = obj.stat().st_mtime_ns
        _, obj2, _ = binary_and_obj()
        m2 = obj2.stat().st_mtime_ns
        self.assertEqual(m1, m2, "unchanged object must be reused")
        stamp.write_text("tampered")  # simulate changed source/flags/compiler
        _, obj3, _ = binary_and_obj()
        m3 = obj3.stat().st_mtime_ns
        self.assertNotEqual(m2, m3, "stale object with mismatched stamp must be rebuilt")

    def test_status_failure_injection_refuses_to_compare(self):
        """--self-check-status-negative must terminate non-passing with the
        injected stage recorded; a failed compute never reaches output
        comparisons (no stale-output use)."""
        r = _run(self.harness_path(), "--experts", "32", "--tokens", "1",
                 "--split", "16", "--reps", "2", "--warmup", "1",
                 "--self-check-status-negative")
        self.assertEqual(r.returncode, 3)
        doc = _doc(r)
        self.assertFalse(doc["verdict"]["pass"])
        self.assertIn("injected failure", doc["verdict"]["reason"])
        self.assertTrue(doc["verdict"]["status_negative_control_refused"])

    def test_warmup_count_is_honored(self):
        r = _run(self.harness_path(), "--experts", "32", "--tokens", "1",
                 "--split", "16", "--reps", "2", "--warmup", "3")
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        doc = _doc(r)
        self.assertEqual(doc["config"]["warmup"], 3)
        self.assertEqual(doc["verdict"]["warmup_runs"], 3)

    @staticmethod
    def harness_path() -> str:
        return _harness_path()


class TestBuildCommands(unittest.TestCase):
    def test_cuda_driver_dependency_and_registration(self):
        """Capture commands without nvcc: VMM needs the driver, and every
        CUDA/host TU must retain compile-time backend registration."""
        spec = importlib.util.spec_from_file_location("moe_build_commands", BUILD_PY)
        build = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(build)
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "source"
            for rel in ("ggml/src/ggml-cuda/ggml-cuda.cu",
                        "ggml/src/ggml-cuda/top-k.cu",
                        "ggml/src/ggml-cuda/template-instances/mmq-instance.cu"):
                p = source / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.touch()
            for cuda in (False, True):
                with self.subTest(cuda=cuda):
                    commands = []
                    with mock.patch.object(build, "pick_compiler", return_value="c++"), \
                         mock.patch.object(build, "sha256_file", return_value="source-hash"), \
                         mock.patch.object(build.shutil, "which", return_value="nvcc"), \
                         mock.patch.object(build.subprocess, "run", side_effect=lambda cmd, **kw: commands.append(cmd)):
                        build.build(source, Path(td) / str(cuda), jobs=2, cuda=cuda)
                    compiles = [c for c in commands if "-c" in c]
                    link = commands[-1]
                    self.assertEqual(len(compiles), len(build.C_SOURCES) + len(build.CXX_SOURCES) + 1 + (3 if cuda else 0))
                    self.assertEqual("-lcuda" in link, cuda)
                    for c in compiles:
                        self.assertEqual("-DGGML_USE_CUDA" in c, cuda)
                        self.assertNotIn("-DGGML_CUDA_NO_VMM", c)
                    if cuda:
                        for lib in ("-lcuda", "-lcudart", "-lcublas", "-lcublasLt", "-lculibos"):
                            self.assertIn(lib, link)
                            self.assertGreater(link.index(lib), max(i for i, arg in enumerate(link) if arg.endswith(".o")))


# Link wrappers inject a returned native failure after the real CPU compute.
# Its outputs are still numerically correct: this exposes false PASS in the
# replay/negative-control paths even when stale data happens to compare equal.
# Log reads, further computes and frees after failure, and model an outstanding
# secondary submission until synchronize, to check the join-before-free path.
_STATUS_FAILURE_SHIM = r'''
#include "ggml-backend.h"
#include <cstdio>
#include <cstdlib>
static int calls = 0;
static bool failed = false;
static ggml_backend_t pending = nullptr;
static void log(const char * action) {
    FILE * f = fopen(std::getenv("MOE_TEST_LOG"), "a");
    if (f) { fprintf(f, "%s\n", action); fclose(f); }
}
static enum ggml_status result(enum ggml_status st) {
    if (failed) log("compute_after_failure");
    if (++calls == std::atoi(std::getenv("MOE_TEST_FAIL_CALL"))) {
        failed = true;
        log("failure");
        return GGML_STATUS_FAILED;
    }
    return st;
}
extern "C" {
enum ggml_status __real_ggml_backend_graph_compute(ggml_backend_t, ggml_cgraph *);
enum ggml_status __real_ggml_backend_graph_compute_async(ggml_backend_t, ggml_cgraph *);
void __real_ggml_backend_tensor_get(const ggml_tensor *, void *, size_t, size_t);
void __real_ggml_backend_tensor_get_async(ggml_backend_t, const ggml_tensor *, void *, size_t, size_t);
void __real_ggml_backend_synchronize(ggml_backend_t);
void __real_ggml_backend_buffer_free(ggml_backend_buffer_t);
enum ggml_status __wrap_ggml_backend_graph_compute(ggml_backend_t b, ggml_cgraph * g) {
    return result(__real_ggml_backend_graph_compute(b, g));
}
enum ggml_status __wrap_ggml_backend_graph_compute_async(ggml_backend_t b, ggml_cgraph * g) {
    pending = b;
    return result(__real_ggml_backend_graph_compute_async(b, g));
}
void __wrap_ggml_backend_tensor_get(const ggml_tensor * t, void * p, size_t o, size_t s) {
    if (failed) log("read_after_failure");
    __real_ggml_backend_tensor_get(t, p, o, s);
}
void __wrap_ggml_backend_tensor_get_async(ggml_backend_t b, const ggml_tensor * t, void * p, size_t o, size_t s) {
    if (failed) log("read_after_failure");
    __real_ggml_backend_tensor_get_async(b, t, p, o, s);
}
void __wrap_ggml_backend_synchronize(ggml_backend_t b) {
    __real_ggml_backend_synchronize(b);
    if (pending == b) { pending = nullptr; if (failed) log("joined"); }
    if (failed) log("synchronized");
}
void __wrap_ggml_backend_buffer_free(ggml_backend_buffer_t b) {
    if (failed && b) log(pending ? "free_before_join" : "released");
    __real_ggml_backend_buffer_free(b);
}
}
'''


@unittest.skipUnless(not SKIP_BUILD, "MOE_OVERLAP_SKIP_BUILD=1")
class TestReturnedComputeFailures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        binary = Path(_harness_path())
        spec = importlib.util.spec_from_file_location("moe_failure_build", BUILD_PY)
        build = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(build)
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        td = Path(cls.tmp.name)
        shim = td / "status_failure.cpp"
        shim.write_text(_STATUS_FAILURE_SHIM)
        source = build.ensure_source(build.DEFAULT_CACHE)
        cxx = build.pick_compiler("c++")
        obj = td / "status_failure.o"
        subprocess.run([cxx, "-std=c++17", f"-I{source / 'ggml/include'}", "-c", str(shim), "-o", str(obj)], check=True)
        objects = [binary.parent / (s.replace("/", "__") + ".o") for s in build.C_SOURCES + build.CXX_SOURCES]
        objects += [binary.parent / "moe_overlap_harness.o", obj]
        wrappers = ["graph_compute", "graph_compute_async", "tensor_get", "tensor_get_async", "synchronize", "buffer_free"]
        cls.harness = str(td / "returned_failure_harness")
        subprocess.run([cxx, *build.BASE_FLAGS, *map(str, objects),
                        *[f"-Wl,--wrap=ggml_backend_{name}" for name in wrappers],
                        "-o", cls.harness], check=True)

    def _assert_failure(self, call, stage, completed_reps, pending=False):
        log = Path(self.tmp.name) / f"call-{call}.log"
        serial, overlap = log.with_suffix(".serial"), log.with_suffix(".overlap")
        env = dict(os.environ, MOE_TEST_FAIL_CALL=str(call), MOE_TEST_LOG=str(log))
        r = subprocess.run([self.harness, "--synthetic", "--experts", "12", "--tokens", "1",
                            "--split", "6", "--threads", "2", "--secondary-threads", "2",
                            "--warmup", "1", "--reps", "2", "--self-check-negative",
                            "--dump-serial", str(serial), "--dump-overlap", str(overlap)],
                           env=env, capture_output=True, text=True, timeout=120)
        doc = _doc(r)
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertFalse(doc["verdict"]["pass"])
        self.assertIn(f"graph compute failed: {stage} (ggml_status=-1)", doc["verdict"]["reason"])
        self.assertEqual(len(doc["reps"]), completed_reps)
        self.assertNotIn("negative_control", doc)
        self.assertNotIn("output_dumps", doc)
        self.assertFalse(serial.exists())
        self.assertFalse(overlap.exists())
        self.assertTrue(doc["resources_released"])
        actions = log.read_text().splitlines()
        self.assertEqual(actions.count("failure"), 1)
        self.assertNotIn("read_after_failure", actions)
        self.assertNotIn("compute_after_failure", actions)
        self.assertNotIn("free_before_join", actions)
        self.assertIn("synchronized", actions)
        self.assertIn("released", actions)
        self.assertLess(actions.index("synchronized"), actions.index("released"))
        if pending:
            self.assertIn("joined", actions)
            self.assertLess(actions.index("joined"), actions.index("released"))
        return doc

    # A split repetition has nine native calls: router, reference, shared,
    # serial(primary/shared/secondary), overlap(secondary-async/primary/shared).
    # Warmup and replay execute the same sequence; measured rep 1 reverses arms.
    def test_measured_returned_failures(self):
        stages = ["router", "reference", "shared", "primary experts", "shared", "secondary experts",
                  "secondary experts (async)", "primary experts", "shared"]
        for offset, stage in enumerate(stages, 1):
            with self.subTest(stage=stage, call=9 + offset):
                doc = self._assert_failure(9 + offset, stage, 0, pending=offset >= 7)
                self.assertNotIn("determinism_recheck", doc)
        # CPU failure while secondary work is pending in the overlap-first rep.
        self._assert_failure(18 + 5, "primary experts", 1, pending=True)

    def test_determinism_replay_returned_failures(self):
        for offset, stage in ((1, "router"), (2, "reference"), (3, "shared"),
                              (7, "secondary experts (async)"), (8, "primary experts"), (9, "shared")):
            with self.subTest(stage=stage):
                doc = self._assert_failure(27 + offset, stage, 2, pending=offset >= 7)
                self.assertNotIn("determinism_recheck", doc)

    def test_negative_control_returned_failures(self):
        for offset, stage in enumerate(("router", "reference", "shared", "primary experts", "secondary experts"), 1):
            with self.subTest(stage=stage):
                doc = self._assert_failure(36 + offset, stage, 2)
                self.assertTrue(doc["determinism_recheck"]["serial_bitwise"])

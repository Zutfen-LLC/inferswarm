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
        for rep in doc["reps"]:
            self.assertTrue(rep["checks"]["routed_counts_ok"])
            # every router-selected expert executed exactly once per token
            self.assertEqual(rep["k_cpu_real"] + rep["k_sec_real"],
                             10 * doc["config"]["tokens"])
            self.assertTrue(rep["checks"]["serial_vs_ref_pass"])
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


def _q8_quantized_dot(ints32: list, xs: list) -> float:
    import struct
    """Model ggml's quantized vec-dot for a Q8_0 weight row (d_w = 1.0)
    against an F32 input row: the input is quantized to Q8_0 per 32-block
    (quantize_row_q8_0_ref: d = amax/127 in F32, reciprocal multiply,
    roundf; d stored as fp16) and dots accumulate per block like the CPU
    kernel does."""
    total = 0.0
    for b in range(len(xs) // 32):
        blk = xs[b * 32:(b + 1) * 32]
        amax = max(abs(_f32(v)) for v in blk)
        d = _f32(_f32(amax) / 127.0)
        d16 = _f32(struct.unpack("<e", struct.pack("<e", d))[0]) if True else d
        idv = _f32(1.0 / d) if d != 0 else 0.0
        sumi = 0
        for i, v in enumerate(blk):
            q = _roundf(_f32(v) * idv) if d != 0 else 0.0
            q = max(-127.0, min(127.0, q))
            sumi += int(ints32[b * 32 + i]) * int(q)
        total += d16 * sumi  # d_w == 1.0
    return total


def fixture_reference(fx: dict, act: list) -> list:
    """Independent F64 block reference straight from the fixture bytes."""
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
            worst = max(abs(g - q) / max(1e-9, abs(q)) for g, q in zip(got, ref))
            max_abs = max(abs(g - q) for g, q in zip(got, ref))
            # derived bound: F32 transcendentals + F64 reference, exact int
            # dot products on both sides (d = 1.0 everywhere by construction)
            self.assertLess(worst, 5e-5, f"max relative deviation {worst}")
            self.assertLess(max_abs, 5e-3, f"max absolute deviation {max_abs}")

    def test_loader_assignment_single_device(self):
        """All-primary variant (also exercises the exact-subset path)."""
        doc, serial, overlap = self._run(split=FIXTURE_EXPERTS)
        ref = fixture_reference(self.fx, self.act)
        worst = max(abs(g - q) / max(1e-9, abs(q)) for g, q in zip(serial, ref))
        self.assertLess(worst, 5e-5)
        for rep in doc["reps"]:
            self.assertEqual(rep["checks"]["serial_vs_ref_max_abs"], 0.0)


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

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

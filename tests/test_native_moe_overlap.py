"""Issue #309 native model FFN integration; small CPU fixtures and loopback RPC.

Scheduling equality uses exact F32 outputs under identical backend arithmetic.
The diagnostics are preserved in failure messages. This is neither real-model
qualification nor CUDA compilation, residency, overlap, or performance evidence.
"""
from __future__ import annotations

import contextlib
import importlib.util
import json
import math
import os
from pathlib import Path
import signal
import socket
import struct
import subprocess
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "tools/native-moe-overlap/build.py"


def load_build():
    spec = importlib.util.spec_from_file_location("native_moe_build", BUILD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class WireProxy:
    """Transparent fixture-only TCP observer; unchanged pinned RPC protocol."""
    def __init__(self, worker_port, fault=None):
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.port = self.listener.getsockname()[1]
        self.listener.listen()
        self.listener.settimeout(0.2)
        self.worker_port = worker_port
        self.fault = fault
        self.frames = []
        self.connections = 0
        self.sockets = []
        self.stop = threading.Event()
        self.fault_reached = threading.Event()
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    @staticmethod
    def read(sock, size):
        data = b""
        while len(data) < size:
            part = sock.recv(size - len(data))
            if not part:
                raise EOFError
            data += part
        return data

    def reverse(self, remote, client):
        try:
            while not self.stop.is_set():
                data = remote.recv(65536)
                if not data:
                    break
                client.sendall(data)
        except OSError:
            pass
        finally:
            with contextlib.suppress(OSError):
                client.shutdown(socket.SHUT_RDWR)

    def serve(self):
        while not self.stop.is_set():
            try:
                client, _ = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            self.connections += 1
            remote = socket.create_connection(("127.0.0.1", self.worker_port), timeout=2)
            remote.settimeout(None)
            self.sockets.extend([client, remote])
            reverse = threading.Thread(target=self.reverse, args=(remote, client), daemon=True)
            reverse.start()
            try:
                while not self.stop.is_set():
                    header = self.read(client, 9)
                    command, size = struct.unpack("<BQ", header)
                    if size > 2**20:
                        raise ValueError("fixture exceeded wire budget")
                    body = self.read(client, size)
                    self.frames.append((command, size))
                    if command in (10, 16) and self.fault:
                        self.fault_reached.set()
                        if self.fault == "stall":
                            self.stop.wait(10)
                        break
                    remote.sendall(header + body)
            except (OSError, EOFError):
                pass
            finally:
                for sock in (client, remote):
                    with contextlib.suppress(OSError):
                        sock.shutdown(socket.SHUT_RDWR)
                    sock.close()
                reverse.join(2)

    def close(self):
        self.stop.set()
        self.listener.close()
        for sock in self.sockets:
            with contextlib.suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)
            sock.close()
        self.thread.join(3)
        if self.thread.is_alive():
            raise AssertionError("proxy cleanup exceeded deadline")


@unittest.skipIf(os.environ.get("MOE_OVERLAP_SKIP_BUILD") == "1", "native build explicitly disabled")
class NativeMoEIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.binaries = load_build().build(ROOT / ".cache/native-moe-overlap", jobs=2)

    @contextlib.contextmanager
    def worker(self, fault=None):
        port = free_port()
        with tempfile.TemporaryFile(mode="w+") as log:
            process = subprocess.Popen([self.binaries["rpc-worker"]["path"], "--host", "127.0.0.1",
                                        "--port", str(port), "--device", "CPU", "--threads", "2"],
                                       stdout=log, stderr=log, start_new_session=True)
            proxy = None
            try:
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        log.seek(0)
                        self.fail("CPU RPC worker exited: " + log.read())
                    try:
                        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                            break
                    except OSError:
                        time.sleep(0.05)
                else:
                    self.fail("worker readiness exceeded deadline")
                proxy = WireProxy(port, fault)
                yield proxy
            finally:
                if proxy:
                    proxy.close()
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=5)
                self.assertIsNotNone(process.returncode)

    def run_fixture(self, mode=None, control="", proxy=None, timeout=20, capture=None):
        env = dict(os.environ)
        env.pop("IS309_MOE", None)
        env.pop("IS309_CAPTURE", None)
        if mode is not None:
            env["IS309_MOE"] = mode
        if capture is not None:
            env["IS309_CAPTURE"] = str(capture)
        # Native RPC errors are fail-stop; avoid the pin's interactive gdb
        # backtrace helper while testing process failure/cleanup.
        env["GGML_NO_BACKTRACE"] = "1"
        args = [self.binaries["native-ffn-fixture"]["path"], f"127.0.0.1:{proxy.port}"]
        if control:
            args.append(control)
        return subprocess.run(args, env=env, capture_output=True, text=True, timeout=timeout)

    def rows(self, result):
        self.assertEqual(result.returncode, 0, result.stderr[-4000:])
        records = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{"')]
        self.assertEqual(records[-1], {"released": True})
        self.assertEqual(len(records), 19)
        for record in records[:-1]:
            self.assertTrue(all(math.isfinite(x) for x in record["output"]), record)
        return records[:-1]

    def outputs(self, mode, control=""):
        with self.worker() as proxy:
            return self.rows(self.run_fixture(mode, control, proxy))

    def compare(self, a, b):
        self.assertEqual(len(a), len(b))
        for left, right in zip(a, b):
            differences = [abs(x - y) for x, y in zip(left["output"], right["output"])]
            diagnostic = {"shape": left["shape"], "step": left["step"], "max_abs": max(differences),
                          "rms": math.sqrt(sum(x*x for x in differences) / len(differences))}
            self.assertEqual(left["output"], right["output"], diagnostic)

    def test_native_serial_overlap_reuse_and_same_work(self):
        for control in ("", "merged", "q8"):
            with self.subTest(control=control):
                serial = self.outputs("0:serial", control)
                overlap = self.outputs("0:overlap", control)
                ordinary = self.outputs(None, control)
                self.compare(serial, overlap)
                self.compare(ordinary, serial)
                self.assertTrue(all(r["owners"] == 0 for r in ordinary))
                for shape in range(3):
                    rows = [r for r in overlap if r["shape"] == shape]
                    self.assertEqual([r["native_steps"] for r in rows], list(range(1, 7)))
                    for key in ("rpc_backend", "routed_buffer", "shared_buffer"):
                        self.assertEqual(len({r[key] for r in rows}), 1, key)
                    self.assertEqual(len({tuple(r["output"]) for r in rows}), 6)
                self.assertEqual(len({r["rpc_backend"] for r in overlap}), 1)

    def test_default_off_and_non_selected_invariance(self):
        ordinary = self.outputs(None)
        non_selected = self.outputs("1:overlap")
        self.compare(ordinary, non_selected)
        self.assertTrue(all(r["owners"] == 0 for r in non_selected))

    def test_shared_work_negative_control(self):
        complete = self.outputs("0:overlap")
        missing = self.outputs(None, "missing-shared")
        self.assertTrue(any(a["output"] != b["output"] for a, b in zip(complete, missing)))
        with self.assertRaises(AssertionError):
            self.compare(complete, missing)

    def test_refuses_unsupported_selection_and_placement(self):
        for mode, control, text in (("2:overlap", "", "outside the model"),
                                    ("0:other", "", "unsupported"),
                                    ("0:overlap", "wrong-placement", "already be resident"),
                                    ("0:overlap", "missing-selected", "gated shared")):
            with self.subTest(mode=mode, control=control), self.worker() as proxy:
                result = self.run_fixture(mode, control, proxy)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn(text, result.stderr)
                self.assertNotIn('"released":true', result.stdout)

    def test_wire_setup_steady_state_and_allocation_cleanup(self):
        with self.worker() as proxy:
            rows = self.rows(self.run_fixture("0:overlap", proxy=proxy))
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and sum(c == 4 for c, _ in proxy.frames) < sum(c == 0 for c, _ in proxy.frames):
                time.sleep(0.02)
            frames = list(proxy.frames)
            self.assertEqual(proxy.connections, 1)
        self.assertEqual(sum(c in (10, 16) for c, _ in frames), 18)
        self.assertEqual(sum(c == 0 for c, _ in frames), sum(c == 4 for c, _ in frames))
        # SET_TENSOR contains a 296-byte rpc_tensor and uint64 offset.
        sets = [size - 304 for command, size in frames if command == 6]
        setup = [size for size in sets if size > 4096]
        self.assertEqual(setup, [32 * 32 * 8 * 4] * 3)
        steady = [size for size in sets if size <= 4096]
        expected = []
        for row in rows:
            expected.extend([row["input_bytes"], row["routing_bytes"] // 2, row["routing_bytes"] // 2])
        self.assertEqual(steady, expected)

    def test_remote_failure_is_fail_stop_and_cleanup_is_bounded(self):
        with self.worker("disconnect") as proxy:
            result = self.run_fixture("0:overlap", proxy=proxy, timeout=10)
            self.assertTrue(proxy.fault_reached.is_set())
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('"released":true', result.stdout)

    def test_stalled_join_obeys_external_process_deadline(self):
        # The pinned transport has no socket deadline. The explicitly scoped
        # experiment is process-supervised; timeout kills the client, closes
        # the connection and then releases the worker. No retry/fallback.
        with self.worker("stall") as proxy:
            with self.assertRaises(subprocess.TimeoutExpired):
                self.run_fixture("0:overlap", proxy=proxy, timeout=2)
            self.assertTrue(proxy.fault_reached.is_set())

    def test_native_input_output_captures_and_numerical_diagnostics(self):
        spec = importlib.util.spec_from_file_location("native_moe_compare", ROOT / "tools/native-moe-overlap/compare.py")
        comparator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(comparator)
        with tempfile.TemporaryDirectory() as td:
            serial, overlap = Path(td) / "serial.bin", Path(td) / "overlap.bin"
            for mode, capture in (("0:serial", serial), ("0:overlap", overlap)):
                with self.worker() as proxy:
                    self.rows(self.run_fixture(mode, proxy=proxy, capture=capture))
            report = comparator.compare(serial, overlap)
            self.assertTrue(report["pass"], report)
            self.assertEqual(report["serial_records"], 18)
            self.assertTrue(all(r["output"]["max_abs"] == 0 for r in report["records"]))
            blob = bytearray(overlap.read_bytes())
            # Corrupt one finite result value; equality must fail and retain
            # the difference instead of inventing or widening a tolerance.
            struct.pack_into("<f", blob, comparator.HEADER.size + 32 * 4, 123.0)
            overlap.write_bytes(blob)
            bad = comparator.compare(serial, overlap)
            self.assertFalse(bad["pass"])
            self.assertGreater(bad["records"][0]["output"]["max_abs"], 100)
            overlap.write_bytes(blob[:-1])
            with self.assertRaisesRegex(ValueError, "truncated"):
                comparator.compare(serial, overlap)


class NativePackaging(unittest.TestCase):
    def test_model_hook_and_scheduler_waits_are_preserved(self):
        patch = (ROOT / "tools/native-moe-overlap/native.patch").read_text()
        self.assertIn("return build_qwen4exp_ffn(cur, model.layers[il]", patch)
        self.assertNotIn("ggml/src/ggml-backend.cpp", patch)
        self.assertNotIn("ggml/src/ggml-rpc", patch)
        self.assertNotIn("inferswarm/operator/qwen_q8.py", patch)

"""Focused Linux/TCP proof of the exact compiled candidate transport engine.

The tiny peer models existing ordered SHA/admission behavior. Native protocol
compatibility is additionally exercised with factorial-rpc-fixture and the
unchanged accepted CPU worker; these tests need no native source or hardware.
"""
import hashlib
import contextlib
import json
import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools/native-moe-overlap"


class FactorialTransport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("g++"):
            raise RuntimeError("focused transport proof requires g++")
        cls.work = tempfile.TemporaryDirectory(prefix="factorial-transport-")
        cls.binary = Path(cls.work.name) / "proof"
        subprocess.run(["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-O2",
                        str(TOOLS / "factorial_rpc_transport_test.cpp"),
                        "-o", str(cls.binary)], check=True, timeout=60)

    @classmethod
    def tearDownClass(cls):
        cls.work.cleanup()

    def run_peer(self, scenario, pipeline=True, size=65536, deadline_ms=3000):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        seen, failures = [], []

        def peer():
            try:
                connection, _ = listener.accept()
                with connection:
                    connection.settimeout(4)
                    connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    connection.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 16384)
                    connection.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1024)

                    def exact(n):
                        data = bytearray()
                        while len(data) < n:
                            part = connection.recv(min(n-len(data), 4093))
                            if not part:
                                raise EOFError
                            data.extend(part)
                        return bytes(data)

                    for index in range(3):
                        command = exact(1)[0]
                        length, = struct.unpack("<Q", exact(8))
                        self.assertEqual(command, 6)
                        self.assertEqual(length, 40+size)
                        header, payload = exact(40), exact(size)
                        item, = struct.unpack("<Q", header[:8])
                        self.assertEqual(item, index)
                        self.assertEqual(payload, bytes((index*29+j) & 255 for j in range(size)))
                        seen.append(item)
                        if scenario == "eof" and index == 1:
                            connection.shutdown(socket.SHUT_WR)
                            while connection.recv(65536):
                                pass
                            return
                        if scenario == "timeout" and index == 1:
                            # Let the client deadline expire; do not block this test.
                            connection.settimeout(1)
                            while connection.recv(65536):
                                pass
                            return
                        valid_sha = hashlib.sha256(payload).digest() == header[8:]
                        if not valid_sha:
                            # Existing v7 worker closes on SHA admission failure.
                            return
                        if scenario == "deferred" and index == 0:
                            # Require a second complete SET before acknowledging
                            # the first: proves actual pipelining without relying
                            # on scheduler timing or tiny latency differences.
                            continue
                        response = struct.pack("<Q", 2 if scenario == "malformed" and index == 1 else 1)
                        response += bytes([0 if scenario == "refused" and index == 1 else 1])
                        if scenario == "deferred" and index == 1:
                            response = struct.pack("<QB", 1, 1) + response
                        for byte in response:
                            connection.sendall(bytes([byte]))
                            if scenario == "fragmented":
                                time.sleep(0.0001)
                        if scenario in ("malformed", "refused") and index == 1:
                            # Incomplete group must shut down without GRAPH.
                            try:
                                while connection.recv(65536):
                                    pass
                            except ConnectionResetError:
                                pass
                            return
                    command = exact(1)[0]
                    self.assertEqual(command, 16)
                    self.assertEqual(exact(8), bytes(8))
                    seen.append("graph")
            except (EOFError, ConnectionResetError, BrokenPipeError):
                if scenario in ("success", "fragmented", "backpressure", "deferred"):
                    failures.append("unexpected connection termination")
            except BaseException as exc:
                failures.append(repr(exc))
            finally:
                listener.close()

        thread = threading.Thread(target=peer, daemon=True)
        thread.start()
        hashes = [hashlib.sha256(bytes((i*29+j) & 255 for j in range(size))).hexdigest() for i in range(3)]
        if scenario == "sha":
            hashes[1] = "0"*64
        result = subprocess.run([str(self.binary), str(port), str(int(pipeline)), str(deadline_ms),
                                 str(size), *hashes], capture_output=True, text=True, timeout=8)
        self.assertEqual(result.returncode, 0, result.stderr)
        thread.join(5)
        self.assertFalse(thread.is_alive(), "peer exceeded bounded proof budget")
        self.assertFalse(failures, (failures, result.stdout, seen))
        return json.loads(result.stdout), seen

    def assert_success(self, scenario, pipeline, size=65536):
        result, seen = self.run_peer(scenario, pipeline, size)
        self.assertEqual(result["status"], "none", result)
        self.assertEqual(seen, [0, 1, 2, "graph"])
        self.assertEqual(result["graph_sent"], 1)
        for frame in result["frames"]:
            self.assertLessEqual(frame["begin"], frame["end"])
            self.assertLessEqual(frame["end"], frame["ack"])
            self.assertLessEqual(frame["first"], frame["ack"])
            self.assertEqual(frame["tx"], size+40+9)
            self.assertEqual(frame["rx"], 9)
        if not pipeline:
            for left, right in zip(result["frames"], result["frames"][1:]):
                self.assertLessEqual(left["ack"], right["begin"])

    def test_serial_fragmented_order_lifetimes_counters(self):
        self.assert_success("fragmented", False)

    def test_pipeline_fragmented_order_lifetimes_counters(self):
        self.assert_success("fragmented", True)

    def test_pipeline_small_buffers_backpressure(self):
        self.assert_success("backpressure", True, 128*1024)

    def test_pipeline_multiple_outstanding_ordered_acks(self):
        self.assert_success("deferred", True)

    def test_refused_second_ack(self):
        result, seen = self.run_peer("refused")
        self.assertEqual(result["status"], "admission refused")
        self.assertEqual(result["graph_sent"], 0)
        self.assertNotIn("graph", seen)
        self.assertNotEqual(result["frames"][0]["ack"], 0)

    def test_malformed_second_ack(self):
        result, seen = self.run_peer("malformed")
        self.assertEqual(result["status"], "malformed response")
        self.assertEqual(result["graph_sent"], 0)
        self.assertNotIn("graph", seen)

    def test_eof_before_admission(self):
        result, seen = self.run_peer("eof")
        self.assertEqual(result["status"], "eof")
        self.assertEqual(result["graph_sent"], 0)
        self.assertNotIn("graph", seen)

    def test_sha_failure_closes_before_graph(self):
        result, seen = self.run_peer("sha")
        # An immediate worker close can reset TCP while later SET bytes are in
        # flight. Both EOF and reset are terminal, connection-poisoning errors.
        self.assertIn(result["status"], ("eof", "read", "write"))
        self.assertEqual(result["graph_sent"], 0)
        self.assertNotIn("graph", seen)

    def test_total_group_deadline(self):
        result, seen = self.run_peer("timeout", deadline_ms=250)
        self.assertEqual(result["status"], "deadline")
        self.assertEqual(result["graph_sent"], 0)
        self.assertNotIn("graph", seen)


@unittest.skipUnless(os.environ.get("IS_FACTORIAL_NATIVE_FIXTURE") and os.environ.get("IS_FACTORIAL_ACCEPTED_WORKER"),
                     "optional real native proof needs explicit fixture and unchanged CPU worker paths")
class FactorialNativeTransport(unittest.TestCase):
    """Real dispatcher/SHA/worker integration; no rebuild or model access."""
    @classmethod
    def setUpClass(cls):
        from tests.test_native_moe_overlap import WireProxy, free_port
        cls.proxy_type = WireProxy
        cls.free_port = staticmethod(free_port)
        cls.fixture = Path(os.environ["IS_FACTORIAL_NATIVE_FIXTURE"]).resolve(strict=True)
        cls.worker = Path(os.environ["IS_FACTORIAL_ACCEPTED_WORKER"]).resolve(strict=True)

    @contextlib.contextmanager
    def connection(self, corrupt_sha=False):
        base = self.proxy_type

        class ShaProxy(base):
            def serve(proxy):
                while not proxy.stop.is_set():
                    try:
                        client, _ = proxy.listener.accept()
                    except socket.timeout:
                        continue
                    except OSError:
                        break
                    remote = socket.create_connection(("127.0.0.1", proxy.worker_port), timeout=2)
                    remote.settimeout(None)
                    proxy.sockets.extend([client, remote])
                    reverse = threading.Thread(target=proxy.reverse, args=(remote, client), daemon=True)
                    reverse.start()
                    try:
                        while not proxy.stop.is_set():
                            header = proxy.read(client, 9)
                            command, length = struct.unpack("<BQ", header)
                            if length > 2**20:
                                raise AssertionError("native proof exceeded 1 MiB frame budget")
                            body = proxy.read(client, length)
                            proxy.frames.append((command, length))
                            if command == 6 and not proxy.fault_reached.is_set():
                                # Corrupt payload after the real client computed
                                # its SHA header. The unchanged worker must reject
                                # admission, close, and prevent any GRAPH send.
                                body = body[:-1] + bytes([body[-1] ^ 1])
                                proxy.fault_reached.set()
                            remote.sendall(header + body)
                    except (OSError, EOFError):
                        pass
                    finally:
                        for connection in (client, remote):
                            with contextlib.suppress(OSError):
                                connection.shutdown(socket.SHUT_RDWR)
                            connection.close()
                        reverse.join(2)

        port = self.free_port()
        with tempfile.TemporaryFile(mode="w+") as log:
            process = subprocess.Popen([str(self.worker), "--host", "127.0.0.1", "--port", str(port),
                                        "--device", "CPU", "--threads", "2"], stdout=log, stderr=log)
            proxy = None
            try:
                deadline = time.monotonic()+5
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        log.seek(0)
                        self.fail("unchanged CPU worker exited: "+log.read())
                    try:
                        with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                            break
                    except OSError:
                        time.sleep(0.02)
                else:
                    self.fail("native worker readiness deadline")
                proxy = (ShaProxy if corrupt_sha else base)(port)
                yield proxy
            finally:
                if proxy:
                    proxy.close()
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=5)

    def invoke(self, proxy, mode):
        env = dict(os.environ, GGML_NO_BACKTRACE="1")
        return subprocess.run([str(self.fixture), f"127.0.0.1:{proxy.port}", mode], env=env,
                              capture_output=True, text=True, timeout=15)

    def test_real_serial_and_pipeline_admissions_lifetimes_counters_recompute(self):
        for mode in ("serial", "pipeline"):
            with self.subTest(mode=mode), self.connection() as proxy:
                result = self.invoke(proxy, mode)
                self.assertEqual(result.returncode, 0, result.stderr)
                report = json.loads(result.stdout)
                self.assertTrue(report["passed"])
                self.assertEqual([step["recompute"] for step in report["steps"]], [0, 1])
                self.assertEqual(sum(command == 6 for command, _ in proxy.frames), 6)
                self.assertEqual(sum(command == 10 for command, _ in proxy.frames), 1)
                self.assertEqual(sum(command == 16 for command, _ in proxy.frames), 1)

    def test_real_worker_sha_rejection_prevents_graph_and_reuse(self):
        with self.connection(corrupt_sha=True) as proxy:
            result = self.invoke(proxy, "pipeline")
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(proxy.fault_reached.is_set())
            self.assertIn("factorial SET admission failed", result.stderr)
            self.assertFalse(any(command in (10, 16) for command, _ in proxy.frames))


if __name__ == "__main__":
    unittest.main()

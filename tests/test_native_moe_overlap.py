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
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "tools/native-moe-overlap/build.py"

# Portable resolution of the pinned llama.cpp source tree (b29c606e, tree
# 950999fe): an explicit env override, else the checkout beside the repo.
# Absent trees skip the optional source-bound assertions instead of failing;
# when present, BOTH the pinned commit and its tree SHA are authenticated.
_PIN_COMMIT = "b29c606e28a01b1bc8c1351026a0fa6e616bf6c4"
_PIN_TREE = "950999fe62b7fe55f44ab5b7394e3c8542f37f12"


def _pinned_source():
    import os
    import subprocess as _sp
    candidates = []
    override = os.environ.get("MOE_OVERLAP_PINNED_SOURCE")
    if override:
        candidates.append(Path(override))
    candidates.append(ROOT.parent / ("llama.cpp-" + _PIN_COMMIT[:7]))
    for source in candidates:
        if (source / "src/llama-graph.cpp").is_file():
            try:
                head = _sp.run(["git", "rev-parse", "HEAD"], cwd=source,
                               capture_output=True, text=True, timeout=30)
                tree = _sp.run(["git", "rev-parse", "HEAD^{tree}"], cwd=source,
                               capture_output=True, text=True, timeout=30)
            except (OSError, _sp.SubprocessError):
                return None
            if (head.returncode or tree.returncode
                    or head.stdout.strip() != _PIN_COMMIT
                    or tree.stdout.strip() != _PIN_TREE):
                raise AssertionError(
                    "pinned source tree identity drift: " + str(source))
            return source
    return None


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
        self.requests = []
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
                    if command in (6, 7) and len(body) >= 352:
                        self.requests.append(dict(cmd=command, tensor=body[228:292].split(b'\0',1)[0].decode('ascii'),
                            shape=list(struct.unpack_from('<IIII',body,20)),offset=struct.unpack_from('<Q',body,296)[0],
                            length=struct.unpack_from('<Q',body,312)[0],sha256=body[320:352].hex(),
                            payload=body[352:] if command==6 else None))
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


class NativeHotExperts(unittest.TestCase):
    """Real source FFN arithmetic vs original CPU, structural wire separately."""
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='native-hot-314-')
        cls.root = Path(cls.temp.name)
        path = ROOT / 'tools/native-moe-overlap/hot-build-composed.py'
        if not path.is_file():
            raise AssertionError('missing integrated hot candidate builder')
        spec = importlib.util.spec_from_file_location('hot_candidate', path)
        cls.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mod)
        retained = os.environ.get('IS314_NATIVE_BUILD')
        if retained:
            cls.build = Path(retained)
        else:
            pin = cls.mod.base.pin
            cache = Path(os.environ.get('MOE_OVERLAP_CACHE', cls.root / 'pin'))
            cache.mkdir(parents=True, exist_ok=True)
            pin.pin.ensure_source(cache)
            result = cls.mod.build(os.environ.get('MOE_OVERLAP_TARBALL', cache / 'pin.tar.gz'),
                                   cls.root / 'candidate', 'cmake', fixtures_only=True, portable_fixtures=True)
            cls.build = Path(result['build_directory'])
        cls.binaries = {n: {'path': str(cls.build / 'bin' / n)} for n in ('rpc-worker', 'native-hot-fixture')}
        cls.selected = [8, 1, 6, 3, 0, 9, 2, 7, 4, 5]
        import hashlib
        cls.bank_bytes = {}
        cls.q8_bytes = {}
        for kind in ('gate', 'up', 'down'):
            values = []
            for eid in range(12):
                for row in range(32):
                    for col in range(32):
                        # Nonuniform signed outputs including cancelling pairs.
                        value = (eid + 1) / 64 if row == col else 0.0
                        if kind == 'down': value *= (-1 if eid % 2 else 1)
                        values.append(value)
            data = struct.pack('<' + 'f' * len(values), *values)
            (cls.root / (kind + '.bin')).write_bytes(data)
            cls.bank_bytes[kind] = data
            blocks=bytearray()
            for eid in range(12):
                for row in range(32):
                    qs=[0]*32; qs[row]=(eid+1)*(-1 if kind=='down' and eid%2 else 1)
                    blocks.extend(struct.pack('<e32b',1/64,*qs))
            cls.q8_bytes[kind]=bytes(blocks)
            (cls.root/(kind+'.q8.bin')).write_bytes(blocks)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    worker = NativeMoEIntegration.worker

    def configure(self, count, endpoint, q8=False, **updates):
        import hashlib
        ids = self.selected[:count]
        if count == 10: ids = ids + [10, 11]  # generic >=10 immutable list
        rows = []
        stride=1088 if q8 else 4096
        for kind, data in (self.q8_bytes if q8 else self.bank_bytes).items():
            packed = b''.join(data[e*stride:(e+1)*stride] for e in ids)
            rows.append(dict(source_name=f'blk.7.ffn_{kind}_exps.weight',
                compact_name=f'is314.fixture.{count}.{kind}', ggml_type=8 if q8 else 0,
                source_shape=[32,32,12,1],compact_shape=[32,32,len(ids),1],
                source_sha256=hashlib.sha256(data).hexdigest(),
                compact_sha256=hashlib.sha256(packed).hexdigest(), expert_bytes=stride,
                ranges=[dict(expert_id=e,source_offset=e*stride,destination_offset=i*stride,length=stride)
                        for i,e in enumerate(ids)]))
        spec = dict(schema='is314-hot-experts/1',layer=7,rpc_backend=f'RPC[{endpoint}]',expert_ids=ids,tensors=rows)
        spec.update(updates)
        path = self.root / 'spec.json'; path.write_text(json.dumps(spec))
        guard = self.root / 'assigned.txt'
        guard.write_text(''.join(f"{r['compact_name']} {r['ggml_type']} " +
            ' '.join(map(str,r['compact_shape'])) + f" {stride*len(ids)} {r['compact_sha256']}\n" for r in rows))
        return path, guard, spec

    def run_hot(self, proxy, count=None, control='', timeout=20):
        endpoint = f'127.0.0.1:{proxy.port}'
        env = dict(os.environ, GGML_NO_BACKTRACE='1')
        for key in ('IS309_MOE', 'IS309_CAPTURE', 'IS314_HOT_SPEC', 'IS311_ASSIGNED'): env.pop(key,None)
        if count is not None:
            path, guard, _ = self.configure(count, endpoint,q8=control=='q8')
            env.update(IS314_HOT_SPEC=str(path),IS311_ASSIGNED=str(guard))
        return subprocess.run([self.binaries['native-hot-fixture']['path'],endpoint,str(self.root),control],
                              env=env,capture_output=True,text=True,timeout=timeout)

    def rows(self, result):
        self.assertEqual(result.returncode,0,result.stderr[-4000:])
        rows = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
        self.assertEqual(rows[-1], {'released': True})
        return rows[:-1]

    def test_hot_candidate_builder_is_additive(self):
        self.assertEqual(self.mod.optimized.optimized_options(),self.mod.build_options())
        receipt = json.loads((self.build.parent/'hot-candidate-receipt.json').read_text())
        self.assertEqual(receipt['rpc_protocol']['major'],7)
        self.assertTrue(receipt['backend_libraries'])
        self.assertTrue(receipt['source_inputs'])
        self.assertTrue(receipt['compiler_versions']['CXX']['sha256'])

    def test_all_hot_counts_source_order_arithmetic_and_reuse(self):
        with self.worker() as proxy: ordinary = self.rows(self.run_hot(proxy))
        for count in range(11):
            with self.subTest(hot=count), self.worker() as proxy:
                result = self.run_hot(proxy,count)
                rows = self.rows(result)
                self.assertEqual([r['output'] for r in rows],[r['output'] for r in ordinary])
                self.assertEqual(rows[0]['hot'],count)
                self.assertEqual(rows[0]['cold'],10-count)
                self.assertEqual(result.stderr.count('IS314_SETUP'),1)
                self.assertTrue(all(r['owners']==0 for r in rows if r['tokens']>1 or r['layer']!=7))
                self.assertEqual(len({r['output'][0] for r in rows[:3]}),3)
                self.assertEqual(len({r['compact_owner'] for r in rows if r['owners']}),1)
                self.assertEqual(proxy.connections,1)
                dispatches = sum(c in (10,16) for c,_ in proxy.frames)
                self.assertEqual(dispatches, sum(r['hot']>0 for r in rows))

    def test_routing_changes_keep_exact_hot_cold_partitions(self):
        import re
        with self.worker() as proxy: baseline = self.rows(self.run_hot(proxy))
        for count in range(11):
            with self.subTest(hot=count), self.worker() as proxy:
                result = self.run_hot(proxy,count)
                rows = self.rows(result)
                self.assertEqual([r['output'] for r in rows],[r['output'] for r in baseline])
                routed = [r for r in rows if r['owners']]
                steps = re.findall(r'IS314_STEP .*?hot=(\d+) cold=(\d+) .*?ids=([0-9,]+) weight_bits=([0-9a-f,]+)',result.stderr)
                self.assertEqual(len(steps),len(routed))
                self.assertGreaterEqual(len({s[2] for s in steps}),2)
                hot_ids = set(self.selected[:count] + ([10,11] if count==10 else []))
                for row, (hot,cold,ids,bits) in zip(routed,steps):
                    ids = [int(x) for x in ids.split(',')]
                    weights = bits.split(',')
                    self.assertEqual(len(ids),10)
                    self.assertEqual(len(set(ids)),10)
                    self.assertEqual(len(weights),10)
                    self.assertGreater(len(set(weights)),1)
                    expected = sum(e in hot_ids for e in ids)
                    self.assertEqual((int(hot),int(cold)),(expected,10-expected))
                    self.assertEqual((row['hot'],row['cold']),(expected,10-expected))

    def test_encoded_q8_0_slices_use_real_source_moe_graph(self):
        with self.worker() as proxy: baseline=self.rows(self.run_hot(proxy,None,'q8'))
        for count in (0,5,10):
            with self.subTest(hot=count),self.worker() as proxy:
                actual=self.rows(self.run_hot(proxy,count,'q8'))
                self.assertEqual([r['output'] for r in actual],[r['output'] for r in baseline])
                sets=[r for r in proxy.requests if r.get('tensor','').startswith('is314.')]
                self.assertEqual(len(sets),0 if count==0 else 3)
                ids=self.selected[:count]+([10,11] if count==10 else [])
                for row in sets:
                    kind=row['tensor'].rsplit('.',1)[1]
                    source=self.q8_bytes[kind]
                    expected=b''.join(source[e*1088:(e+1)*1088] for e in ids)
                    self.assertEqual((row['cmd'],row['offset'],row['shape']),
                                     (6,0,[32,32,len(ids),1]))
                    self.assertEqual(row['length'],len(expected))
                    self.assertEqual(row['payload'],expected)  # encoded bytes, no requantization
                    import hashlib
                    self.assertEqual(row['sha256'],hashlib.sha256(expected).hexdigest())

    def test_setup_weights_uploaded_once_no_steady_weights(self):
        with self.worker() as proxy:
            rows = self.rows(self.run_hot(proxy,5))
            requests = list(proxy.requests)
        weights = [r for r in requests if r.get('tensor','').startswith('is314.')]
        self.assertEqual(len(weights),3)
        for row in weights:
            self.assertEqual((row['cmd'],row['offset'],row['length']),(6,0,5*4096))
            self.assertEqual(row['shape'],[32,32,5,1])
        self.assertFalse(any(r.get('tensor','').startswith('blk.7.') for r in requests))
        self.assertEqual(sum(c==0 for c,_ in proxy.frames),sum(c==4 for c,_ in proxy.frames))

    def test_single_token_prefill_keeps_real_phase(self):
        for control in ('prefill','prefill-no-collector'):
            with self.subTest(control=control), self.worker() as proxy:
                rows = self.rows(self.run_hot(proxy,5,control))
                self.assertEqual(rows[0]['phase'],'prefill')
                self.assertEqual(rows[0]['hot'],5)

    def test_shared_omission_and_slot_permutation_are_detectable(self):
        with self.worker() as proxy: baseline = self.rows(self.run_hot(proxy))
        for control in ('missing-shared','reverse-reduction'):
            with self.subTest(control=control), self.worker() as proxy:
                mutated = self.rows(self.run_hot(proxy,None,control))
                self.assertTrue(any(a['output'] != b['output'] for a,b in zip(baseline,mutated)))

    def test_exact_derived_guard_refuses_partial_view_duplicate_destination(self):
        for control in ('guard-partial','guard-view','guard-duplicate'):
            with self.subTest(control=control), self.worker() as proxy:
                result=self.run_hot(proxy,5,control)
                self.assertNotEqual(result.returncode,0)
                self.assertIn('assigned upload refused',result.stderr)
                self.assertNotIn('IS314_STEP',result.stderr)

    def test_hot_remote_disconnect_and_stall_are_not_fallback(self):
        with self.worker('disconnect') as proxy:
            result = self.run_hot(proxy,5,timeout=10)
            self.assertTrue(proxy.fault_reached.is_set())
            self.assertNotEqual(result.returncode,0)
            self.assertNotIn('"released":true',result.stdout)
        with self.worker('stall') as proxy:
            with self.assertRaises(subprocess.TimeoutExpired): self.run_hot(proxy,5,timeout=2)
            self.assertTrue(proxy.fault_reached.is_set())


class NativePackaging(unittest.TestCase):
    def test_model_hook_and_scheduler_waits_are_preserved(self):
        patch = (ROOT / "tools/native-moe-overlap/native.patch").read_text()
        self.assertIn("return build_qwen4exp_ffn(cur, model.layers[il]", patch)
        self.assertNotIn("ggml/src/ggml-backend.cpp", patch)
        self.assertNotIn("ggml/src/ggml-rpc", patch)
        self.assertNotIn("inferswarm/operator/qwen_q8.py", patch)


class NativeDemandCPU(unittest.TestCase):
    """Compile only the tiny capture seam; never build or run llama here."""
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.binary = Path(cls.tmp.name) / "demand-fixture"
        cls.tool = ROOT / "tools/native-moe-overlap"
        subprocess.run(["c++", "-std=c++17", "-O0", "-I", str(cls.tool),
                        str(cls.tool / "demand_fixture.cpp"),
                        str(cls.tool / "demand.cpp"), "-o", str(cls.binary)], check=True)
        spec = importlib.util.spec_from_file_location("native_demand_summary", cls.tool / "summarize_demand.py")
        cls.summary = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.summary)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def fixture(self, scenario):
        p = subprocess.run([str(self.binary), scenario], capture_output=True, text=True, check=True)
        return json.loads(p.stdout)

    def expected(self):
        return {"model_source": "qwen3.8", "model_revision": "r38", "model_sha256": "a" * 64,
                "representation": "Q8", "native_source": "b29c606e28a01b1bc8c1351026a0fa6e616bf6c4",
                "native_build_sha256": "b" * 64, "workload_sha256": "c" * 64}

    def test_per_layer_phase_and_joint_demand_from_real_capture(self):
        capture = self.fixture("ordinary")
        self.assertEqual(capture["rows"][0]["phase"], "prefill")  # one token, never inferred decode
        self.assertEqual(capture["rows"][0]["tokens"], [[1, 3]])
        self.assertEqual(capture["rows"][1]["tokens"], [[2, 3]])
        self.assertEqual(capture["rows"][2]["phase"], "decode")
        report = self.summary.summarize(capture, self.expected())
        self.assertEqual(report["phase_demand"]["prefill"]["0"]["frequency"], {"1": 1, "3": 1})
        self.assertEqual(report["phase_demand"]["prefill"]["0"]["co_selection"], {"1,3": 1})
        self.assertEqual(report["phase_demand"]["decode"]["0"]["frequency"], {"1": 1, "2": 1})
        self.assertEqual(report["phase_demand"]["prefill"]["1"]["frequency"], {"2": 1, "3": 1})
        self.assertEqual(report["coverage"]["complete"], True)
        self.assertIsNone(report["costs"]["per_expert_execution_ms"])
        self.assertIsNone(report["costs"]["link_ms"])

    def test_repeat_export_is_identical_and_default_off_is_inert(self):
        self.assertTrue(self.fixture("repeat")["identical"])
        self.assertEqual(self.fixture("off"), {"active": False, "rows": 0})

    def test_two_token_prefill_retains_final_output_position(self):
        capture = self.fixture("prefill-last")
        early, final = capture["rows"][:2]
        self.assertEqual(early["tokens"], [[1, 3], [0, 2]])
        self.assertEqual(early["token_positions"], [0, 1])
        self.assertEqual(final["tokens"], [[2, 3]])
        self.assertEqual(final["token_positions"], [1])
        self.assertEqual([r["token_positions"] for r in capture["rows"][2:]], [[2], [2]])
        report = self.summary.summarize(capture, self.expected())
        self.assertTrue(report["coverage"]["complete"])
        self.assertEqual(report["coverage"]["expected_token_rows"], 5)
        self.assertEqual(report["coverage"]["retained_token_rows"], 5)
        self.assertEqual(report["phase_demand"]["prefill"]["0"]["tokens"], 2)
        self.assertEqual(report["phase_demand"]["prefill"]["1"]["tokens"], 1)
        self.assertEqual(report["coverage"]["retained_token_positions"][1],
                         {"phase": "prefill", "step": 0, "layer": 1, "token_positions": [1]})

    def test_output_selected_coverage_preserves_missing_and_rejects_duplicates(self):
        capture = self.fixture("prefill-missing")
        report = self.summary.summarize(capture, self.expected())
        self.assertFalse(report["coverage"]["complete"])
        self.assertEqual(report["coverage"]["missing_layer_steps"], [{"step": 0, "layer": 1}])
        self.assertNotIn("1", report["phase_demand"]["prefill"])
        self.assertEqual(report["coverage"]["retained_token_rows"], 4)
        self.assertTrue(self.fixture("prefill-duplicate")["duplicate_refused"])
        capture = self.fixture("prefill-last")
        capture["rows"].append(capture["rows"][1])
        capture["observed_rows"] += 1
        with self.assertRaisesRegex(ValueError, "duplicate layer"):
            self.summary.summarize(capture, self.expected())

    def test_private_final_router_uses_same_positions_and_actual_row_budget(self):
        capture = self.fixture("prefill-private")
        self.assertEqual(capture["rows"][1]["token_positions"], [1])
        self.assertTrue(self.summary.summarize(capture, self.expected())["coverage"]["complete"])
        capture = self.fixture("final-cost-budget")
        self.assertEqual((capture["observed_rows"], capture["dropped_rows"]), (2, 1))
        self.assertEqual([r["layer"] for r in capture["rows"]], [0])
        self.assertEqual(capture["rows"][0]["token_positions"], [0, 1])
        self.assertFalse(self.summary.summarize(capture, self.expected())["coverage"]["complete"])

    def test_reducer_checks_exact_supported_token_position_mapping(self):
        for row_index, positions in ((0, [0, 0]), (0, [1, 0]), (1, [0]), (1, []), (2, [0])):
            with self.subTest(row=row_index, positions=positions):
                capture = self.fixture("prefill-last")
                capture["rows"][row_index]["token_positions"] = positions
                with self.assertRaisesRegex(ValueError, "token position"):
                    self.summary.summarize(capture, self.expected())
        capture = self.fixture("prefill-last")
        del capture["token_coverage"]
        with self.assertRaisesRegex(ValueError, "unsupported token coverage"):
            self.summary.summarize(capture, self.expected())

    def test_collector_does_not_mutate_router_ids_or_caller_output(self):
        self.assertEqual(self.fixture("integrity"), {"ids_unchanged": True, "output_equal": True})

    def test_repeated_steps_count_the_same_selected_pair_twice(self):
        capture = self.fixture("repeated-steps")
        report = self.summary.summarize(capture, self.expected())
        self.assertEqual(report["phase_demand"]["decode"]["0"]["co_selection"]["1,2"], 2)
        self.assertEqual(report["coverage"]["expected_rows"], 6)
        self.assertTrue(report["coverage"]["complete"])

    def test_bounded_capture_and_missing_layer_are_not_claimed_complete(self):
        capture = self.fixture("bounded")
        self.assertEqual(capture["step_meta"], [{"phase": "prefill", "step": 0, "tokens": 1, "token_start": 0},
                                                {"phase": "decode", "step": 1, "tokens": 1, "token_start": 1}])
        report = self.summary.summarize(capture, self.expected())
        self.assertEqual(report["coverage"]["dropped_rows"], 2)
        self.assertEqual(report["coverage"]["missing_layers"], [1])
        self.assertFalse(report["coverage"]["complete"])
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            self.summary.summarize(capture, {**self.expected(), "model_source": "qwen3.6"})
        with self.assertRaisesRegex(ValueError, "truncated"):
            self.summary.summarize({**capture, "rows": capture["rows"][:-1]}, self.expected())

    def test_byte_budget_drops_whole_rows_without_partial_ids(self):
        capture = self.fixture("byte-budget")
        report = self.summary.summarize(capture, self.expected())
        self.assertFalse(report["coverage"]["complete"])
        self.assertGreater(report["coverage"]["dropped_rows"], 0)
        self.assertEqual(report["coverage"]["retained_rows"] + report["coverage"]["dropped_rows"],
                         report["coverage"]["observed_rows"])

    def test_native_callback_is_bound_to_computed_argsort_and_private_router(self):
        cli = (self.tool / "demand_cli.cpp").read_text()
        private = (self.tool / "overlay/src/llama-moe-overlap.cpp").read_text()
        self.assertIn('is312::observe_argsort(', cli)
        self.assertIn('ggml_backend_tensor_get(static_cast<ggml_tensor *>(source)', cli)
        self.assertIn('s.ids->data', private)
        self.assertIn('is312::active()', private)
        self.assertIn('if (std::getenv("IS309_CAPTURE")) throw', cli)
        self.assertNotIn('IS309_CAPTURE', (self.tool / "demand.cpp").read_text())
        source = _pinned_source()
        if source is not None:
            self.assertIn('cb(selected_experts->src[0], "ffn_moe_argsort", il);',
                          (source / 'src/llama-graph.cpp').read_text())
            subprocess.run(['c++', '-std=c++17', '-fsyntax-only', '-I', str(source / 'include'),
                            '-I', str(source / 'ggml/include'), '-I', str(self.tool),
                            str(self.tool / 'demand_cli.cpp')], check=True)

    def test_selected_layer_uses_existing_native_rpc_override_seam(self):
        cli = (self.tool / "demand_cli.cpp").read_text()
        private = (self.tool / "overlay/src/llama-moe-overlap.cpp").read_text()
        self.assertIn('ggml_backend_rpc_add_server(', cli)
        self.assertIn('ggml_backend_rpc_buffer_type(', cli)
        self.assertIn('params.tensor_buft_overrides =', cli)
        self.assertIn('"--rpc-tensors-regex"', cli)
        self.assertIn('is312::dedicated_callback(cparams.cb_eval)', private)

    def test_computed_argsort_adapter_strided_prefill_decode_and_failures(self):
        result = self.fixture("adapter")
        self.assertEqual(result["rows"][0]["tokens"], [[1, 3], [0, 2], [2, 1]])
        self.assertEqual(result["rows"][0]["phase"], "prefill")
        self.assertEqual(result["rows"][1]["phase"], "decode")
        self.assertEqual(result["rows"][1]["tokens"], [[3, 0]])
        self.assertEqual(result["read_bytes"], 32)  # only K=2 IDs x four tokens
        self.assertTrue(result["nonmatching_ignored"])
        self.assertTrue(result["ids_unchanged"])
        self.assertTrue(result["output_equal"])
        self.assertTrue(result["shape_failed"])
        self.assertTrue(result["type_failed"])
        self.assertTrue(result["layer_failed"])
        self.assertEqual(self.fixture("off"), {"active": False, "rows": 0})

    def test_dedicated_capture_exceeds_generic_observer_limit(self):
        capture = self.fixture("large")
        self.assertEqual(capture["observed_rows"], 48 * 13)
        self.assertEqual(len(capture["rows"]), 48 * 13)
        self.assertEqual(capture["dropped_rows"], 0)
        self.assertTrue(self.summary.summarize(capture, self.expected())["coverage"]["complete"])

    def test_measured_private_overlap_costs_follow_phase_step_layer(self):
        capture = self.fixture("costs")
        report = self.summary.summarize(capture, self.expected())
        row = capture["rows"][0]
        self.assertEqual((row["phase"], row["step"], row["layer"]), ("prefill", 0, 0))
        costs = row["cost_observations"]
        self.assertEqual({x["metric"]["name"] for x in costs},
                         {"dispatch_ms", "shared_ms", "join_ms", "input_bytes", "routing_bytes", "result_bytes"})
        for item in costs:
            self.assertEqual(item["evidence_class"], "measured")
            self.assertEqual(item["metric"]["statistic"], "observation")
        self.assertEqual(next(x["metric"]["value"] for x in costs if x["metric"]["name"] == "join_ms"), 0.75)
        self.assertEqual(report["costs"]["observations"], costs)
        self.assertEqual(report["costs"]["rows"], [{"phase": "prefill", "step": 0,
                                                    "layer": 0, "observations": costs}])
        self.assertIsNone(report["costs"]["per_expert_execution_ms"])
        self.assertIsNone(report["costs"]["link_ms"])
        self.assertEqual({x["metric"]["name"] for x in report["costs"]["unknown"]},
                         {"device_kernel_ms", "per_expert_execution_ms", "link_ms"})
        self.assertTrue(all(x["metric"]["value"] is None and x["evidence_class"] == "unknown"
                            for x in report["costs"]["unknown"]))

    def test_cost_budget_discards_id_row_as_one_unit(self):
        capture = self.fixture("cost-budget")
        self.assertEqual(capture["observed_rows"], 1)
        self.assertEqual(capture["dropped_rows"], 1)
        self.assertEqual(capture["rows"], [])
        self.assertFalse(self.summary.summarize(capture, self.expected())["coverage"]["complete"])

    def test_profiler_is_active_before_context_reservation_builds_overlap_graph(self):
        # Pinned llama_context construction reserves/builds graphs before the
        # first decode. Its existing callback refusal must admit this profiler
        # during reservation too, without recording a synthetic token step.
        cli = (self.tool / "demand_cli.cpp").read_text()
        self.assertLess(cli.index('is312::set_active(&cap);'),
                        cli.index('llama_init_from_model(model.get(), cp)'))
        self.assertLess(cli.index('llama_init_from_model(model.get(), cp)'),
                        cli.index('cap.begin("prefill", 0,'))

    def test_only_registered_callback_is_admitted_during_capture(self):
        self.assertEqual(self.fixture("callback-identity"),
                         {"off_refused": True, "other_refused": True, "dedicated_accepted": True})

    def test_resource_snapshot_reuses_validated_types_without_claiming_freshness(self):
        fixture_spec = importlib.util.spec_from_file_location("issue299_fixture", ROOT / "tests/issue299_fixture.py")
        fixture = importlib.util.module_from_spec(fixture_spec)
        fixture_spec.loader.exec_module(fixture)
        snapshot = fixture.synthetic_profiles()
        runtime = snapshot["runtime_capabilities"][0]
        runtime["source_revision"] = self.expected()["native_source"]
        runtime["binary_sha256"] = self.expected()["native_build_sha256"]
        fixture.reseal_profiles(snapshot)
        report = self.summary.summarize(self.fixture("ordinary"), self.expected(), snapshot)
        self.assertEqual(report["resources"]["digest"], fixture.profile_digest(snapshot))
        self.assertIn(runtime["runtime_id"], report["resources"]["runtime_ids"])
        self.assertIn("A-B", report["resources"]["link_ids"])
        self.assertEqual(report["resources"]["runtime_evidence"][runtime["evidence_id"]],
                         next(e["sha256"] for e in snapshot["evidence"] if e["evidence_id"] == runtime["evidence_id"]))
        self.assertNotEqual(report["resources"]["validation"], "fresh")
        self.assertEqual(self.summary.summarize(self.fixture("ordinary"), self.expected())["resources"]["validation"], "unknown")
        with tempfile.TemporaryDirectory() as td:
            capture_path, profiles_path = Path(td) / "capture.json", Path(td) / "profiles.json"
            capture_path.write_text(json.dumps(self.fixture("ordinary")))
            profiles_path.write_text(json.dumps(snapshot))
            args = [sys.executable, str(self.tool / "summarize_demand.py"),
                    str(capture_path), "--resource-profiles", str(profiles_path)]
            for key, value in self.expected().items():
                args.extend(["--" + key.replace("_", "-"), value])
            cli = subprocess.run(args, capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(cli.stdout)["resources"]["digest"], report["resources"]["digest"])
        with self.assertRaisesRegex(ValueError, "native runtime"):
            self.summary.summarize(self.fixture("ordinary"), self.expected(), fixture.synthetic_profiles())
        snapshot["evidence"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "evidence SHA-256"):
            self.summary.summarize(self.fixture("ordinary"), self.expected(), snapshot)

    def test_identity_provenance_and_bounded_prompt_and_minimal_build_recipe(self):
        capture = self.fixture("ordinary")
        self.assertEqual(capture["identity_provenance"]["workload_sha256"], "operator_attested")
        self.assertEqual(capture["identity_provenance"]["native_build_sha256"], "operator_attested")
        self.assertEqual(capture["observed_gguf"]["architecture"], "qwen4exp")
        cli = (self.tool / "demand_cli.cpp").read_text()
        self.assertIn('std::string prompt(65537', cli)
        self.assertIn('optional_metadata(model.get(), "general.name")', cli)
        build = (self.tool / "build.py").read_text()
        self.assertIn('demand_profile=False', build)
        self.assertIn('parser.add_argument("--demand"', build)
        self.assertIn('if demand_profile:', build)

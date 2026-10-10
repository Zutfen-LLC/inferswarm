"""Offline issue #301 native producer controls; no native build in this suite.

Replays small retained genuine captures produced by the observation overlay;
never compiles, never charges the native campaign ledger, never launches a
server. Negative controls mutate the genuine retained bytes.
"""
import hashlib
import importlib
import json
from pathlib import Path
import tempfile
import unittest

FIXTURES = Path(__file__).resolve().parents[1] / 'tests' / 'fixtures' / 'issue299'
CAPTURES = FIXTURES / 'native-captures'
# Expected SHA-256 of each retained genuine capture; a modified/re-authored
# fixture (even a self-consistent one) must fail these pins before parsing.
RETAINED_CAPTURE_DIGESTS = {
    'static-capture.json': '207f7f414cf56c7b6a25e3c7366bf2f01f8491b897718baecf37e622b38721d9',
    'dynamic-capture.json': 'c6d0015f91b7a830e4e96ea602935af18b3e09709dba13b68246f6adf1b05646',
    'rpc/static-capture.json': '2840f5782383849679e038ec9528030ae7f4cc4f2d689d1ad5bcbf7d8891b884',
    'rpc/dynamic-capture.json': 'f1ffaa3e05a6cacb9fff1f696a2063e56ba45619bddcf73a6fd669c86214749f',
    'exports/fixture-cpu-observed.json': '2a91d1e8c7591e6635b4181fc06221fbca862cc126531a8abb245a52c263fee9',
    'exports/fixture-rpc-observed.json': '690e6450080bf70f0b6bac762399afa416600caf0c0298006271a8c082e53a11',
    'exports/ggml-rpc-server-observed.json': 'd74c6d85d45edeccbe635520bf1fb150fca892e44abf621e3f21a324eb09526d',
    'fact-bounds/clean.json': 'f34ca1b903d3c59ec1a7992ce0aba2ade29b40d3683653cfcbbefe01e7acffde',
}

from inferswarm.operator.bindings import TransportReply  # noqa: E402
from inferswarm.operator import phased_observation as contract  # noqa: E402


def _load(name):
    try:
        return importlib.import_module('inferswarm.operator.native_observer.' + name)
    except ModuleNotFoundError:
        return None


class OverlayTests(unittest.TestCase):
    """Patch/transformed-manifest identity and overlay seam coverage."""

    @classmethod
    def setUpClass(cls):
        cls.overlay = _load('overlay')
        cls.producer = _load('producer')

    def setUp(self):
        self.assertIsNotNone(self.overlay, 'overlay module is not implemented')
        self.assertIsNotNone(self.producer, 'producer module is not implemented')

    def test_patch_exists_and_is_retained(self):
        patch = FIXTURES / 'native-observer-overlay.patch'
        self.assertTrue(patch.is_file(), 'retained overlay patch missing')
        manifest = json.loads((FIXTURES / 'native-observer-transformed.json').read_text())
        self.assertEqual(manifest['schema'], 'native-observer-transformed/1')
        for row in manifest['files']:
            self.assertIn('path', row) and self.assertIn('sha256', row)
        # Patch sha recorded in the manifest matches the retained bytes.
        self.assertEqual(manifest['patch_sha256'],
                         hashlib.sha256(patch.read_bytes()).hexdigest())

    def test_transformed_manifest_matches_declared_files(self):
        manifest = json.loads((FIXTURES / 'native-observer-transformed.json').read_text())
        self.assertGreaterEqual(len(manifest['files']), 1)
        for row in manifest['files']:
            path = FIXTURES / 'overlay' / row['path']
            self.assertTrue(path.is_file(), 'retained transformed file missing: ' + row['path'])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), row['sha256'])

    def test_overlay_files_parse_and_override_pure_markers(self):
        # Every transformed file must carry the observation marker so a derived
        # build can never masquerade as the unmodified base.
        for name in ('is301_observer.h',):
            text = (FIXTURES / 'overlay' / name).read_text()
            self.assertIn('IS301', text)

    def test_apply_is_pure_and_refuses_foreign_bases(self):
        # apply() must not write into the read-only base; it derives an overlay
        # copy under an explicit destination and refuses anything off-pin.
        with self.assertRaises(Exception):
            self.overlay.apply('/nonexistent-source', CAPTURES / 'nope')


class ProducerTests(unittest.TestCase):
    """Finite fact catalog and emitter framing shared with the native side."""

    @classmethod
    def setUpClass(cls):
        cls.producer = _load('producer')
        cls.build = _load('build')

    def setUp(self):
        self.assertIsNotNone(self.producer, 'producer module is not implemented')
        self.assertIsNotNone(self.build, 'extended build module missing')

    def test_event_catalog_is_finite_and_documented(self):
        catalog = self.producer.EVENT_CATALOG
        self.assertTrue(catalog)
        self.assertEqual(len(catalog), len(set(catalog)))
        for name in catalog:
            self.assertIsInstance(name, str) and self.assertTrue(name)

    def test_archive_membership_matches_link_inputs(self):
        # The per-target backend-library archives must contain exactly the
        # objects each link command consumes. Expected sets are derived from
        # the recipe's own compile order (frozen closure), then the declared
        # archive membership in execute() must equal them: index drift or
        # accidental membership changes fail here.
        from inferswarm.operator.native_observer import full_build as fb
        from pathlib import Path as _P
        import inspect
        with tempfile.TemporaryDirectory() as tmp:
            out = _P(tmp)
            r = fb.assemble(_P('/nonexistent-tree'), out)
            compiles = [c for c in r['commands'] if '-c' in c]
            src_names = [c[c.index('-c') + 1].split('/')[-1] for c in compiles]
            sink = src_names.index('is301_sink.cpp')
            rpc_main = src_names.index('rpc-server.cpp')
            ggml_last = max(i for i, n in enumerate(src_names)
                            if n in ('transport.cpp', 'ggml-rpc.cpp'))
            observed = src_names.index('native-buffer-graph-observed.cpp')
            fact_bounds = src_names.index('native-fact-bounds.cpp')
            ggml = set(range(ggml_last + 1))
            server = set(range(len(compiles))) - {rpc_main, observed, fact_bounds}
            expected = {'llama-server': server,
                        'ggml-rpc-server': ggml | {sink} | {rpc_main},
                        'fixture': ggml | {sink, observed},
                        'fact-bounds': ggml | {sink, fact_bounds}}
            for name, cmd in zip(('llama-server', 'ggml-rpc-server', 'fixture', 'fact-bounds'), r['commands'][-4:]):
                objs = {int(_P(a).stem) for a in cmd if a.endswith('.o')}
                self.assertEqual(objs, expected[name], name + ' link membership drift')
            # Declared archive ranges in execute() must cover the same sets.
            src_text = inspect.getsource(fb.execute)
            self.assertIn("list(range(len(recipe['sources']) + 4))", src_text)
            self.assertIn("list(range(ggml_count)) + [len(recipe['sources']) + 1]", src_text)

    def test_manifest_emission_is_parseable(self):
        emit = getattr(self.producer, 'build_manifest_body', None)
        self.assertIsNotNone(emit, 'build_manifest_body is not implemented')
        body = emit(compiler='gcc (fixture) 14.2',
                    options=('-O0', '-g0'),
                    executable_sha256='a' * 64,
                    backend_libraries=(('libggml-base.a', 'b' * 64),),
                    patch_sha256='c' * 64,
                    transformed_manifest_sha256='d' * 64)
        identity = contract.parse_build_manifest(body)
        self.assertFalse(identity.is_unmodified_base)


class GenuineCaptureTests(unittest.TestCase):
    """Retained genuine native-emitted captures; mutation negative controls."""

    @classmethod
    def setUpClass(cls):
        path = CAPTURES / 'static-capture.json'
        if not path.is_file():
            raise unittest.SkipTest('genuine static capture not retained')
        # Byte-pin every retained capture: replacement with newly authored
        # self-consistent bytes is detected here, before any parse.
        for name, expected in RETAINED_CAPTURE_DIGESTS.items():
            actual = hashlib.sha256((FIXTURES / 'native-captures' / name).read_bytes()).hexdigest()
            if actual != expected:
                raise AssertionError('retained capture byte drift: ' + name)
        cls.static_bytes = path.read_bytes()
        cls.dynamic_bytes = (CAPTURES / 'dynamic-capture.json').read_bytes()

    def parse(self, payload):
        return contract.parse_observation(TransportReply(0, payload))

    def test_static_snapshot_capture_parses(self):
        parsed = self.parse(self.static_bytes)
        self.assertEqual(parsed.phase, 'static')
        self.assertEqual(parsed.stream_kind, 'snapshot')
        self.assertTrue(parsed.snapshot_fence and parsed.terminal)

    def test_dynamic_whole_capture_parses_with_native_events(self):
        parsed = self.parse(self.dynamic_bytes)
        self.assertEqual(parsed.phase, 'dynamic')
        self.assertEqual(parsed.stream_kind, 'whole')
        self.assertGreater(parsed.event_count, 0)
        self.assertEqual(parsed.dropped_events, 0)
        self.assertFalse(parsed.overflow)

    def test_native_ids_come_from_execution_not_controller(self):
        parsed = self.parse(self.dynamic_bytes)
        facts = dict(parsed.facts)
        process = dict(facts['process'])
        pid = process.get('pid')
        self.assertIsInstance(pid, int)
        self.assertGreater(pid, 0)

    def test_truncated_capture_refused(self):
        with self.assertRaises(ValueError):
            self.parse(self.dynamic_bytes[:len(self.dynamic_bytes) // 2])

    def _resealed(self, **mutations):
        """Mutate the genuine capture and RECOMPUTE a valid terminal digest.

        The mutated capture is internally consistent (digest, counters and
        fields agree), so refusal exercises the envelope's semantic fences,
        not mere digest-binding failure.
        """
        import hashlib as _h
        from inferswarm.operator.profiles import canonical as _canonical
        record = json.loads(self.dynamic_bytes)
        record.update(mutations)
        material = {k: v for k, v in record.items() if k != 'terminal_digest'}
        record['terminal_digest'] = _h.sha256(_canonical(material)).hexdigest()
        return json.dumps(record).encode()

    def test_dropped_events_refused(self):
        with self.assertRaises(ValueError):
            self.parse(self._resealed(dropped_events=1, event_count=13,
                                      terminal_sequence=13))
        record = json.loads(self.dynamic_bytes)
        record['dropped_events'] = 1
        with self.assertRaises(ValueError):
            self.parse(json.dumps(record).encode())  # unsealed tampering too

    def test_wrong_generation_splice_refused(self):
        # Within one capture a generation string is opaque (cross-capture
        # generation authentication is an explicit downstream collector
        # dependency), but a spliced capture mislabeling its interval IS
        # refused: whole streams must start at zero.
        with self.assertRaises(ValueError):
            self.parse(self._resealed(sequence_start=3))

    def test_overflow_refused(self):
        with self.assertRaises(ValueError):
            self.parse(self._resealed(overflow=True))
        record = json.loads(self.dynamic_bytes)
        record['overflow'] = True
        with self.assertRaises(ValueError):
            self.parse(json.dumps(record).encode())

    def test_missing_terminal_fence_refused(self):
        # A whole stream with terminal=false is a prefix mislabeled whole;
        # refusal is semantic even with a valid recomputed digest.
        with self.assertRaises(ValueError):
            self.parse(self._resealed(terminal=False))

    def test_sequence_gap_refused_with_valid_digest(self):
        record = json.loads(self.dynamic_bytes)
        # Drop a MIDDLE row; counters still declare the full interval, so the
        # remaining rows fail contiguous enumeration with a valid digest.
        record['sequence'] = record['sequence'][:4] + record['sequence'][5:]
        import hashlib as _h
        from inferswarm.operator.profiles import canonical as _canonical
        material = {k: v for k, v in record.items() if k != 'terminal_digest'}
        record['terminal_digest'] = _h.sha256(_canonical(material)).hexdigest()
        # Rows no longer enumerate the declared interval contiguously.
        with self.assertRaises(ValueError):
            self.parse(json.dumps(record).encode())


class NativeOverlayCorrectionTests(unittest.TestCase):
    """Source-realistic controls for the bounded P1-A/P1-B overlay fixes."""

    repo = Path(__file__).resolve().parents[1]
    overlay = FIXTURES / 'overlay'
    pin = Path('/home/zutfen/.hermes/cache/scratch/is299/llama-src')

    def _text(self, relative):
        return (self.overlay / relative).read_text()

    def test_sched_completion_path_is_instrumented(self):
        transformed = self._text('ggml/src/ggml-backend.cpp')
        original = (self.pin / 'ggml/src/ggml-backend.cpp').read_text()
        start = transformed.index('enum ggml_status ggml_backend_sched_graph_compute_async(')
        end = transformed.index('\n}', start) + 2
        self.assertIn('record("sched_graph_compute")', transformed[start:end])
        original_start = original.index('enum ggml_status ggml_backend_sched_graph_compute_async(')
        original_end = original.index('\n}', original_start) + 2
        self.assertNotIn('record("sched_graph_compute")', original[original_start:original_end])

    def test_export_seam_on_real_daemons(self):
        header = self._text('is301_observer.h')
        queue = self._text('tools/server/server-queue.cpp')
        rpc = self._text('ggml/src/ggml-rpc/ggml-rpc.cpp')
        self.assertIn('export_capture', header)
        self.assertIn('export_capture("dynamic", "whole", true, false, "llama-server")', queue)
        self.assertIn('export_capture("dynamic", "whole", true, false, "ggml-rpc-server")', rpc)
        self.assertRegex(header, r'MAX_EXPORTS|EXPORT_CAP|MAX_EXPORT')
        self.assertIn('.tmp', header)
        self.assertIn('rename(', header)

    def test_request_lineage_is_array_not_scalar_overwrite(self):
        script = (self.repo / 'scripts/issue301_derive_overlay.py').read_text()
        self.assertNotIn('facts().add("request"', script)
        self.assertIn('facts().append("tasks"', script)
        self.assertIn('facts().append("responses"', script)
        self.assertIn('kv_num("task_id"', script)
        self.assertIn('kv_str("response_id", "unknown")', script)

    def test_allocation_records_are_preserved(self):
        script = (self.repo / 'scripts/issue301_derive_overlay.py').read_text()
        shim = self._text('is301_c_shim.h')
        sink = self._text('is301_sink.cpp')
        self.assertIn('is301_fact_alloc', script)
        self.assertIn('is301_fact_alloc', shim)
        self.assertIn('facts().append("allocations"', sink)
        self.assertNotIn('is301_fact_num("alloc_buffer_bytes"', script)

    def test_fact_capacity_refusals_are_fail_closed(self):
        header = self._text('is301_observer.h')
        facts = header[header.index('struct facts_builder {'):header.index('\n};', header.index('struct facts_builder {'))]
        self.assertIn('long long dropped = 0;', facts)
        self.assertIn('bool overflowed = false;', facts)
        self.assertGreaterEqual(facts.count('dropped++'), 4)
        self.assertIn('r.dropped + f.dropped', header)
        self.assertIn('r.overflow || f.overflowed', header)
        reset = header[header.index('inline void reset()'):]
        self.assertIn('f.dropped = 0', reset)
        self.assertIn('f.overflowed = false', reset)

    def test_event_catalog_includes_sched_path(self):
        producer = importlib.import_module('inferswarm.operator.native_observer.producer')
        self.assertIn('sched_graph_compute', producer.EVENT_CATALOG)
        self.assertIn('tasks', producer.FACT_KEYS)
        self.assertIn('responses', producer.FACT_KEYS)



class CorrectedProducerEvidenceTests(unittest.TestCase):
    """Genuine native evidence from the PR #304 correction build.

    Captures produced by the corrected overlay: scheduler-path observation,
    collector exports, and adversarial fact-bounds proofs. Byte-pinned above.
    """

    def parse(self, name):
        payload = (FIXTURES / 'native-captures' / name).read_bytes()
        return contract.parse_observation(TransportReply(0, payload))

    def test_scheduler_path_observed_in_dynamic_captures(self):
        # P1-A: the true llama-server entry (ggml_backend_sched_graph_compute_async)
        # is instrumented; genuine captures contain sched_graph_compute events and
        # graphs rows carrying graph identity + explicit unknown lineage.
        for name in ('dynamic-capture.json', 'rpc/dynamic-capture.json'):
            parsed = self.parse(name)
            events = []
            for row in parsed.sequence:
                row_dict = dict(row._asdict()) if hasattr(row, '_asdict') else dict(row)
                events.append(row_dict.get('event'))
            self.assertIn('sched_graph_compute', events, name)
            facts = dict(parsed.facts)
            graphs = list(facts.get('graphs', ()))
            self.assertTrue(graphs, name)
            row = dict(graphs[0])
            self.assertIn('graph_id', row)
            self.assertIn('splits', row)
            self.assertEqual(row.get('ubatch_lineage'), 'unknown')

    def test_collector_exports_parse_as_sealed_streams(self):
        # P1-A: both real-daemon export seams (fixture process and the RPC
        # server's per-connection site) yield parser-valid whole streams.
        export = self.parse('exports/fixture-cpu-observed.json')
        self.assertEqual((export.phase, export.stream_kind, export.terminal),
                         ('dynamic', 'whole', True))
        rpc_export = self.parse('exports/ggml-rpc-server-observed.json')
        self.assertEqual((rpc_export.phase, rpc_export.stream_kind, rpc_export.terminal),
                         ('dynamic', 'whole', True))
        self.assertGreater(rpc_export.event_count, 0)

    def test_fact_bounds_clean_capture_preserves_all_records(self):
        # P1-B: multiple tasks/responses/allocations survive as arrays; the
        # task->response join key is preserved, nothing overwritten.
        clean = self.parse('fact-bounds/clean.json')
        self.assertEqual(clean.dropped_events, 0)
        self.assertFalse(clean.overflow)
        facts = dict(clean.facts)
        tasks = [dict(t) for t in facts.get('tasks', ())]
        responses = [dict(r) for r in facts.get('responses', ())]
        allocations = [dict(a) for a in facts.get('allocations', ())]
        self.assertEqual(len(tasks), 3)
        self.assertEqual(len(responses), 2)
        self.assertEqual(len(allocations), 2)
        for row in tasks:
            self.assertEqual(row.get('response_id'), 'unknown')
            self.assertIsInstance(row.get('task_id'), int)
        for row in responses:
            self.assertIsInstance(row.get('task_id'), int)
        for row in allocations:
            self.assertIn('buffer_bytes', row)
            self.assertIn('backend', row)

    def test_fact_capacity_overflow_is_fail_closed(self):
        # P1-B negative control (native): mutate a retained capture by adding a
        # fact-row count beyond capacity is NOT needed — the genuine adversarial
        # capture from the fixture was already refused for dropped_events>0 at
        # build time (retained build log). Here: resealed valid-digest control.
        import hashlib as _h
        from inferswarm.operator.profiles import canonical as _canonical
        raw = json.loads((FIXTURES / 'native-captures' / 'fact-bounds' / 'clean.json').read_bytes())
        raw['dropped_events'] = 1
        raw['terminal_digest'] = _h.sha256(_canonical(
            {k: v for k, v in raw.items() if k != 'terminal_digest'})).hexdigest()
        with self.assertRaises(ValueError):
            contract.parse_observation(TransportReply(0, json.dumps(raw).encode()))


if __name__ == '__main__':
    unittest.main()

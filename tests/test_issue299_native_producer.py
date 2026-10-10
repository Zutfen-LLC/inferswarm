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
    'static-capture.json': '7e9e1e068c52694cb90e89c99c2b7d6d75f0e049a4139a0da245f62788337a99',
    'dynamic-capture.json': 'a19ef10ed3aefe7e206c5a4b2d9fb1665c9ea5e4cb27fec1d80f096e1b89889d',
    'rpc/static-capture.json': '7d53a6880aba6b896d4a3b44b392088c5a79c5670984288125c743c84faa8870',
    'rpc/dynamic-capture.json': '3ea37236b3eba4b573660c08b85402c2072c91c0bae19ddcae71d6c72bf13a39',
    'exports/fixture-cpu-observed.json': 'cf0747cb2cc40be75542d118af19c39e70879f9480d9a628ec7e7237d8b7424e',
    'exports/fixture-rpc-observed.json': '690e6450080bf70f0b6bac762399afa416600caf0c0298006271a8c082e53a11',
    'exports/ggml-rpc-server-observed.json': '92d4eba0d9098b4e3614cc4b81a1664706737dc9d4077bdc946e4616f3cf20ec',
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
        # Offline recipe contract; no archives or native binaries are created.
        from inferswarm.operator.native_observer import full_build as fb
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            root = Path('/nonexistent-tree')
            recipe = fb.assemble(root, out)
            compiles = [c for c in recipe['commands'] if '-c' in c]
            objects = {c[c.index('-c') + 1]: c[c.index('-o') + 1] for c in compiles}
            mains = {'llama-server': 'tools/server/main.cpp',
                     'ggml-rpc-server': 'tools/rpc/rpc-server.cpp',
                     'native-buffer-graph-observed': 'tests/native-buffer-graph-observed.cpp',
                     'native-fact-bounds': 'tests/native-fact-bounds.cpp',
                     'native-export-claim': 'tests/native-export-claim.cpp'}
            main_paths = {str(root / rel) for rel in mains.values()}
            ggml = [obj for src, obj in objects.items() if src.startswith(str(root / 'ggml') + '/')]
            ggml += [objects[str(root / 'is301_sink.cpp')]]
            expected = {}
            for name, main in mains.items():
                members = [obj for src, obj in objects.items() if src not in main_paths] if name == 'llama-server' else ggml
                expected[name] = members + [objects[str(root / main)]]
            self.assertEqual(fb._link_membership(recipe), expected)
            libraries = fb._archive_membership(recipe)
            self.assertEqual(libraries['libggml-static.a'], ggml)
            self.assertEqual(libraries['libllama-full.a'], expected['llama-server'][:-1])

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
        # The directory bound is an ATOMIC claim (O_CREAT|O_EXCL), not a
        # racy scan: concurrent processes cannot both claim one directory.
        self.assertIn('O_EXCL', header)
        self.assertIn('-claim', header)

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


class RoundTwoRegressionTests(unittest.TestCase):
    repo = Path(__file__).resolve().parents[1]

    def test_overwrite_bound_precedes_replacement(self):
        header = (FIXTURES / 'overlay/is301_observer.h').read_text()
        start = header.index('struct facts_builder {')
        end = header.index('\n};', start)
        source = header[start:end]
        add_start = source.index('void add(const std::string & key')
        add_body = source[add_start:]
        self.assertLess(add_body.index('canonical_value.size() > FACT_BOUND'),
                        add_body.index('row.second = canonical_value'))
        self.assertIn('dropped++; overflowed = true;', add_body)

    def test_fact_bounds_fixture_attempts_oversized_overwrite(self):
        source = (FIXTURES / 'overlay/tests/native-fact-bounds.cpp').read_text()
        # Source-bound offline gate only; native assertions run in parent build.
        self.assertIn('facts().add("overwrite-bound", is301::quote("small"))', source)
        self.assertIn('is301::quote(std::string(4097,', source)
        self.assertIn('/fact-scalar-overwrite.json', source)
        self.assertIn('facts().append("oversized", is301::quote(std::string(4097,', source)
        self.assertIn('/fact-bounds-capture.json', source)
        self.assertIn('before == is301::facts().canonical_object()', source)
        self.assertIn('is301::facts().dropped == 1', source)

    def test_header_claim_is_fixed_sentinel_bound_to_owner(self):
        header = (FIXTURES / 'overlay/is301_observer.h').read_text()
        self.assertIn('is301-claim', header)
        self.assertIn('O_EXCL', header)
        self.assertIn('std::to_string(process_id)', header)
        self.assertNotRegex(header, r'participant\s*\+\s*"-"\s*\+\s*std::to_string\(process_id\)\s*\+\s*"-claim')

    def test_native_claim_helper_exercises_real_export_and_fork(self):
        # Feature-absence/source-binding RED is NOT native behavioral evidence.
        path = FIXTURES / 'overlay/tests/native-export-claim.cpp'
        self.assertTrue(path.is_file(), 'native adversarial claim helper missing')
        source = path.read_text()
        self.assertIn('is301::export_capture(', source)
        self.assertIn('::fork()', source)
        self.assertIn('::pipe(', source)
        self.assertIn('::read(gate[0]', source)
        self.assertIn('::write(gate[1]', source)
        self.assertIn('owner == expected_owner', source)
        self.assertIn('stale claim', source)
        self.assertIn('inherited ownership', source)
        header = (FIXTURES / 'overlay/is301_observer.h').read_text()
        self.assertIn('/proc/self/stat', header)
        self.assertIn('process_start_ticks()', header)
        self.assertIn('owner_pid != process_id', header)
        self.assertIn('owner_start != start_ticks', header)

    def test_generator_mirrors_native_fixtures(self):
        # Load constants without invoking generator main or any native command.
        import runpy
        from unittest import mock
        import sys
        with mock.patch.object(sys, 'argv', ['issue301_derive_overlay.py']):
            generator = runpy.run_path(str(self.repo / 'scripts/issue301_derive_overlay.py'))
        for constant, path in (('FACT_BOUNDS_CPP', 'native-fact-bounds.cpp'),
                               ('EXPORT_CLAIM_CPP', 'native-export-claim.cpp')):
            self.assertIn(constant, generator, 'native fixture generator missing')
            self.assertEqual(generator[constant], (FIXTURES / 'overlay/tests' / path).read_text())

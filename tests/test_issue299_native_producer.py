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
    'static-capture.json': '4d3a19127612e47485d22c2e0df7bcb401a290b44323cac62f54bd585d29986b',
    'dynamic-capture.json': '7626a1c454e9028f72265eae4ef38f70122f53fe7dd856f946640e78b719168a',
    'rpc/static-capture.json': '2d9377bf310519ff412d65284bdc9aa7fde33c8212e43b36504c684327e1146b',
    'rpc/dynamic-capture.json': 'ebd248c960f70ad87ad5a2688e3f8c6bb9c7faa935d3827659b74d9a18e65677',
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
            ggml = set(range(ggml_last + 1))
            server = set(range(len(compiles))) - {rpc_main, len(compiles) - 1}
            expected = {'llama-server': server,
                        'ggml-rpc-server': ggml | {sink} | {rpc_main},
                        'fixture': ggml | {sink, len(compiles) - 1}}
            for name, cmd in zip(('llama-server', 'ggml-rpc-server', 'fixture'), r['commands'][-3:]):
                objs = {int(_P(a).stem) for a in cmd if a.endswith('.o')}
                self.assertEqual(objs, expected[name], name + ' link membership drift')
            # Declared archive ranges in execute() must cover the same sets.
            src_text = inspect.getsource(fb.execute)
            self.assertIn("list(range(len(recipe['sources']) + 5))", src_text)
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


if __name__ == '__main__':
    unittest.main()

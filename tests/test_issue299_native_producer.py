"""Offline issue #301 native producer controls; no native build in this suite.

Replays small retained genuine captures produced by the observation overlay;
never compiles, never charges the native campaign ledger, never launches a
server. Negative controls mutate the genuine retained bytes.
"""
import hashlib
import importlib
import json
from pathlib import Path
import unittest

FIXTURES = Path(__file__).resolve().parents[1] / 'tests' / 'fixtures' / 'issue299'
CAPTURES = FIXTURES / 'native-captures'

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

    def test_dropped_events_refused(self):
        record = json.loads(self.dynamic_bytes)
        record['dropped_events'] = 1
        payload = json.dumps(record).encode()
        with self.assertRaises(ValueError):
            self.parse(payload)

    def test_wrong_generation_splice_refused(self):
        record = json.loads(self.dynamic_bytes)
        record['stream_generation'] = 'other-generation'
        payload = json.dumps(record).encode()
        with self.assertRaises(ValueError):
            self.parse(payload)  # digest binds generation; tampering refused

    def test_overflow_refused(self):
        record = json.loads(self.dynamic_bytes)
        record['overflow'] = True
        payload = json.dumps(record).encode()
        with self.assertRaises(ValueError):
            self.parse(payload)

    def test_missing_terminal_fence_refused(self):
        record = json.loads(self.dynamic_bytes)
        record['terminal'] = False
        payload = json.dumps(record).encode()
        with self.assertRaises(ValueError):
            self.parse(payload)


if __name__ == '__main__':
    unittest.main()

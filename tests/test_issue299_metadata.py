"""Offline metadata-only regression controls; synthetic headers are not evidence."""
import copy
import hashlib
import io
import json
from pathlib import Path
import struct
import tempfile
import tracemalloc
import unittest
from unittest.mock import patch

from inferswarm.operator import source

FIXTURES = Path(__file__).parent / 'fixtures' / 'issue299'
# Frozen from the successful six-range reproduction, not synthetic rows.
FIXTURE_SHA256 = 'd4ff414c3d796abd6afb94329de633c39ad5ba4723fc17baa41bdc4c72dce485'
METADATA_DIGEST = '194c818cb0bbb6016f0a282596131040c7afbdb294f9962e7f9e262d7128239e'
MANIFEST_SHA256 = '50a58f6e8e5a0b3b1d1dd1aec9bd454671760dd44580f6979a26db91f75ee564'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def string(value):
    data = value.encode('utf-8')
    return struct.pack('<Q', len(data)) + data


def header(tensors=(), metadata=()):
    """Synthetic GGUF v3, no alignment padding or tensor body."""
    result = b'GGUF' + struct.pack('<IQQ', 3, len(tensors), len(metadata))
    for key, typ, value in metadata:
        result += string(key) + struct.pack('<I', typ)
        if typ == 8:
            result += string(value)
        elif typ == 9:
            subtype, values = value
            result += struct.pack('<IQ', subtype, len(values))
            for item in values:
                result += string(item) if subtype == 8 else struct.pack('<' + source.SCALAR[subtype], item)
        else:
            result += struct.pack('<' + source.SCALAR[typ], value)
    for name, shape, typ, offset in tensors:
        result += string(name) + struct.pack('<I', len(shape))
        result += struct.pack('<' + 'Q' * len(shape), *shape) + struct.pack('<IQ', typ, offset)
    return result


def decode(data, size):
    if not hasattr(source, 'parse_gguf_header'):
        raise AssertionError('rich parse_gguf_header is not implemented')
    return source.parse_gguf_header(data, object_bytes=size, expected_header_sha256=sha(data))


class ParserTests(unittest.TestCase):
    def test_rich_q8_f32_bf16_and_legacy_wrapper(self):
        data = header([('q8', (32, 2), 8, 0), ('f32', (7,), 0, 96), ('bf16', (16,), 30, 128)])
        start = (len(data) + 31) // 32 * 32
        meta, rows = decode(data, start + 160)
        self.assertIsInstance(rows, tuple)
        self.assertEqual([(r.state_id, r.ggml_type, r.shape, r.relative_offset, r.absolute_offset, r.encoded_bytes) for r in rows],
                         [('q8', 8, (32, 2), 0, start, 68), ('f32', 0, (7,), 96, start + 96, 28), ('bf16', 30, (16,), 128, start + 128, 32)])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'test.gguf'
            path.write_bytes(data + b'\0' * (start + 160 - len(data)))
            self.assertEqual(source.gguf_tensors(path), {r.state_id: (r.absolute_offset, r.encoded_bytes) for r in rows})
        with self.assertRaises((AttributeError, TypeError)):
            rows[0].shape = (1,)

    def test_huge_extent_never_allocates_tensor_body(self):
        data = header([('per_layer_token_embd.weight', (32, 1600000000), 8, 0)])
        size = (len(data) + 31) // 32 * 32 + 54400000000
        tracemalloc.start()
        try:
            with patch('socket.socket', side_effect=AssertionError('network')), patch('subprocess.run', side_effect=AssertionError('subprocess')):
                _, rows = decode(data, size)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertEqual(rows[0].encoded_bytes, 54400000000)
        self.assertLess(peak, 1 << 20)

    def test_required_metadata_arrays_retained_tokenizer_discarded(self):
        data = header(metadata=[('general.architecture', 8, 'qwen4exp'), ('qwen4exp.attention.sliding_window', 9, (4, [0, 512, 0])), ('tokenizer.ggml.tokens', 9, (8, ['private tokenizer text']))])
        meta, rows = decode(data, (len(data) + 31) // 32 * 32)
        self.assertEqual(dict(meta)['qwen4exp.attention.sliding_window'], (0, 512, 0))
        self.assertNotIn('tokenizer.ggml.tokens', dict(meta))
        self.assertEqual(rows, ())

    def test_bad_header_hash_rejected(self):
        self.assertTrue(hasattr(source, 'parse_gguf_header'), 'rich parser missing')
        with self.assertRaisesRegex(ValueError, '^header SHA-256 mismatch$'):
            source.parse_gguf_header(header(), object_bytes=32, expected_header_sha256='0' * 64)

    def test_malformed_hash_object_size_rejected(self):
        self.assertTrue(hasattr(source, 'parse_gguf_header'), 'rich parser missing')
        for size, digest, reason in [(True, sha(header()), 'invalid object_bytes'), (-1, sha(header()), 'invalid object_bytes'), (32, 'abc', 'invalid header SHA-256')]:
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                source.parse_gguf_header(header(), object_bytes=size, expected_header_sha256=digest)

    def test_duplicate_names_metadata_and_extent_rejections(self):
        cases = [
            (header([('x', (8,), 0, 0), ('x', (8,), 0, 32)]), 64, 'duplicate GGUF tensor'),
            (header(metadata=[('general.alignment', 4, 32)] * 2), 0, 'duplicate GGUF metadata'),
            (header([('x', (16,), 0, 0), ('y', (8,), 0, 32)]), 64, 'overlapping GGUF tensor'),
            (header([('x', (8,), 0, 1)]), 64, 'unaligned GGUF offset'),
            (header([('x', (8,), 0, 0)]), 64, 'GGUF extent mismatch'),
            (header([('x', (8,), 0, 0)]), 16, 'out-of-bounds GGUF tensor'),
            (header([('x', (16, 2), 8, 0)]), 34, 'block-incompatible GGUF shape'),
            (header([('x', (0,), 0, 0)]), 0, 'invalid GGUF shape'),
            (header([('x', (2**63, 2**63), 0, 0)]), 0, 'invalid GGUF shape'),
            (header(metadata=[('general.alignment', 4, 3)]), 0, 'invalid GGUF alignment'),
            (header(metadata=[('value', 6, float('inf'))]), 0, 'nonfinite GGUF metadata'),
        ]
        for data, payload, reason in cases:
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                decode(data, (len(data) + 31) // 32 * 32 + payload)

    def test_invalid_split_fields(self):
        for number, count, total in [(6, 6, 1), (0, 0, 1), (0, 6, -1), (True, 6, 1)]:
            meta = [('split.no', 7 if type(number) is bool else 4, number), ('split.count', 4, count), ('split.tensors.count', 11, total)]
            data = header(metadata=meta)
            with self.subTest(values=(number, count, total)), self.assertRaisesRegex(ValueError, 'invalid GGUF split'):
                decode(data, (len(data) + 31) // 32 * 32)

    def test_bounded_counts_strings_arrays_and_truncation(self):
        cases = [(b'GGUF' + struct.pack('<IQQ', 3, 1000001, 0), 'oversized GGUF index'),
                 (b'GGUF' + struct.pack('<IQQQ', 3, 0, 1, 2**63), 'oversized GGUF string'),
                 (b'GGUF' + struct.pack('<IQQ', 3, 0, 1) + string('x') + struct.pack('<IIQ', 9, 4, 2**63), 'oversized GGUF array'),
                 (header([('x', (8,), 0, 0)])[:-1], 'truncated GGUF metadata')]
        for data, reason in cases:
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                decode(data, 4096)

    def test_extra_header_bytes_are_not_tensor_prefix_metadata(self):
        data = header([('x', (8,), 0, 0)])
        with self.assertRaisesRegex(ValueError, 'unexpected bytes after GGUF header'):
            decode(data + b'x', (len(data) + 31) // 32 * 32 + 32)


class Response(io.BytesIO):
    def __init__(self, body, row, *, status=206, headers=None, url=None):
        super().__init__(body)
        self.status = status
        self.headers = {'Content-Range': f"bytes 0-{row['range_end']}/{row['object_bytes']}", 'Content-Encoding': 'identity'}
        self.headers.update(headers or {})
        self.url = url or row['url']
        self.read_sizes = []

    def read(self, size=-1):
        self.read_sizes.append(size)
        if size < 0:
            raise AssertionError('unbounded response read')
        return super().read(size)

    def geturl(self):
        return self.url


class ReproductionTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((FIXTURES / 'public-header-manifest.json').read_text())
        self.row = self.manifest['members'][0]

    def reproduce(self, response, *, allow=True, manifest=None):
        self.calls = []
        from inferswarm.operator.metadata import reproduce_metadata
        def opener(request, **kwargs):
            self.calls.append(request)
            return response
        return reproduce_metadata(manifest or self.manifest, opener=opener, allow_network=allow)

    def test_offline_default_never_opens(self):
        response = Response(b'', self.row)
        with self.assertRaisesRegex(ValueError, '^network reproduction requires explicit opt-in$'):
            self.reproduce(response, allow=False)
        self.assertEqual(self.calls, [])
        self.assertEqual(response.read_sizes, [])

    def test_http200_rejected_before_body_read(self):
        response = Response(b'weights must not be read', self.row, status=200)
        with self.assertRaisesRegex(ValueError, '^expected HTTP 206$'):
            self.reproduce(response)
        self.assertEqual(response.read_sizes, [])
        self.assertEqual(len(self.calls), 1)
        request = self.calls[0]
        self.assertEqual(request.get_header('Range'), f"bytes=0-{self.row['range_end']}")
        self.assertEqual(request.get_header('Accept-encoding'), 'identity')

    def test_wrong_range_total_start_end_encoding_length_rejected_unread(self):
        expected = self.row
        variants = [({'Content-Range': f"bytes 1-{expected['range_end']}/{expected['object_bytes']}"}, 'Content-Range mismatch'),
                    ({'Content-Range': f"bytes 0-{expected['range_end'] - 1}/{expected['object_bytes']}"}, 'Content-Range mismatch'),
                    ({'Content-Range': f"bytes 0-{expected['range_end']}/{expected['object_bytes'] + 1}"}, 'Content-Range mismatch'),
                    ({'Content-Encoding': 'gzip'}, 'nonidentity Content-Encoding'),
                    ({'Content-Length': str(expected['range_end'] + 2)}, 'Content-Length mismatch')]
        for headers, reason in variants:
            response = Response(b'not read', expected, headers=headers)
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                self.reproduce(response)
            self.assertEqual(response.read_sizes, [])

    def test_unapproved_redirect_rejected_before_body_read(self):
        response = Response(b'not read', self.row, url='https://other.invalid/weights')
        with self.assertRaisesRegex(ValueError, 'unapproved response resource'):
            self.reproduce(response)
        self.assertEqual(response.read_sizes, [])

    def test_read_budget_truncation_oversize_hash(self):
        n = self.row['range_end'] + 1
        for body, reason in [(b'x', 'truncated header response'), (b'x' * (n + 1), 'oversized header response'), (b'x' * n, 'header SHA-256 mismatch')]:
            response = Response(body, self.row)
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                self.reproduce(response)
            self.assertLessEqual(sum(response.read_sizes), n + 1)
            self.assertEqual(len(self.calls), 1)

    def test_changed_manifest_rejected_without_network(self):
        variants = []
        for field, value in [('revision', '0' * 40), ('representation', 'IQ1_S'), ('source_id', 'other/model')]:
            data = copy.deepcopy(self.manifest)
            data['source'][field] = value
            variants.append((data, 'source identity mismatch'))
        data = copy.deepcopy(self.manifest)
        data['members'].pop()
        variants.append((data, 'missing or changed public members'))
        for field, value in [('url', 'https://other.invalid/model'), ('range_end', True), ('object_sha256', 'bad')]:
            data = copy.deepcopy(self.manifest)
            data['members'][0][field] = value
            variants.append((data, 'missing or changed public members|invalid'))
        for data, reason in variants:
            response = Response(b'not read', self.row)
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                self.reproduce(response, manifest=data)
            self.assertEqual(self.calls, [])

    def test_identity_bound_hf_cdn_redirect_preserves_exact_range(self):
        from inferswarm.operator.metadata import _PinnedRedirectHandler
        from urllib.request import Request
        row = self.row
        target = 'https://us.aws.cdn.hf.co/xet-bridge-us/object?response-content-disposition=inline%3B%20filename%3D%22' + row['member'] + '%22'
        headers = {'X-Linked-Etag': '"' + row['object_sha256'] + '"', 'X-Linked-Size': str(row['object_bytes'])}
        handler = _PinnedRedirectHandler(row)
        req = handler.redirect_request(Request(row['url']), None, 302, 'Found', headers, target)
        self.assertEqual(req.get_header('Range'), f"bytes=0-{row['range_end']}")
        self.assertEqual(req.get_header('Accept-encoding'), 'identity')
        self.assertIn(target, handler.approved)
        for field, bad in [('X-Linked-Etag', '0' * 64), ('X-Linked-Size', '1')]:
            altered = dict(headers); altered[field] = bad
            handler = _PinnedRedirectHandler(row)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'unapproved redirect resource'):
                handler.redirect_request(Request(row['url']), None, 302, 'Found', altered, target)
            self.assertEqual(handler.approved, {row['url']})

    def test_redirect_response_body_is_never_drained(self):
        from email.message import Message
        from types import SimpleNamespace
        from inferswarm.operator.metadata import _PinnedRedirectHandler
        from urllib.request import Request
        row = self.row
        target = 'https://us.aws.cdn.hf.co/xet-bridge-us/object?response-content-disposition=inline%3B%20filename%3D%22' + row['member'] + '%22'
        headers = Message()
        headers['Location'] = target
        headers['X-Linked-Etag'] = '"' + row['object_sha256'] + '"'
        headers['X-Linked-Size'] = str(row['object_bytes'])
        for status in (301, 302, 303, 307, 308):
            handler = _PinnedRedirectHandler(row)
            calls = []
            def follow(req, **kwargs):
                calls.append(req)
                return 'accepted bounded target'
            handler.parent = SimpleNamespace(open=follow)
            response = Response(b'must not drain redirect body', row, status=status)
            request = Request(row['url']); request.timeout = 60
            with self.subTest(status=status):
                result = getattr(handler, f'http_error_{status}')(request, response, status, 'Found', headers)
                self.assertEqual(result, 'accepted bounded target')
                self.assertEqual(response.read_sizes, [])
                self.assertTrue(response.closed)
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0].get_header('Range'), f"bytes=0-{row['range_end']}")

    def test_default_redirect_policy_blocks_foreign_resource_before_request(self):
        from inferswarm.operator.metadata import _PinnedRedirectHandler
        from urllib.request import Request
        handler = _PinnedRedirectHandler(self.row)
        with self.assertRaisesRegex(ValueError, 'unapproved redirect resource'):
            handler.redirect_request(Request(self.row['url']), None, 302, 'Found', {}, 'https://other.invalid/x')


class AuthenticFixtureTests(unittest.TestCase):
    def load(self):
        from inferswarm.operator.metadata import load_metadata_index
        path = FIXTURES / 'q8-metadata.json'
        with patch('socket.socket', side_effect=AssertionError('normal tests must be offline')), patch('urllib.request.urlopen', side_effect=AssertionError('network')), patch('subprocess.run', side_effect=AssertionError('subprocess')):
            index = load_metadata_index(path, expected_sha256=FIXTURE_SHA256)
            self.assertEqual(index.metadata_digest, METADATA_DIGEST)
            self.assertEqual(sha((FIXTURES / 'public-header-manifest.json').read_bytes()), MANIFEST_SHA256)
            return index

    def test_authentic_census_sets_bytes_shapes_shard_crossings(self):
        index = self.load()
        rows = index.tensors
        self.assertEqual(len(rows), 1224)
        self.assertEqual(len({r.state_id for r in rows}), 1224)
        self.assertEqual(sum(r.encoded_bytes for r in rows), 188214008320)
        banks = [r for r in rows if '_exps.' in r.state_id]
        self.assertEqual(len(banks), 144)
        for layer in range(48):
            actual = {r.state_id for r in banks if r.state_id.startswith(f'blk.{layer}.')}
            self.assertEqual(actual, {f'blk.{layer}.ffn_{name}_exps.weight' for name in ('gate', 'up', 'down')})
        for r in banks:
            self.assertEqual(r.encoded_bytes, 891289600)
            self.assertEqual(r.ggml_type, 8)
            self.assertEqual(r.shape, (640, 2560, 512) if '.ffn_down_' in r.state_id else (2560, 640, 512))
        by_name = {r.state_id: r for r in rows}
        self.assertEqual(by_name['per_layer_token_embd.weight'].encoded_bytes, 54400261120)
        self.assertEqual(by_name['token_embd.weight'].encoded_bytes, 675430400)
        self.assertEqual({r.state_id for r in rows if '.ple_' in r.state_id},
                         {f'blk.1.{name}.weight' for name in ('ple_conv1d', 'ple_key', 'ple_norm_conv', 'ple_norm_key', 'ple_norm_query', 'ple_value')})
        outputs = [r for r in rows if r.state_id.startswith('output')]
        self.assertEqual({r.state_id for r in outputs}, {'output.weight', 'output_hc_down.weight', 'output_hc_norm.weight', 'output_hc_up.weight'})
        self.assertEqual(sum(r.encoded_bytes for r in outputs), 682434560)
        for layer in range(48):
            block = [r for r in rows if r.state_id.startswith(f'blk.{layer}.')]
            expected = (31, 2795244416) if layer == 1 else (26, 2754639872) if layer % 4 == 3 else (25, 2760141696)
            self.assertEqual((len(block), sum(r.encoded_bytes for r in block)), expected)
            self.assertEqual(len({r.member for r in block}), 2 if layer in (17, 35) else 1)
        groups = [[], [], []]
        for row in rows:
            if row.state_id.startswith('blk.'):
                layer = int(row.state_id.split('.')[1])
                owner = 0 if layer < 14 else 1 if layer < 45 else 2
            else:
                owner = 2 if row.state_id.startswith('output') else 0
            groups[owner].append(row)
        self.assertEqual([(len(g), sum(r.encoded_bytes for r in g)) for g in groups], [(361, 93736272512), (783, 85520377984), (80, 8957357824)])
        self.assertEqual(dict(index.model_metadata)['general.architecture'], 'qwen4exp')
        self.assertEqual(index.source.revision, '38bb39ee97821de2c9009abb7e93950eec396e66')
        self.assertEqual(sum(r[4] for r in index.header_identities), 188225033248)
        self.assertEqual(sum(r[2] - r[1] + 1 for r in index.header_identities), 11024837)

    def test_split_duplicate_and_changed_model_metadata_after_valid_parse(self):
        from dataclasses import replace
        from inferswarm.operator.metadata import _assemble_index, _public_members
        index = self.load()
        members = _public_members()
        parsed = []
        for number, member in enumerate(members):
            pairs = index.model_metadata if number == 0 else ()
            pairs = pairs + (('split.no', number), ('split.count', 6), ('split.tensors.count', 1224))
            rows = tuple(replace(r, member='') for r in index.tensors if r.member == member['member'])
            parsed.append((pairs, rows))
        self.assertEqual(_assemble_index(parsed), index)
        bad_split = copy.deepcopy(parsed)
        bad_split[1] = (tuple((k, 2 if k == 'split.no' else v) for k, v in bad_split[1][0]), bad_split[1][1])
        bool_split = copy.deepcopy(parsed)
        bool_split[0] = (tuple((k, False if k == 'split.no' else v) for k, v in bool_split[0][0]), ())
        changed = copy.deepcopy(parsed)
        changed[0] = (tuple((k, 49 if k == 'qwen4exp.block_count' else v) for k, v in changed[0][0]), ())
        duplicate = copy.deepcopy(parsed)
        replacement = replace(duplicate[3][1][0], state_id=duplicate[1][1][0].state_id)
        duplicate[3] = (duplicate[3][0], (replacement,) + duplicate[3][1][1:])
        cases = [(parsed[:-1], 'missing GGUF members'), (bad_split, 'GGUF split identity mismatch'),
                 (bool_split, 'GGUF split identity mismatch'), (changed, 'changed model metadata'),
                 (duplicate, 'duplicate GGUF tensor across members')]
        with patch('socket.socket', side_effect=AssertionError('network')), patch('subprocess.run', side_effect=AssertionError('subprocess')):
            for mutated, reason in cases:
                with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                    _assemble_index(mutated)
        self.assertEqual(sha((FIXTURES / 'q8-metadata.json').read_bytes()), FIXTURE_SHA256)

    def test_coherently_rehashed_fixture_still_rejects_invalid_descriptors(self):
        from inferswarm.operator.metadata import load_metadata_index, _canonical
        original = json.loads((FIXTURES / 'q8-metadata.json').read_bytes())
        variants = []
        for field, bad, reason in [('ggml_type', True, 'invalid ggml_type'),
                                   ('shape', [0], 'invalid GGUF shape'),
                                   ('encoded_bytes', 1, 'GGUF encoded extent mismatch'),
                                   ('absolute_offset', original['tensors'][0]['absolute_offset'] + 1, 'GGUF absolute offset mismatch'),
                                   ('relative_offset', original['tensors'][0]['relative_offset'] + 1, 'unaligned GGUF offset'),
                                   ('member', '../bad.gguf', 'unknown GGUF member'),
                                   ('state_id', original['tensors'][1]['state_id'], 'duplicate GGUF tensor')]:
            changed = copy.deepcopy(original); changed['tensors'][0][field] = bad
            variants.append((changed, reason))
        changed = copy.deepcopy(original); changed['header_identities'][0][1] = False
        variants.append((changed, 'invalid header identity integer'))
        changed = copy.deepcopy(original); changed['source']['revision'] = '0' * 40
        variants.append((changed, 'source identity mismatch'))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'index.json'
            for changed, reason in variants:
                changed['metadata_digest'] = sha(_canonical({k: v for k, v in changed.items() if k != 'metadata_digest'}))
                path.write_bytes(_canonical(changed))
                with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                    load_metadata_index(path, expected_sha256=sha(path.read_bytes()))

    def test_json_overflow_float_rejected_as_nonfinite(self):
        from inferswarm.operator.metadata import load_metadata_index
        text = (FIXTURES / 'q8-metadata.json').read_text().replace('"general.sampling.temp",1.0', '"general.sampling.temp",1e999')
        self.assertIn('1e999', text)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'index.json'; path.write_text(text)
            with self.assertRaisesRegex(ValueError, 'nonfinite JSON'):
                load_metadata_index(path, expected_sha256=sha(path.read_bytes()))

    def test_cli_no_opt_in_preserves_output_and_raw_directory(self):
        from inferswarm.operator.metadata import main
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'out.json'; raw = Path(tmp) / 'raw'
            with patch('socket.socket', side_effect=AssertionError('network')), patch('sys.stderr', new=io.StringIO()):
                with self.assertRaises(SystemExit) as stopped:
                    main(['reproduce', '--manifest', str(FIXTURES / 'public-header-manifest.json'), '--output', str(output), '--raw-header-dir', str(raw)])
            self.assertEqual(stopped.exception.code, 1)
            self.assertFalse(output.exists()); self.assertFalse(raw.exists())

    def test_http200_preserves_output_and_raw_directory(self):
        from types import SimpleNamespace
        from inferswarm.operator.metadata import main
        row = json.loads((FIXTURES / 'public-header-manifest.json').read_bytes())['members'][0]
        response = Response(b'weights must not be read', row, status=200)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'out.json'; raw = Path(tmp) / 'raw'
            with patch('inferswarm.operator.metadata.build_opener', return_value=SimpleNamespace(open=lambda *a, **kw: response)), patch('sys.stderr', new=io.StringIO()) as stderr:
                with self.assertRaises(SystemExit) as stopped:
                    main(['reproduce', '--manifest', str(FIXTURES / 'public-header-manifest.json'), '--output', str(output), '--raw-header-dir', str(raw), '--allow-network'])
            self.assertEqual(stopped.exception.code, 1)
            self.assertEqual(stderr.getvalue(), 'expected HTTP 206\n')
            self.assertEqual(response.read_sizes, [])
            self.assertFalse(output.exists()); self.assertFalse(raw.exists())

    def test_strict_fixture_digest_unknown_duplicate_nonfinite_and_mutations(self):
        from inferswarm.operator.metadata import load_metadata_index
        path = FIXTURES / 'q8-metadata.json'
        original = path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'metadata file SHA-256 mismatch'):
            load_metadata_index(path, expected_sha256='0' * 64)
        data = json.loads(original)
        variants = []
        changed = copy.deepcopy(data); changed['tensors'][0]['encoded_bytes'] += 1
        variants.append((json.dumps(changed), 'metadata digest mismatch'))
        variants += [(original.decode().replace('{', '{"schema":"duplicate",', 1), 'duplicate JSON key'),
                     (original.decode().replace('{', '{"unknown":1,', 1), 'metadata index fields'),
                     (original.decode().replace('{', '{"unknown":NaN,', 1), 'nonfinite JSON')]
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'metadata.json'
            for text, reason in variants:
                target.write_text(text)
                with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                    load_metadata_index(target, expected_sha256=sha(target.read_bytes()))


if __name__ == '__main__':
    unittest.main()

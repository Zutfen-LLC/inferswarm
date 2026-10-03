"""Offline regression checks for the Issue #255 physical staging operator."""
import hashlib
import importlib.util
import io
import pathlib
import struct
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'tools/issue255_mvp/prestage.py'
spec = importlib.util.spec_from_file_location('issue255_prestage', SCRIPT)


def fixture():
    def s(text):
        b = text.encode()
        return struct.pack('<Q', len(b)) + b
    # v3, one tensor, one metadata entry (alignment 32); data at aligned offset.
    header = b'GGUF' + struct.pack('<IQQ', 3, 1, 1)
    header += s('general.alignment') + struct.pack('<II', 4, 32)
    header += s('blk.24.attn_gate.weight') + struct.pack('<IQQIQ', 2, 32, 32, 0, 0)
    header += b'\0' * (-len(header) % 32)
    return header + bytes(range(256)) * 16, len(header)


class PrestageTests(unittest.TestCase):
    def module(self):
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_gguf_metadata_offsets_are_absolute_and_range_checked(self):
        m = self.module()
        blob, start = fixture()
        with tempfile.TemporaryDirectory() as directory:
            p = pathlib.Path(directory) / 'part.gguf'
            p.write_bytes(blob)
            entries = m.read_gguf_tensors(p)
            self.assertEqual(entries['blk.24.attn_gate.weight'], (start, 4096, 0))

    def test_native_fnv_matches_pinned_rpc_cache_key(self):
        m = self.module()
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / 'sample'
            path.write_bytes(b'hello')
            binary = pathlib.Path(directory) / 'fnv'
            m.compile_fnv(binary)
            self.assertEqual(m.fnv_file(binary, path), 'a430d84680aabd0b')

    def test_stage_rejects_non_matching_member_and_existing_key(self):
        m = self.module()
        blob, _ = fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            member = root / 'part.gguf'
            member.write_bytes(blob)
            fnv = root / 'fnv'
            m.compile_fnv(fnv)
            cache = root / 'cache'
            with self.assertRaisesRegex(ValueError, 'identity'):
                m.stage(member, '0'*64, ['blk.24.attn_gate.weight'], cache, fnv)
            receipt = m.stage(member, hashlib.sha256(blob).hexdigest(), ['blk.24.attn_gate.weight'], cache, fnv)
            self.assertEqual(len(receipt), 1)
            self.assertEqual(receipt[0]['sha256'], hashlib.sha256(blob[-4096:]).hexdigest())
            with self.assertRaisesRegex(ValueError, 'already'):
                m.stage(member, hashlib.sha256(blob).hexdigest(), ['blk.24.attn_gate.weight'], cache, fnv)

    def test_identical_tensors_share_cache_key_with_distinct_inventory_rows(self):
        m = self.module()
        def s(x):
            b = x.encode()
            return struct.pack('<Q', len(b)) + b
        h = b'GGUF' + struct.pack('<IQQ', 3, 2, 1)
        h += s('general.alignment') + struct.pack('<II', 4, 32)
        for name, offset in [('blk.45.ssm_a', 0), ('blk.46.ssm_a', 32)]:
            h += s(name) + struct.pack('<IQIQ', 1, 8, 24, offset)
        h += b'\0' * (-len(h) % 32)
        blob = h + b'abcdefgh' + bytes(24) + b'abcdefgh'
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            member = root / 'part.gguf'
            member.write_bytes(blob)
            fnv = root / 'fnv'
            m.compile_fnv(fnv)
            result = m.stage(member, hashlib.sha256(blob).hexdigest(),
                             ['blk.45.ssm_a', 'blk.46.ssm_a'], root / 'cache', fnv)
            self.assertEqual(result[0]['fnv1a'], result[1]['fnv1a'])
            self.assertEqual(len(list((root / 'cache' / 'rpc').iterdir())), 1)


if __name__ == '__main__':
    unittest.main()

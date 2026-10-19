"""Partial offline checker controls; never execute a model, socket or GPU."""
import copy
import ctypes
import importlib.util
import json
import os
from pathlib import Path
import platform
import random
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT/'tools/native-moe-overlap'
spec = importlib.util.spec_from_file_location('operand_check', TOOLS/'layer7_operand_check.py')
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)
HELDOUT = json.loads((ROOT/'tests/fixtures/layer7_operand_heldout.json').read_text())


def boundary(d=32):
    """Deterministic synthetic routing, both tokens, different hot slot order."""
    ids = [i for row in HELDOUT['partitions'] for i in row]
    weights = [(i+1)/128 for i in range(20)]
    raw = {}
    for name in ('A.input', 'B.input', 'B.hot.input'):
        raw[name] = struct.pack('<'+'f'*(d*2), *([.5]*(d*2)))
    for arm in ('A', 'B'):
        raw[arm+'.ids'] = struct.pack('<20i', *ids)
        raw[arm+'.weights'] = struct.pack('<20f', *weights)
        for name, n in (('output', d*2), ('shared', d*2), ('weighted', d*20)):
            raw[arm+'.'+name] = b'\0'*(n*4)
    mapping = []
    for token in range(2):
        counts = dict(hot=0, cold=0)
        branches = {name: ([], []) for name in counts}
        for slot, expert in enumerate(ids[token*10:(token+1)*10]):
            hot = expert in check.stages.HOT
            compact = check.stages.HOT.index(expert) if hot else None
            branch = 'hot' if hot else 'cold'
            mapping.append(dict(token=token, original_slot=slot, global_expert=expert,
                                branch=branch, branch_slot=counts[branch], compact_expert=compact))
            counts[branch] += 1
            branches[branch][0].append(compact if hot else expert)
            branches[branch][1].append(weights[token*10+slot])
        for branch, (bi, bw) in branches.items():
            for name, values, fmt in (('ids', bi, 'i'), ('weights', bw, 'f')):
                key = 'B.'+branch+'.'+name
                raw[key] = raw.get(key, b'')+struct.pack('<5'+fmt, *values)
    row = dict(tokens=2, ids=HELDOUT['partitions'],
        weight_bits=[[f'{v:08x}' for v in struct.unpack('<10I', raw['A.weights'][t*40:(t+1)*40])]
                     for t in range(2)], input_sha256=check.stages.digest(raw['A.input']),
        routing_sha256=check.stages.digest(raw['A.ids']+raw['A.weights']),
        **{arm: dict(output_sha256=check.stages.digest(raw[arm+'.output'])) for arm in ('A', 'B')})
    tensors = {}
    for name, data in raw.items():
        if name.endswith('.ids'):
            shape = [5 if '.hot.' in name or '.cold.' in name else 10, 2, 1, 1]
        elif name.endswith('.weights'):
            shape = [1, 5 if '.hot.' in name or '.cold.' in name else 10, 2, 1]
        elif name.endswith('.weighted'):
            shape = [d, 10, 2, 1]
        else:
            shape = [d, 2, 1, 1]
        strides = [4]
        for dim in shape[:-1]:
            strides.append(strides[-1]*dim)
        integer = name.endswith('.ids')
        tensors[name] = dict(shape=shape, strides_bytes=strides,
            type_name='i32' if integer else 'f32', ggml_type=26 if integer else 0)
    base = dict(tensors=tensors, pair_record=row, slot_map=mapping,
                B_weighted_source='retained-branch-outputs/1')
    return base, raw, mapping


class BoundaryControls(unittest.TestCase):
    def test_varied_partitions_and_all_identity_controls(self):
        base, raw, mapping = boundary()
        check.validate_boundary(base, raw, 32, mapping)
        for key in ('A.ids', 'B.ids', 'B.hot.ids', 'B.cold.ids', 'A.weights',
                    'B.weights', 'B.hot.weights', 'B.cold.weights', 'B.hot.input', 'B.output'):
            altered = dict(raw)
            blob = bytearray(raw[key]); blob[0] ^= 1; altered[key] = bytes(blob)
            with self.subTest(key=key), self.assertRaises(ValueError):
                check.validate_boundary(base, altered, 32, mapping)
        for field, value in (('branch_slot', 3), ('compact_expert', 4), ('original_slot', 9)):
            altered = copy.deepcopy(mapping); altered[1][field] = value
            # A mutually consistent metadata edit still must match the routed bytes.
            other = copy.deepcopy(base); other['slot_map'] = altered
            with self.subTest(field=field), self.assertRaises(ValueError):
                check.validate_boundary(other, raw, 32, altered)
        other = copy.deepcopy(base); other['tensors']['A.input']['shape'][0] += 1
        with self.assertRaises(ValueError): check.validate_boundary(other, raw, 32, mapping)

    def test_all_expert_shared_and_stale_output_controls(self):
        d = 7
        weighted = [(-1 if c % 2 else 1)*(t+1)*(s+1)/1024
                    for t in range(2) for s in range(10) for c in range(d)]
        shared = [(t+1)/16 for t in range(2) for c in range(d)]
        output = check.compose(weighted, shared, d)
        report = check.composition_check(weighted, shared, output, d)
        self.assertEqual(report['status'], 'match')
        self.assertEqual(len(report['negative_controls']), 24)
        self.assertTrue(all(c['status'] == 'rejected' for c in report['negative_controls']))
        for slot in range(11):
            omitted = check.compose(weighted, shared, d, omit=slot)
            self.assertEqual(check.composition_check(weighted, shared, omitted, d)['status'], 'mismatch')
        stale = output[d:]+output[:d]
        self.assertEqual(check.composition_check(weighted, shared, stale, d)['status'], 'mismatch')
        corrupted = output[:]; corrupted[8] = check.f32(corrupted[8]+2**-20)
        self.assertEqual(check.exact(output, corrupted)['status'], 'mismatch')

    def test_insensitive_controls_and_nonfinite(self):
        report = check.composition_check([0.]*20, [0.]*2, [0.]*2, 1)
        self.assertTrue(all(c['status'] == 'insensitive-zero-mass' for c in
                            report['negative_controls'] if isinstance(c['omitted'], int) or c['omitted'] == 'shared'))
        signed = check.composition_check([-0.]*20, [-0.]*2, [-0.]*2, 1)
        self.assertTrue(all(c['status'] == 'insensitive-zero-mass' for c in
                           signed['negative_controls'] if c['omitted'] != 'stale-other-token-output'))
        # Nonzero omitted work can also round away; never label this a rejection.
        planes = [1., 2**-30]+[0.]*8
        report = check.composition_check(planes*2, [0.]*2, [1.]*2, 1)
        self.assertEqual(report['negative_controls'][1]['status'], 'insensitive-rounding')
        for bad in (float('nan'), float('inf'), -float('inf')):
            with self.assertRaises(ValueError): check.exact([bad], [0.])
            with self.assertRaises(ValueError): check.compose([bad]*20, [0.]*2, 1)
        with self.assertRaises(ValueError): check.exact([1.], [1., 2.])
        self.assertEqual(check.exact([0.], [-0.])['status'], 'mismatch')
        self.assertEqual(check.weighting_check([2**-126], [.5], [2**-127], 1)['status'], 'unknown')
        self.assertEqual(check.composition_check([2**-149]*20, [0.]*2, [0.]*2, 1)['status'], 'unknown')

    def test_weighting_wrong_weights_and_slot_permutation(self):
        down, weights = [1., 2., 3., 4.], [.25, .5]
        output = [.25, .5, 1.5, 2.]
        self.assertEqual(check.weighting_check(down, weights, output, 2)['status'], 'match')
        self.assertEqual(check.weighting_check(down, weights[::-1], output, 2)['status'], 'mismatch')
        self.assertEqual(check.weighting_check(down, weights, output[2:]+output[:2], 2)['status'], 'mismatch')
        with self.assertRaises(ValueError): check.weighting_check(down, weights, [0.], 2)

    def test_unsupported_widths_report_unknown(self):
        for tokens in (1, 4, 8, 16):
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp)
                (path/'manifest.json').write_text(json.dumps(dict(pair_record=dict(tokens=tokens))))
                self.assertEqual(check.analyze(path, '/unused')['status'], 'unknown')


@unittest.skipUnless(platform.machine() == 'x86_64' and 'f16c' in Path('/proc/cpuinfo').read_text(),
                     'offline arithmetic helper requires x86 F16C')
class ProjectionControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='l7-operand-')
        cls.helper = Path(cls.temp.name)/'helper.so'
        subprocess.run(['c++', '-O3', '-std=c++17', '-shared', '-fPIC', '-mf16c', '-ffp-contract=off',
            str(TOOLS/'layer7_arithmetic.cpp'), '-o', str(cls.helper)], check=True, capture_output=True, timeout=30)
        cls.math = check.arithmetic.Arithmetic(cls.helper)

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def test_quantization_threshold_neighbours_both_signs_and_tokens(self):
        # All neighbours are fixed binary32 values, independent of physical residuals.
        below, tie, above = 62.499996185302734, 62.5, 62.500003814697266
        for sign in (-1, 1):
            for token in range(2):
                values = [127., sign*below, sign*tie, sign*above]+[0.]*28
                cpu = self.math.quantize(values)
                rn_cuda = self.math.quantize(values, True)
                self.assertEqual(struct.unpack_from('<3b', cpu, 3), (sign*62, sign*62, sign*63))
                self.assertEqual(struct.unpack_from('<3b', rn_cuda, 3), (sign*62, sign*63, sign*63))

    def test_fixed_heldout_projection_and_wrong_bank_slot_stale_controls(self):
        rng = random.Random(HELDOUT['seed']); d, f = HELDOUT['d'], HELDOUT['f']
        values = [rng.randint(-64, 64)/64 for _ in range(2*d)]
        for at in range(0, 2*d, 32): values[at] = 1.
        bank = b''.join(struct.pack('<e32b', 1/32, *(rng.randint(-3, 3) for _ in range(32)))
                        for _ in range(5*f*d//32))
        _, _, mapping = boundary(d)
        # Independently calculate these small, exactly representable lane sums.
        q = []
        for token in range(2):
            q.append([round(check.f32(v*127)) for v in values[token*d:(token+1)*d]])
        scale = struct.unpack('<e', struct.pack('<e', check.f32(1/127)))[0]
        observed = [0.]*(20*f)
        for e in mapping:
            if e['branch'] != 'hot': continue
            for row in range(f):
                at = (e['compact_expert']*f+row)*68
                qs = [*struct.unpack_from('<32b', bank, at+2), *struct.unpack_from('<32b', bank, at+36)]
                value = check.f32(sum(w*v for w, v in zip(qs, q[e['token']]))*scale/32)
                observed[(e['token']*10+e['original_slot'])*f+row] = value
        def run(w=bank, x=values, y=observed, m=mapping, profile=check.CPU):
            return check.cpu_projection(self.math, w, x, y, m, d, f, profile)
        self.assertEqual(run()['status'], 'match')
        # Independent actual pinned CPU functions also check the frozen inputs
        # when the authenticated native oracle is supplied by the local run.
        if os.environ.get('LAYER7_NATIVE_ORACLE'):
            native = ctypes.CDLL(os.environ['LAYER7_NATIVE_ORACLE'])
            native.oracle_quant.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int]
            native.oracle_dot.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int]
            native.oracle_dot.restype = ctypes.c_float
            for token in range(2):
                activation = ctypes.create_string_buffer(68)
                native.oracle_quant(struct.pack('<64f', *values[token*d:(token+1)*d]), activation, d)
                self.assertEqual(activation.raw, self.math.quantize(values[token*d:(token+1)*d]))
                for e in mapping:
                    if e['token'] != token or e['branch'] != 'hot': continue
                    for row in range(f):
                        at = (e['compact_expert']*f+row)*68
                        actual = native.oracle_dot(bank[at:at+68], activation.raw, d)
                        self.assertEqual(actual, observed[(token*10+e['original_slot'])*f+row])
        corrupted = bytearray(bank); corrupted[2] += 1
        self.assertEqual(run(w=bytes(corrupted))['status'], 'mismatch')
        wrong = copy.deepcopy(mapping)
        for e in wrong:
            if e['branch'] == 'hot': e['compact_expert'] = (e['compact_expert']+1)%5
        self.assertEqual(run(m=wrong)['status'], 'mismatch')
        self.assertEqual(run(x=values[d:]+values[:d])['status'], 'mismatch')
        missing = observed[:]
        for e in mapping:
            if e['branch'] == 'hot':
                at = (e['token']*10+e['original_slot'])*f
                changed = missing[:]; changed[at:at+f] = [0.]*f
                self.assertEqual(run(y=changed)['status'], 'mismatch')
        self.assertEqual(run(profile='cuda-mmvq-t8')['status'], 'unknown')
        self.assertEqual(run(x=[1e-12]*(2*d))['status'], 'unknown')
        for bad in (float('inf'), float('nan')):
            changed = values[:]; changed[0] = bad
            with self.assertRaises(ValueError): run(x=changed)

    def test_non_rn_emulator_environment_is_unknown(self):
        library = ctypes.CDLL(None)
        original = library.fegetround()
        try:
            self.assertEqual(library.fesetround(0x400), 0)  # Linux x86 FE_DOWNWARD
            self.assertEqual(self.math.library.l7_environment_ok(), 0)
            result = check.cpu_projection(self.math, b'', [], [], [], 64, 3)
            self.assertEqual(result['status'], 'unknown')
        finally:
            library.fesetround(original)

    @unittest.skipUnless(os.environ.get('LAYER7_STAGE_CAPTURE'), 'optional authenticated retained capture')
    def test_physical_partial_result_never_overrides_invalid(self):
        result = check.analyze(os.environ['LAYER7_STAGE_CAPTURE'], self.helper)
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(result['end_to_end'], 'unknown')
        self.assertFalse(result['numerical_qualification'])
        self.assertFalse(result['legacy_comparator']['pass'])
        self.assertAlmostEqual(result['legacy_comparator']['max_ratio'], 1.1361652968828178)
        self.assertTrue(all(c['status'] == 'match' for c in result['checks'].values()))
        for arm in ('A', 'B'):
            controls = result['checks'][arm+'.composition']['negative_controls']
            self.assertTrue(all(c['status'] == 'rejected' for c in controls))


if __name__ == '__main__': unittest.main()

"""Focused offline arithmetic tests; no sockets, GPU, model or CI campaign."""
import importlib.util
import ctypes
import os
from pathlib import Path
import platform
import struct
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'tools/native-moe-overlap/layer7_arithmetic.cpp'
spec=importlib.util.spec_from_file_location('arithmetic',SOURCE.with_suffix('.py'))
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


@unittest.skipUnless(platform.machine()=='x86_64' and 'f16c' in Path('/proc/cpuinfo').read_text(),
                     'offline helper requires x86 F16C')
class Layer7Arithmetic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='l7-arithmetic-')
        cls.library=Path(cls.temp.name)/'arithmetic.so'
        subprocess.run(['c++','-O3','-std=c++17','-shared','-fPIC','-mf16c','-ffp-contract=off',
                        str(SOURCE),'-o',str(cls.library)],check=True,capture_output=True,timeout=30)
        cls.math=module.Arithmetic(cls.library)

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_integer_ties_and_scale_rounding_are_distinct(self):
        values=[127.,-63.5,62.5]+[0.]*29
        cpu=self.math.quantize(values);cuda=self.math.quantize(values,True)
        self.assertEqual(struct.unpack_from('<e',cpu)[0],1.)
        self.assertEqual(struct.unpack_from('<3b',cpu,2),(127,-64,62))
        self.assertEqual(struct.unpack_from('<3b',cuda,2),(127,-64,63))
        values=[.8800000548362732,-.4400000274181366]+[0.]*30
        cpu=self.math.quantize(values);cuda=self.math.quantize(values,True)
        self.assertEqual(cpu,cuda) # RN host division cannot assert a different device byte.
        self.assertEqual(struct.unpack_from('<b',cpu,3)[0],-64)
        self.assertEqual(struct.unpack_from('<e',cpu)[0],.006927490234375)

    def test_q8_layout_zero_and_invalid_rows(self):
        zero=self.math.quantize([0.]*64)
        self.assertEqual(zero,b'\0'*68)
        for values in ([],[1.]*31,[float('nan')]*32):
            with self.assertRaises(ValueError):self.math.quantize(values)
        for args in ((b'',b''),(b'x'*34,b'x'*68)):
            with self.assertRaises(ValueError):self.math.dot(*args)

    def test_integer_dot_models_and_hypothesis_byte_preserve_scale(self):
        weight=struct.pack('<e32b',.5,*([1]*32))*2
        activation=struct.pack('<e32b',.25,*([2]*32))*2
        self.assertEqual(self.math.dot(weight,activation),16.)
        self.assertEqual(self.math.dot(weight,activation,True),16.)
        changed,old=module.change_byte(activation,57,3)
        self.assertEqual(old,2)
        self.assertEqual(changed[:34],activation[:34])
        self.assertEqual(changed[34:36],activation[34:36])
        self.assertEqual(self.math.dot(weight,changed,True),16.125)
        for index,value in ((64,0),(-1,0),(0,128)):
            with self.assertRaises(ValueError):module.change_byte(activation,index,value)

    def test_signed_zero_is_not_bit_exact(self):
        report=module.metrics([0.,1.],[-0.,1.])
        self.assertEqual(report['exact'],1)
        self.assertEqual(report['max_abs'],0)

    @unittest.skipUnless(os.environ.get('LAYER7_STAGE_CAPTURE'),'optional authenticated physical capture')
    def test_physical_all_experts_both_tokens_and_rejected_alternatives(self):
        directory=Path(os.environ['LAYER7_STAGE_CAPTURE'])
        r=module.analyze(directory,self.library,[(1,1529,-63)])
        self.assertEqual(r['selected_pair'],dict(case='mixed-varied-set',tokens=2,pair=13,warmup=False,order='BA'))
        self.assertEqual(len(r['profiles']),20)
        for key in ('cpu','cuda_hypothesis'):
            self.assertEqual(r['summary'][key],dict(coordinates=12800,exact=12800,max_abs=0.))
        self.assertEqual(r['quantization'][1]['exact_half_integer_host_quotients'][0]['index'],1529)
        self.assertTrue(all(x['host_rn_bytes_equal'] for x in r['quantization']))
        self.assertLess(r['summary']['cuda_host_rn']['exact'],12800)
        self.assertGreater(r['summary']['cuda_host_rn']['max_abs'],4e-5)
        self.assertLess(r['summary']['cuda_hypothesis_no_fma']['exact'],12800)
        # All profiles in both tokens and all original/compact slot mappings.
        for p in r['profiles']:
            self.assertEqual(p['cpu']['exact'],640)
            self.assertEqual(p['cuda_hypothesis']['exact'],640)
        wrong=module.analyze(directory,self.library,[(1,1529,-65)])
        self.assertGreater(wrong['summary']['cuda_hypothesis']['max_abs'],9e-5)
        self.assertEqual(wrong['summary']['cpu']['exact'],12800)

    @unittest.skipUnless(os.environ.get('LAYER7_STAGE_CAPTURE') and os.environ.get('LAYER7_NATIVE_ORACLE'),
                         'optional pinned native CPU quantizer/dot wrapper')
    def test_model_matches_actual_pinned_cpu_functions(self):
        native=ctypes.CDLL(os.environ['LAYER7_NATIVE_ORACLE'])
        native.oracle_quant.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_int]
        native.oracle_dot.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_int]
        native.oracle_dot.restype=ctypes.c_float
        directory=Path(os.environ['LAYER7_STAGE_CAPTURE'])
        m=module.stages.load_capture(directory)
        raw=(directory.parent/'capture/A.input.bin').read_bytes()
        for token in range(2):
            data=raw[token*10240:(token+1)*10240]
            out=ctypes.create_string_buffer(2720)
            native.oracle_quant(data,out,2560)
            values=struct.unpack('<2560f',data)
            self.assertEqual(self.math.quantize(values),out.raw)
            for stage in ('gate','up'):
                bank=(directory/(stage+'.q8_0.bin')).read_bytes()
                for row in range(5*640):
                    weight=bank[row*2720:(row+1)*2720]
                    self.assertEqual(struct.pack('<f',self.math.dot(weight,out.raw)),
                                     struct.pack('<f',native.oracle_dot(weight,out.raw,2560)))


if __name__=='__main__':unittest.main()

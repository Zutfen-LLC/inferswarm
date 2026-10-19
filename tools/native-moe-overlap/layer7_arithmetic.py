#!/usr/bin/env python3
"""Offline gate/up reconstruction of captured Q8_0 layer-7 stages.

The CUDA model uses host RN division, not device approximate division. Explicit
quantized-byte hypotheses remain inferences, even when all output bits match.
No benchmark verdict, tolerance, runtime arithmetic, GPU or network is changed.
"""
from __future__ import annotations
import argparse
import ctypes
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import struct

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('layer7_stage_bytes', HERE/'layer7_stages.py')
stages = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stages)


class Arithmetic:
    def __init__(self, helper):
        self.path = Path(helper).resolve()
        self.library = ctypes.CDLL(str(self.path))
        self.library.l7_quantize.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
        self.library.l7_dot_cpu.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int]
        self.library.l7_dot_cuda.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        self.library.l7_dot_cpu.restype = self.library.l7_dot_cuda.restype = ctypes.c_float

    def quantize(self, values, cuda_rn=False):
        if not values or len(values)%32 or not all(math.isfinite(v) for v in values):
            raise ValueError('finite complete Q8 blocks required')
        data = struct.pack('<'+'f'*len(values), *values)
        out = ctypes.create_string_buffer(len(values)//32*34)
        self.library.l7_quantize(data,len(values),out,int(cuda_rn))
        return out.raw

    def dot(self, weights, activation, cuda=False, fused=True):
        if not weights or len(weights)!=len(activation) or len(weights)%34:
            raise ValueError('matching complete Q8 rows required')
        n = len(weights)//34*32
        if cuda:
            return self.library.l7_dot_cuda(weights,activation,n,int(fused))
        return self.library.l7_dot_cpu(weights,activation,n)


def change_byte(data,index,value):
    if not 0<=index<len(data)//34*32 or not -127<=value<=127:
        raise ValueError('quantized-byte hypothesis outside row')
    result=bytearray(data);position=index//32*34+2+index%32
    previous=struct.unpack_from('<b',result,position)[0]
    struct.pack_into('<b',result,position,value)
    return bytes(result),previous


def metrics(predicted,observed):
    differences=[a-b for a,b in zip(predicted,observed)]
    at=max(range(len(differences)),key=lambda i:abs(differences[i]))
    return dict(coordinates=len(differences),exact=sum(struct.pack('<f',a)==struct.pack('<f',b)
                for a,b in zip(predicted,observed)),max_abs=abs(differences[at]),
                rms=math.sqrt(sum(d*d for d in differences)/len(differences)),
                worst_coordinate=at,reconstructed=predicted[at],captured=observed[at])


def analyze(directory,helper,hypotheses=()):
    directory=Path(directory);m=stages.load_capture(directory);arithmetic=Arithmetic(helper)
    d=m['files']['gate.q8_0.bin']['shape'][0]
    f=m['files']['A.gate.bin']['shape'][0]
    inputs=stages.floats((directory.parent/'capture/A.input.bin').read_bytes())
    if (directory.parent/'capture/A.input.bin').read_bytes()!=(directory.parent/'capture/B.hot.input.bin').read_bytes():
        raise ValueError('paired consumed inputs differ')
    if len(inputs)!=2*d or f>640 or d>2560:
        raise ValueError('bounded two-token gate/up reconstruction required')
    result=dict(schema='h5-layer7-arithmetic/1',performance_claim=False,
        helper_sha256=hashlib.sha256(Path(helper).read_bytes()).hexdigest(),
        helper_source_sha256=hashlib.sha256((HERE/'layer7_arithmetic.cpp').read_bytes()).hexdigest(),
        analysis_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        stage_manifest_sha256=hashlib.sha256((directory/'manifest.json').read_bytes()).hexdigest(),
        selected_pair={k:m['pair_record'][k] for k in ('case','tokens','pair','warmup','order')},
        quantization=[],profiles=[],hypotheses=[],
        scope='CPU AVX2/FMA and NVIDIA 32-lane multi-token MMVQ; host-RN CUDA quantizer is a model, not captured activation bytes',
        attribution='Exact output reproduction under a byte hypothesis does not prove the unretained device byte or approximate division instruction')
    quantized=[]
    for token in range(2):
        values=inputs[token*d:(token+1)*d]
        cpu=arithmetic.quantize(values);cuda=arithmetic.quantize(values,True)
        near=[]
        for b in range(d//32):
            a=max(abs(v) for v in values[b*32:(b+1)*32]);scale=struct.unpack('<f',struct.pack('<f',a/127))[0]
            for j,v in enumerate(values[b*32:(b+1)*32]):
                ratio=struct.unpack('<f',struct.pack('<f',v/scale))[0] if a else 0
                if abs(ratio)%1==.5:
                    near.append(dict(index=b*32+j,input=v,amax=a,scale_f32=scale,
                        scale_f16=struct.unpack_from('<e',cpu,b*34)[0],host_rn_quotient=ratio))
        hypothesized=cuda
        for t,index,value in hypotheses:
            if t not in (0,1):raise ValueError('hypothesis token must be 0 or 1')
            if t==token:
                hypothesized,previous=change_byte(hypothesized,index,value)
                result['hypotheses'].append(dict(token=t,index=index,from_byte=previous,to_byte=value,
                    status='explicit offline hypothesis; device bytes not retained'))
        result['quantization'].append(dict(token=token,cpu_q8_sha256=stages.digest(cpu),
            cuda_host_rn_q8_sha256=stages.digest(cuda),host_rn_bytes_equal=cpu==cuda,
            hypothesized_q8_sha256=stages.digest(hypothesized),
            exact_half_integer_host_quotients=near))
        quantized.append((cpu,cuda,hypothesized))
    for stage in ('gate','up'):
        bank=(directory/(stage+'.q8_0.bin')).read_bytes()
        av=stages.floats((directory/('A.'+stage+'.bin')).read_bytes())
        bv=stages.floats((directory/('B.'+stage+'.bin')).read_bytes())
        for entry in m['slot_map']:
            if entry['branch']!='hot':continue
            token=entry['token'];expert=m['compact_expert_order'].index(entry['global_expert'])
            cpu,cuda,hyp=quantized[token]
            observed_a=av[(token*10+entry['original_slot'])*f:(token*10+entry['original_slot']+1)*f]
            observed_b=bv[(token*5+entry['branch_slot'])*f:(token*5+entry['branch_slot']+1)*f]
            predictions={k:[] for k in ('cpu','cuda_host_rn','cuda_hypothesis','cuda_hypothesis_no_fma')}
            for row in range(f):
                weight=bank[(expert*f+row)*(d//32*34):(expert*f+row+1)*(d//32*34)]
                predictions['cpu'].append(arithmetic.dot(weight,cpu))
                predictions['cuda_host_rn'].append(arithmetic.dot(weight,cuda,True))
                predictions['cuda_hypothesis'].append(arithmetic.dot(weight,hyp,True))
                predictions['cuda_hypothesis_no_fma'].append(arithmetic.dot(weight,hyp,True,False))
            worst=max(range(f),key=lambda c:abs(observed_a[c]-observed_b[c]))
            result['profiles'].append(dict(stage=stage,token=token,global_expert=entry['global_expert'],
                original_slot=entry['original_slot'],branch_slot=entry['branch_slot'],
                observed_difference=metrics(observed_a,observed_b),
                worst_observed_point=dict(coordinate=worst,A=observed_a[worst],B=observed_b[worst],
                    cpu=predictions['cpu'][worst],cuda_host_rn=predictions['cuda_host_rn'][worst],
                    cuda_hypothesis=predictions['cuda_hypothesis'][worst]),
                **{key:metrics(values,observed_a if key=='cpu' else observed_b) for key,values in predictions.items()}))
    result['summary']={key:dict(coordinates=sum(p[key]['coordinates'] for p in result['profiles']),
                exact=sum(p[key]['exact'] for p in result['profiles']),
                max_abs=max(p[key]['max_abs'] for p in result['profiles'])) for key in predictions}
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture',type=Path,required=True)
    parser.add_argument('--helper',type=Path,required=True,help='locally compiled layer7_arithmetic.cpp shared library')
    parser.add_argument('--hypothesis',action='append',default=[],help='explicit TOKEN:INPUT_INDEX:SIGNED_BYTE hypothesis')
    parser.add_argument('--output',type=Path,required=True,help='fresh JSON report')
    args=parser.parse_args()
    hypotheses=[tuple(map(int,item.split(':'))) for item in args.hypothesis]
    if any(len(h)!=3 for h in hypotheses):raise ValueError('hypothesis requires three integers')
    result=analyze(args.capture,args.helper,hypotheses)
    with args.output.open('x') as stream:json.dump(result,stream,indent=2,allow_nan=False);stream.write('\n')
    print(json.dumps(result['summary'],sort_keys=True))

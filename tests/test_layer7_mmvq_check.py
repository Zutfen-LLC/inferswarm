"""Independent widths, frozen inputs and coherent corruption controls."""
import copy
import importlib.util
import json
import math
import os
from pathlib import Path
import random
import struct
import tempfile
import unittest
from tests.test_layer7_operand_check import check, TOOLS, ROOT
from tests import test_layer7_operand_check as support

spec = importlib.util.spec_from_file_location('mmvq', TOOLS/'layer7_mmvq_check.py')
mmvq = importlib.util.module_from_spec(spec); spec.loader.exec_module(mmvq)
FIXTURE = json.loads((ROOT/'tests/fixtures/layer7_mmvq_heldout.json').read_text())


def fixture(helper, tokens):
    d, f = FIXTURE['columns'], FIXTURE['hidden']
    rng = random.Random(FIXTURE['width_seeds'][str(tokens)])
    inputs = [rng.randint(-64,64)/64 for _ in range(tokens*d)]
    for at in range(0,len(inputs),32): inputs[at] = 1.
    rng = random.Random(FIXTURE['width_seeds'][str(tokens)]+100)
    def bank(columns, rows, scale):
        return b''.join(struct.pack('<e32b',scale,*(rng.randint(-5,5) for _ in range(32)))
                        for _ in range(5*rows*columns//32))
    banks = dict(gate=bank(d,f,1/512),up=bank(d,f,1/512),down=bank(f,d,1/256))
    mapping = []
    for t in range(tokens):
        for slot in range(5):
            expert = (slot+t)%5
            mapping.append(dict(token=t,branch='hot',branch_slot=slot,original_slot=slot*2,
                                compact_expert=expert,global_expert=check.stages.HOT[expert]))
    def project(name, operands, columns, rows, down=False):
        result = []
        for e in mapping:
            at = (e['token']*5+e['branch_slot'] if down else e['token'])*columns
            q = helper.quantize(operands[at:at+columns],True)
            for c in range(rows):
                start = (e['compact_expert']*rows+c)*(columns//32*34)
                result.append(helper.dot(banks[name][start:start+columns//32*34],q,True))
        return result
    gate, up = project('gate',inputs,d,f),project('up',inputs,d,f)
    swiglu = [check.f32(g/(1+math.exp(-g))*u) for g,u in zip(gate,up)]
    down = project('down',swiglu,f,d,True)
    return banks, inputs, mapping, dict(gate=gate,up=up,swiglu=swiglu,down=down), project


class ConditionalMMVQ(unittest.TestCase):
    setUpClass = classmethod(support.ProjectionControls.setUpClass.__func__)
    tearDownClass = classmethod(support.ProjectionControls.tearDownClass.__func__)

    @unittest.skipUnless(os.environ.get('LAYER7_STAGE_CAPTURE'), 'optional retained capture')
    def test_retained_complete_conditional_arithmetic_needs_timed_binding(self):
        result=check.analyze(os.environ['LAYER7_STAGE_CAPTURE'], self.helper, conditional=True)
        self.assertEqual(result['conditional_arithmetic'],'match')
        self.assertEqual(result['status'],'inconclusive')
        self.assertEqual(result['timed_binding'],'unknown')
        self.assertTrue(result['sensitive'])
        self.assertFalse(result['numerical_qualification'])
        self.assertFalse(result['legacy_comparator']['pass'])
    def test_widths_separately_with_coherent_omission_wrong_bank_and_stale_controls(self):
        for t in (1,2,4,8):
            with self.subTest(tokens=t):
                banks, inputs, mapping, data, project = fixture(self.math,t)
                def run(stage, observed=None, bank=None, route=None, operands=None):
                    down = stage == 'down'
                    return mmvq.projection(self.math,bank or banks[stage],
                        operands if operands is not None else data['swiglu'] if down else inputs,
                        data[stage] if observed is None else observed, route or mapping,
                        32 if down else 64,64 if down else 32,t,down)
                for stage in ('gate','up','down'):
                    report = run(stage)
                    self.assertEqual(report['status'],'match')
                    self.assertTrue(report['sensitive'])
                    # Coherent downstream recomputation cannot hide the earlier
                    # edge's missing expert: zero each expert vector in turn.
                    rows = 64 if stage == 'down' else 32
                    for e in mapping:
                        changed = data[stage][:];at=(e['token']*5+e['branch_slot'])*rows
                        changed[at:at+rows]=[0.]*rows
                        self.assertEqual(run(stage,observed=changed)['status'],'mismatch')
                    size=len(banks[stage])//5
                    wrong = banks[stage][size:2*size]+banks[stage][:size]+banks[stage][2*size:]
                    self.assertEqual(run(stage,bank=wrong)['status'],'mismatch')
                report = mmvq.swiglu(data['gate'],data['up'],data['swiglu'],32,t)
                self.assertEqual(report['status'],'match');self.assertTrue(report['sensitive'])
                changed=data['swiglu'][:];changed[:32]=[0.]*32
                self.assertEqual(mmvq.swiglu(data['gate'],data['up'],changed,32,t)['status'],'mismatch')
                # Actually recompute later edges after zeroing gate. They remain
                # internally consistent, while the independent gate edge fails.
                gate=data['gate'][:];gate[:32]=[0.]*32
                downstream=[check.f32(g/(1+math.exp(-g))*u) for g,u in zip(gate,data['up'])]
                recomputed=project('down',downstream,32,64,True)
                self.assertEqual(mmvq.swiglu(gate,data['up'],downstream,32,t)['status'],'match')
                self.assertEqual(run('down',observed=recomputed,operands=downstream)['status'],'match')
                self.assertEqual(run('gate',observed=gate)['status'],'mismatch')
                wrong=copy.deepcopy(mapping)
                for e in wrong:e['compact_expert']=(e['compact_expert']+1)%5
                self.assertEqual(run('gate',route=wrong)['status'],'mismatch')
                stale=[check.f32(v*.75) for v in inputs]
                self.assertEqual(run('gate',operands=stale)['status'],'mismatch')
                bounds=mmvq.swiglu_bounds(data['gate'],data['up'])
                changed=data['swiglu'][:];changed[0]=check.f32(bounds[0][1]+1)
                self.assertEqual(mmvq.compare_bounds(bounds,changed)['status'],'mismatch')

    def test_threshold_sets_not_a_selected_byte_exception(self):
        low,high,n=mmvq.quantization_bounds([.8800000548362732,-.4400000274181366]+[0.]*30)
        self.assertEqual(struct.unpack_from('<b',low,3)[0],-64)
        self.assertEqual(struct.unpack_from('<b',high,3)[0],-63)
        self.assertEqual(n,1)
        for sign in (-1,1):
            low,high,n=mmvq.quantization_bounds([127.,sign*62.5]+[0.]*30)
            self.assertEqual(set((struct.unpack_from('<b',low,3)[0],struct.unpack_from('<b',high,3)[0])),{sign*62,sign*63})
        self.assertEqual(mmvq.projection(self.math,b'',[],[],[],64,32,16)['status'],'unknown')
        for bad in (math.nan,math.inf):
            with self.assertRaises(ValueError):mmvq.quantization_bounds([bad]*32)
            with self.assertRaises(ValueError):mmvq.swiglu_bounds([bad],[1.])
        zero=mmvq.projection(self.math,struct.pack('<e32b',1.,*([1]*32))*5,[0.]*32,[0.]*5,
            [dict(token=0,branch='hot',branch_slot=i,compact_expert=i,global_expert=i) for i in range(5)],32,1,1)
        self.assertFalse(zero['sensitive'])

    def test_replay_binds_external_timed_record_and_rejects_stale_identity(self):
        row=dict(case='mixed',tokens=1,pair=0,warmup=False,order='AB',input_sha256='input',
                 routing_sha256='route',ids=[1],weight_bits=['bits'],A=dict(output_sha256='a'),B=dict(output_sha256='b'))
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'stages').mkdir();records=root/'stdout.jsonl'
            records.write_text(json.dumps(row)+'\n')
            binding=dict(schema='h5-layer7-replay-binding/1',timed_record=row,timed_graph_retention=False,replay_after_all_timed_work=True)
            (root/'replay-binding.json').write_text(json.dumps(binding))
            self.assertEqual(check.replay_binding(root/'stages',row,records),'match')
            wrong=copy.deepcopy(row);wrong['B']['output_sha256']='stale'
            self.assertEqual(check.replay_binding(root/'stages',wrong,records),'mismatch')
            wrong=copy.deepcopy(row);wrong['routing_sha256']='old'
            self.assertEqual(check.replay_binding(root/'stages',wrong,records),'mismatch')
            records.write_text(json.dumps(row)+'\n'+json.dumps(row)+'\n')
            self.assertEqual(check.replay_binding(root/'stages',row,records),'mismatch')


if __name__ == '__main__':unittest.main()

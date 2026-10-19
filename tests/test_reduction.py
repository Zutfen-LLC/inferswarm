"""Exact grouped reduction, omission sensitivity and frozen fair-grid controls."""
import copy
import importlib.util
import math
from pathlib import Path
import random
import struct
import unittest
from tests import test_factorial_check as old

TOOLS=old.TOOLS
spec=importlib.util.spec_from_file_location('reduction_tests',TOOLS/'reduction_check.py')
check=importlib.util.module_from_spec(spec);spec.loader.exec_module(check)


def operands(tokens,hot,d=4):
    rng=random.Random(723+tokens+hot)
    # Nonzero, varied F32 terms; cancellation exercises regrouping.
    planes=[check.legacy.f32(rng.uniform(-.05,.05)) for _ in range(tokens*10*d)]
    shared=[check.legacy.f32(rng.uniform(-.05,.05)) for _ in range(tokens*d)]
    mapping=[dict(token=t,original_slot=s,branch='hot' if hot==10 or s%2==0 else 'cold') for t in range(tokens) for s in range(10)]
    return planes,shared,mapping


class Reduction(unittest.TestCase):
    def test_exact_ordered_sum_and_every_omission_and_wrong_token(self):
        for tokens in (1,4):
            for hot in (5,10):
                d=4;p,s,m=operands(tokens,hot,d)
                out,remote=check.reduced_compose(p,s,d,tokens,m)
                report=check.reduced_composition_check(p,s,out,remote,d,tokens,m)
                self.assertEqual(report['status'],'match')
                self.assertTrue(all(c['status']=='rejected' for c in report['negative_controls']))
                self.assertLessEqual(report['max_regrouping_abs'],report['max_regrouping_bound'])
                # No widening: even one F32 neighbour is rejected in either return.
                for field in ('output','remote'):
                    changed=out[:] if field=='output' else remote[:]
                    bits=struct.unpack('<I',struct.pack('<f',changed[0]))[0]
                    changed[0]=struct.unpack('<f',struct.pack('<I',bits+1))[0]
                    self.assertEqual(check.reduced_composition_check(p,s,changed if field=='output' else out,
                        changed if field=='remote' else remote,d,tokens,m)['status'],'mismatch')
                for slot in range(11):
                    bad,_=check.reduced_compose(p,s,d,tokens,m,slot)
                    self.assertEqual(check.reduced_composition_check(p,s,bad,remote,d,tokens,m)['status'],'mismatch')
                if tokens==4:
                    wrong=out[d:]+out[:d]
                    self.assertEqual(check.reduced_composition_check(p,s,wrong,remote,d,tokens,m)['status'],'mismatch')

    def test_mixed_grouping_changes_bytes_and_all_remote_preserves_fold(self):
        for hot in (5,10):
            p,s,m=operands(4,hot)
            grouped,_=check.reduced_compose(p,s,4,4,m)
            original=check.legacy.compose(p,s,4,4)
            self.assertEqual(check.exact(original,grouped)['status'],'match' if hot==10 else 'mismatch')

    def test_nonfinite_underflow_and_mapping_fail_closed(self):
        p,s,m=operands(1,5)
        out,remote=check.reduced_compose(p,s,4,1,m)
        with self.assertRaises(ValueError):check.reduced_composition_check(p,s,out,[math.nan]*4,4,1,m)
        changed=p[:];changed[0]=2**-140
        self.assertEqual(check.reduced_composition_check(changed,s,out,remote,4,1,m)['status'],'unknown')
        wrong=copy.deepcopy(m);wrong[1]['original_slot']=0
        with self.assertRaises(ValueError):check.reduced_compose(p,s,4,1,wrong)

    def test_reduced_boundary_rejects_mapping_and_wrong_token(self):
        for tokens in (1,4):
            for hot in (5,10):
                base,raw,mapping=old.boundary(tokens,hot)
                base['pair_record']['factorial_arm']='reduced'+str(hot)
                raw['B.remote_sum']=bytes(64*tokens*4)
                base['tensors']['B.remote_sum']=copy.deepcopy(base['tensors']['B.output'])
                base['tensors']['B.remote_sum']['file']='B.remote_sum.bin'
                check.validate_boundary(base,raw,64,mapping,tokens)
                changed=copy.deepcopy(mapping);changed[0]['original_slot']=1
                with self.assertRaises(ValueError):check.validate_boundary(base,raw,64,changed,tokens)
                for name in ('B.hot.ids','B.hot.weights','B.output'):
                    wrong=dict(raw);data=bytearray(wrong[name]);data[0]^=1;wrong[name]=bytes(data)
                    with self.assertRaises(ValueError):check.validate_boundary(base,wrong,64,mapping,tokens)


class Grid(unittest.TestCase):
    def records(self):
        records=old.FactorialGrid().records()
        # JSON text replacement keeps block/pair references and all bindings equal.
        import json
        text=json.dumps(records)
        for a,b in [('pipeline5','reduced5'),('pipeline10','reduced10'),('current5','pipeline5'),('current10','pipeline10'),('h5-layer7-factorial/1','h5-layer7-reduction/1')]:text=text.replace(a,b)
        records=json.loads(text)
        for row in records:
            stats=list(row['arms'].items()) if row['type']=='factorial-block' else [(row['factorial_arm'],row['B'])] if row['type']=='factorial-pair' else []
            for name,s in stats:
                if name=='cpu':continue
                reduced=name.startswith('reduced');s['reduced_output']=reduced
                s['result_bytes']=2560*row['tokens']*4*(1 if reduced else s['hot'])
                s['rpc']['pipeline']=1;s['rpc']['rx_wire_bytes']=35+s['result_bytes']
        return records

    def test_actual_bytes_modes_exact_bindings_and_pair_balance(self):
        records=self.records();timed,blocks,mode=check.validate_records(records)
        self.assertEqual((len(timed),len(blocks),mode),(160,50,'cpu-cuda'))
        for field in ('rx_wire_bytes','pipeline'):
            wrong=copy.deepcopy(records)
            # Change both aliased record copies consistently; protocol must reject.
            for row in wrong:
                if row['type']=='factorial-block':row['arms']['reduced5']['rpc'][field]+=1
                if row['type']=='factorial-pair' and row['factorial_arm']=='reduced5':row['B']['rpc'][field]+=1
            with self.assertRaises(ValueError):check.validate_records(wrong)
        check.performance(blocks)


if __name__=='__main__':unittest.main()

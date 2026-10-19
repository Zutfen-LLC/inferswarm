"""Frozen warmed grid, structural STOPs and post-validation timing reports."""
import copy
import hashlib
import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import test_native_moe_overlap as support
from tests.test_layer7_operand_check import check


class WarmedSweep(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        support.Layer7BatchSweepContracts.setUpClass()
        cls.tool = support.Layer7BatchSweepContracts.tool

    def rows(self, warmed=True):
        widths, pairs, warmup = (1,2,4,8), 20 if warmed else 1, 5 if warmed else 0
        rows = [dict(type='setup', comparator=self.tool.comparison_contract('cpu-loopback'),
            comparison_mode='cpu-loopback', tokens_list=list(widths), warmed_operand_sweep=warmed)]
        for t in widths:
            for case in (('mixed',) if t == 1 else ('mixed-varied-set','mixed-shared-set')):
                for warm, count in ((True,warmup),(False,pairs)):
                    for i in range(count):
                        r = support.Layer7BatchSweepContracts.row(case,t,i,warm,5)
                        ids = [54,17,74,231,136,3,290,411,394,277]
                        r['ids'] = [ids]*t if t > 1 else ids
                        r['routing_sha256'] = hashlib.sha256(struct.pack('<10i',*ids)*t+
                            b''.join(bytes.fromhex(b)[::-1] for b in ['3dcccccd']*10*t)).hexdigest()
                        r['structural_valid'] = True
                        for a in ('A','B'):
                            r[a].update(routing_sha256=r['routing_sha256'],output_sha256=a.lower()*64)
                        rows.append(r)
        timed = [r for r in rows if r['type']=='pair' and not r['warmup']]
        rows += [dict(type='operand-replay',case=r['case'],tokens=r['tokens'],pair=r['pair'],
                      warmup=False,outputs_equal=True) for r in timed]
        rows.append(dict(type='summary',valid=True,diagnostic_complete=True,operand_replay=True,
            warmed_operand_sweep=warmed, timing_comparison_valid=False,performance_claim=False,
            replays=len(timed),measured_pairs=len(timed)))
        return rows

    def validate(self, rows, warmed=True):
        return self.tool.validate_result(rows,20 if warmed else 1,5 if warmed else 0,
            'cpu-loopback',(1,2,4,8),operand_replay=True)

    def test_full_grids_order_and_single_pair_compatibility(self):
        for warmed in (True,False):
            rows = self.rows(warmed)
            self.validate(rows,warmed)
            for kind in ('pair','operand-replay'):
                selected = [i for i,r in enumerate(rows) if r['type']==kind]
                for mutation in ('missing','duplicate','reordered'):
                    bad=copy.deepcopy(rows)
                    if mutation=='missing': bad.pop(selected[0])
                    elif mutation=='duplicate': bad.insert(selected[0],copy.deepcopy(bad[selected[0]]))
                    else: bad[selected[0]],bad[selected[1]]=bad[selected[1]],bad[selected[0]]
                    with self.subTest(warmed=warmed,kind=kind,mutation=mutation), self.assertRaises(ValueError):
                        self.validate(bad,warmed)
        bad=self.rows(); bad[1]['order']='BA'
        with self.assertRaises(ValueError): self.validate(bad)

    def test_only_legacy_numerical_disagreement_can_continue(self):
        rows=self.rows()
        rows[1]['valid']=False; rows[1]['correctness'].update(**{'pass':False,'max_ratio':1.14})
        rows[-1]['valid']=False
        self.assertFalse(self.validate(rows)['valid'])
        for key,value in (('structural_valid',False),('shared_nonzero',False),('experts_nonzero',False),('hot',4)):
            bad=copy.deepcopy(rows);bad[1][key]=value
            with self.subTest(field=key),self.assertRaises(ValueError):self.validate(bad)
        for key,value in (('finite',False),('max_ratio',float('nan'))):
            bad=copy.deepcopy(rows);bad[1]['correctness'][key]=value
            with self.assertRaises(ValueError):self.validate(bad)
        for arm,key,value in (('A','input_sha256','0'*64),('B','routing_sha256','0'*64),
                              ('B','tokens',2),('B','total_layer_ms',0),('A','output_sha256','bad')):
            bad=copy.deepcopy(rows);bad[1][arm][key]=value
            with self.subTest(arm=arm,field=key),self.assertRaises(ValueError):self.validate(bad)
        bad=self.rows();bad[-2]['outputs_equal']=False
        with self.assertRaises(ValueError):self.validate(bad)

    def test_all_140_profiles_required_before_performance_excludes_warmup(self):
        rows=self.rows()
        for r in rows:
            if r['type']=='pair' and r['warmup']:
                r['A']['total_layer_ms']=10000
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);(path/'stdout.jsonl').write_text('\n'.join(json.dumps(r) for r in rows))
            helper=path/'helper';helper.write_bytes(b'fixture helper')
            good=dict(status='conditional-profile-match',assumption='explicit vendor profile')
            with patch.object(check,'analyze',side_effect=lambda *a:copy.deepcopy(good)) as call:
                result=check.analyze_replays(path,helper)
            self.assertEqual(call.call_count,140)
            self.assertEqual(len({str(c.args[0]) for c in call.call_args_list}),140)
            self.assertFalse(result['numerical_qualification'])
            for case in result['conditional_performance']['cases'].values():
                self.assertEqual((case['AB_count'],case['BA_count']),(10,10))
                self.assertEqual(case['A_ms']['maximum'],1)
                self.assertEqual(case['B_minus_A_ms']['median'],1)
                self.assertEqual(case['B_faster_count'],0)
            reports=[copy.deepcopy(good) for _ in range(140)];reports[-1]['status']='inconclusive'
            with patch.object(check,'analyze',side_effect=reports):
                result=check.analyze_replays(path,helper)
            self.assertNotIn('conditional_performance',result)
            self.assertEqual(result['status'],'inconclusive')

    def test_token_local_omissions_equal_original_full_batch_semantics(self):
        for t in (1,2,4,8):
            d=3
            weighted=[check.f32(((i*37)%101-49)/64) for i in range(10*d*t)]
            shared=[check.f32((i+1)/32) for i in range(d*t)]
            reference=check.compose(weighted,shared,d,t)
            report=check.composition_check(weighted,shared,reference,d,t)
            self.assertEqual(report['status'],'match')
            for token in range(t):
                for slot in range(11):
                    full=check.compose(weighted,shared,d,t,omit=slot)[token*d:(token+1)*d]
                    local=check.compose(weighted[token*10*d:(token+1)*10*d],shared[token*d:(token+1)*d],d,1,omit=slot)
                    self.assertEqual(full,local)
            self.assertEqual(len(report['negative_controls']),t*(11+(t>1)))
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);(path/'manifest.json').write_text(json.dumps(dict(pair_record=dict(tokens=1))))
            with patch.object(check.stages,'load_capture',return_value=dict(pair_record=dict(pair=0))):
                with self.assertRaisesRegex(ValueError,'expected timed record'):
                    check.analyze(path,'unused',True,expected_record=dict(pair=19))


if __name__=='__main__':unittest.main()

"""Focused cardinality, routing, immutable-bank and paired-grid controls."""
import copy
import importlib.util
import json
import math
from pathlib import Path
import random
import struct
import tempfile
import unittest
from unittest.mock import patch
from tests import test_layer7_operand_check as support

TOOLS = support.TOOLS
spec = importlib.util.spec_from_file_location('factorial_check_test',TOOLS/'factorial_check.py')
check = importlib.util.module_from_spec(spec); spec.loader.exec_module(check)
stages = check.stages


def boundary(tokens, hot, d=64):
    resident = stages.HOT if hot==5 else stages.RESIDENT10
    ids = [[stages.HOT[(s+t)%5] if s%2==0 else t*5+s//2 for s in range(10)] for t in range(tokens)]
    # Five original hot IDs remain selected under either placement factor.
    ids = [[v if s%2 else stages.HOT[(s//2+t)%5] for s,v in enumerate(row)] for t,row in enumerate(ids)]
    weights = [(t*10+s+1)/256 for t in range(tokens) for s in range(10)]
    raw = {}
    input_bytes = struct.pack('<'+str(tokens*d)+'f',*([.5]*tokens*d))
    for name in ('A.input','B.input','B.hot.input'): raw[name]=input_bytes
    for arm in ('A','B'):
        raw[arm+'.ids']=struct.pack('<'+str(tokens*10)+'i',*(v for row in ids for v in row))
        raw[arm+'.weights']=struct.pack('<'+str(tokens*10)+'f',*weights)
        for name,n in (('output',tokens*d),('shared',tokens*d),('weighted',tokens*10*d)):
            raw[arm+'.'+name]=bytes(n*4)
    mapping=[]
    for t,row in enumerate(ids):
        counts=dict(hot=0,cold=0); branches={b:([],[]) for b in counts}
        for s,expert in enumerate(row):
            compact=resident.index(expert) if expert in resident else None
            branch='hot' if compact is not None else 'cold'
            mapping.append(dict(token=t,original_slot=s,global_expert=expert,branch=branch,branch_slot=counts[branch],compact_expert=compact))
            counts[branch]+=1; branches[branch][0].append(compact if branch=='hot' else expert);branches[branch][1].append(weights[t*10+s])
        for branch,(bi,bw) in branches.items():
            if not bi:continue
            for name,values,fmt in (('ids',bi,'i'),('weights',bw,'f')):
                key='B.'+branch+'.'+name
                raw[key]=raw.get(key,b'')+struct.pack('<'+str(len(values))+fmt,*values)
    row=dict(type='factorial-pair',factorial_arm='current'+str(hot),tokens=tokens,case='mixed' if tokens==1 else 'mixed-varied-set',pair=0,warmup=False,order='AB',
        ids=ids[0] if tokens==1 else ids,weight_bits=[[f'{v:08x}' for v in struct.unpack('<10I',raw['A.weights'][t*40:(t+1)*40])] for t in range(tokens)],
        input_sha256=stages.digest(input_bytes),routing_sha256=stages.digest(raw['A.ids']+raw['A.weights']),correctness=dict(finite=True,**{'pass':True}))
    if tokens==1:row['weight_bits']=row['weight_bits'][0]
    for arm in ('A','B'):row[arm]=dict(output_sha256=stages.digest(raw[arm+'.output']))
    tensors={}
    for name,data in raw.items():
        count=hot if '.hot.' in name else 10-hot if '.cold.' in name else 10
        shape=[count,tokens,1,1] if name.endswith('.ids') else [1,count,tokens,1] if name.endswith('.weights') else [d,10,tokens,1] if name.endswith('.weighted') else [d,tokens,1,1]
        strides=[4]
        for dim in shape[:-1]:strides.append(strides[-1]*dim)
        integer=name.endswith('.ids')
        tensors[name]=dict(file=name+'.bin',shape=shape,strides_bytes=strides,type_name='i32' if integer else 'f32',ggml_type=26 if integer else 0,byte_length=len(data),sha256=stages.digest(data))
    base=dict(schema='h5-layer7-capture/2',byte_order='little',hot_count=hot,cold_count=10-hot,resident_expert_order=list(resident),
        tensors=tensors,pair_record=row,slot_map=mapping,B_weighted_source='retained-branch-outputs/1',payload_limit_bytes=stages.BASE_LIMIT,payload_bytes=sum(map(len,raw.values())))
    return base,raw,mapping


def capture(root, hot=10):
    native=root/'native'; replay=native/'replays'/('t1-mixed-p0-current'+str(hot)); directory=replay/'stages'
    directory.mkdir(parents=True);(replay/'capture').mkdir()
    bankdir=native/'banks'/('p'+str(hot));bankdir.mkdir(parents=True)
    base,raw,mapping=boundary(1,hot);resident=base['resident_expert_order'];d,f=64,32
    bank_metas={};sources=[];inventory=[]
    for stage in ('gate','up','down'):
        columns,rows=(f,d) if stage=='down' else (d,f);stride=columns//32*34
        bank=struct.pack('<e32b',1/16,*([1]*32))*(len(resident)*rows*columns//32)
        name=stage+'.q8_0.bin';(bankdir/name).write_bytes(bank);source='blk.7.ffn_'+stage+'_exps.weight';source_sha=stage*16
        bank_metas[name]=dict(file=name,shape=[columns,rows,len(resident),1],strides_bytes=[34,stride,stride*rows,stride*rows*len(resident)],byte_length=len(bank),sha256=stages.digest(bank),ggml_type=8,type_name='q8_0',source_tensor=source,source_sha256=source_sha,B_actual_sha256=stages.digest(bank))
        sources.append(dict(source_name=source,source_sha256=source_sha,compact_sha256=stages.digest(bank),ranges=[dict(expert_id=v) for v in resident]))
        inventory.append(dict(name=source,sha256=source_sha))
    identities={}
    for name,value in (('spec.json',dict(layer=7,expert_ids=resident,tensors=sources)),('weights.json',dict(tensors=inventory)),('assigned.txt',None)):
        text=json.dumps(value) if value is not None else 'assigned-test\n'
        for path in (replay/name,bankdir/name):path.write_text(text)
        identities[name]=stages.digest(text.encode())
    base['identities']=identities
    for name,data in raw.items():(replay/'capture'/base['tensors'][name]['file']).write_bytes(data)
    base_text=json.dumps(base);(replay/'capture/manifest.json').write_text(base_text)
    bm=dict(schema='h5-layer7-factorial-banks/1',byte_order='little',hot_count=hot,cold_count=10-hot,resident_expert_order=resident,identities=identities,files=bank_metas)
    banktext=json.dumps(bm);(bankdir/'manifest.json').write_text(banktext)
    m=dict(schema='h5-layer7-factorial-stages/1',byte_order='little',hot_count=hot,cold_count=10-hot,resident_expert_order=resident,performance_claim=False,
        pair_record=base['pair_record'],slot_map=mapping,input_sha256=base['pair_record']['input_sha256'],routing_sha256=base['pair_record']['routing_sha256'],
        payload_limit_bytes=stages.LIMIT,files={},capture_manifest_sha256=stages.digest(base_text.encode()),bank_manifest='../../../banks/p'+str(hot)+'/manifest.json',bank_manifest_sha256=stages.digest(banktext.encode()))
    total=0
    for arm,count in (('A',10),('B',hot)):
        for stage in stages.STAGES:
            width=f if stage in ('gate','up','swiglu') else d;name=arm+'.'+stage+'.bin';data=bytes(width*count*4);(directory/name).write_bytes(data)
            m['files'][name]=dict(shape=[width,count,1,1],strides_bytes=[4,width*4,width*count*4,width*count*4],ggml_type=0,type_name='f32',flags=2,byte_length=len(data),sha256=stages.digest(data));total+=len(data)
    for name,meta in bank_metas.items():m['files'][name]=dict(meta,file='../../../banks/p'+str(hot)+'/'+name)
    m['payload_bytes']=total;(directory/'manifest.json').write_text(json.dumps(m))
    return directory,m,base,raw


class FactorialBoundary(unittest.TestCase):
    def test_both_placements_and_widths_exact_routing_and_no_cold(self):
        for tokens in (1,4):
            for hot in (5,10):
                base,raw,mapping=boundary(tokens,hot)
                check.validate_boundary(base,raw,64,mapping,tokens)
                for name in ('B.hot.ids','B.hot.weights','B.hot.input','B.output'):
                    changed=dict(raw);data=bytearray(changed[name]);data[0]^=1;changed[name]=bytes(data)
                    with self.subTest(tokens=tokens,hot=hot,name=name),self.assertRaises(ValueError):check.validate_boundary(base,changed,64,mapping,tokens)
                if hot==10:
                    self.assertNotIn('B.cold.ids',raw)
                    changed=dict(raw,**{'B.cold.ids':b''})
                    with self.assertRaises(ValueError):check.validate_boundary(base,changed,64,mapping,tokens)
                    changed=copy.deepcopy(base);changed['resident_expert_order']=list(range(10))
                    with self.assertRaises(ValueError):check.validate_boundary(changed,raw,64,mapping,tokens)

    def test_bank_bytes_read_once_and_malformed_reference_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            directory,m,base,raw=capture(Path(temp));cache={};reads=[];original=Path.read_bytes
            def read(path):
                if path.name.endswith('.q8_0.bin'):reads.append(path)
                return original(path)
            with patch.object(Path,'read_bytes',read):
                stages.load_capture(directory,cache);stages.load_capture(directory,cache)
            self.assertEqual(len(reads),3);self.assertEqual(len(cache),3)
            changed=copy.deepcopy(m);changed['files']['down.q8_0.bin']['shape'][2]=10
            (directory/'manifest.json').write_text(json.dumps(changed))
            with self.assertRaises(ValueError):stages.load_capture(directory,cache)
            changed=copy.deepcopy(m);changed['bank_manifest']='../../../../other/manifest.json'
            (directory/'manifest.json').write_text(json.dumps(changed))
            with self.assertRaises(ValueError):stages.load_capture(directory,cache)
            (directory/'manifest.json').write_text(json.dumps(m));bank=(directory/m['files']['gate.q8_0.bin']['file']).resolve();data=bank.read_bytes();bank.write_bytes(data)
            with self.assertRaisesRegex(ValueError,'immutable bank changed'):stages.load_capture(directory,cache)

    def test_binding_binds_entire_factorial_row(self):
        with tempfile.TemporaryDirectory() as temp:
            directory,m,_,_=capture(Path(temp));row=m['pair_record']
            binding=dict(schema='h5-layer7-replay-binding/1',timed_record=row,outputs_equal=True,timed_graph_retention=False,replay_after_all_timed_work=True)
            (directory.parent/'replay-binding.json').write_text(json.dumps(binding))
            self.assertEqual(check.replay_binding(directory,row,[row]),'match')
            changed=copy.deepcopy(row);changed['factorial_arm']='pipeline10'
            self.assertEqual(check.replay_binding(directory,changed,[row]),'mismatch')
            self.assertEqual(check.replay_binding(directory,row,[row,row]),'mismatch')


class FactorialMMVQ(unittest.TestCase):
    setUpClass=classmethod(support.ProjectionControls.setUpClass.__func__)
    tearDownClass=classmethod(support.ProjectionControls.tearDownClass.__func__)

    def test_ten_selected_twenty_six_resident_independent_outputs_and_controls(self):
        for tokens in (1,4):
            rng=random.Random(924+tokens);columns,rows=64,32
            inputs=[rng.randint(-64,64)/64 for _ in range(tokens*columns)]
            for at in range(0,len(inputs),32):inputs[at]=1.
            bank=b''.join(struct.pack('<e32b',1/512,*(rng.randint(-5,5) for _ in range(32))) for _ in range(26*rows*columns//32))
            mapping=[dict(token=t,branch='hot',branch_slot=s,compact_expert=(s*2+t+5)%26,global_expert=stages.RESIDENT10[(s*2+t+5)%26]) for t in range(tokens) for s in range(10)]
            result=[]
            for e in mapping:
                q=self.math.quantize(inputs[e['token']*columns:(e['token']+1)*columns],True)
                for c in range(rows):
                    at=(e['compact_expert']*rows+c)*(columns//32*34);result.append(self.math.dot(bank[at:at+columns//32*34],q,True))
            def run(observed=result,route=mapping,weights=bank):
                return check.mmvq.projection(self.math,weights,inputs,observed,route,columns,rows,tokens,False,10,26)
            report=run();self.assertEqual(report['status'],'match');self.assertTrue(report['sensitive']);self.assertEqual(len(report['zero_expert_controls']),tokens*10)
            down_inputs=[rng.randint(-64,64)/64 for _ in range(tokens*10*columns)]
            for at in range(0,len(down_inputs),32):down_inputs[at]=1.
            down_result=[]
            for e in mapping:
                at=(e['token']*10+e['branch_slot'])*columns;q=self.math.quantize(down_inputs[at:at+columns],True)
                for c in range(rows):
                    start=(e['compact_expert']*rows+c)*(columns//32*34)
                    down_result.append(self.math.dot(bank[start:start+columns//32*34],q,True))
            self.assertEqual(check.mmvq.projection(self.math,bank,down_inputs,down_result,mapping,columns,rows,tokens,True,10,26)['status'],'match')
            for e in mapping:
                changed=result[:];at=(e['token']*10+e['branch_slot'])*rows;changed[at:at+rows]=[0.]*rows
                self.assertEqual(run(observed=changed)['status'],'mismatch')
            with self.assertRaises(ValueError):run(weights=bank[:len(bank)//26*10])
            wrong=copy.deepcopy(mapping);wrong[-1]['compact_expert']=26
            with self.assertRaises(ValueError):run(route=wrong)
            wrong=copy.deepcopy(mapping);wrong[-1]=wrong[-2]
            with self.assertRaises(ValueError):run(route=wrong)


class FactorialGrid(unittest.TestCase):
    def records(self):
        records=[dict(type='factorial-setup',schema='h5-layer7-factorial/1',comparison_mode='cpu-cuda',dimensions=[2560,640,512,10],pairs=20,warmup=5,tokens_list=[1,4],seed=314159,representation='Q8_0',resident_union=list(stages.RESIDENT10),selected_per_token=10,five_remote_resident_count=5,ten_remote_resident_count=26,ten_remote_payload_bytes=135782400,performance_claim=False,small_test=False)]
        for tokens in (1,4):
            for warmup,count in ((True,5),(False,20)):
                for pair in range(count):
                    rotate=(pair if warmup else pair//2)%5
                    order=list(check.ARMS[rotate:]+check.ARMS[:rotate])
                    if not warmup and pair%2:order.reverse()
                    arms={a:dict(order=order.index(a),total_layer_ms=1.+i/10,input_sha256='input',routing_sha256='route',output_sha256='out'+a) for i,a in enumerate(check.ARMS)}
                    arms['cpu']['commands']=0
                    for name in check.ARMS[1:]:
                        hot=10 if name.endswith('10') else 5;payloads=[2560*tokens*4,hot*tokens*4,hot*tokens*4]
                        sets=[dict(hash_begin_ns=2+i,hash_end_ns=3+i,enqueue_ns=6,write_begin_ns=10+i*15,write_end_ns=11+i*15,flush_ns=11+i*15,ack_first_ns=12+i*15,ack_end_ns=13+i*15,payload_bytes=n,wire_bytes=n+50) for i,n in enumerate(payloads)]
                        arms[name].update(hot=hot,cold=10-hot,tokens=tokens,rpc=dict(begin_ns=1,group_enqueue_ns=6,group_dequeue_ns=7,group_end_ns=60,graph_enqueue_ns=70,graph_write_begin_ns=80,graph_write_end_ns=81,get_enqueue_ns=90,get_write_begin_ns=91,get_write_end_ns=92,get_first_byte_ns=93,get_last_byte_ns=94,end_ns=95,graph_uid=hot,sets=sets,tx_payload_bytes=sum(payloads),tx_wire_bytes=sum(payloads)+200,rx_wire_bytes=35+2560*hot*tokens*4,commands=5,set_commands=3,set_acks=3,graph_commands=1,get_commands=1,graph_recompute=1,failed=0,pipeline=int(name.startswith('pipeline'))))
                    records.append(dict(type='factorial-block',tokens=tokens,pair=pair,warmup=warmup,order=order,arms=arms))
                    for arm in check.ARMS[1:]:
                        records.append(dict(type='factorial-pair',factorial_arm=arm,tokens=tokens,pair=pair,warmup=warmup,case='mixed' if tokens==1 else 'mixed-varied-set',
                            order='AB' if order.index('cpu')<order.index(arm) else 'BA',A=arms['cpu'],B=arms[arm],input_sha256='input',routing_sha256='route',ids=['same'],weight_bits=['same'],correctness=dict(finite=True,**{'pass':True})))
        records.extend(dict(type='factorial-replay',tokens=r['tokens'],case=r['case'],pair=r['pair'],factorial_arm=r['factorial_arm'],outputs_equal=True) for r in records[:] if r.get('type')=='factorial-pair' and not r['warmup'])
        records.append(dict(type='factorial-summary',diagnostic_complete=True,replays=160,numerical_qualification=False,performance_claim=False))
        return records

    def test_full_grid_exact_binding_order_and_fixture_controls(self):
        records=self.records();timed,blocks,mode=check.validate_records(records)
        self.assertEqual((len(timed),len(blocks),mode),(160,50,'cpu-cuda'))
        changed=copy.deepcopy(records);changed[2]['B']=dict(changed[2]['B'],total_layer_ms=99)
        with self.assertRaises(ValueError):check.validate_records(changed)
        early=copy.deepcopy(records)
        for block in early:
            if block.get('type')=='factorial-block':
                for name in check.ARMS[1:]:block['arms'][name]['rpc']['get_enqueue_ns']=75
        # GET may queue before GRAPH writes; one dispatcher still sends in order.
        check.validate_records(early)
        late=copy.deepcopy(records)
        for block in late:
            if block.get('type')=='factorial-block':
                block['arms']['current5']['rpc']['get_write_begin_ns']=79
        with self.assertRaises(ValueError):check.validate_records(late)
        changed=copy.deepcopy(records);changed[2]['routing_sha256']='drift'
        with self.assertRaises(ValueError):check.validate_records(changed)
        changed=[r for i,r in enumerate(records) if i!=2]
        with self.assertRaises(ValueError):check.validate_records(changed)
        changed=copy.deepcopy(records)
        for row in changed:
            if row.get('type')=='factorial-block' and not row['warmup']:row['order']=list(check.ARMS)
        with self.assertRaises(ValueError):check.validate_records(changed)
        with self.assertRaises(ValueError):check.validate_records(records,True)

    def test_paired_contrasts_keep_interaction_and_report_small_gains(self):
        records=self.records();_,blocks,_=check.validate_records(records)
        for block in blocks:
            for arm,value in zip(check.ARMS,(10.,9.8,9.7,9.5,9.1)):
                block['arms'][arm]['total_layer_ms']=value
        report=check.performance(blocks)
        self.assertIn('within-session',report['uncertainty'])
        for case in report['cases'].values():
            self.assertAlmostEqual(case['paired_contrasts_ms']['interaction']['median'],-.3)
            self.assertEqual(case['per_width_adoption_screen']['current5']['measured_direction'],'faster')
            self.assertFalse(case['per_width_adoption_screen']['current5']['conservative_adoption_screen'])


if __name__=='__main__':unittest.main()

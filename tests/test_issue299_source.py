"""Exact source/serialized seam: tiny SYNTHETIC GGUF, not Qwen weights."""
from collections import Counter
from dataclasses import asdict
from pathlib import Path
import copy
import hashlib
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from inferswarm.operator import source


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def text(value):
    data = value.encode()
    return struct.pack('<Q', len(data)) + data


def gguf(names, number, total):
    pairs = [('general.architecture', 'synthetic'), ('split.no', number),
             ('split.count', 6), ('split.tensors.count', total)]
    header = b'GGUF' + struct.pack('<IQQ', 3, len(names), len(pairs))
    for key, value in pairs:
        header += text(key) + struct.pack('<I', 8 if isinstance(value, str) else 4)
        header += text(value) if isinstance(value, str) else struct.pack('<I', value)
    offset = 0
    for name in names:
        header += text(name) + struct.pack('<IQIQ', 1, 32, 8, offset)
        offset += 64  # 34-byte Q8_0 tensor followed by alignment padding.
    data = header + b'\0' * (-len(header) % 32)
    for i, name in enumerate(names):
        if i:
            data += b'\0' * (-len(data) % 32)
        data += hashlib.sha256(name.encode()).digest() + b'Q8'
    return header, data


class Q8Source(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='issue299-source-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        names = [[], ['output.weight', 'output_hc_norm.weight'], ['per_layer_token_embd.weight'],
                 ['token_embd.weight', 'blk.1.ple_value.weight'],
                 ['blk.17.ffn_gate_exps.weight'], ['blk.45.ffn_up_exps.weight']]
        total = sum(map(len, names))
        members = []; identities = []; tensors = []
        for number, group in enumerate(names):
            name = f'member-{number}.gguf'
            header, data = gguf(group, number, total)
            (self.root / name).write_bytes(data)
            h = hashlib.sha256(data).hexdigest()
            members.append([name, h, len(data)])
            identities.append([name, 0, len(header)-1, hashlib.sha256(header).hexdigest(), len(data), h])
            _, rows = source.parse_gguf_header(header, object_bytes=len(data), expected_header_sha256=identities[-1][3])
            tensors.extend(dict(asdict(t), member=name) for t in rows)
        self.runtime = self.root / 'runtime'
        self.runtime.write_bytes(b'SYNTHETIC executable identity, never launched')
        self.helper = self.root / 'fnv-helper'
        self.helper.write_text(f'#!{sys.executable}\nimport sys\nh=0xcbf29ce484222325\nfor b in open(sys.argv[1], "rb").read(): h=((h^b)*0x100000001b3)&((1<<64)-1)\nprint(f"{{h:016x}}")\n')
        self.helper.chmod(0o700)
        model = dict(source_id='synthetic/q8', revision='synthetic-revision', representation='Q8_0', members=members)
        meta = dict(schema='gguf-metadata-index/1', source={k:model[k] for k in ('source_id','revision','representation')},
                    header_identities=identities, model_metadata=[['general.architecture','synthetic']],
                    tensors=sorted(tensors, key=lambda t:t['state_id']), provenance={'claim':'synthetic seam only'})
        meta['metadata_digest'] = digest(meta)
        participants = []
        for role, host, bids in [('client','A',['A-cpu']), ('remote','B',['B-cpu','B-gpu'])]:
            bindings = [dict(binding_id=bid, compute_id=bid, memory_id=bid+'-mem', physical_id=bid+'-physical',
                native_selector='CUDA0' if bid.endswith('gpu') else 'CPU', visible_selector='RPC1' if bid.endswith('gpu') else 'RPC0' if role=='remote' else 'CPU',
                runtime_id=bid+'-runtime', evidence_id=bid+'-evidence', evidence_sha256='a'*64) for bid in bids]
            participants.append(dict(participant_id=host, role=role, host_id=host,
                source_path=str(self.root/members[0][0]), runtime_executable=str(self.runtime), runtime_sha256=source.sha(self.runtime),
                source_id=model['source_id'], source_revision=model['revision'], source_representation=model['representation'],
                cache_path=str(self.root/'cache'), bindings=bindings,
                backing=[dict(memory_id=host+'-disk',member=n,sha256=h,size_bytes=s) for n,h,s in members], cache_ranges=[]))
        assignments = []; placements = []
        for bid in ['A-cpu','B-cpu','B-gpu']:
            ts = [t for t in tensors if self.owner(t['state_id']) == bid]
            unit = 'unit-'+bid
            placements.append(dict(unit_id=unit,binding_id=bid,state_ids=[t['state_id'] for t in ts],
                state_ranges=[[t['state_id'],t['member'],t['absolute_offset'],t['encoded_bytes']] for t in ts]))
            assignments.extend(dict(**{k:t[k] for k in ('state_id','member','absolute_offset','encoded_bytes','ggml_type','shape')},
                binding_id=bid,memory_id=bid+'-mem',authority='immutable-public-source/1') for t in ts)
        self.payload = dict(schema='q8-source-plan/1', plan_digest='b'*64, metadata=meta, model=model,
            source_contract='full-source-both-hosts/1', rpc_cache=False, participants=participants,
            assignments=assignments, placement=placements)
        self.payload = json.loads(canonical(self.payload))
        self.client, self.remote = self.payload['participants']

    def owner(self, name):
        return 'B-gpu' if name.startswith(('output', 'blk.45.')) else 'B-cpu' if name.startswith('blk.17.') else 'A-cpu'

    def api(self):
        self.assertTrue(callable(getattr(source, 'verify_q8_role', None)), 'exact Q8 source verifier missing')
        return source.verify_q8_role

    def verify(self, participant=None, payload=None):
        return self.api()(participant or self.remote, payload or self.payload, fnv_binary=str(self.helper))

    def snapshot(self):
        return {str(p.relative_to(self.root)):(hashlib.sha256(p.read_bytes()).hexdigest(),p.stat().st_mode) for p in self.root.rglob('*') if p.is_file()}

    def reject(self, payload, reason, participant=None):
        before = copy.deepcopy(payload); files = self.snapshot()
        with self.assertRaisesRegex(ValueError, reason):
            self.verify(participant or payload['participants'][1], payload)
        self.assertEqual(payload, before)
        self.assertEqual(self.snapshot(), files)

    def cached(self):
        self.payload['rpc_cache'] = True
        directory = self.root/'cache/rpc'; directory.mkdir(parents=True)
        for placement in self.payload['placement']:
            if placement['binding_id']=='A-cpu': continue
            for state, member, offset, length in placement['state_ranges']:
                data = (self.root/member).read_bytes()[offset:offset+length]
                path = self.root/'range'; path.write_bytes(data)
                key = source.fnv(path); path.unlink()
                (directory/key).write_bytes(data)
                self.remote['cache_ranges'].append(dict(state_id=state,member=member,offset=offset,length=length,
                    sha256=hashlib.sha256(data).hexdigest(),cache_key=key,source_id=self.remote['source_id'],
                    revision=self.remote['source_revision'],representation='Q8_0',unit_id=placement['unit_id']))

    def standalone(self, participant=None, payload=None, raw=None):
        envelope = dict(schema='q8-source-verification/1',participant=participant or self.remote,
                        plan_payload=payload or self.payload,fnv_binary=str(self.helper))
        return subprocess.run([sys.executable,'-c',Path(source.__file__).read_text()],
            input=raw if raw is not None else json.dumps(envelope), text=True, capture_output=True, timeout=15,
            cwd=self.root, env={**os.environ,'PYTHONPATH':'','PYTHONDONTWRITEBYTECODE':'1'})

    def test_full_source_and_ranges_on_both_roles_without_cache_effects(self):
        before = copy.deepcopy(self.payload); files = self.snapshot()
        with patch.object(source,'fnv',side_effect=AssertionError('no helper/cache')), patch.object(source,'compile_fnv',side_effect=AssertionError('no compile')):
            for p in self.payload['participants']:
                r = self.verify(p)
                selected = [a for a in self.payload['assignments'] if a['binding_id'] in {b['binding_id'] for b in p['bindings']}]
                self.assertEqual(r['assigned_count'],len(selected))
                self.assertEqual(r['binding_counts'],dict(Counter(a['binding_id'] for a in selected)))
                self.assertEqual(r['verified_members'],[m[0] for m in self.payload['model']['members']])
                self.assertEqual(r['plan_digest'],self.payload['plan_digest'])
                self.assertEqual(r['metadata_digest'],self.payload['metadata']['metadata_digest'])
                self.assertEqual(r['source_contract'],'full-source-both-hosts/1')
                self.assertEqual(r['status'],'VERIFIED-not-consumed')
                self.assertEqual(r['cache_ranges'],0)
                self.assertEqual(len(r['range_identities']),len(selected))
                for row in r['range_identities']:
                    self.assertEqual(row['sha256'],source.sha(self.root/row['member'],row['offset'],row['length']))
                    self.assertFalse(row['cache_eligible'])
        self.assertEqual(self.payload,before); self.assertEqual(self.snapshot(),files)

    def test_coherent_omissions_expert_client_ple_and_output_reach_inventory(self):
        for name in ('blk.17.ffn_gate_exps.weight','per_layer_token_embd.weight','output_hc_norm.weight'):
            p = copy.deepcopy(self.payload)
            p['assignments'] = [a for a in p['assignments'] if a['state_id']!=name]
            for row in p['placement']:
                row['state_ids'] = [n for n in row['state_ids'] if n!=name]
                row['state_ranges'] = [r for r in row['state_ranges'] if r[0]!=name]
            with self.subTest(name=name): self.reject(p,'assignment inventory mismatch',p['participants'][0] if 'embd' in name else None)

    def test_duplicate_and_extra_assignment_inventory(self):
        for extra in (copy.deepcopy(self.payload['assignments'][0]),dict(self.payload['assignments'][0],state_id='invented')):
            p = copy.deepcopy(self.payload); p['assignments'].append(extra)
            self.reject(p,'assignment inventory mismatch')

    def test_wrong_binding_memory_authority_and_descriptor(self):
        for field,value,reason in [('binding_id','A-cpu','assignment ownership mismatch'),('memory_id','wrong','assignment ownership mismatch'),
                ('authority','wrong','assignment authority mismatch'),('member','member-0.gguf','assignment descriptor mismatch'),
                ('absolute_offset',0,'assignment descriptor mismatch'),('encoded_bytes',35,'assignment descriptor mismatch'),
                ('ggml_type',0,'assignment descriptor mismatch'),('shape',[64],'assignment descriptor mismatch')]:
            p=copy.deepcopy(self.payload); a=next(a for a in p['assignments'] if a['binding_id']=='B-cpu'); a[field]=value
            with self.subTest(field=field): self.reject(p,reason)

    def test_model_header_runtime_and_source_byte_drift(self):
        for target,reason in [(self.runtime,'runtime executable SHA-256 mismatch'),(self.root/'member-4.gguf','model member identity mismatch')]:
            old=target.read_bytes(); target.write_bytes(old[:-1]+bytes([old[-1]^1]))
            self.reject(copy.deepcopy(self.payload),reason); target.write_bytes(old)
        p=copy.deepcopy(self.payload); p['metadata']['header_identities'][4][3]='0'*64
        p['metadata']['metadata_digest']=digest({k:v for k,v in p['metadata'].items() if k!='metadata_digest'})
        self.reject(p,'header SHA-256 mismatch')

    def test_authenticated_metadata_and_backing_not_echoed_inventory(self):
        p=copy.deepcopy(self.payload); p['metadata']['tensors'][0]['shape']=[64]
        self.reject(p,'metadata digest mismatch')
        p['metadata']['metadata_digest']=digest({k:v for k,v in p['metadata'].items() if k!='metadata_digest'})
        self.reject(p,'metadata descriptor mismatch')
        p=copy.deepcopy(self.payload); p['participants'][1]['backing'].pop()
        self.reject(p,'full-source backing inventory mismatch')
        p=copy.deepcopy(self.payload); p['source_contract']='assigned-only'
        self.reject(p,'unsupported full-source backing contract')

    def test_cached_remote_every_binding_native_helper_and_readonly(self):
        self.cached(); before=self.snapshot()
        r=self.verify(); self.assertEqual(r['cache_ranges'],4)
        self.assertEqual(r['binding_counts'],{'B-cpu':1,'B-gpu':3})
        self.assertEqual(self.snapshot(),before)
        child=self.standalone(); self.assertEqual(child.returncode,0,child.stderr)
        self.assertEqual(json.loads(child.stdout),r); self.assertEqual(self.snapshot(),before)

    def test_cache_coverage_including_cpu_expert_omitted_duplicate_extra(self):
        self.cached()
        for mode in ('missing','duplicate','extra'):
            p=copy.deepcopy(self.payload); rows=p['participants'][1]['cache_ranges']
            if mode=='missing': rows[:]=[r for r in rows if not r['state_id'].startswith('blk.17.')]
            elif mode=='duplicate': rows.append(copy.deepcopy(rows[0]))
            else: rows.append(dict(rows[0],state_id='invented'))
            with self.subTest(mode=mode): self.reject(p,'cache descriptor inventory mismatch')

    def test_cache_identity_unit_range_hash_length_and_native_key(self):
        self.cached()
        for field,value,reason in [('source_id','wrong','cache source identity mismatch'),('revision','wrong','cache source identity mismatch'),
                ('representation','wrong','cache source identity mismatch'),('unit_id','unit-A-cpu','cache ownership mismatch'),
                ('member','member-0.gguf','cache range mismatch'),('offset',0,'cache range mismatch'),('length',33,'cache range mismatch'),
                ('sha256','0'*64,'source range digest mismatch'),('cache_key','ABC','invalid/duplicate cache key')]:
            p=copy.deepcopy(self.payload); p['participants'][1]['cache_ranges'][0][field]=value
            with self.subTest(field=field): self.reject(p,reason)
        with patch.object(source,'fnv',return_value='0'*16):
            self.reject(copy.deepcopy(self.payload),'cache native lookup key mismatch')
        p=copy.deepcopy(self.payload); r=p['participants'][1]['cache_ranges'][0]; old=r['cache_key']; r['cache_key']='0'*16
        (self.root/'cache/rpc'/r['cache_key']).write_bytes((self.root/'cache/rpc'/old).read_bytes())
        self.reject(p,'cache native lookup key mismatch')

    def test_cache_bad_bytes_size_missing_preserves_provisioned_files(self):
        self.cached(); path=self.root/'cache/rpc'/self.remote['cache_ranges'][0]['cache_key']; data=path.read_bytes()
        for altered in (data[:-1],bytes([data[0]^1])+data[1:]):
            path.write_bytes(altered); self.reject(copy.deepcopy(self.payload),'cache identity mismatch')
        path.unlink(); self.reject(copy.deepcopy(self.payload),'cache identity mismatch')

    def test_explicit_cache_mode_and_selected_participant_must_match(self):
        for value in (None,'false',0):
            p=copy.deepcopy(self.payload); p['rpc_cache']=value; self.reject(p,'explicit boolean RPC cache mode required')
        p=copy.deepcopy(self.payload); del p['rpc_cache']; self.reject(p,'q8 source plan fields')
        p=copy.deepcopy(self.payload); selected=copy.deepcopy(p['participants'][1]); selected['bindings'].pop()
        self.reject(p,'selected participant mismatch',selected)
        self.cached(); p=copy.deepcopy(self.payload); p['rpc_cache']=False
        self.reject(p,'disabled RPC cache has descriptors')

    def test_actual_standalone_program_positive_client_and_structured_refusals(self):
        for participant in self.payload['participants']:
            child=self.standalone(participant); self.assertEqual(child.returncode,0,child.stderr)
            self.assertEqual(json.loads(child.stdout),self.verify(participant))
        p=copy.deepcopy(self.payload); p['assignments'].pop()
        child=self.standalone(payload=p); self.assertNotEqual(child.returncode,0)
        self.assertIn('assignment inventory mismatch',child.stdout+child.stderr)
        self.assertNotIn('SUCCESS',child.stderr)
        child=self.standalone(raw='{"schema":"q8-source-verification/1","schema":"x"}')
        self.assertNotEqual(child.returncode,0); self.assertIn('duplicate JSON key',child.stdout+child.stderr)

    def test_coherent_transport_and_metadata_omission_still_checks_actual_headers(self):
        p=copy.deepcopy(self.payload); name='per_layer_token_embd.weight'
        p['assignments']=[a for a in p['assignments'] if a['state_id']!=name]
        p['metadata']['tensors']=[t for t in p['metadata']['tensors'] if t['state_id']!=name]
        p['metadata']['metadata_digest']=digest({k:v for k,v in p['metadata'].items() if k!='metadata_digest'})
        for row in p['placement']:
            row['state_ids']=[s for s in row['state_ids'] if s!=name]
            row['state_ranges']=[r for r in row['state_ranges'] if r[0]!=name]
        self.reject(p,'actual GGUF tensor inventory mismatch',p['participants'][0])

    def test_strict_wire_rejects_extra_fields_invalid_types_and_helper_path(self):
        mutations=[('extra',42,'q8 source plan fields'),('plan_digest','INVALID','invalid plan SHA-256')]
        for field,value,reason in mutations:
            p=copy.deepcopy(self.payload); p[field]=value; self.reject(p,reason)
        for raw,reason in [('{"schema":"q8-source-verification/1","x":NaN}','nonfinite JSON'),
                           ('{"schema":"q8-source-verification/1","x":1e999}','nonfinite JSON'),
                           ('{"schema":"unknown"}','unsupported source verification schema')]:
            child=self.standalone(raw=raw); self.assertNotEqual(child.returncode,0)
            self.assertIn(reason,child.stdout+child.stderr)
        self.cached()
        envelope=dict(schema='q8-source-verification/1',participant=self.remote,plan_payload=self.payload,fnv_binary=42)
        child=self.standalone(raw=json.dumps(envelope)); self.assertNotEqual(child.returncode,0)
        self.assertIn('FNV helper path',child.stdout+child.stderr)

    def test_standalone_bound_envelope_and_selected_participant_fields(self):
        envelope=dict(schema='q8-source-verification/1',participant=self.remote,plan_payload=self.payload,fnv_binary=None)
        # Tiny over-limit envelope via a test-only lower limit in sent program.
        program=Path(source.__file__).read_text().replace('MAX_Q8_JSON_BYTES = 8 << 20','MAX_Q8_JSON_BYTES = 64')
        child=subprocess.run([sys.executable,'-c',program],input=json.dumps(envelope),text=True,capture_output=True,timeout=15)
        self.assertNotEqual(child.returncode,0); self.assertIn('oversized Q8 verification JSON',child.stdout+child.stderr)
        envelope['participant']=dict(self.remote,unexpected=True)
        child=self.standalone(raw=json.dumps(envelope)); self.assertNotEqual(child.returncode,0)
        self.assertIn('selected participant fields',child.stdout+child.stderr)

    def test_receipt_does_not_alias_payload_or_claim_disabled_cache_reads(self):
        p=copy.deepcopy(self.payload); before=copy.deepcopy(p)
        r=self.verify(payload=p)
        r['binding_expectations'][0]['native_selector']='changed'
        r['member_identities'][0][0]='changed'
        r['source_identity']['source_id']='changed'
        self.assertEqual(p,before)
        self.assertEqual(r['eligible_cache_reads'],0)
        self.assertFalse(r['physical_observation']); self.assertFalse(r['cache_consumed'])

    def test_exact_six_members_including_metadata_only_member(self):
        p=copy.deepcopy(self.payload)
        p['model']['members']=p['model']['members'][1:]
        p['metadata']['header_identities']=p['metadata']['header_identities'][1:]
        p['metadata']['metadata_digest']=digest({k:v for k,v in p['metadata'].items() if k!='metadata_digest'})
        for participant in p['participants']:
            participant['source_path']=str(self.root/'member-1.gguf')
            participant['backing']=participant['backing'][1:]
        self.reject(p,'model member inventory mismatch')

    def test_cache_eligibility_threshold_is_not_consumption(self):
        self.assertTrue(callable(getattr(source,'_q8_cache_eligible',None)),'exact Q8 native cache eligibility missing')
        self.assertFalse(source._q8_cache_eligible(10*1024*1024))
        self.assertTrue(source._q8_cache_eligible(10*1024*1024+1))
        with self.assertRaisesRegex(ValueError,'cache extent'): source._q8_cache_eligible(True)

    def test_exact_metadata_rows_not_swapped_even_with_coherent_transport(self):
        p=copy.deepcopy(self.payload)
        ts=[t for t in p['metadata']['tensors'] if t['member']=='member-1.gguf']
        first,second=ts
        for key in ('relative_offset','absolute_offset'):
            first[key],second[key]=second[key],first[key]
        for a in p['assignments']:
            if a['state_id']==first['state_id']: a['absolute_offset']=first['absolute_offset']
            if a['state_id']==second['state_id']: a['absolute_offset']=second['absolute_offset']
        for row in p['placement']:
            for r in row['state_ranges']:
                if r[0]==first['state_id']: r[2]=first['absolute_offset']
                if r[0]==second['state_id']: r[2]=second['absolute_offset']
        p['metadata']['metadata_digest']=digest({k:v for k,v in p['metadata'].items() if k!='metadata_digest'})
        self.reject(p,'metadata descriptor mismatch')

    def test_legacy_standalone_dispatch_matches_unchanged_verifier(self):
        envelope=dict(participant=self.client,model=self.payload['model'],placement=[],backend={},fnv_binary=None)
        raw=json.dumps(envelope)
        # Legacy json.load accepted duplicate values; versioned Q8 rejects them.
        raw=raw.replace('"fnv_binary": null','"fnv_binary": null, "fnv_binary": null')
        before=self.snapshot(); child=self.standalone(raw=raw)
        self.assertEqual(child.returncode,0,child.stderr)
        self.assertEqual(json.loads(child.stdout),source.verify_role(self.client,self.payload['model'],[],{}))
        self.assertEqual(self.snapshot(),before)

    def test_authentic_plan_wire_projection_joins_all_1224_without_weights(self):
        from tests.test_issue299_q8_plan import config, metadata
        from tests.issue299_fixture import NOW
        from inferswarm.operator.plan import build_plan
        self.assertTrue(callable(getattr(source,'q8_source_payload',None)),'Q8 wire projection missing')
        for selection in ('one-gpu','cpu-only'):
            plan=build_plan(config(selection),now=NOW)
            before=copy.deepcopy(plan)
            payload=source.q8_source_payload(plan)
            self.assertEqual(plan,before)
            self.assertEqual(len(payload['assignments']),1224)
            self.assertEqual(payload['metadata']['metadata_digest'],metadata().metadata_digest)
            self.assertEqual(payload['plan_digest'],plan.digest)
            self.assertIs(payload['rpc_cache'],False)
            rows={t.state_id:t for t in metadata().tensors}
            for a in payload['assignments']:
                t=rows[a['state_id']]
                self.assertEqual((a['member'],a['absolute_offset'],a['encoded_bytes'],a['ggml_type'],tuple(a['shape'])),
                                 (t.member,t.absolute_offset,t.encoded_bytes,t.ggml_type,t.shape))
            self.assertEqual(sum('_exps.weight' in a['state_id'] for a in payload['assignments']),144)
            json.dumps(payload,allow_nan=False)
            with patch.object(source,'sha',side_effect=AssertionError('no weights')):
                source.validate_q8_payload(payload)


if __name__=='__main__': unittest.main()

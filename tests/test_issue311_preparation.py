"""Selective preparation with offline bytes; no models, GPUs or runtime installs."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tracemalloc
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from issue99_artifact_core import (
    AcquisitionError, LocalFileSource, TransferInterrupted, freeze_artifact_record, self_digest,
)
from issue101_fixture import Fixture
from issue101_orchestration import Coordinator
from issue311_preparation import (
    DiskBudget, StreamingArtifactCache, StreamingNode, backing_usage, prepare_participant,
)
from issue311_native_backing import (
    SOURCE_CONTRACT, native_repair_reserve, prepare_q8_participant, project_q8_preparation,
    publish_rpc_views, runtime_identity,
)
from tests import test_issue299_source as q8_fixture

BUDGET = DiskBudget(64 << 20, 0, 32768)


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fixture = Fixture(self.root/'origin')
        self.origin = LocalFileSource(source_id='origin', root=self.fixture.root)
        self.node = StreamingNode('A', StreamingArtifactCache(self.root/'backing'))
        self.coordinator = Coordinator(node_sources=[self.node.descriptor()], origin_sources=[self.origin.descriptor()])

    def freeze(self, numbers=(1, 2), epoch=1):
        return self.coordinator.freeze(self.fixture.plan(epoch, {'P': ('A', numbers)}), self.fixture.resolve)

    def prepare(self, requirements=None, budget=BUDGET, **extra):
        return prepare_participant(coordinator=self.coordinator, requirements=requirements or self.freeze(),
            participant_id='P', node=self.node, sources={'origin':self.origin}, budget=budget, **extra)

    def test_cold_restart_and_delta_only_fetch_missing_ranges(self):
        required = self.freeze()
        cold = self.prepare(required)
        self.assertEqual(cold['acquisition_bytes'], 8)
        self.assertEqual([(r['offset'],r['length']) for r in self.origin.access_log], [(0,4),(4,4)])
        self.assertFalse(cold['cache_consumed']); self.assertFalse(cold['physical_observation'])
        self.node = StreamingNode('A', StreamingArtifactCache(self.node.cache.root))
        self.coordinator = Coordinator(node_sources=[self.node.descriptor()], origin_sources=[self.origin.descriptor()])
        required = self.freeze()
        warm = self.prepare(required)
        self.assertEqual(warm['acquisition_bytes'], 0)
        self.assertEqual(warm['reuse_bytes'], 8)
        delta = self.prepare(self.freeze([2,3], 2))
        self.assertEqual(delta['acquisition_bytes'], 4)
        self.assertEqual(delta['reuse_bytes'], 4)
        self.assertEqual(self.origin.access_log[-1]['offset'], 8)
        self.assertTrue(self.node.cache.has_verified(self.fixture.records[1]))
        self.assertEqual(self.coordinator.bytes_observed, 0)

    def test_fresh_process_reuses_backing_without_source_files(self):
        required = self.freeze(); self.prepare(required)
        document = self.root/'inputs.json'
        document.write_text(json.dumps(dict(plan=self.fixture.plan(1, {'P':('A',[1,2])}),
                                          records=list(self.fixture.records.values()))))
        (self.fixture.root/'coefficients.bin').unlink()
        code = """
import json, sys
from pathlib import Path
from issue101_orchestration import Coordinator
from issue99_artifact_core import LocalFileSource
from issue311_preparation import *
v=json.loads(Path(sys.argv[1]).read_text())
n=StreamingNode('A',StreamingArtifactCache(Path(sys.argv[2])))
s=LocalFileSource(source_id='origin',root=Path(sys.argv[3]))
c=Coordinator(node_sources=[n.descriptor()],origin_sources=[s.descriptor()])
r=c.freeze(v['plan'],lambda cls,sid:[x for x in v['records'] if sid in x['satisfies_logical_state_ids']])
result=prepare_participant(coordinator=c,requirements=r,participant_id='P',node=n,sources={'origin':s},budget=DiskBudget(1<<20,0,32768))
assert not s.access_log and result['acquisition_bytes']==0
print(result['status'])
"""
        env = dict(os.environ, PYTHONPATH=str(ROOT/'scripts')+os.pathsep+str(ROOT), PYTHONDONTWRITEBYTECODE='1')
        result = subprocess.run([sys.executable,'-c',code,str(document),str(self.node.cache.root),str(self.fixture.root)],
                                env=env, capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('VERIFIED_BACKING-not-consumed',result.stdout)

    def test_interruption_resumes_exact_bound_prefix_and_rejects_corrupt_prefix(self):
        required = self.freeze([1]); original_read = self.origin.read
        def interrupted(origin, offset, length):
            raise TransferInterrupted('fixture interruption', original_read(origin,offset,length)[:2])
        with patch.object(self.origin,'read',side_effect=interrupted):
            result = self.prepare(required)
        self.assertEqual(result['status'],'INTERRUPTED')
        record = self.fixture.records[1]
        self.assertFalse(self.node.cache.has_verified(record))
        self.assertEqual(self.node.inventory()['verified_objects'],[])
        result = self.prepare(required)
        self.assertEqual(result['acquisition_bytes'],2)
        self.assertEqual(self.origin.access_log[-1]['offset'],2)
        # Another requirement has an interrupted but damaged prefix. Final digest
        # rejects it and #99 discards only this owned partial, never publishes it.
        required = self.freeze([2],2)
        with patch.object(self.origin,'read',side_effect=interrupted): self.prepare(required)
        record = self.fixture.records[2]
        self.node.cache._part_path(record['artifact_id']).write_bytes(b'XX')
        with self.assertRaisesRegex(AcquisitionError,'INTEGRITY_DIGEST_MISMATCH'): self.prepare(required)
        self.assertFalse(self.node.cache.has_verified(record))
        self.assertFalse(self.node.cache._part_path(record['artifact_id']).exists())
        self.assertEqual(self.prepare(required)['acquisition_bytes'],4)

    def test_corrupt_truncated_backing_refused_preserved_and_explicit_recovery(self):
        required = self.freeze([1]); self.prepare(required)
        record = self.fixture.records[1]; path = self.node.cache.verified_path(record)
        for damaged in (b'xxxx',b'x'):
            path.write_bytes(damaged); before = len(self.origin.access_log)
            with self.assertRaisesRegex(AcquisitionError,'CACHE_OBJECT_TAMPERED'): self.prepare(required)
            self.assertEqual(path.read_bytes(),damaged)
            self.assertEqual(len(self.origin.access_log),before)
            # Explicit fixture/operator recovery preserves damage in the same
            # charged directory; preparation itself never deletes final content.
            path.rename(self.node.cache.root/('damage-'+str(len(damaged))))
            self.assertEqual(self.prepare(required)['acquisition_bytes'],4)

    def test_budget_counts_foreign_history_partials_and_free_headroom_before_read(self):
        foreign = self.node.cache.root/'unrelated-history'; foreign.write_bytes(b'H'*(128<<10))
        required = self.freeze()
        with self.assertRaisesRegex(ValueError,'disk budget'):
            self.prepare(required,DiskBudget(128<<10,0,32768))
        self.assertEqual(self.origin.access_log,[])
        with patch('issue311_preparation.shutil.disk_usage',return_value=type('Usage',(),{'free':100})()):
            with self.assertRaisesRegex(ValueError,'free headroom'):
                self.prepare(required,DiskBudget(1<<20,100,32768))
        self.assertEqual(self.origin.access_log,[])
        self.assertEqual(foreign.read_bytes(),b'H'*(128<<10))

    def test_stale_requirement_and_wrong_revision_fail_before_reads(self):
        stale = self.freeze(); self.freeze([3],2)
        with self.assertRaisesRegex(AcquisitionError,'RECONCILIATION_MISMATCH'): self.prepare(stale)
        records = copy.deepcopy(self.fixture.records)
        records[1]['provenance']['revision']='wrong'
        records[1]['artifact_id']=self_digest(records[1],identity_field='artifact_id')
        with self.assertRaisesRegex(AcquisitionError,'PROVENANCE_IDENTITY_MISMATCH'):
            self.coordinator.freeze(self.fixture.plan(3,{'P':('A',[1])}),lambda cls,sid:[records[1]])
        self.assertEqual(self.origin.access_log,[])

    def test_short_and_oversized_source_reads_never_publish(self):
        required = self.freeze([1])
        for data in (b'',b'X'*5):
            with patch.object(self.origin,'read',return_value=data):
                with self.assertRaisesRegex(AcquisitionError,'SOURCE_OBJECT_UNAVAILABLE'): self.prepare(required)
            self.assertFalse(self.node.cache.has_verified(self.fixture.records[1]))

    def test_streamed_finalize_and_inventory_do_not_read_full_objects(self):
        data=b'S'*(8<<20); path=self.fixture.root/'large'; path.write_bytes(data+b'X')
        record=freeze_artifact_record(kind='byte_range',content=data,**self.fixture.plan(1,{})['model'],
            satisfies_logical_state_ids=['coefficient.1'],requirement_class='assigned_logical_state',
            origin=dict(source_object='large',source_object_digest='sha256:'+hashlib.sha256(data+b'X').hexdigest(),
                        source_object_length=len(data)+1,byte_start=0,byte_end=len(data)))
        required=self.coordinator.freeze(self.fixture.plan(1,{'P':('A',[1])}),lambda cls,sid:[record])
        del data
        tracemalloc.start()
        try:
            with patch.object(Path,'read_bytes',side_effect=AssertionError('whole object read')):
                self.prepare(required); self.node.inventory()
            _,peak=tracemalloc.get_traced_memory()
        finally: tracemalloc.stop()
        self.assertLess(peak,3<<20,peak)
        self.assertLessEqual(max(r['length'] for r in self.origin.access_log),65536)


class Q8ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = q8_fixture.Q8Source(); self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.fixture.cached()
        self.payload=self.fixture.payload; self.root=self.fixture.root
        self.node=StreamingNode('B',StreamingArtifactCache(self.root/'selective-worker'))
        self.source=LocalFileSource(source_id='origin',root=self.root)
        self.runtime=runtime_identity(self.fixture.runtime,self.fixture.remote['runtime_sha256'])

    def prepare(self, payload=None, **kwargs):
        return prepare_q8_participant(payload=payload or self.payload,epoch=1,
            executable=self.fixture.runtime,executable_sha256=self.fixture.remote['runtime_sha256'],
            node=self.node,origin_source=self.source,budget=BUDGET,**kwargs)

    def test_exact_assigned_descriptor_metadata_and_no_unrelated_acquisition(self):
        projection=project_q8_preparation(self.payload,epoch=1,runtime=self.runtime)
        meta=projection['metadata']
        assigned=[a for a in self.payload['assignments'] if a['binding_id'].startswith('B')]
        self.assertEqual({a['state_id'] for a in meta['tensors']},{a['state_id'] for a in assigned})
        self.assertEqual(set(meta),{'source_contract','source_identity','participant_id','node_id',
                                   'metadata_authority_digest','runtime','tensors'})
        self.assertNotIn('token_embd.weight',json.dumps(meta))
        self.assertNotIn('header_identities',meta)
        receipt=self.prepare()
        self.assertEqual(receipt['source_contract'],SOURCE_CONTRACT)
        self.assertFalse(receipt['q8_runner_integrated'])
        self.assertEqual(sorted((r['source_object'],r['offset'],r['length']) for r in self.source.access_log),
            sorted((a['member'],a['absolute_offset'],a['encoded_bytes']) for a in assigned))
        self.assertEqual(len(list((self.node.cache.root/'objects').iterdir())),len(assigned)+1)
        # The worker stores no full GGUF, tokenizer or model index. Tiny tensor
        # backing is retained but below the native hash-hit threshold.
        self.assertFalse((self.node.cache.root/'rpc').exists())
        self.assertTrue(all(not r['native_hash_hit_eligible'] for r in receipt['backend_view']))
        self.assertEqual(self.prepare()['acquisition_bytes'],0)

    def test_wrong_runtime_quantization_range_digest_and_native_key_refused(self):
        with self.assertRaisesRegex(ValueError,'runtime executable identity'):
            prepare_q8_participant(payload=self.payload,epoch=1,executable=self.fixture.runtime,
                executable_sha256='0'*64,node=self.node,origin_source=self.source,budget=BUDGET)
        for field,value in [('representation','wrong'),('offset',1),('sha256','0'*64),('cache_key','0'*16)]:
            payload=copy.deepcopy(self.payload); payload['participants'][1]['cache_ranges'][0][field]=value
            with self.subTest(field=field),self.assertRaises((ValueError,AcquisitionError)):
                self.prepare(payload)
        self.assertFalse(self.node.cache.root.joinpath('rpc').exists())

    def test_old_runner_keeps_full_source_contract_and_patch_is_explicit(self):
        from inferswarm.operator.source import validate_q8_payload
        payload=copy.deepcopy(self.payload); payload['source_contract']=SOURCE_CONTRACT
        with self.assertRaisesRegex(ValueError,'full-source backing contract'): validate_q8_payload(payload)
        runtime=copy.deepcopy(self.runtime); runtime['rpc_major']=6
        with self.assertRaisesRegex(ValueError,'runtime contract'):
            project_q8_preparation(self.payload,epoch=1,runtime=runtime)

    def test_cache_key_is_never_content_authority(self):
        projection=project_q8_preparation(self.payload,epoch=1,runtime=self.runtime)
        self.prepare(); record,key=projection['native_ranges'][0]
        with self.assertRaisesRegex(ValueError,'key/content mismatch'):
            publish_rpc_views(self.node.cache,[(record,'0'*16)],budget=BUDGET)

    def test_repair_reserve_deduplicates_content_and_counts_durable_plus_peak(self):
        projection=project_q8_preparation(self.payload,epoch=1,runtime=self.runtime)
        record=copy.deepcopy(projection['native_ranges'][0][0])
        # Descriptor-only budget calculation: no source bytes are read.
        size=12<<20
        record.update(length=size)
        record['origin'].update(byte_start=0,byte_end=size,source_object_length=size+1)
        record['artifact_id']=self_digest(record,identity_field='artifact_id')
        other=copy.deepcopy(record)
        other['satisfies_logical_state_ids']=['another-assigned-state']
        other['artifact_id']=self_digest(other,identity_field='artifact_id')
        ranges=[(record,'a'*16),(other,'a'*16)]
        self.assertEqual(native_repair_reserve(ranges),2*size+32768)
        with self.assertRaisesRegex(ValueError,'native durable repair.*reserve'):
            publish_rpc_views(self.node.cache,ranges,budget=DiskBudget(64<<20,0,size+16384))
        self.assertFalse((self.node.cache.root/'rpc').exists())


if __name__=='__main__': unittest.main()

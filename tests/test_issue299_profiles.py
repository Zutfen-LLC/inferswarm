"""Offline SYNTHETIC profile/config contracts; no physical authority."""
import copy
import importlib
import unittest
from dataclasses import FrozenInstanceError
from unittest.mock import patch

from inferswarm.operator import config
from tests.issue299_fixture import NOW, profile_digest, synthetic_config, synthetic_profiles
from tests.test_issue268_operator_plan import sample


class ProfilePositiveTests(unittest.TestCase):
    def profiles(self):
        try:
            return importlib.import_module('inferswarm.operator.profiles')
        except ModuleNotFoundError:
            self.fail('generic profile snapshot API is missing')

    def test_snapshot_frozen_and_digest_bound(self):
        raw = synthetic_profiles()
        snapshot = self.profiles().parse_profiles(raw)
        self.assertEqual(snapshot.digest, profile_digest(raw))
        self.assertEqual(len(snapshot.hosts), 2)
        self.assertEqual(len(snapshot.compute_units), 3)
        self.assertEqual(len(snapshot.memory_resources), 5)
        with self.assertRaises(FrozenInstanceError): snapshot.digest = 'bad'
        with self.assertRaises(TypeError): snapshot.evidence[0].dependencies[0] = ('bad', 'bad')
        raw['hosts'][0]['boot_epoch'] = 'mutated'
        self.assertEqual(snapshot.hosts[0].boot_epoch, 'boot-A')

    def test_inventory_reordering_preserves_normalized_digest(self):
        raw = synthetic_profiles()
        expected = self.profiles().parse_profiles(raw)
        for key in ('hosts', 'compute_units', 'memory_resources', 'links', 'runtime_capabilities', 'evidence'):
            raw[key].reverse()
        self.assertEqual(expected, self.profiles().parse_profiles(raw))

    def test_two_participants_three_bindings_one_remote_endpoint(self):
        parsed = config.parse_config(synthetic_config(), now=NOW, profile_mode='replay')
        self.assertEqual(len(parsed.participants), 2)
        remote = next(p for p in parsed.participants if p.role == 'remote')
        self.assertEqual(remote.rpc_endpoint, 'synthetic-B:5000')
        self.assertEqual(tuple(b.compute_id for b in remote.bindings), ('B-cpu','B-gpu'))
        self.assertEqual(remote.runtime_sha256, 'b'*64)
        self.assertEqual(parsed.selection, 'one-gpu')
        self.assertEqual(parsed.profiles.digest, parsed.profiles.snapshot.digest)
        self.assertEqual(dict(parsed.strategy_options)['opaque'], (('test',(1,2)),))

    def test_parse_has_no_host_model_transport_or_file_side_effects(self):
        raw = synthetic_config()
        before = copy.deepcopy(raw)
        with patch('pathlib.Path.open', side_effect=AssertionError('unexpected filesystem read')), patch('subprocess.Popen', side_effect=AssertionError('unexpected transport')):
            config.parse_config(raw, now=NOW, profile_mode='replay')
        self.assertEqual(raw, before)

    def test_legacy_participant_order_and_bytes_unchanged(self):
        raw = sample()
        first = config.parse_config(raw)
        raw['participants'].reverse()
        second = config.parse_config(raw)
        self.assertEqual(first.participants, tuple(reversed(second.participants)))
        self.assertEqual(first.runtime_bindings, tuple(reversed(second.runtime_bindings)))
        self.assertIsInstance(first, config.OperatorConfig)


class StrictProfileTests(unittest.TestCase):
    def parse(self, value, **kw):
        return config.parse_config(value, now=kw.pop('now', NOW), profile_mode=kw.pop('profile_mode', 'replay'), **kw)

    def reject(self, value, reason, **kw):
        # The complete original fixture succeeds before every one-axis mutation.
        self.parse(synthetic_config())
        before = copy.deepcopy(value)
        with patch('pathlib.Path.open', side_effect=AssertionError('unexpected filesystem side effect')), patch('subprocess.Popen', side_effect=AssertionError('unexpected transport')):
            with self.assertRaisesRegex(ValueError, reason): self.parse(value, **kw)
        self.assertEqual(value, before)

    def mutated_profile(self, mutate, *, reseal=True):
        from tests.issue299_fixture import reseal_profiles
        value = synthetic_profiles(); mutate(value)
        if reseal: reseal_profiles(value)
        result = synthetic_config()
        result['profiles'] = {'snapshot':value, 'digest':profile_digest(value)}
        for participant in result['participants']:
            for binding in participant['bindings']:
                e=next((e for e in value['evidence'] if e['evidence_id']==binding['evidence_id']),None)
                if e is not None: binding['evidence_sha256']=e['sha256']
        return result

    def test_missing_profile_categories(self):
        for group in ('hosts','compute_units','memory_resources','links','runtime_capabilities'):
            with self.subTest(group=group):
                value = synthetic_config(); snapshot=value['profiles']['snapshot']; snapshot[group] = []
                value['profiles']['digest']=profile_digest(snapshot)
                self.reject(value, 'missing '+group+' profile')

    def test_missing_referenced_profiles(self):
        for group, index, reason in (('hosts',0,'missing host profile'),('compute_units',0,'compute profile coverage'),('memory_resources',0,'missing memory profile'),('links',0,'missing links profile'),('runtime_capabilities',0,'runtime profile coverage')):
            with self.subTest(group=group):
                value = synthetic_profiles(); row=value[group].pop(index)
                value['evidence'] = [e for e in value['evidence'] if e['evidence_id'] != row['evidence_id']]
                self.reject(synthetic_config(value), reason)

    def test_missing_evidence(self):
        value = synthetic_profiles(); value['evidence'].pop()
        self.reject(synthetic_config(value), 'missing evidence')

    def test_evidence_hash_substitution(self):
        value = self.mutated_profile(lambda p: p['evidence'][0].update(sha256='f'*64), reseal=False)
        self.reject(value, 'evidence SHA-256 mismatch')

    def test_resource_payload_substitution(self):
        value = self.mutated_profile(lambda p: p['memory_resources'][0].update(available_bytes=1), reseal=False)
        self.reject(value, 'evidence payload mismatch')

    def test_profile_digest_substitution(self):
        value=synthetic_config(); value['profiles']['digest']='f'*64
        self.reject(value, 'profile normalized digest mismatch')

    def test_physical_identity_alias(self):
        for group in ('hosts','compute_units','memory_resources'):
            with self.subTest(group=group):
                self.reject(self.mutated_profile(lambda p: p[group][1].update(physical_id=p[group][0]['physical_id'])), 'physical identity alias')

    def test_duplicate_memory_identity(self):
        self.reject(self.mutated_profile(lambda p:p['memory_resources'].append(copy.deepcopy(p['memory_resources'][0]))), 'duplicate memory_id')

    def test_duplicate_evidence_identity(self):
        value=synthetic_profiles(); value['evidence'].append(copy.deepcopy(value['evidence'][0]))
        self.reject(synthetic_config(value), 'duplicate evidence_id')

    def test_orphan_evidence(self):
        from tests.issue299_fixture import sha
        value=synthetic_profiles(); row=copy.deepcopy(value['evidence'][0]); row['evidence_id']='orphan'
        row['sha256']=sha({k:v for k,v in row.items() if k!='sha256'}); value['evidence'].append(row)
        self.reject(synthetic_config(value), 'unreferenced evidence')

    def test_unsupported_backend(self):
        self.reject(self.mutated_profile(lambda p:p['compute_units'][0].update(backend='unknown-backend')), 'unsupported backend')

    def test_unknown_shared_ram_domain(self):
        self.reject(self.mutated_profile(lambda p:p['compute_units'][1]['memory_ids'].append('unidentified-shared-ram')), 'missing memory profile')

    def test_memory_capacity_integer_finite_bounds(self):
        for field,value in (('total_bytes',True),('total_bytes',-1),('total_bytes',float('inf')),('available_bytes',-1),('available_bytes',1000001)):
            with self.subTest(field=field,value=value):
                raw=synthetic_profiles(); raw['memory_resources'][0][field]=value
                # Invalid nonfinite values cannot have a canonical digest.
                data=synthetic_config(); data['profiles']['snapshot']=raw
                self.reject(data, 'memory capacity')

    def test_link_finite_positive_measurements(self):
        for field,value in (('latency_seconds',float('nan')),('latency_seconds',-1),('throughput_bytes_per_second',True),('throughput_bytes_per_second',0)):
            with self.subTest(field=field,value=value):
                data=synthetic_config(); data['profiles']['snapshot']['links'][0][field]=value
                self.reject(data, 'link measurement')

    def test_unknown_profile_keys(self):
        for target in ('hosts','evidence'):
            with self.subTest(target=target):
                value=synthetic_config(); value['profiles']['snapshot'][target][0]['unexpected']=1
                self.reject(value, 'fields must be exactly')

    def test_future_expired_stale_evidence(self):
        for changes,reason in (({'observed_at':'2026-01-02T12:00:01Z'},'future evidence'),({'expires_at':'2026-01-02T12:00:00Z'},'expired evidence'),({'observed_at':'2026-01-02T09:59:59Z'},'stale evidence')):
            with self.subTest(reason=reason):
                self.reject(self.mutated_profile(lambda p:p['evidence'][0].update(changes)),reason)

    def test_utc_expiry_and_max_age_boundaries(self):
        for changes in ({'observed_at':'2026-01-02T12:00:00Z'}, {'observed_at':'2026-01-02T10:00:00+00:00','expires_at':'2026-01-02T12:00:00.000001Z'}):
            self.parse(self.mutated_profile(lambda p:p['evidence'][0].update(changes)))
        for timestamp in ('2026-01-02T11:00:00','2026-01-02T12:00:00+01:00','not-time'):
            self.reject(self.mutated_profile(lambda p:p['evidence'][0].update(observed_at=timestamp)), 'UTC timestamp')
        self.reject(self.mutated_profile(lambda p:p['evidence'][0].update(expires_at='2026-01-02T11:00:00Z')), 'expiry must follow observation')

    def test_missing_and_wrong_dependency_epochs(self):
        for field in ('host:A:boot_epoch','host:A:topology_epoch'):
            for missing in (False, True):
                def mutate(p):
                    deps=p['evidence'][0]['dependencies']
                    if missing: deps.pop(field)
                    else: deps[field]='wrong'
                with self.subTest(field=field,missing=missing):
                    self.reject(self.mutated_profile(mutate),'dependency mismatch: '+field)

    def test_runtime_model_workload_dependency_scope(self):
        fields=('runtime:runtime-A-cpu:binary_sha256','runtime:runtime-A-cpu:source_revision','runtime:runtime-A-cpu:build_id','runtime:runtime-A-cpu:driver','runtime:runtime-A-cpu:backend','runtime:runtime-A-cpu:route','model:source_id','model:revision','model:representation','workload:digest')
        for field in fields:
            with self.subTest(field=field):
                def mutate(p):
                    e=next(e for e in p['evidence'] if e['evidence_id']=='synthetic-runtime-A-cpu')
                    e['dependencies'][field]='wrong'
                self.reject(self.mutated_profile(mutate),'dependency mismatch: '+field)

    def test_empty_provenance_and_unknown_dependencies(self):
        self.reject(self.mutated_profile(lambda p:p['evidence'][0].update(provenance={})), 'provenance must be nonempty')
        self.reject(self.mutated_profile(lambda p:p['evidence'][0]['dependencies'].update(unresolved='unknown')), 'unknown dependency: unresolved')

    def test_estimated_unknown_and_unmeasured_link_block(self):
        self.reject(self.mutated_profile(lambda p:p['evidence'][0].update(evidence_class='unknown')), 'evidence class not admitted')
        def mutate(p):
            next(e for e in p['evidence'] if e['evidence_id']=='synthetic-A-B')['evidence_class']='calculated'
        self.reject(self.mutated_profile(mutate), 'link requires measured evidence')

    def test_synthetic_and_replay_never_authorize_live(self):
        self.reject(synthetic_config(), 'non-live evidence', profile_mode='live')
        self.reject(self.mutated_profile(lambda p:p['evidence'][0].update(source_scope='replay')), 'non-live evidence', profile_mode='live')

    def test_binding_evidence_identity_substitution(self):
        value=synthetic_config(); value['participants'][1]['bindings'][0]['evidence_sha256']='e'*64
        self.reject(value,'binding evidence identity mismatch')

    def test_binding_physical_identity_and_affinity(self):
        for changes,reason in (({'physical_id':'wrong'},'binding physical identity mismatch'),({'memory_id':'A-ram'},'binding memory affinity mismatch'),({'runtime_id':'runtime-A-cpu'},'binding runtime context mismatch')):
            value=synthetic_config(); value['participants'][1]['bindings'][0].update(changes)
            self.reject(value,reason)

    def test_duplicate_bindings_compute_ids_and_selectors(self):
        for field in ('binding_id','compute_id','native_selector','visible_selector'):
            value=synthetic_config(); rows=value['participants'][1]['bindings']; rows[1][field]=rows[0][field]
            self.reject(value,'duplicate binding '+field)

    def test_participant_epoch_source_runtime_mismatch(self):
        for field,reason in (('boot_epoch','participant boot epoch mismatch'),('topology_epoch','participant topology epoch mismatch'),('source_revision','participant source identity mismatch'),('runtime_sha256','binding runtime binary mismatch')):
            value=synthetic_config(); value['participants'][0][field]='f'*64
            self.reject(value,reason)

    def test_config_unknown_keys_and_unsupported_dispatch(self):
        value=synthetic_config(); value['extra']=1; self.reject(value,'config/3.*exactly')
        value=synthetic_config(); value['strategy_id']='unsupported/1'; self.reject(value,'unsupported strategy_id')
        value=synthetic_config(); value['selection']='automatic'; self.reject(value,'unsupported explicit selection')
        value=synthetic_config(); value['schema']='operator-config/4'; self.reject(value,'unsupported schema')

    def test_invalid_policy_workload_request_and_opaque_values(self):
        for group,field,value,reason in (('policy','max_age_seconds',True,'max_age_seconds'),('workload','context',True,'context'),('workload','batch',-1,'batch'),('request','seed',True,'request'),('request','temperature',float('inf'),'request')):
            raw=synthetic_config(); raw[group][field]=value; self.reject(raw,reason)
        raw=synthetic_config(); raw['strategy_options']['opaque']=-1; self.reject(raw,'negative opaque integer')
        raw=synthetic_config(); raw['strategy_options']['opaque']=float('nan'); self.reject(raw,'nonfinite opaque number')
        raw=synthetic_config(); raw['strategy_options']['opaque']=set(); self.reject(raw,'unsupported opaque value')

    def test_duplicate_missing_policy_memory_and_backing_bounds(self):
        value=synthetic_config(); value['policy']['memory_limits'].append(copy.deepcopy(value['policy']['memory_limits'][0]))
        self.reject(value,'duplicate memory limit')
        value=synthetic_config(); value['policy']['memory_limits'].pop(); self.reject(value,'memory policy coverage')
        value=synthetic_config(); value['participants'][0]['backing'][0]['sha256']='f'*64; self.reject(value,'backing source identity mismatch')
        value=synthetic_config(); value['participants'][0]['backing'][0]['memory_id']='B-disk'; self.reject(value,'backing memory domain mismatch')

    def test_placement_binding_not_array_index_and_exact_ranges(self):
        value=synthetic_config(); value['placement'][0]['binding_id']='0'; self.reject(value,'unknown placement binding')
        value=synthetic_config(); value['placement'][0]['state_ids']=['opaque']; self.reject(value,'state ranges must describe every state exactly once')
        value=synthetic_config(); value['placement'][0].update(state_ids=['opaque'],state_ranges=[dict(state_id='opaque',member='member.gguf',offset=1000,length=1)])
        self.reject(value,'state range outside source member bounds')

    def test_profile_config_deep_immutability_and_order_normalization(self):
        raw=synthetic_config(); parsed=self.parse(raw)
        raw['participants'].reverse()
        for row in raw['participants']: row['bindings'].reverse(); row['backing'].reverse()
        raw['placement'].reverse(); raw['policy']['memory_limits'].reverse()
        self.assertEqual(parsed,self.parse(raw))
        raw['strategy_options']['opaque']['test'].append(3)
        self.assertEqual(dict(parsed.strategy_options)['opaque'],(('test',(1,2)),))
        with self.assertRaises(FrozenInstanceError): parsed.participants[0].bindings[0].memory_id='wrong'

    def test_freshness_revalidated_later_and_live_clock_is_not_replay_clock(self):
        from datetime import timedelta
        parsed=self.parse(synthetic_config())
        reasons=config.validate_config_profiles(parsed,now=NOW+timedelta(hours=2),profile_mode='replay')
        self.assertTrue(any('expired evidence' in r for r in reasons))
        reasons=config.validate_config_profiles(parsed)  # actual UTC clock; synthetic always denied
        self.assertTrue(any('non-live evidence' in r for r in reasons))

    def test_opaque_object_array_shapes_are_unambiguous(self):
        from tests.issue299_fixture import reseal_profiles, sha
        for cache in ({'value': {}}, {'value': []}, {'value': [['key',1]]}, {'value': {'key':1}}):
            raw=synthetic_config(); raw['workload']['cache_settings']=cache
            workload_digest=sha(raw['workload'])
            for evidence in raw['profiles']['snapshot']['evidence']:
                if 'workload:digest' in evidence['dependencies']: evidence['dependencies']['workload:digest']=workload_digest
            reseal_profiles(raw['profiles']['snapshot']); raw['profiles']['digest']=profile_digest(raw['profiles']['snapshot'])
            parsed=self.parse(raw)
            subject=config.profile_subject(parsed,profile_mode='replay')
            self.assertEqual(dict(subject.dependencies)['workload:digest'],workload_digest)

    def test_frozen_strategy_object_and_pair_array_canonical_forms_differ(self):
        profiles=importlib.import_module('inferswarm.operator.profiles')
        first=self.parse(synthetic_config())
        raw=synthetic_config(); raw['strategy_options']={'opaque':[['test',[1,2]]]}
        second=self.parse(raw)
        self.assertNotEqual(profiles.canonical(first.strategy_options),profiles.canonical(second.strategy_options))
        self.assertEqual(profiles.canonical(profiles.freeze({'value':{}})),b'{"value":{}}')

    def test_runtime_same_endpoint_source_and_build_context_consistent(self):
        for field in ('source_revision','build_id'):
            def mutate(p):
                r=next(r for r in p['runtime_capabilities'] if r['runtime_id']=='runtime-B-gpu'); r[field]='different'
                e=next(e for e in p['evidence'] if e['evidence_id']==r['evidence_id']); e['dependencies']['runtime:runtime-B-gpu:'+field]='different'
            self.reject(self.mutated_profile(mutate),'endpoint runtime '+field+' mismatch')

    def test_invalid_evidence_class_types_reject_as_valueerror(self):
        raw=synthetic_config(); raw['profiles']['snapshot']['evidence'][0]['evidence_class']=[]
        self.reject(raw,'unsupported evidence class')

    def test_link_path_protocol_dependency_mismatch(self):
        for field in ('path','protocol'):
            self.reject(self.mutated_profile(lambda p:p['links'][0].update({field:'different'})), 'dependency mismatch: link:A-B:'+field)

    def test_clock_type_and_replay_explicit_clock(self):
        from datetime import datetime, timedelta, timezone
        for clock in (datetime(2026,1,2,12),NOW.astimezone(timezone(timedelta(hours=1))),'2026-01-02T12:00:00Z'):
            self.reject(synthetic_config(),'timezone-aware UTC',now=clock)
        with self.assertRaisesRegex(ValueError,'replay requires explicit as-of clock'):
            config.parse_config(synthetic_config(),profile_mode='replay')

    def test_unknown_and_malformed_metadata_profile_identity(self):
        for field in ('sha256','digest'):
            raw=synthetic_config(); raw['metadata'][field]='bad'; self.reject(raw,'SHA-256')
        raw=synthetic_config(); raw['metadata']['extra']=1; self.reject(raw,'metadata identity fields')
        raw=synthetic_config(); raw['profiles']['digest']=True; self.reject(raw,'SHA-256')

    def test_cpu_only_is_explicit_and_gpu_failure_never_selects_it(self):
        from tests.issue299_fixture import synthetic_cpu_only_config
        parsed=self.parse(synthetic_cpu_only_config())
        self.assertEqual(parsed.selection,'cpu-only')
        self.assertEqual(sum(len(p.bindings) for p in parsed.participants),2)
        raw=synthetic_config(); raw['participants'][1]['bindings'][1]['physical_id']='missing-gpu'
        self.reject(raw,'binding physical identity mismatch')
        self.assertEqual(raw['selection'],'one-gpu')

    def test_shared_ram_has_one_identified_domain(self):
        def mutate(p):
            cu=next(c for c in p['compute_units'] if c['compute_id']=='B-gpu'); cu['memory_ids'].append('B-ram')
            e=next(e for e in p['evidence'] if e['evidence_id']==cu['evidence_id']); e['dependencies']['memory:B-ram:physical_id']='physical-B-ram'
        parsed=self.parse(self.mutated_profile(mutate))
        self.assertEqual(sum(m.memory_id=='B-ram' for m in parsed.profiles.snapshot.memory_resources),1)
        self.assertIn('B-ram',next(c for c in parsed.profiles.snapshot.compute_units if c.compute_id=='B-gpu').memory_ids)

    def test_nonvendor_backend_is_descriptive_not_selection_policy(self):
        def mutate(p):
            cu=next(c for c in p['compute_units'] if c['compute_id']=='B-gpu'); cu['backend']='vulkan'
            rt=next(r for r in p['runtime_capabilities'] if r['compute_id']=='B-gpu'); rt['backend']='vulkan'
            e=next(e for e in p['evidence'] if e['evidence_id']==rt['evidence_id']); e['dependencies']['runtime:runtime-B-gpu:backend']='vulkan'
        parsed=self.parse(self.mutated_profile(mutate))
        self.assertEqual(parsed.selection,'one-gpu')
        self.assertEqual(next(c for c in parsed.profiles.snapshot.compute_units if c.compute_id=='B-gpu').backend,'vulkan')

    def test_manual_snapshot_digest_substitution_rechecked(self):
        from dataclasses import replace
        parsed=self.parse(synthetic_config())
        altered=replace(parsed,profiles=replace(parsed.profiles,snapshot=replace(parsed.profiles.snapshot,digest='e'*64)))
        reasons=config.validate_config_profiles(altered,now=NOW,profile_mode='replay')
        self.assertIn('profile snapshot integrity mismatch',reasons)

    def test_native_cache_descriptor_syntax_source_and_member_bounds(self):
        from tests.issue299_fixture import MODEL
        def fixture():
            raw=synthetic_config(); raw['participants'][1]['cache_ranges']=[dict(state_id='synthetic-state',member='member.gguf',offset=10,length=10,sha256='e'*64,cache_key='0123456789abcdef',**MODEL,unit_id='opaque-unit-B-cpu')]
            return raw
        self.assertEqual(len(self.parse(fixture()).participants[1].cache_ranges),1)
        for changes,reason in (({'cache_key':'../escape'},'cache_key'),({'revision':'wrong'},'cache range source identity mismatch'),({'offset':999},'state range outside source member bounds'),({'length':True},'state range outside source member bounds')):
            raw=fixture(); raw['participants'][1]['cache_ranges'][0].update(changes); self.reject(raw,reason)

    def test_nested_unknown_keys_duplicates_and_roles(self):
        for key in ('participants','placement'):
            raw=synthetic_config(); raw[key][0]['extra']=1; self.reject(raw,'fields must be exactly')
        raw=synthetic_config(); raw['participants'][0]['bindings'][0]['extra']=1; self.reject(raw,'binding fields')
        raw=synthetic_config(); raw['participants'][1]['role']='client'; self.reject(raw,'one client and one remote')
        raw=synthetic_config(); raw['participants'][1]['bindings']=[]; self.reject(raw,'missing bindings')
        raw=synthetic_config(); raw['participants'][1]['rpc_endpoint']='synthetic-B:9999'; self.reject(raw,'rpc_endpoint must match participant port')

    def test_duplicate_json_keys_and_nonfinite_json_profiles(self):
        import json
        raw=synthetic_config()
        text=json.dumps(raw).replace('"host_id": "A"','"host_id": "A", "host_id": "A"',1)
        with self.assertRaisesRegex(ValueError,'duplicate JSON key'):
            config.parse_config_json(text,now=NOW,profile_mode='replay')
        text=json.dumps(raw).replace('0.01','1e999')
        with self.assertRaisesRegex(ValueError,'link measurement|nonfinite'):
            config.parse_config_json(text,now=NOW,profile_mode='replay')


class ProfileFileTests(unittest.TestCase):
    def test_profile_file_relative_bytes_identity_and_bounded_read(self):
        import hashlib
        import json
        import tempfile
        from pathlib import Path
        raw=synthetic_config()
        with tempfile.TemporaryDirectory() as root:
            root=Path(root); profile=root/'profiles.json'; profile.write_bytes(json.dumps(raw['profiles']['snapshot']).encode())
            raw['profiles']={'path':'profiles.json','sha256':hashlib.sha256(profile.read_bytes()).hexdigest(),'digest':raw['profiles']['digest']}
            path=root/'config.json'; path.write_text(json.dumps(raw))
            parsed=config.load_config(path,now=NOW,profile_mode='replay')
            self.assertEqual(parsed.profiles.sha256,raw['profiles']['sha256'])
            self.assertEqual(parsed.metadata.path,str(root/'metadata.json'))
            before=path.read_bytes(); profile.write_bytes(profile.read_bytes()+b' ')
            with self.assertRaisesRegex(ValueError,'profile file SHA-256 mismatch'):
                config.load_config(path,now=NOW,profile_mode='replay')
            self.assertEqual(path.read_bytes(),before)
            profile.write_bytes(b' '*(4*1024*1024+1))
            with self.assertRaisesRegex(ValueError,'oversized profile JSON'):
                config.load_config(path,now=NOW,profile_mode='replay')

    def test_profile_file_pinned_duplicate_keys_and_nonfinite_reject(self):
        import hashlib
        import json
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as root:
            root=Path(root); raw=synthetic_config(); profile=root/'profiles.json'
            text=json.dumps(raw['profiles']['snapshot'])
            for changed,reason in ((text.replace('"host_id": "A"','"host_id": "A", "host_id": "A"',1),'duplicate JSON key'),(text.replace('0.01','1e999'),'link measurement')):
                profile.write_bytes(changed.encode())
                value=copy.deepcopy(raw); value['profiles']={'path':'profiles.json','sha256':hashlib.sha256(profile.read_bytes()).hexdigest(),'digest':raw['profiles']['digest']}
                before=profile.read_bytes()
                with self.assertRaisesRegex(ValueError,reason):
                    config.parse_config(value,base_dir=root,now=NOW,profile_mode='replay')
                self.assertEqual(profile.read_bytes(),before)

    def test_profile_path_is_not_identity_and_pinned_bytes_are(self):
        import hashlib
        import json
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as root:
            root=Path(root); raw=synthetic_config(); content=json.dumps(raw['profiles']['snapshot']).encode()
            for name in ('first.json','second.json'): (root/name).write_bytes(content)
            raw['profiles']={'path':'first.json','sha256':hashlib.sha256(content).hexdigest(),'digest':raw['profiles']['digest']}
            first=config.parse_config(raw,base_dir=root,now=NOW,profile_mode='replay')
            raw['profiles']['path']='second.json'
            self.assertEqual(first,config.parse_config(raw,base_dir=root,now=NOW,profile_mode='replay'))
            (root/'second.json').write_bytes(content+b' '); raw['profiles']['sha256']=hashlib.sha256(content+b' ').hexdigest()
            second=config.parse_config(raw,base_dir=root,now=NOW,profile_mode='replay')
            self.assertEqual(first.profiles.digest,second.profiles.digest)
            self.assertNotEqual(first.profiles.sha256,second.profiles.sha256)

    def test_profile_file_requires_explicit_base_and_pin_before_read(self):
        value=synthetic_config(); value['profiles']={'path':'profiles.json','sha256':'f'*64,'digest':value['profiles']['digest']}
        with patch('pathlib.Path.open',side_effect=AssertionError('unexpected read')):
            with self.assertRaisesRegex(ValueError,'relative profile path requires config directory'):
                config.parse_config(value,now=NOW,profile_mode='replay')
            value['profiles']['sha256']='malformed'
            with self.assertRaisesRegex(ValueError,'SHA-256'):
                config.parse_config(value,base_dir='/synthetic',now=NOW,profile_mode='replay')


if __name__ == '__main__': unittest.main()

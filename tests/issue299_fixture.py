"""Small SYNTHETIC test builders. Not public evidence or physical inventory."""
import copy
import hashlib
import json
from datetime import datetime, timezone
from typing import Any

NOW = datetime(2026, 1, 2, 12, tzinfo=timezone.utc)
MODEL = dict(source_id='synthetic/model', revision='synthetic-revision', representation='opaque')
WORKLOAD = dict(context=32, slots=1, batch=8, microbatch=4, cache_settings={'opaque': ['test']})
GROUPS = ('hosts', 'compute_units', 'memory_resources', 'links', 'runtime_capabilities')
ID_KEYS = ('host_id', 'compute_id', 'memory_id', 'link_id', 'runtime_id')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def profile_digest(value):
    value = copy.deepcopy(value)
    for group, key in zip(GROUPS, ID_KEYS):
        value[group].sort(key=lambda row: row[key])
        if group == 'compute_units':
            for row in value[group]:
                row['memory_ids'].sort()
        if group == 'runtime_capabilities':
            for row in value[group]:
                row['capabilities'].sort()
    value['evidence'].sort(key=lambda row: row['evidence_id'])
    return sha(value)


def reseal_profiles(value):
    """Reseal synthetic envelopes, deliberately NOT repairing dependencies."""
    evidence = {r['evidence_id']: r for r in value['evidence']}
    for group in GROUPS:
        for row in value[group]:
            e = evidence[row['evidence_id']]
            payload = {k: copy.deepcopy(v) for k, v in row.items() if k != 'evidence_id'}
            if group == 'compute_units': payload['memory_ids'].sort()
            if group == 'runtime_capabilities': payload['capabilities'].sort()
            e['payload'] = payload
            e['sha256'] = sha({k: v for k, v in e.items() if k != 'sha256'})
    return value


def synthetic_profiles() -> dict[str, Any]:
    value: dict[str, Any] = dict(schema='resource-profiles/1', hosts=[], compute_units=[], memory_resources=[], links=[], runtime_capabilities=[], evidence=[])
    def add(group, row, deps):
        eid = 'synthetic-' + row[ID_KEYS[GROUPS.index(group)]]
        row['evidence_id'] = eid
        value[group].append(row)
        value['evidence'].append(dict(evidence_id=eid, sha256='0'*64,
            observed_at='2026-01-02T11:00:00Z', expires_at='2026-01-02T13:00:00Z',
            provenance={'producer': 'synthetic unittest fixture', 'protocol': 'illustrative only'},
            dependencies=deps, evidence_class='measured', source_scope='synthetic', payload={}))
    def hostdeps(host):
        return {f'host:{host}:boot_epoch': f'boot-{host}', f'host:{host}:topology_epoch': f'topology-{host}'}
    for host in ('A', 'B'):
        add('hosts', dict(host_id=host, physical_id='host-'+host, boot_epoch='boot-'+host, topology_epoch='topology-'+host), hostdeps(host))
        for suffix, kind in (('ram', 'ram'), ('disk', 'storage')):
            mid=host+'-'+suffix
            add('memory_resources', dict(memory_id=mid, physical_id='physical-'+mid, host_id=host, kind=kind, total_bytes=1000000, available_bytes=900000), {**hostdeps(host), f'memory:{mid}:physical_id':'physical-'+mid})
    add('memory_resources', dict(memory_id='B-vram', physical_id='physical-B-vram', host_id='B', kind='vram', total_bytes=500000, available_bytes=400000), {**hostdeps('B'), 'memory:B-vram:physical_id':'physical-B-vram'})
    for cid, host, backend, mem in (('A-cpu','A','cpu','A-ram'),('B-cpu','B','cpu','B-ram'),('B-gpu','B','cuda','B-vram')):
        add('compute_units', dict(compute_id=cid, host_id=host, physical_id='physical-'+cid, backend=backend, memory_ids=[mem]), {**hostdeps(host), f'compute:{cid}:physical_id':'physical-'+cid, f'memory:{mem}:physical_id':'physical-'+mem})
        rid='runtime-'+cid
        runtime=dict(runtime_id=rid, host_id=host, compute_id=cid, source_revision='synthetic-runtime-source', build_id='synthetic-build', binary_sha256='b'*64, driver='synthetic-driver', backend=backend, route='synthetic-route', capabilities=['opaque-capability'])
        deps={**hostdeps(host), f'compute:{cid}:physical_id':'physical-'+cid,
              **{f'runtime:{rid}:{key}':runtime[key] for key in ('source_revision','build_id','binary_sha256','driver','backend','route')},
              **{'model:'+key: val for key,val in MODEL.items()}, 'workload:digest':sha(WORKLOAD)}
        add('runtime_capabilities', runtime, deps)
    add('links', dict(link_id='A-B', source_host_id='A', target_host_id='B', path='synthetic-direct-path', protocol='tcp', throughput_bytes_per_second=10000, latency_seconds=0.01), {**hostdeps('A'), **hostdeps('B'), 'link:A-B:path':'synthetic-direct-path', 'link:A-B:protocol':'tcp'})
    return reseal_profiles(value)


def synthetic_config(profiles=None) -> dict[str, Any]:
    profiles = synthetic_profiles() if profiles is None else profiles
    def binding(cid, mid, selector):
        e=next((e for e in profiles['evidence'] if e['evidence_id']=='synthetic-'+cid), {'evidence_id':'synthetic-'+cid, 'sha256':'0'*64})
        return dict(binding_id='binding-'+cid, compute_id=cid, memory_id=mid, physical_id='physical-'+cid,
                    native_selector=selector, visible_selector=selector, runtime_id='runtime-'+cid,
                    evidence_id=e['evidence_id'], evidence_sha256=e['sha256'])
    def participant(role, host, bindings):
        return dict(participant_id='process-'+host, role=role, host_id=host, boot_epoch='boot-'+host, topology_epoch='topology-'+host,
                    transport='local' if role=='client' else 'rpc', execution_address='synthetic-'+host,
                    rpc_endpoint=None if role=='client' else 'synthetic-B:5000', source_path='/synthetic/model/member.gguf',
                    runtime_executable='/synthetic/runtime', runtime_sha256='b'*64, cache_path='/synthetic/cache/'+host,
                    port=8080 if role=='client' else 5000, lifecycle_dir='/synthetic/lease/'+host,
                    source_id=MODEL['source_id'], source_revision=MODEL['revision'], source_representation=MODEL['representation'],
                    bindings=bindings, backing=[dict(memory_id=host+'-disk', member='member.gguf', sha256='a'*64, size_bytes=1000)], cache_ranges=[])
    return dict(schema='operator-config/3', plan_id='synthetic-plan', model={**MODEL, 'members':[dict(name='member.gguf',sha256='a'*64,size_bytes=1000)]},
        strategy_id='qwen38-q8-fixed/1', selection='one-gpu', metadata=dict(path='metadata.json',sha256='c'*64,digest='d'*64),
        profiles=dict(snapshot=profiles, digest=profile_digest(profiles)),
        policy=dict(max_age_seconds=7200, allowed_evidence_classes=['measured','calculated'], memory_limits=[dict(memory_id=r['memory_id'],peak_bytes=r['total_bytes'],min_available_bytes=0,reserve_bytes=1) for r in profiles['memory_resources']]),
        workload=copy.deepcopy(WORKLOAD), participants=[participant('client','A',[binding('A-cpu','A-ram','CPU')]),participant('remote','B',[binding('B-cpu','B-ram','CPU'),binding('B-gpu','B-vram','CUDA0')])],
        placement=[dict(unit_id='opaque-unit-'+cid,binding_id='binding-'+cid,state_ids=[],state_ranges=[]) for cid in ('A-cpu','B-cpu','B-gpu')],
        strategy_options={'opaque': {'test': [1,2]}}, request=dict(prompt='synthetic test', max_tokens=1,temperature=0.0,seed=1))


def synthetic_cpu_only_config():
    """Explicit synthetic comparison fixture; NEVER a fallback path."""
    result=synthetic_config(); result['selection']='cpu-only'
    profiles=result['profiles']['snapshot']
    profiles['compute_units']=[r for r in profiles['compute_units'] if r['compute_id']!='B-gpu']
    profiles['memory_resources']=[r for r in profiles['memory_resources'] if r['memory_id']!='B-vram']
    profiles['runtime_capabilities']=[r for r in profiles['runtime_capabilities'] if r['runtime_id']!='runtime-B-gpu']
    profiles['evidence']=[r for r in profiles['evidence'] if r['evidence_id'] not in ('synthetic-B-gpu','synthetic-B-vram','synthetic-runtime-B-gpu')]
    result['profiles']['digest']=profile_digest(profiles)
    result['participants'][1]['bindings']=result['participants'][1]['bindings'][:1]
    result['placement']=result['placement'][:2]
    result['policy']['memory_limits']=[r for r in result['policy']['memory_limits'] if r['memory_id']!='B-vram']
    return result

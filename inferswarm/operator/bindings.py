"""Bounded internal owned-observer contract; no native observer or executor.

Stock b29c606 telemetry is insufficient. BindingTransport refuses without any
I/O. A future transport must independently capture native-context inventory,
not echo a plan or interpret RPC type/ordinal/layer logs. Its producer/method
must be qualified in frozen *measured* runtime evidence before capture.

Wire versions: binding-preflight/1 (no process), owned-observation/1 (complete
process/materialization capture). TransportReply carries raw UTF-8 JSON bytes;
nonzero status is refused BEFORE decoding. All fields are exact, bounded and
privately frozen. evidence.record_digest is SHA256(canonical whole envelope
with just that digest omitted); it is integrity, not cryptographic attestation.

Live mode always uses real UTC, disallows clock injection and synthetic/replay
scope regardless of config.profile_mode. mode='synthetic-test' requires a UTC
clock callable and explicit synthetic scope in observer AND profile evidence.
Synthetic receipts never qualify physical execution. Even live observer proof
is not execution authorization; the runner must freshly revalidate the whole
plan before this seam and retain leases/listener/cleanup ownership. This module
never re-admits, launches, queries hosts, retries, or changes a selection.

Process start is an opaque exact host-native creation identity (e.g. Linux
/proc start ticks), NOT a wall-clock approximation. The future runner supplies
ProcessIdentity and owned_argv from the actual spawn/lease, never from a payload.
identity_reader(participant,pid) independently reads the identity immediately
before/after transport.observe; capture compares every field on both sides.

Complete inventories are opaque candidate contracts. Buffers enumerate every
actual tensor/state base allocation; auxiliary enumerates all serve-phase
charge IDs. Shared base buffers are allowed only for nonoverlapping exact
views in one physical domain. Lazy-backed extent and current resident bytes
remain distinct; neither zero residence nor an mmap is proof of RAM fit.
Boundary logical_bytes is never a wire measurement. Actual route, completed
copy provenance and positive wire/staging observations are required.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import json
from typing import Callable

from .profiles import (FrozenMapping, _dependency_context, canonical, digest,
    freeze, integer, keys, sha256, text, thaw, utc_timestamp, validate_profiles)

MAX_OBSERVATION_BYTES = 8 << 20
MAX_INVENTORY_ROWS = 10000
OBSERVER_CAPABILITIES = ('physical-bindings/1', 'complete-materialization/1',
    'state-authority/1', 'copy-route/1', 'process-identity/1')
OBSERVER_METHOD = 'native-context-inventory/1'
UNSUPPORTED_OBSERVER = ('UNKNOWN/unsupported owned materialization observer: '
    'stock pinned runtime lacks independent physical binding and complete '
    'tensor/buffer/state/copy observations; no launch or request is permitted')


@dataclass(frozen=True)
class TransportReply:
    exit_code: int
    payload: bytes


@dataclass(frozen=True)
class ProcessIdentity:
    participant_id: str
    host_id: str
    boot_epoch: str
    topology_epoch: str
    pid: int
    start: str
    executable: str
    binary_sha256: str
    effective_argv: tuple[str, ...]
    visibility: FrozenMapping
    endpoint: str | None

    def __post_init__(self):
        for k in ('participant_id','host_id','boot_epoch','topology_epoch','start','executable'):
            text(getattr(self,k), 'process '+k)
        integer(self.pid, 'process pid', minimum=1)
        digest(self.binary_sha256, 'process binary')
        if not isinstance(self.effective_argv,tuple) or not self.effective_argv:
            raise ValueError('immutable effective argv required')
        for arg in self.effective_argv: text(arg, 'process argv')
        if not isinstance(self.visibility,FrozenMapping):
            raise ValueError('immutable process visibility required')
        object.__setattr__(self,'visibility',freeze(thaw(self.visibility)))
        if self.endpoint is not None: text(self.endpoint,'process endpoint')


@dataclass(frozen=True)
class BindingReceipt:
    participant_id: str
    expected_digest: str
    observed_digest: str
    expected: FrozenMapping
    observed: FrozenMapping
    evidence_classes: tuple
    physical_qualified: bool
    execution_authorized: bool = False


@dataclass(frozen=True)
class OwnedObservation:
    owned: ProcessIdentity
    before: ProcessIdentity
    after: ProcessIdentity
    invocation_token: str
    payload: FrozenMapping
    mode: str


@dataclass(frozen=True)
class MaterializationReceipt:
    expected_digest: str
    observed_digest: str
    expected: FrozenMapping
    observed: FrozenMapping
    tensor_count: int
    state_count: int
    buffer_count: int
    auxiliary_count: int
    boundary_count: int
    binding_counts: tuple
    wire_digests: tuple
    evidence_classes: tuple
    physical_qualified: bool
    execution_authorized: bool = False


class BindingTransport:
    """Default refusal, not an incomplete fake telemetry adapter.

    Inject the narrow preflight/observe duck-typed seam only when a frozen
    profile qualifies that producer/method and its complete native observations.
    observe must return the raw transport status, not parse failed output.
    """
    def preflight(self, participant, plan) -> TransportReply:
        raise ValueError(UNSUPPORTED_OBSERVER)

    def observe(self, participant, plan, *, owned_pid, start, invocation_token,
                owned_argv) -> TransportReply:
        raise ValueError(UNSUPPORTED_OBSERVER)


def _plain(value):
    if hasattr(value,'__dataclass_fields__'): value=asdict(value)
    return json.loads(canonical(thaw(value)))


def _same(actual, expected):
    # JSON true must not compare equal to 1, nor 1.0 to 1.
    return canonical(actual)==canonical(expected)


def _array(value, label, maximum=MAX_INVENTORY_ROWS):
    if type(value) is not list or len(value)>maximum:
        raise ValueError(label+' must be bounded array')
    return value


def _decode(reply):
    if not isinstance(reply,TransportReply): raise ValueError('typed observer transport reply required')
    if type(reply.exit_code) is not int or reply.exit_code != 0:
        raise ValueError('observer transport exit '+str(reply.exit_code))
    if type(reply.payload) is not bytes: raise ValueError('observer payload must be bytes')
    if len(reply.payload)>MAX_OBSERVATION_BYTES: raise ValueError('oversized observation payload')
    def pairs(items):
        out={}
        for k,v in items:
            if k in out: raise ValueError('duplicate observation key: '+k)
            out[k]=v
        return out
    def constant(v): raise ValueError('nonfinite observation number: '+v)
    try:
        out=json.loads(reply.payload,object_pairs_hook=pairs,parse_constant=constant)
        # Also rejects 1e999, deep/massive structures and invalid text/integers.
        freeze(out)
    except (UnicodeError,RecursionError,json.JSONDecodeError) as exc:
        raise ValueError('invalid observation JSON') from exc
    return out


def _now(mode, clock):
    if mode=='live':
        if clock is not None: raise ValueError('live clock injection is prohibited')
        now=datetime.now(timezone.utc)
    elif mode=='synthetic-test':
        if not callable(clock): raise ValueError('synthetic test clock must be explicitly injected')
        now=clock()
    else: raise ValueError('unsupported observation mode')
    if not isinstance(now,datetime) or now.tzinfo is None or now.utcoffset()!=timezone.utc.utcoffset(now):
        raise ValueError('observation clock must be timezone-aware UTC')
    return now


def _subject(plan):
    return dict(plan_digest=plan.digest,selection=plan.selection,
        profiles_digest=plan.profiles.digest,profiles_file_sha256=plan.profiles.sha256,
        metadata_digest=plan.metadata.digest,metadata_sha256=plan.metadata.sha256,
        model_digest=sha256(asdict(plan.model)),workload_digest=sha256(asdict(plan.workload)))


def _dependencies(plan):
    return {**_dependency_context(plan.profiles.snapshot),
        **dict(plan.candidate.subject.dependencies),
        **{'subject:'+k:str(v) for k,v in _subject(plan).items()}}


def _participant(plan, participant):
    matches=[p for p in plan.participants if p.participant_id==participant.participant_id]
    if len(matches)!=1 or matches[0]!=participant: raise ValueError('frozen participant identity mismatch')
    return matches[0]


def _expected_bindings(participant, plan):
    s=plan.profiles.snapshot
    cu={r.compute_id:r for r in s.compute_units}
    mem={r.memory_id:r for r in s.memory_resources}
    runtimes={r.runtime_id:r for r in s.runtime_capabilities}
    bindings=sorted(participant.bindings,key=lambda b:b.visible_selector)
    return [dict(binding=_plain(b),compute=_plain(cu[b.compute_id]),
        memory=_plain(mem[b.memory_id]),runtime=_plain(runtimes[b.runtime_id])) for b in bindings]


_COMMON_FIELDS=('schema','participant_id','subject','host','endpoint','visibility',
    'capabilities','bindings','evidence')
_OWNED_FIELDS=(*_COMMON_FIELDS,'invocation_token','process','context','source_receipt_digest',
    'tensors','states','buffers','auxiliary','boundaries')
_EVIDENCE_FIELDS=('producer','method','provenance','observed_at','expires_at','evidence_class',
    'source_scope','dependencies','record_digest')


def _validate_common(participant,plan,data,*,mode,now,owned=False):
    _participant(plan,participant)
    keys(data,_OWNED_FIELDS if owned else _COMMON_FIELDS,'owned observation' if owned else 'preflight')
    if data['schema']!=('owned-observation/1' if owned else 'binding-preflight/1'):
        raise ValueError('unsupported observation schema')
    e=data['evidence']; keys(e,_EVIDENCE_FIELDS,'observer evidence')
    digest(e['record_digest'],'observer record digest')
    body={k:v for k,v in data.items() if k!='evidence'}
    body['evidence']={k:v for k,v in e.items() if k!='record_digest'}
    if sha256(body)!=e['record_digest']: raise ValueError('observer record digest mismatch')
    if e['method']!=OBSERVER_METHOD: raise ValueError('independent observer method required; no config echo/layer logs')
    text(e['producer'],'observer producer')
    keys(e['provenance'],('protocol','record_id'),'observer provenance')
    for k,v in e['provenance'].items(): text(v,'observer provenance '+k)
    if e['evidence_class']!='measured': raise ValueError('observer evidence class must be measured')
    if mode=='live' and e['source_scope']!='live': raise ValueError('non-live observer evidence')
    if mode=='synthetic-test' and e['source_scope']!='synthetic': raise ValueError('synthetic test scope must be explicit')
    observed=utc_timestamp(e['observed_at']); expires=utc_timestamp(e['expires_at'])
    if observed>now: raise ValueError('future observer evidence')
    if expires<=now or expires<=observed: raise ValueError('expired observer evidence')
    if (now-observed).total_seconds()>plan.policy.max_age_seconds: raise ValueError('stale observer evidence')
    if not _same(e['dependencies'],_dependencies(plan)): raise ValueError('observer dependency mismatch')
    if not _same(data['subject'],_subject(plan)): raise ValueError('observer subject mismatch')
    if data['participant_id']!=participant.participant_id or data['endpoint']!=participant.rpc_endpoint:
        raise ValueError('observer participant/endpoint mismatch')
    s=plan.profiles.snapshot
    # Baseline profile integrity/freshness is not whole-plan re-admission.
    if mode=='synthetic-test' and any(e.source_scope!='synthetic' for e in s.evidence):
        raise ValueError('synthetic test profile scope must be explicit')
    reasons=validate_profiles(s,now=now,policy=plan.policy,
        subject=replace(plan.candidate.subject,mode='live' if mode=='live' else 'replay'))
    if reasons: raise ValueError('observer baseline profile: '+reasons[0])
    if s.digest!=plan.profiles.digest: raise ValueError('observer baseline profiles digest mismatch')
    host=next(r for r in s.hosts if r.host_id==participant.host_id)
    if not _same(data['host'],_plain(host)): raise ValueError('host epoch/physical identity mismatch')
    expected=_expected_bindings(participant,plan)
    actual=_array(data['bindings'],'bindings',len(expected)+1)
    if len(actual)!=len(expected): raise ValueError('binding coverage mismatch')
    for row in actual: keys(row,('binding','compute','memory','runtime','advertised_type'),'observed binding')
    ids=[r['binding'].get('binding_id') for r in actual if isinstance(r['binding'],dict)]
    if set(ids)!={b['binding']['binding_id'] for b in expected} or len(set(ids))!=len(actual):
        raise ValueError('binding coverage mismatch')
    if ids!=[r['binding']['binding_id'] for r in expected]: raise ValueError('ordered binding translation mismatch')
    visibility=data['visibility']; keys(visibility,('native','visible','environment'),'configured visibility')
    if not _same(visibility['native'],[r['binding']['native_selector'] for r in expected]) or not _same(visibility['visible'],[r['binding']['visible_selector'] for r in expected]):
        raise ValueError('configured visibility mismatch')
    if type(visibility['environment']) is not dict: raise ValueError('configured visibility environment required')
    for k,v in visibility['environment'].items(): text(k,'visibility variable'); text(v,'visibility value')
    caps=_array(data['capabilities'],'observer capability',len(OBSERVER_CAPABILITIES))
    if set(caps)!=set(OBSERVER_CAPABILITIES) or len(caps)!=len(set(caps)):
        raise ValueError('observer capability complete coverage required')
    token='owned-observer/1:'+e['producer']+':'+e['method']
    ev={r.evidence_id:r for r in s.evidence}
    for actual,want in zip(actual,expected):
        if not _same(actual['binding'],want['binding']): raise ValueError('physical binding identity/selector mismatch')
        if not _same(actual['compute'],want['compute']): raise ValueError('physical binding identity/CPU domain mismatch')
        if not _same(actual['memory'],want['memory']): raise ValueError('physical memory ownership mismatch')
        if not _same(actual['runtime'],want['runtime']): raise ValueError('runtime identity/build/driver mismatch')
        runtime=want['runtime']
        if ev[runtime['evidence_id']].evidence_class!='measured' or not set((*OBSERVER_CAPABILITIES,token))<=set(runtime['capabilities']):
            raise ValueError('observer capability not qualified in baseline measured runtime evidence')
        # advertised_type intentionally has NO physical or capability authority.
        text(actual['advertised_type'],'descriptive advertised type')
    return expected


def validate_preflight(participant, plan, reply: TransportReply, *, mode='live',
                       clock: Callable | None=None) -> BindingReceipt:
    now=_now(mode,clock)
    data=_decode(reply)
    expected=_validate_common(participant,plan,data,mode=mode,now=now)
    frozen_expected=freeze(dict(subject=_subject(plan),bindings=expected))
    return BindingReceipt(participant.participant_id,sha256(frozen_expected),sha256(data),
        frozen_expected,freeze(data),((data['evidence']['evidence_class'],data['evidence']['source_scope']),),mode=='live')


def preflight_bindings(plan, *, transport=None, mode='live', clock=None) -> tuple[BindingReceipt,...]:
    if transport is None or type(transport) is BindingTransport: raise ValueError(UNSUPPORTED_OBSERVER)
    _now(mode,clock)
    receipts=tuple(validate_preflight(p,plan,transport.preflight(p,plan),mode=mode,clock=clock) for p in plan.participants)
    _distinct_bindings(plan)
    return receipts


def _distinct_bindings(plan):
    rows=[b for p in plan.participants for b in p.bindings]
    for field in ('binding_id','physical_id','memory_id'):
        values=[getattr(b,field) for b in rows]
        if len(values)!=len(set(values)): raise ValueError('distinct binding physical domain ownership required: '+field)
    handles=[b.visible_selector for b in rows]
    if len(handles)!=len(set(handles)): raise ValueError('distinct visible binding handles required')


def _validate_owned(participant, data, owned, argv, token):
    if not isinstance(owned,ProcessIdentity): raise ValueError('typed owned process identity required')
    if type(argv) is not tuple or argv!=owned.effective_argv: raise ValueError('owned argv must come from actual spawn')
    text(token,'invocation token')
    for key,want in dict(participant_id=participant.participant_id,host_id=participant.host_id,
            boot_epoch=participant.boot_epoch,topology_epoch=participant.topology_epoch,
            executable=participant.runtime_executable,binary_sha256=participant.runtime_sha256,
            endpoint=participant.rpc_endpoint).items():
        if getattr(owned,key)!=want: raise ValueError('owned process frozen identity mismatch: '+key)
    if data['invocation_token']!=token: raise ValueError('invocation token mismatch')
    if not _same(data['process'],_plain(owned)): raise ValueError('owned observation process mismatch')
    if not _same(data['visibility'],thaw(owned.visibility)): raise ValueError('owned observation process visibility mismatch')


def gather_owned_observation(participant, plan, *, transport=None, owned: ProcessIdentity,
        owned_argv: tuple[str,...], invocation_token: str, identity_reader=None,
        mode='live', clock=None) -> OwnedObservation:
    if transport is None or type(transport) is BindingTransport: raise ValueError(UNSUPPORTED_OBSERVER)
    _now(mode,clock)
    _participant(plan,participant)
    if not isinstance(owned,ProcessIdentity): raise ValueError('typed owned process identity required')
    if type(owned_argv) is not tuple or owned_argv!=owned.effective_argv:
        raise ValueError('owned argv must come from actual spawn')
    text(invocation_token,'invocation token')
    if not callable(identity_reader): raise ValueError('independent identity reader required; no host-query default')
    before=identity_reader(participant,owned.pid)
    if not isinstance(before,ProcessIdentity) or before!=owned: raise ValueError('owned process identity before capture mismatch')
    try:
        reply=transport.observe(participant,plan,owned_pid=owned.pid,start=owned.start,
            invocation_token=invocation_token,owned_argv=owned_argv)
    finally:
        # Raised capture failures also recheck once; a recheck failure retains
        # the capture exception as context, otherwise the same error propagates.
        after=identity_reader(participant,owned.pid)
        if not isinstance(after,ProcessIdentity) or after!=owned: raise ValueError('owned process identity after capture mismatch')
    data=_decode(reply)
    now=_now(mode,clock)
    _validate_common(participant,plan,data,mode=mode,now=now,owned=True)
    _validate_owned(participant,data,owned,owned_argv,invocation_token)
    if not _same(data['context'],_plain(plan.workload)): raise ValueError('observer context mismatch')
    return OwnedObservation(owned,before,after,invocation_token,freeze(data),mode)


def _owned_data(plan, observations, mode, now):
    if not isinstance(observations,(list,tuple)): raise ValueError('owned participant coverage required')
    if len(observations)!=len(plan.participants) or any(not isinstance(o,OwnedObservation) for o in observations):
        raise ValueError('owned participant coverage mismatch')
    ids=[o.owned.participant_id for o in observations]
    if set(ids)!={p.participant_id for p in plan.participants} or len(ids)!=len(set(ids)):
        raise ValueError('owned participant coverage mismatch')
    byid={p.participant_id:p for p in plan.participants}
    result=[]
    for o in sorted(observations,key=lambda o:o.owned.participant_id):
        if o.mode!=mode: raise ValueError('owned observation mode mismatch')
        if o.before!=o.owned or o.after!=o.owned: raise ValueError('owned process identity capture mismatch')
        data=thaw(o.payload); p=byid[o.owned.participant_id]
        _validate_common(p,plan,data,mode=mode,now=now,owned=True)
        _validate_owned(p,data,o.owned,o.owned.effective_argv,o.invocation_token)
        if not _same(data['context'],_plain(plan.workload)): raise ValueError('observer context mismatch')
        result.append((p,data))
    if len({o.invocation_token for o in observations})!=1: raise ValueError('global invocation token mismatch')
    _distinct_bindings(plan)
    return result


def reconcile_bindings(plan, observations, *, mode='live', clock=None) -> tuple[BindingReceipt,...]:
    rows=_owned_data(plan,observations,mode,_now(mode,clock))
    receipts=[]
    for p,data in rows:
        expected=freeze(dict(subject=_subject(plan),bindings=_expected_bindings(p,plan)))
        receipts.append(BindingReceipt(p.participant_id,sha256(expected),sha256(data),expected,
            freeze(data),((data['evidence']['evidence_class'],data['evidence']['source_scope']),),mode=='live'))
    return tuple(receipts)


def _inventory(rows,key,label,maximum):
    indexed={}
    for row in _array(rows,label,maximum+1):
        if type(row) is not dict or key not in row: raise ValueError(label+' identity required')
        name=text(row[key],label+' identity')
        if name in indexed: raise ValueError('duplicate '+label+': '+name)
        indexed[name]=row
    return indexed


def _source_ranges(plan,rows,sources):
    if type(sources) is not dict or set(sources)!={p.participant_id for p,_ in rows}:
        raise ValueError('source receipt participant coverage mismatch')
    result={}; normalized={}
    for p,data in rows:
        source=_plain(sources[p.participant_id])
        needed=('schema','participant_id','status','plan_digest','metadata_digest',
            'source_identity','runtime_sha256','range_identities','physical_observation','cache_consumed')
        if any(k not in source for k in needed): raise ValueError('source receipt identity missing')
        # The full Slice4A receipt may additionally contain its documented
        # descriptive fields; this seam consumes only the named byte join.
        allowed=set(needed)|{'role','source_contract','rpc_cache','verified_members','member_identities',
            'header_identities','binding_expectations','assigned_count','binding_counts','cache_ranges',
            'eligible_cache_ranges','eligible_cache_reads','backing'}
        if set(source)-allowed: raise ValueError('source receipt fields mismatch')
        checks=dict(schema='q8-source-receipt/1',participant_id=p.participant_id,
            status='VERIFIED-not-consumed',plan_digest=plan.digest,metadata_digest=plan.metadata.digest,
            source_identity={k:getattr(plan.model,k) for k in ('source_id','revision','representation')},
            runtime_sha256=p.runtime_sha256,physical_observation=False,cache_consumed=False)
        if any(not _same(source[k],v) for k,v in checks.items()): raise ValueError('source receipt identity mismatch')
        if not _same(source.get('member_identities'),_plain(plan.model)['members']):
            raise ValueError('source receipt identity member mismatch')
        if sha256(source)!=data['source_receipt_digest']: raise ValueError('source receipt identity digest mismatch')
        ids={b.binding_id for b in p.bindings}
        assignments={a.state_id:a for a in plan.candidate.assignments if a.binding_id in ids}
        ranges=_inventory(source['range_identities'],'state_id','source range',len(assignments))
        if set(ranges)!=set(assignments): raise ValueError('source range coverage mismatch')
        for name,a in assignments.items():
            r=ranges[name]
            keys(r,('state_id','member','offset','length','sha256','binding_id','memory_id','authority','cache_eligible','cache_key'),'source range')
            for k,v in dict(member=a.member,offset=a.absolute_offset,length=a.encoded_bytes,
                    binding_id=a.binding_id,memory_id=a.memory_id,authority=a.authority).items():
                if not _same(r[k],v): raise ValueError('source range identity mismatch: '+name)
            digest(r['sha256'],'source range SHA')
            if type(r['cache_eligible']) is not bool: raise ValueError('source cache eligible must be bool')
            if name in result: raise ValueError('duplicate global source range')
            result[name]=r
        source['range_identities']=sorted(ranges.values(),key=lambda r:r['state_id'])
        normalized[p.participant_id]=source
    return result,normalized


_MATERIAL_FIELDS=('contract','materialization_id','buffer_id','buffer_offset','allocated_bytes',
    'resident_bytes','residence','native_buffer_type','source_sha256')


def _materials(plan,rows,field,expected,source_ranges):
    label='tensor' if field=='tensors' else 'state'
    records=[]; hosts={b.binding_id:p.participant_id for p in plan.participants for b in p.bindings}
    tokens={p.participant_id:data.get('invocation_token') for p,data in rows}
    facts=('authority_owner','authority_epoch','lineage_id','dependencies_observed','actual_representation')
    for p,data in rows:
        for row in _array(data[field],label,len(expected)+1):
            if label=='state' and (type(row) is not dict or not set(facts)<=set(row)):
                raise ValueError('actual state authority observation is incomplete')
            keys(row,(*_MATERIAL_FIELDS,*facts) if label=='state' else _MATERIAL_FIELDS,label+' materialization')
            contract=row['contract']
            if type(contract) is not dict or 'state_id' not in contract: raise ValueError(label+' contract identity required')
            records.append((p.participant_id,row))
    indexed={}
    for pid,row in records:
        name=text(row['contract']['state_id'],label+' identity')
        if name in indexed: raise ValueError('duplicate '+label+': '+name)
        indexed[name]=(pid,row)
    wants={a.state_id:_plain(a) for a in expected}
    if set(indexed)!=set(wants): raise ValueError(label+' coverage mismatch')
    for name,want in wants.items():
        pid,row=indexed[name]; actual=row['contract']
        keys(actual,want.keys(),label+' contract')
        if actual['binding_id']!=want['binding_id'] or pid!=hosts[want['binding_id']]: raise ValueError(label+' ownership mismatch: '+name)
        if actual['memory_id']!=want['memory_id']: raise ValueError(label+' memory mismatch: '+name)
        if actual['authority']!=want['authority']: raise ValueError(label+' authority mismatch: '+name)
        if label=='tensor':
            if not _same(actual,want): raise ValueError('tensor descriptor mismatch: '+name)
        else:
            for k,reason in (('representation','state representation'),('dependencies','state dependencies'),
                    ('reconstructible','state authority'),('lower_bound_bytes','state lower bound')):
                if not _same(actual[k],want[k]): raise ValueError(reason+' mismatch: '+name)
            if row['authority_owner']!=want['binding_id'] or row['authority_epoch']!=tokens[pid]:
                raise ValueError('state authority observation owner/epoch mismatch: '+name)
            text(row['lineage_id'],'state authority observation lineage')
            if not _same(row['dependencies_observed'],want['dependencies']): raise ValueError('state dependencies observation mismatch: '+name)
            if row['actual_representation']!=want['representation']: raise ValueError('state representation observation mismatch: '+name)
        allocated=integer(row['allocated_bytes'],'materialization bytes')
        if label=='state':
            minimum=want['lower_bound_bytes']
            if allocated<(minimum if minimum is not None else 1): raise ValueError('state lower bound observation: '+name)
            if row['source_sha256'] is not None: raise ValueError('state source SHA is not immutable-source authority')
        else:
            if allocated<want['encoded_bytes']: raise ValueError('materialization bytes below encoded extent: '+name)
            if row['source_sha256']!=source_ranges[name]['sha256']: raise ValueError('source range identity mismatch: '+name)
        _residence(row,allocated,'materialization residence')
        for k in ('materialization_id','buffer_id','native_buffer_type'): text(row[k],'materialization '+k)
        integer(row['buffer_offset'],'materialization buffer offset')
    return indexed


def _residence(row,allocated,label):
    resident=integer(row['resident_bytes'],label,maximum=allocated)
    if row['residence'] not in ('resident','lazy-backed'): raise ValueError(label+' must be resident or independently lazy-backed')
    if row['residence']=='resident' and resident!=allocated: raise ValueError(label+' resident extent mismatch')


def _buffers(rows,tensors,states):
    materials=list(tensors.values())+list(states.values())
    material_ids=[r['materialization_id'] for _,r in materials]
    if len(material_ids)!=len(set(material_ids)): raise ValueError('duplicate materialization identity')
    buffers={}; owners={}
    for p,data in rows:
        local=_inventory(data['buffers'],'buffer_id','buffer',len(materials))
        for name,row in local.items():
            keys(row,('buffer_id','binding_id','memory_id','allocated_bytes','resident_bytes','residence','native_buffer_type'),'buffer')
            if name in buffers: raise ValueError('duplicate buffer: '+name)
            buffers[name]=row; owners[name]=p.participant_id
    if set(buffers)!={r['buffer_id'] for _,r in materials}: raise ValueError('buffer coverage mismatch; hidden/omitted allocations')
    extents={}; resident_totals=Counter()
    for pid,row in materials:
        b=buffers[row['buffer_id']]
        if pid!=owners[row['buffer_id']] or b['binding_id']!=row['contract']['binding_id'] or b['memory_id']!=row['contract']['memory_id']:
            raise ValueError('buffer physical ownership mismatch')
        amount=integer(b['allocated_bytes'],'buffer extent',minimum=1)
        end=row['buffer_offset']+row['allocated_bytes']
        if end>amount: raise ValueError('buffer extent mismatch')
        _residence(b,amount,'buffer residence')
        if b['native_buffer_type']!=row['native_buffer_type']: raise ValueError('buffer native type mismatch')
        if row['resident_bytes']>b['resident_bytes'] or row['residence']!=b['residence']:
            raise ValueError('buffer residence mismatch')
        spans=extents.setdefault(row['buffer_id'],[])
        start=row['buffer_offset']
        if any(start<other_end and other_start<end for other_start,other_end in spans):
            raise ValueError('buffer overlapping materializations')
        spans.append((start,end))
        resident_totals[row['buffer_id']]+=row['resident_bytes']
    for name,resident in resident_totals.items():
        if resident>buffers[name]['resident_bytes']:
            raise ValueError('buffer residence sum exceeds base residence')
    return buffers


def _auxiliary(plan,rows):
    memories={m.memory_id:m.host_id for m in plan.profiles.snapshot.memory_resources}
    wants={c.allocation_id:c for c in plan.candidate.charges if c.phase=='serve'}
    indexed={}; owner={}
    for p,data in rows:
        local=_inventory(data['auxiliary'],'allocation_id','auxiliary',len(wants))
        for name,r in local.items():
            if name in indexed: raise ValueError('duplicate auxiliary allocation')
            keys(r,('allocation_id','memory_id','role','phase','actual_bytes','resident_bytes','residence'),'auxiliary')
            indexed[name]=r; owner[name]=p.host_id
    if set(indexed)!=set(wants): raise ValueError('auxiliary coverage mismatch')
    for name,c in wants.items():
        r=indexed[name]
        if r['memory_id']!=c.memory_id or owner[name]!=memories[c.memory_id] or r['role']!=c.role or r['phase']!=c.phase:
            raise ValueError('auxiliary physical role/phase ownership mismatch')
        amount=integer(r['actual_bytes'],'auxiliary observation')
        resident=integer(r['resident_bytes'],'auxiliary residence',maximum=amount)
        if c.bytes is not None and amount>c.bytes: raise ValueError('auxiliary observed bound exceeded')
        if c.role in ('backing','virtual','reserve'):
            if r['residence']!=c.role or resident!=0: raise ValueError('auxiliary backing/virtual/reserve is not residence')
        elif r['residence'] not in ('resident','lazy-backed'): raise ValueError('auxiliary residence UNKNOWN')
        if r['residence']=='resident' and resident!=amount: raise ValueError('auxiliary resident extent mismatch')
    return indexed


def _boundaries(plan,rows,materializations=None):
    if materializations is None: materializations={}
    wants={b.semantic_id:_plain(b) for b in plan.candidate.boundaries}
    hosts={b.binding_id:p.participant_id for p in plan.participants for b in p.bindings}
    runtimes={r.runtime_id:r for r in plan.profiles.snapshot.runtime_capabilities}
    tokens={p.participant_id:data.get('invocation_token') for p,data in rows}
    producers={p.participant_id:data['evidence']['producer'] for p,data in rows}
    indexed={}; owner={}; route={}
    for p,data in rows:
        for r in _array(data['boundaries'],'boundary',len(wants)+1):
            if type(r) is not dict or 'copies' not in r:
                raise ValueError('actual boundary copy observation is incomplete')
            keys(r,('contract','route','copy_method','copy_provenance','wire_bytes','staging_bytes','completed','copies'),'boundary observation')
            if type(r['contract']) is not dict or 'semantic_id' not in r['contract']: raise ValueError('boundary contract identity required')
            name=text(r['contract']['semantic_id'],'boundary identity')
            if name in indexed: raise ValueError('duplicate boundary: '+name)
            indexed[name]=r; owner[name]=p.participant_id
            route[name]={runtimes[b.runtime_id].route for b in p.bindings}
    if set(indexed)!=set(wants): raise ValueError('boundary coverage mismatch')
    for name,want in wants.items():
        r=indexed[name]
        if owner[name]!=hosts[want['producer_binding']] or not _same(r['contract'],want): raise ValueError('boundary contract mismatch: '+name)
        if route[name]!={r['route']}: raise ValueError('boundary route mismatch: '+name)
        if r['copy_method']!='native-copy-trace/1': raise ValueError('boundary copy provenance must be actual native-copy-trace/1')
        keys(r['copy_provenance'],('producer','protocol'),'boundary copy provenance')
        for v in r['copy_provenance'].values(): text(v,'boundary copy provenance')
        if r['copy_provenance']['producer']!=producers[owner[name]]: raise ValueError('boundary copy provenance is not the qualified capture producer')
        if r['completed'] is not True: raise ValueError('boundary completion not observed')
        wire=integer(r['wire_bytes'],'boundary wire observation',minimum=1)
        integer(r['staging_bytes'],'boundary staging observation',minimum=1)
        if want['wire_bytes'] is not None and wire!=want['wire_bytes']: raise ValueError('boundary wire observation differs from frozen exact contract')
        _copy_legs(plan,r,want,tokens[owner[name]],materializations)
    return indexed


def _copy_legs(plan,observation,want,token,materializations=None):
    if materializations is None: materializations={}
    links={r.link_id:r for r in plan.profiles.snapshot.links}
    memories={r.memory_id:r for r in plan.profiles.snapshot.memory_resources}
    bindings={b.binding_id:b for p in plan.participants for b in p.bindings}
    copies=_array(observation['copies'],'actual boundary copies',len(want['link_legs'])+1)
    if len(copies)!=len(want['link_legs']): raise ValueError('actual boundary copy coverage mismatch')
    wire_total=0; staging_total=0
    fields=('sequence','source_materialization_id','target_materialization_id','source_host','target_host','source_memory_id','target_memory_id','link_id','path','protocol',
        'wire_bytes','staging_bytes','completed','invocation_token','shape','strides','representation',
        'alias_base_id','view_offset','base_extent_bytes','ordering','dependencies_observed','state_dependencies_observed')
    for i,(copy,lid) in enumerate(zip(copies,want['link_legs'])):
        if type(copy) is not dict or not {'source_materialization_id','target_materialization_id'}<=set(copy):
            raise ValueError('actual boundary copy continuity observations required')
        keys(copy,fields,'actual boundary copy')
        for key in ('source_materialization_id','target_materialization_id'): text(copy[key],'actual boundary copy continuity')
        if copy['source_materialization_id']==copy['target_materialization_id']:
            raise ValueError('actual boundary copy continuity aliases different physical endpoints')
        if i and (copies[i-1]['target_materialization_id']!=copy['source_materialization_id'] or copies[i-1]['target_memory_id']!=copy['source_memory_id']):
            raise ValueError('actual boundary copy continuity between staged legs mismatch')
        source_host,target_host=want['route_hosts'][i:i+2]
        if (copy['source_host'],copy['target_host'])!=(source_host,target_host): raise ValueError('actual boundary copy route mismatch')
        link=links[lid]
        if (copy['link_id'],copy['path'],copy['protocol'])!=(lid,link.path,link.protocol): raise ValueError('actual boundary copy link mismatch')
        if type(copy['sequence']) is not int or copy['sequence']!=i or copy['ordering']!=want['ordering'] or copy['invocation_token']!=token:
            raise ValueError('actual boundary copy ordering/invocation mismatch')
        for field,host,endpoint_binding in (('source_memory_id',source_host,want['producer_binding'] if i==0 else None),
                ('target_memory_id',target_host,want['consumer_binding'] if i==len(copies)-1 else None)):
            memory=memories.get(copy[field])
            if memory is None or memory.host_id!=host or (endpoint_binding is not None and memory.memory_id!=bindings[endpoint_binding].memory_id):
                raise ValueError('actual boundary copy memory ownership mismatch')
            if endpoint_binding is None and memory.kind!='ram': raise ValueError('actual boundary copy memory staging must be host RAM')
        # Repeated staging IDs are valid, but an ID is physical, not logical.
        for side,host in (('source',source_host),('target',target_host)):
            name=copy[side+'_materialization_id']; physical=(host,copy[side+'_memory_id'])
            if materializations.setdefault(name,physical)!=physical:
                raise ValueError('actual boundary copy materialization physical identity/ownership mismatch')
        if not _same(copy['dependencies_observed'],want['dependencies']) or not _same(copy['state_dependencies_observed'],want['state_dependencies']):
            raise ValueError('actual boundary copy dependency mismatch')
        if not _same(copy['shape'],want['shape']) or not _same(copy['strides'],want['strides']) or copy['representation']!=want['representation']:
            raise ValueError('actual boundary copy alias layout mismatch')
        text(copy['alias_base_id'],'actual boundary copy alias base')
        offset=integer(copy['view_offset'],'actual boundary copy alias offset')
        extent=integer(copy['base_extent_bytes'],'actual boundary copy alias extent',minimum=1)
        if offset+want['logical_bytes']>extent: raise ValueError('actual boundary copy alias range mismatch')
        if copy['completed'] is not True: raise ValueError('actual boundary copy completion not observed')
        wire_total+=integer(copy['wire_bytes'],'actual boundary copy bytes',minimum=1)
        staging_total+=integer(copy['staging_bytes'],'actual boundary copy bytes staging',minimum=1)
    if wire_total!=observation['wire_bytes'] or staging_total!=observation['staging_bytes']:
        raise ValueError('actual boundary copy bytes total mismatch')


def reconcile_materialization(plan, observations, *, source_receipts, mode='live',
                              clock=None) -> MaterializationReceipt:
    """Complete global reconciliation; no re-admission, fallback or I/O.

    source_receipts are independently verified Slice4A runner outputs, NOT
    observer-supplied expected maps. Range SHA joins prove byte identity only;
    physical inventory must still satisfy this entire owned capture contract.
    Receipt counts/digests describe exact inventory, not memory-fit or requests.
    """
    rows=_owned_data(plan,observations,mode,_now(mode,clock))
    ranges,sources=_source_ranges(plan,rows,source_receipts)
    tensors=_materials(plan,rows,'tensors',plan.candidate.assignments,ranges)
    states=_materials(plan,rows,'states',plan.candidate.required_state,ranges)
    buffers=_buffers(rows,tensors,states)
    auxiliary=_auxiliary(plan,rows)
    # _buffers already enforces global tensor/state materialization identities.
    hosts={p.participant_id:p.host_id for p,_ in rows}
    materializations={r['materialization_id']:(hosts[pid],r['contract']['memory_id'])
        for pid,r in list(tensors.values())+list(states.values())}
    boundaries=_boundaries(plan,rows,materializations)
    expected=freeze(dict(subject=_subject(plan),bindings=[_expected_bindings(p,plan) for p,_ in rows],
        tensors=[_plain(a) for a in plan.candidate.assignments],states=[_plain(a) for a in plan.candidate.required_state],
        boundaries=[_plain(b) for b in plan.candidate.boundaries],
        auxiliary=[_plain(c) for c in plan.candidate.charges if c.phase=='serve']))
    # Inventory order is nonsemantic. Preserve original wire digests separately;
    # normalized evidence retains producer/time/scope/dependencies, never erases
    # a declared synthetic label or promotes logical demand to wire measurement.
    normalized=[]
    for p,data in rows:
        data['evidence'].pop('record_digest')
        for field,key in (('tensors','state_id'),('states','state_id'),('boundaries','semantic_id')):
            data[field].sort(key=lambda r:r['contract'][key])
        for field,key in (('buffers','buffer_id'),('auxiliary','allocation_id')):
            data[field].sort(key=lambda r:r[key])
        data['capabilities'].sort()
        data['source_receipt_digest']=sha256(sources[p.participant_id])
        normalized.append(data)
    observed=freeze(dict(observations=normalized,source_receipts=sources))
    classes=tuple(sorted({(data['evidence']['evidence_class'],data['evidence']['source_scope']) for _,data in rows}))
    counts=tuple(sorted(Counter(row['contract']['binding_id'] for _,row in tensors.values()).items()))
    return MaterializationReceipt(sha256(expected),sha256(observed),expected,observed,
        len(tensors),len(states),len(buffers),len(auxiliary),len(boundaries),counts,
        tuple(sorted((o.owned.participant_id,dict(dict(o.payload)['evidence'])['record_digest']) for o in observations)),
        classes,mode=='live')


__all__=['BindingTransport','TransportReply','ProcessIdentity','BindingReceipt','OwnedObservation',
    'MaterializationReceipt','validate_preflight','preflight_bindings','gather_owned_observation',
    'reconcile_bindings','reconcile_materialization']

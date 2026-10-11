"""Bounded Qwen3.8 Q8_0 strategy at an exact unmodified native source pin.

Metadata and source semantics are CALCULATED, never weight/kernel/physical proof.
Only one explicitly selected fixed candidate is emitted. No execution or search.
"""
from __future__ import annotations
from dataclasses import dataclass, replace
from .config import ModelIdentity, ProfiledOperatorConfig, profile_subject
from .metadata import MetadataIndex, _index, _public_members
from .source import _encoded_bytes, _validate_extents
from .plan import ResourceCharge, LegalCandidate, CapabilityRequirement, PHASES
from .profiles import thaw, integer, keys, text
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .phased_observation import StaticPlanContext
    from .plan import ProfiledOperatorPlan

STRATEGY_ID = 'qwen38-q8-fixed/1'
RUNTIME_PIN = 'b29c606e28a01b1bc8c1351026a0fa6e616bf6c4'
RUNTIME_TREE = '950999fe62b7fe55f44ab5b7394e3c8542f37f12'
METADATA_DIGEST = '194c818cb0bbb6016f0a282596131040c7afbdb294f9962e7f9e262d7128239e'
SOURCE_EVIDENCE = 'source:'+RUNTIME_PIN
OUTPUTS = ('output.weight','output_hc_down.weight','output_hc_norm.weight','output_hc_up.weight')
BANKS = ('ffn_down_exps.weight','ffn_gate_exps.weight','ffn_up_exps.weight')
PLE_SUPPORT = ('ple_conv1d.weight','ple_key.weight','ple_norm_conv.weight','ple_norm_key.weight','ple_norm_query.weight','ple_value.weight')
LARGEST_BANK = 891289600


@dataclass(frozen=True)
class WeightAssignment:
    state_id: str
    member: str
    absolute_offset: int
    encoded_bytes: int
    ggml_type: int
    shape: tuple[int, ...]
    binding_id: str
    memory_id: str
    authority: str = 'immutable-public-source/1'


@dataclass(frozen=True)
class RequiredState:
    state_id: str
    binding_id: str
    memory_id: str
    representation: str
    lower_bound_bytes: int | None
    authority: str = 'native-single-sequence/1'
    reconstructible: bool = False
    dependencies: tuple[str, ...] = ()


@dataclass(frozen=True)
class Boundary:
    semantic_id: str
    before_layer: int
    producer_binding: str
    consumer_binding: str
    shape: tuple[int, ...]
    representation: str
    logical_bytes: int
    wire_bytes: int | None
    strides: tuple[int, ...]
    alias_rule: str
    ordering: str
    dependencies: tuple[str, ...]
    state_dependencies: tuple[str, ...]
    route_hosts: tuple[str, ...]
    link_legs: tuple[str, ...]
    source_citation: str


@dataclass(frozen=True)
class Q8Contract:
    selection: str
    bindings: tuple
    workload: object
    route: str
    metadata_digest: str
    header_identities: tuple
    model_metadata: tuple
    binding_hosts: tuple
    links: tuple


def _owner(name, contract):
    binding = dict(contract.bindings)
    if name in ('token_embd.weight','per_layer_token_embd.weight'): return binding['loader']
    layer = int(name.split('.')[1]) if name.startswith('blk.') else 48
    return binding['loader'] if layer<14 else binding['remote_gpu'] if contract.selection=='one-gpu' and layer>=45 else binding['remote_cpu']


def _states(contract):
    h = dict(contract.model_metadata)
    w = contract.workload
    cache = thaw(w.cache_settings)
    rows = cache['recurrent_rows']*(1+cache['rs_sequences'])
    cells = cache['attention_cells']*cache['cache_streams']
    result=[]
    for layer in range(h['qwen4exp.block_count']):
        owner = _owner(f'blk.{layer}.state',contract)
        dep = (f'complete-layer:{layer}','client-control')
        if layer%h['qwen4exp.full_attention_interval']==h['qwen4exp.full_attention_interval']-1:
            for name, dim in (('cache_k',h['qwen4exp.attention.key_length']*h['qwen4exp.attention.head_count_kv']),
                              ('cache_v',h['qwen4exp.attention.value_length']*h['qwen4exp.attention.head_count_kv']),
                              ('cache_idx_k',h['qwen4exp.attention.indexer.key_length'])):
                result.append(RequiredState(f'{name}_l{layer}',owner.binding_id,owner.memory_id,'f16',2*dim*cells,
                    dependencies=dep+('attention-cell-layout','raw-indexer-key-layout')))
        else:
            r = (h['qwen4exp.ssm.conv_kernel']-1)*(h['qwen4exp.ssm.inner_size']+2*h['qwen4exp.ssm.group_count']*h['qwen4exp.ssm.state_size'])
            s = h['qwen4exp.ssm.state_size']*h['qwen4exp.ssm.inner_size']
            for name,dim in (('cache_r',r),('cache_s',s)):
                result.append(RequiredState(f'{name}_l{layer}',owner.binding_id,owner.memory_id,'f32',4*dim*rows,dependencies=dep+('recurrent-cell-lineage',)))
            if layer in h['qwen4exp.ple.layers']:
                ple=(h['qwen4exp.ple.conv_kernel']-1)*h['qwen4exp.ple.ngram_size']*h['qwen4exp.hyper_connection.count']*h['qwen4exp.embedding_length']
                result.append(RequiredState(f'cache_ple_r_l{layer}',owner.binding_id,owner.memory_id,'f32',4*ple*rows,dependencies=dep+('token-predecessors',)))
    loader=dict(contract.bindings)['loader']
    final=dict(contract.bindings)['remote_gpu' if contract.selection=='one-gpu' else 'remote_cpu']
    result.extend((RequiredState('client-control',loader.binding_id,loader.memory_id,'native-cell-sequence-lineage/1',None,
        dependencies=('positions','output-selectors','attention-masks','kv-row-indices','recurrent-source-rollback-indices','qsa-maps-bias','token-predecessors')),
        RequiredState('final-output-state',final.binding_id,final.memory_id,'native-hc-mix-logits/1',None,dependencies=OUTPUTS)))
    return tuple(sorted(result,key=lambda s:s.state_id))


def _boundaries(contract):
    binding=dict(contract.bindings)
    hosts=dict(contract.binding_hosts)
    link=next(l for l in contract.links if {l.source_host_id,l.target_host_id}==set(hosts.values()))
    h=dict(contract.model_metadata); embd=h['qwen4exp.embedding_length']; hc=h['qwen4exp.hyper_connection.count']
    n=contract.workload.microbatch
    shape=(embd,hc,n); strides=(4,4*embd,4*embd*hc)
    state=_states(contract)
    edges=[(14,binding['loader'],binding['remote_cpu'])]
    if contract.selection=='one-gpu': edges.append((45,binding['remote_cpu'],binding['remote_gpu']))
    result=[]
    for before,src,dst in edges:
        route=(hosts[src.binding_id],hosts[dst.binding_id]) if before==14 else (hosts[src.binding_id],hosts[binding['loader'].binding_id],hosts[dst.binding_id]) if contract.route=='client-mediated' else (hosts[src.binding_id],hosts[dst.binding_id])
        legs=(link.link_id,) if before==14 else (link.link_id,link.link_id) if contract.route=='client-mediated' else ()
        result.append(Boundary(f'completed-layer-{before-1}/{before}',before,src.binding_id,dst.binding_id,
            shape,'f32-completed-hc-residual/1',4*embd*hc*n,None,strides,
            'view-base-range-and-layout-must-be-observed','completed-layer-before-consumer;plan-epoch/request/ubatch-fenced',
            ('positions','output-selectors','attention-masks','kv-row-indices','recurrent-source-rollback-indices','qsa-maps-bias','token-predecessors','client-control'),
            tuple(s.state_id for s in state if s.binding_id in (src.binding_id,dst.binding_id)),route,legs,
            f'{RUNTIME_PIN}:src/models/qwen4exp.cpp:264-440;ggml/src/ggml-backend.cpp:944-948'))
    return tuple(result)


def _assignments(placements, metadata, contract):
    tensors={t.state_id:t for t in metadata.tensors}
    bindings={b.binding_id:b for _,b in contract.bindings}
    result=[]
    for row in placements:
        binding=bindings[row.binding_id]
        for name,member,offset,length in row.state_ranges:
            t=tensors[name]
            result.append(WeightAssignment(name,member,offset,length,t.ggml_type,t.shape,binding.binding_id,binding.memory_id))
    return tuple(sorted(result,key=lambda a:a.state_id))


def bound_capability(charge, amount):
    """Exact token inside an authenticated, dependency-scoped runtime profile."""
    return f'budget-bound:{charge.allocation_id}:{charge.memory_id}:{charge.role}:{amount}:{METADATA_DIGEST}'


def _bound_evidence(config, charge, amount, evidence_id):
    memory=next(m for m in config.profiles.snapshot.memory_resources if m.memory_id==charge.memory_id)
    runtimes=[r for r in config.profiles.snapshot.runtime_capabilities if r.evidence_id==evidence_id and r.host_id==memory.host_id]
    if len(runtimes)!=1 or bound_capability(charge,amount) not in runtimes[0].capabilities:
        raise ValueError('bound evidence scope: amount/role/phase/domain/metadata/runtime must be authenticated: '+charge.allocation_id)
    evidence=next(e for e in config.profiles.snapshot.evidence if e.evidence_id==evidence_id)
    if dict(evidence.dependencies).get('memory:'+memory.memory_id+':physical_id')!=memory.physical_id:
        raise ValueError('bound physical memory scope: '+charge.allocation_id)


def _charges(config, contract, assignments, states, boundaries, options):
    charges=[]; requirements=[]
    by_binding={b.binding_id:b for _,b in contract.bindings}
    def add(aid,mid,role,amount,phases,*,evidence=SOURCE_EVIDENCE):
        for phase in phases:
            charges.append(ResourceCharge(aid+'/'+phase,mid,role,amount,phase,evidence))
    resident=('load','serve','cleanup')
    for bid,b in by_binding.items():
        weights=sum(a.encoded_bytes for a in assignments if a.binding_id==bid and a.state_id!='per_layer_token_embd.weight')
        add('encoded-weights:'+bid,b.memory_id,'required',weights,resident)
        local=sum(s.lower_bound_bytes for s in states if s.binding_id==bid and s.lower_bound_bytes is not None)
        add('state-lower-bound:'+bid,b.memory_id,'required',local,('serve','cleanup'))
        for label in ('backend-allocation-repacking','state-allocator-overhead','graph','workspace','observer'):
            add(label+':'+bid,b.memory_id,'required',None,resident,evidence='unknown:'+label)
        for capability in ('q8-kernels-qualified','bf16-indexer-qualified','gdn-ssm-conv-qualified',
                           'qsa-top-k-qualified:'+str(thaw(contract.workload.cache_settings)['attention_cells']),
                           'qsa-dense-attention-qualified:'+str(thaw(contract.workload.cache_settings)['attention_cells']),
                           'unmodified-source-tree:'+RUNTIME_TREE,'effective-argv-environment-qualified',
                           'complete-physical-observer','no-unplanned-host-mirror','native-weight-state-map'):
            requirements.append(CapabilityRequirement(b.runtime_id,capability,capability+':'+bid))
    for s in states:
        if s.lower_bound_bytes is None:
            add(s.state_id,s.memory_id,'required',None,('serve','cleanup'),evidence='unknown:'+s.state_id)
    loader=dict(contract.bindings)['loader']; remote_cpu=dict(contract.bindings)['remote_cpu']
    for p in config.participants:
        # Complete source is a bounded selected backend scaffold, not eligibility.
        for backing in p.backing:
            add('source-backing:'+p.participant_id+':'+backing.member,backing.memory_id,'backing',backing.size_bytes,PHASES)
        ram=loader.memory_id if p.role=='client' else remote_cpu.memory_id
        add('verification-read-buffer:'+p.participant_id,ram,'transient',None,('verification',),evidence='unknown:verification-buffer')
        add('verification-page-residence:'+p.participant_id,ram,'required',None,('verification',),evidence='unknown:verification-residence')
        add('source-page-residence:'+p.participant_id,ram,'required',None,resident,evidence='unknown:source-residence')
        add('transport-envelope:'+p.participant_id,ram,'transient',None,('load',),evidence='unknown:transport-envelope')
    # Whole-file lazy mappings are virtual only, kept separate from PLE working set.
    total=sum(size for _,_,size in config.model.members)
    add('whole-source-mmap',loader.memory_id,'virtual',total,resident)
    add('PLE-active-backed-residence',loader.memory_id,'required',None,resident,evidence='unknown:PLE-residence')
    requirements.append(CapabilityRequirement(loader.runtime_id,'lazy-mmap','lazy PLE mmap support'))
    for label,mid in (('full-tensor-loader',loader.memory_id),('FNV-cache-message-staging',loader.memory_id),('remote-receive-staging',remote_cpu.memory_id)):
        add(label,mid,'transient',LARGEST_BANK,('load',))
    for boundary in boundaries:
        # Logical residual is only a lower bound. The complete split inventory,
        # repeated copies and side inputs require a runtime-scoped upper bound.
        add('boundary-wire:'+boundary.semantic_id,loader.memory_id,'virtual',None,('serve',),evidence='unknown:wire-bound')
        if boundary.before_layer==45 and contract.route=='client-mediated':
            add('boundary-bounce-lower-bound',loader.memory_id,'transient',boundary.logical_bytes,('serve',))
            add('boundary-bounce-overlap',loader.memory_id,'transient',None,('serve',),evidence='unknown:bounce-overlap')
        requirements.append(CapabilityRequirement(remote_cpu.runtime_id,'route:'+contract.route,'copy route '+contract.route))
    if options['rpc_cache']=='enabled':
        remote=next(p for p in config.participants if p.role=='remote')
        disk=remote.backing[0].memory_id
        add('assigned-cache-disk',disk,'optional',sum(r.length for r in remote.cache_ranges),PHASES)
        add('full-tensor-cache-hit-vector',remote_cpu.memory_id,'transient',LARGEST_BANK,('load',))
        add('cache-hit-vector-overlap',remote_cpu.memory_id,'transient',None,('load',),evidence='unknown:cache-vector-overlap')
    for mirror in options['host_mirrors']:
        add('host-mirror:'+mirror['allocation_id'],mirror['memory_id'],'optional',mirror['bytes'],('load','serve','cleanup'),evidence=mirror['evidence_id'])
    bounds={b['allocation_id']:b for b in options['bounds']}
    if set(bounds)-{c.allocation_id for c in charges}: raise ValueError('unknown budget allocation')
    resolved=[]
    for charge in charges:
        bound=bounds.get(charge.allocation_id)
        if bound is not None:
            if charge.bytes is not None and bound['bytes']<charge.bytes:
                raise ValueError('source-derived lower bound cannot be reduced: '+charge.allocation_id)
            _bound_evidence(config,charge,bound['bytes'],bound['evidence_id'])
            charge=replace(charge,bytes=bound['bytes'],evidence_id=bound['evidence_id'])
        if charge.allocation_id.startswith('host-mirror:'):
            _bound_evidence(config,charge,charge.bytes,charge.evidence_id)
        resolved.append(charge)
    return tuple(sorted(resolved,key=lambda c:c.allocation_id)),tuple(sorted(set(requirements),key=lambda r:(r.runtime_id,r.capability)))


def _expected_tensor_schema():
    """Exact named conversion descriptors, checked before pinned digest authority."""
    shared = {
        'ffn_down_exps.weight':(8,(640,2560,512)), 'ffn_gate_exps.weight':(8,(2560,640,512)),
        'ffn_up_exps.weight':(8,(2560,640,512)), 'ffn_down_shexp.weight':(8,(640,2560)),
        'ffn_gate_shexp.weight':(8,(2560,640)), 'ffn_up_shexp.weight':(8,(2560,640)),
        'ffn_gate_inp.weight':(0,(2560,512)), 'ffn_gate_inp_shexp.weight':(0,(2560,)),
    }
    for part in ('attn','ffn'):
        for suffix,typ,shape in (('down',8,(10240,320)),('up',8,(320,10240)),
                                 ('inject',8,(10240,4)),('norm',0,(10240,))):
            shared[f'hc_{part}_{suffix}.weight']=(typ,shape)
    recurrent={'attn_gate.weight':(8,(2560,6144)), 'attn_qkv.weight':(8,(2560,10240)),
        'ssm_a':(0,(48,)), 'ssm_alpha.weight':(8,(2560,48)), 'ssm_beta.weight':(8,(2560,48)),
        'ssm_conv1d.weight':(0,(4,10240)), 'ssm_dt.bias':(0,(48,)),
        'ssm_norm.weight':(0,(128,)), 'ssm_out.weight':(8,(6144,2560))}
    attention={'attn_k.weight':(8,(2560,512)), 'attn_v.weight':(8,(2560,512)),
        'attn_k_norm.weight':(0,(256,)), 'attn_q_norm.weight':(0,(256,)),
        'attn_q.weight':(8,(2560,12288)), 'attn_output.weight':(8,(6144,2560)),
        'indexer.k_norm.weight':(0,(128,)), 'indexer.q_norm.weight':(0,(128,)),
        'indexer.k_proj.weight':(30,(2560,128)), 'indexer.q_proj.weight':(30,(2560,512))}
    ple={'ple_conv1d.weight':(0,(4,10240)), 'ple_key.weight':(8,(2560,10240)),
         'ple_norm_conv.weight':(0,(10240,)), 'ple_norm_key.weight':(0,(10240,)),
         'ple_norm_query.weight':(0,(10240,)), 'ple_value.weight':(8,(2560,2560))}
    result={}
    for layer in range(48):
        layer_schema={**shared,**(attention if layer%4==3 else recurrent),**(ple if layer==1 else {})}
        result.update((f'blk.{layer}.{name}',shape) for name,shape in layer_schema.items())
    result.update({'token_embd.weight':(8,(2560,248320)), 'per_layer_token_embd.weight':(8,(160,320001536)),
                   'output.weight':(8,(2560,248320)), 'output_hc_down.weight':(8,(10240,320)),
                   'output_hc_norm.weight':(0,(10240,)), 'output_hc_up.weight':(8,(320,10240))})
    return result


def _validate_metadata(metadata):
    rows=metadata.tensors
    names=[t.state_id for t in rows]; inventory=set(names)
    if len(names)!=len(inventory): raise ValueError('duplicate metadata tensor')
    expected=_expected_tensor_schema()
    bank_names={f'blk.{layer}.{suffix}' for layer in range(48) for suffix in BANKS}
    if {name for name in inventory if '_exps' in name}!=bank_names:
        raise ValueError('expert coverage: exact three complete banks per each of 48 layers required')
    if not {'token_embd.weight','per_layer_token_embd.weight'}<=inventory: raise ValueError('PLE/input coverage')
    if {name for name in inventory if name.startswith('output')}!=set(OUTPUTS): raise ValueError('output coverage')
    if {name for name in inventory if '.ple_' in name}!={f'blk.1.{name}' for name in PLE_SUPPORT}:
        raise ValueError('PLE support coverage')
    if inventory!=set(expected): raise ValueError('layer tensor coverage: complete exact named inventory required')
    for row in rows:
        typ,shape=expected[row.state_id]
        if row.shape!=shape or row.ggml_type!=typ or type(row.ggml_type) is not int:
            raise ValueError(('expert shape' if row.state_id in bank_names else 'tensor shape/type')+': '+row.state_id)
        if type(row.encoded_bytes) is not int or row.encoded_bytes!=_encoded_bytes(row.shape,row.ggml_type):
            raise ValueError('encoded extent: '+row.state_id)
    public=_public_members()
    identities=tuple((r['member'],0,r['range_end'],r['header_sha256'],r['object_bytes'],r['object_sha256']) for r in public)
    members=tuple((r['member'],r['object_sha256'],r['object_bytes']) for r in public)
    if metadata.header_identities!=identities: raise ValueError('model header identity authentication')
    if (metadata.source.source_id,metadata.source.revision,metadata.source.representation)!=('unsloth/Qwen3.8-Flash-Next-GGUF','38bb39ee97821de2c9009abb7e93950eec396e66','Q8_0') or metadata.source.members!=members:
        raise ValueError('model member identity authentication')
    # Next-offset and final-object coverage independent of arithmetic totals.
    for member in public:
        group=[r for r in rows if r.member==member['member']]
        start=(member['range_end']+32)//32*32
        _validate_extents(group,member['object_bytes'],start,32)
    if any(t.member not in {r['member'] for r in public} for t in rows): raise ValueError('unknown source member')
    authenticated=_index(metadata.model_metadata,rows)
    if authenticated!=metadata or metadata.metadata_digest!=METADATA_DIGEST:
        raise ValueError('metadata descriptor authentication: pinned full descriptor/hparam digest differs')


def _validate_options(config,metadata):
    if config.strategy_id!=STRATEGY_ID: raise ValueError('unsupported strategy id')
    if config.selection not in ('one-gpu','cpu-only'): raise ValueError('unsupported explicit selection')
    options=thaw(config.strategy_options)
    base_fields=('bindings','route','source_contract','rpc_cache','host_mirrors','bounds','startup_timeout_seconds')
    keys(options,base_fields+('observer',) if 'observer' in options else base_fields,'strategy options')
    observer=options.get('observer')
    if observer is not None:
        # #302 explicit derived-build qualification for the collected /2 path.
        # Optional: the legacy /1 observer path and all existing configs are
        # unchanged; the collected runner refuses without it.
        if not isinstance(observer,dict) or set(observer)!={'manifest_path','executable_path'}:
            raise ValueError('observer options: exact manifest/executable deployment paths required')
        for value in observer.values():
            text(value,'observer deployment path')
    keys(options['bindings'],('loader','remote_cpu','remote_gpu') if config.selection=='one-gpu' else ('loader','remote_cpu'),'strategy bindings')
    if options['route'] not in ('client-mediated','server-local'): raise ValueError('unsupported explicit copy route')
    if options['source_contract']!='full-source-both-hosts/1': raise ValueError('unsupported full-source backing contract')
    if options['rpc_cache'] not in ('disabled','enabled'): raise ValueError('unsupported explicit RPC cache mode')
    integer(options['startup_timeout_seconds'],'startup timeout',minimum=1,maximum=3600)
    w=config.workload; cache=thaw(w.cache_settings)
    keys(cache,('k','v','recurrent_rows','rs_sequences','cache_streams','attention_cells','text_only','kv_offload'),'state/workload cache settings')
    if w.slots!=1 or not 1<=w.microbatch<=w.batch<=w.context<=262144:
        raise ValueError('state/workload: single-slot bounded text sequence required')
    if cache['k']!='f16' or cache['v']!='f16' or cache['text_only'] is not True or cache['kv_offload'] is not True:
        raise ValueError('state/workload: f16 caches, text-only and explicit kv-offload required')
    for name in ('recurrent_rows','rs_sequences','cache_streams','attention_cells'): integer(cache[name],'state/workload '+name)
    if cache['recurrent_rows']!=1 or cache['rs_sequences']!=0 or cache['cache_streams']!=1 or cache['attention_cells']!=(w.context+255)//256*256:
        raise ValueError('state/workload: native single-sequence rows, rollback and padded cells mismatch')
    bindings={b.binding_id:(p,b) for p in config.participants for b in p.bindings}
    if len(bindings)!=len(options['bindings']) or set(bindings)!=set(options['bindings'].values()):
        raise ValueError('fixed binding coverage')
    computes={c.compute_id:c for c in config.profiles.snapshot.compute_units}
    memories={m.memory_id:m for m in config.profiles.snapshot.memory_resources}
    runtimes={r.runtime_id:r for r in config.profiles.snapshot.runtime_capabilities}
    for key,bid in options['bindings'].items():
        p,b=bindings[bid]
        gpu=key=='remote_gpu'
        if p.role!=('client' if key=='loader' else 'remote'):
            raise ValueError('fixed binding participant role')
        if computes[b.compute_id].backend!=('cuda' if gpu else 'cpu') or memories[b.memory_id].kind!=('vram' if gpu else 'ram'):
            raise ValueError('fixed binding backend/memory legality')
        if b.native_selector!=('CUDA0' if gpu else 'CPU') or b.visible_selector!=('CPU' if key=='loader' else 'RPC1' if gpu else 'RPC0'):
            raise ValueError('fixed native/visible selector translation')
        if runtimes[b.runtime_id].source_revision!=RUNTIME_PIN: raise ValueError('runtime source pin mismatch')
        if runtimes[b.runtime_id].route!=options['route']: raise ValueError('runtime route context mismatch')
    if config.model!=metadata.source or config.metadata.digest!=metadata.metadata_digest:
        raise ValueError('model/metadata identity mismatch')
    names=[name for p in config.placement for name in p.state_ids]
    if len(names)!=len(set(names)): raise ValueError('duplicate ownership')
    if set(names)!={t.state_id for t in metadata.tensors}: raise ValueError('ownership coverage')
    for p in config.participants:
        if sorted((b.member,b.sha256,b.size_bytes) for b in p.backing)!=list(metadata.source.members):
            raise ValueError('full-source backing: all six authenticated member identities exactly once on each host')
        if options['rpc_cache']=='disabled' and p.cache_ranges: raise ValueError('disabled RPC cache has descriptors')
        if p.role=='client' and p.cache_ranges: raise ValueError('client cache ranges unsupported')
    if options['rpc_cache']=='enabled':
        remote=next(p for p in config.participants if p.role=='remote')
        assigned={row.unit_id:row for row in config.placement if bindings[row.binding_id][0].role=='remote'}
        actual=[r.state_id for r in remote.cache_ranges]
        required=[name for row in assigned.values() for name in row.state_ids]
        if len(actual)!=len(set(actual)) or set(actual)!=set(required): raise ValueError('cache state coverage')
        descriptors={name:(row.unit_id,member,offset,length) for row in assigned.values() for name,member,offset,length in row.state_ranges}
        for r in remote.cache_ranges:
            if descriptors[r.state_id]!=(r.unit_id,r.member,r.offset,r.length): raise ValueError('cache source range coverage')
    for field,expected in (('bounds',('allocation_id','bytes','evidence_id')),('host_mirrors',('allocation_id','memory_id','bytes','evidence_id'))):
        if not isinstance(options[field],list): raise ValueError(field+' must be array')
        seen=set()
        for row in options[field]:
            keys(row,expected,'host mirror' if field=='host_mirrors' else 'budget bound')
            text(row['allocation_id'],'allocation_id'); integer(row['bytes'],'bound bytes'); text(row['evidence_id'],'bound evidence_id')
            if row['allocation_id'] in seen: raise ValueError('duplicate '+field+' allocation_id')
            seen.add(row['allocation_id'])
            if field=='host_mirrors':
                if row['memory_id'] not in memories or memories[row['memory_id']].kind!='ram': raise ValueError('host mirror memory domain')
    return options


def validate_q8_ownership(candidate, metadata):
    _validate_metadata(metadata)
    contract,=candidate.semantic_contract
    if not isinstance(contract,Q8Contract) or candidate.candidate_id!=contract.selection:
        raise ValueError('fixed selection contract')
    tensors={t.state_id:t for t in metadata.tensors}
    names=[a.state_id for a in candidate.assignments]
    if len(names)!=len(set(names)): raise ValueError('duplicate ownership')
    if set(names)!=set(tensors): raise ValueError('ownership coverage')
    by_member={}
    for assignment in candidate.assignments:
        t=tensors[assignment.state_id]
        if (assignment.member,assignment.absolute_offset,assignment.encoded_bytes,assignment.ggml_type,assignment.shape)!=(t.member,t.absolute_offset,t.encoded_bytes,t.ggml_type,t.shape):
            raise ValueError('source range/descriptor substitution: '+assignment.state_id)
        owner=_owner(t.state_id,contract)
        if (assignment.binding_id,assignment.memory_id)!=(owner.binding_id,owner.memory_id):
            raise ValueError(('output owner' if t.state_id in OUTPUTS else 'whole-layer ownership' if t.state_id.startswith('blk.') else 'PLE/input owner')+': '+t.state_id)
        if assignment.authority!='immutable-public-source/1': raise ValueError('weight authority')
        by_member.setdefault(t.member,[]).append(assignment)
    for rows in by_member.values():
        rows.sort(key=lambda a:a.absolute_offset)
        if any(a.absolute_offset+a.encoded_bytes>b.absolute_offset for a,b in zip(rows,rows[1:])):
            raise ValueError('overlapping source ownership ranges')
    if candidate.required_state!=_states(contract): raise ValueError('required local state: exact native state/authority/representation coverage')
    if candidate.boundaries!=_boundaries(contract):
        raise ValueError('boundary schema: exact shape/layout/authority/route/side-input source contract required')
    h=dict(metadata.model_metadata); n=contract.workload.microbatch
    expected_cuts=(14,45) if contract.selection=='one-gpu' else (14,)
    if tuple(b.before_layer for b in candidate.boundaries)!=expected_cuts: raise ValueError('boundary schema: exact completed-layer cuts')
    for b in candidate.boundaries:
        expected_shape=(h['qwen4exp.embedding_length'],h['qwen4exp.hyper_connection.count'],n)
        src=_owner(f'blk.{b.before_layer-1}.state',contract); dst=_owner(f'blk.{b.before_layer}.state',contract)
        if (b.shape,b.representation,b.logical_bytes,b.wire_bytes,b.producer_binding,b.consumer_binding)!=(expected_shape,'f32-completed-hc-residual/1',4*expected_shape[0]*expected_shape[1]*n,None,src.binding_id,dst.binding_id):
            raise ValueError('boundary schema: wide HC residual not narrow hidden vector')
        if b.dependencies!=('positions','output-selectors','attention-masks','kv-row-indices','recurrent-source-rollback-indices','qsa-maps-bias','token-predecessors','client-control'):
            raise ValueError('boundary schema: side-input/control dependencies')


def q8_candidates(config, metadata):
    _validate_metadata(metadata)
    options=_validate_options(config,metadata)
    bindings={b.binding_id:b for p in config.participants for b in p.bindings}
    chosen=tuple(sorted((key,bindings[bid]) for key,bid in options['bindings'].items()))
    contract=Q8Contract(config.selection,chosen,config.workload,options['route'],metadata.metadata_digest,metadata.header_identities,metadata.model_metadata,
        tuple(sorted((b.binding_id,p.host_id) for p in config.participants for b in p.bindings)),config.profiles.snapshot.links)
    assignments=_assignments(config.placement,metadata,contract)
    states=_states(contract)
    boundaries=_boundaries(contract)
    charges,requirements=_charges(config,contract,assignments,states,boundaries,options)
    unsupported=()
    if config.selection=='one-gpu' and options['route']=='server-local':
        unsupported=(f'UNSUPPORTED_PLACEMENT: server-local CPU/CUDA copy unavailable at {RUNTIME_PIN}:ggml/src/ggml-rpc/ggml-rpc.cpp:1621;ggml/src/ggml-cuda/ggml-cuda.cu:820-843',)
    # Inventory normalization belongs to the strategy, not generic admission.
    from .profiles import freeze
    normalized_options = {**options,
        'bounds':sorted(options['bounds'],key=lambda row:row['allocation_id']),
        'host_mirrors':sorted(options['host_mirrors'],key=lambda row:row['allocation_id'])}
    candidate=LegalCandidate(config.selection,assignments,states,boundaries,charges,requirements,
        (options['source_contract'],RUNTIME_PIN,RUNTIME_TREE,metadata.source,metadata.header_identities,NativeQ8Options(config.selection)),
        subject=profile_subject(config,profile_mode=config.profile_mode),required_charge_ids=tuple(c.allocation_id for c in charges),
        calculated_evidence=(SOURCE_EVIDENCE,),unsupported=unsupported,semantic_contract=(contract,),
        canonical_strategy_options=freeze(normalized_options))
    validate_q8_ownership(candidate,metadata)
    return (candidate,)


@dataclass(frozen=True)
class Q8PersistentCache:
    """CALCULATED named cache expectation, not an allocation/initialization fact.

    native_dimensions uses GGML's four ne dimensions, including trailing ones;
    state.lower_bound_bytes excludes backend padding/extent and residency.
    Stream views do not introduce additional physical cache expectations.
    """
    state: RequiredState
    native_name: str
    ggml_type: int
    native_dimensions: tuple[int, int, int, int]
    source_sites: tuple[str, ...]
    phase: str = 'persistent-pre-request-expectation'


@dataclass(frozen=True)
class Q8LogicalComposite:
    """Unresolved logical obligation, not a persistent/completed native tensor."""
    state: RequiredState
    phase: str = 'unresolved-phase-partition'


@dataclass(frozen=True)
class Q8StaticInventory:
    """Description only: no dispatch, output acceptance or source-byte proof.

    Startup reservation/output containers do not establish request computation.
    No component capacities or allocator/reservation closure are supplied here;
    in particular initial client output staging is NOT assigned to final B state.
    """
    base_revision: str
    base_tree: str
    metadata_source: ModelIdentity
    metadata_digest: str
    header_identities: tuple
    model_metadata: tuple
    selection: str
    weights: tuple[WeightAssignment, ...]
    persistent_caches: tuple[Q8PersistentCache, ...]
    logical_composites: tuple[Q8LogicalComposite, ...]
    charges: tuple[ResourceCharge, ...]
    capability_requirements: tuple[CapabilityRequirement, ...]
    pending_dynamic: tuple[str, ...]
    charge_semantics: str = 'description-only/resource-obligations'


def _inventory_exact_value(actual, expected):
    """Complete typed equality; bool/int equality cannot mask a substitution."""
    from dataclasses import fields, is_dataclass
    if type(actual) is not type(expected): return False
    if is_dataclass(expected):
        return all(_inventory_exact_value(getattr(actual, f.name), getattr(expected, f.name))
                   for f in fields(expected))
    if isinstance(expected, tuple):
        return len(actual) == len(expected) and all(_inventory_exact_value(a, e) for a, e in zip(actual, expected))
    return actual == expected


def q8_static_inventory(config: ProfiledOperatorConfig, metadata: MetadataIndex, *,
                        candidate: LegalCandidate | None = None) -> Q8StaticInventory:
    """Pure source-derived pre-request expectations, never admission evidence.

    Re-derive from the typed config and authenticated public metadata. A supplied
    candidate must match EVERY freshly derived field, not totals or a digest.
    A new coherent config describes that new config only: original controller,
    process/source/build custody and freshness are later reconciliation work.
    BLOCKED/unknown-resource plans can still have these ownership expectations.
    """
    from dataclasses import fields
    from .config import WorkloadSettings
    from .plan import _immutable
    if type(config) is not ProfiledOperatorConfig or not _immutable(config):
        raise ValueError('typed inventory config: immutable ProfiledOperatorConfig required')
    if type(config.workload) is not WorkloadSettings:
        raise ValueError('typed inventory workload: WorkloadSettings required')
    for name in ('context', 'slots', 'batch', 'microbatch'):
        integer(getattr(config.workload, name), 'inventory workload ' + name)
    if type(metadata) is not MetadataIndex or not _immutable(metadata):
        raise ValueError('typed inventory metadata: immutable MetadataIndex required')
    if candidate is not None and type(candidate) is not LegalCandidate:
        raise ValueError('typed inventory candidate: LegalCandidate required')
    expected, = q8_candidates(config, metadata)
    if candidate is not None:
        for field in fields(LegalCandidate):
            if not _inventory_exact_value(getattr(candidate, field.name), getattr(expected, field.name)):
                raise ValueError('inventory candidate mismatch: ' + field.name)

    h = dict(metadata.model_metadata)
    cache = thaw(config.workload.cache_settings)
    rows = cache['recurrent_rows'] * (1 + cache['rs_sequences'])
    cells, streams = cache['attention_cells'], cache['cache_streams']
    states = {s.state_id:s for s in expected.required_state}
    persistent = []
    # Pinned constructors, not receipts: recurrent.cpp:101-113; kv-cache.cpp:
    # 209-244; hybrid-idx.cpp:49-68. Source pin is citation, not byte verification.
    recurrent_site = RUNTIME_PIN + ':src/llama-memory-recurrent.cpp:101-113'
    recurrent_shape_site = RUNTIME_PIN + ':src/llama-hparams.cpp:226-257'
    ple_shape_site = RUNTIME_PIN + ':src/llama-hparams.cpp:268-275'
    kv_site = RUNTIME_PIN + ':src/llama-kv-cache.cpp:230-244'
    kv_shape_site = RUNTIME_PIN + ':src/llama-hparams.cpp:156-166'
    idx_site = RUNTIME_PIN + ':src/llama-memory-hybrid-idx.cpp:49-68'
    def add(name, layer, typ, dimensions, sites):
        sid = f'{name}_l{layer}'
        state = states[sid]
        lower = (4 if typ == 0 else 2)
        for dim in dimensions: lower *= dim
        if (state.representation, state.lower_bound_bytes) != ('f32' if typ == 0 else 'f16', lower):
            raise ValueError('inventory native cache lower bound mismatch: ' + sid)
        persistent.append(Q8PersistentCache(state, sid, typ, dimensions, sites))

    for layer in range(h['qwen4exp.block_count']):
        if layer % h['qwen4exp.full_attention_interval'] == h['qwen4exp.full_attention_interval'] - 1:
            # GGML_TYPE_F16=1; selected FA off, no unified KV. Value dimensions
            # are constant for this authenticated model, even with v_trans.
            for name, dim in (('cache_k', h['qwen4exp.attention.key_length'] * h['qwen4exp.attention.head_count_kv']),
                              ('cache_v', h['qwen4exp.attention.value_length'] * h['qwen4exp.attention.head_count_kv'])):
                add(name, layer, 1, (dim, cells, streams, 1), (kv_site, kv_shape_site))
            # cache_%sk_l%d + name_tag="idx_"; raw single-head K, MLA skips V.
            add('cache_idx_k', layer, 1, (h['qwen4exp.attention.indexer.key_length'], cells, streams, 1),
                (idx_site, kv_site))
        else:
            # GGML_TYPE_F32=0; native 2D R/S history/state, four ne dimensions.
            r = (h['qwen4exp.ssm.conv_kernel'] - 1) * (h['qwen4exp.ssm.inner_size'] +
                 2 * h['qwen4exp.ssm.group_count'] * h['qwen4exp.ssm.state_size'])
            s = h['qwen4exp.ssm.state_size'] * h['qwen4exp.ssm.inner_size']
            add('cache_r', layer, 0, (r, rows, 1, 1), (recurrent_site, recurrent_shape_site))
            add('cache_s', layer, 0, (s, rows, 1, 1), (recurrent_site, recurrent_shape_site))
            if layer in h['qwen4exp.ple.layers']:
                ple = (h['qwen4exp.ple.conv_kernel'] - 1) * h['qwen4exp.ple.ngram_size'] * \
                      h['qwen4exp.hyper_connection.count'] * h['qwen4exp.embedding_length']
                add('cache_ple_r', layer, 0, (ple, rows, 1, 1), (recurrent_site, ple_shape_site))
    composites = tuple(Q8LogicalComposite(states[sid]) for sid in ('client-control', 'final-output-state'))
    if {r.state.state_id for r in persistent} | {r.state.state_id for r in composites} != set(states):
        raise ValueError('inventory state partition coverage')
    return Q8StaticInventory(RUNTIME_PIN, RUNTIME_TREE, metadata.source, metadata.metadata_digest,
        metadata.header_identities, metadata.model_metadata, config.selection, expected.assignments,
        tuple(sorted(persistent, key=lambda r:r.state.state_id)), composites, expected.charges,
        expected.capability_requirements, ('request-valued-control-and-state-authority',
        'same-request-graph-and-ubatch', 'actual-boundary-and-side-input-copies',
        'final-output-computation-and-custody', 'original-controller-and-owned-process-binding'))


@dataclass(frozen=True)
class NativeQ8Options:
    selection: str
    gpu_layers: int = 35
    split_mode: str = 'layer'
    fit: str = 'off'
    lazy_mode: str = 'on'
    load_mode: str = 'none'
    kv_offload: bool = True
    op_offload: bool = False
    flash_attention: str = 'off'
    kv_unified: bool = False

    def __post_init__(self):
        if (self.selection not in ('one-gpu','cpu-only') or type(self.gpu_layers) is not int or
                (self.gpu_layers,self.split_mode,self.fit,self.lazy_mode,self.load_mode,self.kv_offload,self.op_offload)
                !=(35,'layer','off','on','none',True,False) or type(self.kv_offload) is not bool or type(self.op_offload) is not bool
                or self.flash_attention!='off' or self.kv_unified is not False):
            raise ValueError('fixed native options: no adaptive fit, overrides, CPU-MoE or alternative split')

    @property
    def tensor_split(self):
        return (31,4) if self.selection=='one-gpu' else (1,)

    def layer_device_indices(self):
        # Source-exact float32 cumulative splits and upper_bound, output slot 48.
        # This demonstrates the native requested map, NOT observed placement.
        import bisect
        import struct
        def f32(value): return struct.unpack('f',struct.pack('f',value))[0]
        splits=[]; total=f32(0)
        for amount in self.tensor_split:
            total=f32(total+amount); splits.append(total)
        splits=[f32(v/total) for v in splits]
        start=49-self.gpu_layers
        return tuple(None if layer<start else bisect.bisect_right(splits,f32((layer-start)/self.gpu_layers)) for layer in range(49))


@dataclass(frozen=True)
class Q8LaunchSpec:
    executable: str
    executable_sha256: str
    execution_address: str
    rpc_endpoint: str
    device: str
    args: tuple[str, ...]
    rpc_args: tuple[str, ...]
    expected_assignments: tuple[WeightAssignment, ...]
    required_state: tuple[RequiredState, ...]
    boundaries: tuple[Boundary, ...]
    context: int
    slots: int
    startup_timeout_seconds: int
    executable_ready: bool
    deficits: tuple[str, ...]
    runtime_source: str = RUNTIME_PIN


def q8_llama_cpp_spec(plan):
    client=next(p for p in plan.participants if p.role=='client')
    remote=next(p for p in plan.participants if p.role=='remote')
    options=thaw(plan.strategy_options)
    native_options=NativeQ8Options(plan.selection)
    binding=dict(plan.candidate.semantic_contract[0].bindings)
    device=','.join(binding[k].visible_selector for k in ('remote_cpu','remote_gpu') if k in binding)
    native=','.join(binding[k].native_selector for k in ('remote_cpu','remote_gpu') if k in binding)
    w=plan.workload
    args=('--rpc',remote.rpc_endpoint,'--device',device,'--split-mode',native_options.split_mode,'--gpu-layers',str(native_options.gpu_layers),
          '--tensor-split',','.join(str(n) for n in native_options.tensor_split),'--fit',native_options.fit,'--lazy-mode',native_options.lazy_mode,'--load-mode',native_options.load_mode,
          '--no-op-offload','--kv-offload','--cache-type-k','f16','--cache-type-v','f16',
          '--flash-attn',native_options.flash_attention,'--no-kv-unified',
          '--model',client.source_path,'--ctx-size',str(w.context),'--batch-size',str(w.batch),
          '--ubatch-size',str(w.microbatch),'--parallel',str(w.slots),'--no-warmup')
    return Q8LaunchSpec(client.runtime_executable,client.runtime_sha256,client.execution_address,remote.rpc_endpoint,
        device,args,('--device',native),plan.candidate.assignments,plan.candidate.required_state,plan.candidate.boundaries,
        w.context,w.slots,options['startup_timeout_seconds'],plan.admission.execution_ready,plan.admission.deficits)

# Startup-only source expectations. These private tables are definitions, not
# observation IDs, executable expressions or caller-extensible catalog inputs.
_Q8_STARTUP_PARTITIONS = ('verification', 'startup-active', 'startup-reservation',
                          'load-only', 'request-only', 'backing', 'virtual', 'policy-reserve')
_Q8_STARTUP_LIFETIMES = ('verification-call', 'load-call', 'context', 'request', 'source-backing', 'policy')
_Q8_STARTUP_PASS_ORDER = ('graph.hc-pre', 'graph.hc-comb', 'graph.hc-post',
                         'graph.pp', 'graph.tg', 'graph.pp-again')
_Q8_STARTUP_SOURCES = {
    'output.ids': ('src/llama-context.cpp:llama_context::output_reserve:2093-2096,2197-2200',),
    'output.logits': ('src/llama-context.cpp:llama_context::output_reserve:2049-2071,2138-2144',),
    'output.embd': ('src/llama-context.cpp:llama_context::output_reserve:2057,2071,2146-2147',
                    'src/llama-model.cpp:llama_model_base::load_hparams:1229-1233',
                    'src/llama-hparams.h:llama_hparams::n_embd_out:241-242'),
    'output.sampling': ('src/llama-context.cpp:llama_context::output_reserve:2086-2091,2161-2194',),
    'output.base': ('src/llama-context.cpp:llama_context::output_reserve:2098-2101,2123-2135',
                    'ggml/src/ggml-rpc/ggml-rpc.cpp:ggml_backend_rpc_device_i:2220-2229'),
    'vocab.ids': ('src/llama-context.cpp:llama_context::llama_context:470-477',
                  'src/llama-model.h:LLAMA_LOAD_LOCALS:829-847',
                  'src/llama-vocab.cpp:llama_vocab::n_tokens:3887-3888'),
    'context.layers': ('src/llama-context.cpp:llama_context::llama_context:124-126',
                       'src/llama-context.h:llama_context:303-305'),
    'attn.cells': ('src/llama-kv-cache.cpp:llama_kv_cache::llama_kv_cache:84-87,137-154',
                   'src/llama-kv-cells.h:llama_kv_cells::resize/reset:13-20,38-75,486-524',
                   'src/llama-cparams.h:LLAMA_MAX_SEQ:8'),
    'idx.cells': ('src/llama-memory-hybrid-idx.cpp:llama_memory_hybrid_idx::llama_memory_hybrid_idx:49-68',
                  'src/llama-kv-cache.cpp:llama_kv_cache::llama_kv_cache:84-87,137-154',
                  'src/llama-kv-cells.h:llama_kv_cells::resize/reset:13-20,38-75,486-524'),
    'recurrent.cells': ('src/llama-memory-recurrent.cpp:llama_memory_recurrent::llama_memory_recurrent:20-39',
                        'src/llama-memory-recurrent.h:llama_memory_recurrent::mem_cell:69-94'),
    'recurrent.rs_idx': ('src/llama-memory-recurrent.cpp:llama_memory_recurrent::llama_memory_recurrent:20-39',
                         'src/llama-memory-recurrent.h:llama_memory_recurrent::rs_idx:76-77'),
    'cache.raw': ('src/llama-memory-recurrent.cpp:llama_memory_recurrent::llama_memory_recurrent:49-125',
                  'src/llama-kv-cache.cpp:llama_kv_cache::llama_kv_cache:230-244'),
    'cache.views': ('src/llama-kv-cache.cpp:llama_kv_cache::llama_kv_cache:276-295',
                    'src/llama-memory-hybrid-idx.cpp:llama_memory_hybrid_idx::llama_memory_hybrid_idx:49-68'),
    'cache.contexts': ('src/llama-memory-recurrent.cpp:llama_memory_recurrent::llama_memory_recurrent:49-125',
                       'src/llama-kv-cache.cpp:llama_kv_cache::llama_kv_cache:112-129,230-244'),
    'graph.hc-pre': ('src/llama-context.cpp:llama_context::resolve_fused_ops:505-579:HC-pre-first',),
    'graph.hc-comb': ('src/llama-context.cpp:llama_context::resolve_fused_ops:505-579:HC-comb-second',),
    'graph.hc-post': ('src/llama-context.cpp:llama_context::resolve_fused_ops:505-579:HC-post-third',),
    'graph.pp': ('src/llama-context.cpp:llama_context::sched_reserve:630-652:PP-fourth',
                 'src/llama-context.cpp:llama_context::graph_reserve:2418-2467'),
    'graph.tg': ('src/llama-context.cpp:llama_context::sched_reserve:654-665:TG-fifth',
                 'src/llama-context.cpp:llama_context::graph_reserve:2418-2467'),
    'graph.pp-again': ('src/llama-context.cpp:llama_context::sched_reserve:667-678:PP-again-sixth',
                       'src/llama-context.cpp:llama_context::graph_reserve:2418-2467'),
    'graph.results': ('src/llama-context.cpp:llama_context::sched_reserve:598-605',
                      'src/llama-graph.cpp:llm_graph_result::llm_graph_result/reset:1311-1354',
                      'src/llama-context.cpp:llama_context::graph_max_nodes:2307-2354'),
    'sched.host': ('ggml/src/ggml-backend.cpp:ggml_backend_sched_new:1845-1910,1475-1484',),
    'galloc.host': ('ggml/src/ggml-alloc.c:ggml_gallocr_new_n:482-529,825-901',),
    'reserve.compute': ('ggml/src/ggml-alloc.c:ggml_dyn_tallocr/ggml_gallocr:96-175,424-445,515-527,904-963',),
    'final.template': ('src/models/qwen4exp.cpp:llama_model_qwen4exp::graph::graph:428-440',),
    'loader.mapping': ('src/llama-model-loader.cpp:llama_model_loader::init_mappings/load_all_data:1073-1106,1403-1432,1730-1754',),
    'loader.read': ('src/llama-model-loader.cpp:llama_model_loader::load_all_data:1731-1739',),
    'loader.upload': ('src/llama-model-loader.cpp:llama_model_loader::load_all_data:1502-1513,1519-1581,1746-1754',),
    'rpc.send': ('ggml/src/ggml-rpc/ggml-rpc.cpp:ggml_backend_rpc_buffer_set_tensor:700-723',),
    'rpc.alloc': ('ggml/src/ggml-rpc/ggml-rpc.cpp:ggml_backend_rpc_buffer_type_alloc_buffer:782-800',
                  'ggml/src/ggml-rpc/ggml-rpc.cpp:rpc_server::alloc_buffer:1224-1243',),
    'rpc.receive': ('ggml/src/ggml-rpc/ggml-rpc.cpp:recv_msg(vector):279-290',
                    'ggml/src/ggml-rpc/ggml-rpc.cpp:rpc_server::set_tensor:1400-1449',),
    'rpc.cache-hit': ('ggml/src/ggml-rpc/ggml-rpc.cpp:rpc_server::get_cached_file/set_tensor_hash:1452-1511',),
    'rpc.graph': ('ggml/src/ggml-rpc/ggml-rpc.cpp:rpc_server::graph_compute:1681-1718',),
    'server.slots': ('tools/server/server-context.cpp:server_context_impl::load_model:1253-1314',),
    'server.batch': ('tools/server/server-context.cpp:server_context_impl::load_model:1343-1348',
                     'tools/server/server-context.cpp:server_batch::init:148-154',
                     'src/llama-batch.cpp:llama_batch_init:945-970'),
    'server.prompt-cache': ('tools/server/server-context.cpp:server_context_impl::load_model:1343-1361',
                            'tools/server/server-task.h:server_prompt_cache:612-624'),
}


@dataclass(frozen=True, slots=True)
class Q8StartupInputs:
    """Independently retained EXPECTED settings; None is not a native default."""
    n_outputs_max: int | None
    n_outputs_max_per_seq: int | None
    embeddings: bool | None
    backend_samplers_present: bool | None
    cache_ram_mib: int | None

    def __post_init__(self):
        _q8_startup_inputs_guard(self)


@dataclass(frozen=True, slots=True)
class Q8StartupComponent:
    component_id: str
    site_id: str
    logical_state_id: str | None
    participant_id: str
    memory_id: str
    partition: str
    lifetime: str
    representation: str
    dimension_law: str
    dimensions: tuple[int | None, ...]
    minimum_bytes: int | None
    allocation_request_bytes: int | None
    capacity_bytes: None
    alias_group: str | None
    enabled: bool | None
    source_sites: tuple[str, ...]
    pending: tuple[str, ...]

    def __post_init__(self):
        _q8_startup_component_guard(self)


@dataclass(frozen=True, slots=True)
class Q8StartupChargeJoin:
    charge: ResourceCharge
    site_ids: tuple[str, ...]
    partition: str
    pending: tuple[str, ...]

    def __post_init__(self):
        _q8_startup_join_detach(self)


@dataclass(frozen=True, slots=True)
class Q8StartupOracle:
    """Finite description only, not original provenance or STATIC_ADMITTED."""
    context: 'StaticPlanContext'
    startup: Q8StartupInputs
    components: tuple[Q8StartupComponent, ...]
    charge_joins: tuple[Q8StartupChargeJoin, ...]
    pending: tuple[str, ...]

    def __post_init__(self):
        _q8_startup_oracle_detach(self)


# (member, dimension-law, native representation). Ordered facts, not a DSL.
_Q8_STARTUP_MEMBERS = {
    'output.ids': (('', 'batch-int32', 'host-vector-int32'),),
    'output.logits': (('', 'startup-logits', 'buf-output-float-subview'),),
    'output.embd': (('', 'startup-embedding', 'buf-output-float-subview'),),
    'output.sampling': (('sampling.logits', 'sampler-float', 'buf-output-float-subview'),
                        ('sampling.probs', 'sampler-float', 'buf-output-float-subview'),
                        ('sampling.sampled', 'sampler-token', 'buf-output-token-subview'),
                        ('sampling.candidates', 'sampler-token', 'buf-output-token-subview'),
                        ('sampling.logits_count', 'sampler-count', 'host-vector-uint32'),
                        ('sampling.probs_count', 'sampler-count', 'host-vector-uint32'),
                        ('sampling.candidates_count', 'sampler-count', 'host-vector-uint32')),
    'output.base': (('', 'output-base-request', 'CPU-buf-output-base'),),
    'vocab.ids': (('', 'vocab-int32', 'host-vector-int32'),),
    'context.layers': (('cparams.embeddings_layer_inp', 'layer-vector', 'host-vector-bool'),
                       ('embd_layer_inp', 'layer-vector', 'host-vector-empty-buffer-views')),
    'recurrent.cells': (('', 'recurrent-cells', 'host-vector-mem-cell'),
                        ('r_l', 'layer-vector', 'host-vector-tensor-pointers'),
                        ('s_l', 'layer-vector', 'host-vector-tensor-pointers'),
                        ('p_l', 'layer-vector', 'host-vector-tensor-pointers')),
    'recurrent.rs_idx': (('', 'recurrent-index', 'host-vector-uint32'),),
    'cache.raw': (('', 'approved-cache-family', 'approved-raw-cache-family'),),
    'cache.views': (('', 'approved-cache-family', 'borrowed-raw-cache-stream-views'),),
    'cache.contexts': (('', 'approved-cache-family', 'host-ggml-context-family'),),
    'graph.results': (('gf_res_prev', 'graph-result-meta', 'host-graph-result-meta'),
                      ('gf_res_reserve', 'graph-result-meta', 'host-graph-result-meta')),
    'sched.host': (('', 'scheduler-meta', 'host-scheduler-metadata'),),
    'galloc.host': (('', 'gallocr-meta', 'host-gallocr-metadata'),),
    'reserve.compute': (('', 'reserve-chunks', 'expected-binding-vbuffer-family'),),
    'final.template': (('', 'final-request-output', 'request-HC-mix-logits'),),
    'loader.mapping': (('', 'source-mapping', 'source-range-mapping-family'),),
    'loader.read': (('', 'tensor-read', 'load-read-buffer-family'),),
    'loader.upload': (('', 'upload-staging', 'conditional-four-upload-buffers'),),
    'rpc.send': (('', 'rpc-frame', 'SET-request-envelope-new-array'),),
    'rpc.alloc': (('', 'rpc-allocation', 'remote-buffer-allocation-family'),),
    'rpc.receive': (('', 'rpc-frame', 'host-receive-vector-frame'),),
    'rpc.cache-hit': (('', 'rpc-cache-vector', 'host-cache-hit-vector'),),
    'rpc.graph': (('', 'rpc-request-graph', 'host-request-graph-buffer'),),
    'server.slots': (('', 'server-slots', 'host-server-slots'),),
    'server.batch': (('token', 'server-batch', 'host-int32-array'),
                     ('pos', 'server-batch', 'host-int32-array'),
                     ('n_seq_id', 'server-batch', 'host-int32-array'),
                     ('seq_id', 'server-batch', 'host-seq-id-int32-arrays'),
                     ('logits', 'server-batch', 'host-int8-array'),
                     ('seq_id_ptrs', 'server-batch', 'host-pointer-array'),
                     ('tokens', 'server-batch', 'host-empty-token-vector')),
    'server.prompt-cache': (('', 'prompt-cache-policy', 'host-empty-prompt-cache-states'),),
}
for _q8_site in _Q8_STARTUP_PASS_ORDER:
    _Q8_STARTUP_MEMBERS[_q8_site] = (('', 'graph-template', 'split-only-support-template' if _q8_site.startswith('graph.hc-') else 'reservation-template'),)
for _q8_site in ('attn.cells', 'idx.cells'):
    _Q8_STARTUP_MEMBERS[_q8_site] = (
        ('v_heads', 'stream-heads', 'host-vector-uint32'),
        ('seq_to_stream', 'seq-stream-map', 'host-vector-uint32'),
        ('stream-0/pos', 'cell-pos', 'host-vector-int32'),
        ('stream-0/shift', 'cell-shift', 'host-vector-int32'),
        ('stream-0/ext', 'cell-ext', 'host-vector-three-int32-ext'),
        ('stream-0/seq', 'cell-seq-bits', 'host-vector-seq-bitsets'),
        ('stream-0/used', 'empty-set', 'host-empty-used-set'),
        ('stream-0/seq_pos', 'empty-set', 'host-empty-sequence-position-sets'))
del _q8_site


def _q8_startup_components(context, startup):
    c, inv = context.config, context.inventory
    w = c.workload
    b0, u, cells, sequences = min(w.context, w.batch), min(w.context, w.batch, w.microbatch), (w.context + 255) // 256 * 256, 1
    h = dict(inv.model_metadata)
    weights = {r.state_id:r for r in inv.weights}
    vocab = weights['output.weight'].shape[1]
    if weights['token_embd.weight'].shape[1] != vocab:
        raise ValueError('startup vocabulary shape')
    hout_override = h.get('qwen4exp.embedding_length_out', 0)
    if type(hout_override) is not int or not 0 <= hout_override <= 262144:
        raise ValueError('startup output width')
    hout = hout_override if hout_override != 0 else h['qwen4exp.embedding_length']
    if type(hout) is not int or not 1 <= hout <= 262144:
        raise ValueError('startup output width')
    client = next(p for p in c.participants if p.role == 'client')
    remote = next(p for p in c.participants if p.role == 'remote')
    options = thaw(c.strategy_options)
    bindings = {b.binding_id:(p, b) for p in c.participants for b in p.bindings}
    loader = bindings[options['bindings']['loader']][1]
    remote_cpu = bindings[options['bindings']['remote_cpu']][1]
    final = bindings[options['bindings']['remote_gpu' if c.selection == 'one-gpu' else 'remote_cpu']]
    result = []

    def add(site, member='', dims=(None,), minimum=None, request=None, *, enabled=True,
            alias=None, logical=None, partition='startup-active', lifetime='context', domain=None, pending=()):
        descriptor = next(d for d in _Q8_STARTUP_MEMBERS[site] if d[0] == ('' if site == 'reserve.compute' else member))
        participant, memory = (client.participant_id, loader.memory_id) if domain is None else domain
        cid = site + ('/' + member if member else '')
        result.append(Q8StartupComponent(cid, site, logical, participant, memory, partition, lifetime,
            descriptor[2], descriptor[1], dims, minimum, request, None, alias, enabled,
            tuple(RUNTIME_PIN + ':' + source for source in _Q8_STARTUP_SOURCES[site]),
            ('native-capacity-ABI-heap-residence-UNKNOWN',) + pending))

    add('output.ids', dims=(b0,), minimum=4*b0, logical='client-control', pending=('initial-entries=-1;startup-n_outputs=0',))
    add('output.logits', dims=(vocab, sequences), minimum=4*vocab*sequences, alias='output.base', pending=('A-staging-not-final-B-logits',))
    add('output.embd', dims=(hout, sequences), minimum=4*hout*sequences, enabled=startup.embeddings,
        alias='output.base', pending=('expected-embeddings-and-authenticated-output-width',))
    for member, law, _ in _Q8_STARTUP_MEMBERS['output.sampling']:
        count = law == 'sampler-count'
        dims = (sequences,) if count or member == 'sampling.sampled' else (vocab, sequences)
        minimum = 4*sequences if len(dims) == 1 else 4*vocab*sequences
        add('output.sampling', member, dims, minimum, enabled=startup.backend_samplers_present,
            alias=None if count else 'output.base', pending=('expected-backend-sampler-registration;counts-initially=0;sampled=TOKEN_NULL',))
    request = None
    if startup.embeddings is not None and startup.backend_samplers_present is not None:
        request = 4*vocab*sequences + (4*hout*sequences if startup.embeddings else 0)
        if startup.backend_samplers_present:
            request += 8*vocab*sequences + 4*(1+vocab)*sequences
    add('output.base', minimum=request, request=request, pending=('branch-flags-expected-not-observed;counts-are-separate-host-vectors',))
    add('vocab.ids', dims=(vocab,), minimum=4*vocab, logical='client-control', pending=('values=index;tokenizer-consumption-unproven',))
    for member, _, _ in _Q8_STARTUP_MEMBERS['context.layers']:
        add('context.layers', member, (h['qwen4exp.block_count'] + 1,), logical='client-control', pending=('initial-flags=false;views-empty;no-layer-input-buffer',))
    for family in ('attn.cells', 'idx.cells'):
        for member, law, _ in _Q8_STARTUP_MEMBERS[family]:
            dims, minimum = (cells,), None
            if law in ('cell-pos', 'cell-shift'): minimum = 4*cells
            elif law == 'cell-ext': minimum = 12*cells
            elif law == 'cell-seq-bits': dims = (256, cells)
            elif law == 'stream-heads': dims, minimum = (sequences,), 4*sequences
            elif law == 'seq-stream-map': dims, minimum = (256,), 4*256
            elif law == 'empty-set': dims = (0,)
            add(family, member, dims, minimum, logical='client-control', pending=(
                'pos=-1;shift=0;ext=(0,0,TOKEN_NULL);seq-bits-reset;used/seq_pos-empty;heads=0;seq_to_stream=0',
                'attention-and-indexer-separate-control-containers;empty-logical-set-not-zero-heap',))
    add('recurrent.cells', dims=(sequences,), logical='client-control', pending=('pos/src/src0/tail=-1;seq_id-empty;head=used=0',))
    add('recurrent.rs_idx', dims=(sequences,), minimum=4*sequences, logical='client-control', pending=('initial-values=0',))
    for member in ('r_l', 's_l', 'p_l'):
        add('recurrent.cells', member, (h['qwen4exp.block_count'],), logical='client-control')
    for site in ('cache.raw', 'cache.views', 'cache.contexts'):
        add(site, alias='cache.raw' if site == 'cache.views' else None, pending=(
            'exact-context-inventory-persistent_caches;raw-owner-follows-each-approved-binding',
            'stream-views-borrow-exact-corresponding-raw-state_ids;not-new-bases',
            'recurrent-context=3*layers*tensor_overhead;KV-context=2*(1+S)*layers*tensor_overhead-per-buft;ABI/buft-UNKNOWN',))
    n = min(cells, u)
    for site in _Q8_STARTUP_PASS_ORDER:
        dims = (sequences, sequences, sequences) if site in _Q8_STARTUP_PASS_ORDER[:3] or site == 'graph.tg' else (n, sequences, min(n, startup.n_outputs_max) if startup.n_outputs_max is not None else None)
        add(site, dims=dims, partition='startup-reservation', alias='sched/galloc-reservation', pending=(
            'split-only-not-graph_compute-not-request-ubatch-copy-or-physical-base',
            'source-order:' + '>'.join(_Q8_STARTUP_PASS_ORDER), 'expected-n_outputs_max',))
    for member in ('gf_res_prev', 'gf_res_reserve'):
        add('graph.results', member, partition='startup-reservation', pending=(
            'tensor_overhead*G+graph_overhead_custom(G,false);G=max(40*N,32*T)+sampler-terms',
            'native-T-is-not-assumed-1224;two-reused-results-not-six-bases',))
    for site in ('sched.host', 'galloc.host'):
        add(site, partition='startup-reservation', pending=('G/hash-size/backend-buft-equivalence/native-record-ABI-UNKNOWN',))
    for bid in sorted(options['bindings'].values()):
        participant, binding = bindings[bid]
        add('reserve.compute', bid, partition='startup-reservation', domain=(participant.participant_id, binding.memory_id), pending=(
            'source-upper-count:at-most-16-per-distinct-dynallocator;actual-chunk-count-UNKNOWN',
            'chunk-max_size/alignment/get_alloc_size/buft-slot-alias-UNKNOWN;expected-domain-not-physical-base',))
    add('final.template', logical='final-output-state', partition='request-only', lifetime='request',
        domain=(final[0].participant_id, final[1].memory_id), pending=('HC-mix/logits-task-layout-materialization-copies-output-custody-UNKNOWN',))
    add('loader.mapping', partition='backing', lifetime='source-backing', pending=('assigned-ranges/lazy-PLE/mmap-fragments/pages/FD-lifetime-UNKNOWN',))
    add('loader.read', partition='load-only', lifetime='load-call', pending=('logical-tensor-nbytes;actual-read_buf-size/overlap/load-end-UNKNOWN',))
    add('loader.upload', partition='load-only', lifetime='load-call', enabled=None, pending=('conditional-four-source-buffer_size-uploads;support/alignment/release-UNKNOWN',))
    add('rpc.send', partition='load-only', lifetime='load-call', pending=(
        'SEND-SET-request-new-array=sizeof-rpc_tensor+8+payload;ABI/actual-payload-UNKNOWN',
        'hash-hit-no-payload;shared_ptr-dispatch-lifetime;load-or-request-not-permanent-base',))
    b_ram = (remote.participant_id, remote_cpu.memory_id)
    add('rpc.alloc', domain=b_ram, pending=('B-RAM-proxy-metadata-not-remote-physical-buffer;alloc-response-remote_size-UNKNOWN',))
    add('rpc.receive', partition='load-only', lifetime='load-call', domain=b_ram, pending=('RECEIVE-vector-frame-length/overlap-UNKNOWN;not-SEND-envelope',))
    add('rpc.cache-hit', partition='load-only', lifetime='load-call', domain=b_ram,
        enabled=options['rpc_cache'] == 'enabled', pending=('conditional-cache-file-vector;actual-consumption/length-load-end-UNKNOWN',))
    add('rpc.graph', partition='request-only', lifetime='request', domain=b_ram, pending=('stored-graph-buffer-grows-only-at-graph_compute;no-request-executed',))
    add('server.slots', dims=(sequences,), logical='client-control', pending=('CPU-samplers-exist-regardless-of-backend-samplers;slot-ABI-UNKNOWN',))
    capacity = max(b0, sequences)
    for member, _, _ in _Q8_STARTUP_MEMBERS['server.batch']:
        dims = (0,) if member == 'tokens' else (capacity+1,) if member == 'seq_id_ptrs' else (capacity,)
        minimum = capacity if member == 'logits' else None if member in ('seq_id_ptrs', 'tokens') else 4*capacity
        add('server.batch', member, dims, minimum, logical='client-control', pending=(
            'batch-capacity=max(B0,S);each-seq_id-one-int32;tokens-reserve-capacity-but-size=0;pointer-ABI-UNKNOWN',))
    add('server.prompt-cache', dims=(0,), logical='client-control', enabled=None if startup.cache_ram_mib is None else startup.cache_ram_mib != 0,
        pending=('cache_ram_mib-policy-not-preallocation-or-upper-heap-bound;states-empty',))
    return tuple(sorted(result, key=lambda r:r.component_id))


def _q8_startup_charge_joins(context):
    c = context.config
    loader = next(p for p in c.participants if p.role == 'client')
    loader_memory = next(b.memory_id for b in loader.bindings if b.binding_id == thaw(c.strategy_options)['bindings']['loader'])
    result = []
    for charge in context.inventory.charges:
        suffix = '/' + charge.phase
        if charge.phase not in PHASES or not charge.allocation_id.endswith(suffix):
            raise ValueError('startup charge phase suffix')
        group = charge.allocation_id[:-len(suffix)]
        prefix = group.split(':', 1)[0]
        pending = ('exact-original-charge-not-rebudgeted;site-relationships-not-additive-capacity',)
        partition = 'startup-active'
        if prefix in ('encoded-weights', 'backend-allocation-repacking'):
            sites = ('loader.mapping', 'rpc.alloc')
            pending += ('approved-weights-vs-native-layout/repacking/padding-UNKNOWN',)
        elif prefix == 'state-lower-bound':
            sites = ('cache.raw',)
            pending += ('approved-cache-payload-only;physical-extent-UNKNOWN',)
        elif prefix == 'state-allocator-overhead':
            sites = ('cache.contexts', 'context.layers', 'vocab.ids', 'server.slots', 'server.prompt-cache') if charge.memory_id == loader_memory else ('cache.contexts',)
            pending += ('cache-padding/native-context-metadata-UNKNOWN',)
            if charge.memory_id != loader_memory:
                pending += ('unresolved-domain-gap:A-host-metadata-vs-charge-memory',)
        elif prefix == 'graph':
            sites = ('reserve.compute', 'graph.results', 'sched.host', 'galloc.host') if charge.memory_id == loader_memory else ('reserve.compute',)
            partition = 'startup-reservation'
            pending += ('native-chunks/host-metadata/alias-extents-UNKNOWN',)
        elif prefix == 'workspace':
            sites = ('output.base', 'server.batch') if charge.memory_id == loader_memory else ()
            pending += ('workspace-host-residual-UNKNOWN',) if sites else ('unresolved-domain-gap:backend-workspace-vs-A-host',)
        elif prefix == 'observer':
            sites = ()
            pending += ('observer-producer-allocator-no-pinned-native-site',)
        elif prefix == 'client-control':
            sites = ('output.ids', 'vocab.ids', 'context.layers', 'attn.cells', 'idx.cells', 'recurrent.cells', 'recurrent.rs_idx', 'server.slots', 'server.prompt-cache')
            pending += ('host-control-heap-closure-UNKNOWN',)
        elif prefix == 'final-output-state':
            sites, partition = ('final.template',), 'request-only'
            pending += ('startup-reservation-not-final-output-state',)
        elif prefix in ('source-backing', 'assigned-cache-disk'):
            sites, partition = ('loader.mapping',) if prefix == 'source-backing' else ('rpc.cache-hit',), 'backing'
            pending += ('source-member/assigned-cache/FD-consumption/lifetime-UNKNOWN',)
        elif prefix in ('verification-read-buffer', 'verification-page-residence'):
            sites, partition = (), 'verification'
            pending += ('operator-verifier-no-native-constructor-site;prior-read-peak/page-residence-UNKNOWN',)
        elif prefix in ('source-page-residence', 'PLE-active-backed-residence', 'whole-source-mmap'):
            sites = ('loader.mapping',)
            partition = 'virtual' if prefix == 'whole-source-mmap' else 'startup-active'
            pending += ('source-page/weight-mmap-alias-dedupe-disk-VA-residence-separately;lazy-PLE-unchanged',)
        elif prefix in ('transport-envelope', 'full-tensor-loader', 'FNV-cache-message-staging', 'remote-receive-staging'):
            sites = ('loader.read', 'loader.upload') if prefix == 'full-tensor-loader' else ('rpc.receive',) if prefix == 'remote-receive-staging' or charge.memory_id != loader_memory else ('rpc.send',)
            partition = 'load-only'
            pending += ('load-end/peak/overlap-UNKNOWN;loader-read-and-message-not-aliases',)
        elif prefix in ('full-tensor-cache-hit-vector', 'cache-hit-vector-overlap'):
            sites, partition = ('rpc.cache-hit',), 'load-only'
            pending += ('conditional-RPC-cache-consumption/vector-overlap-UNKNOWN',)
        elif prefix == 'host-mirror':
            sites = ()
            pending += ('intended-mirror-site/source-physical-relation-UNKNOWN',)
        elif prefix in ('boundary-wire', 'boundary-bounce-lower-bound', 'boundary-bounce-overlap'):
            sites = ('rpc.send', 'rpc.receive') if prefix == 'boundary-wire' else ()
            partition = 'request-only'
            pending += ('wire/overlap/GET-destination-view-allocation-UNKNOWN;B-CPU>A-staging>B-CUDA-legs-not-completed',)
        else:
            raise ValueError('startup unmapped charge prefix: ' + prefix)
        join = Q8StartupChargeJoin(charge, sites, partition, pending)
        # Private builders share THIS context's nodes; standalone constructors
        # still detach their caller charge. The whole result owns its context.
        object.__setattr__(join, 'charge', charge)
        result.append(join)
    return tuple(sorted(result, key=lambda j:(PHASES.index(j.charge.phase), j.charge.allocation_id, j.charge.memory_id)))


def _q8_startup_pending(context):
    return context.inventory.pending_dynamic + (
        'startup-expectations-not-observed-settings-or-STATIC_ADMITTED',
        'effective-argv/environment/server/cparams-join-UNKNOWN;CPU-samplers-always-exist',
        'nonspeculative-text/pooling-none-no-MTP/multimodal/restored-context-closure-pending',
        'source-order:' + '>'.join(_Q8_STARTUP_PASS_ORDER),
        'full-source/mapping/cache/build/owned-process/resource/freshness/site-allocator-closure-UNKNOWN',
        'policy-reserve-from-config-policy-not-ResourceCharge-or-allocation',
        'finite-catalog-not-complete-host-heap/backend-layout/capacity-closure',
        'source-upper-count-16-not-allocated-chunks-or-sum-of-backend-slot-capacities',
        'base/subview/minimum/charge-sites-not-summed-to-satisfy-budgets',
        'derived-artifact-qualification-separate;unmodified-source-capability-unchanged')


def derive_q8_startup_oracle(plan: 'ProfiledOperatorPlan', metadata: MetadataIndex, *,
                              original_plan_digest: str, startup: Q8StartupInputs) -> Q8StartupOracle:
    """Pure bounded prerequisite; approved original-plan predicates run first."""
    from .phased_observation import derive_static_plan_context
    context = derive_static_plan_context(plan, metadata, original_plan_digest=original_plan_digest)
    _q8_startup_inputs_guard(startup, context)
    return Q8StartupOracle(context, startup, _q8_startup_components(context, startup),
                           _q8_startup_charge_joins(context), _q8_startup_pending(context))

def _q8_startup_shape(value, kind, names, predicate):
    from dataclasses import fields
    if type(value) is not kind or tuple(f.name for f in fields(kind)) != names:
        raise ValueError(predicate)


def _q8_startup_text(value, predicate):
    if type(value) is not str or not value or len(value) > 4096 or value != value.strip() or '\x00' in value:
        raise ValueError(predicate)


def _q8_startup_tuple_text(value, predicate, *, empty=True):
    if type(value) is not tuple or len(value) > 128 or (not empty and not value):
        raise ValueError(predicate)
    for child in value:
        _q8_startup_text(child, predicate)


def _q8_startup_inputs_guard(startup, context=None):
    _q8_startup_shape(startup, Q8StartupInputs,
        ('n_outputs_max', 'n_outputs_max_per_seq', 'embeddings', 'backend_samplers_present', 'cache_ram_mib'),
        'startup input type')
    for name in ('n_outputs_max', 'n_outputs_max_per_seq', 'cache_ram_mib'):
        value = getattr(startup, name)
        lo, hi = (-1, 2**31-1) if name == 'cache_ram_mib' else (1, 262144)
        if value is not None and (type(value) is not int or not lo <= value <= hi):
            raise ValueError('startup input ' + name)
    for name in ('embeddings', 'backend_samplers_present'):
        value = getattr(startup, name)
        if value is not None and type(value) is not bool:
            raise ValueError('startup input ' + name)
    if startup.n_outputs_max is not None and startup.n_outputs_max_per_seq is not None and startup.n_outputs_max_per_seq > startup.n_outputs_max:
        raise ValueError('startup input n_outputs_max_per_seq')
    if context is not None:
        w = context.config.workload
        if not 1 <= w.microbatch <= w.batch <= w.context <= 262144 or w.slots != 1:
            raise ValueError('startup oracle context workload')
        b0 = min(w.context, w.batch)
        for name in ('n_outputs_max', 'n_outputs_max_per_seq'):
            value = getattr(startup, name)
            expected = (b0 if startup.embeddings else 1) if name == 'n_outputs_max' else 1
            if value is not None and (value > b0 or ((name == 'n_outputs_max_per_seq' or startup.embeddings is not None) and value != expected)):
                raise ValueError('startup effective output limits')


def _q8_startup_component_guard(row):
    _q8_startup_shape(row, Q8StartupComponent,
        ('component_id', 'site_id', 'logical_state_id', 'participant_id', 'memory_id', 'partition',
         'lifetime', 'representation', 'dimension_law', 'dimensions', 'minimum_bytes',
         'allocation_request_bytes', 'capacity_bytes', 'alias_group', 'enabled', 'source_sites', 'pending'),
        'startup component type')
    for name in ('component_id', 'site_id', 'participant_id', 'memory_id', 'partition',
                 'lifetime', 'representation', 'dimension_law'):
        _q8_startup_text(getattr(row, name), 'startup component ' + name)
    if row.site_id not in _Q8_STARTUP_SOURCES:
        raise ValueError('startup component site_id')
    members = _Q8_STARTUP_MEMBERS[row.site_id]
    if row.site_id == 'reserve.compute':
        if not row.component_id.startswith('reserve.compute/'):
            raise ValueError('startup component member')
        _q8_startup_text(row.component_id[len('reserve.compute/'):], 'startup component member')
        descriptor = members[0]
    else:
        descriptors = {row.site_id + ('/' + d[0] if d[0] else ''):d for d in members}
        if row.component_id not in descriptors:
            raise ValueError('startup component member')
        descriptor = descriptors[row.component_id]
    if row.dimension_law != descriptor[1]:
        raise ValueError('startup component dimension_law')
    if row.representation != descriptor[2]:
        raise ValueError('startup component representation')
    if row.partition not in _Q8_STARTUP_PARTITIONS:
        raise ValueError('startup component partition')
    if row.lifetime not in _Q8_STARTUP_LIFETIMES:
        raise ValueError('startup component lifetime')
    if row.logical_state_id is not None and (type(row.logical_state_id) is not str or row.logical_state_id not in ('client-control', 'final-output-state')):
        raise ValueError('startup component logical_state_id')
    if row.alias_group is not None and (type(row.alias_group) is not str or row.alias_group not in ('output.base', 'cache.raw', 'sched/galloc-reservation')):
        raise ValueError('startup component alias_group')
    if type(row.dimensions) is not tuple or not 1 <= len(row.dimensions) <= 3:
        raise ValueError('startup component dimensions')
    for dim in row.dimensions:
        if dim is not None and (type(dim) is not int or not 0 <= dim <= 2**63-1):
            raise ValueError('startup component dimensions')
    for name in ('minimum_bytes', 'allocation_request_bytes'):
        value = getattr(row, name)
        if value is not None and (type(value) is not int or not 0 <= value <= 2**63-1):
            raise ValueError('startup component ' + name)
    if row.allocation_request_bytes is not None and row.site_id != 'output.base':
        raise ValueError('startup component allocation_request_bytes')
    if row.capacity_bytes is not None:
        raise ValueError('startup component capacity_bytes')
    if row.enabled is not None and type(row.enabled) is not bool:
        raise ValueError('startup component enabled')
    _q8_startup_tuple_text(row.source_sites, 'startup component source_sites', empty=False)
    if row.source_sites != tuple(RUNTIME_PIN + ':' + s for s in _Q8_STARTUP_SOURCES[row.site_id]):
        raise ValueError('startup component source_sites')
    _q8_startup_tuple_text(row.pending, 'startup component pending', empty=False)


def _q8_startup_join_guard(join):
    from .phased_observation import _static_record
    _q8_startup_shape(join, Q8StartupChargeJoin, ('charge', 'site_ids', 'partition', 'pending'), 'startup charge type')
    _static_record(join.charge, ResourceCharge, 'startup charge.charge')
    _q8_startup_tuple_text(join.site_ids, 'startup charge site_ids')
    if len(set(join.site_ids)) != len(join.site_ids) or any(site not in _Q8_STARTUP_SOURCES for site in join.site_ids):
        raise ValueError('startup charge site_ids')
    if type(join.partition) is not str or join.partition not in _Q8_STARTUP_PARTITIONS:
        raise ValueError('startup charge partition')
    _q8_startup_tuple_text(join.pending, 'startup charge pending', empty=False)


def _q8_startup_join_detach(join):
    from dataclasses import fields
    _q8_startup_join_guard(join)
    # Reconstruct only the closed ResourceCharge primitives; no copy hooks.
    charge = ResourceCharge(**{f.name:getattr(join.charge, f.name) for f in fields(ResourceCharge)})
    object.__setattr__(join, 'charge', charge)


def _q8_startup_oracle_detach(oracle):
    from dataclasses import fields
    from .phased_observation import StaticPlanContext
    _q8_startup_shape(oracle, Q8StartupOracle,
        ('context', 'startup', 'components', 'charge_joins', 'pending'), 'startup oracle type')
    _q8_startup_shape(oracle.context, StaticPlanContext,
        ('original_plan_digest', 'config', 'inventory'), 'startup oracle context')
    # This existing constructor proves shape and detaches, NOT semantic origin.
    context = StaticPlanContext(oracle.context.original_plan_digest, oracle.context.config, oracle.context.inventory)
    _q8_startup_inputs_guard(oracle.startup, context)
    startup = Q8StartupInputs(**{f.name:getattr(oracle.startup, f.name) for f in fields(Q8StartupInputs)})
    for name, kind, guard in (('components', Q8StartupComponent, _q8_startup_component_guard),
                              ('charge_joins', Q8StartupChargeJoin, _q8_startup_join_guard)):
        rows = getattr(oracle, name)
        if type(rows) is not tuple or len(rows) > 4096:
            raise ValueError('startup oracle ' + name)
        for row in rows:
            if type(row) is not kind:
                raise ValueError('startup oracle ' + name)
            guard(row)
    _q8_startup_tuple_text(oracle.pending, 'startup oracle pending', empty=False)
    components = _q8_startup_components(context, startup)
    joins = _q8_startup_charge_joins(context)
    pending = _q8_startup_pending(context)
    actual_components = {r.component_id:r for r in oracle.components}
    if len(actual_components) != len(oracle.components) or set(actual_components) != {r.component_id for r in components}:
        raise ValueError('startup component coverage')
    for expected in components:
        actual = actual_components[expected.component_id]
        for field in fields(Q8StartupComponent):
            if not _inventory_exact_value(getattr(actual, field.name), getattr(expected, field.name)):
                raise ValueError('startup component law: ' + expected.component_id + '.' + field.name)
    def key(join):
        return join.charge.allocation_id, join.charge.memory_id, join.charge.phase
    actual_joins = {key(j):j for j in oracle.charge_joins}
    if len(actual_joins) != len(oracle.charge_joins) or set(actual_joins) != {key(j) for j in joins}:
        raise ValueError('startup charge coverage')
    for expected in joins:
        for field in fields(Q8StartupChargeJoin):
            if not _inventory_exact_value(getattr(actual_joins[key(expected)], field.name), getattr(expected, field.name)):
                raise ValueError('startup charge law: ' + expected.charge.allocation_id + '.' + field.name)
    if not _inventory_exact_value(oracle.pending, pending):
        raise ValueError('startup oracle pending')
    for name, value in (('context', context), ('startup', startup), ('components', components),
                        ('charge_joins', joins), ('pending', pending)):
        object.__setattr__(oracle, name, value)

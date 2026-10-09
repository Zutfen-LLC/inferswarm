"""Bounded Qwen3.8 Q8_0 strategy at an exact unmodified native source pin.

Metadata and source semantics are CALCULATED, never weight/kernel/physical proof.
Only one explicitly selected fixed candidate is emitted. No execution or search.
"""
from __future__ import annotations
from dataclasses import dataclass, replace
from .config import profile_subject
from .metadata import _index, _public_members
from .source import _encoded_bytes, _validate_extents
from .plan import ResourceCharge, LegalCandidate, CapabilityRequirement, PHASES
from .profiles import thaw, integer, keys, text

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
    keys(options,('bindings','route','source_contract','rpc_cache','host_mirrors','bounds','startup_timeout_seconds'),'strategy options')
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

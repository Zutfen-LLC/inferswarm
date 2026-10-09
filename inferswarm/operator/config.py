"""Strict, side-effect-free operator configuration parsing."""
from __future__ import annotations
import json, math, re
from dataclasses import dataclass, asdict, fields
import hashlib
from pathlib import Path
from typing import Any, Mapping

@dataclass(frozen=True)
class ModelIdentity:
    source_id: str
    revision: str
    representation: str
    members: tuple[tuple[str, str, int], ...]

@dataclass(frozen=True)
class CacheRange:
    state_id: str
    member: str
    offset: int
    length: int
    sha256: str
    cache_key: str
    source_id: str
    revision: str
    representation: str
    unit_id: str

@dataclass(frozen=True)
class Participant:
    role: str; node_id: str; compute_id: str; transport: str; execution_address: str
    rpc_endpoint: str | None; device: str; source_path: str; runtime_executable: str
    runtime_sha256: str; cache_path: str; port: int; lifecycle_dir: str
    source_id: str; source_revision: str; source_representation: str
    cache_ranges: tuple[CacheRange, ...]

@dataclass(frozen=True)
class Placement:
    unit_id: str; compute_id: str; state_ids: tuple[str, ...]
    state_ranges: tuple[tuple[str, str, int, int], ...]
    first_layer: int; last_layer: int; output: bool

@dataclass(frozen=True)
class RuntimeBinding:
    role: str
    executable: str
    sha256: str

@dataclass(frozen=True)
class BackendOptions:
    hidden_layers: int; offload_tail: int; cpu_experts: bool
    tensor_split: tuple[float, ...]; context: int; slots: int
    startup_timeout_seconds: int; split_mode: str; verbosity: int
    rpc_physical_device: str | None = None

@dataclass(frozen=True)
class OperatorConfig:
    plan_id: str; model: ModelIdentity; participants: tuple[Participant, ...]
    strategy_id: str; placement: tuple[Placement, ...]
    backend_options: BackendOptions; request: tuple[tuple[str, Any], ...]
    runtime_bindings: tuple[RuntimeBinding, ...]

def _strict_pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out: raise ValueError(f"duplicate JSON key: {key}")
        out[key] = value
    return out

def parse_config_json(text: str, *, base_dir=None, now=None, profile_mode='live') -> OperatorConfig | ProfiledOperatorConfig:
    try: data = json.loads(text, object_pairs_hook=_strict_pairs, parse_constant=lambda x: (_ for _ in ()).throw(ValueError("non-finite JSON number")))
    except (json.JSONDecodeError, TypeError) as exc: raise ValueError("invalid config JSON") from exc
    return parse_config(data, base_dir=base_dir, now=now, profile_mode=profile_mode)


def _keys(v, expected, where):
    if not isinstance(v, Mapping) or set(v) != expected: raise ValueError(f"{where}: expected exactly {sorted(expected)}")
def _text(v, name):
    if not isinstance(v, str) or not v or v != v.strip() or "\x00" in v: raise ValueError(f"{name} must be non-empty exact text")
    v.encode("utf-8", "strict"); return v
def _path(v, name):
    s = _text(v, name)
    if not Path(s).is_absolute(): raise ValueError(f"{name} must be absolute")
    return s
def _digest(v, name):
    if not isinstance(v, str) or len(v) != 64 or any(c not in "0123456789abcdef" for c in v): raise ValueError(f"{name} must be lowercase SHA-256")
    return v
def _int(v, name, maximum=2**31-1):
    if type(v) is not int or not 1 <= v <= maximum: raise ValueError(f"{name} must be integer 1..{maximum}")
    return v

def _parse_config_v2(data: Mapping[str, Any]) -> OperatorConfig:
    _keys(data, {"schema","plan_id","model","participants","strategy_id","placement","backend_options","request"}, "config")
    if data["schema"] != "operator-config/2": raise ValueError("unsupported schema")
    _keys(data["model"], {"source_id","revision","representation","members"}, "model")
    m=data["model"]
    if not isinstance(m["members"], list) or not m["members"]: raise ValueError("model.members must be nonempty")
    members=[]
    for r in m["members"]:
        _keys(r,{"name","sha256","size_bytes"},"member"); name=_text(r["name"],"member.name")
        if Path(name).name != name or name in (".",".."): raise ValueError("member.name must be basename")
        members.append((name,_digest(r["sha256"],"member.sha256"),_int(r["size_bytes"],"member.size_bytes",2**63-1)))
    if len({x[0] for x in members}) != len(members): raise ValueError("duplicate model member")
    sizes = {name: size for name, _, size in members}
    model=ModelIdentity(_text(m["source_id"],"source_id"),_text(m["revision"],"revision"),_text(m["representation"],"representation"),tuple(members))
    if not isinstance(data["participants"],list) or len(data["participants"]) != 2: raise ValueError("exactly two participants required")
    participants=[]; roles=set(); nodes=set(); cus=set(); ports=set()
    keys={"role","node_id","compute_id","transport","execution_address","rpc_endpoint","device","source_path","runtime_executable","runtime_sha256","cache_path","port","lifecycle_dir","source_id","source_revision","source_representation","cache_ranges"}
    for r in data["participants"]:
        _keys(r,keys,"participant"); role=_text(r["role"],"role")
        if role not in ("client","remote") or role in roles: raise ValueError("exactly one client and one remote role required")
        roles.add(role); transport=_text(r["transport"],"transport")
        if transport != ("local" if role=="client" else "rpc"): raise ValueError("unsupported participant transport for role")
        ident=(r["source_id"],r["source_revision"],r["source_representation"])
        if ident != (model.source_id,model.revision,model.representation): raise ValueError("participant source identity mismatch")
        node=_text(r["node_id"],"node_id"); cu=_text(r["compute_id"],"compute_id")
        if node in nodes or cu in cus: raise ValueError("duplicate participant identity")
        nodes.add(node); cus.add(cu); port=r["port"]
        if type(port) is not int or not 1<=port<=65535 or port in ports: raise ValueError("port must be unique integer 1..65535")
        ports.add(port); endpoint=r["rpc_endpoint"]
        if role=="remote":
            endpoint=_text(endpoint,"rpc_endpoint")
            if ":" not in endpoint: raise ValueError("rpc_endpoint requires host and port")
        elif endpoint is not None: raise ValueError("client rpc_endpoint must be null")
        if not isinstance(r["cache_ranges"], list):
            raise ValueError("cache_ranges must be a list")
        if role == "remote" and not r["cache_ranges"]:
            raise ValueError("remote cache_ranges must be nonempty")
        ranges=[]
        for cr in r["cache_ranges"]:
            _keys(cr,{"state_id","member","offset","length","sha256","cache_key","source_id","revision","representation","unit_id"},"cache range")
            member=_text(cr["member"],"cache.member"); off=cr["offset"]; length=cr["length"]
            if member not in sizes or type(off)is not int or off<0 or type(length)is not int or length<1 or off+length>sizes[member]: raise ValueError("cache range outside source member bounds")
            if (cr["source_id"],cr["revision"],cr["representation"]) != (model.source_id,model.revision,model.representation): raise ValueError("cache range source identity mismatch")
            key=_text(cr["cache_key"],"cache_key")
            if not re.fullmatch(r'[0-9a-f]{16}',key): raise ValueError('cache_key must be exact 16-character lowercase hexadecimal')
            ranges.append(CacheRange(_text(cr["state_id"],"cache.state_id"),member,off,length,_digest(cr["sha256"],"cache.sha256"),key,*ident,_text(cr["unit_id"],"unit_id")))
        if len({x.cache_key for x in ranges})!=len(ranges): raise ValueError("duplicate cache key")
        participants.append(Participant(role,node,cu,transport,_text(r["execution_address"],"execution_address"),endpoint,_text(r["device"],"device"),_path(r["source_path"],"source_path"),_path(r["runtime_executable"],"runtime_executable"),_digest(r["runtime_sha256"],"runtime_sha256"),_path(r["cache_path"],"cache_path"),port,_path(r["lifecycle_dir"],"lifecycle_dir"),*ident,tuple(ranges)))
    if roles!={"client","remote"}: raise ValueError("exactly one client and one remote role required")
    client=next(x for x in participants if x.role=="client"); remote=next(x for x in participants if x.role=="remote")

    if not isinstance(data["placement"],list) or not data["placement"]: raise ValueError("placement must be nonempty")
    placements=[]; units=set()
    for r in data["placement"]:
        _keys(r,{"unit_id","compute_id","state_ids","state_ranges","first_layer","last_layer","output"},"placement")
        uid=_text(r["unit_id"],"unit_id"); cu=_text(r["compute_id"],"compute_id"); states=r["state_ids"]
        if uid in units or cu not in cus: raise ValueError("duplicate unit or unknown compute id")
        if not isinstance(states,list) or (not states and cu!=client.compute_id) or any(not isinstance(s,str) or not s for s in states) or len(set(states))!=len(states): raise ValueError("invalid state_ids")
        raw_ranges = r["state_ranges"]
        if not isinstance(raw_ranges, list): raise ValueError("placement state_ranges must be a list")
        state_ranges = []
        for state_range in raw_ranges:
            _keys(state_range, {"state_id", "member", "offset", "length"}, "placement state range")
            state_id = _text(state_range["state_id"], "state_range.state_id")
            member = _text(state_range["member"], "state_range.member")
            offset, length = state_range["offset"], state_range["length"]
            if member not in {m[0] for m in members} or type(offset) is not int or offset < 0 or type(length) is not int or length < 1 or offset + length > sizes[member]:
                raise ValueError("placement state range outside source member bounds")
            state_ranges.append((state_id, member, offset, length))
        if {item[0] for item in state_ranges} != set(states) or len(state_ranges) != len(states):
            raise ValueError("placement state ranges must describe every state exactly once")
        if type(r["first_layer"]) is not int or type(r["last_layer"]) is not int or type(r["output"]) is not bool: raise ValueError("invalid placement range")
        units.add(uid); placements.append(Placement(uid,cu,tuple(states),tuple(state_ranges),r["first_layer"],r["last_layer"],r["output"]))
    required_opts={"hidden_layers","offload_tail","cpu_experts","tensor_split","context","slots","startup_timeout_seconds","split_mode","verbosity"}
    if not isinstance(data['backend_options'], Mapping) or set(data['backend_options']) not in (required_opts,required_opts|{'rpc_physical_device'}): raise ValueError('unsupported backend option fields')
    b=data["backend_options"]
    if type(b["cpu_experts"]) is not bool or b["split_mode"]!="layer": raise ValueError("unsupported backend option")
    ts=b["tensor_split"]
    if not isinstance(ts,list) or len(ts)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) or v<=0 for v in ts): raise ValueError("tensor_split requires two finite positive values")
    rpc_device = None if 'rpc_physical_device' not in b else _text(b['rpc_physical_device'],'rpc_physical_device')
    opts=BackendOptions(_int(b["hidden_layers"],"hidden_layers"),_int(b["offload_tail"],"offload_tail"),b["cpu_experts"],tuple(float(v) for v in ts),_int(b["context"],"context"),_int(b["slots"],"slots"),_int(b["startup_timeout_seconds"],"startup_timeout_seconds",3600),b["split_mode"],_int(b["verbosity"],"verbosity",10),rpc_device)
    _keys(data["request"],{"prompt","max_tokens","temperature","seed"},"request"); q=data["request"]
    if not isinstance(q["prompt"],str) or not q["prompt"] or type(q["max_tokens"]) is not int or q["max_tokens"]<1 or type(q["temperature"]) not in (int,float) or not math.isfinite(q["temperature"]) or not 0<=q["temperature"]<=2 or type(q["seed"]) is not int: raise ValueError("invalid request settings")
    bindings = tuple(RuntimeBinding(p.role, p.runtime_executable, p.runtime_sha256) for p in participants)
    return OperatorConfig(_text(data["plan_id"],"plan_id"),model,tuple(participants),_text(data["strategy_id"],"strategy_id"),tuple(placements),opts,tuple(sorted(q.items())),bindings)

# New schema types are deliberately separate: legacy dataclasses and parsing
# above retain their accepted /2 representation and ordering.
from .profiles import (ResourceSnapshot, ProfileSubject, EVIDENCE_CLASSES, freeze,
                       parse_profiles, validate_profiles, integer, sha256, thaw, keys, _texts, _array)


@dataclass(frozen=True)
class PhysicalBinding:
    binding_id: str
    compute_id: str
    memory_id: str
    physical_id: str
    native_selector: str
    visible_selector: str
    runtime_id: str
    evidence_id: str
    evidence_sha256: str


@dataclass(frozen=True)
class BackingDescriptor:
    memory_id: str
    member: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class ProfiledParticipant:
    participant_id: str
    role: str
    host_id: str
    boot_epoch: str
    topology_epoch: str
    transport: str
    execution_address: str
    rpc_endpoint: str | None
    source_path: str
    runtime_executable: str
    runtime_sha256: str
    cache_path: str
    port: int
    lifecycle_dir: str
    source_id: str
    source_revision: str
    source_representation: str
    bindings: tuple[PhysicalBinding, ...]
    backing: tuple[BackingDescriptor, ...]
    cache_ranges: tuple[CacheRange, ...]


@dataclass(frozen=True)
class BindingPlacement:
    unit_id: str
    binding_id: str
    state_ids: tuple[str, ...]
    state_ranges: tuple[tuple[str, str, int, int], ...]


@dataclass(frozen=True)
class MetadataIdentity:
    path: str
    sha256: str
    digest: str


@dataclass(frozen=True)
class ProfileIdentity:
    sha256: str | None
    digest: str
    snapshot: ResourceSnapshot


@dataclass(frozen=True)
class MemoryLimit:
    memory_id: str
    peak_bytes: int
    min_available_bytes: int
    reserve_bytes: int


@dataclass(frozen=True)
class ProfilePolicy:
    max_age_seconds: int
    allowed_evidence_classes: tuple[str, ...]
    memory_limits: tuple[MemoryLimit, ...]


@dataclass(frozen=True)
class WorkloadSettings:
    context: int
    slots: int
    batch: int
    microbatch: int
    cache_settings: tuple


@dataclass(frozen=True)
class ProfiledOperatorConfig:
    plan_id: str
    model: ModelIdentity
    participants: tuple[ProfiledParticipant, ...]
    strategy_id: str
    selection: str
    metadata: MetadataIdentity
    profiles: ProfileIdentity
    policy: ProfilePolicy
    workload: WorkloadSettings
    placement: tuple[BindingPlacement, ...]
    strategy_options: tuple
    request: tuple
    profile_mode: str


MAX_PROFILE_BYTES = 4 << 20


def _descriptor_path(value, *, base_dir, where, require_base=False):
    value = _text(value, where)
    path = Path(value)
    if not path.is_absolute() and base_dir is not None:
        path = Path(base_dir).absolute() / path
    elif not path.is_absolute() and require_base:
        raise ValueError('relative profile path requires config directory')
    return str(path)


def _profile_identity(value, *, base_dir):
    if not isinstance(value, Mapping): raise ValueError('profiles descriptor must be mapping')
    expected = {'snapshot','digest'} if 'snapshot' in value else {'path','sha256','digest'}
    keys(value, expected, 'profiles descriptor')
    expected_digest = _digest(value['digest'], 'profile normalized digest')
    file_sha = None
    if 'snapshot' in value:
        raw = value['snapshot']
    else:
        file_sha = _digest(value['sha256'], 'profile file SHA-256')
        path = _descriptor_path(value['path'], base_dir=base_dir, where='profile path', require_base=True)
        with Path(path).open('rb') as stream: content = stream.read(MAX_PROFILE_BYTES+1)
        if len(content) > MAX_PROFILE_BYTES: raise ValueError('oversized profile JSON')
        if hashlib.sha256(content).hexdigest() != file_sha: raise ValueError('profile file SHA-256 mismatch')
        try:
            raw = json.loads(content, object_pairs_hook=_strict_pairs,
                             parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite profile JSON')))
        except (json.JSONDecodeError, UnicodeDecodeError, RecursionError) as exc:
            raise ValueError('invalid profile JSON') from exc
    snapshot = parse_profiles(raw)
    if snapshot.digest != expected_digest: raise ValueError('profile normalized digest mismatch')
    return ProfileIdentity(file_sha, expected_digest, snapshot)


def _model_v3(value):
    keys(value, ('source_id','revision','representation','members'), 'model')
    members = []
    for row in _array(value['members'], 'model members'):
        keys(row, ('name','sha256','size_bytes'), 'member')
        name = _text(row['name'],'member.name')
        if Path(name).name != name or name in ('.','..'): raise ValueError('member.name must be basename')
        members.append((name, _digest(row['sha256'],'member.sha256'), integer(row['size_bytes'],'member.size_bytes',minimum=1)))
    if len({r[0] for r in members}) != len(members): raise ValueError('duplicate model member')
    return ModelIdentity(_text(value['source_id'],'source_id'), _text(value['revision'],'revision'),
                         _text(value['representation'],'representation'), tuple(sorted(members)))


def _policy_v3(value):
    keys(value, [f.name for f in fields(ProfilePolicy)], 'policy')
    max_age = integer(value['max_age_seconds'],'max_age_seconds',minimum=1)
    allowed = _texts(value['allowed_evidence_classes'], 'allowed_evidence_classes')
    if not set(allowed) <= EVIDENCE_CLASSES: raise ValueError('unsupported allowed evidence classes')
    limits = []
    for raw in _array(value['memory_limits'],'memory limits'):
        keys(raw, [f.name for f in fields(MemoryLimit)], 'memory limit')
        limits.append(MemoryLimit(_text(raw['memory_id'],'memory_id'),
                      integer(raw['peak_bytes'],'peak_bytes',minimum=1),
                      integer(raw['min_available_bytes'],'min_available_bytes'),
                      integer(raw['reserve_bytes'],'reserve_bytes')))
    if len({r.memory_id for r in limits}) != len(limits): raise ValueError('duplicate memory limit')
    return ProfilePolicy(max_age, allowed, tuple(sorted(limits,key=lambda r:r.memory_id)))


def _workload_v3(value):
    keys(value, [f.name for f in fields(WorkloadSettings)], 'workload')
    if not isinstance(value['cache_settings'], Mapping): raise ValueError('cache_settings must be mapping')
    cache_settings = freeze(value['cache_settings'])
    assert isinstance(cache_settings, tuple)
    return WorkloadSettings(integer(value['context'],'context',minimum=1), integer(value['slots'],'slots',minimum=1),
                            integer(value['batch'],'batch',minimum=1), integer(value['microbatch'],'microbatch',minimum=1),
                            cache_settings)


def _request_v3(value):
    keys(value, ('prompt','max_tokens','temperature','seed'), 'request')
    _text(value['prompt'],'request.prompt')
    integer(value['max_tokens'],'request.max_tokens',minimum=1); integer(value['seed'],'request.seed')
    temperature=value['temperature']
    if type(temperature) not in (int,float) or not math.isfinite(temperature) or not 0 <= temperature <= 2:
        raise ValueError('invalid request temperature')
    return tuple(sorted(value.items()))


def _range_v3(raw, *, members, model, cache=False) -> Any:
    expected = {'state_id','member','offset','length'}
    if cache: expected |= {'sha256','cache_key','source_id','revision','representation','unit_id'}
    keys(raw, expected, 'cache range' if cache else 'state range')
    state = _text(raw['state_id'],'state_id'); member = _text(raw['member'],'range.member')
    offset, length = raw['offset'], raw['length']
    if member not in members or type(offset) is not int or offset < 0 or type(length) is not int or length < 1 or offset+length > members[member][1]:
        raise ValueError('state range outside source member bounds')
    if not cache: return (state, member, offset, length)
    if (raw['source_id'],raw['revision'],raw['representation']) != (model.source_id,model.revision,model.representation):
        raise ValueError('cache range source identity mismatch')
    _digest(raw['sha256'],'cache.sha256')
    if not isinstance(raw['cache_key'],str) or not re.fullmatch('[0-9a-f]{16}',raw['cache_key']):
        raise ValueError('cache_key must be exact 16-character lowercase hexadecimal')
    _text(raw['unit_id'],'cache.unit_id')
    return CacheRange(**raw)


def _participants_v3(value, *, model, snapshot):
    if not isinstance(value,list) or len(value) != 2: raise ValueError('exactly two participants required')
    hosts = {r.host_id:r for r in snapshot.hosts}
    members = {name:(digest,size) for name,digest,size in model.members}
    participants = []; seen_roles=set(); seen_hosts=set(); seen_ids=set(); seen_bindings=set(); seen_computes=set()
    for raw in value:
        keys(raw, [f.name for f in fields(ProfiledParticipant)], 'participant/3')
        row = dict(raw)
        for field in ('participant_id','role','host_id','boot_epoch','topology_epoch','execution_address','transport'):
            _text(row[field],field)
        role=row['role']; host=row['host_id']
        if role not in ('client','remote') or role in seen_roles: raise ValueError('exactly one client and one remote role required')
        if host in seen_hosts or row['participant_id'] in seen_ids: raise ValueError('duplicate participant identity')
        seen_roles.add(role); seen_hosts.add(host); seen_ids.add(row['participant_id'])
        if host not in hosts: raise ValueError(f'missing host profile: {host}')
        if row['boot_epoch'] != hosts[host].boot_epoch: raise ValueError('participant boot epoch mismatch')
        if row['topology_epoch'] != hosts[host].topology_epoch: raise ValueError('participant topology epoch mismatch')
        if row['transport'] != ('local' if role=='client' else 'rpc'): raise ValueError('unsupported participant transport for role')
        port=integer(row['port'],'port',minimum=1,maximum=65535)
        endpoint=row['rpc_endpoint']
        if role=='remote':
            endpoint=_text(endpoint,'rpc_endpoint')
            address, sep, endpoint_port=endpoint.rpartition(':')
            if not address or not sep or not endpoint_port.isdigit() or int(endpoint_port) != port:
                raise ValueError('rpc_endpoint must match participant port')
        elif endpoint is not None: raise ValueError('client rpc_endpoint must be null')
        for field in ('source_path','runtime_executable','cache_path','lifecycle_dir'): _path(row[field],field)
        _digest(row['runtime_sha256'],'runtime_sha256')
        if (row['source_id'],row['source_revision'],row['source_representation']) != (model.source_id,model.revision,model.representation):
            raise ValueError('participant source identity mismatch')
        bindings=[]
        local_seen={key:set() for key in ('native_selector','visible_selector')}
        # Detect duplicate identities before interpreting any altered binding.
        for br in _array(row['bindings'],'bindings'):
            keys(br, [f.name for f in fields(PhysicalBinding)], 'binding')
            for field in br: _text(br[field],field)
            _digest(br['evidence_sha256'],'binding evidence_sha256')
            for field,seen in (('binding_id',seen_bindings),('compute_id',seen_computes),*local_seen.items()):
                if br[field] in seen: raise ValueError('duplicate binding '+field)
                seen.add(br[field])
            bindings.append(PhysicalBinding(**br))
        row['bindings']=tuple(sorted(bindings,key=lambda r:r.binding_id))
        backing=[]; seen_backing=set()
        for br in _array(row['backing'],'backing',nonempty=False):
            keys(br,[f.name for f in fields(BackingDescriptor)],'backing descriptor')
            mid=_text(br['memory_id'],'backing.memory_id'); member=_text(br['member'],'backing.member')
            _digest(br['sha256'],'backing.sha256'); integer(br['size_bytes'],'backing.size_bytes',minimum=1)
            if (mid,member) in seen_backing: raise ValueError('duplicate backing descriptor')
            seen_backing.add((mid,member))
            if members.get(member) != (br['sha256'],br['size_bytes']): raise ValueError('backing source identity mismatch')
            memory=next((r for r in snapshot.memory_resources if r.memory_id==mid),None)
            if memory is None or memory.host_id != host or memory.kind != 'storage': raise ValueError('backing memory domain mismatch')
            backing.append(BackingDescriptor(**br))
        row['backing']=tuple(sorted(backing,key=lambda r:(r.memory_id,r.member)))
        ranges=tuple(_range_v3(r,members=members,model=model,cache=True) for r in _array(row['cache_ranges'],'cache ranges',nonempty=False))
        if len({r.cache_key for r in ranges}) != len(ranges): raise ValueError('duplicate cache key')
        row['cache_ranges']=tuple(sorted(ranges,key=lambda r:(r.unit_id,r.state_id,r.member,r.offset)))
        participants.append(ProfiledParticipant(**row))
    return tuple(sorted(participants,key=lambda p:p.participant_id))


def _placements_v3(value, *, participants, model):
    bindings={b.binding_id for p in participants for b in p.bindings}
    members={name:(digest,size) for name,digest,size in model.members}
    result=[]; units=set()
    for raw in _array(value,'placement'):
        keys(raw,[f.name for f in fields(BindingPlacement)],'placement/3')
        uid=_text(raw['unit_id'],'unit_id'); bid=_text(raw['binding_id'],'binding_id')
        if uid in units: raise ValueError('duplicate placement unit_id')
        units.add(uid)
        if bid not in bindings: raise ValueError('unknown placement binding')
        states=tuple(sorted(_text(s,'state_id') for s in _array(raw['state_ids'],'state ids',nonempty=False)))
        if len(set(states))!=len(states): raise ValueError('duplicate placement state_id')
        ranges=tuple(sorted(_range_v3(r,members=members,model=model) for r in _array(raw['state_ranges'],'state ranges',nonempty=False)))
        if {r[0] for r in ranges} != set(states) or len(ranges)!=len(states):
            raise ValueError('state ranges must describe every state exactly once')
        result.append(BindingPlacement(uid,bid,states,ranges))
    return tuple(sorted(result,key=lambda r:r.unit_id))


def profile_subject(config, *, profile_mode='live') -> ProfileSubject:
    """Explicit subject to feed generic validation; no model legality decisions."""
    snapshot=config.profiles.snapshot
    bindings=tuple(b for p in config.participants for b in p.bindings)
    memory_ids={b.memory_id for b in bindings}|{b.memory_id for p in config.participants for b in p.backing}
    # Workload tuple maps remain tuples in Python but hash JSON object semantics.
    workload=asdict(config.workload); workload['cache_settings']=thaw(config.workload.cache_settings)
    dependencies=tuple(sorted([('model:source_id',config.model.source_id),('model:revision',config.model.revision),
                               ('model:representation',config.model.representation),('workload:digest',sha256(workload))]))
    return ProfileSubject(tuple(sorted(p.host_id for p in config.participants)),
                          tuple(sorted(b.compute_id for b in bindings)), tuple(sorted(memory_ids)),
                          tuple(sorted(link.link_id for link in snapshot.links)), tuple(sorted(b.runtime_id for b in bindings)),
                          dependencies,profile_mode)


def validate_config_profiles(config, *, now=None, profile_mode='live') -> tuple[str, ...]:
    """Recheck freshness at planning/execution; live defaults to real UTC now."""
    if not isinstance(config,ProfiledOperatorConfig): raise ValueError('config/3 required for profile validation')
    snapshot=config.profiles.snapshot
    reasons=list(validate_profiles(snapshot,now=now,policy=config.policy,subject=profile_subject(config,profile_mode=profile_mode)))
    if config.profiles.digest != snapshot.digest: reasons.append('profile normalized digest mismatch')
    if {r.memory_id for r in config.policy.memory_limits} != {r.memory_id for r in snapshot.memory_resources}:
        reasons.append('memory policy coverage mismatch')
    computes={r.compute_id:r for r in snapshot.compute_units}; memories={r.memory_id:r for r in snapshot.memory_resources}
    runtimes={r.runtime_id:r for r in snapshot.runtime_capabilities}; evidence={r.evidence_id:r for r in snapshot.evidence}
    host_ids={p.host_id for p in config.participants}
    if not any({link.source_host_id,link.target_host_id}==host_ids for link in snapshot.links):
        reasons.append('missing measured link profile between participants')
    for participant in config.participants:
        endpoint_runtimes=[runtimes[b.runtime_id] for b in participant.bindings if b.runtime_id in runtimes]
        for field in ('source_revision','build_id'):
            if len({getattr(r,field) for r in endpoint_runtimes})>1:
                reasons.append('endpoint runtime '+field+' mismatch')
        for binding in participant.bindings:
            cu=computes.get(binding.compute_id); memory=memories.get(binding.memory_id); runtime=runtimes.get(binding.runtime_id)
            if cu is None: reasons.append('compute profile coverage mismatch'); continue
            if cu.physical_id != binding.physical_id or cu.host_id != participant.host_id: reasons.append('binding physical identity mismatch')
            if memory is None or binding.memory_id not in cu.memory_ids or memory.host_id != participant.host_id:
                reasons.append('binding memory affinity mismatch')
            e=evidence.get(binding.evidence_id)
            if e is None or cu.evidence_id!=binding.evidence_id or e.sha256!=binding.evidence_sha256:
                reasons.append('binding evidence identity mismatch')
            if runtime is None or runtime.host_id!=participant.host_id or runtime.compute_id!=binding.compute_id or runtime.backend!=cu.backend:
                reasons.append('binding runtime context mismatch')
            elif runtime.binary_sha256!=participant.runtime_sha256: reasons.append('binding runtime binary mismatch')
    return tuple(reasons)


def _parse_config_v3(data, *, base_dir, now, profile_mode):
    keys(data, ('schema','plan_id','model','participants','strategy_id','selection','metadata','profiles','policy','workload','placement','strategy_options','request'), 'config/3')
    _text(data['plan_id'],'plan_id')
    if data['strategy_id'] != 'qwen38-q8-fixed/1': raise ValueError('unsupported strategy_id')
    if data['selection'] not in ('one-gpu','cpu-only'): raise ValueError('unsupported explicit selection')
    if profile_mode not in ('live','replay'): raise ValueError('unsupported profile validation mode')
    model=_model_v3(data['model']); policy=_policy_v3(data['policy']); workload=_workload_v3(data['workload'])
    request=_request_v3(data['request'])
    if not isinstance(data['strategy_options'],Mapping): raise ValueError('strategy_options must be opaque mapping')
    strategy_options=freeze(data['strategy_options'])
    assert isinstance(strategy_options, tuple)
    keys(data['metadata'],[f.name for f in fields(MetadataIdentity)],'metadata identity')
    metadata=MetadataIdentity(_descriptor_path(data['metadata']['path'],base_dir=base_dir,where='metadata path'),
                              _digest(data['metadata']['sha256'],'metadata.sha256'),_digest(data['metadata']['digest'],'metadata.digest'))
    profiles=_profile_identity(data['profiles'],base_dir=base_dir)
    participants=_participants_v3(data['participants'],model=model,snapshot=profiles.snapshot)
    placements=_placements_v3(data['placement'],participants=participants,model=model)
    result=ProfiledOperatorConfig(data['plan_id'],model,participants,data['strategy_id'],data['selection'],metadata,profiles,
                                  policy,workload,placements,strategy_options,request,profile_mode)
    reasons=validate_config_profiles(result,now=now,profile_mode=profile_mode)
    if reasons: raise ValueError('; '.join(reasons))
    return result


def parse_config(data: Mapping[str, Any], *, base_dir=None, now=None, profile_mode='live') -> OperatorConfig | ProfiledOperatorConfig:
    if isinstance(data, Mapping) and data.get('schema') == 'operator-config/3':
        return _parse_config_v3(data, base_dir=base_dir, now=now, profile_mode=profile_mode)
    if isinstance(data, Mapping) and data.get('schema') not in (None, 'operator-config/2'):
        raise ValueError('unsupported schema')
    return _parse_config_v2(data)


def load_config(path: str | Path, *, now=None, profile_mode='live') -> OperatorConfig | ProfiledOperatorConfig:
    path = Path(path)
    return parse_config_json(path.read_text(encoding='utf-8'), base_dir=path.parent, now=now, profile_mode=profile_mode)


__all__ = ['BackendOptions','CacheRange','ModelIdentity','OperatorConfig','Participant','Placement','RuntimeBinding',
           'ProfiledOperatorConfig','PhysicalBinding','ProfiledParticipant','BindingPlacement','MetadataIdentity',
           'ProfileIdentity','MemoryLimit','ProfilePolicy','WorkloadSettings','BackingDescriptor',
           'load_config','parse_config','parse_config_json','profile_subject','validate_config_profiles']

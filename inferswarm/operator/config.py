"""Strict, side-effect-free operator configuration parsing."""
from __future__ import annotations
import json, math
from dataclasses import dataclass
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
    member: str; offset: int; length: int; sha256: str; cache_key: str
    source_id: str; revision: str; representation: str; unit_id: str

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
    first_layer: int; last_layer: int; output: bool

@dataclass(frozen=True)
class BackendOptions:
    hidden_layers: int; offload_tail: int; cpu_experts: bool
    tensor_split: tuple[float, ...]; context: int; slots: int
    startup_timeout_seconds: int; split_mode: str; verbosity: int

@dataclass(frozen=True)
class OperatorConfig:
    plan_id: str; model: ModelIdentity; participants: tuple[Participant, ...]
    strategy_id: str; placement: tuple[Placement, ...]
    backend_options: BackendOptions; request: tuple[tuple[str, Any], ...]

def _strict_pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out: raise ValueError(f"duplicate JSON key: {key}")
        out[key] = value
    return out

def parse_config_json(text: str) -> OperatorConfig:
    try: data = json.loads(text, object_pairs_hook=_strict_pairs, parse_constant=lambda x: (_ for _ in ()).throw(ValueError("non-finite JSON number")))
    except (json.JSONDecodeError, TypeError) as exc: raise ValueError("invalid config JSON") from exc
    return parse_config(data)

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

def parse_config(data: Mapping[str, Any]) -> OperatorConfig:
    _keys(data, {"schema","plan_id","model","participants","strategy_id","placement","backend_options","request"}, "config")
    if data["schema"] != "operator-config/2": raise ValueError("unsupported schema")
    _keys(data["model"], {"source_id","revision","representation","members"}, "model")
    m=data["model"]
    if not isinstance(m["members"], list) or not m["members"]: raise ValueError("model.members must be nonempty")
    members=[]
    for r in m["members"]:
        _keys(r,{"name","sha256","size_bytes"},"member"); name=_text(r["name"],"member.name")
        if Path(name).name != name or name in (".",".."): raise ValueError("member.name must be basename")
        members.append((name,_digest(r["sha256"],"member.sha256"),_int(r["size_bytes"],"member.size_bytes")))
    if len({x[0] for x in members}) != len(members): raise ValueError("duplicate model member")
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
        if not isinstance(r["cache_ranges"],list) or not r["cache_ranges"]: raise ValueError("cache_ranges must be nonempty")
        ranges=[]; sizes={n:size for n,_,size in members}
        for cr in r["cache_ranges"]:
            _keys(cr,{"member","offset","length","sha256","cache_key","source_id","revision","representation","unit_id"},"cache range")
            member=_text(cr["member"],"cache.member"); off=cr["offset"]; length=cr["length"]
            if member not in sizes or type(off)is not int or off<0 or type(length)is not int or length<1 or off+length>sizes[member]: raise ValueError("cache range outside source member bounds")
            if (cr["source_id"],cr["revision"],cr["representation"]) != (model.source_id,model.revision,model.representation): raise ValueError("cache range source identity mismatch")
            ranges.append(CacheRange(member,off,length,_digest(cr["sha256"],"cache.sha256"),_text(cr["cache_key"],"cache_key"),*ident,_text(cr["unit_id"],"unit_id")))
        if len({x.cache_key for x in ranges})!=len(ranges): raise ValueError("duplicate cache key")
        participants.append(Participant(role,node,cu,transport,_text(r["execution_address"],"execution_address"),endpoint,_text(r["device"],"device"),_path(r["source_path"],"source_path"),_path(r["runtime_executable"],"runtime_executable"),_digest(r["runtime_sha256"],"runtime_sha256"),_path(r["cache_path"],"cache_path"),port,_path(r["lifecycle_dir"],"lifecycle_dir"),*ident,tuple(ranges)))
    if roles!={"client","remote"}: raise ValueError("exactly one client and one remote role required")
    client=next(x for x in participants if x.role=="client"); remote=next(x for x in participants if x.role=="remote")
    if (client.runtime_executable,client.runtime_sha256)!=(remote.runtime_executable,remote.runtime_sha256): raise ValueError("runtime executable identity mismatch")
    if not isinstance(data["placement"],list) or not data["placement"]: raise ValueError("placement must be nonempty")
    placements=[]; units=set()
    for r in data["placement"]:
        _keys(r,{"unit_id","compute_id","state_ids","first_layer","last_layer","output"},"placement")
        uid=_text(r["unit_id"],"unit_id"); cu=_text(r["compute_id"],"compute_id"); states=r["state_ids"]
        if uid in units or cu not in cus: raise ValueError("duplicate unit or unknown compute id")
        if not isinstance(states,list) or not states or any(not isinstance(s,str) or not s for s in states) or len(set(states))!=len(states): raise ValueError("invalid state_ids")
        if type(r["first_layer"]) is not int or type(r["last_layer"]) is not int or type(r["output"]) is not bool: raise ValueError("invalid placement range")
        units.add(uid); placements.append(Placement(uid,cu,tuple(states),r["first_layer"],r["last_layer"],r["output"]))
    _keys(data["backend_options"],{"hidden_layers","offload_tail","cpu_experts","tensor_split","context","slots","startup_timeout_seconds","split_mode","verbosity"},"backend_options")
    b=data["backend_options"]
    if type(b["cpu_experts"]) is not bool or b["split_mode"]!="layer": raise ValueError("unsupported backend option")
    ts=b["tensor_split"]
    if not isinstance(ts,list) or len(ts)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) or v<=0 for v in ts): raise ValueError("tensor_split requires two finite positive values")
    opts=BackendOptions(_int(b["hidden_layers"],"hidden_layers"),_int(b["offload_tail"],"offload_tail"),b["cpu_experts"],tuple(float(v) for v in ts),_int(b["context"],"context"),_int(b["slots"],"slots"),_int(b["startup_timeout_seconds"],"startup_timeout_seconds",3600),b["split_mode"],_int(b["verbosity"],"verbosity",10))
    _keys(data["request"],{"prompt","max_tokens","temperature","seed"},"request"); q=data["request"]
    if not isinstance(q["prompt"],str) or not q["prompt"] or type(q["max_tokens"]) is not int or q["max_tokens"]<1 or type(q["temperature"]) not in (int,float) or not math.isfinite(q["temperature"]) or not 0<=q["temperature"]<=2 or type(q["seed"]) is not int: raise ValueError("invalid request settings")
    return OperatorConfig(_text(data["plan_id"],"plan_id"),model,tuple(participants),_text(data["strategy_id"],"strategy_id"),tuple(placements),opts,tuple(sorted(q.items())))

def load_config(path: str | Path) -> OperatorConfig:
    return parse_config_json(Path(path).read_text(encoding="utf-8"))

__all__=["BackendOptions","CacheRange","ModelIdentity","OperatorConfig","Participant","Placement","load_config","parse_config","parse_config_json"]

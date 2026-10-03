"""Pure parsing and validation for ordinary operator configuration."""
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

@dataclass(frozen=True)
class ModelIdentity:
    source_id: str
    revision: str
    representation: str
    members: tuple[tuple[str, str], ...]

@dataclass(frozen=True)
class Participant:
    node_id: str
    compute_id: str
    transport: str
    address: str
    device: str
    source_path: str
    runtime_executable: str
    runtime_sha256: str
    cache_path: str
    port: int
    lifecycle_dir: str
    backing_verified: bool = False

@dataclass(frozen=True)
class Placement:
    unit_id: str
    compute_id: str
    native_args: tuple[str, ...]

@dataclass(frozen=True)
class OperatorConfig:
    plan_id: str
    model: ModelIdentity
    participants: tuple[Participant, ...]
    strategy_id: str
    placement: tuple[Placement, ...]
    request: tuple[tuple[str, Any], ...]

_HEX = set("0123456789abcdef")
def _keys(value: Mapping[str, Any], expected: set[str], where: str) -> None:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ValueError(f"{where}: expected exactly {sorted(expected)}")
def _text(v: Any, name: str) -> str:
    if not isinstance(v, str) or not v.strip(): raise ValueError(f"{name} must be non-empty text")
    return v
def _digest(v: Any, name: str) -> str:
    if not isinstance(v, str) or len(v) != 64 or any(c not in _HEX for c in v): raise ValueError(f"{name} must be lowercase SHA-256")
    return v

def parse_config(data: Mapping[str, Any]) -> OperatorConfig:
    _keys(data, {"schema","plan_id","model","participants","strategy_id","placement","request"}, "config")
    if data["schema"] != "operator-config/1": raise ValueError("unsupported schema")
    _keys(data["model"], {"source_id","revision","representation","members"}, "model")
    m=data["model"]
    members=[]
    if not isinstance(m["members"], list) or not m["members"]: raise ValueError("model.members must be nonempty")
    for row in m["members"]:
        _keys(row,{"name","sha256"},"member"); members.append((_text(row["name"],"member.name"),_digest(row["sha256"],"member.sha256")))
    if len({n for n,_ in members}) != len(members): raise ValueError("duplicate model member")
    model=ModelIdentity(_text(m["source_id"],"source_id"),_text(m["revision"],"revision"),_text(m["representation"],"representation"),tuple(members))
    if not isinstance(data["participants"],list) or len(data["participants"])<2: raise ValueError("at least two participants required")
    participants=[]; nodes=set(); cus=set()
    pk={"node_id","compute_id","transport","address","device","source_path","runtime_executable","runtime_sha256","cache_path","port","lifecycle_dir","source_id","source_revision","source_representation"}
    for row in data["participants"]:
        _keys(row,pk,"participant")
        if (row["source_id"],row["source_revision"],row["source_representation"]) != (model.source_id,model.revision,model.representation): raise ValueError("participant source identity mismatch")
        n=_text(row["node_id"],"node_id"); cu=_text(row["compute_id"],"compute_id")
        if n in nodes or cu in cus: raise ValueError("duplicate participant identity")
        nodes.add(n); cus.add(cu)
        port=row["port"]
        if type(port) is not int or not 1 <= port <= 65535: raise ValueError("port must be integer 1..65535")
        participants.append(Participant(n,cu,*(_text(row[k],k) for k in ("transport","address","device","source_path","runtime_executable")),_digest(row["runtime_sha256"],"runtime_sha256"),_text(row["cache_path"],"cache_path"),port,_text(row["lifecycle_dir"],"lifecycle_dir")))
    if len({p.port for p in participants}) != len(participants): raise ValueError("duplicate port")
    if not isinstance(data["placement"],list) or not data["placement"]: raise ValueError("placement must be nonempty")
    placements=[]; units=set()
    for row in data["placement"]:
        _keys(row,{"unit_id","compute_id","native_args"},"placement")
        u=_text(row["unit_id"],"unit_id"); cu=_text(row["compute_id"],"compute_id")
        if u in units or cu not in cus: raise ValueError("duplicate unit or unknown compute id")
        units.add(u)
        args=row["native_args"]
        if not isinstance(args,list) or not all(isinstance(a,str) and a for a in args): raise ValueError("native_args must be text array")
        placements.append(Placement(u,cu,tuple(args)))
    req=data["request"]
    if not isinstance(req,dict) or set(req)!={"prompt","max_tokens","temperature"}: raise ValueError("invalid request fields")
    if not isinstance(req["prompt"],str) or not req["prompt"] or type(req["max_tokens"]) is not int or req["max_tokens"]<=0 or type(req["temperature"]) not in (int,float) or not 0<=req["temperature"]<=2: raise ValueError("invalid request settings")
    return OperatorConfig(_text(data["plan_id"],"plan_id"),model,tuple(participants),_text(data["strategy_id"],"strategy_id"),tuple(placements),tuple(sorted(req.items())))

def load_config(path: str | Path) -> OperatorConfig:
    with open(path,encoding="utf-8") as f: return parse_config(json.load(f))

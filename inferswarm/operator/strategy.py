"""Typed pure llama.cpp strategy realization; never launches processes."""
from __future__ import annotations
from dataclasses import dataclass
from .plan import OperatorPlan

@dataclass(frozen=True)
class ExpectedPlacement:
    unit_id: str
    compute_id: str
    first_layer: int
    last_layer: int
    output: bool

@dataclass(frozen=True)
class LaunchSpec:
    executable: str
    executable_sha256: str
    execution_address: str
    rpc_endpoint: str
    device: str
    args: tuple[str, ...]
    expected_placement: tuple[ExpectedPlacement, ...]
    context: int
    slots: int
    startup_timeout_seconds: int

def llama_cpp_spec(plan: OperatorPlan) -> LaunchSpec:
    if plan.strategy_id != "llama.cpp": raise ValueError("unsupported strategy id")
    clients=[p for p in plan.participants if p.role=="client"]
    remotes=[p for p in plan.participants if p.role=="remote"]
    if len(clients)!=1 or len(remotes)!=1: raise ValueError("exact client/remote roles required")
    client,remote=clients[0],remotes[0]
    if remote.rpc_endpoint is None: raise ValueError("remote RPC endpoint is required")
    opt=plan.backend_options
    if opt.hidden_layers!=48 or opt.offload_tail<1 or opt.offload_tail>opt.hidden_layers: raise ValueError("unsupported explicit llama.cpp layer dimensions")
    threshold=opt.hidden_layers-opt.offload_tail
    spans=sorted(plan.placement,key=lambda x:x.first_layer); cursor=0; out=0; expected=[]
    if opt.offload_tail!=8 or len(spans)!=3:
        raise ValueError("llama.cpp adapter requires the explicit accepted three-range layer topology")
    required=((client.compute_id,0,40,False),(client.compute_id,41,44,False),(remote.compute_id,45,47,True))
    actual=tuple((row.compute_id,row.first_layer,row.last_layer,row.output) for row in spans)
    if actual!=required:
        raise ValueError("placement does not match the adapter's explicit accepted range contract")
    for row in spans:
        if row.first_layer!=cursor or row.last_layer<row.first_layer or row.last_layer>=opt.hidden_layers: raise ValueError("placement ranges must completely and disjointly cover hidden layers in order")
        if row.output:
            out+=1
            if row.compute_id!=remote.compute_id or row.last_layer!=opt.hidden_layers-1: raise ValueError("output assignment must be on final remote placement")
        expected.append(ExpectedPlacement(row.unit_id,row.compute_id,row.first_layer,row.last_layer,row.output)); cursor=row.last_layer+1
    if cursor!=opt.hidden_layers or out!=1: raise ValueError("placement must cover hidden layers and assign output exactly once")
    if {p.compute_id for p in spans}!={client.compute_id,remote.compute_id}: raise ValueError("placement must use both explicit compute units")
    for participant in plan.participants:
        assigned={p.unit_id for p in spans if p.compute_id==participant.compute_id}
        if not assigned.issubset({r.unit_id for r in participant.cache_ranges}): raise ValueError("cache descriptors must bind assigned units")
    args=("--rpc",remote.rpc_endpoint,"--device",f"{client.device},{remote.device}","--split-mode",opt.split_mode,"--tensor-split",",".join(format(x,".15g") for x in opt.tensor_split),"-ngl",str(opt.offload_tail),"-cmoe" if opt.cpu_experts else "-no-cmoe","-c",str(opt.context),"-np",str(opt.slots),"--no-warmup","-lv",str(opt.verbosity),"--seed",str(dict(plan.request)["seed"]))
    return LaunchSpec(client.runtime_executable,client.runtime_sha256,client.execution_address,remote.rpc_endpoint,f"{client.device},{remote.device}",args,tuple(expected),opt.context,opt.slots,opt.startup_timeout_seconds)

__all__=["ExpectedPlacement","LaunchSpec","llama_cpp_spec"]

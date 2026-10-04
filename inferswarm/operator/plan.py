"""Immutable operator-authorized execution plan and stable digest."""
from __future__ import annotations
import hashlib, json
from dataclasses import dataclass
from .config import BackendOptions, ModelIdentity, Participant, Placement

@dataclass(frozen=True)
class OperatorPlan:
    plan_id: str
    digest: str
    model: ModelIdentity
    participants: tuple[Participant, ...]
    strategy_id: str
    placement: tuple[Placement, ...]
    backend_options: BackendOptions
    request: tuple[tuple[str, object], ...]

def build_plan(config) -> OperatorPlan:
    payload={"plan_id":config.plan_id,"model":config.model,"participants":tuple(sorted(config.participants,key=lambda p:p.role)),"strategy_id":config.strategy_id,"placement":config.placement,"backend_options":config.backend_options,"request":config.request}
    def normalize(value):
        if hasattr(value,"__dataclass_fields__"): return {k:normalize(v) for k,v in value.__dict__.items()}
        if isinstance(value,tuple): return [normalize(v) for v in value]
        if isinstance(value,dict): return {k:normalize(v) for k,v in value.items()}
        return value
    canonical=json.dumps(normalize(payload),sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False)
    digest=hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return OperatorPlan(config.plan_id,digest,config.model,config.participants,config.strategy_id,config.placement,config.backend_options,config.request)

__all__=["OperatorPlan","build_plan"]

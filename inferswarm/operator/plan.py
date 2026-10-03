"""Explicit immutable operator plan and canonical digest."""
from __future__ import annotations
import hashlib, json
from dataclasses import dataclass
from .config import OperatorConfig, Participant, Placement

@dataclass(frozen=True)
class OperatorPlan:
    plan_id: str
    digest: str
    model: object
    participants: tuple[Participant, ...]
    strategy_id: str
    placement: tuple[Placement, ...]
    request: tuple[tuple[str, object], ...]

def build_plan(config: OperatorConfig) -> OperatorPlan:
    payload={"plan_id":config.plan_id,"model":{"source_id":config.model.source_id,"revision":config.model.revision,"representation":config.model.representation,"members":config.model.members},"participants":[p.__dict__ for p in config.participants],"strategy_id":config.strategy_id,"placement":[{"unit_id":p.unit_id,"compute_id":p.compute_id,"native_args":p.native_args} for p in config.placement],"request":config.request}
    canonical=json.dumps(payload,sort_keys=True,separators=(",",":"),ensure_ascii=False)
    digest=hashlib.sha256(canonical.encode()).hexdigest()
    return OperatorPlan(config.plan_id,digest,config.model,config.participants,config.strategy_id,config.placement,config.request)

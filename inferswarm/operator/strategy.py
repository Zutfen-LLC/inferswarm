"""Pure llama.cpp strategy binding; never starts a process."""
from dataclasses import dataclass
from .plan import OperatorPlan

@dataclass(frozen=True)
class LaunchSpec:
    executable: str
    executable_sha256: str
    endpoint: str
    device: str
    placement_args: tuple[str, ...]
    expected_placement: tuple

def llama_cpp_spec(plan: OperatorPlan) -> LaunchSpec:
    if plan.strategy_id != "llama.cpp": raise ValueError("plan selects a different strategy")
    if len(plan.participants) != 2: raise ValueError("llama.cpp adapter supports exactly two explicit participants")
    if len({p.compute_id for p in plan.placement}) != 2: raise ValueError("placement must explicitly use both compute units")
    remote=next((p for p in plan.participants if p.transport.lower()=="rpc"),None)
    local=next((p for p in plan.participants if p is not remote),None)
    if remote is None or local is None: raise ValueError("explicit local and RPC participants required")
    return LaunchSpec(local.runtime_executable,local.runtime_sha256,remote.address, f"{local.device},{remote.device}", tuple(a for unit in plan.placement for a in unit.native_args),plan.placement)

__all__=["LaunchSpec","llama_cpp_spec"]

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

def _build_legacy_plan(config) -> OperatorPlan:
    payload={"plan_id":config.plan_id,"model":config.model,"participants":tuple(sorted(config.participants,key=lambda p:p.role)),"strategy_id":config.strategy_id,"placement":config.placement,"backend_options":config.backend_options,"request":config.request}
    def normalize(value):
        if hasattr(value,"__dataclass_fields__"): return {k:normalize(v) for k,v in value.__dict__.items()}
        if isinstance(value,tuple): return [normalize(v) for v in value]
        if isinstance(value,dict): return {k:normalize(v) for k,v in value.items()}
        return value
    canonical=json.dumps(normalize(payload),sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False)
    digest=hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return OperatorPlan(config.plan_id,digest,config.model,config.participants,config.strategy_id,config.placement,config.backend_options,config.request)

# New /3 contracts are deliberately separate from the accepted /2 digest.
from dataclasses import asdict, replace
from .config import ProfiledOperatorConfig, validate_config_profiles
from .profiles import ProfileSubject, validate_profiles, sha256, integer, text

PHASES = ('verification', 'load', 'serve', 'cleanup')


@dataclass(frozen=True)
class ResourceCharge:
    allocation_id: str
    memory_id: str
    role: str
    bytes: int | None
    phase: str
    evidence_id: str
    shared_allocation_id: str | None = None

    def __post_init__(self):
        for key in ('allocation_id','memory_id','evidence_id'):
            text(getattr(self,key),'charge '+key)
        if self.bytes is not None: integer(self.bytes,'charge bytes')
        if self.role not in ('required','optional','transient','backing','virtual','reserve'):
            raise ValueError('invalid charge role')
        if self.phase not in PHASES: raise ValueError('invalid charge phase')
        if self.shared_allocation_id is not None: text(self.shared_allocation_id,'shared allocation identity')


@dataclass(frozen=True)
class CapabilityRequirement:
    runtime_id: str
    capability: str
    reason: str


@dataclass(frozen=True)
class LegalCandidate:
    candidate_id: str
    assignments: tuple
    required_state: tuple
    boundaries: tuple
    charges: tuple[ResourceCharge, ...]
    capability_requirements: tuple[CapabilityRequirement, ...]
    source_contract: tuple
    subject: ProfileSubject
    required_charge_ids: tuple[str, ...] = ()
    calculated_evidence: tuple[str, ...] = ()
    unsupported: tuple[str, ...] = ()
    semantic_contract: tuple = ()
    canonical_strategy_options: object = None

    def __post_init__(self):
        text(self.candidate_id,'candidate identity')
        for name in ('assignments','required_state','boundaries','charges','capability_requirements',
                     'source_contract','required_charge_ids','calculated_evidence','unsupported','semantic_contract'):
            value=getattr(self,name)
            if not isinstance(value,tuple) or not _immutable(value):
                raise ValueError('immutable candidate payload required: '+name)
        if not _immutable(self.canonical_strategy_options):
            raise ValueError('immutable candidate canonical options required')
        if not isinstance(self.subject,ProfileSubject) or not _immutable(self.subject):
            raise ValueError('immutable candidate subject required')
        if not all(isinstance(c,ResourceCharge) for c in self.charges):
            raise ValueError('typed candidate charges required')
        if not all(isinstance(r,CapabilityRequirement) for r in self.capability_requirements):
            raise ValueError('typed capability requirements required')


def _immutable(value):
    if value is None or type(value) in (str,int,bool): return True
    if type(value) is float:
        import math
        return math.isfinite(value)
    if isinstance(value,tuple): return all(_immutable(v) for v in value)
    if hasattr(value,'__dataclass_fields__'):
        return value.__dataclass_params__.frozen and all(_immutable(v) for v in vars(value).values())
    return False


@dataclass(frozen=True)
class BudgetPeak:
    memory_id: str
    physical_id: str
    phase_bytes: tuple
    peak_bytes: int
    existing_load_bytes: int
    virtual_bytes: int
    reserve_bytes: int
    unknown_allocations: tuple[str, ...]
    bounded_peak_bytes: int | None = None
    role_phase_bytes: tuple = ()


@dataclass(frozen=True)
class Admission:
    status: str
    structural_admissible: bool
    technical_feasibility: str
    policy_eligible: bool
    execution_ready: bool
    deficits: tuple[str, ...]
    peaks: tuple[BudgetPeak, ...]
    evidence_classes: tuple


def admit_candidate(candidate, snapshot, policy, *, now):
    """Opaque physical-domain accounting; known totals are lower bounds if UNKNOWN.

    All charges in one phase are simultaneous. Disjoint phases do not overlap.
    Existing load is reported separately and current availability constrains new
    allocations. A replay ADMITTED receipt is illustrative, never execution-ready.
    """
    reasons = list(validate_profiles(snapshot, now=now, policy=policy, subject=candidate.subject))
    reasons.extend(candidate.unsupported)
    memories = {r.memory_id:r for r in snapshot.memory_resources}
    limits = {r.memory_id:r for r in policy.memory_limits}
    if len(limits)!=len(policy.memory_limits) or set(limits)!=set(memories):
        raise ValueError('memory policy coverage mismatch')
    for limit in limits.values():
        integer(limit.peak_bytes,'policy peak bytes',minimum=1)
        integer(limit.reserve_bytes,'policy reserve bytes')
        integer(limit.min_available_bytes,'policy minimum available bytes')
    runtimes = {r.runtime_id:r for r in snapshot.runtime_capabilities}
    evidence = {e.evidence_id:e for e in snapshot.evidence}
    for req in candidate.capability_requirements:
        runtime = runtimes.get(req.runtime_id)
        if runtime is None or req.capability not in runtime.capabilities:
            reasons.append('UNKNOWN capability: '+req.reason)
        elif evidence[runtime.evidence_id].evidence_class != 'measured':
            reasons.append('UNKNOWN capability evidence: '+req.reason)
    structural = True
    ids = [c.allocation_id for c in candidate.charges]
    if len(ids)!=len(set(ids)):
        structural = False
        reasons.append('duplicate allocation identity')
    for missing in set(candidate.required_charge_ids)-set(ids):
        structural = False
        reasons.append('missing required allocation: '+missing)
    aliases = {}
    counted = []
    for charge in candidate.charges:
        if charge.memory_id not in memories:
            structural = False
            reasons.append('missing charge memory domain: '+charge.allocation_id)
        if charge.bytes is None:
            reasons.append('UNKNOWN allocation: '+charge.allocation_id)
        elif charge.evidence_id not in candidate.calculated_evidence and charge.evidence_id not in evidence:
            reasons.append('missing charge evidence: '+charge.allocation_id)
        if charge.shared_allocation_id is not None:
            signature=(charge.memory_id,charge.bytes,charge.phase,charge.role,charge.evidence_id)
            previous=aliases.get(charge.shared_allocation_id)
            if previous is not None:
                if previous!=signature:
                    structural = False
                    reasons.append('inconsistent shared alias: '+charge.shared_allocation_id)
                else:
                    continue
            else:
                aliases[charge.shared_allocation_id]=signature
        counted.append(charge)
    peaks=[]; policy_reasons=[]; capacity_reasons=[]
    for memory in snapshot.memory_resources:
        charges=[c for c in counted if c.memory_id==memory.memory_id]
        phases=tuple((phase,sum(c.bytes for c in charges if c.phase==phase and c.role not in ('virtual','reserve') and c.bytes is not None)) for phase in PHASES)
        peak=max(v for _,v in phases)
        limit=limits[memory.memory_id]
        unknown=tuple(sorted(c.allocation_id for c in charges if c.bytes is None))
        # Explicit reserve charges can add to (never silently replace) policy.
        reserves=tuple(limit.reserve_bytes+sum(c.bytes for c in charges if c.role=='reserve' and c.phase==phase and c.bytes is not None) for phase in PHASES)
        reserve=max(reserves)
        if peak>limit.peak_bytes: policy_reasons.append('policy peak: '+memory.memory_id)
        if memory.available_bytes<limit.min_available_bytes:
            policy_reasons.append('insufficient MemAvailable: '+memory.memory_id)
        if any(memory.available_bytes-value<headroom for (_,value),headroom in zip(phases,reserves)):
            policy_reasons.append('projected available reserve: '+memory.memory_id)
        if any(value+headroom>memory.total_bytes for (_,value),headroom in zip(phases,reserves)):
            capacity_reasons.append('physical capacity deficit: '+memory.memory_id)
        peaks.append(BudgetPeak(memory.memory_id,memory.physical_id,phases,peak,
            memory.total_bytes-memory.available_bytes,
            max(sum(c.bytes for c in charges if c.role=='virtual' and c.phase==phase and c.bytes is not None) for phase in PHASES),
            reserve,unknown,None if unknown else peak,
            tuple((phase,role,sum(c.bytes for c in charges if c.phase==phase and c.role==role and c.bytes is not None))
                  for phase in PHASES for role in ('required','optional','transient','backing','reserve','virtual'))))
    unknown_reasons = tuple(reasons)
    reasons.extend(policy_reasons+capacity_reasons)
    feasibility='INFEASIBLE' if candidate.unsupported or capacity_reasons else 'UNKNOWN' if unknown_reasons else 'FEASIBLE'
    return Admission('BLOCKED' if reasons else 'ADMITTED',structural,feasibility,
        not policy_reasons,not reasons and candidate.subject.mode=='live',tuple(sorted(set(reasons))),tuple(peaks),
        tuple(sorted((e.evidence_id,e.evidence_class,e.source_scope) for e in snapshot.evidence)))


@dataclass(frozen=True)
class ProfiledOperatorPlan:
    plan_id: str
    digest: str
    model: ModelIdentity
    participants: tuple
    strategy_id: str
    placement: tuple
    request: tuple
    selection: str
    metadata: object
    profiles: object
    policy: object
    workload: object
    strategy_options: tuple
    candidate: LegalCandidate
    admission: Admission
    config: ProfiledOperatorConfig


def build_plan(config, *, now=None):
    if not isinstance(config, ProfiledOperatorConfig):
        return _build_legacy_plan(config)
    from .metadata import load_metadata_index
    from .strategy import candidates_for
    metadata = load_metadata_index(config.metadata.path, expected_sha256=config.metadata.sha256)
    candidate, = candidates_for(config, metadata)
    admission = admit_candidate(candidate,config.profiles.snapshot,config.policy,now=now)
    extra = validate_config_profiles(config,now=now,profile_mode=config.profile_mode)
    if extra:
        admission = replace(admission,status='BLOCKED',execution_ready=False,
                            deficits=tuple(sorted(set(admission.deficits+extra))))
    # Clock and time-dependent verdict are not reproducible plan inputs.
    digest = _profiled_digest(config,candidate)
    return ProfiledOperatorPlan(config.plan_id,digest,config.model,config.participants,config.strategy_id,
        config.placement,config.request,config.selection,config.metadata,config.profiles,config.policy,
        config.workload,config.strategy_options,candidate,admission,config)


def _profiled_digest(config,candidate):
    # Re-derive through the opaque strategy seam; a retained candidate cannot
    # supply canonical options for a different current config. Normalization
    # (including unordered inventories and object/array shape) stays strategy-owned.
    from .metadata import load_metadata_index
    from .strategy import candidates_for
    metadata=load_metadata_index(config.metadata.path,expected_sha256=config.metadata.sha256)
    current,=candidates_for(config,metadata)
    if current.canonical_strategy_options!=candidate.canonical_strategy_options:
        raise ValueError('plan strategy options integrity mismatch')
    payload=asdict(config)
    payload['metadata'].pop('path')
    if current.canonical_strategy_options is not None:
        payload['strategy_options']=current.canonical_strategy_options
    payload['candidate']=asdict(candidate)
    return sha256(payload)


def revalidate_admission(plan, *, now=None):
    integrity=[]
    try:
        if plan.digest!=_profiled_digest(plan.config,plan.candidate):
            integrity.append('plan digest integrity mismatch')
    except ValueError:
        integrity.append('plan strategy options integrity mismatch')
    fields=('plan_id','model','participants','strategy_id','placement','request','selection',
            'metadata','profiles','policy','workload','strategy_options')
    if any(getattr(plan,name)!=getattr(plan.config,name) for name in fields):
        integrity.append('plan field integrity mismatch')
    mode = 'live' if now is None else plan.config.profile_mode
    candidate = replace(plan.candidate, subject=replace(plan.candidate.subject,mode=mode))
    receipt = admit_candidate(candidate,plan.profiles.snapshot,plan.policy,now=now)
    extra = tuple(integrity)+validate_config_profiles(plan.config,now=now,profile_mode=mode)
    if extra:
        receipt = replace(receipt,status='BLOCKED',execution_ready=False,
                          deficits=tuple(sorted(set(receipt.deficits+extra))))
    return receipt


__all__=['OperatorPlan','ProfiledOperatorPlan','ResourceCharge','LegalCandidate','CapabilityRequirement',
         'BudgetPeak','Admission','build_plan','admit_candidate','revalidate_admission']

"""Internal /2 native identity and bounded stream parsing, not admission.

Parsing authenticates a self-consistent description, not actual files, physical
facts or execution. Both reconciliation entry points deliberately fail closed
until the complete static/dynamic predicates are implemented in later slices.
The historical bindings.py /1 path is unaffected.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
import hashlib
import json
import math
import re
from typing import Any, Mapping, NoReturn

from .bindings import TransportReply
from .profiles import FrozenMapping, canonical, freeze, integer, keys, thaw
from .config import ProfiledOperatorConfig
from .metadata import MetadataIndex
from .plan import ProfiledOperatorPlan, _profiled_digest_from_metadata
from .qwen_q8 import Q8StaticInventory, q8_static_inventory


# Closed private guards for the current Q8 records, not a public validator.
from . import config as _config, profiles as _profiles, plan as _plan, qwen_q8 as _q8
from .source import TensorRecord as _TensorRecord


def _static_bad(path) -> NoReturn:
    raise ValueError('static context typed input: ' + path)


def _static_scalar(value, kind, path, *, nullable=False):
    if nullable and value is None:
        return
    if kind == 'number':
        if type(value) not in (int, float) or not math.isfinite(value):
            _static_bad(path)
    elif kind == 'digest':
        if type(value) is not str or re.fullmatch(r'[0-9a-f]{64}', value) is None:
            _static_bad(path)
    elif type(value) is not kind:
        _static_bad(path)


def _static_tuple(value, path, *, length=None):
    if type(value) is not tuple or (length is not None and len(value) != length):
        _static_bad(path)


def _static_rows(value, kind, path):
    _static_tuple(value, path)
    for i, child in enumerate(value):
        child_path = path + '[' + str(i) + ']'
        if kind in (str, int, bool):
            _static_scalar(child, kind, child_path)
        else:
            _static_record(child, kind, child_path)


def _static_pairs(value, path, kinds):
    _static_tuple(value, path)
    seen = set()
    for i, row in enumerate(value):
        row_path = path + '[' + str(i) + ']'
        _static_tuple(row, row_path, length=len(kinds))
        for j, (child, kind) in enumerate(zip(row, kinds)):
            child_path = row_path + '[' + str(j) + ']'
            if kind == 'json':
                _static_json(child, child_path)
            elif kind in (str, int, bool, 'digest', 'number'):
                _static_scalar(child, kind, child_path)
            else:
                _static_record(child, kind, child_path)
        if row[0] in seen:
            _static_bad(row_path + '[0]')
        seen.add(row[0])


def _static_json(value, path):
    """Only tagged objects/plain arrays and exact immutable JSON scalars."""
    if type(value) is FrozenMapping:
        seen = set()
        for i, row in enumerate(value):
            row_path = path + '[' + str(i) + ']'
            _static_tuple(row, row_path, length=2)
            _static_scalar(row[0], str, row_path + '[0]')
            if row[0] in seen:
                _static_bad(row_path + '[0]')
            seen.add(row[0])
            _static_json(row[1], row_path + '[1]')
    elif type(value) is tuple:
        for i, child in enumerate(value):
            _static_json(child, path + '[' + str(i) + ']')
    elif value is None or type(value) in (str, int, bool):
        return
    elif type(value) is float and math.isfinite(value):
        return
    else:
        _static_bad(path)


def _static_object(value, path):
    if type(value) is not FrozenMapping:
        _static_bad(path)
    _static_json(value, path)


def _static_cache(value, path):
    _static_object(value, path)
    for i, (name, child) in enumerate(value):
        child_path = path + '[' + str(i) + '][1]'
        if name in ('recurrent_rows', 'rs_sequences', 'cache_streams', 'attention_cells'):
            _static_scalar(child, int, child_path)
        elif name in ('text_only', 'kv_offload'):
            _static_scalar(child, bool, child_path)
        elif name in ('k', 'v'):
            _static_scalar(child, str, child_path)


def _static_options(value, path):
    _static_object(value, path)
    for i, (name, child) in enumerate(value):
        child_path = path + '[' + str(i) + '][1]'
        if name == 'bindings':
            _static_object(child, child_path)
            for j, (_, binding) in enumerate(child):
                _static_scalar(binding, str, child_path + '[' + str(j) + '][1]')
        elif name in ('route', 'source_contract', 'rpc_cache'):
            _static_scalar(child, str, child_path)
        elif name == 'startup_timeout_seconds':
            _static_scalar(child, int, child_path)
        elif name == 'observer':
            _static_object(child, child_path)
            for j, (key, leaf) in enumerate(child):
                if key in ('client_manifest_path', 'client_executable_path',
                           'remote_manifest_path', 'remote_executable_path'):
                    _static_scalar(leaf, str, child_path + '[' + str(j) + '][1]')
        elif name in ('bounds', 'host_mirrors'):
            _static_tuple(child, child_path)
            for j, row in enumerate(child):
                row_path = child_path + '[' + str(j) + ']'
                _static_object(row, row_path)
                for k, (key, leaf) in enumerate(row):
                    if key in ('bytes', 'allocation_id', 'memory_id', 'evidence_id'):
                        _static_scalar(leaf, int if key == 'bytes' else str,
                                       row_path + '[' + str(k) + '][1]')


def _static_request(value, path):
    _static_pairs(value, path, (str, 'json'))
    if {name for name, _ in value} != {'prompt', 'max_tokens', 'temperature', 'seed'}:
        _static_bad(path)
    for i, (name, child) in enumerate(value):
        _static_scalar(child, str if name == 'prompt' else 'number' if name == 'temperature' else int,
                       path + '[' + str(i) + '][1]')


def _static_record(value, expected, path):
    """Closed declaration-order walk; a new/unsupported field never passes."""
    if type(value) is not expected:
        _static_bad(path)
    for field in fields(expected):
        name = field.name
        child = getattr(value, name)
        child_path = path + '.' + name
        _static_field(expected, name, child, child_path)


def _static_profile_payload(value, path):
    _static_object(value, path)
    names = {name for name, _ in value}
    if 'runtime_id' in names:
        owner = _profiles.RuntimeCapability
    elif 'compute_id' in names:
        owner = _profiles.ComputeProfile
    elif 'memory_id' in names:
        owner = _profiles.MemoryProfile
    elif 'link_id' in names:
        owner = _profiles.LinkProfile
    elif 'host_id' in names:
        owner = _profiles.HostProfile
    else:
        _static_bad(path)
    if names != {field.name for field in fields(owner)} - {'evidence_id'}:
        _static_bad(path)
    for i, (name, child) in enumerate(value):
        _static_field(owner, name, child, path + '[' + str(i) + '][1]')


def _static_field(owner, name, value, path):
    # Explicit current records only. Opaque JSON is allowed only in named slots.
    if owner in (ProfiledOperatorConfig, ProfiledOperatorPlan):
        if name in ('plan_id', 'strategy_id', 'selection', 'profile_mode'):
            return _static_scalar(value, str, path)
        if name == 'digest':
            return _static_scalar(value, 'digest', path)
        if name == 'model':
            return _static_record(value, _config.ModelIdentity, path)
        if name == 'participants':
            return _static_rows(value, _config.ProfiledParticipant, path)
        if name == 'placement':
            return _static_rows(value, _config.BindingPlacement, path)
        if name == 'metadata':
            return _static_record(value, _config.MetadataIdentity, path)
        if name == 'profiles':
            return _static_record(value, _config.ProfileIdentity, path)
        if name == 'policy':
            return _static_record(value, _config.ProfilePolicy, path)
        if name == 'workload':
            return _static_record(value, _config.WorkloadSettings, path)
        if name == 'strategy_options':
            return _static_options(value, path)
        if name == 'request':
            return _static_request(value, path)
        if owner is ProfiledOperatorPlan:
            if name == 'candidate':
                return _static_record(value, _plan.LegalCandidate, path)
            if name == 'admission':
                return _static_record(value, _plan.Admission, path)
            if name == 'config':
                return _static_record(value, ProfiledOperatorConfig, path)
    elif owner is _config.ModelIdentity:
        if name in ('source_id', 'revision', 'representation'):
            return _static_scalar(value, str, path)
        if name == 'members':
            return _static_pairs(value, path, (str, 'digest', int))
    elif owner is _config.PhysicalBinding:
        if name == 'evidence_sha256':
            return _static_scalar(value, 'digest', path)
        if name in ('binding_id', 'compute_id', 'memory_id', 'physical_id', 'native_selector',
                    'visible_selector', 'runtime_id', 'evidence_id'):
            return _static_scalar(value, str, path)
    elif owner in (_config.BackingDescriptor, _config.CacheRange):
        if name == 'sha256':
            return _static_scalar(value, 'digest', path)
        if name in ('size_bytes', 'offset', 'length'):
            return _static_scalar(value, int, path)
        if name in ('memory_id', 'member', 'state_id', 'cache_key', 'source_id', 'revision',
                    'representation', 'unit_id'):
            return _static_scalar(value, str, path)
    elif owner is _config.ProfiledParticipant:
        if name in ('participant_id', 'role', 'host_id', 'boot_epoch', 'topology_epoch', 'transport',
                    'execution_address', 'source_path', 'runtime_executable', 'cache_path',
                    'lifecycle_dir', 'source_id', 'source_revision', 'source_representation'):
            return _static_scalar(value, str, path)
        if name == 'rpc_endpoint':
            return _static_scalar(value, str, path, nullable=True)
        if name == 'runtime_sha256':
            return _static_scalar(value, 'digest', path)
        if name == 'port':
            return _static_scalar(value, int, path)
        if name == 'bindings':
            return _static_rows(value, _config.PhysicalBinding, path)
        if name == 'backing':
            return _static_rows(value, _config.BackingDescriptor, path)
        if name == 'cache_ranges':
            return _static_rows(value, _config.CacheRange, path)
    elif owner is _config.BindingPlacement:
        if name in ('unit_id', 'binding_id'):
            return _static_scalar(value, str, path)
        if name == 'state_ids':
            return _static_rows(value, str, path)
        if name == 'state_ranges':
            return _static_pairs(value, path, (str, str, int, int))
    elif owner is _config.MetadataIdentity:
        if name == 'path':
            return _static_scalar(value, str, path)
        if name in ('sha256', 'digest'):
            return _static_scalar(value, 'digest', path)
    elif owner is _config.ProfileIdentity:
        if name in ('sha256', 'digest'):
            return _static_scalar(value, 'digest', path, nullable=name == 'sha256')
        if name == 'snapshot':
            return _static_record(value, _profiles.ResourceSnapshot, path)
    elif owner is _config.MemoryLimit:
        if name == 'memory_id':
            return _static_scalar(value, str, path)
        if name in ('peak_bytes', 'min_available_bytes', 'reserve_bytes'):
            return _static_scalar(value, int, path)
    elif owner is _config.ProfilePolicy:
        if name == 'max_age_seconds':
            return _static_scalar(value, int, path)
        if name == 'allowed_evidence_classes':
            return _static_rows(value, str, path)
        if name == 'memory_limits':
            return _static_rows(value, _config.MemoryLimit, path)
    elif owner is _config.WorkloadSettings:
        if name in ('context', 'slots', 'batch', 'microbatch'):
            return _static_scalar(value, int, path)
        if name == 'cache_settings':
            return _static_cache(value, path)
    elif owner is _profiles.ResourceSnapshot:
        if name == 'digest':
            return _static_scalar(value, 'digest', path)
        if name == 'hosts':
            return _static_rows(value, _profiles.HostProfile, path)
        if name == 'compute_units':
            return _static_rows(value, _profiles.ComputeProfile, path)
        if name == 'memory_resources':
            return _static_rows(value, _profiles.MemoryProfile, path)
        if name == 'links':
            return _static_rows(value, _profiles.LinkProfile, path)
        if name == 'runtime_capabilities':
            return _static_rows(value, _profiles.RuntimeCapability, path)
        if name == 'evidence':
            return _static_rows(value, _profiles.EvidenceRef, path)
    elif owner in (_profiles.HostProfile, _profiles.ComputeProfile, _profiles.MemoryProfile,
                   _profiles.LinkProfile, _profiles.RuntimeCapability):
        if name in ('host_id', 'physical_id', 'boot_epoch', 'topology_epoch', 'evidence_id',
                    'compute_id', 'backend', 'memory_id', 'kind', 'link_id', 'source_host_id',
                    'target_host_id', 'path', 'protocol', 'runtime_id', 'source_revision',
                    'build_id', 'driver', 'route'):
            return _static_scalar(value, str, path)
        if name in ('memory_ids', 'capabilities'):
            return _static_rows(value, str, path)
        if name in ('total_bytes', 'available_bytes', 'throughput_bytes_per_second'):
            return _static_scalar(value, int, path)
        if name == 'latency_seconds':
            return _static_scalar(value, 'number', path)
        if name == 'binary_sha256':
            return _static_scalar(value, 'digest', path)
    elif owner is _profiles.EvidenceRef:
        if name in ('evidence_id', 'observed_at', 'expires_at', 'evidence_class', 'source_scope'):
            return _static_scalar(value, str, path)
        if name == 'sha256':
            return _static_scalar(value, 'digest', path)
        if name in ('provenance', 'dependencies'):
            return _static_pairs(value, path, (str, str))
        if name == 'payload':
            return _static_profile_payload(value, path)
    elif owner is _profiles.ProfileSubject:
        if name in ('host_ids', 'compute_ids', 'memory_ids', 'link_ids', 'runtime_ids'):
            return _static_rows(value, str, path)
        if name == 'dependencies':
            return _static_pairs(value, path, (str, str))
        if name == 'mode':
            return _static_scalar(value, str, path)
    elif owner is MetadataIndex:
        if name == 'source':
            return _static_record(value, _config.ModelIdentity, path)
        if name == 'metadata_digest':
            return _static_scalar(value, 'digest', path)
        if name == 'header_identities':
            return _static_pairs(value, path, (str, int, int, 'digest', int, 'digest'))
        if name == 'model_metadata':
            return _static_pairs(value, path, (str, 'json'))
        if name == 'tensors':
            return _static_rows(value, _TensorRecord, path)
    elif owner in (_TensorRecord, _q8.WeightAssignment):
        if name in ('state_id', 'member', 'binding_id', 'memory_id', 'authority'):
            return _static_scalar(value, str, path)
        if name in ('ggml_type', 'relative_offset', 'absolute_offset', 'encoded_bytes'):
            return _static_scalar(value, int, path)
        if name == 'shape':
            return _static_rows(value, int, path)
    elif owner is _q8.RequiredState:
        if name in ('state_id', 'binding_id', 'memory_id', 'representation', 'authority'):
            return _static_scalar(value, str, path)
        if name == 'lower_bound_bytes':
            return _static_scalar(value, int, path, nullable=True)
        if name == 'reconstructible':
            return _static_scalar(value, bool, path)
        if name == 'dependencies':
            return _static_rows(value, str, path)
    elif owner is _q8.Boundary:
        if name in ('semantic_id', 'producer_binding', 'consumer_binding', 'representation',
                    'alias_rule', 'ordering', 'source_citation'):
            return _static_scalar(value, str, path)
        if name in ('before_layer', 'logical_bytes', 'wire_bytes'):
            return _static_scalar(value, int, path, nullable=name == 'wire_bytes')
        if name in ('shape', 'strides'):
            return _static_rows(value, int, path)
        if name in ('dependencies', 'state_dependencies', 'route_hosts', 'link_legs'):
            return _static_rows(value, str, path)
    elif owner is _plan.ResourceCharge:
        if name in ('allocation_id', 'memory_id', 'role', 'phase', 'evidence_id'):
            return _static_scalar(value, str, path)
        if name == 'bytes':
            return _static_scalar(value, int, path, nullable=True)
        if name == 'shared_allocation_id':
            return _static_scalar(value, str, path, nullable=True)
    elif owner is _plan.CapabilityRequirement:
        if name in ('runtime_id', 'capability', 'reason'):
            return _static_scalar(value, str, path)
    elif owner is _q8.NativeQ8Options:
        if name in ('selection', 'split_mode', 'fit', 'lazy_mode', 'load_mode', 'flash_attention'):
            return _static_scalar(value, str, path)
        if name == 'gpu_layers':
            return _static_scalar(value, int, path)
        if name in ('kv_offload', 'op_offload', 'kv_unified'):
            return _static_scalar(value, bool, path)
    elif owner is _q8.Q8Contract:
        if name in ('selection', 'route'):
            return _static_scalar(value, str, path)
        if name == 'metadata_digest':
            return _static_scalar(value, 'digest', path)
        if name == 'bindings':
            return _static_pairs(value, path, (str, _config.PhysicalBinding))
        if name == 'workload':
            return _static_record(value, _config.WorkloadSettings, path)
        if name == 'header_identities':
            return _static_pairs(value, path, (str, int, int, 'digest', int, 'digest'))
        if name == 'model_metadata':
            return _static_pairs(value, path, (str, 'json'))
        if name == 'binding_hosts':
            return _static_pairs(value, path, (str, str))
        if name == 'links':
            return _static_rows(value, _profiles.LinkProfile, path)
    elif owner is _plan.LegalCandidate:
        if name == 'candidate_id':
            return _static_scalar(value, str, path)
        if name == 'assignments':
            return _static_rows(value, _q8.WeightAssignment, path)
        if name == 'required_state':
            return _static_rows(value, _q8.RequiredState, path)
        if name == 'boundaries':
            return _static_rows(value, _q8.Boundary, path)
        if name == 'charges':
            return _static_rows(value, _plan.ResourceCharge, path)
        if name == 'capability_requirements':
            return _static_rows(value, _plan.CapabilityRequirement, path)
        if name == 'source_contract':
            _static_tuple(value, path, length=6)
            for i in range(3):
                _static_scalar(value[i], str, path + '[' + str(i) + ']')
            _static_record(value[3], _config.ModelIdentity, path + '[3]')
            _static_pairs(value[4], path + '[4]', (str, int, int, 'digest', int, 'digest'))
            return _static_record(value[5], _q8.NativeQ8Options, path + '[5]')
        if name == 'subject':
            return _static_record(value, _profiles.ProfileSubject, path)
        if name in ('required_charge_ids', 'calculated_evidence', 'unsupported'):
            return _static_rows(value, str, path)
        if name == 'semantic_contract':
            return _static_rows(value, _q8.Q8Contract, path)
        if name == 'canonical_strategy_options':
            return _static_options(value, path)
    elif owner is _plan.Admission:
        if name in ('status', 'technical_feasibility'):
            return _static_scalar(value, str, path)
        if name in ('structural_admissible', 'policy_eligible', 'execution_ready'):
            return _static_scalar(value, bool, path)
        if name == 'deficits':
            return _static_rows(value, str, path)
        if name == 'peaks':
            return _static_rows(value, _plan.BudgetPeak, path)
        if name == 'evidence_classes':
            return _static_pairs(value, path, (str, str, str))
    elif owner is _plan.BudgetPeak:
        if name in ('memory_id', 'physical_id'):
            return _static_scalar(value, str, path)
        if name in ('peak_bytes', 'existing_load_bytes', 'virtual_bytes', 'reserve_bytes', 'bounded_peak_bytes'):
            return _static_scalar(value, int, path, nullable=name == 'bounded_peak_bytes')
        if name == 'unknown_allocations':
            return _static_rows(value, str, path)
        if name == 'phase_bytes':
            return _static_pairs(value, path, (str, int))
        if name == 'role_phase_bytes':
            # First-column phases repeat for distinct roles; validate rows without a key-uniqueness claim.
            _static_tuple(value, path)
            for i, row in enumerate(value):
                row_path = path + '[' + str(i) + ']'
                _static_tuple(row, row_path, length=3)
                for j, kind in enumerate((str, str, int)):
                    _static_scalar(row[j], kind, row_path + '[' + str(j) + ']')
            return
    elif owner is _q8.Q8StaticInventory:
        if name in ('base_revision', 'base_tree', 'selection', 'charge_semantics'):
            return _static_scalar(value, str, path)
        if name == 'metadata_source':
            return _static_record(value, _config.ModelIdentity, path)
        if name == 'metadata_digest':
            return _static_scalar(value, 'digest', path)
        if name == 'header_identities':
            return _static_pairs(value, path, (str, int, int, 'digest', int, 'digest'))
        if name == 'model_metadata':
            return _static_pairs(value, path, (str, 'json'))
        if name == 'weights':
            return _static_rows(value, _q8.WeightAssignment, path)
        if name == 'persistent_caches':
            return _static_rows(value, _q8.Q8PersistentCache, path)
        if name == 'logical_composites':
            return _static_rows(value, _q8.Q8LogicalComposite, path)
        if name == 'charges':
            return _static_rows(value, _plan.ResourceCharge, path)
        if name == 'capability_requirements':
            return _static_rows(value, _plan.CapabilityRequirement, path)
        if name == 'pending_dynamic':
            return _static_rows(value, str, path)
    elif owner in (_q8.Q8PersistentCache, _q8.Q8LogicalComposite):
        if name == 'state':
            return _static_record(value, _q8.RequiredState, path)
        if name in ('native_name', 'phase'):
            return _static_scalar(value, str, path)
        if name == 'ggml_type':
            return _static_scalar(value, int, path)
        if name == 'native_dimensions':
            _static_tuple(value, path, length=4)
            return _static_rows(value, int, path)
        if name == 'source_sites':
            return _static_rows(value, str, path)
    _static_bad(path)


def _static_context_snapshot(value, memo):
    """Detach already shape-checked nodes, retaining shared-node relationships."""
    if value is None or type(value) in (str, int, bool, float):
        return value
    identity = id(value)
    if identity in memo:
        return memo[identity]
    if type(value) in (tuple, FrozenMapping):
        result = type(value)(_static_context_snapshot(child, memo) for child in value)
    else:
        # Only the closed, previously validated dataclass records reach here.
        # Do not use deepcopy hooks or re-run constructors to coerce inputs.
        result = object.__new__(type(value))
        memo[identity] = result
        for field in fields(value):
            object.__setattr__(result, field.name,
                               _static_context_snapshot(getattr(value, field.name), memo))
    memo[identity] = result
    return result


@dataclass(frozen=True)
class StaticPlanContext:
    """Detached original-plan description; never admission or execution proof."""
    original_plan_digest: str
    config: ProfiledOperatorConfig
    inventory: Q8StaticInventory

    def __post_init__(self):
        _static_scalar(self.original_plan_digest, 'digest', 'original_plan_digest')
        _static_record(self.config, ProfiledOperatorConfig, 'config')
        _static_record(self.inventory, Q8StaticInventory, 'inventory')
        memo = {}
        object.__setattr__(self, 'config', _static_context_snapshot(self.config, memo))
        object.__setattr__(self, 'inventory', _static_context_snapshot(self.inventory, memo))


def derive_static_plan_context(plan: ProfiledOperatorPlan, metadata: MetadataIndex, *,
                               original_plan_digest: str) -> StaticPlanContext:
    """Pure expectations only; lifecycle, freshness and admission remain pending."""
    if type(plan) is not ProfiledOperatorPlan:
        _static_bad('plan')
    _static_scalar(original_plan_digest, 'digest', 'original_plan_digest')
    # Config wins over bad metadata or downstream strategy inputs. Validate all
    # mirrored/candidate/admission shapes before any profile serialization.
    _static_record(plan.config, ProfiledOperatorConfig, 'plan.config')
    _static_record(plan, ProfiledOperatorPlan, 'plan')
    _static_record(metadata, MetadataIndex, 'metadata')
    if plan.digest != original_plan_digest:
        raise ValueError('static context original plan digest')
    from .qwen_q8 import _inventory_exact_value
    from .profiles import parse_profiles, snapshot_mapping
    for name in ('plan_id', 'model', 'participants', 'strategy_id', 'placement', 'request',
                 'selection', 'metadata', 'profiles', 'policy', 'workload', 'strategy_options'):
        if not _inventory_exact_value(getattr(plan, name), getattr(plan.config, name)):
            raise ValueError('static context plan field mismatch: ' + name)
    snapshot = plan.config.profiles.snapshot
    if (plan.config.profiles.digest != snapshot.digest or
            not _inventory_exact_value(parse_profiles(snapshot_mapping(snapshot)), snapshot)):
        raise ValueError('static context profile integrity mismatch')
    inventory = q8_static_inventory(plan.config, metadata, candidate=plan.candidate)
    if _profiled_digest_from_metadata(plan.config, plan.candidate, metadata) != original_plan_digest:
        raise ValueError('static context plan digest integrity mismatch')
    return StaticPlanContext(original_plan_digest, plan.config, inventory)

BUILD_SCHEMA = 'q8-owned-observation/2'
RECEIPT_SCHEMA = 'q8-observation-receipt/2'
NATIVE_STREAM_SCHEMA = 'inferswarm-native-observation/2'
BUILD_MANIFEST_SCHEMA = 'q8-native-build-manifest/2'
MAX_OBSERVATION_BYTES = 8 << 20
MAX_ROWS = 16384
MAX_NODES = 65536
MAX_DEPTH = 32
MAX_TEXT_BYTES = 65536
MAX_STREAM_SEQUENCE = 1 << 31
PINNED_BASE_REVISION = 'b29c606e28a01b1bc8c1351026a0fa6e616bf6c4'
PINNED_BASE_TREE = '950999fe62b7fe55f44ab5b7394e3c8542f37f12'
BUILD_COMPONENTS = ('base_revision', 'base_tree', 'patch_sha256',
                    'transformed_manifest_sha256', 'protocol', 'compiler',
                    'build_options', 'executable_sha256', 'backend_libraries')


def _text(value, where):
    if type(value) is not str or not value or value != value.strip() or '\x00' in value:
        raise ValueError(where + ' must be nonempty exact text')
    try:
        encoded = value.encode('utf-8')
    except UnicodeError as exc:
        raise ValueError(where + ' must be UTF-8 text') from exc
    if len(encoded) > 4096:
        raise ValueError(where + ' text exceeds limit')
    return value


def _digest(value, where, *, nonzero=False):
    if type(value) is not str or not re.fullmatch(r'[0-9a-f]{64}', value):
        raise ValueError(where + ' must be lowercase SHA-256')
    if nonzero and value == '0' * 64:
        raise ValueError(where + ' must be nonzero for derived observer build')
    return value


def _array(value, where, maximum, *, nonempty=False):
    if type(value) not in (tuple, list) or len(value) > maximum or (nonempty and not value):
        raise ValueError(where + ' must be bounded' + (' nonempty' if nonempty else '') + ' array')
    return value


def _build_body(identity):
    return {'schema': BUILD_MANIFEST_SCHEMA,
            **{name: getattr(identity, name) for name in BUILD_COMPONENTS if name != 'backend_libraries'},
            'backend_libraries': [{'name': n, 'sha256': d} for n, d in identity.backend_libraries]}


@dataclass(frozen=True)
class NativeBuildIdentity:
    base_revision: str
    base_tree: str
    patch_sha256: str
    transformed_manifest_sha256: str
    protocol: str
    compiler: str
    build_options: tuple[str, ...]
    executable_sha256: str
    backend_libraries: tuple[tuple[str, str], ...]
    manifest_sha256: str

    def __post_init__(self):
        for name in ('base_revision', 'base_tree'):
            value = _text(getattr(self, name), name)
            if not re.fullmatch(r'[0-9a-f]{40}', value):
                raise ValueError(name + ' must be exact lowercase git identity')
        if self.base_revision != PINNED_BASE_REVISION or self.base_tree != PINNED_BASE_TREE:
            raise ValueError('native source base identity mismatch')
        _text(self.protocol, 'native observation protocol')
        if self.protocol != NATIVE_STREAM_SCHEMA:
            raise ValueError('native observation protocol mismatch')
        for name in ('patch_sha256', 'transformed_manifest_sha256', 'executable_sha256'):
            _digest(getattr(self, name), name, nonzero=True)
        _text(self.compiler, 'compiler identity')
        options = tuple(_text(option, 'build option') for option in
                        _array(self.build_options, 'build options', 256, nonempty=True))
        libraries = []
        seen = set()
        for row in _array(self.backend_libraries, 'backend libraries', 128, nonempty=True):
            if type(row) not in (list, tuple) or len(row) != 2:
                raise ValueError('backend library must be exact name/digest pair')
            name = _text(row[0], 'backend library name')
            sha = _digest(row[1], 'backend library digest', nonzero=True)
            if name in seen:
                raise ValueError('duplicate backend library identity')
            seen.add(name)
            libraries.append((name, sha))
        object.__setattr__(self, 'build_options', options)
        object.__setattr__(self, 'backend_libraries', tuple(sorted(libraries)))
        _digest(self.manifest_sha256, 'native build manifest digest')
        if hashlib.sha256(canonical(_build_body(self))).hexdigest() != self.manifest_sha256:
            raise ValueError('native build manifest digest mismatch')

    @property
    def is_unmodified_base(self) -> bool:
        """A /2 derived observer can never describe an unmodified base."""
        return False

    def matches(self, other: 'NativeBuildIdentity') -> bool:
        return type(other) is NativeBuildIdentity and all(
            getattr(self, name) == getattr(other, name) for name in (*BUILD_COMPONENTS, 'manifest_sha256'))


def parse_build_manifest(mapping: Mapping) -> NativeBuildIdentity:
    """Pure description validation; collector must separately read actual bytes."""
    keys(mapping, ('schema', *BUILD_COMPONENTS), 'native build manifest')
    if type(mapping['schema']) is not str or mapping['schema'] != BUILD_MANIFEST_SCHEMA:
        raise ValueError('unsupported native build manifest schema')
    # Wire arrays/rows have exact JSON types; constructors also accept detached
    # list/tuple inputs and snapshot them after component validation.
    options = mapping['build_options']
    if type(options) is not list:
        raise ValueError('build options must be bounded nonempty array')
    libraries = mapping['backend_libraries']
    if type(libraries) is not list:
        raise ValueError('backend libraries must be bounded nonempty array')
    _array(options, 'build options', 256, nonempty=True)
    _array(libraries, 'backend libraries', 128, nonempty=True)
    pairs = []
    for row in libraries:
        keys(row, ('name', 'sha256'), 'backend library')
        pairs.append((_text(row['name'], 'backend library name'),
                      _digest(row['sha256'], 'backend library digest', nonzero=True)))
    body = {name: mapping[name] for name in ('schema', *BUILD_COMPONENTS)}
    body['backend_libraries'] = [{'name': n, 'sha256': d} for n, d in sorted(pairs)]
    # Validate primitives before canonicalization so bad inputs raise ValueError,
    # never a serializer TypeError (and never mutate the caller's manifest).
    for name in ('base_revision', 'base_tree', 'protocol', 'compiler'):
        _text(mapping[name], name)
    for name in ('patch_sha256', 'transformed_manifest_sha256', 'executable_sha256'):
        _digest(mapping[name], name, nonzero=True)
    for option in options:
        _text(option, 'build option')
    sha = hashlib.sha256(canonical(body)).hexdigest()
    return NativeBuildIdentity(
        base_revision=mapping['base_revision'], base_tree=mapping['base_tree'],
        patch_sha256=mapping['patch_sha256'],
        transformed_manifest_sha256=mapping['transformed_manifest_sha256'],
        protocol=mapping['protocol'], compiler=mapping['compiler'],
        build_options=tuple(options), executable_sha256=mapping['executable_sha256'],
        backend_libraries=tuple(pairs), manifest_sha256=sha)


def native_build_matches(actual: NativeBuildIdentity, expected: NativeBuildIdentity) -> bool:
    """Exact component match, not actual-file verification or an opaque build ID."""
    return type(actual) is NativeBuildIdentity and actual.matches(expected)


def require_native_build_match(actual: NativeBuildIdentity, expected: NativeBuildIdentity) -> None:
    """Refuse with the first differing exact component, not a generic build label."""
    if type(actual) is not NativeBuildIdentity or type(expected) is not NativeBuildIdentity:
        raise ValueError('typed native build identities required')
    for name in (*BUILD_COMPONENTS, 'manifest_sha256'):
        if getattr(actual, name) != getattr(expected, name):
            raise ValueError('native build ' + name + ' mismatch')


@dataclass(frozen=True)
class RequestIdentity:
    """Dispatch nonce first; native/server task/response/graph facts bind later.

    graph_generations records known generations, not exactly one graph for the
    request lifetime. This value neither fabricates native IDs nor proves them.
    """
    invocation_token: str
    request_nonce: str
    task_id: str | None = None
    response_id: str | None = None
    graph_generations: tuple[int, ...] = ()

    def __post_init__(self):
        for name in ('invocation_token', 'request_nonce'):
            _text(getattr(self, name), 'request ' + name)
        for name in ('task_id', 'response_id'):
            if getattr(self, name) is not None:
                _text(getattr(self, name), 'request ' + name)
        generations = tuple(integer(n, 'graph generation', maximum=MAX_STREAM_SEQUENCE) for n in
                            _array(self.graph_generations, 'graph generations', MAX_ROWS))
        if len(set(generations)) != len(generations):
            raise ValueError('duplicate graph generation')
        object.__setattr__(self, 'graph_generations', generations)


def _snapshot(value, depth=0, budget=None) -> Any:
    """Validate and defensively freeze JSON data, including direct constructors."""
    if budget is None:
        budget = [MAX_NODES]
    budget[0] -= 1
    if budget[0] < 0:
        raise ValueError('observation node limit exceeded')
    if depth > MAX_DEPTH:
        raise ValueError('observation nesting exceeds limit')
    if type(value) in (dict, FrozenMapping):
        pairs = value.items() if type(value) is dict else value
        if len(value) > MAX_ROWS:
            raise ValueError('observation object exceeds row limit')
        rows = []
        seen = set()
        for row in pairs:
            if type(row) is not tuple or len(row) != 2:
                raise ValueError('observation object requires exact key/value pairs')
            key, child = row
            _text(key, 'observation key')
            if key in seen:
                raise ValueError('duplicate observation key: ' + key)
            seen.add(key)
            rows.append((key, _snapshot(child, depth + 1, budget)))
        return FrozenMapping(sorted(rows))
    if type(value) in (list, tuple):
        if len(value) > MAX_ROWS:
            raise ValueError('observation array exceeds row limit')
        return tuple(_snapshot(child, depth + 1, budget) for child in value)
    if value is None or type(value) is bool:
        return value
    if type(value) is int:
        if not -(1 << 63) <= value <= (1 << 63) - 1:
            raise ValueError('observation integer outside bounds')
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError('nonfinite observation number')
        return value
    if type(value) is str:
        try:
            encoded = value.encode('utf-8')
        except UnicodeError as exc:
            raise ValueError('observation text must be UTF-8') from exc
        if len(encoded) > MAX_TEXT_BYTES or '\x00' in value:
            raise ValueError('observation text exceeds limit or contains NUL')
        return value
    raise ValueError('unsupported observation primitive')


def _bounded_observation_material(frozen):
    """Admit the complete canonical envelope before incrementally hashing it.

    Snapshot node/depth/primitive limits already bound this one detached JSON
    tree and each encoder chunk (at most one escaped string plus punctuation).
    iterencode's non-one-shot path never joins an aggregate output buffer.
    ASCII escaping makes chunk character counts exact canonical byte counts;
    aliases, keys, punctuation and terminal_digest are charged per occurrence.
    """
    material: Any = thaw(frozen)
    encoder = json.JSONEncoder(sort_keys=True, separators=(',', ':'),
                               ensure_ascii=True, allow_nan=False)
    size = 0
    for chunk in encoder.iterencode(material):
        size += len(chunk)
        if size > MAX_OBSERVATION_BYTES:
            raise ValueError('oversized observation payload')
    # Only this self-hash field is excluded. Material is strictly smaller than
    # the admitted complete envelope, so it needs no second aggregate buffer.
    del material['terminal_digest']
    digest = hashlib.sha256()
    for chunk in encoder.iterencode(material):
        digest.update(chunk.encode('ascii'))
    return material, digest.hexdigest()


@dataclass(frozen=True)
class ParsedObservation:
    schema: str
    phase: str
    participant_id: str
    plan_digest: str
    invocation_token: str
    stream_generation: str
    sequence: tuple[FrozenMapping, ...]
    terminal_digest: str
    terminal: bool
    facts: FrozenMapping
    stream_kind: str
    sequence_start: int
    terminal_sequence: int
    event_count: int
    snapshot_fence: bool
    dropped_events: int
    overflow: bool

    def __post_init__(self):
        raw = {field.name: getattr(self, field.name) for field in fields(self)}
        frozen = _snapshot(raw)
        if type(self.schema) is not str or self.schema != NATIVE_STREAM_SCHEMA:
            raise ValueError('unsupported native observation schema')
        if type(self.phase) is not str or self.phase not in ('static', 'dynamic'):
            raise ValueError('unsupported observation phase')
        for name in ('participant_id', 'invocation_token', 'stream_generation'):
            _text(getattr(self, name), 'observation ' + name)
        _digest(self.plan_digest, 'observation plan digest')
        _digest(self.terminal_digest, 'observation terminal digest')
        for name in ('terminal', 'snapshot_fence', 'overflow'):
            if type(getattr(self, name)) is not bool:
                raise ValueError('observation ' + name + ' must be boolean')
        for name in ('sequence_start', 'terminal_sequence', 'event_count', 'dropped_events'):
            integer(getattr(self, name), 'observation ' + name, maximum=MAX_STREAM_SEQUENCE)
        if type(self.stream_kind) is not str or self.stream_kind not in ('snapshot', 'whole', 'prefix'):
            raise ValueError('unsupported observation stream kind')
        _array(self.sequence, 'observation sequence', MAX_ROWS)
        if type(self.facts) not in (dict, FrozenMapping):
            raise ValueError('observation facts must be object')
        for row in self.sequence:
            if type(row) not in (dict, FrozenMapping):
                raise ValueError('observation sequence entry must be object')
            item: Any = thaw(row)
            keys(item, ('sequence', 'event'), 'observation sequence entry')
            integer(item['sequence'], 'observation sequence', maximum=MAX_STREAM_SEQUENCE)
            _text(item['event'], 'observation event')
        material, material_digest = _bounded_observation_material(frozen)
        if material_digest != self.terminal_digest:
            raise ValueError('observation terminal digest mismatch')
        # Digest first, then completeness semantics: unchanged digests on changed
        # counters/status/facts must be diagnosed as tampering, not another guard.
        if self.dropped_events != 0:
            raise ValueError('observation dropped events refuse completeness')
        if self.overflow:
            raise ValueError('observation overflow refuses completeness')
        if self.event_count != len(self.sequence):
            raise ValueError('declared event count does not match rows')
        if self.terminal_sequence - self.sequence_start != self.event_count:
            raise ValueError('declared sequence interval does not match rows')
        if self.stream_kind in ('whole', 'prefix') and self.sequence_start != 0:
            raise ValueError(self.stream_kind + ' stream must start at zero')
        for index, item in enumerate(material['sequence']):
            if item['sequence'] != self.sequence_start + index:
                raise ValueError('observation sequence must be contiguous declared interval')
        if self.stream_kind == 'snapshot':
            if self.phase != 'static':
                raise ValueError('snapshot stream must be static')
            if not self.snapshot_fence or not self.terminal:
                raise ValueError('static snapshot fence and terminal required')
            if self.sequence_start != 0 or self.terminal_sequence != 0 or self.sequence:
                raise ValueError('static snapshot must have empty zero interval')
        else:
            if self.snapshot_fence:
                raise ValueError('snapshot fence only allowed for static snapshot')
            if self.stream_kind == 'whole' and not self.terminal:
                raise ValueError('whole stream requires terminal fence')
            if self.stream_kind == 'prefix' and self.terminal:
                raise ValueError('prefix stream must be nonterminal')
            if self.phase == 'static' and not self.sequence:
                raise ValueError('empty static event list requires snapshot')
            if self.phase == 'dynamic' and self.stream_kind == 'whole' and not self.sequence:
                raise ValueError('dynamic whole stream requires native events')
        snapshot = dict(frozen)
        object.__setattr__(self, 'sequence', snapshot['sequence'])
        object.__setattr__(self, 'facts', snapshot['facts'])


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate observation key: ' + key)
        result[key] = value
    return result


def _finite_float(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError('nonfinite observation number')
    return result


def _no_constant(value):
    raise ValueError('nonfinite observation number: ' + value)


def parse_observation(reply: TransportReply) -> ParsedObservation:
    """Require successful raw transport before decoding; never accept execution."""
    if type(reply) is not TransportReply:
        raise ValueError('typed observer transport reply required')
    if type(reply.exit_code) is not int or reply.exit_code != 0:
        raise ValueError('observer transport exit ' + str(reply.exit_code))
    if type(reply.payload) is not bytes:
        raise ValueError('observer payload must be bytes')
    if len(reply.payload) > MAX_OBSERVATION_BYTES:
        raise ValueError('oversized observation payload')
    try:
        raw = json.loads(reply.payload.decode('utf-8'), object_pairs_hook=_pairs,
                         parse_constant=_no_constant, parse_float=_finite_float)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError('invalid observation JSON') from exc
    keys(raw, tuple(field.name for field in fields(ParsedObservation)), 'native observation stream')
    if type(raw['sequence']) is not list:
        raise ValueError('observation sequence must be bounded array')
    return ParsedObservation(**raw)


@dataclass(frozen=True)
class PhaseReceipt:
    """Structural receipt binding spawn facts; never execution authority."""
    schema: str
    phase: str
    verdict: str
    plan_digest: str
    selection: str
    invocation_token: str
    observation_digest: str
    observations_valid: bool
    physical_qualified: bool
    execution_authorized: bool
    request_identity: RequestIdentity | None = None
    counts: tuple[tuple[str, int], ...] = ()
    spawn_facts: tuple[tuple[str, int, str], ...] = ()


class IncompleteReconciliation(ValueError):
    """A named reconciliation predicate is unimplemented or unevidenced."""


@dataclass(frozen=True)
class OwnedSpawnFacts:
    """Controller-side spawn receipt facts; never observer-supplied."""
    participant_id: str
    pid: int
    start: str
    invocation_token: str

    def __post_init__(self):
        _text(self.participant_id, 'spawn participant')
        integer(self.pid, 'spawn pid', minimum=1)
        _text(self.start, 'spawn start')
        _text(self.invocation_token, 'spawn invocation token')


@dataclass(frozen=True)
class DerivedBuildEvidence:
    """Explicit derived-build qualification joins, independently collected.

    The manifest is an authenticated ``q8-native-build-manifest/2`` identity;
    ``executable_sha256`` is independently read from the actual executable
    bytes by the collector, never taken from the manifest alone.
    """
    manifest: NativeBuildIdentity
    executable_sha256: str

    def __post_init__(self):
        if type(self.manifest) is not NativeBuildIdentity:
            raise ValueError('derived build evidence: typed manifest required')
        _digest(self.executable_sha256, 'derived build executable digest')
        if self.executable_sha256 != self.manifest.executable_sha256:
            raise ValueError('derived build executable bytes mismatch')


@dataclass(frozen=True)
class ObservedHostFacts:
    """Independently observed host facts for one participant (#302 P1-C).

    Every field must come from a trusted observation source (remote /proc,
    owned-listener checks, observed process environment) — never from
    participant configuration. ``None`` marks a fact no in-scope observer
    can currently observe; reconciliation refuses on it and names the
    smallest missing observer capability instead of echoing configuration.
    """
    boot_epoch: str | None
    topology_epoch: str | None
    listening: tuple[str, ...]
    observer_environment: FrozenMapping
    source: str

    def __post_init__(self):
        for name in ('boot_epoch', 'topology_epoch'):
            value = getattr(self, name)
            if value is not None:
                _text(value, 'observed ' + name)
        if type(self.listening) is not tuple:
            raise ValueError('observed listeners must be a tuple')
        for endpoint in self.listening:
            _text(endpoint, 'observed listener')
        environment = thaw(self.observer_environment)
        if type(environment) is not dict:
            raise ValueError('observed environment must be an object')
        for key, value in environment.items():
            _text(key, 'observed environment key')
            if type(value) is not str:
                raise ValueError('observed environment value must be text')
        _text(self.source, 'observed host facts source')
        object.__setattr__(self, 'observer_environment', _snapshot(environment))


@dataclass(frozen=True)
class ObservedInventoryEvidence:
    """Observed pre-request inventory for one participant (#302 P1-B).

    Labeled observed facts joined against the CALCULATED inventory during
    static admission. ``source`` labels the evidence origin (for offline
    tests ``synthetic-contract``); calculated expectations never populate
    these fields. The retained #301 producer cannot yet emit this family
    before POST, so the production collector leaves it absent and static
    reconciliation fails closed naming the missing capability.
    """
    weights: tuple[FrozenMapping, ...] = ()
    persistent_states: tuple[FrozenMapping, ...] = ()
    logical_composites: tuple[FrozenMapping, ...] = ()
    extents: tuple[FrozenMapping, ...] = ()
    allocations: tuple[FrozenMapping, ...] = ()
    source: str = 'observed/unknown'

    def __post_init__(self):
        from .profiles import thaw as _thaw
        _text(self.source, 'observed inventory source')
        for name in ('weights', 'persistent_states', 'logical_composites',
                     'extents', 'allocations'):
            value = getattr(self, name)
            if type(value) is not tuple:
                raise ValueError('observed inventory ' + name + ' must be a tuple')
            for row in value:
                if type(row) not in (dict, FrozenMapping):
                    raise ValueError('observed inventory row must be an object')
            object.__setattr__(self, name, tuple(_snapshot(_thaw(row)) for row in value))


@dataclass(frozen=True)
class ParticipantStaticEvidence:
    """One participant's independently collected static admission evidence.

    The retained #301 overlay emits only terminal dynamic envelopes from its
    two production sites; there is no production static-snapshot producer, so
    static admission is built from independently collected process identity,
    verified source ranges and explicit derived-build qualification only.
    ``observed_inventory``/``observed_host_facts`` carry the #302 P1-B/P1-C
    observed families; absent observations refuse at reconciliation with the
    smallest missing observer capability named, never a configuration echo.
    """
    participant_id: str
    identity: Any
    spawn: OwnedSpawnFacts
    build: DerivedBuildEvidence
    source_receipt_digest: str
    observed_inventory: ObservedInventoryEvidence | None = None
    observed_host_facts: ObservedHostFacts | None = None
    capture: FrozenMapping | None = None

    def __post_init__(self):
        if self.capture is not None:
            if type(self.capture) not in (dict, FrozenMapping):
                raise ValueError('static capture must be an object')
            object.__setattr__(self, 'capture', _snapshot(thaw(self.capture)))


@dataclass(frozen=True)
class ParticipantDynamicEvidence:
    """One participant's collected same-request dynamic evidence.

    The native envelope's ``participant_id``/``invocation_token`` are
    producer-local labels (e.g. ``llama-server``); the controller binding is
    the invocation-owned export claim, whose pid/start must equal the owned
    spawn receipt facts, and whose claimed native label must equal the
    envelope's own participant label.
    """
    participant_id: str
    observation: ParsedObservation
    spawn: OwnedSpawnFacts
    claim_pid: int
    claim_start: str
    native_participant: str

    def __post_init__(self):
        _text(self.participant_id, 'dynamic evidence participant')
        if type(self.observation) is not ParsedObservation:
            raise ValueError('dynamic evidence: typed observation required')
        if self.observation.phase != 'dynamic':
            raise ValueError('dynamic evidence: dynamic phase required')
        if self.observation.stream_kind != 'whole' or not self.observation.terminal:
            raise ValueError('dynamic evidence: terminal whole stream required')
        if type(self.spawn) is not OwnedSpawnFacts:
            raise ValueError('dynamic evidence: typed spawn receipt required')
        if self.spawn.participant_id != self.participant_id:
            raise ValueError('dynamic evidence: spawn participant mismatch')
        _text(self.native_participant, 'dynamic evidence native participant')
        if self.native_participant != self.observation.participant_id:
            raise ValueError('dynamic evidence: envelope label does not match export claim')
        from .profiles import integer
        integer(self.claim_pid, 'dynamic evidence claim pid', minimum=1)
        _text(self.claim_start, 'dynamic evidence claim start')
        if self.claim_pid != self.spawn.pid or self.claim_start != self.spawn.start:
            raise ValueError('dynamic evidence: export claim does not match owned spawn')


_SOURCE_RECEIPT_FIELDS = ('schema', 'participant_id', 'status', 'plan_digest', 'metadata_digest',
    'source_identity', 'runtime_sha256', 'range_identities', 'physical_observation', 'cache_consumed')
_SOURCE_RANGE_FIELDS = ('state_id', 'member', 'offset', 'length', 'sha256', 'binding_id',
    'memory_id', 'authority', 'cache_eligible', 'cache_key')


def _same_json(actual, expected):
    from .profiles import canonical as _canonical, thaw as _thaw
    return _canonical(_thaw(actual)) == _canonical(_thaw(expected))


def _static_evidence_rows(plan, evidence):
    from .plan import ProfiledOperatorPlan as _Plan
    if type(plan) is not _Plan:
        raise ValueError('static reconciliation: typed profiled plan required')
    if plan.strategy_id != 'qwen38-q8-fixed/1':
        raise ValueError('static reconciliation: unsupported profiled strategy')
    if type(evidence) not in (tuple, list) or not evidence:
        raise ValueError('static reconciliation: typed participant evidence required')
    rows = []
    for row in evidence:
        if type(row) is not ParticipantStaticEvidence:
            raise ValueError('static reconciliation: typed participant evidence required')
        if type(row.spawn) is not OwnedSpawnFacts:
            raise ValueError('static reconciliation: owned spawn receipt required: '
                             + repr(row.participant_id))
        rows.append(row)
    ids = [row.participant_id for row in rows]
    participants = {p.participant_id: p for p in plan.participants}
    if set(ids) != set(participants) or len(ids) != len(set(ids)):
        raise ValueError('static reconciliation: participant coverage mismatch')
    tokens = {row.spawn.invocation_token for row in rows}
    if len(tokens) != 1:
        raise ValueError('static reconciliation: invocation token mismatch')
    return participants, rows, tokens.pop()


def _static_source_join(plan, participants, rows, source_receipts):
    from .profiles import sha256 as _sha256
    if type(source_receipts) is not dict:
        raise ValueError('static reconciliation: source receipt mapping required')
    if set(source_receipts) != set(participants):
        raise ValueError('static reconciliation: source receipt coverage mismatch')
    global_ranges = set()
    for row in rows:
        participant = participants[row.participant_id]
        receipt = source_receipts[row.participant_id]
        if not isinstance(receipt, dict) or any(field not in receipt for field in _SOURCE_RECEIPT_FIELDS):
            raise ValueError('static reconciliation: source receipt identity missing: ' + row.participant_id)
        checks = dict(schema='q8-source-receipt/1', participant_id=row.participant_id,
            status='VERIFIED-not-consumed', plan_digest=plan.digest, metadata_digest=plan.metadata.digest,
            source_identity={k: getattr(plan.model, k) for k in ('source_id', 'revision', 'representation')},
            runtime_sha256=participant.runtime_sha256, physical_observation=False, cache_consumed=False)
        for field, want in checks.items():
            if not _same_json(receipt[field], want):
                raise ValueError('static reconciliation: source receipt identity mismatch: ' + row.participant_id)
        if not _same_json(receipt.get('member_identities'), _plan_members_wire(plan)):
            raise ValueError('static reconciliation: source receipt member mismatch: ' + row.participant_id)
        if _sha256(receipt) != row.source_receipt_digest:
            raise ValueError('static reconciliation: source receipt digest mismatch: ' + row.participant_id)
        ids = {b.binding_id for b in participant.bindings}
        assignments = {a.state_id: a for a in plan.candidate.assignments if a.binding_id in ids}
        if not assignments:
            raise ValueError('static reconciliation: participant owns no weights: ' + row.participant_id)
        indexed = {}
        for r in receipt['range_identities']:
            if not isinstance(r, dict) or 'state_id' not in r:
                raise ValueError('static reconciliation: source range identity required: ' + row.participant_id)
            name = r['state_id']
            if name in indexed:
                raise ValueError('static reconciliation: duplicate source range: ' + name)
            indexed[name] = r
        if set(indexed) != set(assignments):
            raise ValueError('static reconciliation: source range coverage mismatch: ' + row.participant_id)
        for name, assignment in assignments.items():
            r = indexed[name]
            if any(field not in r for field in _SOURCE_RANGE_FIELDS):
                raise ValueError('static reconciliation: source range fields: ' + name)
            for field, want in dict(member=assignment.member, offset=assignment.absolute_offset,
                    length=assignment.encoded_bytes, binding_id=assignment.binding_id,
                    memory_id=assignment.memory_id, authority=assignment.authority).items():
                if not _same_json(r[field], want):
                    raise ValueError('static reconciliation: source range mismatch: ' + name)
            if type(r['cache_eligible']) is not bool:
                raise ValueError('static reconciliation: source cache flag: ' + name)
            if name in global_ranges:
                raise ValueError('static reconciliation: duplicate global source range: ' + name)
            global_ranges.add(name)
    if global_ranges != {a.state_id for a in plan.candidate.assignments}:
        raise ValueError('static reconciliation: complete weight coverage mismatch')


def _plan_members_wire(plan):
    from dataclasses import asdict as _asdict
    return [list(row) for row in _asdict(plan.model)['members']]


def _static_observed_joins(plan, participants, rows, metadata_inventory=None):
    """#302 P1-B/P1-C: observed evidence joins, fail-closed.

    The calculated inventory (q8_static_inventory) supplies EXPECTATIONS
    only; every admission predicate about observed resources consumes the
    independently collected ObservedInventoryEvidence/ObservedHostFacts on
    each row. Missing observations refuse with the smallest missing
    observer capability named; observed values must match the frozen plan.
    """
    from .profiles import thaw as _thaw
    from .qwen_q8 import q8_static_inventory
    if metadata_inventory is None:
        from .metadata import load_metadata_index
        from pathlib import Path as _Path
        metadata_inventory = load_metadata_index(
            _Path(plan.config.metadata.path), expected_sha256=plan.metadata.sha256)
    inventory = q8_static_inventory(plan.config, metadata_inventory,
                                    candidate=plan.candidate)
    expected_states = {c.state.state_id: c for c in inventory.persistent_caches}
    expected_composites = {c.state.state_id: c for c in inventory.logical_composites}
    expected_weights = {a.state_id: a for a in plan.candidate.assignments}
    for row in rows:
        participant = participants[row.participant_id]
        inv = row.observed_inventory
        if inv is None:
            raise ValueError(
                'static reconciliation: observed persistent-state inventory '
                'missing for ' + row.participant_id + '; smallest missing observer '
                'capability: a pre-POST static export of allocation/state extents '
                'in the #301 observation overlay (currently it exports '
                'allocations only in terminal dynamic envelopes)')
        if not isinstance(inv, ObservedInventoryEvidence):
            raise ValueError('static reconciliation: typed observed inventory '
                             'required: ' + row.participant_id)
        observed_states = {}
        for frozen_row in inv.persistent_states:
            record = _thaw(frozen_row)
            name = record.get('state_id')
            if not isinstance(name, str) or name in observed_states:
                raise ValueError('static reconciliation: observed state identity '
                                 'malformed: ' + row.participant_id)
            observed_states[name] = record
        ids = {b.binding_id for b in participant.bindings}
        owned_states = {name: expected_states[name] for name in expected_states
                        if expected_states[name].state.binding_id in ids}
        if set(observed_states) != set(owned_states):
            raise ValueError('static reconciliation: observed state coverage '
                             'mismatch (expected %d owned persistent-state expectations '
                             'for %s, observed %d)'
                             % (len(owned_states), row.participant_id, len(observed_states)))
        for name, expected in owned_states.items():
            record = observed_states[name]
            for field, want in dict(binding_id=expected.state.binding_id,
                    memory_id=expected.state.memory_id,
                    native_name=expected.native_name,
                    ggml_type=expected.ggml_type,
                    native_dimensions=list(expected.native_dimensions)).items():
                if record.get(field) != want:
                    raise ValueError('static reconciliation: observed state '
                                     + field + ' mismatch: ' + name)
            if record.get('observed_bytes') is None:
                raise ValueError('static reconciliation: observed state bytes '
                                 'UNKNOWN refuses admission: ' + name)
            if type(record.get('observed_bytes')) is not int \
                    or record['observed_bytes'] < expected.state.lower_bound_bytes:
                raise ValueError('static reconciliation: observed state bytes '
                                 'mismatch: ' + name)
        observed_composites = set()
        owned_composites = {name: c for name, c in expected_composites.items()
                            if c.state.binding_id in ids}
        for frozen_row in inv.logical_composites:
            record = _thaw(frozen_row)
            name = record.get('state_id')
            if name not in owned_composites or name in observed_composites:
                raise ValueError('static reconciliation: observed composite is not '
                                 'an expected logical composite: ' + repr(name))
            if record.get('observed') is not True:
                raise ValueError('static reconciliation: observed composite not '
                                 'confirmed observed: ' + name)
            expected = owned_composites[name].state
            if record.get('binding_id') != expected.binding_id or record.get('memory_id') != expected.memory_id:
                raise ValueError('static reconciliation: observed composite owner mismatch: ' + name)
            observed_composites.add(name)
        if observed_composites != set(owned_composites):
            raise ValueError('static reconciliation: observed composite coverage '
                             'mismatch: ' + row.participant_id)
        observed_extents = {}
        for frozen_row in inv.extents:
            record = _thaw(frozen_row)
            name = record.get('state_id')
            if not isinstance(name, str) or name in observed_extents:
                raise ValueError('static reconciliation: observed extent identity '
                                 'malformed or duplicated: ' + row.participant_id)
            observed_extents[name] = record
        for name, expected in owned_states.items():
            record = observed_extents.get(name)
            if record is None:
                raise ValueError('static reconciliation: observed extent missing: '
                                 + name)
            if record.get('layout_exact') is not True:
                raise ValueError('static reconciliation: observed extent mismatch: '
                                 + name)
        observed_allocations = {}
        for frozen_row in inv.allocations:
            record = _thaw(frozen_row)
            allocation = record.get('allocation_id')
            if not isinstance(allocation, str) or allocation in observed_allocations:
                raise ValueError('static reconciliation: observed allocation identity '
                                 'malformed or duplicated: ' + row.participant_id)
            observed_allocations[allocation] = record
        owned_memories = {m.memory_id for m in plan.profiles.snapshot.memory_resources
                          if m.host_id == participant.host_id}
        for charge in inventory.charges:
            if charge.memory_id not in owned_memories:
                continue
            if charge.bytes is None:
                raise ValueError('static reconciliation: observed allocation UNKNOWN: ' + charge.allocation_id)
            if charge.allocation_id not in observed_allocations:
                raise ValueError('static reconciliation: observed allocation '
                                 'missing: ' + charge.allocation_id)
            record = observed_allocations[charge.allocation_id]
            if type(record.get('observed_bytes')) is not int or record['observed_bytes'] < charge.bytes \
                    or record.get('memory_id') != charge.memory_id:
                raise ValueError('static reconciliation: observed allocation '
                                 'mismatch: ' + charge.allocation_id)
        host = row.observed_host_facts
        if host is None:
            raise ValueError('static reconciliation: observed host facts missing '
                             'for ' + row.participant_id + '; smallest missing '
                             'observer capability: independent remote host '
                             'boot/topology/listener observation at collection '
                             'time (currently only /proc process identity is read)')
        if not isinstance(host, ObservedHostFacts):
            raise ValueError('static reconciliation: typed observed host facts '
                             'required: ' + row.participant_id)
        if host.boot_epoch is None or host.boot_epoch != participant.boot_epoch:
            raise ValueError('static reconciliation: observed boot epoch mismatch '
                             'or UNKNOWN: ' + row.participant_id)
        if host.topology_epoch is None \
                or host.topology_epoch != participant.topology_epoch:
            raise ValueError('static reconciliation: observed topology epoch '
                             'mismatch or UNKNOWN: ' + row.participant_id)
        endpoint = participant.rpc_endpoint if participant.rpc_endpoint is not None \
            else '127.0.0.1:%d' % participant.port
        if endpoint not in host.listening:
            raise ValueError('static reconciliation: observed listener does not '
                             'cover the configured participant endpoint: '
                             + row.participant_id)
        environment = _thaw(host.observer_environment)
        if environment.get('IS301_OBSERVE') != '1' \
                or 'IS301_EXPORT_DIR' not in environment:
            raise ValueError('static reconciliation: observer environment not '
                             'observed on the owned process: ' + row.participant_id)
        owned_weights = {name: expected_weights[name] for name in expected_weights
                         if expected_weights[name].binding_id in ids}
        observed_weights = {}
        for frozen_row in inv.weights:
            record = _thaw(frozen_row)
            name = record.get('state_id')
            if not isinstance(name, str) or name in observed_weights:
                raise ValueError('static reconciliation: observed weight identity '
                                 'malformed or duplicated: ' + row.participant_id)
            observed_weights[name] = record
        if set(observed_weights) != set(owned_weights):
            raise ValueError('static reconciliation: observed weight coverage '
                             'mismatch (expected %d owned weights for %s, observed %d)'
                             % (len(owned_weights), row.participant_id,
                                len(observed_weights)))
        for name, expected in owned_weights.items():
            record = observed_weights[name]
            if (record.get('binding_id') != expected.binding_id
                    or record.get('memory_id') != expected.memory_id
                    or record.get('observed_bytes') != expected.encoded_bytes):
                raise ValueError('static reconciliation: observed weight identity '
                                 'or bytes mismatch: ' + name)
        # Extras are contradictions, not harmless surplus.
        if set(observed_extents) != set(owned_states):
            raise ValueError('static reconciliation: observed extent coverage '
                             'mismatch (unexpected or missing extents): '
                             + row.participant_id)
        expected_allocations = {charge.allocation_id for charge in inventory.charges
                                if charge.memory_id in owned_memories
                                and charge.bytes is not None}
        if set(observed_allocations) != expected_allocations:
            raise ValueError('static reconciliation: observed allocation coverage '
                             'mismatch (unexpected or missing allocations): '
                             + row.participant_id)
        _static_actual_allocations(plan, inventory, observed_allocations, observed_extents,
                                   observed_states, owned_composites, inv)
        if not expected_weights:
            raise ValueError('static reconciliation: participant owns no weights: '
                             + row.participant_id)
    return inventory


def _static_actual_allocations(plan, inventory, allocations, extents, states, composites, inv):
    """Account actual unique allocations, not descriptor estimates or labels."""
    memories = {m.memory_id: m for m in plan.profiles.snapshot.memory_resources}
    limits = {m.memory_id: m for m in plan.policy.memory_limits}
    charges = {c.allocation_id: c for c in inventory.charges}
    phase_allocations = {}
    domain_metrics = {}
    for name, record in allocations.items():
        charge = charges[name]
        memory = memories[charge.memory_id]
        if record.get('physical_domain') != memory.physical_id:
            raise ValueError('static reconciliation: allocation physical domain mismatch: ' + name)
        if record.get('phase') != charge.phase or record.get('role') != charge.role:
            raise ValueError('static reconciliation: allocation phase/role mismatch: ' + name)
        physical = record.get('physical_allocation_id')
        _text(physical, 'observed physical allocation identity')
        amount = record['observed_bytes']
        capacity, available = record.get('total_bytes'), record.get('available_bytes')
        if type(capacity) is not int or capacity < 1 or type(available) is not int or not 0 <= available <= capacity:
            raise ValueError('static reconciliation: actual allocation capacity/headroom UNKNOWN or inconsistent')
        metrics = (capacity, available)
        domain = memory.physical_id
        if domain in domain_metrics and metrics != domain_metrics[domain]:
            raise ValueError('static reconciliation: actual allocation capacity/headroom inconsistent across domain')
        domain_metrics[domain] = metrics
        if charge.role == 'virtual':
            continue
        key = (domain, charge.phase, physical)
        signature = (amount, charge.role, charge.memory_id)
        if key in phase_allocations:
            previous_name, previous = phase_allocations[key]
            # Only explicitly declared equal shared aliases can deduplicate.
            if (previous != signature or not charge.shared_allocation_id
                    or charge.shared_allocation_id != charges[previous_name].shared_allocation_id):
                raise ValueError('static reconciliation: actual allocation unplanned mirror or inconsistent alias')
        else:
            phase_allocations[key] = (name, signature)
    totals = {}
    for (domain, phase, physical), (name, signature) in phase_allocations.items():
        totals[domain, phase] = totals.get((domain, phase), 0) + signature[0]
    for (domain, phase), amount in totals.items():
        capacity, available = domain_metrics[domain]
        domain_limits = [limits[m.memory_id] for m in memories.values()
                         if m.physical_id == domain and m.memory_id in limits]
        if not domain_limits:
            raise ValueError('static reconciliation: actual allocation domain policy missing')
        if amount > capacity:
            raise ValueError('static reconciliation: actual allocation capacity exceeded: ' + domain)
        if any(amount > limit.peak_bytes for limit in domain_limits):
            raise ValueError('static reconciliation: actual allocation policy peak exceeded: ' + domain)
        if any(available < limit.min_available_bytes or available - amount < limit.reserve_bytes
               for limit in domain_limits):
            raise ValueError('static reconciliation: actual allocation headroom/reserve deficit: ' + domain)
    views = {}
    for name, extent in extents.items():
        allocation = extent.get('allocation_id')
        base = allocations.get(allocation)
        state = states[name]
        if base is None or base['memory_id'] != state['memory_id'] or base['role'] == 'virtual':
            raise ValueError('static reconciliation: observed extent unaccounted or foreign allocation: ' + name)
        offset, length = extent.get('offset'), extent.get('length')
        if (type(offset) is not int or offset < 0 or type(length) is not int
                or length != state['observed_bytes'] or extent.get('base_buffer_bytes') != base['observed_bytes']
                or offset + length > base['observed_bytes']):
            raise ValueError('static reconciliation: observed extent range outside base or mismatch: ' + name)
        views.setdefault(allocation, []).append((offset, offset + length, name))
    for frozen in inv.logical_composites:
        record = thaw(frozen)
        name = record['state_id']
        allocation = record.get('allocation_id')
        base = allocations.get(allocation)
        offset, length = record.get('offset'), record.get('observed_bytes')
        if (base is None or base['memory_id'] != composites[name].state.memory_id
                or base['role'] == 'virtual' or type(offset) is not int or offset < 0
                or type(length) is not int or length < 1 or offset + length > base['observed_bytes']):
            raise ValueError('static reconciliation: observed composite allocation/range UNKNOWN or mismatch: ' + name)
        views.setdefault(allocation, []).append((offset, offset + length, name))
    for allocation, intervals in views.items():
        end = 0
        used = 0
        for start, stop, name in sorted(intervals):
            if start < end:
                raise ValueError('static reconciliation: observed extent overlap: ' + name)
            end = stop
            used += stop - start
        padding = allocations[allocation].get('padding_bytes')
        if type(padding) is not int or padding < 0 or used + padding != allocations[allocation]['observed_bytes']:
            raise ValueError('static reconciliation: observed extent unaccounted base bytes: ' + allocation)


def _static_identity_join(plan, participants, rows, token):
    from .bindings import ProcessIdentity as _ProcessIdentity
    for row in rows:
        participant = participants[row.participant_id]
        spawn = row.spawn
        if spawn.participant_id != row.participant_id or spawn.invocation_token != token:
            raise ValueError('static reconciliation: spawn receipt identity mismatch: ' + row.participant_id)
        identity = row.identity
        if type(identity) is not _ProcessIdentity:
            raise ValueError('static reconciliation: typed owned identity required: ' + row.participant_id)
        expected = dict(participant_id=participant.participant_id, host_id=participant.host_id,
            boot_epoch=participant.boot_epoch, topology_epoch=participant.topology_epoch,
            executable=participant.runtime_executable, binary_sha256=participant.runtime_sha256,
            endpoint=participant.rpc_endpoint)
        for field, want in expected.items():
            if getattr(identity, field) != want:
                raise ValueError('static reconciliation: owned identity mismatch: ' + field + ': ' + row.participant_id)
        if identity.pid != spawn.pid or identity.start != spawn.start:
            raise ValueError('static reconciliation: owned identity pid/start mismatch: ' + row.participant_id)
        # The observed effective argv must contain the frozen runtime
        # executable; a foreign process image is a named refusal.
        if not identity.effective_argv or identity.effective_argv[0] != participant.runtime_executable:
            raise ValueError('static reconciliation: owned process image mismatch: ' + row.participant_id)
        # Effective device visibility must be OBSERVED and equal the frozen
        # configured selectors. The /proc identity reader cannot currently
        # observe native/visible selectors, so production refuses here with
        # the smallest missing observer capability named — an empty or
        # mismatched visibility is never silently accepted.
        from .profiles import thaw as _thawx
        visibility = _thawx(identity.visibility)
        expected_native = sorted(b.native_selector for b in participant.bindings)
        expected_visible = sorted(b.visible_selector for b in participant.bindings)
        observed_native = sorted(visibility.get('native') or [])
        observed_visible = sorted(visibility.get('visible') or [])
        if observed_native != expected_native or observed_visible != expected_visible:
            raise ValueError(
                'static reconciliation: effective device visibility not independently '
                'observed for ' + row.participant_id + '; smallest missing observer '
                'capability: native/visible selector observation of the owned process '
                '(the /proc identity reader currently reports none)')


def _static_build_join(plan, participants, rows):
    from .qwen_q8 import RUNTIME_PIN, RUNTIME_TREE
    for row in rows:
        participant = participants[row.participant_id]
        build = row.build
        if type(build) is not DerivedBuildEvidence:
            raise ValueError('static reconciliation: derived build evidence required: ' + row.participant_id)
        manifest = build.manifest
        if manifest.executable_sha256 != participant.runtime_sha256:
            raise ValueError('static reconciliation: derived build executable identity mismatch: ' + row.participant_id)
        if manifest.base_revision != RUNTIME_PIN or manifest.base_tree != RUNTIME_TREE:
            raise ValueError('static reconciliation: derived build does not descend from the pinned base: ' + row.participant_id)


_STATIC_VERDICT = 'STATIC_ADMITTED'
_DYNAMIC_VERDICT = 'DYNAMIC_ACCEPTED'
_SET_OPS = ('set', 'rpc_set')
_GET_OPS = ('get', 'rpc_get')


def _static_capture_join(plan, rows, mode, now):
    """Fresh independent capture joins; labels are not authentication or #300."""
    from .profiles import utc_timestamp, validate_profiles
    for row in rows:
        origins = (getattr(row.observed_inventory, 'source', None),
                   getattr(row.observed_host_facts, 'source', None))
        if mode == 'live' and origins != ('native-observer/2', 'proc-owned/2'):
            raise ValueError('static reconciliation: evidence provenance missing, synthetic or unknown: '
                             + row.participant_id)
        if mode == 'synthetic-test' and any(origin not in (None, 'synthetic-contract') for origin in origins):
            raise ValueError('static reconciliation: synthetic evidence provenance must be explicit')
        capture = row.capture
        if capture is None:
            if mode == 'live':
                raise ValueError('static reconciliation: independent capture provenance missing: '
                                 + row.participant_id)
            continue
        capture = thaw(capture)
        required = ('observed_at', 'expires_at', 'capture_id', 'producer', 'plan_digest',
                    'invocation_token', 'pid', 'start', 'build_digest', 'source_digest')
        keys(capture, required, 'static capture')
        for key, expected in dict(plan_digest=plan.digest,
                invocation_token=row.spawn.invocation_token, pid=row.spawn.pid, start=row.spawn.start,
                build_digest=row.build.manifest.manifest_sha256,
                source_digest=row.source_receipt_digest,
                producer='native-observer/2' if mode == 'live' else 'synthetic-contract').items():
            if not _same_json(capture[key], expected):
                raise ValueError('static reconciliation: capture ' + key + ' mismatch')
        _text(capture['capture_id'], 'static capture identity')
        observed = utc_timestamp(capture['observed_at'])
        expires = utc_timestamp(capture['expires_at'])
        if observed > now or expires <= now or expires <= observed or (now - observed).total_seconds() > plan.policy.max_age_seconds:
            raise ValueError('static reconciliation: capture stale, expired or future')
    if mode == 'live':
        from dataclasses import replace
        deficits = validate_profiles(plan.profiles.snapshot, now=now, policy=plan.policy,
                                     subject=replace(plan.candidate.subject, mode='live'))
        if deficits:
            raise ValueError('static reconciliation: capture profile freshness/provenance: ' + '; '.join(deficits))


def _evidence_wire(value):
    from dataclasses import asdict
    return thaw(asdict(value)) if value is not None else None


def reconcile_static(plan, evidence, source_receipts, *, mode='live', clock=None):
    """Complete static admission over independently collected evidence.

    Joins the typed plan's calculated inventory with independently collected
    per-participant evidence: complete verified source ranges over every
    weight assignment, owned spawn/identity equality, and the explicit
    derived-build qualification binding the observer binary to the pinned
    base. Any missing, stale or contradictory fact refuses with its name;
    a receipt never authorizes execution.
    """
    from .bindings import _now as _binding_now
    from .profiles import sha256 as _sha256, canonical as _canonical, thaw as _thaw
    now = _binding_now(mode, clock)
    participants, rows, token = _static_evidence_rows(plan, evidence)
    _static_source_join(plan, participants, rows, source_receipts)
    _static_identity_join(plan, participants, rows, token)
    _static_build_join(plan, participants, rows)
    _static_capture_join(plan, rows, mode, now)
    inventory = _static_observed_joins(plan, participants, rows)
    material = []
    for row in sorted(rows, key=lambda r: r.participant_id):
        material.append(dict(participant_id=row.participant_id,
            identity_digest=_identity_wire_digest(row.identity),
            spawn_pid=row.spawn.pid, spawn_start=row.spawn.start,
            build_manifest=manifest_wire(row.build.manifest),
            executable_sha256=row.build.executable_sha256,
            source_receipt_digest=row.source_receipt_digest,
            observed_inventory=_evidence_wire(row.observed_inventory),
            observed_host_facts=_evidence_wire(row.observed_host_facts),
            capture=thaw(row.capture), invocation_token=row.spawn.invocation_token,
            plan_digest=plan.digest))
    counts = (('participants', len(rows)),
              ('source-range-joined-weights', len(plan.candidate.assignments)),
              ('expected-states', len(plan.candidate.required_state)),
              ('boundaries', len(plan.candidate.boundaries)),
              ('observed-persistent-states', len(inventory.persistent_caches)),
              ('observed-logical-composites', len(inventory.logical_composites)))
    spawns = tuple(sorted((row.spawn.participant_id, row.spawn.pid, row.spawn.start)
                          for row in rows))
    return PhaseReceipt(RECEIPT_SCHEMA, 'static', _STATIC_VERDICT, plan.digest, plan.selection,
        token, _sha256(material), True, False, False, None, counts, spawns)


def _identity_wire_digest(identity):
    from .profiles import sha256 as _sha256
    from dataclasses import asdict as _asdict
    payload = _asdict(identity)
    payload['effective_argv'] = list(payload['effective_argv'])
    payload['visibility'] = _visibility_wire(payload['visibility'])
    return _sha256(payload)


def _visibility_wire(value):
    from .profiles import thaw as _thaw
    out = _thaw(value)
    if isinstance(out, dict):
        return {k: (list(v) if isinstance(v, (list, tuple)) else dict(v) if isinstance(v, dict) else v)
                for k, v in out.items()}
    return out


def manifest_wire(manifest):
    body = {name: getattr(manifest, name) for name in BUILD_COMPONENTS if name != 'backend_libraries'}
    body['build_options'] = list(manifest.build_options)
    body['backend_libraries'] = [{'name': n, 'sha256': d} for n, d in manifest.backend_libraries]
    body['manifest_sha256'] = manifest.manifest_sha256
    return body


def reconcile_dynamic(plan, static_receipt, evidence, request_identity, *, mode='live', clock=None):
    """Same-request dynamic acceptance over collected native evidence.

    Requires a STATIC_ADMITTED receipt for the same plan and invocation,
    terminal whole dynamic streams for every participant, the actual
    task/response and graph-generation facts for this request, nonempty
    allocation catalogs, and both GET/SET copy legs with the client-side
    output-custody readback. A verdict accepts output only; execution
    already occurred and is never authorized here.
    """
    from .bindings import _now as _binding_now
    from .plan import ProfiledOperatorPlan as _Plan
    from .profiles import sha256 as _sha256, thaw as _thaw, integer as _integer
    _binding_now(mode, clock)
    if type(plan) is not _Plan or plan.strategy_id != 'qwen38-q8-fixed/1':
        raise ValueError('dynamic reconciliation: typed profiled plan required')
    if type(static_receipt) is not PhaseReceipt:
        raise ValueError('dynamic reconciliation: typed static receipt required')
    if (static_receipt.schema != RECEIPT_SCHEMA or static_receipt.phase != 'static'
            or static_receipt.verdict != _STATIC_VERDICT):
        raise ValueError('dynamic reconciliation: static admission receipt required')
    if not static_receipt.observations_valid:
        raise ValueError('dynamic reconciliation: static receipt observations invalid')
    if not static_receipt.spawn_facts:
        raise ValueError('dynamic reconciliation: static receipt spawn facts missing')
    if static_receipt.plan_digest != plan.digest or static_receipt.selection != plan.selection:
        raise ValueError('dynamic reconciliation: static receipt plan identity mismatch')
    if type(request_identity) is not RequestIdentity:
        raise ValueError('dynamic reconciliation: typed request identity required')
    if static_receipt.invocation_token != request_identity.invocation_token:
        raise ValueError('dynamic reconciliation: invocation token mismatch')
    if request_identity.response_id is None:
        raise ValueError('dynamic reconciliation: request response binding missing')
    if request_identity.task_id is None:
        raise ValueError('dynamic reconciliation: request task binding missing: '
                         'bind the observed native task id from collected evidence, '
                         'never dispatch without it')
    if type(evidence) not in (tuple, list) or not evidence:
        raise ValueError('dynamic reconciliation: typed participant evidence required')
    rows = []
    for row in evidence:
        if type(row) is not ParticipantDynamicEvidence:
            raise ValueError('dynamic reconciliation: typed participant evidence required')
        rows.append(row)
    participants = {p.participant_id: p for p in plan.participants}
    ids = [row.participant_id for row in rows]
    if set(ids) != set(participants) or len(ids) != len(set(ids)):
        raise ValueError('dynamic reconciliation: participant coverage mismatch')
    client_id = next(p.participant_id for p in plan.participants if p.role == 'client')
    events = {}
    facts = {}
    wire_bytes = 0
    tokens = set()
    for row in rows:
        observation = row.observation
        tokens.add(row.spawn.invocation_token)
        if observation.participant_id != row.native_participant:
            raise ValueError('dynamic reconciliation: observation label mismatch: ' + row.participant_id)
        facts[row.participant_id] = _thaw(observation.facts)
        events[row.participant_id] = tuple(item['event'] for item in
                                           [_sequence_wire(item) for item in observation.sequence])
        allocations = facts[row.participant_id].get('allocations')
        if not isinstance(allocations, list) or not allocations:
            raise ValueError('dynamic reconciliation: allocation catalog incomplete: ' + row.participant_id)
        for record in allocations:
            if (not isinstance(record, dict) or type(record.get('buffer_bytes')) is not int
                    or record['buffer_bytes'] < 1):
                raise ValueError('dynamic reconciliation: allocation record incomplete: ' + row.participant_id)
            backend = record.get('backend')
            # Native backend labels are 'CPU' or ordinal RPC registration
            # names ('RPC0[host:port]'); anything else is not a native fact.
            if (not isinstance(backend, str) or not backend
                    or (backend != 'CPU' and not backend.startswith('RPC'))):
                raise ValueError('dynamic reconciliation: allocation backend not a native '
                                 'selector label: ' + row.participant_id)
        for record in transfers_of(facts[row.participant_id]):
            wire_bytes += _integer(record.get('bytes'), 'dynamic transfer bytes', minimum=0)
    if len(tokens) != 1 or tokens.pop() != request_identity.invocation_token:
        raise ValueError('dynamic reconciliation: invocation token mismatch')
    dynamic_spawns = tuple(sorted((row.spawn.participant_id, row.spawn.pid, row.spawn.start)
                                  for row in rows))
    if dynamic_spawns != tuple(static_receipt.spawn_facts):
        raise ValueError('dynamic reconciliation: spawn continuity with static admission mismatch')
    # Same-request task/response/graph/ubatch/token/state-lineage joins.
    # The request nonce is the controller-side correlation key; the observed
    # native task/response/ubatch/output-custody facts must carry it back.
    # The native producer emits response_id as the literal "unknown" at
    # task-creation time; request binding is by observed task id AND the
    # request nonce correlation.
    client_facts = facts[client_id]
    nonce = request_identity.request_nonce
    tasks = client_facts.get('tasks')
    if not isinstance(tasks, list) or not tasks:
        raise ValueError('dynamic reconciliation: request task facts missing')
    correlated_tasks = set()
    observed_task_ids = set()
    for task in tasks:
        if not isinstance(task, dict) or type(task.get('task_id')) is not int:
            raise ValueError('dynamic reconciliation: request task record malformed')
        observed_task_ids.add(task['task_id'])
        if task.get('request_nonce') == nonce:
            correlated_tasks.add(task['task_id'])
    if request_identity.task_id not in {str(t) for t in observed_task_ids}:
        raise ValueError('dynamic reconciliation: request task not observed for this request')
    if int(request_identity.task_id) not in correlated_tasks:
        raise ValueError('dynamic reconciliation: request task lacks request '
                         'correlation (observed nonce mismatch): no same-request '
                         'identity join; smallest missing observer capability: '
                         'request-nonce correlation emitted in native task/response '
                         'facts by the retained #301 producer (controller-side '
                         'binding alone cannot join them)')
    request_task = int(request_identity.task_id)
    responses = client_facts.get('responses')
    if not isinstance(responses, list) or not responses:
        raise ValueError('dynamic reconciliation: response custody facts missing')
    # The response custodian must have answered THE request's task with the
    # request's nonce; responses naming only other tasks or lacking the
    # nonce do not establish this request's output custody.
    answered = set()
    for response in responses:
        if not isinstance(response, dict) or type(response.get('task_id')) is not int:
            raise ValueError('dynamic reconciliation: response task record malformed')
        if response['task_id'] not in observed_task_ids:
            raise ValueError('dynamic reconciliation: response task join mismatch')
        if response.get('request_nonce') == nonce:
            answered.add(response['task_id'])
    if request_task not in answered:
        raise ValueError('dynamic reconciliation: no observed response for the '
                         'request task with request correlation')
    graphs = client_facts.get('graphs')
    if not isinstance(graphs, list) or not graphs:
        raise ValueError('dynamic reconciliation: graph facts missing')
    observed_generations = set()
    for graph in graphs:
        if not isinstance(graph, dict) or type(graph.get('status')) is not int \
                or graph['status'] != 0:
            raise ValueError('dynamic reconciliation: graph status not successful')
        # Native graph ids are runtime pointers (unbounded 64-bit); the value
        # is opaque, so only identity presence and a successful status count.
        if type(graph.get('graph_id')) is not int or graph['graph_id'] < 1:
            raise ValueError('dynamic reconciliation: graph identity missing')
        if type(graph.get('nodes')) is not int or graph['nodes'] < 1:
            raise ValueError('dynamic reconciliation: graph node count missing')
        if graph.get('ubatch_lineage') in (None, 'unknown', ''):
            raise ValueError('dynamic reconciliation: graph ubatch lineage UNKNOWN '
                             'refuses same-request acceptance')
        observed_generations.add(graph['graph_id'])
    for generation in request_identity.graph_generations:
        if generation not in observed_generations:
            raise ValueError('dynamic reconciliation: graph generation not observed for this request')
    # Ubatches and tokens must be correlated with the request nonce and the
    # observed task; state lineage must cover the required-state catalog.
    ubatches = client_facts.get('ubatches')
    if not isinstance(ubatches, list) or not ubatches:
        raise ValueError('dynamic reconciliation: ubatch lineage facts missing')
    for ubatch in ubatches:
        if not isinstance(ubatch, dict) or ubatch.get('task_id') != request_task \
                or ubatch.get('request_nonce') != nonce:
            raise ValueError('dynamic reconciliation: ubatch not correlated with '
                             'the request task/nonce')
        if type(ubatch.get('tokens')) is not int or ubatch['tokens'] < 1:
            raise ValueError('dynamic reconciliation: ubatch token count missing')
    tokens = client_facts.get('tokens')
    if not isinstance(tokens, list) or not tokens:
        raise ValueError('dynamic reconciliation: token facts missing')
    for token_row in tokens:
        if not isinstance(token_row, dict) or token_row.get('task_id') != request_task \
                or token_row.get('request_nonce') != nonce:
            raise ValueError('dynamic reconciliation: token facts not correlated '
                             'with the request task/nonce')
    lineage = client_facts.get('state_lineage')
    if not isinstance(lineage, list) or not lineage:
        raise ValueError('dynamic reconciliation: state lineage facts missing')
    for row_lineage in lineage:
        if not isinstance(row_lineage, dict) or row_lineage.get('task_id') != request_task \
                or row_lineage.get('request_nonce') != nonce:
            raise ValueError('dynamic reconciliation: state lineage not correlated '
                             'with the request task/nonce')
    client_events = events[client_id]
    for required in ('server_task_new_id', 'server_task_processed', 'server_response_send'):
        if required not in client_events:
            raise ValueError('dynamic reconciliation: request lifecycle event missing: ' + required)
    # Output custody for THIS request's task and nonce on the client side.
    custody = client_facts.get('output_custody')
    if not isinstance(custody, list) or not custody:
        raise ValueError('dynamic reconciliation: output custody facts missing')
    if not any(isinstance(row, dict) and row.get('task_id') == request_task
               and row.get('request_nonce') == nonce
               and type(row.get('readback_bytes')) is int
               and row['readback_bytes'] > 0 for row in custody):
        raise ValueError('dynamic reconciliation: output custody not bound to the '
                         'request task/nonce')
    # Route-correct copy-route legs. one-gpu requires every B CPU -> A
    # staging -> B CUDA boundary on both SET and GET families with explicit
    # domain endpoints; cpu-only requires CPU-domain legs only. Incidental
    # CPU fixture activity never satisfies the CUDA-route predicate.
    all_transfers = [record for row in rows for record in transfers_of(facts[row.participant_id])]
    # Every transfer must be attributable to this request, not merely carry a
    # matching boundary label. The collector must supply producer-observed
    # task/nonce values; absence is not repaired from controller context.
    nonce = request_identity.request_nonce
    for record in all_transfers:
        if (type(record.get('task_id')) is not int
                or record.get('task_id') != request_task
                or record.get('request_nonce') != nonce):
            raise ValueError('dynamic reconciliation: transfer request task/nonce '
                             'correlation missing or foreign')
    ops = {record.get('op') for record in all_transfers}
    if not any(op in _SET_OPS for op in ops):
        raise ValueError('dynamic reconciliation: copy route SET leg missing')
    if not any(op in _GET_OPS for op in ops):
        raise ValueError('dynamic reconciliation: copy route GET leg missing')
    if plan.selection == 'one-gpu':
        # Each required boundary must be satisfied by a transfer record that
        # is completed AND joins the correct op family and source/destination
        # domains; a record carrying the label with a wrong op, wrong domains
        # or incomplete status cannot satisfy the predicate.
        required_legs = (
            ('b-cpu-to-a-staging', _SET_OPS, 'B/cpu', 'A/staging'),
            ('a-staging-to-b-cuda', _SET_OPS, 'A/staging', 'B/cuda'),
            ('b-cuda-to-a-staging', _GET_OPS, 'B/cuda', 'A/staging'),
            ('a-staging-to-output', _GET_OPS, 'A/staging', 'A/cpu-output'),
        )
        for boundary, family, source, destination in required_legs:
            satisfied = any(
                record.get('boundary') == boundary
                and record.get('completed') is True
                and record.get('op') in family
                and record.get('source_domain') == source
                and record.get('dest_domain') == destination
                and type(record.get('bytes')) is int and record['bytes'] >= 1
                for record in all_transfers)
            if not satisfied:
                raise ValueError('dynamic reconciliation: copy route boundary '
                                 'missing or not domain/op-joined for the one-gpu '
                                 'CUDA route: ' + boundary)
        # Every completed transfer must name a known boundary of this route;
        # foreign labels are contradictions, not harmless surplus. The RPC
        # participant observes its own side of the CPU->CUDA hop as a single
        # b-cpu-to-b-cuda leg (remote backend perspective), so it is known.
        known = {boundary for boundary, _, _, _ in required_legs} | {'b-cpu-to-b-cuda', 'b-cuda-to-b-cpu'}
        for record in all_transfers:
            if record.get('completed') is True and record.get('boundary') not in known:
                raise ValueError('dynamic reconciliation: completed transfer with '
                                 'foreign boundary label refuses the one-gpu route: '
                                 + repr(record.get('boundary')))
            if type(record.get('bytes')) is not int or record['bytes'] < 1:
                raise ValueError('dynamic reconciliation: transfer record without '
                                 'material bytes')
    else:
        seen_ops = set()
        for record in all_transfers:
            if record.get('boundary') != 'cpu-only' \
                    or record.get('source_domain') not in ('B/cpu', 'A/cpu') \
                    or record.get('dest_domain') not in ('B/cpu', 'A/cpu'):
                raise ValueError('dynamic reconciliation: cpu-only route requires '
                                 'CPU-domain boundary evidence')
            if record.get('completed') is True:
                seen_ops.add(record.get('op'))
        # Both legs must exist as completed CPU-domain transfers.
        if not any(op in _SET_OPS for op in seen_ops):
            raise ValueError('dynamic reconciliation: cpu-only route SET leg missing')
        if not any(op in _GET_OPS for op in seen_ops):
            raise ValueError('dynamic reconciliation: cpu-only route GET leg missing')
    material = []
    for row in sorted(rows, key=lambda r: r.participant_id):
        material.append(dict(participant_id=row.participant_id,
            claim_pid=row.claim_pid, claim_start=row.claim_start,
            observation_digest=row.observation.terminal_digest,
            events=len(events[row.participant_id])))
    counts = (('participants', len(rows)),
              ('tasks', 1),
              ('graphs', len(graphs)),
              ('transfers', len(all_transfers)),
              ('wire_bytes', wire_bytes))
    return PhaseReceipt(RECEIPT_SCHEMA, 'dynamic', _DYNAMIC_VERDICT, plan.digest, plan.selection,
        request_identity.invocation_token, _sha256(material), True, False, False,
        request_identity, counts)


def transfers_of(facts):
    transfers = facts.get('transfers')
    if not isinstance(transfers, list) or not transfers:
        raise ValueError('dynamic reconciliation: transfer facts missing')
    for record in transfers:
        if not isinstance(record, dict):
            raise ValueError('dynamic reconciliation: transfer record malformed')
        if type(record.get('bytes')) is not int or record['bytes'] < 1:
            raise ValueError('dynamic reconciliation: transfer record without material bytes')
        shape = record.get('shape')
        if (not isinstance(shape, list) or not shape
                or any(type(dim) is not int or dim < 1 for dim in shape)):
            raise ValueError('dynamic reconciliation: transfer record without observed shape')
        if not isinstance(record.get('op'), str) or not record['op']:
            raise ValueError('dynamic reconciliation: transfer record without op')
    return transfers


def _sequence_wire(item):
    from .profiles import thaw as _thaw
    return _thaw(item)


__all__ = ['BUILD_SCHEMA', 'RECEIPT_SCHEMA', 'NATIVE_STREAM_SCHEMA',
           'NativeBuildIdentity', 'RequestIdentity', 'ParsedObservation', 'PhaseReceipt',
           'IncompleteReconciliation', 'parse_build_manifest', 'native_build_matches',
           'require_native_build_match', 'parse_observation', 'reconcile_static', 'reconcile_dynamic',
           'StaticPlanContext', 'derive_static_plan_context', 'OwnedSpawnFacts', 'DerivedBuildEvidence',
           'ParticipantStaticEvidence', 'ParticipantDynamicEvidence']

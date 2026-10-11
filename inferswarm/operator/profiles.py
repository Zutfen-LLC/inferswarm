"""Generic immutable resource/evidence snapshots, without model placement rules.

An authenticated profile is operator-supplied evidence, not discovered hardware.
Synthetic/replay records are illustrative and never live execution authority.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
import re
import hashlib
import json
import math
from typing import Any, Mapping


@dataclass(frozen=True)
class EvidenceRef:
    evidence_id: str
    sha256: str
    observed_at: str
    expires_at: str
    provenance: tuple
    dependencies: tuple
    evidence_class: str
    source_scope: str
    payload: tuple


@dataclass(frozen=True)
class HostProfile:
    host_id: str
    physical_id: str
    boot_epoch: str
    topology_epoch: str
    evidence_id: str


@dataclass(frozen=True)
class ComputeProfile:
    compute_id: str
    host_id: str
    physical_id: str
    backend: str
    memory_ids: tuple[str, ...]
    evidence_id: str


@dataclass(frozen=True)
class MemoryProfile:
    memory_id: str
    physical_id: str
    host_id: str
    kind: str
    total_bytes: int
    available_bytes: int
    evidence_id: str


@dataclass(frozen=True)
class LinkProfile:
    link_id: str
    source_host_id: str
    target_host_id: str
    path: str
    protocol: str
    throughput_bytes_per_second: int
    latency_seconds: float
    evidence_id: str


@dataclass(frozen=True)
class RuntimeCapability:
    runtime_id: str
    host_id: str
    compute_id: str
    source_revision: str
    build_id: str
    binary_sha256: str
    driver: str
    backend: str
    route: str
    capabilities: tuple[str, ...]
    evidence_id: str


@dataclass(frozen=True)
class ResourceSnapshot:
    hosts: tuple[HostProfile, ...]
    compute_units: tuple[ComputeProfile, ...]
    memory_resources: tuple[MemoryProfile, ...]
    links: tuple[LinkProfile, ...]
    runtime_capabilities: tuple[RuntimeCapability, ...]
    evidence: tuple[EvidenceRef, ...]
    digest: str


class FrozenMapping(tuple):
    """Immutable tuple of key/value pairs, tagged to distinguish JSON objects.

    Use canonical()/thaw() for digest-bearing serialization, never guess whether
    a plain tuple containing pairs was originally an object or an array.
    """
    __slots__ = ()


def thaw(value):
    if isinstance(value, FrozenMapping): return {k:thaw(v) for k,v in value}
    if isinstance(value, Mapping): return {k:thaw(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)): return [thaw(v) for v in value]
    return value


def canonical(value):
    return json.dumps(thaw(value), sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('utf-8')


def sha256(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def freeze(value, *, _depth=0):
    """Freeze bounded opaque data; generic code never interprets strategy keys."""
    if _depth > 32: raise ValueError('opaque data too deeply nested')
    if isinstance(value, Mapping):
        if len(value) > 10000: raise ValueError('oversized opaque mapping')
        for key in value: text(key, 'opaque key')
        return FrozenMapping((k, freeze(v, _depth=_depth+1)) for k, v in sorted(value.items()))
    if isinstance(value, (list, tuple)):
        if len(value) > 10000: raise ValueError('oversized opaque array')
        return tuple(freeze(v, _depth=_depth+1) for v in value)
    if value is None or type(value) is bool: return value
    if type(value) is int:
        if value < 0: raise ValueError('negative opaque integer')
        if value > 2**64-1: raise ValueError('oversized opaque integer')
        return value
    if type(value) is float:
        if not math.isfinite(value): raise ValueError('nonfinite opaque number')
        if value < 0: raise ValueError('negative opaque number')
        return value
    if type(value) is str:
        if '\x00' in value or len(value.encode('utf-8')) > 65536: raise ValueError('invalid opaque text')
        return value
    raise ValueError('unsupported opaque value')


def keys(value, expected, where):
    if not isinstance(value, Mapping) or set(value) != set(expected):
        raise ValueError(f'{where} fields must be exactly {sorted(expected)}')


def text(value, where):
    if not isinstance(value, str) or not value or value != value.strip() or '\x00' in value or len(value.encode('utf-8')) > 4096:
        raise ValueError(f'{where} must be nonempty exact text')
    return value


def integer(value, where, *, minimum=0, maximum=2**63-1):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f'{where} must be integer {minimum}..{maximum}')
    return value


def digest(value, where):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError(f'{where} must be lowercase SHA-256')
    return value


def utc_timestamp(value):
    text(value, 'UTC timestamp')
    if not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|\+00:00)', value):
        raise ValueError('expected timezone-aware UTC timestamp')
    try: return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc: raise ValueError('invalid UTC timestamp') from exc


def _array(value, where, *, nonempty=True):
    if not isinstance(value, (list, tuple)) or len(value) > 10000:
        raise ValueError(f'{where} must be bounded array')
    if nonempty and not value: raise ValueError(f'missing {where} profile')
    return value


def _texts(value, where):
    result = tuple(sorted(text(v, where) for v in _array(value, where)))
    if len(set(result)) != len(result): raise ValueError(f'duplicate {where}')
    return result


def _text_pairs(value, where):
    if not isinstance(value, Mapping) or not value: raise ValueError(f'{where} must be nonempty mapping')
    if len(value) > 1000: raise ValueError(f'oversized {where}')
    return tuple(sorted((text(k, where), text(v, where)) for k, v in value.items()))


# Descriptive backend vocabulary, not vendor/placement policy. Strategies decide
# which of these capabilities are legal for their own state/representations.
BACKENDS = frozenset(('cpu', 'cuda', 'vulkan', 'hip', 'sycl', 'metal', 'opencl', 'npu'))
EVIDENCE_CLASSES = frozenset(('measured', 'calculated', 'estimated', 'unknown'))
_GROUPS = (('hosts', HostProfile, 'host_id'), ('compute_units', ComputeProfile, 'compute_id'),
           ('memory_resources', MemoryProfile, 'memory_id'), ('links', LinkProfile, 'link_id'),
           ('runtime_capabilities', RuntimeCapability, 'runtime_id'))


def parse_profiles(mapping) -> ResourceSnapshot:
    """Validate identities/envelopes and freeze; freshness needs validate_profiles.

    Evidence SHA authenticates the canonical envelope (all fields except sha256)
    and its exact resource payload. An operator's pinned file/digest supplies the
    external authority; self-hashing invented records does not prove hardware.
    """
    keys(mapping, ('schema', *[g[0] for g in _GROUPS], 'evidence'), 'profiles')
    if mapping['schema'] != 'resource-profiles/1': raise ValueError('unsupported profile schema')
    normalized = {'schema': mapping['schema']}
    groups = []
    for name, cls, key in _GROUPS:
        rows = []
        for raw in _array(mapping[name], name):
            keys(raw, [f.name for f in fields(cls)], name)
            row = dict(raw)
            for field, value in row.items():
                if field not in ('memory_ids','capabilities','total_bytes','available_bytes','throughput_bytes_per_second','latency_seconds'):
                    text(value, f'{name}.{field}')
            if name == 'memory_resources':
                total = integer(row['total_bytes'], 'memory capacity total_bytes', minimum=1)
                integer(row['available_bytes'], 'memory capacity available_bytes', maximum=total)
                if row['kind'] not in ('ram','vram','hbm','storage','cxl','device'):
                    raise ValueError('unsupported memory resource kind')
            if name == 'links':
                integer(row['throughput_bytes_per_second'], 'link measurement throughput', minimum=1)
                latency = row['latency_seconds']
                if type(latency) not in (int,float) or not math.isfinite(latency) or latency < 0:
                    raise ValueError('link measurement requires finite nonnegative latency')
                if row['source_host_id'] == row['target_host_id']: raise ValueError('link endpoints must be distinct')
            for field in ('memory_ids', 'capabilities'):
                if field in row: row[field] = _texts(row[field], field)
            if 'backend' in row and row['backend'] not in BACKENDS: raise ValueError('unsupported backend')
            if 'binary_sha256' in row: digest(row['binary_sha256'], 'runtime binary')
            rows.append(cls(**row))
        if len({getattr(r,key) for r in rows}) != len(rows): raise ValueError(f'duplicate {key}')
        if key in ('host_id','compute_id','memory_id') and len({r.physical_id for r in rows}) != len(rows):
            raise ValueError(f'physical identity alias in {name}')
        rows.sort(key=lambda row: getattr(row,key))
        groups.append(tuple(rows)); normalized[name] = [asdict(row) for row in rows]
    hosts, computes, memories, links, runtimes = groups
    hostmap = {r.host_id:r for r in hosts}; memmap = {r.memory_id:r for r in memories}; cumap = {r.compute_id:r for r in computes}
    for r in (*computes, *memories, *runtimes):
        if r.host_id not in hostmap: raise ValueError(f'missing host profile: {r.host_id}')
    for cu in computes:
        for mid in cu.memory_ids:
            if mid not in memmap: raise ValueError(f'missing memory profile: {mid}')
            if memmap[mid].host_id != cu.host_id: raise ValueError('compute memory host affinity mismatch')
    for link in links:
        if link.source_host_id not in hostmap or link.target_host_id not in hostmap: raise ValueError('missing host profile for link')
    for runtime in runtimes:
        cu = cumap.get(runtime.compute_id)
        if cu is None: raise ValueError('compute profile coverage: missing runtime compute')
        if cu.host_id != runtime.host_id or cu.backend != runtime.backend: raise ValueError('runtime compute context mismatch')
    evidence = []; envelopes = []
    for raw in _array(mapping['evidence'], 'evidence'):
        keys(raw, [f.name for f in fields(EvidenceRef)], 'evidence')
        text(raw['evidence_id'], 'evidence_id'); digest(raw['sha256'], 'evidence')
        observed, expires = utc_timestamp(raw['observed_at']), utc_timestamp(raw['expires_at'])
        if expires <= observed: raise ValueError('expiry must follow observation')
        if not isinstance(raw['evidence_class'], str) or raw['evidence_class'] not in EVIDENCE_CLASSES: raise ValueError('unsupported evidence class')
        if raw['source_scope'] not in ('live','synthetic','replay'): raise ValueError('unsupported evidence source scope')
        provenance = _text_pairs(raw['provenance'], 'provenance')
        dependencies = _text_pairs(raw['dependencies'], 'dependencies')
        if not isinstance(raw['payload'], Mapping): raise ValueError('evidence payload must be mapping')
        payload = freeze(raw['payload'])
        assert isinstance(payload, FrozenMapping)
        if sha256({k:v for k,v in raw.items() if k!='sha256'}) != raw['sha256']:
            raise ValueError(f'evidence SHA-256 mismatch: {raw["evidence_id"]}')
        evidence.append(EvidenceRef(raw['evidence_id'], raw['sha256'], raw['observed_at'], raw['expires_at'], provenance, dependencies, raw['evidence_class'], raw['source_scope'], payload))
        envelopes.append(dict(raw))
    if len({e.evidence_id for e in evidence}) != len(evidence): raise ValueError('duplicate evidence_id')
    evmap = {e.evidence_id:e for e in evidence}; referenced = set()
    for group in groups:
        for row in group:
            e = evmap.get(row.evidence_id)
            if e is None: raise ValueError(f'missing evidence: {row.evidence_id}')
            if row.evidence_id in referenced: raise ValueError('substituted evidence reused for distinct profiles')
            referenced.add(row.evidence_id)
            expected = asdict(row); expected.pop('evidence_id')
            if freeze(expected) != e.payload: raise ValueError(f'evidence payload mismatch: {e.evidence_id}')
    if referenced != set(evmap): raise ValueError('unreferenced evidence')
    evidence.sort(key=lambda r:r.evidence_id)
    normalized['evidence'] = sorted(envelopes, key=lambda r:r['evidence_id'])
    return ResourceSnapshot(groups[0],groups[1],groups[2],groups[3],groups[4],tuple(evidence),sha256(normalized))


@dataclass(frozen=True)
class ProfileSubject:
    host_ids: tuple[str, ...]
    compute_ids: tuple[str, ...]
    memory_ids: tuple[str, ...]
    link_ids: tuple[str, ...]
    runtime_ids: tuple[str, ...]
    dependencies: tuple[tuple[str, str], ...]
    mode: str = 'live'


def snapshot_mapping(snapshot):
    """Return a detached JSON-shaped mapping, for integrity revalidation."""
    value: dict[str, Any] = {'schema':'resource-profiles/1'}
    for group, _, _ in _GROUPS: value[group] = [asdict(r) for r in getattr(snapshot,group)]
    value['evidence'] = []
    for e in snapshot.evidence:
        row = asdict(e)
        for name in ('provenance','dependencies','payload'): row[name] = dict(getattr(e,name))
        value['evidence'].append(row)
    return value


def _dependency_context(snapshot):
    context = {}
    for host in snapshot.hosts:
        for key in ('physical_id','boot_epoch','topology_epoch'): context[f'host:{host.host_id}:{key}'] = getattr(host,key)
    for name, key in (('compute_units','compute_id'),('memory_resources','memory_id')):
        prefix = 'compute' if key=='compute_id' else 'memory'
        for row in getattr(snapshot,name): context[f'{prefix}:{getattr(row,key)}:physical_id'] = row.physical_id
    for runtime in snapshot.runtime_capabilities:
        for key in ('source_revision','build_id','binary_sha256','driver','backend','route'):
            context[f'runtime:{runtime.runtime_id}:{key}'] = getattr(runtime,key)
    for link in snapshot.links:
        for key in ('path','protocol'): context[f'link:{link.link_id}:{key}'] = getattr(link,key)
    return context


def validate_profiles(snapshot, *, now, policy, subject) -> tuple[str, ...]:
    """Return named blocking reasons, empty only if evidence is applicable now.

    now=None queries real UTC. Replay clock never makes synthetic evidence live.
    Call again at planning/execution; no clock value enters snapshot.digest.
    Empty reasons do NOT establish kernel/physical qualification or authority.
    """
    if not isinstance(snapshot, ResourceSnapshot) or not isinstance(subject, ProfileSubject):
        raise ValueError('snapshot and profile subject types required')
    if subject.mode not in ('live','replay'): raise ValueError('unsupported profile validation mode')
    if subject.mode == 'replay' and now is None: raise ValueError('replay requires explicit as-of clock')
    now = datetime.now(timezone.utc) if now is None else now
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() != timezone.utc.utcoffset(now):
        raise ValueError('validation now must be timezone-aware UTC')
    # Frozen types alone are not authority: catch manually substituted snapshots.
    if parse_profiles(snapshot_mapping(snapshot)) != snapshot: return ('profile snapshot integrity mismatch',)
    max_age = integer(policy.max_age_seconds, 'max_age_seconds', minimum=1)
    allowed = set(policy.allowed_evidence_classes)
    if not allowed or not allowed <= EVIDENCE_CLASSES: raise ValueError('unsupported allowed evidence classes')
    reasons = []
    for group, _, key in _GROUPS:
        attr = {'hosts':'host_ids','compute_units':'compute_ids','memory_resources':'memory_ids','links':'link_ids','runtime_capabilities':'runtime_ids'}[group]
        if {getattr(r,key) for r in getattr(snapshot,group)} != set(getattr(subject,attr)):
            label = {'compute_units':'compute','runtime_capabilities':'runtime'}.get(group,group)
            reasons.append(f'{label} profile coverage mismatch')
    context = _dependency_context(snapshot)
    for key, value in subject.dependencies:
        if key in context and context[key] != value: reasons.append(f'dependency mismatch: {key}')
        else: context[key] = value
    required = {}
    def hostkeys(host): return {f'host:{host}:boot_epoch', f'host:{host}:topology_epoch'}
    for host in snapshot.hosts: required[host.evidence_id] = hostkeys(host.host_id)
    for memory in snapshot.memory_resources:
        required[memory.evidence_id] = hostkeys(memory.host_id) | {f'memory:{memory.memory_id}:physical_id'}
    for cu in snapshot.compute_units:
        required[cu.evidence_id] = hostkeys(cu.host_id) | {f'compute:{cu.compute_id}:physical_id'} | {f'memory:{mid}:physical_id' for mid in cu.memory_ids}
    for runtime in snapshot.runtime_capabilities:
        required[runtime.evidence_id] = hostkeys(runtime.host_id) | {f'compute:{runtime.compute_id}:physical_id'} | {f'runtime:{runtime.runtime_id}:{k}' for k in ('source_revision','build_id','binary_sha256','driver','backend','route')} | {'model:source_id','model:revision','model:representation','workload:digest'}
    link_evidence = {link.evidence_id for link in snapshot.links}
    for link in snapshot.links:
        required[link.evidence_id] = hostkeys(link.source_host_id) | hostkeys(link.target_host_id) | {f'link:{link.link_id}:path',f'link:{link.link_id}:protocol'}
    for evidence in snapshot.evidence:
        eid = evidence.evidence_id
        observed, expires = utc_timestamp(evidence.observed_at), utc_timestamp(evidence.expires_at)
        if observed > now: reasons.append(f'future evidence: {eid}')
        if expires <= now: reasons.append(f'expired evidence: {eid}')
        if (now-observed).total_seconds() > max_age: reasons.append(f'stale evidence: {eid}')
        if evidence.evidence_class == 'unknown' or evidence.evidence_class not in allowed:
            reasons.append(f'evidence class not admitted: {eid} ({evidence.evidence_class})')
        if eid in link_evidence and evidence.evidence_class != 'measured': reasons.append(f'link requires measured evidence: {eid}')
        if subject.mode == 'live' and evidence.source_scope != 'live': reasons.append(f'non-live evidence: {eid} ({evidence.source_scope})')
        actual = dict(evidence.dependencies)
        for key in sorted(required[eid]):
            if key not in context or actual.get(key) != context[key]: reasons.append(f'dependency mismatch: {key} in {eid}')
        for key, value in evidence.dependencies:
            if key not in context: reasons.append(f'unknown dependency: {key} in {eid}')
            elif context[key] != value and key not in required[eid]: reasons.append(f'dependency mismatch: {key} in {eid}')
    return tuple(reasons)


__all__ = ['EvidenceRef', 'ResourceSnapshot', 'HostProfile', 'ComputeProfile', 'MemoryProfile',
           'LinkProfile', 'RuntimeCapability', 'ProfileSubject', 'FrozenMapping', 'freeze', 'thaw',
           'canonical', 'sha256', 'snapshot_mapping', 'parse_profiles', 'validate_profiles']

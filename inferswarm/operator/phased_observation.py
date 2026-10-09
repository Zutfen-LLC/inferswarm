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
from typing import Any, Mapping

from .bindings import TransportReply
from .profiles import FrozenMapping, canonical, integer, keys, thaw

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
    """Reserved structural receipt, not authority; no reconciler creates one yet."""
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


class IncompleteReconciliation(ValueError):
    """The parser-only implementation cannot issue admission or acceptance."""


def reconcile_static(plan, observations, source_receipts, *, mode='live', clock=None):
    """Fail closed until the full inventory/source/identity/resource gate exists."""
    raise IncompleteReconciliation('static incomplete reconciliation: unsupported admission')


def reconcile_dynamic(plan, static_receipt, observations, request_identity, *, mode='live', clock=None):
    """Fail closed until complete same-request graph/state/copy/output proof exists."""
    raise IncompleteReconciliation('dynamic incomplete reconciliation: unsupported acceptance')


__all__ = ['BUILD_SCHEMA', 'RECEIPT_SCHEMA', 'NATIVE_STREAM_SCHEMA',
           'NativeBuildIdentity', 'RequestIdentity', 'ParsedObservation', 'PhaseReceipt',
           'IncompleteReconciliation', 'parse_build_manifest', 'native_build_matches',
           'require_native_build_match', 'parse_observation', 'reconcile_static', 'reconcile_dynamic']

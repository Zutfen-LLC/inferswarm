"""Finite #311 ordinary-startup connection to stopped-worker preparation.

No acquisition or loader implementation lives here. Preparation remains the
existing #99/#101 adapter; normal startup authenticates its exact durable state.
"""
from copy import deepcopy
import json
from pathlib import Path
import sys

CONTRACT = 'coordinator-full-source/participant-assigned-rpc-backing/1'
ROOT = Path(__file__).resolve().parents[2]
IDENTITIES = ROOT/'tools/native-cache/operator-build-identities.json'

def identities():
    return json.loads(IDENTITIES.read_text())

# The reviewed CPU pair keeps its exact historical keys ('client', 'remote').
# The historical table has no CUDA worker. A separately selected Step A pair
# below carries its own CPU client AND CUDA worker; it never replaces these
# historical rows or promotes a receipt supplied by a caller.
CPU_BACKEND = 'cpu'
CUDA_BACKEND = 'cuda'
ROLE_BACKENDS = (('remote', (CPU_BACKEND, CUDA_BACKEND)), ('client', (CPU_BACKEND,)))
HISTORICAL_BUILD_PAIR = 'historical-cpu'
STEP_A_BUILD_PAIR = 'step-a-cpu05-cuda03'
STEP_A_MANIFESTS = ROOT/'tools/native-cache/step-a-build-pair'
OPTIMIZED_BUILD_PAIR = 'optimized-cpu05-cuda03'
HOT_BUILD_PAIR = 'hot-experts-candidate-cpu05-cuda03'
# Intentionally absent until a real candidate is built and separately reviewed.
# Receipt generation never writes this authority path.
HOT_CPU_MANIFEST = ROOT/'tools/native-hot-experts/reviewed-cpu05-llama-server.build-manifest.json'


def hot_cpu_identities():
    from .phased_observation import parse_build_manifest
    try:
        candidate = parse_build_manifest(json.loads(HOT_CPU_MANIFEST.read_text()))
    except FileNotFoundError as exc:
        raise ValueError('hot-expert candidate not reviewed; build receipt is not promotion') from exc
    accepted = optimized_cpu_identities()
    old = accepted['client']
    if (candidate.base_revision != old.base_revision or candidate.base_tree != old.base_tree
            or candidate.protocol != old.protocol or candidate.build_options != old.build_options
            or any('ggml-cuda' in name for name, _ in candidate.backend_libraries)):
        raise ValueError('hot-expert candidate CPU composition/options mismatch')
    return dict(client=candidate, remote=accepted['remote'])

# Additive reviewed candidate identity; historical pairs remain unchanged.
# No caller/config path or supplied hash can populate this finite authority.
OPTIMIZED_CPU_MANIFEST = ROOT/'tools/native-cache/optimized-cpu-build-pair/cpu05-llama-server.build-manifest.json'


def optimized_cpu_identities():
    """One additive CPU successor, always paired with the unchanged Step A CUDA worker."""
    from .phased_observation import parse_build_manifest
    pair = step_a_identities()
    try:
        candidate = parse_build_manifest(json.loads(OPTIMIZED_CPU_MANIFEST.read_text()))
    except FileNotFoundError as exc:
        raise ValueError('selective backing unreviewed optimized CPU build identity') from exc
    expected = tuple(o.replace('=-O0 -g0', '=-O3 -g0') for o in pair['client'].build_options)
    expected += ('-DCMAKE_EXPORT_COMPILE_COMMANDS=ON',)
    if (candidate.build_options != expected
            or candidate.patch_sha256 != pair['client'].patch_sha256
            or any('ggml-cuda' in name for name, _ in candidate.backend_libraries)):
        raise ValueError('selective backing optimized CPU options/patch/backend mismatch')
    return dict(client=candidate, remote=pair['remote'])


def step_a_identities():
    """The complete, finite Step A pair; never import caller-supplied receipts."""
    from .phased_observation import parse_build_manifest
    try:
        pair = {role: parse_build_manifest(json.loads((STEP_A_MANIFESTS/name).read_text()))
                for role, name in (('client', 'cpu05-llama-server.build-manifest.json'),
                                   ('remote', 'cuda03-ggml-rpc-server.build-manifest.json'))}
    except FileNotFoundError as exc:
        raise ValueError('selective backing incomplete Step A build pair') from exc
    for role, backend in (('client', CPU_BACKEND), ('remote', CUDA_BACKEND)):
        identity = pair[role]
        if ('-DGGML_CUDA='+('ON' if backend==CUDA_BACKEND else 'OFF')) not in identity.build_options:
            raise ValueError('selective backing wrong backend in Step A build pair: '+role)
        if any('ggml-cuda' in name for name, _ in identity.backend_libraries) != (backend==CUDA_BACKEND):
            raise ValueError('selective backing wrong library backend in Step A build pair: '+role)
    return pair

def role_key(role, backend=CPU_BACKEND):
    if backend not in (CPU_BACKEND, CUDA_BACKEND):
        raise ValueError('unsupported native build backend: '+str(backend))
    backends = next((b for r,b in ROLE_BACKENDS if r==role), None)
    if backends is None or backend not in backends:
        raise ValueError('no supported native build backend '+str(backend)+' for role: '+str(role))
    return role if backend==CPU_BACKEND else role+'-'+backend

def role_identity(role, backend=CPU_BACKEND, *, build_pair=HISTORICAL_BUILD_PAIR):
    """Selected finite build identity; CPU hashes never answer for CUDA.

    An absent backend-qualified entry refuses: a missing, unreviewed or
    mismatched CUDA identity must stop selective admission, and caller-supplied
    executable hashes are never treated as approval (callers compare against
    the value returned here instead). A row offered under the CUDA key must
    itself be a CUDA build (CUDA backend option plus a ggml-cuda library in
    the closure), so an accepted CPU row is never reinterpreted as one.
    """
    from .phased_observation import parse_build_manifest
    key = role_key(role, backend)
    if build_pair == HOT_BUILD_PAIR:
        pair = hot_cpu_identities()
        if backend != (CPU_BACKEND if role == 'client' else CUDA_BACKEND):
            raise ValueError('wrong backend for hot-expert candidate build pair')
        return pair[role]
    if build_pair == OPTIMIZED_BUILD_PAIR:
        pair = optimized_cpu_identities()  # Missing CPU review refuses BOTH roles.
        if backend != (CPU_BACKEND if role=='client' else CUDA_BACKEND):
            raise ValueError('selective backing wrong backend for optimized CPU build pair: '+role)
        return pair[role]
    if build_pair == STEP_A_BUILD_PAIR:
        pair = step_a_identities()  # Load BOTH roles, even when collecting just one.
        if backend != (CPU_BACKEND if role=='client' else CUDA_BACKEND):
            raise ValueError('selective backing wrong backend for Step A build pair: '+role)
        return pair[role]
    if build_pair != HISTORICAL_BUILD_PAIR:
        raise ValueError('unknown selective backing build pair: '+str(build_pair))
    rows = identities()['roles']
    if key not in rows:
        raise ValueError('selective backing unreviewed per-role runtime identity: '
            'no accepted '+backend+' build for role '+role)
    identity = parse_build_manifest(rows[key]['identity'])
    if backend == CUDA_BACKEND:
        cuda_option = any(option == '-DGGML_CUDA=ON' or option.startswith('-DGGML_CUDA=ON') for option in identity.build_options)
        cuda_library = any('ggml-cuda' in name for name, _ in identity.backend_libraries)
        if not (cuda_option and cuda_library):
            raise ValueError('selective backing identity for '+key+' is not a reviewed CUDA build')
    return identity

def project_payload(payload, options):
    """Reuse the merged projector; complete GGUF rows here are provenance only."""
    from .source import validate_q8_payload
    if str(ROOT/'scripts') not in sys.path: sys.path.insert(0, str(ROOT/'scripts'))
    from issue311_native_backing import project_q8_preparation, _runtime_contract
    old = deepcopy(payload)
    old['source_contract'] = 'full-source-both-hosts/1'
    remote = next(p for p in old['participants'] if p['role']=='remote')
    remote['backing'] = [dict(memory_id=options['memory_id'],member=n,sha256=h,size_bytes=s)
                         for n,h,s in old['model']['members']]
    validate_q8_payload(old)
    projection = project_q8_preparation(old,epoch=options['epoch'],runtime=_runtime_contract(remote['runtime_sha256']))
    payload['prepared_metadata'] = projection['metadata']
    payload['backing_budget'] = {k:options[k] for k in ('limit_bytes','min_free_bytes','reserve_bytes')}
    return payload

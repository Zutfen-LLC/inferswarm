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
# A one-GPU selective pair needs a separately reviewed CUDA worker build; its
# accepted identity lives under the backend-qualified key below. The key is
# deliberately absent until a maintainer reviews a real hardware build receipt:
# nothing here invents, derives or promotes one automatically, and a candidate
# build receipt is never itself an approved runtime.
CPU_BACKEND = 'cpu'
CUDA_BACKEND = 'cuda'
ROLE_BACKENDS = (('remote', (CPU_BACKEND, CUDA_BACKEND)), ('client', (CPU_BACKEND,)))

def role_key(role, backend=CPU_BACKEND):
    if backend not in (CPU_BACKEND, CUDA_BACKEND):
        raise ValueError('unsupported native build backend: '+str(backend))
    backends = next((b for r,b in ROLE_BACKENDS if r==role), None)
    if backends is None or backend not in backends:
        raise ValueError('no supported native build backend '+str(backend)+' for role: '+str(role))
    return role if backend==CPU_BACKEND else role+'-'+backend

def role_identity(role, backend=CPU_BACKEND):
    """Accepted per-role build identity; CPU hashes never answer for CUDA.

    An absent backend-qualified entry refuses: a missing, unreviewed or
    mismatched CUDA identity must stop selective admission, and caller-supplied
    executable hashes are never treated as approval (callers compare against
    the value returned here instead). A row offered under the CUDA key must
    itself be a CUDA build (CUDA backend option plus a ggml-cuda library in
    the closure), so an accepted CPU row is never reinterpreted as one.
    """
    from .phased_observation import parse_build_manifest
    key = role_key(role, backend)
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

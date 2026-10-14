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

def role_identity(role):
    from .phased_observation import parse_build_manifest
    return parse_build_manifest(identities()['roles'][role]['identity'])

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

"""Issue #314 opt-in native expert-demand capture under the guarded session.

The smallest additive path: an explicit ``demand`` block in the frozen
q8-two-cuda-session/1 JSON turns ONE measured request into a dedicated,
separately reviewed demand-client invocation. Everything else — both owned
CUDA workers, 41/45 placement, selective backing, source digests, admission,
caps, deadlines, sequential handling, cleanup and evidence retention — is
reused unchanged from the existing runner. Default-off behavior is identical.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re

MAX_PROMPT_BYTES = 65536
MAX_DECODE_STEPS = 256
MAX_ROWS = 100000
EXPORT_BYTE_BOUND = 16 * 1024 * 1024
DIGEST_RE = re.compile(r'[0-9a-f]{64}')
# The fixed two-gpu 41/45 native lowering of the accepted operator path.
FIXED_OPTIONS = {
    'gpu_layers': 8, 'tensor_split': (4, 4), 'split_mode': 'layer',
    'fit': 'off', 'lazy_mode': 'on', 'load_mode': 'none',
    'kv_offload': True, 'op_offload': False, 'flash_attention': 'off',
    'kv_unified': False, 'cache_type_k': 'f16', 'cache_type_v': 'f16',
}
DEMAND_FIELDS = ('client_manifest_path', 'client_executable_path', 'client_sha256',
                 'max_rows', 'model_sha256', 'native_build_sha256')


@dataclass(frozen=True)
class DemandProfileRequest:
    """One explicitly requested capture; never inferred from a bare request."""
    client_manifest_path: str
    client_executable_path: str
    client_sha256: str
    max_rows: int
    model_sha256: str
    native_build_sha256: str
    request_index: int          # 1-based index into the frozen session
    decode_steps: int
    prompt: str

    @property
    def prompt_sha256(self):
        return hashlib.sha256(self.prompt.encode('utf-8')).hexdigest()

    def workload_sha256(self, session_digest):
        """Structural workload identity: frozen session order + this prompt."""
        return hashlib.sha256(json.dumps(
            [session_digest, self.request_index, self.prompt_sha256],
            separators=(',', ':')).encode()).hexdigest()


def validate_demand(raw, session, *, client_manifest_body=None):
    """Validate the opt-in block; returns None when absent (default off).

    ``raw`` is the session JSON dict (already structurally validated). A
    ``demand`` key may appear only on exactly one MEASURED request; warmups
    can never carry it. Caller-supplied hashes never bypass review: when the
    reviewed client manifest body is available it must match the declared
    executable digest exactly.
    """
    if 'demand' not in raw:
        return None
    demand = raw['demand']
    if not isinstance(demand, dict) or set(demand) != set(DEMAND_FIELDS) | {
            'request_index', 'decode_steps', 'prompt'}:
        raise ValueError('demand capture block fields must be exact')
    for key in ('client_manifest_path', 'client_executable_path'):
        value = demand[key]
        if (not isinstance(value, str) or not value.startswith('/')
                or '..' in value.split('/')):
            raise ValueError('demand capture requires absolute reviewed client paths')
    for key in ('client_sha256', 'model_sha256', 'native_build_sha256'):
        if not isinstance(demand[key], str) or not DIGEST_RE.fullmatch(demand[key]):
            raise ValueError('demand capture digest must be lowercase SHA-256')
    for key, bound in (('max_rows', MAX_ROWS), ('decode_steps', MAX_DECODE_STEPS)):
        value = demand[key]
        if type(value) is not int or not 1 <= value <= bound:
            raise ValueError(f'demand capture {key} must be an integer in 1..{bound}')
    index = demand['request_index']
    requests = session.payload()['requests']
    if type(index) is not int or not 1 <= index <= len(requests):
        raise ValueError('demand capture request_index must name a frozen session request')
    if requests[index - 1]['warmup']:
        raise ValueError('demand capture cannot bind a warmup request')
    prompt = demand['prompt']
    if (not isinstance(prompt, str) or not prompt
            or len(prompt.encode('utf-8')) > MAX_PROMPT_BYTES):
        raise ValueError('demand capture prompt must be nonempty bounded text')
    # The capture prompt IS the measured request prompt: one load, one profile.
    if prompt != requests[index - 1]['body']['prompt']:
        raise ValueError('demand capture prompt must equal its measured request prompt')
    if client_manifest_body is not None:
        declared = client_manifest_body.get('executable_sha256')
        if declared != demand['client_sha256']:
            raise ValueError('demand client digest does not match its reviewed manifest')
    return DemandProfileRequest(
        client_manifest_path=demand['client_manifest_path'],
        client_executable_path=demand['client_executable_path'],
        client_sha256=demand['client_sha256'], max_rows=demand['max_rows'],
        model_sha256=demand['model_sha256'],
        native_build_sha256=demand['native_build_sha256'],
        request_index=index, decode_steps=demand['decode_steps'], prompt=prompt)


def demand_client_argv(profile, *, rpc_endpoints, model_path, file_type,
                       workload_sha256, model_source, model_revision,
                       representation, context, batch, microbatch, threads):
    """Exact flag-for-flag parity with the guarded 41/45 client invocation."""
    endpoints = ','.join(rpc_endpoints)
    return (
        profile.client_executable_path,
        '--model', model_path,
        '--output', '__demand_profile__',   # replaced by the runner (fresh path)
        '--prompt-file', '__demand_prompt__',  # replaced by the runner (fresh file)
        '--max-rows', str(profile.max_rows),
        '--decode-steps', str(profile.decode_steps),
        '--model-sha256', profile.model_sha256,
        '--native-build-sha256', profile.native_build_sha256,
        '--workload-sha256', workload_sha256,
        '--cohort', 'profiling',
        '--workload-label', 'operator-session-request-%d' % profile.request_index,
        '--backend', 'cpu',
        '--file-type', str(file_type),
        '--model-source', model_source,
        '--model-revision', model_revision,
        '--representation', representation,
        '--rpc-endpoints', endpoints,
        '--devices', 'RPC0,RPC1',
        '--gpu-layers', str(FIXED_OPTIONS['gpu_layers']),
        '--tensor-split', '4,4',
        '--split-mode', FIXED_OPTIONS['split_mode'],
        '--fit', FIXED_OPTIONS['fit'],
        '--lazy-mode', FIXED_OPTIONS['lazy_mode'],
        '--load-mode', FIXED_OPTIONS['load_mode'],
        '--kv-offload', 'on',
        '--no-op-offload', 'on',
        '--cache-type-k', FIXED_OPTIONS['cache_type_k'],
        '--cache-type-v', FIXED_OPTIONS['cache_type_v'],
        '--flash-attn', FIXED_OPTIONS['flash_attention'],
        '--no-kv-unified', 'on',
        '--ctx-size', str(context),
        '--batch-size', str(batch),
        '--ubatch-size', str(microbatch),
        '--parallel', '1',
        '--threads', str(threads),
    )

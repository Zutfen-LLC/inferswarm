"""Finite #314 session opt-in; ordinary ownership and supervision stay intact."""
from dataclasses import dataclass
from pathlib import Path
import re

from .assigned_backing import HOT_BUILD_PAIR


@dataclass(frozen=True)
class HotRequest:
    enabled: bool
    prepared_path: str
    prepared_sha256: str


def validate_hot_request(raw):
    if 'hot_experts' not in raw:
        return None
    if 'demand' in raw:
        raise ValueError('hot-expert comparison cannot run a profiling capture')
    value = raw['hot_experts']
    if not isinstance(value, dict) or set(value) != {'enabled', 'prepared_path', 'prepared_sha256'}:
        raise ValueError('hot_experts fields must be exact')
    if type(value['enabled']) is not bool:
        raise ValueError('hot_experts enabled must be boolean')
    path = value['prepared_path']
    if not isinstance(path, str) or not Path(path).is_absolute() or '..' in Path(path).parts:
        raise ValueError('absolute prepared hot-expert path required')
    sha = value['prepared_sha256']
    if not isinstance(sha, str) or re.fullmatch('[0-9a-f]{64}', sha) is None:
        raise ValueError('hot_experts requires SHA-256')
    return HotRequest(value['enabled'], path, sha)


def merge_assigned(original, derived):
    """Add complete derived identities without replacing any ordinary bank."""
    if len(original.encode()) + len(derived.encode()) > 65536:
        raise ValueError('combined assigned guard exceeds staging bound')
    names = set()
    for line in (original + '\n' + derived).splitlines():
        if not line.strip():
            continue
        fields = line.split()
        if len(fields) != 8 or re.fullmatch('[0-9a-f]{64}', fields[-1]) is None:
            raise ValueError('malformed assigned guard')
        if fields[0] in names:
            raise ValueError('duplicate immutable destination')
        names.add(fields[0])
    return original.rstrip('\n') + '\n' + derived.rstrip('\n') + '\n'


def validate_hot_plan(plan, prepared):
    from .profiles import thaw
    options = thaw(plan.strategy_options)
    if (plan.selection != 'two-gpu' or options.get('build_pair') != HOT_BUILD_PAIR
            or options.get('placement_variant') is not None):
        raise ValueError('hot-expert session requires reviewed candidate and unchanged 41/45 placement')
    spec = prepared.native_spec()
    if spec['layer'] != 7 or spec['expert_ids'] != [54, 74, 136, 290, 394]:
        raise ValueError('guarded experiment requires the frozen layer-7 H5 list')
    if spec['rpc_backend'] != 'RPC[' + options['rpc_endpoints'][0] + ']':
        raise ValueError('hot experts must reuse the existing GPU0 endpoint')


def load_hot_prepared(request):
    from .hot_experts import load_prepared
    with Path(request.prepared_path).open('rb') as stream:
        data = stream.read(65537)
    if len(data) > 65536:
        raise ValueError('prepared hot-expert record exceeds bound')
    return load_prepared(data, expected_sha256=request.prepared_sha256)


def stage_hot_experts(runner, guard, plan, sources, client, remote):
    """Only add derived upload identities; ordinary assignment checks already ran."""
    import base64
    import hashlib
    from .hot_experts import validate_prepared_sources
    from .profiles import thaw
    from .source import q8_source_payload
    request = guard.hot_request
    prepared = guard.hot_prepared
    validate_hot_plan(plan, prepared)
    metadata = q8_source_payload(plan)['metadata']
    validate_prepared_sources(prepared, metadata, sources[client.participant_id])
    record = dict(enabled=request.enabled, prepared_sha256=request.prepared_sha256,
                  report=prepared.report(), setup_weight_uploads_expected=3 if request.enabled else 0,
                  persistent_hash_hits_expected=False)
    if not request.enabled:
        return None, record
    guard.checkpoint()
    guard.phase = 'hot-preparation'
    def stage(part, name, data):
        path = str(Path(runner.leases.invocation_dir(part.execution_address))/name)
        runner.leases._call(part.execution_address, 'write', path=path,
                           data=base64.b64encode(data).decode('ascii'))
        actual = guard._run(part, ['python3', '-c',
            'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read(65537)).hexdigest())', path]).strip()
        if actual != hashlib.sha256(data).hexdigest():
            raise ValueError('staged hot-expert file readback mismatch')
        return path
    native_path = stage(client, 'hot-experts.json', prepared.native_spec_bytes)
    bid = thaw(plan.strategy_options)['bindings']['remote_gpu0']
    for part, key in ((client, None), (remote, bid)):
        receipt = sources[part.participant_id]
        original_path = (receipt['assigned_guard_path'] if key is None
                         else receipt['assigned_guard_paths'][key])
        original = guard._run(part, ['python3', '-c',
            'import sys; print(open(sys.argv[1]).read(65537),end="")', original_path])
        combined = merge_assigned(original, prepared.assigned_guard.decode('ascii')).encode('ascii')
        path = stage(part, 'hot-assigned.txt', combined)
        if key is None:
            receipt['assigned_guard_path'] = path
        else:
            receipt['assigned_guard_paths'][key] = path
    guard.checkpoint()
    return native_path, record


def comparison_helpers():
    import importlib.util
    path = Path(__file__).resolve().parents[2]/'tools/native-hot-experts/comparison.py'
    spec = importlib.util.spec_from_file_location('is314_comparison', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tokenize_hot_session(runner, guard, plan, base, client):
    """Actual admitted, already-loaded tokenizer; no extra model or inference."""
    import hashlib
    from .profiles import canonical
    from .source import q8_source_payload
    helper = comparison_helpers()
    session = guard.session.payload()
    helper.validate_frozen_session(session)
    model_sha = hashlib.sha256(canonical(q8_source_payload(plan)['model'])).hexdigest()
    if model_sha != helper.MODEL_SHA256:
        raise ValueError('frozen comparison model identity mismatch')
    receipt = dict(schema='is314-tokenizer-receipt/1', model_sha256=model_sha,
        session_sha256=guard.session.digest, tokenizer=dict(
            source_revision=helper.NATIVE_SOURCE, executable_sha256=client.runtime_sha256,
            add_special=True, parse_special=True, actual_model_input=True), requests=[])
    guard.phase = 'tokenization'
    for index, request in enumerate(session['requests'], 1):
        guard.checkpoint()
        response = runner.http.post(base+'/tokenize', dict(content=request['body']['prompt'],
            add_special=True, parse_special=True, with_pieces=False), timeout=guard.request_timeout_seconds())
        receipt['requests'].append(dict(index=index,
            body_sha256=hashlib.sha256(canonical(request['body'])).hexdigest(),
            token_ids=response.get('tokens')))
    if runner.evidence is None or not runner.evidence.save_session_json('actual-tokenizer.json', receipt):
        raise RuntimeError('actual tokenizer receipt retention failed')
    helper.validate_tokenizer_receipt(receipt, session)
    guard.checkpoint()
    return receipt

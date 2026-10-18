#!/usr/bin/env python3
"""Authenticate retained #314 demand evidence offline; never load model weights."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from inferswarm.operator.profiles import canonical
from inferswarm.operator.q8_demand import validate_demand
from inferswarm.operator.q8_session import validate_session

BUNDLE_SHA256 = '5d52bf5badee1cdbf450d9c5ba59a1089c85ac45f0c386574cf0a7500b3bf42f'
MODEL_SHA256 = 'a13849d1ad98cff76713f7cd0f650be1217402d79588327815025bd7d42b48d1'
H5 = [54, 74, 136, 290, 394]
REDUCER = ROOT / 'tools/native-moe-overlap/summarize_demand.py'
METADATA = ROOT / 'tests/fixtures/issue299/q8-metadata.json'


def digest(blob):
    return hashlib.sha256(blob).hexdigest()


def verify_reduction(raw, expected, stored_summary):
    """Call the unchanged production reducer, then require complete retained data."""
    spec = importlib.util.spec_from_file_location('is314_production_reducer', REDUCER)
    if spec is None or spec.loader is None:
        raise ValueError('production reducer unavailable')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.summarize(raw, expected)
    coverage = result['coverage']
    if (not coverage['complete'] or coverage['retained_rows'] != 1584
            or coverage['observed_rows'] != 1584 or coverage['dropped_rows'] != 0
            or (raw['layers'], raw['expert_count'], raw['top_k'], raw['steps']) != (48,512,10,33)):
        raise ValueError('require complete 1584-row capture with zero dropped rows')
    if stored_summary is not None and canonical(result) != canonical(stored_summary):
        raise ValueError('retained reducer output does not equal actual raw reduction')
    return result


def inspect_bundle(path):
    """Return small deterministic public provenance; read members without extraction."""
    path = Path(path)
    with path.open('rb') as source:
        actual = hashlib.file_digest(source, 'sha256').hexdigest()
    if actual != BUNDLE_SHA256:
        raise ValueError('private bundle SHA-256 mismatch')
    blobs, members = {}, {}
    with tarfile.open(path, 'r:gz') as archive:
        for member in archive:
            name = PurePosixPath(member.name)
            if (not member.isfile() or name.is_absolute() or '..' in name.parts
                    or member.name in members or not 0 <= member.size <= 16 << 20):
                raise ValueError('invalid, duplicate or oversized evidence member')
            source = archive.extractfile(member)
            if source is None:
                raise ValueError('regular evidence member unavailable')
            blob = source.read()
            if len(blob) != member.size:
                raise ValueError('truncated evidence member')
            members[member.name] = {'size_bytes': len(blob), 'sha256': digest(blob)}
            blobs[member.name] = blob
    manifest = json.loads(blobs['BUNDLE-MANIFEST.json'])
    listed = {}
    for entry in manifest['files']:
        if entry['path'] in listed:
            raise ValueError('duplicate bundle manifest member')
        listed[entry['path']] = {'size_bytes': entry['size'], 'sha256': entry['sha256']}
    if listed != {k:v for k,v in members.items() if k != 'BUNDLE-MANIFEST.json'}:
        raise ValueError('bundle member ledger mismatch')
    if blobs['source/tools/native-moe-overlap/summarize_demand.py'] != REDUCER.read_bytes():
        raise ValueError('production reducer drift from retained source')
    raw = json.loads(blobs['evidence/demand/demand-profile.json'])
    if raw != json.loads(blobs['evidence/demand-export.json']):
        raise ValueError('raw/controller capture data mismatch')
    expected = json.loads(blobs['reducer-expected-identity.json'])
    summary = verify_reduction(raw, expected, json.loads(blobs['demand-summary.json']))
    config = json.loads(blobs['config.json'])
    model = config['model']
    metadata = json.loads(METADATA.read_bytes())
    model_members = {m['name']: (m['sha256'], m['size_bytes']) for m in model['members']}
    if model_members != {h[0]: (h[5], h[4]) for h in metadata['header_identities']}:
        raise ValueError('retained model does not bind checked-in metadata members')
    if (digest(canonical(model)) != MODEL_SHA256 or expected['model_sha256'] != MODEL_SHA256
            or expected['model_source'] != model['source_id']
            or expected['model_revision'] != model['revision']
            or expected['representation'] != model['representation']):
        raise ValueError('model identity object mismatch')
    raw_session = json.loads(blobs['session.json'])
    if raw_session != json.loads(blobs['evidence/frozen-session.json']):
        raise ValueError('retained frozen session mismatch')
    session = validate_session(raw_session)
    profile = validate_demand(raw_session, session,
                             client_manifest_body=json.loads(blobs['reviewed-external-manifest.json']))
    if profile is None:
        raise ValueError('retained demand profile binding missing')
    if (profile.workload_sha256(session.digest) != expected['workload_sha256']
            or profile.model_sha256 != MODEL_SHA256
            or profile.native_build_sha256 != expected['native_build_sha256']):
        raise ValueError('workload/model/build identity mismatch')
    requests = []
    for index, row in enumerate(raw_session['requests'], 1):
        started = json.loads(blobs[f'evidence/request-{index:02d}-started.json'])
        body_digest = digest(canonical(row['body']))
        if started['body'] != row['body'] or started['request_sha256'] != body_digest:
            raise ValueError('retained request bytes/body digest mismatch')
        requests.append({'index': index, 'warmup': row['warmup'],
                         'body_sha256': body_digest,
                         'prompt_utf8_sha256': digest(row['body']['prompt'].encode('utf-8')),
                         'n_predict': row['body']['n_predict']})
    if blobs['evidence/demand/demand-prompt.txt'] != profile.prompt.encode('utf-8'):
        raise ValueError('raw prompt bytes mismatch')
    decode = summary['phase_demand']['decode']['7']
    prefill = summary['phase_demand']['prefill']['7']
    h5 = [int(k) for k,v in decode['frequency'].items() if v == 32]
    if sorted(h5) != H5 or decode['tokens'] != 32:
        raise ValueError('retained layer-7 H5 identity/count mismatch')
    coverage = {k: v for k,v in summary['coverage'].items()
                if k not in ('retained_token_positions', 'step_meta')}
    return {
        'schema': 'is314-capture-provenance/1',
        'scope': 'retained repetitive ABCD profiling evidence only; not representative demand or performance',
        'bundle': {'basename': path.name, 'sha256': actual, 'size_bytes': path.stat().st_size},
        'members': members, 'model': model,
        'model_sha256': MODEL_SHA256,
        'model_digest_definition': 'SHA-256 canonical source_id/revision/representation/member identity object; not a new model-file read',
        'metadata': {'path': str(METADATA.relative_to(ROOT)), 'sha256': digest(METADATA.read_bytes()),
                     'digest': metadata['metadata_digest']},
        'identity': expected, 'identity_provenance': raw['identity_provenance'],
        'reducer': {'path': str(REDUCER.relative_to(ROOT)), 'sha256': digest(REDUCER.read_bytes()),
                    'reproduced_summary_equal': True,
                    'canonical_summary_sha256': digest(canonical(summary))},
        'coverage': coverage,
        'request_binding': {'session_sha256': session.digest,
                            'raw_session_sha256': members['session.json']['sha256'],
                            'requests': requests, 'profiled_request_index': profile.request_index,
                            'workload_sha256': profile.workload_sha256(session.digest)},
        'h5': {'layer': 7, 'expert_ids': H5, 'decode_positions': 32,
               'frequency_each': 32, 'decode_selected_slots': sum(decode['frequency'][str(i)] for i in H5),
               'decode_total_slots': decode['tokens'] * raw['top_k'],
               'decode_distinct_experts': len(decode['frequency']),
               'prefill_distinct_experts': len(prefill['frequency'])},
        'historical_limitations': {'general_observer': 'REFUSED-DROPPED-EVENTS',
                                   'raw_retention_manifest_complete': False,
                                   'output_accepted': False, 'physical_qualified': False},
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--output', type=Path, help='fresh small provenance JSON; never overwrite evidence')
    parser.add_argument('--check', type=Path, help='require exact canonical reproduction of this provenance')
    args = parser.parse_args(argv)
    try:
        blob = canonical(inspect_bundle(args.bundle)) + b'\n'
        if args.check is not None and args.check.read_bytes() != blob:
            raise ValueError('checked provenance differs from authenticated reproduction')
        if args.output is not None:
            with args.output.open('xb') as output:
                output.write(blob)
        print(json.dumps({'status': 'VERIFIED', 'provenance_sha256': digest(blob),
                          'bundle_sha256': BUNDLE_SHA256}, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, tarfile.TarError) as error:
        parser.exit(1, f'provenance refused: {error}\n')


if __name__ == '__main__':
    raise SystemExit(main())

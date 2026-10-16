"""Reuse complete ordinary CI outcomes through existing Actions authentication.

Only same-tree, complete, disjoint, successful coverage of the current loader
population is eligible. Skipped IDs are executed again in Final CPU Validation;
they are never silently counted as passed. Any lookup uncertainty falls back to
the canonical full suite. Composition reauthenticates all source bytes.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from collections import Counter
from pathlib import Path

import yaml

try:
    from . import ci_unittest as outcomes
except ImportError:
    import ci_unittest as outcomes

ROOT = Path(__file__).resolve().parents[1]
MODE = 'verified_ordinary_ci'
PREFIX = 'ci-outcomes-'
MAX_BYTES = 2 * 1024 * 1024


def schedule(root=ROOT):
    import ci_workflow_parity as parity
    doc = yaml.safe_load((root / '.github/workflows/ci.yml').read_text())
    problems = parity.identity_problems(doc, root=root)
    if problems:
        raise ValueError('workflow identity parity failed: ' + '; '.join(problems))
    return parity.job_executed_ids(doc, root=root)


def suite_configuration(root=ROOT):
    jobs = schedule(root)
    return {'schema': 'suite-config/1', 'tests_dir': 'tests', 'jobs': len(jobs),
            'plan_digest': hashlib.sha256(json.dumps(jobs, sort_keys=True).encode()).hexdigest(),
            'timeout': 7200.0, 'retain_dir': None}


def validate_records(records, *, expected, runtime, tree, run_id, attempt):
    """Require every started identity to have exactly one successful outcome."""
    started, rows = [], []
    for record in records:
        if (record.get('schema') != outcomes.SCHEMA or record.get('ok') is not True
                or record.get('runtime') != runtime or record.get('tree') != tree
                or record.get('run_id') != str(run_id)
                or record.get('attempt') != str(attempt)):
            raise ValueError('outcome identity, environment or success mismatch')
        if not isinstance(record.get('started_unix'), (int, float)) or not isinstance(
                record.get('ended_unix'), (int, float)) or not (
                0 < record['started_unix'] <= record['ended_unix']):
            raise ValueError('invalid outcome timestamps')
        started.extend(record['started_ids'])
        rows.extend(record['outcomes'])
    if Counter(started) != Counter(expected) or len(set(started)) != len(started):
        raise ValueError('incomplete, duplicate or extra started identities')
    if Counter(row[0] for row in rows) != Counter(expected):
        raise ValueError('missing or duplicate terminal outcomes')
    for test_id, state, reason in rows:
        if state not in ('success', 'skip') or (state == 'skip' and not isinstance(reason, str)):
            raise ValueError('unsuccessful or malformed terminal outcome')
    return sorted(row[0] for row in rows if row[1] == 'skip')


def _records(blob, parse):
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        members = archive.infolist()
        if (not members or len(members) > 32
                or len({m.filename for m in members}) != len(members)
                or sum(m.file_size for m in members) > 4 * MAX_BYTES
                or any(m.is_dir() or not m.filename.endswith('.json') for m in members)):
            raise ValueError('invalid outcome archive')
        return [parse(archive.read(member)) for member in members]


def authenticate(api, *, request, current_run_id, pr_number, root=ROOT,
                 pointer=None):
    import hosted_ci_verification as ci
    import final_validation_reuse as reuse
    if pr_number is None:
        raise ValueError('ordinary reuse requires a verified current PR association')
    verifier = ci.HostedCiVerifier(api, ci.CANONICAL_REPOSITORY, pr_number=pr_number)
    verdict = verifier.verify(request.git_commit_sha,
                              pinned_run_id=None if pointer is None else pointer['run_id'])
    if verdict['verdict'] != ci.PASS or not verdict['pr_bound']:
        raise ValueError('ordinary CI not authenticated: ' + verdict['detail'])
    run = verdict['run']
    run_id, attempt = run['id'], run['attempt']
    if run_id >= current_run_id:
        raise ValueError('ordinary source must be earlier than final validation')
    jobs = schedule(root)
    expected_all = [i for ids in jobs.values() for i in ids]
    # Reuse the canonical loader authority, not just workflow count/parity.
    import run_full_cpu_suite as runner
    discovered = runner.ids_for_units(runner.discover_units(root, root / 'tests'))
    if Counter(expected_all) != Counter(discovered):
        raise ValueError('ordinary workflow does not cover the entire canonical population')
    listing = api.list_artifacts(run_id)
    if listing.get('total_count') != len(listing.get('artifacts', [])):
        raise ValueError('incomplete artifact listing')
    tree = outcomes.git_value(root, 'HEAD^{tree}')
    runtime = outcomes.runtime_identity()
    artifacts, skipped, records_all = [], [], []
    for job, expected in sorted(jobs.items()):
        named = [a for a in listing['artifacts'] if a.get('name') == PREFIX + job]
        if len(named) != 1:
            raise ValueError('missing or ambiguous outcomes for ' + job)
        art = named[0]
        bound = art.get('workflow_run', {})
        if (art.get('expired') is not False or bound.get('id') != run_id
                or bound.get('head_sha') != request.git_commit_sha
                or not isinstance(bound.get('repository_id'), int)
                or bound.get('repository_id') != bound.get('head_repository_id')
                or not isinstance(art.get('size_in_bytes'), int)
                or not 0 < art['size_in_bytes'] <= MAX_BYTES):
            raise ValueError('outcome artifact not bound to authenticated source')
        blob = api.download_artifact(art['id'], MAX_BYTES)
        digest = 'sha256:' + hashlib.sha256(blob).hexdigest()
        if digest != art.get('digest'):
            raise ValueError('outcome artifact digest mismatch')
        records = _records(blob, reuse.parse_strict_json)
        if any(r.get('job') != job for r in records):
            raise ValueError('outcome job identity mismatch')
        skipped.extend(validate_records(records, expected=expected, runtime=runtime,
                                        tree=tree, run_id=run_id, attempt=attempt))
        records_all.extend(records)
        artifacts.append({'id': art['id'], 'digest': digest, 'job': job})
    # Detect a rerun that began while the artifacts were being downloaded.
    after = verifier.verify(request.git_commit_sha, pinned_run_id=run_id)
    if after['verdict'] != ci.PASS or after['run'] != run:
        raise ValueError('ordinary run changed during outcome authentication')
    source = {'run_id': run_id, 'run_attempt': attempt, 'workflow': 'CI',
              'artifacts': artifacts, 'tree': tree, 'skipped_ids': sorted(skipped)}
    if pointer is not None and source != pointer:
        raise ValueError('ordinary decision differs from authenticated source')
    return source, records_all


def lookup(api, *, request, current_run_id, pr_number, root=ROOT):
    import final_validation_reuse as reuse
    try:
        source, _ = authenticate(api, request=request, current_run_id=current_run_id,
                                 pr_number=pr_number, root=root)
        decision = reuse._decision('reuse', 'complete authenticated ordinary CI',
                                   request.git_commit_sha)
        decision.update(source=source, source_kind=MODE)
        return decision
    except Exception as error:
        return reuse._decision('run', 'ordinary reuse unavailable: ' + str(error),
                               request.git_commit_sha)


def confirm_skips(ids, root=ROOT):
    """Physically check only the source's skipped tests in the final environment."""
    if not ids:
        return
    with tempfile.TemporaryDirectory(prefix='ci-skip-confirm-') as temporary:
        environment = dict(os.environ, CI_OUTCOMES_DIR=temporary)
        process = subprocess.run([sys.executable, '-m', 'scripts.ci_unittest', *ids, '-v'],
                                 cwd=root, env=environment, timeout=1800)
        if process.returncode:
            raise ValueError('ordinary CI skip confirmation failed')
        records = [json.loads(p.read_text()) for p in Path(temporary).glob('*.json')]
        validate_records(records, expected=ids, runtime=outcomes.runtime_identity(),
                         tree=outcomes.git_value(root, 'HEAD^{tree}'),
                         run_id=os.environ['GITHUB_RUN_ID'],
                         attempt=os.environ['GITHUB_RUN_ATTEMPT'])


def compose(decision, *, api, request, current_run_id, attempt, pr_number,
            dispatch_sha, root=ROOT):
    import issue213_gate_orchestration as gate
    if (decision.get('action') != 'reuse' or decision.get('source_kind') != MODE
            or decision.get('expected_sha') != request.git_commit_sha
            or dispatch_sha != request.git_commit_sha):
        raise ValueError('ordinary reuse decision is not bound to the final head')
    source, records = authenticate(api, request=request, current_run_id=current_run_id,
                                  pr_number=pr_number, root=root,
                                  pointer=decision.get('source'))
    confirm_skips(source['skipped_ids'], root)
    # Record the actual ordinary schedule. It is an explicitly allowed alternate
    # schedule, never claimed to be execution of the canonical subprocess plan.
    suite = dict(request.suite, suite_config=suite_configuration(root))
    receipt = gate.SuiteReceipt(request.git_commit_sha, suite, request.environment,
                                'PASS', suite['count'],
                                min(r['started_unix'] for r in records),
                                max(r['ended_unix'] for r in records)).to_dict()
    execution = {'mode': MODE, 'dispatch_sha': dispatch_sha,
                 'reuse_contract': gate.FINAL_VALIDATION_REUSE_CONTRACT,
                 'ordinary_source': source, 'skips_confirmed': True}
    return gate.build_final_validation_receipt(
        request.git_commit_sha, receipt, github_run_id=str(current_run_id),
        github_run_attempt=attempt, pr_number=pr_number,
        finalizer_check=True, project_status_check=True, execution=execution)


def validate_execution(execution, *, git_commit_sha, github_run_id):
    """Keep the existing strict envelope contract for the alternate schedule."""
    import issue213_gate_orchestration as gate
    import final_validation_reuse as reuse
    import re
    def require(condition, message):
        if not condition:
            raise gate.GateOrderingError(message)
    require(set(execution) == {'mode', 'dispatch_sha', 'reuse_contract',
                               'ordinary_source', 'skips_confirmed'},
            'ordinary execution fields mismatch')
    require(execution['dispatch_sha'] == git_commit_sha
            and execution['reuse_contract'] == gate.FINAL_VALIDATION_REUSE_CONTRACT
            and execution['skips_confirmed'] is True,
            'ordinary execution head, contract or skip confirmation mismatch')
    source = execution['ordinary_source']
    require(isinstance(source, dict) and set(source) == {
        'run_id', 'run_attempt', 'workflow', 'artifacts', 'tree', 'skipped_ids'},
        'ordinary source fields mismatch')
    require(type(source['run_id']) is int and source['workflow'] == 'CI'
            and isinstance(source['tree'], str)
            and re.fullmatch('[0-9a-f]{40}', source['tree']),
            'ordinary source identity malformed')
    skipped = source['skipped_ids']
    require(isinstance(skipped, list) and all(isinstance(i, str) and
            re.fullmatch(r'tests\.test_\w+\.\w+\.\w+', i) for i in skipped)
            and skipped == sorted(set(skipped)), 'ordinary skipped identities malformed')
    artifacts = source['artifacts']
    require(isinstance(artifacts, list) and 0 < len(artifacts) <= 100,
            'ordinary source artifacts missing')
    jobs, ids = set(), set()
    for art in artifacts:
        require(isinstance(art, dict) and set(art) == {'id', 'digest', 'job'},
                'ordinary artifact fields mismatch')
        require(isinstance(art['job'], str) and art['job'] not in jobs
                and type(art['id']) is int and art['id'] not in ids,
                'ordinary artifact ownership duplicate or malformed')
        jobs.add(art['job']); ids.add(art['id'])
        # Reuse the existing strict source pointer validation, including
        # digest shape, attempt and no self/forward source references.
        block = gate.execution_block_reused(
            execution['dispatch_sha'], source_run_id=str(source['run_id']),
            source_run_attempt=source['run_attempt'], source_artifact_id=art['id'],
            source_artifact_digest=art['digest'],
            source_envelope_sha256=reuse.canonical_sha256(source), source_workflow='CI')
        gate.validate_execution_block(block, git_commit_sha=git_commit_sha,
                                      github_run_id=github_run_id)

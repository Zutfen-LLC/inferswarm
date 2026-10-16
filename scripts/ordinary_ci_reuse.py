"""Reuse authenticated ordinary CI outcomes through existing Actions authentication.

Only same-tree, disjoint, successful job coverage of the current loader
population is eligible. Uncovered modules execute in Final CPU Validation. Skipped IDs are executed again in Final CPU Validation;
they are never silently counted as passed. Any lookup uncertainty falls back to
the canonical full suite. Composition reauthenticates all source bytes.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
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


def canonical_test_id(workflow_id):
    """Map only the workflow loader's exact ``tests.`` import prefix.

    Per-job started/outcome IDs and skipped IDs retain their original spelling.
    Canonical discovery imports test modules directly from the tests directory.
    """
    match = re.fullmatch(r"tests\.(test_\w+\.\w+\.\w+)", workflow_id)
    if match is None:
        raise ValueError('unexpected workflow test identity: ' + repr(workflow_id))
    return match.group(1)


def schedule(root=ROOT):
    import ci_workflow_parity as parity
    doc = yaml.safe_load((root / '.github/workflows/ci.yml').read_text())
    problems = parity.identity_problems(doc, root=root)
    if problems:
        raise ValueError('workflow identity parity failed: ' + '; '.join(problems))
    return parity.job_executed_ids(doc, root=root)


def suite_configuration(root=ROOT, source=None):
    jobs = schedule(root)
    if source is not None and len(source['artifacts']) < len(jobs):
        jobs = {a['job']: jobs[a['job']] for a in source['artifacts']}
        jobs['final_completion'] = completion_plan(source, root)['fresh_ids']
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
    if Counter(map(canonical_test_id, expected_all)) != Counter(discovered):
        raise ValueError('ordinary workflow does not cover the entire canonical population')
    listing = api.list_artifacts(run_id)
    if listing.get('total_count') != len(listing.get('artifacts', [])):
        raise ValueError('incomplete artifact listing')
    tree = outcomes.git_value(root, 'HEAD^{tree}')
    runtime = outcomes.runtime_identity()
    artifacts, skipped, records_all = [], [], []
    for job, expected in sorted(jobs.items()):
        named = [a for a in listing['artifacts'] if a.get('name') == PREFIX + job]
        if not named:
            continue  # Impact-selected CI did not execute this job.
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
    if not artifacts:
        raise ValueError('no eligible ordinary coverage')
    # Detect a rerun that began while the artifacts were being downloaded.
    after = verifier.verify(request.git_commit_sha, pinned_run_id=run_id)
    if after['verdict'] != ci.PASS or after['run'] != run:
        raise ValueError('ordinary run changed during outcome authentication')
    source = {'run_id': run_id, 'run_attempt': attempt, 'workflow': 'CI',
              'artifacts': artifacts, 'tree': tree, 'skipped_ids': sorted(skipped)}
    if len(artifacts) < len(jobs) and not completion_plan(source, root)['reused_ids']:
        raise ValueError('no reusable complete-module coverage')
    if pointer is not None and source != pointer:
        raise ValueError('ordinary decision differs from authenticated source')
    return source, records_all


def lookup(api, *, request, current_run_id, pr_number, root=ROOT):
    import final_validation_reuse as reuse
    try:
        source, _ = authenticate(api, request=request, current_run_id=current_run_id,
                                 pr_number=pr_number, root=root)
        decision = reuse._decision('reuse', 'authenticated ordinary CI with required completion',
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
        return records


def completion_plan(source, root=ROOT):
    """Repeat a whole module if any of its required tests lack CI coverage.

    This preserves module/class fixture lifecycles. Source skips in otherwise
    covered modules still need individual rechecks, as in the existing path.
    """
    import run_full_cpu_suite as runner
    jobs = schedule(root)
    required = runner.ids_for_units(runner.discover_units(root, root / 'tests'))
    if len(required) != len(set(required)):
        raise ValueError('duplicate canonical identities')
    covered = [canonical_test_id(i) for art in source['artifacts']
               for i in jobs[art['job']]]
    if len(covered) != len(set(covered)) or not set(covered) <= set(required):
        raise ValueError('ambiguous ordinary coverage')
    modules = sorted({i.split('.')[0] for i in set(required) - set(covered)})
    repeated = {i for i in required if i.split('.')[0] in modules}
    skipped = {canonical_test_id(i) for i in source['skipped_ids']}
    if not skipped <= set(covered):
        raise ValueError('skipped identity outside ordinary coverage')
    fresh = repeated | skipped
    reused = set(covered) - fresh
    if reused | fresh != set(required) or reused & fresh:
        raise ValueError('incomplete completion plan')
    return {'reused_ids': sorted(reused),
            'fresh_ids': ['tests.' + i for i in sorted(fresh)],
            'selectors': ['tests.' + m for m in modules] +
                         ['tests.' + i for i in sorted(skipped - repeated)]}


def execute_completion(plan, root=ROOT):
    """Use the existing outcome recorder, but launch whole missing modules."""
    with tempfile.TemporaryDirectory(prefix='ci-completion-') as temporary:
        process = subprocess.run(
            [sys.executable, '-m', 'scripts.ci_unittest', *plan['selectors'], '-v'],
            cwd=root, env=dict(os.environ, CI_OUTCOMES_DIR=temporary), timeout=7200)
        if process.returncode:
            raise ValueError('ordinary CI completion failed')
        records = [json.loads(p.read_text()) for p in Path(temporary).glob('*.json')]
        validate_records(records, expected=plan['fresh_ids'],
                         runtime=outcomes.runtime_identity(),
                         tree=outcomes.git_value(root, 'HEAD^{tree}'),
                         run_id=os.environ['GITHUB_RUN_ID'],
                         attempt=os.environ['GITHUB_RUN_ATTEMPT'])
        return records


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
    partial = len(source['artifacts']) < len(schedule(root))
    completion = None
    if partial:
        plan = completion_plan(source, root)
        fresh = execute_completion(plan, root)
        validate_records(fresh, expected=plan['fresh_ids'],
                         runtime=outcomes.runtime_identity(), tree=source['tree'],
                         run_id=current_run_id, attempt=attempt)
        completion = {'reused_ids': plan['reused_ids'], 'records': fresh}
        records = records + fresh
    else:
        rechecks = confirm_skips(source['skipped_ids'], root)
        records = records + (rechecks if isinstance(rechecks, list) else [])
    # Record the actual ordinary schedule. It is an explicitly allowed alternate
    # schedule, never claimed to be execution of the canonical subprocess plan.
    suite = dict(request.suite, suite_config=suite_configuration(root, source))
    receipt = gate.SuiteReceipt(request.git_commit_sha, suite, request.environment,
                                'PASS', suite['count'],
                                min(r['started_unix'] for r in records),
                                max(r['ended_unix'] for r in records)).to_dict()
    execution = {'mode': MODE, 'dispatch_sha': dispatch_sha,
                 'reuse_contract': gate.FINAL_VALIDATION_REUSE_CONTRACT,
                 'ordinary_source': source, 'skips_confirmed': True}
    if completion is not None:
        execution['completion'] = completion
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
    fields = set(execution) - {'completion'}
    require(fields == {'mode', 'dispatch_sha', 'reuse_contract',
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

    if len(artifacts) < len(schedule()):
        completion = execution.get('completion')
        require(isinstance(completion, dict) and set(completion) == {
            'reused_ids', 'records'}, 'partial completion evidence missing')
        plan = completion_plan(source)
        require(completion['reused_ids'] == plan['reused_ids'],
                'partial reused population mismatch')
        records = completion['records']
        require(isinstance(records, list) and bool(records),
                'partial fresh outcomes missing')
        try:
            validate_records(records, expected=plan['fresh_ids'],
                             runtime=records[0]['runtime'], tree=source['tree'],
                             run_id=github_run_id, attempt=records[0]['attempt'])
        except (ValueError, KeyError, TypeError) as error:
            raise gate.GateOrderingError('invalid completion outcomes: ' + str(error)) from error
    else:
        require('completion' not in execution, 'unexpected partial completion')

"""Risk-based merge handoff using the existing planner and exact-head verifier.

CPU-only, read-only Git/GitHub inspection. A scoped success proves selected CI
jobs, never full qualification; no tests execute during receipt assembly.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

import ci_workflow_parity as parity
import hosted_ci_verification as ci
import issue213_gate_orchestration as gate
import plan_ci


def _pull_identity(pull):
    return {k: pull[k] for k in ('number', 'state', 'head', 'base')}


def _changed_paths(root, base_sha, expected_sha):
    if not re.fullmatch('[0-9a-f]{40}', base_sha or ''):
        raise ValueError('PR base is not an exact SHA')
    # --no-renames includes both the removed and added path of a rename. NUL
    # separation keeps whitespace-bearing paths intact for planner rejection.
    output = subprocess.check_output([
        'git', '-C', str(root), 'diff', '--name-only', '--no-renames', '-z',
        f'{base_sha}...{expected_sha}', '--'], text=True)
    return output.removesuffix('\0').split('\0') if output else []


def selected_population(root, groups):
    """Derive exact required jobs/IDs from executable CI and registry parity."""
    doc = yaml.safe_load((root / '.github/workflows/ci.yml').read_text())
    problems = parity.identity_problems(doc, root=root)
    if problems:
        raise ValueError('CI identity parity failed: ' + '; '.join(problems))
    jobs = parity.job_executed_ids(doc, root=root)
    selected = {job: ids for job, ids in jobs.items()
                if parity.job_group_id(job) in groups}
    if {parity.job_group_id(job) for job in selected} != set(groups):
        raise ValueError('selected group has no executing job')
    ids = sorted(i for values in selected.values() for i in values)
    if len(ids) != len(set(ids)):
        raise ValueError('selected population has duplicate identities')
    return tuple(doc['jobs'][job]['name'] for job in sorted(selected)), ids


def handoff_status(final_head, *, root, ci_verifier, finalizer_ok,
                   suite_receipt=None, final_validation_receipt=None,
                   hosted_ci_status=None):
    """Select scoped vs full requirements from an authenticated PR/base diff."""
    root = Path(root).resolve()
    gate._require_clean_committed_worktree(root)
    if gate.git_commit_sha(root) != final_head.git_commit_sha:
        raise ValueError('handoff request differs from checked-out head')
    if (not isinstance(ci_verifier, ci.HostedCiVerifier)
            or ci_verifier.repository != ci.CANONICAL_REPOSITORY
            or ci_verifier.pr_number is None):
        raise ValueError('risk-based handoff requires canonical current-PR verification')
    before = _pull_identity(ci_verifier.api.get_pull(ci_verifier.pr_number))
    if (before['number'] != ci_verifier.pr_number or before['state'] != 'open'
            or before['head']['sha'] != final_head.git_commit_sha):
        raise ValueError('PR is not open at the checked-out exact head')
    paths = _changed_paths(root, before['base']['sha'], final_head.git_commit_sha)
    plan = plan_ci.plan(paths)
    print(f"[merge-validation] receipt assembly only: head={final_head.git_commit_sha} "
          f"scope={plan['mode']} selected={plan['groups']}", file=sys.stderr, flush=True)
    if plan['full_regression']:
        result = gate.handoff_gate_status(
            final_head, suite_receipt, hosted_ci_status, finalizer_ok,
            final_validation_receipt, ci_verifier=ci_verifier)
        result.update(validation_scope='full', full_qualification_required=True,
                      selection=plan, base_sha=before['base']['sha'])
    else:
        if suite_receipt is not None or final_validation_receipt is not None:
            # Do not re-label a full receipt as scoped or hide a bad receipt.
            raise ValueError('scoped handoff needs no full receipt; use the full handoff to validate it')
        names, ids = selected_population(root, plan['groups'])
        verifier = ci.HostedCiVerifier(
            ci_verifier.api, ci_verifier.repository, pr_number=ci_verifier.pr_number,
            required_success_jobs=names)
        verdict = gate._authenticate_hosted_ci(final_head, hosted_ci_status, verifier)
        ci_ok = verdict['verdict'] == ci.PASS
        result = {
            'schema': gate.SCHEMA, 'handoff_complete': ci_ok and finalizer_ok,
            'final_head_sha': final_head.git_commit_sha, 'base_sha': before['base']['sha'],
            'validation_scope': 'scoped', 'full_qualification_required': False,
            'full_suite_receipt_valid': False, 'full_suite_proof': None,
            'scoped_checks_valid': ci_ok, 'hosted_ci_success': ci_ok,
            'hosted_ci_verdict': verdict, 'finalizer_status_ok': finalizer_ok,
            'selection': plan, 'required_test_ids': ids,
            'required_population_digest': hashlib.sha256(
                json.dumps(ids, separators=(',', ':')).encode()).hexdigest(),
            'reused_groups': plan['groups'] if ci_ok else [],
            'uncovered_groups': sorted(set(plan_ci.GROUP_TEST_MODULES) - set(plan['groups'])),
            'execution': 'receipt assembly only; selected checks ran in authenticated CI',
            'note': 'Scoped merge validation. Uncovered groups were not qualified; '
                    'this result cannot satisfy a full-suite receipt request.',
        }
    print(f"[merge-validation] reused={result.get('reused_groups', [])} "
          f"uncovered={result.get('uncovered_groups', [])}", file=sys.stderr, flush=True)
    after = _pull_identity(ci_verifier.api.get_pull(ci_verifier.pr_number))
    if after != before:
        raise ValueError('PR head/base changed during risk-based handoff')
    if gate.git_commit_sha(root) != final_head.git_commit_sha or not gate.git_tree_clean(root):
        raise ValueError('checkout changed during risk-based handoff')
    return result

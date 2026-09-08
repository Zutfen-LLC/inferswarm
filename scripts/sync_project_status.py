#!/usr/bin/env python3
"""Render living project status; CPU-only, offline, and fail-closed on drift.

This maintenance tool is not an execution authority or a frozen producer.
It renders recorded decisions; it never infers acceptance from a PASS or merge.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'docs/project-status.json'
TARGETS = {
    'README.md': ('capabilities', 'frontier', 'runtime'),
    'ROADMAP.md': ('frontier',),
    'ARCHITECTURE.md': ('frontier',),
    'docs/implementation/README.md': ('frontier',),
    'docs/integrations/freetoken.md': ('frontier', 'runtime'),
    'docs/protocols/README.md': ('frontier',),
}
# Only these already-maintained documentation/CI rows may be refreshed.
# Never regenerate a historical evidence directory or expand this by glob.
LIVE_ROWS = {
    'docs/qualification/gemma4-12b-it-v1/MANIFEST.sha256': (
        '.github/workflows/ci.yml', 'ARCHITECTURE.md', 'ROADMAP.md',
        'docs/protocols/README.md'),
    'docs/implementation/plan-driven-artifact-acquisition-99/evidence/MANIFEST.sha256': (
        '.github/workflows/ci.yml', 'ARCHITECTURE.md', 'ROADMAP.md',
        'docs/implementation/README.md'),
    'docs/implementation/plan-driven-artifact-orchestration-101/evidence/MANIFEST.sha256': (
        '.github/workflows/ci.yml',),
    'docs/implementation/artifact-locality-transition-planning-103/evidence/MANIFEST.sha256': (
        '.github/workflows/ci.yml',),
    'docs/implementation/r6-successor-dense-full-integration-117/evidence/MANIFEST.sha256': (
        '.github/workflows/ci.yml',),
}


def fields(value, names):
    if not isinstance(value, dict) or set(value) != set(names):
        raise ValueError(f'expected fields: {", ".join(names)}')


def text(value):
    if not isinstance(value, str) or not value.strip() or any(c in value for c in '\n\r<>|'):
        raise ValueError('expected nonempty single-line text without HTML or table delimiters')


def reference(value):
    text(value)
    parsed = urlparse(value)
    if (parsed.scheme != 'https' or parsed.netloc != 'github.com'
            or not parsed.path.startswith('/Zutfen-LLC/')
            or any(c.isspace() for c in value) or any(c in value for c in '()')):
        raise ValueError('expected a Zutfen-LLC GitHub HTTPS source reference')


def observed_and_accepted(value):
    observation, acceptance = value['observation'], value['acceptance']
    fields(observation, ('result', 'reference'))
    fields(acceptance, ('state', 'reference'))
    if observation['result'] is None:
        if observation['reference'] is not None:
            raise ValueError('an absent observation cannot cite a result')
    else:
        text(observation['result'])
        reference(observation['reference'])
    if acceptance['state'] not in ('pending', 'accepted'):
        raise ValueError('acceptance must be pending or accepted')
    if acceptance['state'] == 'accepted':
        if observation['result'] is None:
            raise ValueError('acceptance requires an observed result')
        reference(acceptance['reference'])
    elif acceptance['reference'] is not None:
        raise ValueError('pending acceptance must not claim an acceptance reference')


def validate(record):
    fields(record, ('schema', 'capabilities', 'frontier', 'runtime', 'limits'))
    if record['schema'] != 'inferswarm.project-status/1':
        raise ValueError('unsupported status schema')
    if not isinstance(record['capabilities'], list) or not record['capabilities']:
        raise ValueError('capabilities must be a nonempty list')
    ids = set()
    for item in record['capabilities']:
        fields(item, ('id', 'title', 'scope', 'summary', 'observation', 'acceptance'))
        for key in ('id', 'title', 'summary'):
            text(item[key])
        if item['id'] in ids:
            raise ValueError('duplicate capability id')
        ids.add(item['id'])
        if item['scope'] not in ('physical', 'cpu-fixture'):
            raise ValueError('capability scope must distinguish physical from cpu-fixture')
        observed_and_accepted(item)
        if item['acceptance']['state'] != 'accepted':
            raise ValueError('demonstrated capabilities must cite recorded acceptance')
    frontier = record['frontier']
    fields(frontier, ('title', 'reference', 'objective', 'prerequisite', 'execution'))
    text(frontier['title'])
    text(frontier['objective'])
    reference(frontier['reference'])
    fields(frontier['prerequisite'], ('title', 'observation', 'acceptance'))
    text(frontier['prerequisite']['title'])
    observed_and_accepted(frontier['prerequisite'])
    execution = frontier['execution']
    fields(execution, ('state', 'step', 'reference', 'constraints'))
    text(execution['step'])
    if execution['state'] not in ('authorized', 'blocked'):
        raise ValueError('execution authorization must be explicit')
    if execution['state'] == 'authorized':
        reference(execution['reference'])
        if frontier['prerequisite']['acceptance']['state'] != 'accepted':
            raise ValueError('authorization requires accepted prerequisite evidence')
    elif execution['reference'] is not None:
        reference(execution['reference'])
    for values in (execution['constraints'], record['limits']):
        if not isinstance(values, list) or not values:
            raise ValueError('constraints and limits must be nonempty lists')
        for value in values:
            text(value)
    runtime = record['runtime']
    fields(runtime, ('repository', 'integration_branch', 'reference'))
    reference(runtime['repository'])
    reference(runtime['reference'])
    if not isinstance(runtime['integration_branch'], str) or not re.fullmatch(
            r'[A-Za-z0-9_./-]+', runtime['integration_branch']):
        raise ValueError('invalid integration branch')


def render(record):
    validate(record)
    capabilities = [
        '| Capability | Evidence scope | Demonstrated result |',
        '|---|---|---|',
    ]
    for item in record['capabilities']:
        scope = 'Physical' if item['scope'] == 'physical' else 'CPU fixture'
        capabilities.append(
            f"| {item['title']} | {scope} | {item['summary']} "
            f"[Evidence]({item['observation']['reference']}); "
            f"[acceptance]({item['acceptance']['reference']}). |")
    capabilities += ['', *('- ' + limit for limit in record['limits'])]
    f = record['frontier']
    p, e = f['prerequisite'], f['execution']
    observation = p['observation']
    result = (f"[`{observation['result']}`]({observation['reference']})"
              if observation['result'] is not None else 'not yet observed')
    acceptance = p['acceptance']
    accepted = (f"[accepted]({acceptance['reference']})"
                if acceptance['state'] == 'accepted' else 'pending maintainer acceptance')
    authority = (f" [Authority]({e['reference']})." if e['reference'] else '')
    frontier = [
        f"**[{f['title']}]({f['reference']})**", '', f['objective'], '',
        f"- **{p['title']} observation:** {result}.",
        f"- **Maintainer acceptance:** {accepted}.",
        f"- **Recorded execution authorization:** {e['state']} — {e['step']}.{authority}",
        '', *('- ' + constraint for constraint in e['constraints']),
    ]
    r = record['runtime']
    runtime = [
        f"The [FreeToken fork]({r['repository']}) is the initial runtime vehicle.",
        f"Its durable integration branch is `{r['integration_branch']}` "
        f"([established by #59]({r['reference']})).",
        'Upstream-tracking `main` and immutable evidence branches have separate roles.',
        'Execution uses the exact producer named by the current gate authority,',
        'never an unreviewed branch tip. FreeToken is not the permanent product boundary.',
    ]
    return {'capabilities': '\n'.join(capabilities), 'frontier': '\n'.join(frontier),
            'runtime': '\n'.join(runtime)}


def replace_section(content, section, body):
    begin = f'<!-- project-status:{section}:start -->'
    end = f'<!-- project-status:{section}:end -->'
    if content.count(begin) != 1 or content.count(end) != 1:
        raise ValueError(f'missing or duplicate {section} markers')
    start = content.index(begin) + len(begin)
    stop = content.index(end)
    if stop < start or '<!-- project-status:' in content[start:stop]:
        raise ValueError(f'reversed or nested {section} markers')
    return content[:start] + '\n' + body + '\n' + content[stop:]


def prepare_updates(root):
    sections = render(json.loads((root / SOURCE).read_text(encoding='utf-8')))
    rendered = {}
    for relative, names in TARGETS.items():
        content = (root / relative).read_text(encoding='utf-8')
        expected_markers = {f'<!-- project-status:{n}:{edge} -->'
                            for n in names for edge in ('start', 'end')}
        actual_markers = re.findall(r'<!-- project-status:[^\n]*?-->', content)
        if set(actual_markers) != expected_markers or len(actual_markers) != len(expected_markers):
            raise ValueError(f'{relative}: unexpected, missing, or duplicate status markers')
        for name in names:
            content = replace_section(content, name, sections[name])
        rendered[relative] = content.encode('utf-8')
    for relative, allowed in LIVE_ROWS.items():
        original = (root / relative).read_text(encoding='utf-8')
        seen = set()
        rows = []
        for line in original.splitlines(keepends=True):
            digest, path = line.rstrip('\n').split('  ', 1)
            if not re.fullmatch('[0-9a-f]{64}', digest) or path in seen:
                raise ValueError(f'{relative}: malformed or duplicate manifest row')
            seen.add(path)
            if path in allowed:
                data = rendered[path] if path in rendered else (root / path).read_bytes()
                line = hashlib.sha256(data).hexdigest() + '  ' + path + '\n'
            rows.append(line)
        if not set(allowed) <= seen:
            raise ValueError(f'{relative}: missing maintained manifest row')
        rendered[relative] = ''.join(rows).encode('utf-8')
    return {path: data for path, data in rendered.items()
            if (root / path).read_bytes() != data}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check', action='store_true', help='fail on drift (default)')
    mode.add_argument('--write', action='store_true', help='update designated living sections and manifest rows')
    args = parser.parse_args(argv)
    try:
        updates = prepare_updates(ROOT)
        if args.write:
            for path, content in updates.items():
                (ROOT / path).write_bytes(content)
                print('Updated ' + path)
        elif updates:
            print('Project status is stale: ' + ', '.join(updates), file=sys.stderr)
            print('Run python3 scripts/sync_project_status.py --write', file=sys.stderr)
            return 1
        else:
            print('Project status sections and maintained manifest rows are current')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f'Project status check failed: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

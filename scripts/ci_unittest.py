"""Ordinary unittest CLI with lossless, per-invocation outcome recording.

The workflow uploads these records only after the job succeeds. They are inputs
for authenticated ordinary-CI reuse, never standalone gate authorization.
"""
from __future__ import annotations

import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 'ci-unittest-outcomes/1'


def git_value(root, revision):
    return subprocess.check_output(['git', '-C', str(root), 'rev-parse', revision],
                                   text=True).strip()


def runtime_identity():
    # Paths vary between fresh runners. Versions, OS, architecture and test
    # switches must agree; caches and per-process temporary paths are private.
    switches = {k: v for k, v in os.environ.items() if k.startswith(
        ('MOE_', 'ISSUE', 'NATIVE_', 'INFER_SWARM_'))}
    switches.update({k: os.environ[k] for k in (
        'CC', 'CXX', 'CFLAGS', 'CXXFLAGS', 'LDFLAGS', 'PYTHONHASHSEED',
        'OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'ImageOS', 'ImageVersion')
                     if k in os.environ})
    tools = {}
    for tool in ('c++', 'cmake', 'openssl'):
        executable = shutil.which(tool)
        if executable is None:
            tools[tool] = None
        else:
            option = 'version' if tool == 'openssl' else '--version'
            result = subprocess.run([executable, option], capture_output=True,
                                    text=True, timeout=10, check=True)
            tools[tool] = result.stdout.splitlines()[0]
    return {'python': platform.python_version(), 'system': platform.system(),
            'machine': platform.machine(), 'os': platform.freedesktop_os_release(),
            'packages': sorted([d.metadata['Name'].lower(), d.version]
                               for d in importlib.metadata.distributions()),
            'switches': switches, 'tools': tools}


class OutcomeResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.started_ids = []
        self.outcomes = []

    def startTest(self, test):
        self.started_ids.append(test.id())
        super().startTest(test)

    def addSuccess(self, test):
        self.outcomes.append([test.id(), 'success', None])
        super().addSuccess(test)

    def addSkip(self, test, reason):
        self.outcomes.append([test.id(), 'skip', reason])
        super().addSkip(test, reason)


class OutcomeRunner(unittest.TextTestRunner):
    resultclass = OutcomeResult


def main(argv=None):
    started = time.time()
    runtime = runtime_identity()
    program = unittest.TestProgram(
        module=None, argv=['unittest', *(sys.argv[1:] if argv is None else argv)],
        testRunner=OutcomeRunner, exit=False)
    result = program.result
    out = os.environ.get('CI_OUTCOMES_DIR')
    if out:
        record = {'schema': SCHEMA, 'run_id': os.environ.get('GITHUB_RUN_ID'),
                  'attempt': os.environ.get('GITHUB_RUN_ATTEMPT'),
                  'job': os.environ.get('GITHUB_JOB'),
                  'checkout_sha': git_value(ROOT, 'HEAD'),
                  'tree': git_value(ROOT, 'HEAD^{tree}'),
                  'runtime': runtime, 'started_unix': started,
                  'ended_unix': time.time(), 'ok': result.wasSuccessful(),
                  'started_ids': result.started_ids, 'outcomes': result.outcomes}
        directory = Path(out)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f'{uuid.uuid4().hex}.json').write_text(json.dumps(record))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())

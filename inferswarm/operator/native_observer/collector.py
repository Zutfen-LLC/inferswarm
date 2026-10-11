"""Real bounded collector and independent process-identity reader (#302).

The collector reads retained observer artifacts over the existing lifecycle
SSH transport and authenticates every byte before parsing: the derived-build
manifest against the actual executable bytes, the native observation stream
against the invocation-owned export-directory claim, and the /proc identity
of the observed process. It never launches, installs, or writes on any host;
its SSH usage is strictly ``subprocess.run`` of a read-only Python program,
mirroring the qualified source-transport pattern.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path
import shlex
import subprocess

from ..bindings import ProcessIdentity, TransportReply
from ..profiles import canonical, freeze, sha256, thaw
from ..phased_observation import (NativeBuildIdentity, OwnedSpawnFacts, DerivedBuildEvidence,
    ParticipantStaticEvidence, ParticipantDynamicEvidence, ParsedObservation,
    parse_build_manifest, parse_observation)

# Native export labels written by the retained #301 observation overlay:
# the client/server process exports as llama-server (server-queue.cpp) and
# the RPC server exports as ggml-rpc-server (rpc-server main loop).
NATIVE_LABELS = {'client': 'llama-server', 'remote': 'ggml-rpc-server'}
SSH_TIMEOUT_SECONDS = 120
CLAIM_NAME = 'is301-claim'
# Producer export cap: is301_observer.h export_capture MAX_EXPORTS.
MAX_EXPORTS = 64
MANIFEST_SUFFIX = '.build-manifest.json'


class CollectorError(RuntimeError):
    pass


class SSHCollectorTransport:
    """Read-only SSH artifact reader (qualified source-transport pattern)."""

    def read_bytes(self, address: str, path: str) -> bytes:
        # base64 wraps arbitrary binary through the text-only SSH channel.
        program = ("import base64,sys\n"
                   "sys.stdout.write(base64.b64encode(open(sys.argv[1],'rb').read()).decode('ascii'))")
        proc = subprocess.run(
            ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', address,
             'python3 -c ' + shlex.quote(program) + ' ' + shlex.quote(path)],
            capture_output=True, timeout=SSH_TIMEOUT_SECONDS)
        if proc.returncode != 0:
            raise CollectorError(f'collector read failed ({address}:{path}): {proc.stderr[-300:]!r}')
        import base64
        try:
            return base64.b64decode(proc.stdout, validate=True)
        except Exception as exc:
            raise CollectorError(f'collector read returned invalid base64 ({address}:{path})') from exc

    def read_json(self, address: str, path: str):
        raw = self.read_bytes(address, path)
        try:
            return json.loads(raw.decode('utf-8'))
        except (UnicodeError, ValueError) as exc:
            raise CollectorError(f'collector read invalid JSON ({address}:{path})') from exc

    def list_dir(self, address: str, path: str) -> list[str]:
        program = ("import sys\n"
                   "print('\\n'.join(sorted(p.name for p in __import__('pathlib').Path(sys.argv[1]).iterdir())))")
        proc = subprocess.run(
            ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', address,
             'python3 -c ' + shlex.quote(program) + ' ' + shlex.quote(path)],
            capture_output=True, text=True, timeout=SSH_TIMEOUT_SECONDS)
        if proc.returncode != 0:
            raise CollectorError(f'collector listing failed ({address}:{path}): {proc.stderr[-300:]!r}')
        return [name for name in proc.stdout.splitlines() if name]


_IDENTITY_PROGRAM = ("import json,sys\n"
    "pid=sys.argv[1]\n"
    "fields=open(f'/proc/{pid}/stat').read().rsplit(') ',1)[1].split()\n"
    "start=fields[19]\n"
    "exe=__import__('os').path.realpath(f'/proc/{pid}/exe')\n"
    "raw=open(f'/proc/{pid}/cmdline','rb').read().split(b'\\0')\n"
    "argv=[p.decode('utf-8','surrogateescape') for p in raw if p]\n"
    "env={}\n"
    "for line in open(f'/proc/{pid}/environ','rb').read().split(b'\\0'):\n"
    "    if b'=' in line:\n"
    "        k,v=line.split(b'=',1); env[k.decode('utf-8','surrogateescape')]=v.decode('utf-8','surrogateescape')\n"
    "import hashlib\n"
    "sha=hashlib.sha256(open(exe,'rb').read()).hexdigest()\n"
    "print(json.dumps({'start':start,'exe':exe,'argv':argv,'sha256':sha,'environ':env}))")


class ProcIdentityReader:
    """Independent /proc-based identity reader over the lifecycle transport.

    Reads pid/start/executable/argv/environ for the exact PID and hashes the
    actual executable bytes. Every field is independently observed and
    compared against the controller's frozen expectations by the caller;
    configured values are never echoed in place of observations.
    """

    def __init__(self, transport: SSHCollectorTransport | None = None):
        self.transport = transport or SSHCollectorTransport()

    def read(self, participant, pid: int, *, expected_executable: str,
             expected_sha256: str, expected_argv: tuple[str, ...],
             visibility_environment: tuple[str, ...] = ()) -> ProcessIdentity:
        proc = subprocess.run(
            ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', participant.execution_address,
             'python3 -c ' + shlex.quote(_IDENTITY_PROGRAM) + ' ' + str(int(pid))],
            capture_output=True, text=True, timeout=SSH_TIMEOUT_SECONDS)
        if proc.returncode != 0:
            raise CollectorError(f'identity read failed ({participant.participant_id}): {proc.stderr[-300:]!r}')
        try:
            raw = json.loads(proc.stdout)
        except ValueError as exc:
            raise CollectorError(f'identity read invalid reply ({participant.participant_id})') from exc
        # Independent observations must equal the frozen expectations; a
        # mismatch is a named refusal, never an echo of configured values.
        observed = (raw.get('exe'), tuple(raw.get('argv', ())), raw.get('sha256'), raw.get('start'))
        expected = (expected_executable, tuple(expected_argv), expected_sha256)
        if observed[0] != expected[0]:
            raise CollectorError(f'identity executable mismatch ({participant.participant_id}): '
                                 f'{observed[0]!r} != {expected[0]!r}')
        if observed[1] != expected[1]:
            raise CollectorError(f'identity argv mismatch ({participant.participant_id})')
        if observed[2] != expected[2]:
            raise CollectorError(f'identity executable bytes mismatch ({participant.participant_id})')
        environment = {k: v for k, v in raw.get('environ', {}).items()
                       if k in visibility_environment or k in ('IS301_EXPORT_DIR', 'IS301_OBSERVE')}
        return ProcessIdentity(participant.participant_id, participant.host_id,
            participant.boot_epoch, participant.topology_epoch, int(pid), str(observed[3]),
            expected_executable, expected_sha256,
            tuple(raw['argv']), freeze(dict(native=[], visible=[], environment=environment)),
            participant.rpc_endpoint)


# Retained #301 derived-build artifacts the collector must authenticate
# independently, mirroring tests/fixtures/issue299/round2-native/.
RETAINED_PATCH_SHA256 = 'd471abb83e3c911ed5bcc812c04bb8bb36a062183cea1e2f79b4f80fe482d2ef'
RETAINED_TRANSFORMED_MANIFEST_SHA256 = 'f03cc3272424082c1657588d341bd18bfa399ba54fe05e3bb85021d626fb84f7'
RETAINED_COMPILER = 'c++ (Debian 14.2.0-19) 14.2.0'
RETAINED_BUILD_OPTIONS = ('-O0', '-g0', '-pthread', '-D_GNU_SOURCE', '-D_XOPEN_SOURCE=600', '-DGGML_SCHED_MAX_COPIES=4', '-DGGML_USE_CPU', '-DGGML_USE_RPC', '-DLLAMA_SUBPROCESS', '-DCPPHTTPLIB_FORM_URL_ENCODED_PAYLOAD_MAX_LENGTH=1048576', '-DCPPHTTPLIB_LISTEN_BACKLOG=512', '-DCPPHTTPLIB_REQUEST_URI_MAX_LENGTH=32768', '-DCPPHTTPLIB_TCP_NODELAY=1')
RETAINED_BACKEND_LIBRARIES = (('libllama-full.a', '6bafcb05a5188e287117d5df9d2b36798bf95c92640317697b26d2af0f5138c6'),)


class NativeObserverCollector:
    """Bounded collector joining native exports to owned lifecycle facts."""

    def __init__(self, transport: SSHCollectorTransport | None = None,
                 identity_reader: ProcIdentityReader | None = None):
        self.transport = transport or SSHCollectorTransport()
        self.identity_reader = identity_reader or ProcIdentityReader(self.transport)

    def collect_static(self, participant, spawn: OwnedSpawnFacts, manifest_path: str,
                       executable_path: str, source_receipt_digest: str, *,
                       expected_argv: tuple[str, ...]) -> ParticipantStaticEvidence:
        build = self.collect_build(participant, manifest_path, executable_path)
        identity = self.identity_reader.read(participant, spawn.pid,
            expected_executable=participant.runtime_executable,
            expected_sha256=participant.runtime_sha256,
            expected_argv=expected_argv)
        if identity.pid != spawn.pid or identity.start != spawn.start:
            raise CollectorError('owned identity pid/start mismatch: '
                                 + participant.participant_id)
        return ParticipantStaticEvidence(participant.participant_id, identity, spawn, build,
                                         source_receipt_digest)

    def collect_build(self, participant, manifest_path: str,
                      executable_path: str) -> DerivedBuildEvidence:
        body = self.transport.read_json(participant.execution_address, manifest_path)
        manifest = parse_build_manifest(body)
        executable = self.transport.read_bytes(participant.execution_address, executable_path)
        import hashlib
        digest = hashlib.sha256(executable).hexdigest()
        if digest != manifest.executable_sha256:
            raise CollectorError('derived build executable bytes do not match manifest: '
                                 + participant.participant_id)
        # Explicit derived-build qualification: the manifest must descend from
        # the retained authenticated #301 producer artifacts, not merely be
        # self-consistent. A foreign patch/transformed/compiler/flag identity
        # is a named refusal even when the executable bytes match.
        if manifest.patch_sha256 != RETAINED_PATCH_SHA256:
            raise CollectorError('derived build patch identity is not the retained '
                                 'authenticated #301 overlay: ' + participant.participant_id)
        if manifest.transformed_manifest_sha256 != RETAINED_TRANSFORMED_MANIFEST_SHA256:
            raise CollectorError('derived build transformed-manifest identity is not the '
                                 'retained authenticated #301 overlay: '
                                 + participant.participant_id)
        if manifest.compiler != RETAINED_COMPILER:
            raise CollectorError('derived build compiler identity is not the retained '
                                 'authenticated #301 toolchain: ' + participant.participant_id)
        if tuple(manifest.build_options) != RETAINED_BUILD_OPTIONS:
            raise CollectorError('derived build options are not the retained '
                                 'authenticated #301 recipe: ' + participant.participant_id)
        if tuple(manifest.backend_libraries) != RETAINED_BACKEND_LIBRARIES:
            raise CollectorError('derived build backend libraries are not the retained '
                                 'authenticated #301 artifacts: ' + participant.participant_id)
        return DerivedBuildEvidence(manifest, digest)

    def collect_dynamic(self, participant, spawn: OwnedSpawnFacts, export_dir: str,
                        plan_digest: str, invocation_token: str,
                        native_label: str) -> ParticipantDynamicEvidence:
        # The retained producer writes the claim as plaintext
        # 'PID\nSTART_TICKS\nLABEL\n' (is301_observer.h export_capture).
        raw = self.transport.read_bytes(participant.execution_address,
                                        str(Path(export_dir) / CLAIM_NAME))
        try:
            text = raw.decode('utf-8')
            claim_pid, claim_start, claim_label = text.splitlines()[:3]
            claim_pid = int(claim_pid)
        except (UnicodeError, ValueError) as exc:
            raise CollectorError('export claim malformed: '
                                 + participant.participant_id) from exc
        if (claim_label != native_label
                or claim_pid != spawn.pid or claim_start != spawn.start):
            raise CollectorError('export directory claim owner mismatch: '
                                 + participant.participant_id)
        # Only the exact plaintext claim file is excluded; every other JSON
        # file is inspected so a second stream cannot hide behind a
        # claim-prefixed name.
        names = sorted(name for name in
                       self.transport.list_dir(participant.execution_address, export_dir)
                       if name.endswith('.json') and name != CLAIM_NAME)
        # Every envelope in an owned export directory must be either the one
        # DYNAMIC evidence stream or a legal static snapshot (fenced, empty
        # zero interval). A 'static'-labeled envelope carrying an event
        # stream is a disguised dynamic capture and refuses.
        dynamics = []
        for name in names:
            payload = self.transport.read_bytes(participant.execution_address,
                                                str(Path(export_dir) / name))
            candidate = parse_observation(TransportReply(0, payload))
            if candidate.phase == 'dynamic':
                dynamics.append((name, candidate))
            elif not (candidate.stream_kind == 'snapshot' and candidate.snapshot_fence
                      and candidate.terminal and candidate.event_count == 0):
                raise CollectorError('export directory holds a disguised non-snapshot '
                                     'envelope: ' + name)
        if len(dynamics) != 1:
            raise CollectorError(f'export directory must hold exactly one dynamic envelope '
                                 f'({participant.participant_id}): '
                                 f'{[name for name, _ in dynamics]}')
        name, observation = dynamics[0]
        # Bind the selected envelope to the owned claim on every identity
        # surface. The producer writes '<label>-<pid>-%04d.json' and a
        # generation 'exp-<pid>-<ordinal>-<ns>' from the SAME capture: exact
        # full-format match, same owned pid AND same ordinal on both surfaces.
        # Canonical ASCII producer format only: the filename ordinal is a
        # zero-padded %04d, the pid/ordinals in both surfaces are unpadded
        # decimal, and the ordinal lies within the producer's 64-export cap.
        match = re.fullmatch(r'([A-Za-z0-9_.-]+)-([0-9]+)-([0-9]{4})', name[:-len('.json')])
        if match is None or match.group(1) != native_label \
                or match.group(2) != str(claim_pid) \
                or match.group(3) != '%04d' % int(match.group(3)) \
                or int(match.group(3)) >= MAX_EXPORTS:
            raise CollectorError('dynamic envelope filename does not match the owned '
                                 'claim producer format: ' + name)
        ordinal = int(match.group(3))
        generation = observation.stream_generation
        gen = re.fullmatch(r'exp-([0-9]+)-([0-9]+)-([0-9]+)', generation)
        if gen is None or gen.group(1) != str(claim_pid) \
                or gen.group(2) != str(ordinal):
            raise CollectorError('dynamic envelope generation does not match the owned '
                                 'claim capture: ' + generation)
        facts = thaw(observation.facts)
        process = facts.get('process')
        # A present process census is mandatory-shaped: exact dict with an
        # exact-int pid equal to the owned claim. Malformed or contradictory
        # values refuse; there is no absent-census escape once the key exists.
        if 'process' in facts:
            if not isinstance(process, dict) or type(process.get('pid')) is not int:
                raise CollectorError('dynamic envelope process census malformed: '
                                     + participant.participant_id)
            if process['pid'] != claim_pid:
                raise CollectorError('dynamic envelope process census does not match the '
                                     'owned claim pid: ' + participant.participant_id)
        # The retained overlay seals native envelopes with a zero plan digest
        # (the producer never sees the controller plan identity); the binding
        # to this invocation runs through the export claim checked above.
        if observation.plan_digest != plan_digest and observation.plan_digest != '0' * 64:
            raise CollectorError('observation plan digest mismatch: ' + participant.participant_id)
        return ParticipantDynamicEvidence(participant.participant_id, observation, spawn,
                                          claim_pid, claim_start, native_label)


__all__ = ['CollectorError', 'SSHCollectorTransport', 'ProcIdentityReader', 'NativeObserverCollector',
           'CLAIM_NAME', 'MANIFEST_SUFFIX']

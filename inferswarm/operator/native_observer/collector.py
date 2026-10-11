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
from dataclasses import asdict
from pathlib import Path
import shlex
import subprocess

from ..bindings import ProcessIdentity, TransportReply
from ..profiles import canonical, freeze, sha256, thaw
from ..phased_observation import (NativeBuildIdentity, OwnedSpawnFacts, DerivedBuildEvidence,
    ParticipantStaticEvidence, ParticipantDynamicEvidence, parse_build_manifest, parse_observation)

# Native export labels written by the retained #301 observation overlay:
# the client/server process exports as llama-server (server-queue.cpp) and
# the RPC server exports as ggml-rpc-server (rpc-server main loop).
NATIVE_LABELS = {'client': 'llama-server', 'remote': 'ggml-rpc-server'}
SSH_TIMEOUT_SECONDS = 120
CLAIM_NAME = 'is301-claim'
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


class ProcIdentityReader:
    """Independent /proc-based identity reader over the lifecycle transport.

    Reads pid/start/executable/argv/environ for the exact PID and compares
    every field against the controller's frozen expectations; it never
    trusts observer-supplied identity fields.
    """

    def __init__(self, transport: SSHCollectorTransport | None = None):
        self.transport = transport or SSHCollectorTransport()

    PROGRAM = ("import json,sys\n"
               "pid=sys.argv[1]\n"
               "fields=open(f'/proc/{pid}/stat').read().rsplit(') ',1)[1].split()\n"
               "start=fields[19]\n"
               "raw=open(f'/proc/{pid}/cmdline','rb').read().split(b'\\0')\n"
               "argv=[p.decode('utf-8','surrogateescape') for p in raw if p]\n"
               "env={}\n"
               "for line in open(f'/proc/{pid}/environ','rb').read().split(b'\\0'):\n"
               "    if b'=' in line:\n"
               "        k,v=line.split(b'=',1); env[k.decode('utf-8','surrogateescape')]=v.decode('utf-8','surrogateescape')\n"
               "print(json.dumps({'start':start,'argv':argv,'environ':env}))")

    def read(self, participant, pid: int) -> ProcessIdentity:
        proc = subprocess.run(
            ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', participant.execution_address,
             'python3 -c ' + shlex.quote(self.PROGRAM) + ' ' + str(int(pid))],
            capture_output=True, text=True, timeout=SSH_TIMEOUT_SECONDS)
        if proc.returncode != 0:
            raise CollectorError(f'identity read failed ({participant.participant_id}): {proc.stderr[-300:]!r}')
        try:
            raw = json.loads(proc.stdout)
        except ValueError as exc:
            raise CollectorError(f'identity read invalid reply ({participant.participant_id})') from exc
        # Filter the environment to the controlled visibility keys.
        environment = {k: v for k, v in raw.get('environ', {}).items()
                       if k in ('GGML_BACKEND_PATH', 'IS301_EXPORT_DIR', 'LLAMA_CACHE')}
        return ProcessIdentity(participant.participant_id, participant.host_id,
            participant.boot_epoch, participant.topology_epoch, int(pid), str(raw['start']),
            participant.runtime_executable, participant.runtime_sha256,
            tuple(raw['argv']), freeze(dict(native=[], visible=[], environment=environment)),
            participant.rpc_endpoint)


class NativeObserverCollector:
    """Bounded collector joining native exports to owned lifecycle facts."""

    def __init__(self, transport: SSHCollectorTransport | None = None):
        self.transport = transport or SSHCollectorTransport()

    def collect_static(self, participant, spawn: OwnedSpawnFacts, manifest_path: str,
                       executable_path: str, source_receipt_digest: str) -> ParticipantStaticEvidence:
        manifest = self.collect_build(participant, manifest_path, executable_path)
        return ParticipantStaticEvidence(participant.participant_id, None, spawn, manifest,
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
        return DerivedBuildEvidence(manifest, digest)

    def collect_dynamic(self, participant, spawn: OwnedSpawnFacts, export_dir: str,
                        plan_digest: str, invocation_token: str,
                        native_label: str) -> ParticipantDynamicEvidence:
        claim = self.transport.read_json(participant.execution_address,
                                         str(Path(export_dir) / CLAIM_NAME))
        if (claim.get('participant') != native_label
                or int(claim['pid']) != spawn.pid or str(claim['start_ticks']) != spawn.start):
            raise CollectorError('export directory claim owner mismatch: '
                                 + participant.participant_id)
        names = self.transport.list_dir(participant.execution_address, export_dir)
        dynamic = [name for name in names if name.endswith('.json')
                   and not name.startswith(CLAIM_NAME)]
        if len(dynamic) != 1:
            raise CollectorError(f'export directory must hold exactly one dynamic envelope '
                                 f'({participant.participant_id}): {dynamic}')
        payload = self.transport.read_bytes(participant.execution_address,
                                            str(Path(export_dir) / dynamic[0]))
        observation = parse_observation(TransportReply(0, payload))
        # The retained overlay seals native envelopes with a zero plan digest
        # (the producer never sees the controller plan identity); the binding
        # to this invocation runs through the export claim checked above.
        if observation.plan_digest != plan_digest and observation.plan_digest != '0' * 64:
            raise CollectorError('observation plan digest mismatch: ' + participant.participant_id)
        return ParticipantDynamicEvidence(participant.participant_id, observation, spawn,
                                          int(claim['pid']), str(claim['start_ticks']),
                                          native_label)


__all__ = ['CollectorError', 'SSHCollectorTransport', 'ProcIdentityReader', 'NativeObserverCollector',
           'CLAIM_NAME', 'MANIFEST_SUFFIX']

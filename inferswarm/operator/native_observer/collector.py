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
    ObservedHostFacts, ParticipantStaticEvidence, ParticipantDynamicEvidence,
    ParsedObservation, parse_build_manifest, parse_observation)

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
    """Read-only SSH artifact reader (qualified source-transport pattern).

    Every read is bounded by an explicit per-artifact family limit that is
    enforced REMOTELY, before the payload is materialized: the remote
    program refuses to emit more than the bound, so an overbound artifact
    can never trigger an unbounded allocation or parse on the controller.
    """

    # Distinct per-artifact families: the plaintext ownership claim is a
    # three-line file; build manifests are small JSON; native observation
    # envelopes share the parser's 8 MiB cap; retained native executables
    # get their own generous but finite cap.
    CLAIM_MAX_BYTES = 4096
    MANIFEST_MAX_BYTES = 1 << 20
    ENVELOPE_MAX_BYTES = 8 << 20
    EXECUTABLE_MAX_BYTES = 300 << 20

    def read_bytes(self, address: str, path: str, *, max_bytes: int) -> bytes:
        if type(max_bytes) is not int or max_bytes < 1:
            raise ValueError('collector read requires an explicit positive bound')
        # base64 wraps arbitrary binary through the text-only SSH channel;
        # the remote program checks the actual size BEFORE reading, so the
        # bound is enforced before materialization on either side.
        program = ("import base64,sys\n"
                   "limit=int(sys.argv[2])\n"
                   "data=open(sys.argv[1],'rb').read(limit+1)\n"
                   "if len(data)>limit: sys.exit(3)\n"
                   "sys.stdout.write(base64.b64encode(data).decode('ascii'))")
        proc = subprocess.run(
            ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', address,
             'python3 -c ' + shlex.quote(program) + ' ' + shlex.quote(path)
             + ' ' + str(int(max_bytes))],
            capture_output=True, timeout=SSH_TIMEOUT_SECONDS)
        if proc.returncode == 3:
            raise CollectorError(f'collector read exceeds family bound '
                                 f'({address}:{path}): {max_bytes} bytes')
        if proc.returncode != 0:
            raise CollectorError(f'collector read failed ({address}:{path}): {proc.stderr[-300:]!r}')
        import base64
        try:
            payload = base64.b64decode(proc.stdout, validate=True)
        except Exception as exc:
            raise CollectorError(f'collector read returned invalid base64 ({address}:{path})') from exc
        if len(payload) > max_bytes:
            raise CollectorError(f'collector read exceeds family bound '
                                 f'({address}:{path}): {max_bytes} bytes')
        return payload

    def read_json(self, address: str, path: str, *, max_bytes: int):
        raw = self.read_bytes(address, path, max_bytes=max_bytes)
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


# Distinct per-artifact read families, enforced before materialization.
CLAIM_MAX_BYTES = SSHCollectorTransport.CLAIM_MAX_BYTES
MANIFEST_MAX_BYTES = SSHCollectorTransport.MANIFEST_MAX_BYTES
ENVELOPE_MAX_BYTES = SSHCollectorTransport.ENVELOPE_MAX_BYTES
EXECUTABLE_MAX_BYTES = SSHCollectorTransport.EXECUTABLE_MAX_BYTES


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


_HOST_FACTS_PROGRAM = ("import json,sys\n"
    "btime=None\n"
    "for line in open('/proc/stat'):\n"
    "    if line.startswith('btime '):\n"
    "        btime=line.split()[1]\n"
    "import hashlib,os,glob\n"
    "h=hashlib.sha256()\n"
    "for sub in ('cpu/cpu[0-9]*','node/node[0-9]*'):\n"
    "    for path in sorted(glob.glob(os.path.join('/sys/devices/system',sub))):\n"
    "        h.update(path.encode()); h.update(b'\\n')\n"
    "print(json.dumps({'boot_epoch':btime,'topology_epoch':h.hexdigest()}))")


class HostFactsReader:
    """Independent remote host-facts reader (#302 P1-C).

    Reads the boot epoch (/proc/stat btime) and a topology digest over the
    same read-only SSH channel. Listener identity and the observer
    environment are supplied by the caller from the trusted owned-listener
    seam and the independently read process environment; every field is
    joined against the frozen plan by reconciliation, never echoed.
    """

    def __init__(self, transport: SSHCollectorTransport | None = None):
        self.transport = transport or SSHCollectorTransport()

    def read(self, participant, *, listening=(), environment=None):
        proc = subprocess.run(
            ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
             participant.execution_address,
             'python3 -c ' + shlex.quote(_HOST_FACTS_PROGRAM)],
            capture_output=True, text=True, timeout=SSH_TIMEOUT_SECONDS)
        if proc.returncode != 0:
            raise CollectorError('host facts read failed ('
                                 + participant.participant_id + '): '
                                 + repr(proc.stderr[-300:]))
        try:
            raw = json.loads(proc.stdout)
        except ValueError as exc:
            raise CollectorError('host facts read invalid reply ('
                                 + participant.participant_id + ')') from exc
        boot = raw.get('boot_epoch')
        topology = raw.get('topology_epoch')
        return ObservedHostFacts(
            boot_epoch=str(boot) if boot is not None else None,
            topology_epoch=str(topology) if topology is not None else None,
            listening=tuple(listening),
            observer_environment=dict(environment or {}),
            source='remote-proc-observation')


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
# independently, mirroring tests/fixtures/issue299/round2-native/. The two
# retained builds are genuinely distinct per role: the client runs
# llama-server and closes over libllama-full.a; the RPC participant runs
# ggml-rpc-server and closes over libggml-static.a. A shared deployment
# identity or a swapped-role join must refuse.
RETAINED_PATCH_SHA256 = 'd471abb83e3c911ed5bcc812c04bb8bb36a062183cea1e2f79b4f80fe482d2ef'
RETAINED_TRANSFORMED_MANIFEST_SHA256 = 'f03cc3272424082c1657588d341bd18bfa399ba54fe05e3bb85021d626fb84f7'
RETAINED_COMPILER = 'c++ (Debian 14.2.0-19) 14.2.0'
RETAINED_BUILD_OPTIONS = ('-O0', '-g0', '-pthread', '-D_GNU_SOURCE', '-D_XOPEN_SOURCE=600', '-DGGML_SCHED_MAX_COPIES=4', '-DGGML_USE_CPU', '-DGGML_USE_RPC', '-DLLAMA_SUBPROCESS', '-DCPPHTTPLIB_FORM_URL_ENCODED_PAYLOAD_MAX_LENGTH=1048576', '-DCPPHTTPLIB_LISTEN_BACKLOG=512', '-DCPPHTTPLIB_REQUEST_URI_MAX_LENGTH=32768', '-DCPPHTTPLIB_TCP_NODELAY=1')
RETAINED_ROLE_BUILDS = {
    'client': {
        'executable_name': 'llama-server',
        'executable_sha256': '1058266e497df92d919177702f55131b4675e107c2b316973ec72b35dd999987',
        'backend_libraries': (('libllama-full.a', '6bafcb05a5188e287117d5df9d2b36798bf95c92640317697b26d2af0f5138c6'),),
    },
    'remote': {
        'executable_name': 'ggml-rpc-server',
        'executable_sha256': '5f535dd9693f6b82ce132c24566c662ad8b2c85aa25a863ddd741cae5af0bb35',
        'backend_libraries': (('libggml-static.a', 'f516d3630131a2309f3845cf3c204cc74738836e288d4ee7f313ef3728dbeff6'),),
    },
}


def _retained_role_build(participant, retained_builds=None) -> dict:
    role = participant.role
    table = RETAINED_ROLE_BUILDS if retained_builds is None else retained_builds
    retained = table.get(role)
    if retained is None:
        raise CollectorError('no retained derived-build identity for role: ' + str(role))
    return retained



class NativeObserverCollector:
    """Bounded collector joining native exports to owned lifecycle facts."""

    def __init__(self, transport: SSHCollectorTransport | None = None,
                 identity_reader: ProcIdentityReader | None = None,
                 retained_builds=None, host_facts_reader: 'HostFactsReader | None' = None, *, selective=False):
        self.selective=selective
        self.transport = transport or SSHCollectorTransport()
        self.identity_reader = identity_reader or ProcIdentityReader(self.transport)
        # Independent remote host-facts seam (#302 P1-C): boot/topology
        # epochs observed at collection time, listener/environment joined by
        # the caller from trusted seams.
        self.host_facts_reader = host_facts_reader or HostFactsReader(self.transport)
        # The retained per-role build pins are production constants; the
        # optional injection exists only so offline tests can rebind the
        # executable-byte pin to synthetic binaries while keeping the
        # genuine overlay/backend-closure identities.
        self.retained_builds = RETAINED_ROLE_BUILDS if retained_builds is None else retained_builds


    def collect_static(self, participant, spawn: OwnedSpawnFacts, manifest_path: str,
                       executable_path: str, source_receipt_digest: str, *,
                       expected_argv: tuple[str, ...],
                       listener_endpoints: tuple[str, ...] = ()) -> ParticipantStaticEvidence:
        build = self.collect_build(participant, manifest_path, executable_path)
        identity = self.identity_reader.read(participant, spawn.pid,
            expected_executable=participant.runtime_executable,
            expected_sha256=participant.runtime_sha256,
            expected_argv=expected_argv)
        if identity.pid != spawn.pid or identity.start != spawn.start:
            raise CollectorError('owned identity pid/start mismatch: '
                                 + participant.participant_id)
        host_facts = self.host_facts_reader.read(participant,
            listening=listener_endpoints or (),
            environment=thaw(identity.visibility).get('environment'))
        # The observed pre-request inventory family is deliberately absent:
        # the retained #301 producer cannot emit it before POST, and
        # reconciliation fails closed naming that missing capability.
        return ParticipantStaticEvidence(participant.participant_id, identity, spawn, build,
                                         source_receipt_digest,
                                         observed_host_facts=host_facts)

    def collect_build(self, participant, manifest_path,
                      executable_path, *, backend='cpu'):
        body = self.transport.read_json(participant.execution_address, manifest_path,
                                        max_bytes=SSHCollectorTransport.MANIFEST_MAX_BYTES)
        manifest = parse_build_manifest(body)
        executable = self.transport.read_bytes(participant.execution_address, executable_path,
                                               max_bytes=SSHCollectorTransport.EXECUTABLE_MAX_BYTES)
        import hashlib
        digest = hashlib.sha256(executable).hexdigest()
        if digest != manifest.executable_sha256:
            raise CollectorError('derived build executable bytes do not match manifest: '
                                 + participant.participant_id)
        if self.selective:
            from ..assigned_backing import role_identity
            # backend names which reviewed identity table row applies; the
            # loader/client role is always the CPU build (role_identity refuses
            # a CUDA identity for it), and an unreviewed CUDA row refuses.
            expected=role_identity(participant.role, backend)
            if manifest != expected or digest != participant.runtime_sha256:
                raise CollectorError('selective backing unreviewed per-role derived build identity')
            return DerivedBuildEvidence(manifest,digest)
        # Explicit per-role derived-build qualification: the manifest must
        # descend from the retained authenticated #301 producer artifacts
        # for THIS participant's role (llama-server closes over
        # libllama-full.a; ggml-rpc-server closes over libggml-static.a),
        # not merely be self-consistent. A foreign patch/transformed/
        # compiler/flag identity, a swapped role deployment, or a foreign
        # backend closure is a named refusal even when the executable bytes
        # match.
        retained = _retained_role_build(participant, self.retained_builds)
        if manifest.executable_sha256 != retained['executable_sha256']:
            raise CollectorError('derived build executable identity is not the retained '
                                 'authenticated #' + '301 ' + retained['executable_name']
                                 + ' build for this role: ' + participant.participant_id)
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
        if tuple(manifest.backend_libraries) != tuple(retained['backend_libraries']):
            raise CollectorError('derived build backend libraries are not the retained '
                                 'authenticated #' + '301 ' + retained['executable_name']
                                 + ' closure for this role: ' + participant.participant_id)
        return DerivedBuildEvidence(manifest, digest)

    def await_terminal_export(self, participant, spawn: OwnedSpawnFacts,
                               export_dir: str, native_label: str, *,
                               timeout: float = 60.0, pause: float = 0.2):
        """Deterministic exact-owned terminal-export fence (#302 P2).

        The retained producer writes its dynamic envelope at owned-process
        termination (server_queue::terminate / RPC connection close), which
        can land slightly AFTER the controller observed process exit. Before
        any output is accepted, the controller waits (bounded) until the
        export directory holds a terminal dynamic envelope belonging to THIS
        owned spawn: filename '<label>-<pid>-%04d.json' with the owned pid.
        Missing, foreign-pid, malformed-name or never-arriving exports are
        named refusals, never silent acceptance.
        """
        import time as _time
        deadline = _time.monotonic() + timeout
        wanted = '%s-%d-' % (native_label, spawn.pid)
        while True:
            try:
                names = self.transport.list_dir(participant.execution_address, export_dir)
            except CollectorError:
                names = []
            terminal = [name for name in names
                        if name.endswith('.json')
                        and name.startswith(wanted)]
            if terminal:
                # The envelope must actually be the terminal dynamic stream
                # of this owned spawn, not a name-shaped placeholder; a
                # partially-written file (still .tmp or nonterminal) keeps
                # waiting until the deadline.
                try:
                    for name in sorted(terminal):
                        payload = self.transport.read_bytes(
                            participant.execution_address,
                            str(Path(export_dir) / name),
                            max_bytes=SSHCollectorTransport.ENVELOPE_MAX_BYTES)
                        candidate = parse_observation(TransportReply(0, payload))
                        if (candidate.phase == 'dynamic'
                                and candidate.stream_kind == 'whole'
                                and candidate.terminal
                                and candidate.participant_id == native_label):
                            return sorted(terminal)
                except CollectorError:
                    pass
            if _time.monotonic() >= deadline:
                raise CollectorError(
                    'terminal export for owned spawn did not complete before output '
                    'acceptance: ' + participant.participant_id)
            _time.sleep(pause)

    def collect_dynamic(self, participant, spawn: OwnedSpawnFacts, export_dir: str,
                        plan_digest: str, invocation_token: str,
                        native_label: str) -> ParticipantDynamicEvidence:
        # The retained producer writes the claim as plaintext
        # 'PID\nSTART_TICKS\nLABEL\n' (is301_observer.h export_capture).
        raw = self.transport.read_bytes(participant.execution_address,
                                        str(Path(export_dir) / CLAIM_NAME),
                                        max_bytes=SSHCollectorTransport.CLAIM_MAX_BYTES)
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
                                                str(Path(export_dir) / name),
                                                max_bytes=SSHCollectorTransport.ENVELOPE_MAX_BYTES)
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
        # std::to_string(now_ns()) never emits a leading zero on the suffix.
        nanoseconds = None if gen is None else gen.group(3)
        if gen is None or gen.group(1) != str(claim_pid) \
                or gen.group(2) != str(ordinal) \
                or (nanoseconds.startswith('0') and nanoseconds != '0'):
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

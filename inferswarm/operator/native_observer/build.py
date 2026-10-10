"""Direct GCC stock CPU/RPC fixture recipe; intentionally not canonical CMake.

No model, GPU, installs, upstream writes, or observer/derived-patch claims.
Native compilation is explicit opt-in: python -m ...build --execute.
"""
from contextlib import contextmanager
import ctypes
from dataclasses import asdict, dataclass, field
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import shutil
import signal
import socket
import subprocess
import time
import stat
import tempfile
import uuid

PIN = 'b29c606e28a01b1bc8c1351026a0fa6e616bf6c4'
TREE = '950999fe62b7fe55f44ab5b7394e3c8542f37f12'
SCRATCH = Path('/home/zutfen/.hermes/cache/scratch/is299/native-build')
SOURCE = SCRATCH.parent / 'llama-src'
REPO = Path(__file__).resolve().parents[3]
FIXTURE = REPO / 'tests/fixtures/issue299/native-buffer-graph.cpp'
BASE = ['ggml.c', 'ggml.cpp', 'ggml-alloc.c', 'ggml-backend.cpp',
        'ggml-backend-meta.cpp', 'ggml-opt.cpp', 'ggml-threading.cpp', 'ggml-quants.c', 'gguf.cpp']
CPU = ['ggml-cpu.c', 'ggml-cpu.cpp', 'repack.cpp', 'iqp.cpp', 'hbm.cpp', 'quants.c',
       'traits.cpp', 'amx/amx.cpp', 'amx/mmq.cpp', 'binary-ops.cpp', 'unary-ops.cpp',
       'vec.cpp', 'ops.cpp', 'arch/x86/quants.c', 'arch/x86/repack.cpp']
SOURCES = (['ggml/src/' + p for p in BASE] +
           ['ggml/src/ggml-backend-dl.cpp', 'ggml/src/ggml-backend-reg.cpp'] +
           ['ggml/src/ggml-cpu/' + p for p in CPU] +
           ['ggml/src/ggml-rpc/ggml-rpc.cpp', 'ggml/src/ggml-rpc/transport.cpp',
            'tools/rpc/rpc-server.cpp'])


class BuildError(RuntimeError):
    """Fail closed and preserve the exact failing step."""


@dataclass(frozen=True)
class Limits:
    as_bytes: int = 3 << 30
    rss_bytes: int = 4 << 30
    file_bytes: int = 256 << 20
    artifact_bytes: int = 4 << 30
    disk_floor: int = 16 << 30
    phase_seconds: float = 1800
    cumulative_seconds: float = 5400
    fixture_seconds: float = 60
    jobs: int = 1

    def __post_init__(self):
        ceilings = {'as_bytes': 3 << 30, 'rss_bytes': 4 << 30,
                    'file_bytes': 256 << 20, 'artifact_bytes': 4 << 30,
                    'phase_seconds': 1800, 'cumulative_seconds': 5400,
                    'fixture_seconds': 60, 'jobs': 1}
        for key, ceiling in ceilings.items():
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= ceiling:
                raise ValueError('malformed or expanded bound: ' + key)
            if key.endswith('bytes') or key == 'jobs':
                if not isinstance(value, int):
                    raise ValueError('integer bound required: ' + key)
        if not isinstance(self.disk_floor, int) or isinstance(self.disk_floor, bool) or self.disk_floor < 16 << 30:
            raise ValueError('disk floor cannot be reduced')


@dataclass(frozen=True)
class Workspace:
    """One immutable root/lock/ledger authority; test roots confer no native authority."""
    root: Path

    def __post_init__(self):
        object.__setattr__(self, 'root', Path(self.root).resolve())

    @property
    def lock(self):
        return self.root / '.build.lock'

    @property
    def ledger(self):
        return self.root / 'ledger.json'


CAMPAIGN = Workspace(SCRATCH)


@dataclass(frozen=True)
class Issue301Authorization:
    """The user's one approved extension, not a configurable resource limit.

    Pass explicitly as Supervisor(..., authorization=Issue301Authorization()).
    validate(workspace, ledger_bytes) is pure and returns the validated ledger.
    No alternative workspace, starting history, or ceiling can be supplied.
    """
    issue: int = field(default=301, init=False)
    workspace_root: str = field(default='/home/zutfen/.hermes/cache/scratch/is299/native-build', init=False)
    original_seconds: int = field(default=5400, init=False)
    extra_seconds: int = field(default=1200, init=False)
    ceiling_seconds: int = field(default=6600, init=False)
    original_ledger_sha256: str = field(default='ca237e383609bef6c62414ef7c132e2d5716eb13a016e84960e67b0a326a5c04', init=False)
    original_phase_prefix_sha256: str = field(default='d0f56ae803fbc8b50048b8d3ecd786c6bf43982898a0e6be0d8ee1fd98a0962a', init=False)
    original_phase_count: int = field(default=94, init=False)
    start_consumption_seconds: float = field(default=5328.017504271702, init=False)

    def validate(self, workspace, ledger_bytes):
        """Authenticate the original bytes or an unchanged prefix plus receipts."""
        if str(workspace.root) != self.workspace_root:
            raise BuildError('issue301 authorization requires the exact campaign workspace')
        try:
            if not isinstance(ledger_bytes, bytes) or len(ledger_bytes) > 4 << 20:
                raise ValueError('missing or oversized original ledger')
            ledger = json.loads(ledger_bytes)
            if not isinstance(ledger, dict) or set(ledger) != {'elapsed_seconds', 'phases'}:
                raise ValueError('invalid ledger fields')
            def seconds(value):
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                    raise ValueError('invalid elapsed seconds')
                return value
            elapsed = seconds(ledger['elapsed_seconds'])
            phases = ledger['phases']
            if not isinstance(phases, list) or len(phases) < self.original_phase_count:
                raise ValueError('missing or truncated original ledger prefix')
            required = {'elapsed_seconds', 'peak_sampled_rss_bytes', 'reason', 'root'}
            for phase in phases:
                if not isinstance(phase, dict) or not required <= set(phase) or set(phase) - required - {'status'}:
                    raise ValueError('invalid phase fields')
                seconds(phase['elapsed_seconds'])
                peak = phase['peak_sampled_rss_bytes']
                if isinstance(peak, bool) or not isinstance(peak, int) or peak < 0:
                    raise ValueError('invalid sampled RSS')
                if not isinstance(phase['root'], str) or not isinstance(phase['reason'], str) or ('status' in phase and not isinstance(phase['status'], str)):
                    raise ValueError('invalid phase metadata')
            total = math.fsum(phase['elapsed_seconds'] for phase in phases)
            if not math.isclose(total, elapsed, rel_tol=0, abs_tol=1e-9):
                raise ValueError('phase sum does not match cumulative elapsed seconds')
            prefix = phases[:self.original_phase_count]
            prefix_bytes = json.dumps(prefix, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
            if hashlib.sha256(prefix_bytes).hexdigest() != self.original_phase_prefix_sha256:
                raise ValueError('original phase entries changed')
            if not math.isclose(math.fsum(phase['elapsed_seconds'] for phase in prefix), self.start_consumption_seconds, rel_tol=0, abs_tol=1e-9):
                raise ValueError('original consumption changed')
            # Reconstruct the pinned original envelope on continuation, never
            # truncate or write it. All original entries remain in the live list.
            original = {'elapsed_seconds': self.start_consumption_seconds, 'phases': prefix}
            original_bytes = (json.dumps(original, indent=2, sort_keys=True) + '\n').encode()
            if hashlib.sha256(original_bytes).hexdigest() != self.original_ledger_sha256:
                raise ValueError('original ledger digest changed')
            if len(phases) == self.original_phase_count and hashlib.sha256(ledger_bytes).hexdigest() != self.original_ledger_sha256:
                raise ValueError('original ledger bytes changed')
            return ledger
        except (ValueError, KeyError, TypeError, OverflowError) as error:
            raise BuildError('invalid issue301 continuous ledger: ' + str(error)) from error


def output_root(path, workspace=CAMPAIGN):
    path = Path(path).resolve()
    if path == workspace.root or not path.is_relative_to(workspace.root):
        raise BuildError('outputs must remain in authorized scratch')
    return path


def git(source, *args):
    return subprocess.check_output(['git', '-C', str(source), *args], timeout=30)


def _read_bounded(path, ceiling=256 << 20):
    """Bound regular-file reads; do not follow input symlinks."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > ceiling:
                raise BuildError('input file bound/type violated: ' + str(path))
            data = stream.read(ceiling + 1)
    except OSError as error:
        raise BuildError('unreadable input: ' + str(path)) from error
    if len(data) > ceiling:
        raise BuildError('input file bound violated: ' + str(path))
    return data


def verify_blob(path, blob):
    data = _read_bounded(path)
    actual = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
    if actual != blob:
        raise BuildError('changed pinned source: ' + str(path))
    return {'blob': blob, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}


def validate_identity(identity, pin=PIN):
    """Pure rejection predicate, not authorization for native execution."""
    if pin != PIN or list(identity) != [PIN, TREE]:
        raise BuildError('native base identity mismatch')


def authenticate(source, pin=PIN):
    source = Path(source).resolve()
    identity = git(source, 'rev-parse', 'HEAD', 'HEAD^{tree}').decode().splitlines()
    validate_identity(identity, pin)
    # Authenticate all GGML inputs plus the actual server target and build rules.
    result = {}
    for row in git(source, 'ls-tree', '-rz', PIN, '--', 'ggml', 'tools/rpc', 'cmake').split(b'\0'):
        if not row:
            continue
        meta, name = row.split(b'\t', 1)
        mode, kind, blob = meta.decode().split()
        name = name.decode()
        if kind != 'blob' or mode not in ('100644', '100755'):
            raise BuildError('unsupported source entry: ' + name)
        path = source / name
        if path.is_symlink() or not path.resolve().is_relative_to(source):
            raise BuildError('source path escaped pin: ' + name)
        result[name] = verify_blob(path, blob)
    return result


def recipe(source=SOURCE, output=SCRATCH / 'stock', target='cpu-rpc'):
    """Real Git discovery/authentication; portable controls call pure assembly."""
    if target != 'cpu-rpc':
        raise BuildError('unknown target; only cpu-rpc fixture closure is supported')
    inputs = authenticate(source)
    short = git(source, 'rev-parse', '--short', PIN).decode().strip()
    return assemble_recipe(source, output, inputs, [PIN, TREE], short, target=target)


def assemble_recipe(source, output, inputs, identity, short_commit, *,
                    target='cpu-rpc', workspace=CAMPAIGN):
    """No-effects command assembly; supplied metadata never enables execute()."""
    if target != 'cpu-rpc':
        raise BuildError('unknown target; only cpu-rpc fixture closure is supported')
    source, output = Path(source).resolve(), output_root(output, workspace)
    if os.uname().machine != 'x86_64':
        raise BuildError('recipe only authenticated for Linux x86_64')
    validate_identity(identity)
    if not isinstance(short_commit, str) or not 7 <= len(short_commit) <= 40 or not PIN.startswith(short_commit):
        raise BuildError('native short identity mismatch')
    flags = ['-O0', '-g0', '-pthread', '-D_GNU_SOURCE', '-D_XOPEN_SOURCE=600',
             '-DGGML_SCHED_MAX_COPIES=4', '-DGGML_USE_CPU', '-DGGML_USE_RPC']
    includes = [source / 'ggml/include', source / 'ggml/src', source / 'ggml/src/ggml-cpu', output]
    commands = []
    objects = []
    for index, name in enumerate(SOURCES):
        src = source / name
        obj = output / f'{index:02d}.o'
        compiler = '/usr/bin/cc' if src.suffix == '.c' else '/usr/bin/c++'
        commands.append([compiler, '-std=c11' if src.suffix == '.c' else '-std=c++17',
                         *flags, *['-I' + str(p) for p in includes], '-MD', '-MF',
                         str(output / f'{index:02d}.d'), '-c', str(src), '-o', str(obj)])
        objects.append(str(obj))
    commands.append(['/usr/bin/c++', '-std=c++17', *flags, *['-I' + str(p) for p in includes],
                     '-MD', '-MF', str(output / 'fixture.d'), '-c', str(FIXTURE), '-o', str(output / 'fixture.o')])
    libraries = ['-pthread', '-ldl', '-lm']
    commands.append(['/usr/bin/c++', *objects, *libraries, '-o', str(output / 'ggml-rpc-server')])
    commands.append(['/usr/bin/c++', *objects[:-1], str(output / 'fixture.o'), *libraries,
                     '-o', str(output / 'native-buffer-graph')])
    return {'base_revision': PIN, 'base_tree': TREE, 'patch': None, 'target': target,
            'kind': 'independent direct GCC stock CPU/RPC fixture; not upstream CMake',
            'sources': SOURCES, 'inputs': inputs, 'commands': commands, 'flags': flags,
            'features': {'native': False, 'openmp': False, 'rdma': False, 'cpu_repack': False,
                         'llamafile': False, 'backend_dl': False, 'shared_libraries': False,
                         'x86_optional_isa': False, 'gpu': False},
            'template_options': {'GGML_VERSION': '0.24.0',
                                 'GGML_BUILD_COMMIT': short_commit}}


def _safe_metadata(path):
    path = Path(path)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise BuildError('unsafe metadata output: ' + str(path))
    return path


def dump(path, data):
    """Atomic metadata replacement without following a preexisting symlink."""
    path = _safe_metadata(path)
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(json.dumps(data, indent=2, sort_keys=True) + '\n')
        _safe_metadata(path)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def _exclusive_output(path):
    try:
        return open(path, 'xb')
    except OSError as error:
        raise BuildError('existing output or unavailable output: ' + str(path)) from error


def proc_stat(pid):
    text = Path(f'/proc/{pid}/stat').read_text()
    return text[text.rfind(')') + 2:].split()


def group_rss(groups):
    total = 0
    for path in Path('/proc').iterdir():
        if not path.name.isdigit():
            continue
        try:
            fields = proc_stat(path.name)
            if int(fields[2]) in groups:
                total += int(fields[21]) * os.sysconf('SC_PAGE_SIZE')
        except (OSError, ValueError, IndexError):
            continue  # sampling races; hard AS limits remain inherited
    return total


class Supervisor:
    """One exclusive phase, serial children, hard exec limits, owned-group cleanup."""
    def __init__(self, root, limits=None, *, workspace=CAMPAIGN, authorization=None):
        self.workspace = workspace
        self.root = output_root(root, workspace)
        self.limits = limits or Limits()
        if authorization is not None:
            if type(authorization) is not Issue301Authorization:
                raise BuildError('unsupported cumulative budget authorization')
            if self.limits.cumulative_seconds != authorization.original_seconds:
                raise BuildError('issue301 authorization cannot override a tighter cumulative limit')
        self.authorization = authorization
        # Expanded authority is applied only after loading the continuous ledger.
        self.cumulative_seconds = self.limits.cumulative_seconds
        self.rows = []
        self.active = {}
        self.servers = {}
        self.peak = 0
        self.previous_subreaper = None
        self.ledger = None

    def _restore_subreaper(self):
        if self.previous_subreaper is not None and not self.active:
            if ctypes.CDLL(None, use_errno=True).prctl(36, self.previous_subreaper, 0, 0, 0) != 0:
                raise BuildError('cannot restore Linux child subreaper')
            self.previous_subreaper = None

    def _load_ledger(self):
        self.ledger_path = self.workspace.ledger
        self.ledger = None
        self.cumulative_seconds = self.limits.cumulative_seconds
        try:
            if self.authorization is not None:
                # Never initialize a missing extension ledger; authenticate the
                # exact original history before permitting any new accounting.
                ledger = self.authorization.validate(
                    self.workspace, _read_bounded(self.ledger_path, 4 << 20))
            elif self.ledger_path.exists() or self.ledger_path.is_symlink():
                ledger = json.loads(_read_bounded(self.ledger_path, 4 << 20))
            else:
                ledger = {'elapsed_seconds': 0, 'phases': []}
            elapsed = ledger['elapsed_seconds']
            if isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)) or not math.isfinite(elapsed) or elapsed < 0 or not isinstance(ledger['phases'], list):
                raise ValueError('invalid ledger fields')
            self.ledger = ledger
            if self.authorization is not None:
                self.cumulative_seconds = self.authorization.ceiling_seconds
        except (BuildError, ValueError, KeyError, TypeError) as error:
            raise BuildError('malformed build ledger: ' + str(error)) from error

    def _charge(self, reason, status):
        elapsed = time.monotonic() - self.start
        receipt = {'root': str(self.root), 'elapsed_seconds': elapsed,
                   'peak_sampled_rss_bytes': self.peak, 'reason': reason, 'status': status}
        if self.ledger is not None:
            self.ledger['elapsed_seconds'] += elapsed
            self.ledger['phases'].append(receipt)
            dump(self.ledger_path, self.ledger)
        return receipt

    def __enter__(self):
        self.workspace.root.mkdir(parents=True, exist_ok=True)
        try:
            self.lock = os.fdopen(os.open(self.workspace.lock, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600), 'w')
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            if hasattr(self, 'lock'):
                self.lock.close()
            raise BuildError('native build ledger is locked or unsafe') from error
        self.start = time.monotonic()
        exhausted = False
        try:
            self._load_ledger()
            if self.ledger['elapsed_seconds'] >= self.cumulative_seconds:
                exhausted = True
                raise BuildError('cumulative wall budget exhausted')
            # Process-wide policy is temporary. Supported commands do not detach;
            # this is owned PROCESS-GROUP cleanup, not arbitrary tree confinement.
            libc = ctypes.CDLL(None, use_errno=True)
            previous = ctypes.c_int()
            if libc.prctl(37, ctypes.byref(previous), 0, 0, 0) != 0:
                raise BuildError('cannot read Linux child subreaper')
            self.previous_subreaper = previous.value
            if libc.prctl(36, 1, 0, 0, 0) != 0:
                raise BuildError('cannot enable Linux child subreaper')
            try:
                self.root.mkdir(parents=True, exist_ok=False)
            except FileExistsError as error:
                raise BuildError('existing output directory; choose a fresh run') from error
            self.check_storage()
            dump(self.root / 'envelope.json', {'limits': asdict(self.limits),
                 'authorization': asdict(self.authorization) if self.authorization is not None else None,
                 'effective_cumulative_seconds': self.cumulative_seconds,
                 'start_unix': time.time(), 'meminfo': Path('/proc/meminfo').read_text(),
                 'disk': dict(zip(('total', 'used', 'free'), shutil.disk_usage(self.workspace.root))),
                 'rss_sampling_seconds': .05,
                 'rss_limitation': 'sum of owned non-detaching process groups; sampling may miss short peaks, shared pages counted per process; hard AS per process',
                 'server_deadline_limitation': 'synchronous body must call check/run/readiness; arbitrary blocking context bodies unsupported'})
            return self
        except BaseException as error:
            try:
                if not exhausted:
                    receipt = self._charge(str(error), 'admission refused')
                    dump(self.workspace.root / ('admission-refusal-' + uuid.uuid4().hex + '.json'), receipt)
            except BaseException as accounting_error:
                # Never replace an invalid prior ledger or obscure the refusal.
                error.add_note('admission accounting failed: ' + str(accounting_error))
            finally:
                try:
                    self._restore_subreaper()
                finally:
                    self.lock.close()
            raise

    def __exit__(self, kind, error, trace):
        try:
            for child in list(self.active.values()):
                self.stop(child)
            self._charge(str(error) if error else 'completed', 'finished')
            dump(self.root / 'execution.json', self.rows)
        except BaseException as cleanup_error:
            if error is None:
                raise
            error.add_note('supervisor cleanup/accounting failed: ' + str(cleanup_error))
        finally:
            try:
                self._restore_subreaper()
            finally:
                self.lock.close()

    def check_storage(self, free_bytes=None, artifact_bytes=None):
        if free_bytes is None:
            free_bytes = shutil.disk_usage(self.workspace.root).free
        if artifact_bytes is None:
            artifact_bytes = sum(p.lstat().st_size for p in self.workspace.root.rglob('*') if p.is_file() or p.is_symlink())
        if free_bytes < self.limits.disk_floor:
            raise BuildError('disk floor violated')
        if artifact_bytes > self.limits.artifact_bytes:
            raise BuildError('artifact budget violated')

    def remaining_server_seconds(self):
        if not self.servers:
            return None
        return min(deadline for _, deadline in self.servers.values()) - time.monotonic()

    def _check_server_deadline(self):
        remaining = self.remaining_server_seconds()
        if remaining is not None and remaining <= 0:
            raise BuildError('server fixture wall deadline exceeded')

    def check(self):
        self._check_server_deadline()
        elapsed = time.monotonic() - self.start
        if elapsed > self.limits.phase_seconds or elapsed + self.ledger['elapsed_seconds'] > self.cumulative_seconds:
            raise BuildError('phase/cumulative wall budget exceeded')
        rss = group_rss(set(self.active))
        self.peak = max(self.peak, rss)
        if rss > self.limits.rss_bytes:
            raise BuildError('owned RSS budget exceeded')
        self.check_storage()
        self._check_server_deadline()  # scans may consume the remaining budget

    def exec_limits(self):
        resource.setrlimit(resource.RLIMIT_AS, (self.limits.as_bytes,) * 2)
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_FSIZE, (self.limits.file_bytes,) * 2)

    def spawn(self, command, env_extra=None):
        self.check()
        index = len(self.rows)
        row = {'command': list(map(str, command)), 'start_unix': time.time(),
               'stdout': str(self.root / f'step-{index:03d}.stdout'),
               'stderr': str(self.root / f'step-{index:03d}.stderr')}
        env = {'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'OMP_NUM_THREADS': '1',
               'HOME': str(self.root), 'LLAMA_CACHE': str(self.root / 'cache')}
        if env_extra:
            bad = set(env_extra) - {'IS301_OBSERVE', 'IS301_RPC_ENDPOINT',
                                    'IS301_EXPORT_DIR'}
            if bad or not all(isinstance(v, str) for v in env_extra.values()):
                raise BuildError('unsupported supervised environment extension')
            env.update(env_extra)
        start = time.monotonic()
        with _exclusive_output(row['stdout']) as out, _exclusive_output(row['stderr']) as err:
            child = subprocess.Popen(row['command'], cwd=self.root, env=env, stdout=out,
                                     stderr=err, start_new_session=True, preexec_fn=self.exec_limits)
        self.active[child.pid] = child
        row['pid'] = child.pid
        row['start_ticks'] = proc_stat(child.pid)[19]
        self.rows.append(row)
        return child, row, start

    def stop(self, child):
        # Always kill the OWNED group, including descendants when leader exited.
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.wait(timeout=5)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                pid, _ = os.waitpid(-child.pid, os.WNOHANG)
                if pid == 0:
                    time.sleep(.01)
                    continue
            except ChildProcessError:
                break
        else:
            raise BuildError('owned descendant reaping deadline exceeded')
        self.active.pop(child.pid, None)

    def run(self, command, seconds=None, env_extra=None):
        seconds = self.limits.phase_seconds if seconds is None else seconds
        if not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or not 0 < seconds <= self.limits.phase_seconds:
            raise ValueError('malformed child deadline')
        child, row, start = self.spawn(command, env_extra)
        reason = 'completed'
        deadline = start + seconds
        remaining = self.remaining_server_seconds()
        if remaining is not None:
            deadline = min(deadline, time.monotonic() + remaining)
        try:
            while child.poll() is None:
                self.check()
                if time.monotonic() > deadline:
                    self._check_server_deadline()
                    reason = 'wall'
                    raise BuildError('child wall deadline exceeded')
                time.sleep(min(.05, max(0, deadline - time.monotonic())))
            self.check()  # no success/output acceptance after a server deadline
            if child.returncode:
                reason = f'exit {child.returncode}'
                raise BuildError(reason + ': ' + ' '.join(row['command']))
            return row
        except BaseException as error:
            if reason == 'completed':
                reason = str(error)
            raise
        finally:
            self.stop(child)
            row.update(exit_code=child.returncode, reason=reason,
                       elapsed_seconds=time.monotonic() - start, peak_sampled_phase_rss_bytes=self.peak)
            dump(self.root / 'execution.json', self.rows)
            self.check_storage()

    @contextmanager
    def server(self, command, env_extra=None):
        """Checked synchronous bodies only; no autonomous blocking-body watchdog."""
        child, row, start = self.spawn(command, env_extra)
        self.servers[child.pid] = (start, start + self.limits.fixture_seconds)
        try:
            yield child
            self.check()
            row['reason'] = 'owned server reaped'
        except BaseException as error:
            row['reason'] = str(error)
            raise
        finally:
            self.stop(child)
            self.servers.pop(child.pid, None)
            row.update(exit_code=child.returncode, elapsed_seconds=time.monotonic() - start,
                       peak_sampled_phase_rss_bytes=self.peak)
            dump(self.root / 'execution.json', self.rows)


def wait_listener(supervisor, child, port):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        supervisor.check()
        if child.poll() is not None:
            raise BuildError('RPC server exited before listening')
        inodes = {p.readlink().name for p in Path(f'/proc/{child.pid}/fd').iterdir() if p.is_symlink()}
        for row in Path('/proc/net/tcp').read_text().splitlines()[1:]:
            fields = row.split()
            if fields[1] == f'0100007F:{port:04X}' and fields[3] == '0A' and f'socket:[{fields[9]}]' in inodes:
                supervisor.check()  # listener success cannot bypass deadline
                return
        remaining = supervisor.remaining_server_seconds()
        time.sleep(.05 if remaining is None else min(.05, max(0, remaining)))
    supervisor.check()
    raise BuildError('owned loopback listener readiness timeout')


def _dep_paths(depfile, cwd):
    """Bounded single GCC -MD Make rule (no variables, comments or phony rules).

    Support escaped space/tab/#/:/backslash and backslash-newline folds.
    Reject all other Make syntax rather than accepting an incomplete closure.
    """
    depfile = Path(depfile)
    if not depfile.is_file():
        raise BuildError('missing depfile: ' + str(depfile))
    try:
        text = _read_bounded(depfile, 4 << 20).decode('utf-8')
    except (BuildError, UnicodeError) as error:
        raise BuildError('unsupported depfile: unreadable encoding/size/type') from error
    words, token, targets, separator = [], [], [], False
    index = 0
    ended = False
    def flush():
        if token:
            words.append(''.join(token))
            token.clear()
    while index < len(text):
        char = text[index]
        if char == '\\':
            index += 1
            if index == len(text):
                raise BuildError('unsupported depfile: trailing escape')
            escaped = text[index]
            if escaped == '\n':
                flush()
            elif escaped in ' \t#:\\':
                if ended:
                    raise BuildError('unsupported depfile: multiple rules')
                token.append(escaped)
            else:
                raise BuildError('unsupported depfile: escape')
        elif char == ':':
            if separator or ended:
                raise BuildError('unsupported depfile: target separator')
            flush()
            targets = words[:]
            words.clear()
            if not targets:
                raise BuildError('unsupported depfile: empty target')
            separator = True
        elif char in ' \t\n':
            flush()
            if char == '\n':
                ended = True
        elif char in '#$|;%=*?[]' or ord(char) < 32 or ord(char) == 127:
            raise BuildError('unsupported depfile: Make syntax/control character')
        else:
            if ended:
                raise BuildError('unsupported depfile: multiple rules')
            token.append(char)
        index += 1
        if len(words) > 100000:
            raise BuildError('unsupported depfile: dependency count bound')
    flush()
    if not separator or not words:
        raise BuildError('unsupported depfile: missing target/dependencies')
    result = []
    for name in words:
        path = Path(name)
        path = path if path.is_absolute() else Path(cwd) / path
        if not path.is_file():
            raise BuildError('missing dependency: ' + str(path))
        result.append(path.resolve())
    return result


def compiled_inputs(depfiles, cwd):
    """Exact real-file hashes, shared by portable controls and execute()."""
    depfiles = list(depfiles)
    if not depfiles or len(depfiles) > 1000:
        raise BuildError('unsupported depfile: missing/excessive dependency files')
    inputs = {}
    for dep in depfiles:
        for path in _dep_paths(dep, cwd):
            if str(path) not in inputs:
                inputs[str(path)] = hashlib.sha256(_read_bounded(path)).hexdigest()
    return inputs


def execute(source=SOURCE, output=SCRATCH / 'stock', *, workspace=CAMPAIGN):
    if workspace != CAMPAIGN:
        raise BuildError('unauthorized native workspace')
    output = output_root(output, workspace)
    # Real authentication cannot be substituted with a supplied recipe manifest.
    # Refuse an invalid source before acquiring/charging campaign authority.
    r = recipe(source, output)
    with Supervisor(output, workspace=workspace) as supervisor:
        dump(output / 'recipe.json', r)
        version = (Path(source) / 'ggml/src/ggml-version.h.in').read_text() \
            .replace('@GGML_VERSION@', r['template_options']['GGML_VERSION']) \
            .replace('@GGML_BUILD_COMMIT@', r['template_options']['GGML_BUILD_COMMIT'])
        with _exclusive_output(output / 'ggml-version.h') as stream:
            stream.write(version.encode())
        for compiler in ('/usr/bin/cc', '/usr/bin/c++'):
            supervisor.run([compiler, '--version'])
        for command in r['commands']:
            supervisor.run(command)
        supervisor.run([str(output / 'native-buffer-graph')], seconds=supervisor.limits.fixture_seconds)
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            port = reservation.getsockname()[1]
        command = [str(output / 'ggml-rpc-server'), '-H', '127.0.0.1', '-p', str(port), '-d', 'CPU', '-t', '1']
        with supervisor.server(command) as server:
            wait_listener(supervisor, server, port)
            supervisor.run([str(output / 'native-buffer-graph'), f'127.0.0.1:{port}'],
                           seconds=supervisor.limits.fixture_seconds)
        final_inputs = authenticate(source)
        if final_inputs != r['inputs']:
            raise BuildError('native source changed during build')
        depfiles = [Path(c[c.index('-MF') + 1]) for c in r['commands'] if '-MF' in c]
        headers = compiled_inputs(depfiles, output)
        artifacts = {str(p): {'sha256': hashlib.sha256(p.read_bytes()).hexdigest(), 'bytes': p.stat().st_size}
                     for p in output.iterdir() if p.is_file() and p.suffix in ('.o', '.h', '.d') or p in (output / 'ggml-rpc-server', output / 'native-buffer-graph')}
        dump(output / 'provenance.json', {'base_revision': PIN, 'base_tree': TREE, 'patch': None,
             'recipe_sha256': hashlib.sha256((output / 'recipe.json').read_bytes()).hexdigest(),
             'builder_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
             'fixture_sha256': hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
             'compiled_inputs': headers, 'artifacts': artifacts,
             'verdict': 'stock native CPU and loopback SET/GET/ADD passed; not observer proof'})
    return output


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--source', type=Path, default=SOURCE)
    parser.add_argument('--output', type=Path, default=SCRATCH / 'stock')
    args = parser.parse_args()
    if args.execute:
        print(execute(args.source, args.output))
    else:
        print(json.dumps(recipe(args.source, args.output), sort_keys=True, indent=2))

"""Controller-owned durable evidence retention for the #313 campaign.

The experimental two-CUDA driver runs against remote lifecycle namespaces it
does not own durably: invocation directories live on the workers, and an
observation refusal or later host-side disappearance can leave the controller
with a receipt but no raw bytes.  This module gives the controller one fresh,
token-bound directory OUTSIDE those namespaces and preserves, on every exit
path:

* the complete sole HTTP response JSON as received (before any later
  validation or observation collection can fail);
* original bytes from each owned process independently (rpc0, rpc1, client):
  native export envelopes, the plaintext ``is301-claim`` ownership claim and
  the bounded native log tail -- malformed or dropped-event exports are
  preserved before parsing;
* a manifest-last SHA-256 ledger with per-artifact success/missing/error
  status and exact size/hash rows.

Hard rules (IS326 follow-up):

* Never raise past the caller: retention failure must not bypass stopping
  owned processes, releasing leases, closing owned transports or stopping
  aggregate slices.  Every public method swallows per-artifact failures into
  honest status rows instead.
* Bounded always: finite per-file, per-process file-count, total-byte and
  wall-time budgets; a symlink, a path escape, an oversized or a partially
  copied artifact is recorded as incomplete, never as collected.  Log
  retention keeps the LAST ``max_log_bytes`` bytes with an explicit
  truncation record; export envelopes keep whole-file limits and refusal.
* Honest identity: each attempted process is registered BEFORE its launch
  is dispatched (``register_attempt``), so a lost spawn reply still leaves
  its role and artifact paths with an unknown (``null``) PID/start -- never
  a fabricated identity -- and an omitted process keeps ``complete`` false.
* Manifest finalized on every catchable exit, including
  KeyboardInterrupt/SystemExit after the owned cleanup path; no recovery is
  promised for SIGKILL or power loss.
* Sensitive content: artifacts are 0600 inside a 0700 directory, never logged,
  never published automatically; the manifest carries hashes and statuses
  only.

Trust assumption (deliberately narrow): trusted experiment hosts,
invocation-owned directories, and the bounded pinned producers that write
them.  The read-only probes defend against symlinks and non-regular files
at the target path, but no ancestor-symlink traversal defense or
directory-enumeration redesign is claimed or implemented here.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import time

from .native_observer.collector import CLAIM_NAME


EVIDENCE_SCHEMA = 'q8-experimental-evidence-retention/1'
IDENTITY_NAME = 'identity.json'
MANIFEST_NAME = 'MANIFEST.json'
RESPONSE_NAME = 'http-response.json'

# Read-only remote probes over the fixed command runner (argv-only, like
# SSHCommandRunner).  One program lists a directory with lstat types/sizes so
# symlinks and non-regular entries are rejected without materializing them;
# the other streams at most bound+1 bytes base64-encoded so the bound is
# enforced by the reader, not trusted after the fact.  A missing directory is
# a distinct observable, not an error, so a process that never spawned
# records an honest 'missing' row.
STAT_PROGRAM = (
    "import json,os,stat,sys\n"
    "try:\n"
    "    names=sorted(os.listdir(sys.argv[1]))\n"
    "except OSError as exc:\n"
    "    print(json.dumps({'missing':True} if exc.errno==2 else {'error':str(exc)}))\n"
    "    sys.exit(0)\n"
    "out={}\n"
    "for name in names:\n"
    "    try: st=os.lstat(os.path.join(sys.argv[1],name))\n"
    "    except OSError as exc:\n"
    "        out[name]={'type':'error','error':str(exc)}\n"
    "        continue\n"
    "    if stat.S_ISLNK(st.st_mode): out[name]={'type':'symlink'}\n"
    "    elif stat.S_ISREG(st.st_mode): out[name]={'type':'file','size':st.st_size}\n"
    "    else: out[name]={'type':'other'}\n"
    "print(json.dumps(out))\n")

READ_PROGRAM = (
    "import base64,os,stat,sys\n"
    "limit=int(sys.argv[2])\n"
    "fd=os.open(sys.argv[1],os.O_RDONLY|os.O_NOFOLLOW)\n"
    "try:\n"
    "    if not stat.S_ISREG(os.fstat(fd).st_mode): sys.exit(4)\n"
    "    data=b''\n"
    "    while len(data)<=limit:\n"
    "        chunk=os.read(fd,min(1<<20,limit+1-len(data)))\n"
    "        if not chunk: break\n"
    "        data+=chunk\n"
    "finally:\n"
    "    os.close(fd)\n"
    "sys.stdout.write(base64.b64encode(data).decode('ascii'))\n")

# Tail read for log retention: streams at most ``bound`` bytes from the END
# of the file (seek-based, one forward read of the final bound bytes) plus
# the original size, so an oversized log keeps its last bounded bytes with
# an explicit truncation record instead of being rejected whole.
TAIL_PROGRAM = (
    "import base64,os,stat,sys\n"
    "limit=int(sys.argv[2])\n"
    "fd=os.open(sys.argv[1],os.O_RDONLY|os.O_NOFOLLOW)\n"
    "try:\n"
    "    if not stat.S_ISREG(os.fstat(fd).st_mode): sys.exit(4)\n"
    "    size=os.fstat(fd).st_size\n"
    "    os.lseek(fd,max(0,size-limit),os.SEEK_SET)\n"
    "    data=b''\n"
    "    while len(data)<limit:\n"
    "        chunk=os.read(fd,min(1<<20,limit-len(data)))\n"
    "        if not chunk: break\n"
    "        data+=chunk\n"
    "finally:\n"
    "    os.close(fd)\n"
    "print(size)\n"
    "sys.stdout.write(base64.b64encode(data).decode('ascii'))\n")

# Frozen collection bounds.  The byte bounds mirror the collector families
# (8 MiB envelopes, 2,000,000 B log tail); the collection deadline fits well
# inside the reserved 1200 s cleanup budget so retention can never starve the
# real cleanup ordering that follows it.
MAX_FILE_BYTES = 8 << 20
MAX_LOG_BYTES = 2_000_000
MAX_RESPONSE_BYTES = 8 << 20
MAX_FILES_PER_PROCESS = 80
MAX_TOTAL_BYTES = 512 << 20
MAX_COLLECTION_SECONDS = 480
MANIFEST_RESERVE_SECONDS = 30
STAT_TIMEOUT_SECONDS = 60

_NAME = frozenset('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-')

# Statuses that do NOT contradict a complete ledger.  Every other status
# (missing, error, oversize, rejected-*, file-limit, budget, deadline,
# partial) makes 'complete' false.
_COLLECTED = 'collected'


def _safe_component(value):
    return (isinstance(value, str) and value not in ('', '.', '..')
            and _NAME.issuperset(value))


def _digest(value, label):
    if (not isinstance(value, str) or len(value) != 64
            or any(c not in '0123456789abcdef' for c in value)):
        raise ValueError(label + ' must be lowercase SHA-256')
    return value


class DurableEvidenceStore:
    """One invocation's controller-owned evidence destination.

    Created fresh before launch (:meth:`create` refuses an existing
    destination, so one invocation can never overwrite another); finalized
    exactly once with the manifest written last.
    """

    def __init__(self, root, invocation_token, config_sha256, request_sha256,
                 *, max_file_bytes=MAX_FILE_BYTES, max_log_bytes=MAX_LOG_BYTES,
                 max_response_bytes=MAX_RESPONSE_BYTES,
                 max_files_per_process=MAX_FILES_PER_PROCESS,
                 max_total_bytes=MAX_TOTAL_BYTES,
                 max_collection_seconds=MAX_COLLECTION_SECONDS):
        self.root = Path(root)
        self.invocation_token = invocation_token
        self.config_sha256 = config_sha256
        self.request_sha256 = request_sha256
        self.max_file_bytes = max_file_bytes
        self.max_log_bytes = max_log_bytes
        self.max_response_bytes = max_response_bytes
        self.max_files_per_process = max_files_per_process
        self.max_total_bytes = max_total_bytes
        self.max_collection_seconds = max_collection_seconds
        self._rows = []
        self._events = []
        self._processes = {}
        self._attempted = {}
        self._collected_processes = set()
        self._absolute_deadline = None
        self._collected_bytes = 0
        self._files_by_process = {}
        self._collect_deadline = None
        self._collected = False
        self._finalized = False
        self._manifest_error = None
        self._response_status = 'not-received'
        self._response_row = None
        self._summary = None
        self._session_rows = []

    # ------------------------------------------------------------- creation

    @classmethod
    def create(cls, root, invocation_token, *, config_sha256, request_sha256,
               **bounds):
        """Create the fresh destination or refuse before any launch happens.

        Only this entry point may raise: it runs strictly before remote work,
        where refusal is the safe outcome.  An existing destination (including
        one left by another invocation) is never touched or overwritten.
        """
        root = Path(root)
        if not root.is_absolute():
            raise ValueError('durable evidence root must be an absolute path')
        if not _safe_component(invocation_token) and not invocation_token:
            raise ValueError('durable evidence requires an invocation token')
        _digest(config_sha256, 'config_sha256')
        _digest(request_sha256, 'request_sha256')
        if os.path.lexists(root):
            raise ValueError('durable evidence destination already exists: '
                             + str(root))
        try:
            root.parent.mkdir(parents=True, exist_ok=True)
            root.mkdir(mode=0o700)
        except FileExistsError as exc:
            raise ValueError('durable evidence destination already exists: '
                             + str(root)) from exc
        store = cls(root, invocation_token, config_sha256, request_sha256,
                    **bounds)
        store._event('created')
        store._write_identity()
        return store

    def _write_identity(self):
        payload = json.dumps(dict(schema=EVIDENCE_SCHEMA,
            invocation_token=self.invocation_token,
            config_sha256=self.config_sha256,
            request_sha256=self.request_sha256), sort_keys=True,
            indent=1).encode('utf-8')
        self._write_new(IDENTITY_NAME, payload)

    def _write_new(self, relative, payload):
        """Exclusive-create one artifact; never overwrite an existing file."""
        target = self.root / relative
        with open(target, 'xb') as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(target, 0o600)
        return len(payload)

    def _event(self, event, detail=None):
        row = dict(event=event)
        if detail is not None:
            row['detail'] = str(detail)[-500:]
        self._events.append(row)

    # ------------------------------------------------- identity registration

    def register_attempt(self, name, address, export_dir, log_path):
        """Register one attempted process BEFORE its launch is dispatched.

        Records the known role and artifact paths with an honestly unknown
        (``None``) PID/start.  If the process starts but its spawn reply is
        lost, cleanup still ran against the leases and retention can still
        attempt these known paths; the identity stays ``None`` rather than
        being fabricated.  A later acknowledged :meth:`register_process`
        fills in the real PID/start.  Any attempt that is never collected
        keeps ``complete`` false.
        """
        if self._finalized or not _safe_component(name):
            return
        self._processes.setdefault(name, dict(source_host=address,
                                              pid=None, start=None))
        self._attempted[name] = dict(source_host=address,
                                     export_dir=(None if export_dir is None
                                                 else str(export_dir)),
                                     log_path=(None if log_path is None
                                               else str(log_path)))

    def register_process(self, name, address, pid, start):
        """Bind one owned process identity into the manifest.

        Called at spawn receipt so the PID/start identity survives even when
        later collection cannot reach the process artifacts.
        """
        if self._finalized or not _safe_component(name):
            return
        self._processes[name] = dict(source_host=address,
                                     pid=pid, start=start)

    # ---------------------------------------------------- response retention

    def save_response(self, response):
        """Persist the complete HTTP response JSON immediately at receipt.

        Runs before any validation, observation collection or cleanup can
        fail, and never raises: a serialization or write failure is recorded
        as an honest status.  Called at most once with the received object.
        """
        if self._response_status != 'not-received':
            self._event('response-ignored-already-attempted',
                        self._response_status)
            return
        try:
            payload = json.dumps(response, sort_keys=True,
                                 indent=1).encode('utf-8')
        except (TypeError, ValueError) as exc:
            self._response_status = 'error'
            self._event('response-serialize-failed', exc)
            return
        if len(payload) > self.max_response_bytes:
            self._response_status = 'oversize'
            self._event('response-oversize', len(payload))
            return
        size = len(payload)
        digest = hashlib.sha256(payload).hexdigest()
        try:
            size = self._write_new(RESPONSE_NAME, payload)
        except OSError as exc:
            self._response_status = 'error'
            self._event('response-write-failed', exc)
            return
        self._response_status = 'saved'
        self._response_row = dict(kind='http-response', source_host='controller',
            source_path=RESPONSE_NAME, status=_COLLECTED, size=size,
            sha256=digest, target=RESPONSE_NAME)
        self._collected_bytes += size
        self._event('response-saved', size)

    def save_session_json(self, name, value):
        """Append a private session artifact; manifest exposes only its digest.

        Request response files are complete JSON at receipt, before validation.
        Started/received/final snapshots and the final report are separate,
        exclusive files, so catchable interrupts cannot erase prior records.
        A failed write returns false: callers stop rather than silently lose a
        response and continue a nominally complete measurement sequence.
        """
        if self._finalized or not _safe_component(name):
            return False
        row = dict(target=name, status='error', sha256=None, size=None)
        self._session_rows.append(row)
        try:
            payload = json.dumps(value, sort_keys=True, indent=1,
                                 allow_nan=False).encode('utf-8')
            bound=(self.max_response_bytes if name.endswith('-response.json')
                   else self.max_total_bytes)
            if len(payload) > bound:
                row['status'] = 'oversize'
                return False
            if self._collected_bytes + len(payload) > self.max_total_bytes:
                row['status'] = 'budget'
                return False
            size = self._write_new(name, payload)
            row.update(status=_COLLECTED, size=size,
                       sha256=hashlib.sha256(payload).hexdigest())
            self._collected_bytes += size
            return True
        except Exception as exc:
            self._event('session-write-failed', exc)
            return False

    # ---------------------------------------------------- artifact retention

    def begin_collection_budget(self, absolute_deadline, *, clock=time.monotonic):
        """Bind retention to the campaign's EXISTING absolute deadline.

        The wall deadline for collection becomes
        ``min(absolute_deadline - MANIFEST_RESERVE_SECONDS, now +
        max_collection_seconds)``: no fresh budget is granted after the
        campaign budget has expired, and manifest finalization always has
        reserved time.  Idempotent; earliest binding wins.
        """
        if self._finalized or self._collected:
            return
        manifest_deadline = absolute_deadline - MANIFEST_RESERVE_SECONDS
        capped = clock() + self.max_collection_seconds
        candidate = min(manifest_deadline, capped)
        if self._absolute_deadline is None:
            self._absolute_deadline = absolute_deadline
            self._collect_deadline = candidate
            self._event('budget-bound', dict(
                absolute_deadline=absolute_deadline,
                collect_deadline=candidate))
        elif candidate < self._collect_deadline:
            self._collect_deadline = candidate

    def collect_processes(self, entries, runner, *, clock=time.monotonic):
        """Collect raw bytes for each process independently, never raising.

        ``entries`` is a list of ``{name, address, export_dir, log_path,
        pid, start}``.  A failure collecting rpc0 (probe refused, deadline,
        ...) never prevents the attempt for rpc1 or the client.  Idempotent:
        a second call is a no-op.  ``runner`` is the fixed command runner
        (``run(address, argv, *, timeout) -> stdout text``).

        When :meth:`begin_collection_budget` bound an earlier absolute
        deadline, that deadline (minus the manifest reserve) governs; the
        per-call budget below only applies when no absolute deadline was
        bound.  Processes registered via :meth:`register_attempt` but absent
        from ``entries`` (launch reply lost) are still attempted through
        their pre-registered paths, with their unknown identity recorded
        honestly.
        """
        if self._finalized or self._collected:
            return
        self._collected = True
        if self._collect_deadline is None:
            self._collect_deadline = clock() + self.max_collection_seconds
        by_name = {}
        for entry in entries:
            name = entry.get('name')
            if isinstance(name, str):
                by_name.setdefault(name, entry)
        merged = []
        for name in dict.fromkeys([*(e.get('name') for e in entries),
                                   *sorted(self._attempted)]):
            if name is None:
                continue
            registered = self._attempted.get(name)
            entry = by_name.get(name)
            if entry is not None:
                merged.append(entry)
            elif registered is not None:
                # Attempted launch whose reply was lost: retention still
                # tries the pre-registered known paths.  PID/start stay
                # unknown (None) -- never fabricated.
                merged.append(dict(name=name,
                    address=registered['source_host'],
                    export_dir=registered['export_dir'],
                    log_path=registered['log_path'],
                    pid=self._processes.get(name, {}).get('pid'),
                    start=self._processes.get(name, {}).get('start')))
        for entry in merged:
            if isinstance(entry.get('name'), str):
                self._collected_processes.add(entry['name'])
        for entry in merged:
            try:
                self._collect_one(entry, runner, clock)
            except BaseException as exc:  # retention never escapes
                self._event('collect-process-failed',
                            str(entry.get('name')) + ': ' + str(exc))
                self._row(entry, 'export-dir', entry.get('export_dir'),
                          'error', error=exc)

    def _row(self, entry, kind, source_path, status, *, size=None,
             sha256=None, target=None, error=None, truncated=None,
             original_size=None, retained_range=None):
        row = dict(process=entry['name'], kind=kind,
                   source_host=entry.get('address'), source_path=source_path,
                   pid=entry.get('pid'), start=entry.get('start'),
                   status=status, size=size, sha256=sha256, target=target)
        if truncated is not None:
            row['truncated'] = truncated
        if original_size is not None:
            row['original_size'] = original_size
        if retained_range is not None:
            row['retained_range'] = retained_range
        if error is not None:
            row['error'] = str(error)[-500:]
        self._rows.append(row)
        return row

    def _budget_ok(self, entry, kind, source_path, size_hint, clock):
        if (self._collect_deadline is not None
                and clock() >= self._collect_deadline):
            self._row(entry, kind, source_path, 'deadline')
            return False
        count = self._files_by_process.get(entry['name'], 0)
        if count >= self.max_files_per_process:
            self._row(entry, kind, source_path, 'file-limit')
            return False
        if (size_hint is not None
                and self._collected_bytes + size_hint > self.max_total_bytes):
            self._row(entry, kind, source_path, 'budget')
            return False
        return True

    def _copy(self, entry, kind, name, source_path, runner, bound, clock):
        if not _safe_component(name):
            self._row(entry, kind, source_path, 'rejected-path')
            return
        if not self._budget_ok(entry, kind, source_path, None, clock):
            return
        try:
            data = self._read_remote(runner, entry['address'], source_path,
                                     bound, clock)
        except ValueError as exc:
            if 'exceeds bound' in str(exc):
                self._row(entry, kind, source_path, 'oversize', error=exc)
            else:
                self._row(entry, kind, source_path, 'error', error=exc)
            return
        except Exception as exc:
            self._row(entry, kind, source_path, 'error', error=exc)
            return
        if len(data) > bound:
            self._row(entry, kind, source_path, 'oversize')
            return
        if self._collected_bytes + len(data) > self.max_total_bytes:
            self._row(entry, kind, source_path, 'budget')
            return
        target = entry['name'] + '/' + name
        try:
            size = self._write_new(target, data)
        except FileExistsError as exc:
            self._row(entry, kind, source_path, 'error', error=exc)
            return
        except OSError as exc:
            self._row(entry, kind, source_path, 'error', error=exc)
            return
        self._files_by_process[entry['name']] = (
            self._files_by_process.get(entry['name'], 0) + 1)
        self._collected_bytes += size
        self._row(entry, kind, source_path, _COLLECTED, size=size,
                  sha256=hashlib.sha256(data).hexdigest(), target=target)

    def _probe_timeout(self, clock):
        """Clamp each probe timeout to the remaining collection budget."""
        if self._collect_deadline is None:
            return STAT_TIMEOUT_SECONDS
        remaining = self._collect_deadline - clock()
        if remaining <= 0:
            return 0
        return max(1, min(STAT_TIMEOUT_SECONDS, int(remaining)))

    def _stat_listing(self, runner, address, directory, clock):
        if directory is None:
            return {'missing': True}
        if (self._collect_deadline is not None
                and clock() >= self._collect_deadline):
            return {'error': 'collection deadline reached before listing'}
        argv = ['python3', '-c', STAT_PROGRAM, str(directory)]
        return json.loads(runner.run(address, argv,
                                     timeout=self._probe_timeout(clock)))

    def _read_remote(self, runner, address, path, bound, clock):
        """Read at most ``bound`` original bytes; raise ValueError on oversize."""
        import base64
        argv = ['python3', '-c', READ_PROGRAM, str(path), str(int(bound))]
        encoded = runner.run(address, argv,
                             timeout=self._probe_timeout(clock))
        data = base64.b64decode(encoded.encode('ascii'), validate=True)
        if len(data) > bound:
            raise ValueError('evidence read exceeds bound')
        return data

    def _read_tail(self, runner, address, path, bound, clock):
        """Read the LAST ``bound`` bytes; return ``(data, original_size)``.

        The tail program emits the original file size on its first line and
        the base64 of the final ``bound`` bytes after it; the reader-side
        bound stays enforced on the returned data.
        """
        import base64
        argv = ['python3', '-c', TAIL_PROGRAM, str(path), str(int(bound))]
        output = runner.run(address, argv,
                            timeout=self._probe_timeout(clock))
        newline = output.find('\n')
        if newline < 0:
            raise ValueError('tail probe returned no size line')
        original_size = int(output[:newline])
        data = base64.b64decode(output[newline + 1:].encode('ascii'),
                                validate=True)
        if len(data) > bound:
            raise ValueError('evidence tail exceeds bound')
        return data, original_size

    def _copy_log_tail(self, entry, name, source_path, runner, bound, clock):
        """Retain the last ``bound`` bytes of a log with an honest record.

        A log larger than the bound keeps its final ``bound`` bytes plus a
        truncation row (original size and retained byte range); a bounded
        log is copied whole.  Export-file limits and refusal behavior are
        unchanged -- truncation applies to logs only.
        """
        if not _safe_component(name):
            self._row(entry, 'log', source_path, 'rejected-path')
            return
        if not self._budget_ok(entry, 'log', source_path, None, clock):
            return
        try:
            data, original_size = self._read_tail(runner, entry['address'],
                                                  source_path, bound, clock)
        except ValueError as exc:
            self._row(entry, 'log', source_path, 'error', error=exc)
            return
        except Exception as exc:
            self._row(entry, 'log', source_path, 'error', error=exc)
            return
        if self._collected_bytes + len(data) > self.max_total_bytes:
            self._row(entry, 'log', source_path, 'budget')
            return
        target = entry['name'] + '/' + name
        try:
            size = self._write_new(target, data)
        except OSError as exc:
            self._row(entry, 'log', source_path, 'error', error=exc)
            return
        self._files_by_process[entry['name']] = (
            self._files_by_process.get(entry['name'], 0) + 1)
        self._collected_bytes += size
        row = dict(truncated=(original_size > len(data)),
                   original_size=original_size,
                   retained_range=[original_size - len(data), original_size])
        self._row(entry, 'log', source_path, _COLLECTED, size=size,
                  sha256=hashlib.sha256(data).hexdigest(), target=target,
                  **row)

    def _collect_one(self, entry, runner, clock):
        name = entry['name']
        if not _safe_component(name):
            self._event('collect-refused-name', name)
            return
        try:
            (self.root / name).mkdir()
        except OSError as exc:
            self._event('process-directory-failed', name + ': ' + str(exc))
            self._row(entry, 'export-dir', entry.get('export_dir'), 'error',
                      error=exc)
            return
        export_dir = entry.get('export_dir')
        listing = None
        try:
            listing = self._stat_listing(runner, entry['address'],
                                         export_dir, clock)
        except Exception as exc:
            listing = {'error': str(exc)}
        if not isinstance(listing, dict):
            listing = {'error': 'unparseable listing'}
        export_rows = 0
        if listing.get('missing') is True:
            self._row(entry, 'export-dir', export_dir, 'missing')
        elif 'error' in listing:
            self._row(entry, 'export-dir', export_dir, 'error',
                      error=listing['error'])
        else:
            for file_name in sorted(listing):
                info = listing[file_name] if isinstance(
                        listing.get(file_name), dict) else {}
                kind = 'claim' if file_name == CLAIM_NAME else 'export'
                source_path = str(Path(export_dir) / file_name)
                entry_type = info.get('type')
                if entry_type == 'symlink':
                    self._row(entry, kind, source_path, 'rejected-symlink')
                elif entry_type == 'other':
                    self._row(entry, kind, source_path,
                              'rejected-non-regular')
                elif entry_type == 'error':
                    self._row(entry, kind, source_path, 'error',
                              error=info.get('error'))
                elif entry_type == 'file':
                    export_rows += 1
                    if info.get('size', 0) > self.max_file_bytes:
                        self._row(entry, kind, source_path, 'oversize')
                        continue
                    self._copy(entry, kind, file_name, source_path,
                               runner, self.max_file_bytes, clock)
                else:
                    self._row(entry, kind, source_path, 'error',
                              error='unparseable stat entry')
        if export_rows == 0:
            # An existing but empty export directory is not a complete
            # diagnostic record for this process: record the gap honestly.
            self._row(entry, 'export-dir', export_dir, 'missing',
                      error='export directory holds no claim or envelope')
        log_path = entry.get('log_path')
        if log_path is not None:
            self._copy_log_tail(entry, Path(log_path).name, log_path,
                                runner, self.max_log_bytes, clock)

    # ------------------------------------------------------------- finalize

    def finalize(self):
        """Write the manifest last and return the receipt summary.

        Idempotent and exception-free: even a manifest write failure yields an
        honest summary with ``complete: false``.
        """
        if self._finalized:
            return self._summary
        self._finalized = True
        rows = sorted(self._rows, key=lambda row: (row.get('process') or '',
                                                   row.get('kind') or '',
                                                   row.get('source_path') or ''))
        counts = {}
        for row in rows:
            counts[row['status']] = counts.get(row['status'], 0) + 1
        complete = (not rows or all(row['status'] == _COLLECTED
                                    for row in rows))
        # An attempted launch that was never enumerated for collection --
        # not attempted through its known paths, no artifact row at all --
        # makes the ledger honestly incomplete: an omitted process must not
        # yield a falsely complete manifest.
        omitted = sorted(name for name in self._attempted
                         if name not in self._collected_processes)
        if omitted:
            complete = False
        if self._response_row is not None:
            counts[_COLLECTED] = counts.get(_COLLECTED, 0) + 1
        elif self._response_status not in ('saved', 'not-received'):
            counts[self._response_status] = (
                counts.get(self._response_status, 0) + 1)
            complete = False
        manifest = dict(schema=EVIDENCE_SCHEMA,
                        invocation_token=self.invocation_token,
                        config_sha256=self.config_sha256,
                        request_sha256=self.request_sha256,
                        bounds=dict(max_file_bytes=self.max_file_bytes,
                                    max_log_bytes=self.max_log_bytes,
                                    max_response_bytes=self.max_response_bytes,
                                    max_files_per_process=self.max_files_per_process,
                                    max_total_bytes=self.max_total_bytes,
                                    max_collection_seconds=self.max_collection_seconds),
                        process_identities=dict(sorted(self._processes.items())),
                        omitted_processes=omitted,
                        response=dict(status=self._response_status,
                                      row=self._response_row),
                        artifacts=rows,
                        counts=dict(sorted(counts.items())),
                        complete=complete,
                        events=list(self._events))
        if self._session_rows:
            manifest['session_artifacts'] = list(self._session_rows)
            manifest['response'] = dict(status='session', rows=[row for row in self._session_rows
                if row['target'].endswith('-response.json')])
            for row in self._session_rows:
                counts[row['status']] = counts.get(row['status'], 0) + 1
                if row['status'] != _COLLECTED:
                    complete = False
            manifest['counts'] = dict(sorted(counts.items()))
            manifest['complete'] = complete
        manifest_sha256 = None
        try:
            payload = json.dumps(manifest, sort_keys=True,
                                 indent=1).encode('utf-8')
            self._write_new(MANIFEST_NAME, payload)
            manifest_sha256 = hashlib.sha256(payload).hexdigest()
        except OSError as exc:
            self._manifest_error = str(exc)
            complete = False
        self._summary = dict(schema=EVIDENCE_SCHEMA, root=str(self.root),
                             manifest=MANIFEST_NAME,
                             manifest_sha256=manifest_sha256,
                             complete=complete,
                             counts=dict(sorted(counts.items())),
                             response_status=self._response_status,
                             processes=sorted(self._processes),
                             artifact_count=len(rows),
                             error=self._manifest_error)
        if self._session_rows:
            self._summary.update(response_status='session',
                                 session_responses=manifest['response']['rows'])
        return self._summary

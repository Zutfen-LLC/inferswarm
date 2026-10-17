"""Frozen, sequential native /completion diagnostics; no qualification authority.

Opt in with --session pointing at q8-two-cuda-session/1 JSON. Every request has
exactly {warmup: bool, body: {prompt, n_predict, temperature, seed, stream: false,
cache_prompt: bool}}. The envelope's request_sha256 binds the canonical ENTIRE
session, including order and warmups, rather than the legacy plan request.
The pinned native /completion cache_prompt=false reset seam is used instead of
assuming an OpenAI-compatible chat extension disables prompt reuse.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math

from .profiles import canonical
from .q8_experiment import SystemdCampaignGuard

MAX_REQUESTS = 6
MAX_GENERATION_TOKENS = 4096
ENDPOINT = '/completion'


@dataclass(frozen=True)
class DiagnosticSession:
    # Immutable canonical bytes prevent later caller or HTTP mutation of the
    # frozen request bodies. Decode fresh at the request boundary.
    canonical_bytes: bytes
    count: int

    @property
    def digest(self):
        return hashlib.sha256(self.canonical_bytes).hexdigest()

    def payload(self):
        return json.loads(self.canonical_bytes)


def validate_session(raw):
    if (not isinstance(raw, dict)
            or not {'schema', 'requests'} <= set(raw) <= {'schema', 'requests', 'demand'}
            or raw['schema'] != 'q8-two-cuda-session/1'):
        raise ValueError('strict q8-two-cuda-session/1 required')
    requests = raw['requests']
    if not isinstance(requests, list) or not 1 <= len(requests) <= MAX_REQUESTS:
        raise ValueError('session requires 1..6 requests including warmups')
    for row in requests:
        if (not isinstance(row, dict) or set(row) != {'body', 'warmup'}
                or type(row['warmup']) is not bool):
            raise ValueError('session request requires body and boolean warmup')
        body = row['body']
        if not isinstance(body, dict) or set(body) != {
                'prompt', 'n_predict', 'temperature', 'seed', 'stream', 'cache_prompt'}:
            raise ValueError('session native request body fields must be exact')
        if not isinstance(body['prompt'], str) or not body['prompt']:
            raise ValueError('session prompt must be nonempty text')
        if type(body['n_predict']) is not int or not 1 <= body['n_predict'] <= MAX_GENERATION_TOKENS:
            raise ValueError('session generation cap must be an integer in 1..4096')
        temperature = body['temperature']
        if (type(temperature) not in (int, float) or not math.isfinite(temperature)
                or not 0 <= temperature <= 2):
            raise ValueError('session temperature must be finite in 0..2')
        if type(body['seed']) is not int or not 0 <= body['seed'] < 2**32:
            raise ValueError('session seed must be a fixed unsigned 32-bit integer')
        if body['stream'] is not False or type(body['cache_prompt']) is not bool:
            raise ValueError('session requires stream=false and explicit boolean cache_prompt')
    return DiagnosticSession(canonical(raw), len(requests))


def response_metrics(response):
    """Keep native quantities as reported; missing is not zero or inferred TTFT."""
    timings = response.get('timings')
    timings = timings if isinstance(timings, dict) else {}
    result = {key: timings.get(key) for key in (
        'cache_n', 'prompt_n', 'prompt_ms', 'prompt_per_second', 'predicted_n',
        'predicted_ms', 'predicted_per_second')}
    result.update(raw_timings=response.get('timings'),
                  tokens_predicted=response.get('tokens_predicted'),
                  tokens_evaluated=response.get('tokens_evaluated'),
                  tokens_cached=response.get('tokens_cached'),
                  ttft_seconds=None,
                  ttft_unavailable_reason='nonstreaming response; wall time is not TTFT')
    return result


class SystemdSessionGuard(SystemdCampaignGuard):
    """Only the explicit session path lifts the old sole-request restriction."""
    def __init__(self, *args, session, **kwargs):
        self.session = session
        # #314 opt-in demand capture for exactly one measured request; None
        # keeps the exact pre-#314 session behavior (default off).
        self.demand_profile = None
        self.demand_state = None
        self.phase = 'verification'
        self.phase_index = None
        self.setup = {}
        self.request_records = []
        super().__init__(*args, **kwargs)

    def begin(self, plan, spec, client, remote):
        super().begin(plan, spec, client, remote)
        self.setup['verification_started_monotonic'] = self.started
        self._samples.append(self.resource_sample({}))

    def sources_verified(self, plan, sources):
        super().sources_verified(plan, sources)
        self.setup['verification_ended_monotonic'] = self.clock()
        self.setup['load_started_monotonic'] = self.clock()
        self.phase = 'load'
        self._samples.append(self.resource_sample({}))

    def request_started(self):
        self.checkpoint()
        if self.request_attempts >= self.session.count:
            raise RuntimeError('frozen session requests exhausted')
        self.request_attempts += 1

    def resource_sample(self, rows):
        sample = super().resource_sample(rows)
        sample.update(phase=self.phase, request_index=self.phase_index,
                      timestamp=datetime.now(timezone.utc).isoformat())
        # Light cumulative CPU/disk counters from procfs and the owned cgroup;
        # no tracing/profiling, no graph or kernel-proof claims. Unknown optional
        # counters are explicit None, not a fabricated zero.
        counters = {}
        for part in (self.client, self.remote):
            paths = ['/proc/stat', '/proc/diskstats']
            group = sample['aggregates'][part.execution_address]['ControlGroup']
            paths += ['/sys/fs/cgroup'+group+'/cpu.stat',
                      '/sys/fs/cgroup'+group+'/io.stat']
            program = ("# load-once-resource-sample\n"
                "import json,pathlib,sys\n"
                "out={}\n"
                "for name in sys.argv[1:]:\n"
                "    try:\n"
                "        with open(name) as f: data=f.readline() if name=='/proc/stat' else f.read(16385)\n"
                "        out[name]={'raw':data[:16384],'truncated':len(data)>16384}\n"
                "    except OSError: out[name]=None\n"
                "print(json.dumps(out))\n")
            try:
                counters[part.host_id] = json.loads(self._run(part, ['python3', '-c', program, *paths]))
            except Exception as exc:
                counters[part.host_id] = dict(raw=None, unavailable=str(exc))
        sample['raw_cpu_disk_counters'] = counters
        return sample

    def _demand_outcome(self, result):
        """Honest demand-capture outcome; absent means default-off, not zero."""
        record = result.get('demand_capture')
        if record is None:
            return 'disabled'
        if record.get('status') == 'FINISHED' and record.get('export_status') == 'retained':
            return 'EXPORTED'
        status = record.get('export_status')
        if status in ('missing', 'oversize', 'retention-failed',
                      'client-exit', 'unknown-exit'):
            return 'COLLECTION-' + status.upper().replace('-', '_')
        return 'FAILED'

    def report(self, result, *, failure=None, interrupted=None, cleanup=None):
        refused = 'observation_refusal' in result
        complete = (len(self.request_records) == self.session.count
                    and all(row['status'] == 'COMPLETED' for row in self.request_records))
        cleanup_ok = bool(cleanup) and all(row.get('lease') == 'released' for row in cleanup.values())
        if hasattr(self.leases, 'cleanup_budgets'):
            cleanup_ok = cleanup_ok and bool(getattr(self, 'final_aggregates', {}))
        cleanup_ok = cleanup_ok and getattr(self, 'cleanup_error', None) is None
        # Actual response completion is independent of a later cleanup error,
        # observer timeout or interrupt; the campaign's top-level status/error
        # still records STOPPED/INTERRUPTED separately.
        execution = ('COMPLETED' if complete else
                     ('INTERRUPTED' if interrupted is not None else 'STOPPED'))
        result.update(session_sha256=self.session.digest, frozen_session=self.session.payload(),
            requests=self.request_records, setup=self.setup, samples=list(self._samples),
            outcomes=dict(execution=execution, correctness='NOT-EVALUATED',
                completed_requests=sum(row['status']=='COMPLETED' for row in self.request_records),
                planned_requests=self.session.count,
                timing_resources='REPORTED-WITH-MISSING-FIELDS',
                observer=('REFUSED' if refused else ('COMPLETE' if result.get('listener_observations') else 'INCOMPLETE')),
                observer_scope='two RPC terminal streams; no per-request native dynamic acceptance',
                cleanup='COMPLETE' if cleanup_ok else 'FAILED-OR-INCOMPLETE',
                # #314 demand capture is reported SEPARATELY from general
                # observer completeness: a ring-saturated observer refusal
                # neither erases the structural demand export nor is relabeled.
                demand_capture=self._demand_outcome(result)),
            output_accepted=False, physical_qualified=False)
        if getattr(self, 'cleanup_error', None) is not None:
            result['cleanup_failure'] = self.cleanup_error
        if failure is not None:
            result['session_failure'] = dict(type=type(failure).__name__, reason=str(failure))
        return result

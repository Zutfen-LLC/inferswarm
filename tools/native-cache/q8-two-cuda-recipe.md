# Later Hermes recipe: Q8 on two CUDA devices (#313)

This recipe is a reviewable handoff, not execution authority. Physical access,
model reads, downloads, GPU probes and host operations remain outside this
coding task. Stop on any identity, capacity, placement or cleanup mismatch.

The runnable path is deliberately separate from ordinary operator admission:

```bash
python3 -m inferswarm.operator experimental-q8-two-cuda \
  --config /absolute/path/step-a-cpu05-cuda03.json \
  --envelope /absolute/path/q8-two-cuda-experiment.json
```

The ordinary `run` command is unchanged and must continue to refuse
unknown allocation/capability terms.  The experimental command also refuses
unless the envelope contains the exact opt-in string
`I_AUTHORIZE_ONE_UNQUALIFIED_Q8_TWO_CUDA_EXPERIMENT`, SHA-256 of the exact
config bytes, SHA-256 of the canonical request object, and fresh `CUDA0` and
`CUDA1` UUID bindings.  Its `limits` object must contain exactly:

```json
{
  "application_payload_ceiling_bytes": 25769803776,
  "backing_ceiling_bytes": 51539607552,
  "cleanup_reserve_seconds": 1200,
  "coordinator_memory_max_bytes": 118111600640,
  "coordinator_min_host_headroom_bytes": 8589934592,
  "min_free_disk_bytes": 68719476736,
  "owned_swap_max_bytes": 0,
  "per_gpu_reserve_bytes": 536870912,
  "total_seconds": 10800,
  "worker_memory_max_bytes": 10737418240,
  "worker_min_host_headroom_bytes": 4294967296
}
```

The config's assigned-backing budget must independently encode a 48 GiB
ceiling, at least 64 GiB free-disk floor, and a positive repair reserve within
that ceiling.  Freeze the exact short request in the config; the command sends
it once and records its hash.  The receipt always preserves ordinary admission
status and unknown allocations and always sets `output_accepted: false` and
`physical_qualified: false`.

The full envelope has exactly the fields `schema`, `opt_in`, `config_sha256`,
`request_sha256`, `limits`, and `gpu_bindings`; `schema` is
`q8-two-cuda-experiment/1`. `gpu_bindings` is an ordered two-element list of
`{"selector":"CUDA0","uuid":"GPU-<observed UUID>"}` and the analogous CUDA1
row. The request digest is SHA-256 of `profiles.canonical(dict(plan.request))`;
the config digest covers the exact file bytes. Freeze both before invocation.
The command parses those same bytes once, so a second config read cannot
silently change the frozen request.

The native payload and its simultaneous per-bank repair reserve require at
least **41,574,852,992 B before metadata**. A 24 GiB application-payload ceiling
is not a disk allowance. The worker remains assigned-only. The 168,221,585,536 B
CPU assignment exceeds 125 GiB physical memory: this is an honest lazy/mmap
trial whose working set may fail within the 110 GiB external cap.

Supervision uses fresh systemd slices with aggregate `MemoryMax` 10 GiB on the
worker and 110 GiB on the coordinator and `MemorySwapMax=0`. Source verification
and read-only collector helpers use `systemd-run --wait --pipe` in the same
slices; native services also have owned systemd units, exact PID/start receipts,
`KillMode=control-group`, a ten-second stop timeout and the remaining 160-minute
execution budget. No inference process starts before aggregate enforcement is
verified. Failed or ambiguous spawns remain registered for cleanup. The watcher
runs during source verification, load and the sole request, stopping owned
units on a violation or failed monitor. It samples GPU reserve rather than
claiming an implicit hard GPU cap. It always reports compute attribution as
`INCONCLUSIVE` until adequate endpoint/PID/UUID kernel evidence exists.

## Two phases under one outer Hermes budget

**Phase A is existing stopped-worker preparation, outside this command.** Use
[`bounded-acquisition.md`](bounded-acquisition.md) and
[`selective-preparation.md`](selective-preparation.md): the existing
`prepare_q8_participant` API with authenticated assigned records, provisioned
source/tunnel, reviewed executable/FNV helper, one writer and `DiskBudget`.
The paired bounded-acquisition helpers are callable APIs, not an acquisition
subcommand of the operator. They fetch only missing assigned bytes and retain
the source/acquisition ledger. Keep workers stopped and authenticate/publish
both prepared banks before Phase B. The diagnostic command refuses missing or
invalid backing; it never fills it in or downloads a model.

**Phase B is supervised verification, native load and at most one request.**
Only this phase is implemented by `experimental-q8-two-cuda`. Its
`application_payload_ceiling_bytes` checks the sum of encoded GPU assignments;
it is not a measured acquisition or runtime transfer meter. A passing value
must never be reported as enforcement of a 24 GiB transfer allowance.

Before Phase A, Hermes must freeze one outer start time T0, an execution STOP
at T0 + 160 minutes, and an absolute end at T0 + 180 minutes. Preparation,
source/tunnel helpers, verification, load and the request all consume that
same budget; the last 20 minutes are reserved for stopping and verifying
cleanup of every owned process on both hosts. Phase B's internal timer starts
when the command begins and is only a local backstop: it does not know time
already spent in Phase A and must not extend either outer deadline. There is
no supported outer-start/deadline CLI flag or envelope field. Hermes must
supply an independently reviewed outer watchdog that stops both preparation
and execution ownership sets at the earlier STOP and verifies cleanup by the
absolute end. If that spanning supervision cannot be enforced, refuse the
physical launch rather than reset the budget between phases.

Freeze acquisition/transfer accounting separately in that outer session:
authenticate the missing-only delta before reads, enforce the approved 24 GiB
application-payload acquisition/transfer allowance against actual counted bytes
for its frozen traffic classes, and retain source/ledger receipts. Record
metadata/control, verification GET and native application payload separately;
do not substitute encoded assignment arithmetic, a range-size limit or the
48 GiB disk ceiling for a transfer counter. Apply the 48 GiB backing ceiling,
64 GiB free-disk floor, per-bank repair reserve, aggregate host memory/swap
limits and host headroom rules during preparation as well as execution.
The command's slices start only in Phase B and do not supervise the earlier
source/server/writer processes. Hermes must own and clean those Phase A jobs
and refuse if any required limit/counter/ownership receipt is absent. A STOP
is terminal for this attempt: no automatic repair/retry/restart/tuning.

## 1. Current inventory and identity admission

1. Record fresh read-only inventory for inferswarm05 and inferswarm03: CPU/RAM,
   free RAM and swap, source member identities under `/srv/models`, free SSD,
   existing listeners/process owners, both GPU UUIDs, PCI addresses, negotiated
   link widths, driver/runtime versions, clocks, temperatures and measured free
   VRAM. Historical labels such as x16/x4 and nominal 12 GiB are hypotheses.
2. Bind inferswarm05 as the full-source CPU coordinator and inferswarm03 as the
   assigned-only worker. Do not acquire full model members on the worker.
3. Admit the exact reviewed `step-a-cpu05-cuda03` client/worker manifests only
   when the deployed executables, libraries, compiler/CUDA closure and native
   pin `b29c606e28a01b1bc8c1351026a0fa6e616bf6c4` match. If the observer must
   change to emit endpoint/device ordinals, build into a fresh owned directory,
   capture complete manifests, and stop for separate review. Never alias a CPU
   identity as CUDA or promote a source-inspected candidate.
4. Bind device order by observed UUID. Reserve two distinct ports on the same
   worker and bind one owned process/listener to each: `rpc0 --device CUDA0`
   and `rpc1 --device CUDA1`. Register the two endpoints in that order and
   verify that the client enumerates them as `RPC0` and `RPC1`. Record the
   listener, PID/start and GPU UUID join for each process; a selector string is
   not UUID or residency proof.
5. Confirm the ordinary CI receipt for the repository's bounded native CPU
   fixture. It builds the actual pinned RPC server, holds simultaneous client
   connections to two server processes/listeners, concurrently transfers two
   distinct whole tensors through one cache root, verifies exact readback, and
   then verifies zero warm weight payload. This closes the generic native
   two-listener mechanism only. CUDA device enumeration and execution remain
   physical gates; a missing or failed CI receipt is STOP.

### Shared cache and per-listener guards

The two listeners use one complete prepared cache root but never share an
upload guard. Preparation authenticates every object/native view before either
process starts, and each process receives the immutable guard for only its
assigned bank. Normal startup therefore performs read-only opens of existing
keys. For a permitted repair, the native patch uses a unique `mkstemp` staging
file, verifies the complete SHA-256 before atomic publication, and admission
requires cache keys to be globally unique; the two disjoint banks cannot write
the same final cache path. Any missing object, duplicate key, wrong guard or
failed verification is STOP before launch.

## 2. Freeze budgets from the real census

Generate the full plan before launch. Require exact, disjoint state ranges and
the fixed ownership census: layers 41--44 on GPU 0 (11,035,064,960 B encoded
weights), layers 45--47 plus output on GPU 1 (8,957,357,824 B), all earlier
layers/source on the coordinator. For each GPU separately, sum encoded weights,
persistent state/KV, backend extents/repacking, graph, workspace, observer and a
declared reserve against measured available VRAM. For worker RAM, sum assigned
metadata/page residence, verification, transport, receive/cache staging,
runtime heap and a declared host reserve against measured available RAM. Record
phase peaks rather than aggregating VRAM or treating worker RAM as a weight
mirror. The exact encoded GPU assignment is 19,992,422,784 B. The coordinator
assignment is 168,221,585,536 B (about 156.67 GiB), so the roughly 125 GiB
coordinator must separately demonstrate a bounded lazy/mmap resident working
set, file-cache/paging headroom and acceptable fault behavior; full CPU
residency cannot be assumed. Unknown terms stay visible and block ordinary admission; only the exact
experimental opt-in may attempt the externally capped trial. Insufficient
headroom or a plan requiring the full model on the worker is STOP.

## 3. One bounded experimental start

1. With owned processes stopped, run the existing assigned-only preparation.
   Acquire only missing immutable whole tensors for both GPU banks. Record
   source reads/hashes, weight payload, metadata/control and cache publication
   separately.
2. After authenticating the complete shared cache, publish disjoint immutable
   assigned guards and start two owned RPC servers on the reserved ports, one
   with `--device CUDA0` and one with `--device CUDA1`. Start the coordinator
   with both endpoints, `--device RPC0,RPC1`,
   `--gpu-layers 8`, and `--tensor-split 4,4`. Use the unchanged short fixed
   request and existing numerical diagnostics/thresholds. The disk budget must
   retain every eligible native view and reserve the largest eligible repair in
   each assigned bank because both listeners can stage a replacement at once.
   Guards constrain hash-backed assigned lookup/publication; they neither prove
   endpoint placement nor reject every possible raw SET.
3. During the single request, bind samples to the exact listener/PID/UUID joins.
   Require measured
   weight residency and backend execution on both GPUs, per-device peak/reserve,
   worker host peak/headroom, the coordinator-mediated GPU0-to-GPU1 transition,
   correct final output custody/readback, a retained raw diagnostic response,
   and complete cleanup of both RPC processes. The software result remains
   diagnostic-only and must not be reported as accepted output. CPU-fixture
   evidence is not a substitute.
4. Stop only the owned processes and retain each service's final cgroup/systemd
   result, memory peak, swap observation, raw response, source/cache receipt and
   all GPU samples.  `Result=oom-kill`, owned swap, device loss, reserve/headroom
   breach, deadline, monitor failure or incomplete cleanup is STOP. Recoverable
   file-cache reclaim at `memory.max` and unrelated host swap are observations,
   not violations by themselves.

### Durable controller-side evidence retention (mandatory)

Before launch, the controller must create a fresh evidence directory outside
every remote lifecycle namespace (default
`~/.local/share/inferswarm/q8-two-cuda-evidence-<token>/`, or an explicit
`--evidence-root` that must not already exist; one invocation never overwrites
another's directory).  The command refuses to launch if that destination
cannot be created.  The directory is bound to the invocation token and the
frozen config/request SHA-256 hashes and is mode 0700 with 0600 artifacts:
its contents are potentially sensitive user content — never logged, never
published automatically.

Collection order on every exit path (success, observation refusal, execution
failure, cleanup failure):

1. the complete HTTP response JSON is saved immediately after receipt,
   before checkpoint/validation/observation collection can fail — usage,
   finish metadata and all other returned fields, not just extracted answer
   text;
2. owned processes are stopped and leases released (existing cleanup
   ordering unchanged);
3. raw bytes are then preserved per process independently — rpc0, rpc1 and
   client export envelopes, `is301-claim` files and bounded native log
   tails — with malformed or dropped-event exports retained verbatim before
   any parsing; a failure collecting rpc0 never prevents the attempt for
   rpc1 or the client;
4. a manifest is written last with source host/path, PID/start identity,
   file size, SHA-256 and per-artifact success/missing/error status.

Bounds and partial-failure behavior: 8 MiB per export/claim file, 2,000,000 B
per log tail, 80 files per process, 512 MiB total, 480 s collection wall
time (inside the reserved 20-minute cleanup budget).  Symlinks and path
escapes are rejected; absent, oversized or partially copied evidence is
recorded as such and never reported complete.  A retention failure is
reported separately in the receipt's `evidence_retention` summary and never
bypasses stopping owned processes, releasing leases, closing owned
transports or stopping aggregate slices; the guards that may refuse new work
after monitor failure, cancellation or execution-deadline expiry are never
disabled to force a copy.  Execution, observation, retention and cleanup
outcomes stay separate fields in the receipt.

This dispatch permits one load and at most one request: no physical restart,
retry or tuning. Existing CPU fixtures retain the missing-only restart-reuse
contract; a later separately reviewed campaign may measure it. Preserve the
single-attempt receipt and failures. Do not retry into PASS, adjust the frozen
allocation after launch, run extra requests, claim fit from nominal VRAM, or
close #313/#311/#315/#300. With the CPU two-listener mechanism established
by ordinary CI, the next smallest physical operation is fresh read-only worker
inventory plus exact CUDA build admission and the complete
per-device/host/coordinator memory census. Only after those gates receive
separate review and dispatch should the one full-Q8 diagnostic above run.

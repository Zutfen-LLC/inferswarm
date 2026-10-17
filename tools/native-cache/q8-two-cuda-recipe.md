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

Collection order on every CATCHABLE exit path (success, observation refusal,
execution failure, cleanup failure, KeyboardInterrupt/SystemExit after the
cleanup path; no recovery is promised for SIGKILL or power loss):

0. each attempted process's role and artifact paths (export dir, log path)
   are registered BEFORE its launch is dispatched: if the process starts but
   its spawn reply is lost, cleanup still stops the leases and retention
   still attempts those pre-registered paths; the PID/start identity is
   recorded as honestly unknown (null), never fabricated, and an attempted
   process that is never enumerated keeps the manifest honestly incomplete;
1. the complete HTTP response JSON is saved immediately after receipt,
   before checkpoint/validation/observation collection can fail — usage,
   finish metadata and all other returned fields, not just extracted answer
   text;
2. owned processes are stopped and leases released, INCLUDING units whose
   spawn reply was lost and the aggregate slices (acknowledged stops via
   lease cleanup, then the remaining registered units and slices via the
   supervision cleanup) — retention waits for every stop;
3. raw bytes are then preserved per process independently — rpc0, rpc1 and
   client export envelopes, `is301-claim` files and bounded native log
   tails — with malformed or dropped-event exports retained verbatim before
   any parsing; a failure collecting rpc0 never prevents the attempt for
   rpc1 or the client; a log larger than the 2,000,000 B bound keeps its
   LAST bounded bytes with an explicit truncation record (original size and
   retained byte range) instead of being rejected whole — export files keep
   whole-file limits and refusal behavior unchanged;
4. a manifest is written last with source host/path, PID/start identity,
   file size, SHA-256 and per-artifact success/missing/error status. An
   existing but empty export directory records an honest missing-evidence
   gap; remote reads use O_NOFOLLOW and a regular-file check so replaced or
   symlinked sources are refused rather than followed.

Bounds and partial-failure behavior: 8 MiB per export/claim file, 2,000,000 B
per log tail, 80 files per process, 512 MiB total, and collection time
clamped to the campaign's EXISTING absolute deadline minus a 30 s manifest
reserve (never a fresh 480 s window after the campaign budget has expired;
each probe's timeout is clamped to the remaining budget and no probe starts
once it is gone).  Symlinks and path
escapes are rejected on both the listing and the read; absent, oversized,
empty-directory or partially copied evidence is recorded as such and never
reported complete.  A retention failure is
reported separately in the receipt's `evidence_retention` summary and never
bypasses stopping owned processes, releasing leases, closing owned
transports or stopping aggregate slices; the guards that may refuse new work
after monitor failure, cancellation or execution-deadline expiry are never
disabled to force a copy.  Execution, observation, retention and cleanup
outcomes stay separate fields in the receipt, and an interrupt's original
exception/exit status is re-raised unchanged after finalization.

Trust assumption (deliberately narrow, unchanged by this round): trusted
experiment hosts, invocation-owned directories and bounded pinned producers.
The read-only probes refuse symlinks and non-regular files at the target
path; no ancestor-symlink traversal defense or directory-enumeration
redesign is claimed or implemented here.

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

## Later 40/44 comparison (coding only)

This is one proposed comparison for separate physical authorization. The
implementation approval covers local code, offline tests and a local commit;
it grants no model reads/hashes, acquisition, host probes or GPU execution.
The default 41/45 placement and all previous results remain available.

1. Use the existing optimized baseline as the comparator: reported MEASURED
   native prefill **2.274 s**, native decode **8.568 s**, HTTP wall **13.154 s**,
   with **28 prompt / 32 generated tokens**. These observations were supplied
   in the maintainer handoff; their raw session/response artifacts are retained
   outside this repository. Copy and authenticate the exact prior warmup and
   short-decode request bytes, settings, session digest and timing provenance
   before a comparison. Missing inputs or material context drift means STOP
   for this recipe; the numbers alone do not establish a reproducible baseline.
2. Keep `selection: two-gpu` and explicitly add
   `strategy_options.placement_variant: "40-44"`. Reassign complete layer 40
   from coordinator to GPU0 and complete layer 44 from GPU0 to GPU1, including
   each layer's state; keep embeddings on CPU and output on GPU1. Recompute the
   plan/config/profile/session/envelope identities and exact assigned ranges.
   Retain `build_pair: optimized-cpu05-cuda03`: CPU executable
   `8fbea89ca86a22572fe9b83807a7943a75dccaaaa0ec283c4fc24508c90b3156`
   with unchanged CUDA executable
   `46345f6c4df4f229aa11e76514c6c6eff9c9a148257f9232a505c8173d2ebf73`.
   Use their [reviewed complete manifests](optimized-cpu-build-pair/README.md);
   no runtime rebuild, native patch or observer redesign is part of this slice.
3. With workers stopped, authenticate the old shared assigned cache using the
   existing preparation/inventory/delta machinery. If all old content remains
   valid, acquire only missing layer 40: CALCULATED **2,760,141,696 B** of whole
   tensors. Layer 44 already exists in that cache; update its metadata/binding
   and move it between immutable listener guards without fetching its weights
   again. Keep content SHA/native keys, source extent/type/shape and repair
   reserves authenticated. Retain old valid objects; do not clear the cache or
   silently broaden acquisition if the census differs. Reuse the established
   coordinator source-digest cache only while its witnesses remain valid;
   the new CPU assignment is a subset of the old one. Existing source
   verification and cache-miss rules still apply.
4. Treat the fit as narrowly plausible, unproved. CALCULATED GPU0 weights stay
   **11,035,064,960 B**; GPU1 weights become **11,717,499,520 B**. GPU1 gains
   **2,763,410,304 B** including recurrent state. The latest reported MEASURED
   minimum free GPU1 memory was **3,234 MiB** on the baseline; subtraction gives
   CALCULATED **598.607 MiB** remaining, only **86.607 MiB** above the unchanged
   **512 MiB** reserve, before unknown workspace/alignment/graph/observer costs.
   This historical sample is not current headroom or a fit proof. Admit actual
   per-device and host budgets using the existing resource checks; STOP on
   allocation failure, reserve breach or any other frozen resource failure.
5. Freeze one outer start T0 covering acquisition through cleanup: execution
   STOP **T0 + 160 minutes**, absolute end **T0 + 180 minutes**, final **20
   minutes** reserved for owned cleanup. Keep the existing **110 GiB aggregate
   coordinator / 10 GiB aggregate worker** caps, **zero owned swap**, host
   headroom, disk/repair/free-space/transfer limits, and **900 s per-request**
   timeout. Enforce the existing spanning watchdog and actual byte counters;
   neither preparation nor session entry resets those absolute deadlines.
6. One candidate load, then exactly the retained warmup and the identical short
   decode, using the existing bounded `--session` path and fresh evidence root.
   Native argv must show `--gpu-layers 9 --tensor-split 4,5`; both listener
   PID/start/UUID joins and exact guards remain required. No extra prefill,
   prompt change, reload, tuning, retry or retry into PASS. Stop on resource
   failure and preserve the attempt. Report verification/acquisition, load,
   warmup and measured short-decode timings separately, plus returned token
   counts and the existing correctness diagnostics. Exclude warmup from timing
   summaries while charging its budget. Preserve raw responses, resource peaks,
   cleanup and observer saturation/refusal separately; keep
   `output_accepted:false` and `physical_qualified:false`. A completed HTTP
   request does not resolve the observer's existing endpoint attribution gap.

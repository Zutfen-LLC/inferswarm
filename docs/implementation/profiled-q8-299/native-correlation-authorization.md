# #302 native correlation authorization boundary

Status: BLOCKED_ON_NATIVE_INSTRUMENTATION_AUTHORIZATION.
Maintainer authority: PR #305 review `5483410569`, reviewed source
`3e40e2ede56e54a3d067846adc99f93c8f3d335e`, main
`8ed795b01aca2cd720b70564228c244158739f9d`.
This document requests a separately scoped decision. It authorizes nothing.

## Established implementation gap

At the reviewed head, `OperatorRunner._run_profiled_collected` creates a
controller-owned `request_nonce` and `RequestIdentity`, but the sole
`POST /v1/chat/completions` body contains only messages, max_tokens,
temperature, seed and stream. No nonce is sent. The subsequent native task
ID is selected from collected facts; selection cannot prove that task was
caused by this nonce. A process/invocation identity and one observed task are
not a controller-to-native correlation channel.

The retained #301 emitter records server task assignment/processing/response,
opaque graph IDs and tensor/RPC transfer facts. It does not bind those facts
to a received controller nonce, graph generation, ubatch or complete
source/destination tensor range. `NativeObserverCollector.collect_static`
returns no observed inventory; the independent identity reader supplies no
complete native/visible physical selectors. Production admission therefore
remains refused. Adding an emitter field alone cannot close these gaps.

The offline correction does not add an HTTP field/header, environment nonce,
RPC payload, inferred task identity or synthesized observation. No currently
authorized native transport carries the controller nonce. A nonce existing
only in a controller or synthetic fixture is not successful native receipt.

## Exact controller-to-native requirement (not a transport choice)

The controller's original plan digest, owned invocation and fresh request
nonce must be correlated through the actual single HTTP request, accepted
native request/task, all resulting graph/ubatch work, material transfer
occurrences and final response/output custody. The native observer must
report the nonce actually received by that task, not a configured expected
value. The observed task ID must match the received nonce; the observed
response must bind the same task and HTTP response ID. Missing, ambiguous,
foreign, reset, stale, reordered or incomplete joins refuse.

Remote RPC work also requires a causal association with the same task and
nonce. Local thread context, process-global current-task state, RPC connection
identity or adjacent timestamps alone do not establish this association across
asynchronous scheduling and remote commands. The maintainer must separately
approve a concrete audited correlation carrier at the HTTP/task and RPC
boundaries before implementation. No carrier is selected, implemented or
claimed to exist here. If no observation-only carrier is feasible without
changing the accepted native protocol/scheduling, stop for a scope decision.

## Smallest proposed source slice

All changes would be additive successor artifacts at the same pinned base
`b29c606e28a01b1bc8c1351026a0fa6e616bf6c4`; preserve the accepted #301 overlay,
executables, manifests, captures and continuous budget ledger byte-for-byte.
Do not overwrite the old producer or retrofit its captures.

1. Controller `runtime.py`: only after carrier approval, carry the immutable
   nonce through the sole existing HTTP request and require observed receipt.
   No extra generation/probe/warmup request.
2. Native HTTP request/task seams (`tools/server/server.cpp`, server task,
   queue and context code): validate/retain the received correlation value,
   bind native task assignment/response and propagate causal observation
   context to actual graph/ubatch execution. Inspect the pinned source before
   selecting the precise changed files; this is not authority to modify all
   server code.
3. Model/context/cache and allocation seams (`src/llama-model-loader.cpp`,
   `src/llama-kv-cache.cpp`, `src/llama-memory-recurrent.cpp`,
   `src/llama-memory-hybrid-idx.cpp`, and existing ggml allocation hooks): emit
   a complete owned pre-POST snapshot at the actual load/context-ready fence,
   including weights, 109 persistent states, owner-local logical composites,
   physical bases/extents, aliases, mirrors and resource accounting.
4. Existing scheduler/graph and tensor-copy seams in `ggml-backend.cpp` and
   `ggml-rpc.cpp`: observe actual request-bound graph/ubatch and ordered
   completed copy occurrences. Observe server completion, not only client
   intent. The remote correlation mechanism itself requires the separate
   carrier decision above; no protocol change is silently approved.
5. Successor observer helper/derivation and Python collector/identity reader:
   authenticated pre-POST snapshot and terminal-export custody, actual
   native/visible selectors and measured available resource/headroom facts.
   Keep expected plan facts distinct from observations.

No inference mathematics, kernels, placement, scheduling, copy route,
synchronization/eval callbacks or fallback may change to obtain evidence.
Physical CUDA/Q8 numerical, route, fit and performance qualification remain
outside #302 and separately gated in #300.

## Required capture families

Use the existing bounded envelope/content-integrity law, with a separately
versioned fact catalog and independently authenticated producer identity.
These are requirements, not emitted captures or a finalized wire schema.

- Static provenance/custody: observed-native source, participant, owned
  PID/start, boot/topology epoch, plan/invocation, capture time, snapshot
  generation/fence, executable/backend/patch identity, complete physical
  selectors and independent host-facts provenance/freshness.
- Static inventory: weight/member/range/source identity; state or composite
  owner; actual component shape/type/strides/offset/size; physical allocation
  ID/domain/measured base capacity/lifetime; checked non-overlapping extents;
  accounted aliases/mirrors/staging/workspace/source backing and per-domain
  capacity, available memory, policy reserve/headroom. Lower bounds never
  become measured allocation sizes.
- Request: received nonce, original invocation, native task ID, response ID,
  ordered graph generation(s), ubatch identity/generation/count/token range
  and native successful-completion evidence.
- Every material transfer: same task/nonce/graph/ubatch, tensor identity,
  source/destination physical domains and allocation IDs, source/destination
  offset and byte interval, shape/strides/type, boundary/operation, occurrence
  ordering and actual completion. Join both B CPU -> A staging -> B CUDA legs
  and output-return legs; account side inputs and repeated copies separately.
- Output custody: same request/task/response/graph/ubatch and exact tensor/
  range lineage through the observed final output and A-side readback, with
  completion/order and observed counts. No graph reservation, startup copy,
  synthetic route label or unrelated request can satisfy this family.
- Terminal: complete bounded stream, generation/no reset, contiguous counters,
  drop/overflow refusal, owned export claim and process census, source-cache
  continuity, collection and post-blocking-call freshness.

## Proposed bounded verification and build budget

First audit the carrier and derivation entirely offline, add failing Python
and native-source fixture controls, then independent SPEC and QUALITY review
of the proposed source/catalog before any build. A native source harness is
not full-target verification. No compilation is authorized by this document.

A separate authorization should name the successor source freeze, new output
root and new continuous ledger, with one CPU-only full-server/RPC build,
330-TU closure re-authenticated from the pinned target definitions, one
compiler job and no concurrent build. Proposed cumulative envelope: 6,600
seconds INCLUDING compiler, link and tiny fixture phases, with 1,800 seconds
maximum per build phase and 60 seconds per tiny fixture. This is a request for
NEW #302 authority, not reuse of the #301 budget or its unused seconds. If
reviewed recipe estimates cannot fit, stop before spending; no automatic
extension/rebuild/retry. Preserve the original #301 6,360.491934636724-second
ledger unchanged.

Retain existing conservative limits: 3 GiB address space per compiler/link/
fixture; 4 GiB summed owned-tree RSS; no cores; 256 MiB individual output;
4 GiB generated tree; stop below 16 GiB free; tiny buffers at most 1 MiB each
and 16 MiB total. Use a supervised, deadline-bound, exact-owned process tree;
check memory/disk around each step and terminate/reap owned descendants on
any breach. No package/tool installation, models, GPUs or inference hosts.

Tests: one tiny CPU task with real received correlation, two distinct tiny
requests proving foreign graph/copy/output refusal, missing/dropped/stale/
reordered nonce and evidence controls, CPU loopback RPC causal joins and
SET/GET ordering/completion, padded extents/owner-scoped composites/aliases/
resource overruns, unchanged computation bytes, collector authentication and
ordinary-runner zero-POST/static and rejected-output/dynamic controls. These
prove producer and contract behavior only; no full-Q8 or CUDA qualification.

STOP on identity/main drift, source/patch/evidence mutation, carrier ambiguity,
required UNKNOWN, missing native correlation, deadline/resource breach,
uncontrolled process/listener, changed mathematics/scheduling/route, fixture
failure, or any need for a second build/expanded scope. Preserve all failure
bytes and remaining budget. No retry-until-PASS, deployment, hosted final
validation, merge or issue closure.

## Governance

PR #305 remains OPEN/DRAFT/unmerged; #302 and #299 remain open; #303 remains
pending integration; #300 is untouched. Offline green tests and advisory
reviews do not close the usable production-runner gap or grant native authority.

# Q8 fixed two-CUDA topology (#313)

This is the smallest opt-in software slice for issue #313. It does not record
a physical result or authorize a hardware run.

## Fixed topology

`selection: two-gpu` keeps the complete Q8 source and layers 0--40 on the CPU
coordinator. One small-RAM worker owns two complete CUDA layer ranges:

| owner | native selector | coordinator selector | complete states | encoded weights |
|---|---|---|---|---:|
| coordinator CPU | `CPU` | `CPU` | embeddings and layers 0--40 | 168,221,585,536 B |
| worker GPU 0 | `CUDA0` | `RPC0` | layers 41--44 | 11,035,064,960 B |
| worker GPU 1 | `CUDA1` | `RPC1` | layers 45--47 and output | 8,957,357,824 B |

The byte census comes from the exact pinned Q8 metadata used by the operator.
It is a lower bound, not a fit verdict. Each VRAM domain is admitted separately
with its own weights, persistent state, backend allocation, graph, workspace,
observer and reserve. Worker RAM is charged separately for assigned metadata,
page residence, verification, transport and bounded receive/cache staging,
plus the logical cross-device RPC payload and unknown overlap/runtime heap.
The mode requires assigned-only backing; the worker has no full-source backing
and no permanent host weight mirror.

The pinned RPC server accepts one connection and synchronously serves it until
disconnect. One listener therefore cannot back the client's two persistent
dispatchers. The worker instead runs two owned processes on distinct ports:
`rpc0 --device CUDA0` and `rpc1 --device CUDA1`. The coordinator registers both
listeners in that order and selects `RPC0,RPC1`; `--gpu-layers 8
--tensor-split 4,4` places four complete layers on each. Because these are
distinct dispatchers, the GPU0-to-GPU1 boundary uses the existing generic
coordinator-staged GET/SET route. No P2P or server-local GPU copy is assumed.
Duplicate ports, different worker hosts, reversed primary ownership and
`server-local` routing refuse.

Assigned acquisition authenticates the complete two-bank cache first, then
publishes a distinct immutable assigned guard for each server's disjoint tensor
bank. The server guard narrows hash-backed lookup/publication, but it is not a
general destination firewall: it does not by itself reject every raw SET or
prove CUDA placement. Endpoint-bound execution observations provide that proof.
Both processes and their unknown runtime heaps are owned, accounted and
cleaned up independently. Existing `cpu-only` and `one-gpu` launch receipt
shapes remain unchanged.

"Shared cache" means one already prepared and completely authenticated durable
cache root, not a shared upload guard. Each listener receives only its bank's
guard. Ordinary startup finds every immutable key present and opens it
read-only. If a later exact assigned repair is needed, the native patch stages
through a unique `mkstemp` file and the two banks have distinct validated cache
keys, so the listeners never publish to the same final path. Duplicate cache
keys are rejected during source admission. Admission reserves the complete
retained eligible set plus the largest eligible repair in each binding bank,
so two simultaneous listener temporaries fit without changing the historical
single-listener reserve calculation.

Existing `cpu-only` and `one-gpu` selections and their identity rows are
unchanged. Assigned-only v7 acquisition, immutable tensor identities,
whole-tensor guards and missing-only restart reuse are reused without a new
cache or protocol.

## Honest observation boundary

The reviewed CUDA build closure is eligible for static planning/lowering only.
The retained transfer observation ABI identifies RPC operations but not the
endpoint/device ordinal for each occurrence. It cannot prove the required
`RPC0 -> coordinator staging -> RPC1` transition, so ordinary dynamic
reconciliation of `two-gpu` still explicitly refuses.

The collected runner provides a narrower diagnostic path. It binds each owned
listener endpoint to its process PID/start, admitted binding physical ID,
native selector and per-bank upload guard; it requires an observed RPC command
on each listener and retains the raw response and its digest. The result is
always `EXECUTED-OUTPUT-UNACCEPTED` (or
`EXECUTED-OBSERVATION-REFUSED`) and never physical qualification. A hardware
receipt must additionally join each PID/listener to a GPU UUID and prove
residency and execution on that UUID. Source inspection or a CPU fixture must
not mint a qualified CUDA identity.

The later bounded hardware recipe is
[`../../tools/native-cache/q8-two-cuda-recipe.md`](../../tools/native-cache/q8-two-cuda-recipe.md).
It requires real per-device and host budgets before launch. The exact encoded
GPU weight sum is 19,992,422,784 B, but it is only a placement hypothesis. The
coordinator assignment is 168,221,585,536 B, larger than the stated roughly
125 GiB RAM, so admission must use a measured lazy/file-backed working-set and
paging budget rather than imply full CPU weight residency.

## Offline evidence

Focused regressions cover the pinned serial-listener constraint, two-process
selector/endpoint order and native argv, nonoverlapping
whole-layer/tensor ownership, final output ownership, independent VRAM refusal,
bounded worker-host charges, unsupported route refusal, assigned-only backing
projection and explicit dynamic-observer refusal. Existing CPU/loopback suites
continue to cover old modes, complete assigned-bank loading, restart reuse,
changed inputs and failure cleanup. Those fixtures do not prove CUDA execution,
residency, numerical correctness or capacity.

The existing native-cache CI fixture additionally builds the actual pinned CPU
RPC server and proves that two server processes on distinct listeners can each
hold a client connection at the same time, concurrently transfer different
whole tensors through the shared cache, expose two simultaneous distinct repair
temporaries within the summed bank reserve, read them back exactly, and reuse
both keys with zero warm weight payload. This proves the native two-listener route
mechanism on CPU only; it does not prove CUDA enumeration, residency, kernels,
P2P, capacity or output acceptance.

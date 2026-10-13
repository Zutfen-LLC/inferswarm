# Remote resident-block overlap: RPC feasibility (Phase 1, source-based)

Offline, source-only investigation for the follow-on to PR #307. Question: can
the existing pinned llama.cpp RPC backend support a bounded two-host
resident-MoE-block overlap prototype — coordinator computes routing and the
shared branch locally, one remote GPU worker retains the routed-expert
weights across requests — **without** a new protocol, scheduler, loader or
engine?

Every claim below cites the pinned tree (`llama.cpp b29c606e28a01b1bc8c1351026a0fa6e616bf6c4`,
`ggml/src/ggml-rpc/ggml-rpc.cpp`, protocol v6.0.0, TCP transport). Verdict:
**YES — proceed with a small implementation; no native patch needed.**

## 1. Can expert tensors/buffers stay resident across repeated requests?

Yes, by construction. `rpc_server::alloc_buffer` inserts every allocated
buffer into a connection-lifetime `buffers` set; only `~rpc_server` — invoked
when the client disconnects (`rpc_serve_client` returns) — frees them
(`for (auto buffer : buffers) ggml_backend_buffer_free(buffer)`). There is no
eviction, TTL or re-negotiation anywhere in the server loop. A coordinator
that uploads the three Q8_0 expert-slice tensors once (setup) reuses the same
remote allocations for every subsequent request. `RPC_CMD_FREE_BUFFER` exists
but is only sent by the client's `free_buffer` — never triggered during the
request loop.

## 2. Which calls block, and can remote work overlap local shared work?

Traced through the actual implementation — the function name
`graph_compute_async` alone is not proof, so each path was followed to the
socket layer:

- `ggml_backend_rpc_graph_compute` (the iface target of both
  `ggml_backend_graph_compute_async` and `ggml_backend_graph_compute`, which
  the generic layer defines as async + `synchronize`) enqueues via
  `dispatcher->send_async(RPC_CMD_GRAPH_COMPUTE, …)`. `send_async` is a
  **pure queue push** (`queue.push(msg)`, no future wait). Critically,
  `RPC_CMD_GRAPH_COMPUTE` has **no response** at the wire level (the server's
  `case RPC_CMD_GRAPH_COMPUTE` branch sends nothing back; the no-response
  `send_rpc_cmd` variant is used). So graph dispatch never blocks the caller
  and there is no completion signal either.
- `set_tensor_async` likewise enqueues without waiting; the host source bytes
  are copied into the request buffer synchronously at call time, so the
  caller's activation vector is consumed before return. (For payloads > 10 MiB
  — `HASH_THRESHOLD` — the client first does a *blocking* hash round-trip;
  our steady-state payloads are far below this, and setup uploads use the
  blocking `tensor_set` path anyway.)
- `ggml_backend_synchronize` on the RPC backend posts a dummy
  `RPC_CMD_NONE` message and waits for the dispatcher IO thread to complete
  it. Because the IO thread processes the queue strictly in order, this proves
  all *requests were sent* — it is a client-queue drain, **not** a
  server-compute join.
- The **only response-bearing data path is `GET_TENSOR`**
  (`ggml_backend_rpc_buffer_get_tensor` → blocking `send` with output). The
  server loop is strictly serial per connection: it reads a command, fully
  executes it (including `ggml_backend_graph_compute` on the device), then
  reads the next. Therefore a `GET_TENSOR` response can only be produced
  after every previously enqueued `GRAPH_COMPUTE` on that connection has
  finished executing remotely. The D2H read-back is the natural join point.

**Overlap recipe (client-only, no protocol change):**

```
dispatch: set_tensor_async(cur/ids/w) ; graph_compute_async(sec_plan)   // non-blocking
local:    CPU shared branch (+ CPU expert subset when split > 0)        // concurrent
join:     get_tensor_async(partial_sec) ; synchronize                   // blocking response
combine:  out = (partial_cpu + partial_sec) + shared                    // same arithmetic order
```

The coordinator's dispatch returns immediately; the remote compute and its
wire transfer overlap the local shared-branch work. The existing PR #307
overlap arm already has exactly this call structure, so the pinned client's
internal single dispatcher IO thread per endpoint already provides the
"dedicated worker thread owning remote operations" — no additional harness
worker thread is required, and none was added.

**Serial arm:** unchanged semantics — blocking `tensor_set`, blocking
`graph_compute` (= async dispatch + `synchronize`), then blocking
`tensor_get` before any local stage begins. Both arms execute identical work
with identical placement.

## 3. Thread-ownership and buffer-lifetime constraints

- All client-side socket writes happen on **one dispatcher IO thread per
  endpoint** (started in `rpc_dispatcher::start`); caller threads only push
  mutex-protected queue entries. Single-writer socket ownership; the
  coordinator thread never touches the socket. Concurrent multi-threaded use
  of one backend handle is therefore safe *by queueing*, not by parallel
  remote execution — the server remains serial per connection.
- `get_tensor_async` hands the caller's destination buffer to the IO thread,
  which fills it later; the destination (and any source buffers referenced)
  must stay alive and unmodified until the join. The harness's existing
  ArmContext-per-repetition and join-before-free discipline (validated by the
  `TestReturnedComputeFailures` suite) satisfies this unchanged.
- Remote buffers are freed only at connection close (see §1) or explicit
  client `free_buffer`. Server-side graph metadata (`stored_graphs[device]`)
  survives across requests on the same connection but is keyed to graph uid
  (below).
- Failure semantics: transport errors surface as
  `GGML_ABORT("Remote RPC server crashed or returned malformed response")`
  from `RPC_STATUS_ASSERT` — the process aborts; it never returns a stale
  output that could be compared as success. There is **no hard cancellation**:
  an unresponsive endpoint can hang the dispatcher thread indefinitely; the
  recipe must bound runs with an external process timeout (verified offline:
  dead endpoint → immediate abort, rc 134, no JSON emitted).

## 4. Graph-metadata resend (known, bounded)

`ggml_backend_rpc_graph_compute` takes a `GRAPH_RECOMPUTE` fast path
(metadata-free, tiny `rpc_msg_graph_recompute_req`) when
`cgraph->uid != 0 && last_graph_uid == cgraph->uid`. The harness builds each
repetition's expert graphs with `ggml_new_graph` + `ggml_build_forward_expand`,
which never sets `uid` (only `ggml_backend_sched` does, at
`ggml-backend.cpp:1085`). So every expert-plan compute sends a full
serialized graph: `4 + 4 + 8·n_nodes + 4 + 120·n_tensors` bytes
(`rpc_tensor` is 120 bytes packed). For the split-0 secondary plan
(~30 nodes, ~40 tensors) this is ~5 KiB per invocation — small relative to
the activation payload, reported separately in the run report as graph
metadata traffic, and **not** weight retransmission. Weights are never
resent during the request loop (client-side accounting + wire-level check in
the loopback test).

## 5. Build changes and measurements (minimal)

- Build: link `ggml-rpc.cpp` + `transport.cpp` (TCP; RDMA is CMake
  auto-detection, compile-time `GGML_RPC_RDMA`, not defined) into the harness
  closure and add a 100-line worker binary that calls
  `ggml_backend_rpc_start_server` (the pin's own server entry point, the same
  one `tools/rpc/rpc-server.cpp` uses). `GGML_USE_RPC` is NOT defined so the
  global backend registry is untouched; the harness reaches the client
  through `ggml_backend_rpc_init(endpoint, 0)` directly. No kernel, protocol
  or loader changes; the pin's sources are used verbatim.
- Measurements added (RPC mode only; existing fields unchanged): per-rep
  `serial/overlap_request/response_bytes` at the secondary call sites
  (measured application payload, cross-checked against calculated tensor
  sizes), `expected_*_bytes` (calculated), setup `secondary_weight_bytes`
  (calculated) alongside the existing `secondary_slice_ms` setup-upload time,
  and the existing per-stage `h2d/sec/d2h` client-observed intervals, now
  labeled as transport-inclusive wall-clock — never GPU kernel time.
- A context check from the task: at T=128 an F32 [128, 2560] activation is
  1.25 MiB each way; at Gigabit (~112 MiB/s) the input+output payload alone
  is ~22 ms before protocol overhead — comparable to the entire measured
  single-host overlapped phase (15.7 ms). The hardware recipe therefore
  measures rather than assumes; the loopback numbers on loopback TCP are
  contract evidence only, not performance evidence.

## Limitations recorded

- The RPC protocol at this pin transports **no remote device identity**: the
  client device description is literally the endpoint string, and
  `device_get_type` is hard-coded `GPU` without asking the server. The run
  report records `remote_device_identity: NOT_TRANSPORTED_BY_RPC_PROTOCOL`
  plus the observed device-memory snapshot; an "RPC" label alone cannot prove
  the remote CUDA arithmetic profile, and no numerical reference
  reconstruction is offered for the rpc secondary
  (`reference_secondary_mode: rpc-remote-unverified`;
  `check_reference.py` rejects that mode fail-closed, while the narrow
  `moe-scheduling-equivalence/1` checker remains applicable — scheduling
  equivalence and numerical qualification stay separated).
- No hard cancellation; external process timeout required (documented in the
  recipe).
- One worker, one endpoint, one resident block; no fallback, eviction,
  compression or placement optimization anywhere.

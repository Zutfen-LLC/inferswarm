# Two-node hardware recipe: remote resident-block overlap (RPC)

Proposed, **separately authorized** hardware steps for measuring the PR #307
overlap mechanism with the routed experts on a remote GPU worker. Nothing
here is execution authority; run it only after maintainer dispatch through
the normal Hermes handoff. Preconditions: PR #307 merged or its branch
available; this stacked branch at the reviewed head; the pinned llama.cpp
source verified per `build.py` (commit + tree digests).

## Topology and roles

- **Coordinator** (CPU-only is sufficient): runs `moe_overlap_harness` with
  `--secondary rpc --rpc-endpoint HOST:PORT`. Owns routing, the shared
  branch, the CPU expert subset (empty at `--split 0`), both scheduling arms,
  all validation and reporting. One process, one connection.
- **Worker** (GPU host, e.g. inferswarm01/03/04): runs `moe_rpc_worker`
  (built with `build.py --cuda --rpc-worker`). Serves exactly one backend
  device over the pinned RPC protocol v6.0.0 (TCP). Binds `127.0.0.1` by
  default — for cross-host use pass `--host <lan-ip>` and keep the port on
  the homelab LAN/VLAN only (the pin's rpc-server prints the same
  never-expose warning; the protocol has no authentication).
- Link: Gigabit LAN measured baseline (the run reports application bytes;
  physical throughput is measured, not assumed).

## Build (per host, bounded)

Coordinator (CPU-only closure is sufficient — the RPC client links in):

```
python3 tools/moe-overlap/build.py --jobs <n>
```

Worker (full CUDA closure; budget 60+ min for the 188-TU nvcc phase on the
3060-class hosts — see the PR #307 CUDA build lessons; same libcuda.so
symlink and nvcc-wrapper notes apply):

```
python3 tools/moe-overlap/build.py --cuda --rpc-worker --jobs 2
# (produces moe_rpc_worker_cuda — a distinct name from the CUDA harness
# binary, so the two roles never overwrite each other in the shared cache)
```

Record binary sha256s, the pinned source verification output, and
`--list-devices` output on the worker host.

## Session sequence

1. **Startup order and readiness.** Start the worker first:
   `moe_rpc_worker --host <ip> --port <port> --device CUDA0` (exact device
   name from `--list-devices`). Readiness = the `RPC_WORKER device=…` banner
   PLUS a TCP LISTEN row for the bind address (do not probe the protocol
   port with a connect-and-close; it emits an RPC protocol error). External
   bound: `TimeoutStartSec` via systemd-run, or a shell `timeout`.
2. **Setup/residency (measured separately).** The harness's load phase
   uploads the three Q8_0 expert-slice tensors once
   (`load.secondary_slice_ms`, `load.secondary_weight_bytes` in the report).
   Verify device-memory drop on the worker roughly matches
   `secondary_weight_bytes` (nvidia-smi before/after); residency for the
   whole session follows from the connection-lifetime buffer semantics
   (rpc-feasibility.md §1).
3. **One-case scheduling validation (Phase A).** Exactly one exported
   scheduling check per shape:
   `--warmup 0 --reps 1 --dump-reference-case <new-dir> --self-check-negative`
   then `check_scheduling.py <dir>` — must return `SCHEDULING_EQUIVALENT`
   before any timing run. Do NOT apply the one-repetition scheduling checker
   to timing runs, and do not extend it to multi-repetition certification
   (one-repetition scope is its contract).
4. **Fixed-input paired timing (Phase B, only after Phase A is green).**
   `--warmup 3 --reps 10` (no dumps), synthetic or captured activations via
   `--inputs-file`. Guards are the native per-rep checks (routing counts,
   bitwise arm equality, determinism replay, negative control); the exit-3
   legacy-numerical-only classification rules from PR #307 carry over
   unchanged.
5. **Shapes.** T=1 and T=128, `--split 0` (all routed experts remote, shared
   branch local — the placement that matches the single-host boundary
   experiment). Optional single confirmation shape at an intermediate split
   is NOT part of the minimal recipe.
6. **Resource bounds and cleanup.** Run each phase under a unit that bounds
   the RUN, not just startup: `sudo systemd-run --unit=… --property=Type=oneshot
   --property=MemoryMax=16G --property=MemorySwapMax=0
   --property=RuntimeMaxSec=<ceiling> --property=TimeoutStartSec=<start-ceiling>
   --wait bash -c '… ; echo $?>run.rc'`. With the default `Type=simple`,
   `TimeoutStartSec` expires once the process has merely STARTED and does not
   bound execution — `RuntimeMaxSec` (plus `Type=oneshot`, where
   `TimeoutStartSec` covers the whole run) is what limits a stall (no hard
   cancellation exists in the transport; the unit kill is the bound).
   Sample GPU temp/util, MemAvailable and cgroup peak externally.
   Cleanup: terminate the harness first (it closes the connection, which
   frees all remote buffers), then SIGTERM the worker by exact PID, verify
   `ss -tln` empty for the port and no leftover processes; chown any
   root-owned artifacts back to the working user.

## Reading the results honestly

- `serial_stages`/`overlap_stages` `h2d_ms`, `sec_ms`, `d2h_ms` are
  client-observed wall-clock intervals that include RPC protocol processing
  and network transfer — they are never "GPU kernel time".
- Per-rep `rpc.*_bytes` are measured application payloads at the call sites
  (cross-checked against `expected_*_bytes`); `load.secondary_weight_bytes`
  is the setup weight traffic. Physical network traffic additionally
  includes TCP framing and per-compute graph metadata (wire-observed ~9.7
  KiB per GRAPH_COMPUTE at split-0 T=128 shapes; the pinned client does not
  expose it to callers, so measure it externally if exact wire traffic is
  needed). The report's `weights_retransmitted_in_request: "no"` is the
  client-side accounting statement, cross-checkable externally (a transparent
  loopback proxy observed exactly three setup uploads and none after).
- Compare against the single-host baselines sequentially (placement and
  backend confounds documented in PR #307): T=128 serial 29.394 ms /
  overlap 15.749 ms, CPU shared ~14.4 ms, GPU experts ~13.8 ms, router
  ~22.2 ms. At Gigabit the T=128 activation payload alone is ~22 ms before
  overhead, so the remote overlapped phase may plausibly be network-bound —
  that is the measurement, not a failure.
- Numerical qualification: `reference_secondary_mode` is
  `rpc-remote-unverified` (the protocol transports no backend identity);
  `check_reference.py` refuses the mode. Scheduling equivalence
  (`check_scheduling.py`) remains valid. Both arms can share a numerical
  defect; nothing here upgrades the preserved legacy FAIL diagnostics.

## Stop conditions

- Phase A not `SCHEDULING_EQUIVALENT` → stop; preserve the export.
- Any worker abort / malformed-response abort → stop; preserve logs.
- Unit timeout or watchdog trip → stop; treat as inconclusive, not a pass.
- Device-memory shortfall at setup → do not shrink placement; stop.

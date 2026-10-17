# Opt-in native expert-demand capture under the guarded two-CUDA path (#314 integration)

## Scope and starting point

Started from freshly fetched `origin/main`
`dc35fdfa2553a2b09f09fd03b4cde28284999ae8` (PR #336 merge; no later
commits) in an isolated worktree on `issue-314-demand-integration`. This
continues #312 and supplies inputs for #314. No placement experiment,
launcher framework, physical validation dispatch, merge or deploy happened
here. The inference hosts were never contacted.

## What this adds

1. A composed CPU demand-client builder,
   `tools/native-moe-overlap/demand-build-composed.py`. It reuses the
   authenticated pin archive (`b29c606e…`, archive
   `03fb0431…`), the complete #311 assigned-cache + #301 observer
   composition (RPC v7), the #309 qwen4exp overlap overlay, the #312 demand
   collector, and the reviewed optimized-CPU recipe's exact options
   (`Debug -O3 -g0`, assertions retained, `-DCMAKE_EXPORT_COMPILE_COMMANDS`).
   It emits one binary, `native-demand`, plus a separate candidate build
   manifest (`native-demand.build-manifest.json`,
   schema `native-demand-composed-build/1`). The builder never invents or
   substitutes a reviewed binary hash: the manifest records the actual
   composite, patches and executable digest of this build only. Both accepted
   step-a/optimized executables keep their exact identities; the composed
   tree is derived fresh from the archive, never from a historical overlay.
   The accepted worker (CUDA03 `ggml-rpc-server`) is not rebuilt.

2. `demand_cli.cpp` operator parity: a finite accepted option table. The
   `--rpc-endpoints`/`--devices` two-listener block accepts exactly the
   guarded 41/45 lowering (`gpu_layers=8`, `tensor_split=4,4`, `split_mode
   layer`, `fit off`, `lazy on`, `load-mode none`, KV offload on, f16 K/V,
   op-offload off, flash-attn off, no unified KV, `parallel 1`, explicit
   ctx/batch/ubatch/threads). Both endpoints and the `RPC0,RPC1` device
   order are validated (`host:port`, distinct) before any model load.
   Unknown flags are refused (`unsupported profiling option: …`) instead of
   being silently stored. The legacy single-endpoint overlap selection
   (`--rpc-endpoint` + `--rpc-tensors-regex`) is unchanged and exclusive
   with the operator block. Context settings mirror the guarded client
   exactly (`n_seq_max=1`, `flash_attn_type DISABLED`, `type_k/v F16`,
   `offload_kqv true`, `op_offload false`, `kv_unified false`,
   explicit threads); the threads default in the runner mirrors the pinned
   server's `-t` default (`SC_NPROCESSORS_ONLN`, not
   `hardware_concurrency`).

3. An opt-in `demand` block in the frozen `q8-two-cuda-session/1` JSON
   (`inferswarm/operator/q8_demand.py`). Absent block = byte-identical
   previous behavior (the session validator now additionally accepts the
   one optional top-level `demand` key). A present block must name exactly
   one MEASURED request (never a warmup), carry its exact prompt (so warmup
   and measured captures cannot mix), absolute reviewed client
   manifest/executable paths, digests, and bounded `max_rows`/`decode_steps`.
   The declared `client_sha256` must equal the reviewed successor manifest's
   `executable_sha256` when the manifest body is supplied.

4. The smallest runner path (`OperatorRunner._run_demand_capture`): after
   the workers load and before the session POSTs, one `demand` process is
   spawned through the SAME lease manager (name `demand`, coordinator
   aggregate cap, systemd supervision, PID/start identity, cleanup), reads
   the frozen session prompt from the owned invocation directory, connects
   to the already-listening `rpc0`/`rpc1`, and writes its bounded export to
   a fresh path in the same invocation directory. Identity admission is
   fail-closed: the manifest is read through the collector transport, parsed
   with the existing `parse_build_manifest`, its options/patch/base must
   match the reviewed optimized-CPU client shape, and the executable BYTES
   are read and hashed to match the declared digest. The capture wait reuses
   the campaign's absolute deadline (`guard.checkpoint`).

5. Durable export through the existing private evidence store:
   `demand-capture-started.json` / `demand-capture-finished.json` /
   `demand-export.json` are retained with manifest digests, register_attempt
   before dispatch (lost spawn replies still get retention attempted), and
   the export byte bound (16 MiB) is enforced with honest
   `missing`/`oversize`/`retention-failed` states. The session report gains
   `outcomes.demand_capture` (`disabled`/`EXPORTED`/`COLLECTION-MISSING`/…)
   SEPARATE from general observer completeness: the general observer's
   known ring saturation neither erases the demand export nor is relabeled.

6. `tests/test_native_moe_overlap.py`'s hard-coded
   `/home/zutfen/llama.cpp-252` optional-source path is replaced by a
   portable `_pinned_source()` resolver (env override
   `MOE_OVERLAP_PINNED_SOURCE`, else the pinned checkout adjacent to the
   repo), authenticating BOTH the pinned commit and its tree SHA; absent
   trees skip the optional source-bound assertions cleanly instead of
   failing. The regression itself is preserved, not weakened.

## Coverage contract preserved

The capture still uses one contiguous prefill and one-token decodes with
`logits=null`/`embeddings=false`; earlier prefill layers retain all prompt
positions, the final layer the last output position, decode positions
continue afterward; no extra logits or expert work are requested. The
`qwen4exp-last-output` coverage validation in the #312 reducer is reused
unchanged. Unsupported batching/output-selection shapes remain refused by
the reducer's exact token-position mapping.

## Tests

`tests/test_issue314_demand_integration.py` (16 tests): default-off
inertness; measured-request/prompt binding incl. warmup refusal; bounds,
digest, path and unknown-field refusals; reviewed-manifest digest binding;
exact 41/45 argument propagation (both endpoints, device order, layer/tensor
split 4,4, gpu 8, offload/KV/flash/ctx/batch/ubatch/threads); source-level
unsupported-option refusal; real #312 capture/reducer fixtures for
phase/position mapping and capacity/drop reporting; coordinator-cap spawn
parity with ancillary refusal; durable export on success plus honest
interrupted-collection incompleteness through the real evidence store; and
the review-correction pins (parsed-manifest use, authenticated file_type
mapping, client-host thread observation).

## Independent review and correction pass

One scoped independent review at `06a5498e` returned NO-GO with one blocking
defect and related findings; all were corrected at `a9befed7`:

1. Manifest admission double-decoded `read_json`'s parsed object and
   therefore rejected every valid manifest (blocking).
2. `file_type` was hardcoded; it is now mapped from the plan's
   authenticated model metadata (the pinned Q8 model is file_type 7).
3. Threads were guessed from the controller; they are now observed on the
   client host through the guard channel, refusing when unobservable.
4. Prompt staging/export read touched controller-local paths for
   client-host files; a bounded exclusive lifecycle `write` action (owned
   invocation directory only, 64 KiB, O_EXCL, escape-refused) stages the
   prompt and the collector transport reads the export back.
5. The capture was marked FINISHED regardless of the supervised unit's
   result; the unit `Result` now decides and nonzero/unknown exits are
   honest failure states.
6. The CLI refused legacy `--gpu-layers`, changing main's behavior; exact
   legacy behavior is restored and operator-only flags outside the parity
   block are refused instead of ignored.

The reviewer's probes (default-off canonical byte identity, digest bypass
refusal, warmup binding refusal) all passed unchanged.

## Second review pass (complete report disposition)

The reviewer's full report added three findings beyond the six above; all
are corrected at `cda47e28`:

1. **Blocking** — the lifecycle admitted `demand` at spawn but refused it in
   the `log` and `alive/inspect/stop` allowlists, so the first liveness
   check failed and lease cleanup could not stop the unit (the aggregate
   slice backstop still bounded it). All three allowlists now admit
   `demand` together, pinned by an end-to-end spawn/alive/log/stop/release
   regression on the real lifecycle.
2. **Blocking** — the pinned RPC server serves ONE connection synchronously,
   so the demand client could never register while the loaded session client
   held the workers' connections. The capture now runs AFTER the frozen
   session's requests with the ordinary client stopped (lease row removed)
   first; the workers stay up and their validated assigned cache serves the
   demand client's load through the existing #311 restart-reuse path.
3. **Contained** — `save_session_json` returns False on refusal; its result
   is now honored so a refused export write downgrades to
   `retention-failed` instead of labelling the export `retained`.

Feasible local checks run: composed CPU build of `native-demand`
(-O3/Debug, RPC v7, links clean), `-fsyntax-only` against the pinned tree,
focused suites (issue314, q8_experiment, issue313, native_moe_overlap,
issue311 backing/startup), and the CI planner/retention gates. These are
NOT host builds of the accepted pair, model execution, or Final CPU
Validation.

## Registration

The new test module is registered on all four CI surfaces in this change:
`scripts/plan_ci.py` (group + path rule), `scripts/ci_groups.json`
(regenerated through `--emit-registry`), the `issue-99-103` unittest line in
`.github/workflows/ci.yml`, and `docs/ci/test-retention-audit.json`
(`--self-check` OK, retention check OK, PR-mode classification lands in
`issue-99-103`).

## Limits

The composed demand client is a CANDIDATE receipt, not an accepted runtime
identity; using it requires a separate additive identity review (a successor
manifest table), exactly like the optimized-CPU path did. Nothing here
changes normal model execution, the accepted workers, 41/45 placement,
selective backing, source-digest reuse or resource limits. Profiling remains
distinct from evaluation prompts; prompts/token IDs/generated text stay out
of structural exports. No fit, speedup, correctness or GPU claim follows.

## Third review pass (PR #337 head 3f42add1): two runner defects

Both findings were reproduced RED on a pristine `git archive` of the
reviewed head (same test file, same assertions) and are corrected here.

1. **Monitored ownership through the client->demand handoff** — the reviewed
   head stopped the ordinary client and deleted it from the runner rows and
   lease ownership, but `CampaignGuard.rows` kept the copy registered by
   `process_started`; the next 2 s monitor tick inspected the removed
   client, raised `KeyError('client')`, and the monitor error path called
   `stop_units()`, aborting demand capture. The handoff is now ONE
   synchronized guard transition (`retire_client_for_demand`): stop
   confirmed, then atomic removal from the monitored set AND lease
   ownership, all under a `_rows_lock` the monitor ticks and every
   `process_started` registration also hold. The demand process is
   registered with `process_started` under the same lock and inspected as a
   COORDINATOR process (client host, coordinator cap, client-host log
   tail); after its confirmed exit it leaves only the monitored set
   (`retire_finished_demand`) while lease ownership is retained for
   terminal cleanup. Real process-loss detection is unchanged: any other
   inactive/mismatched unit — including a killed demand unit between exit
   and retirement — still stops the campaign, and the owned-unit sweep
   stops every still-owned process. A terminal demand unit with an own-exit
   systemd result is a classified completion, not a loss.
2. **Lifecycle completion response shape** — `lifecycle.py` returns the
   systemd receipt nested (`{'unit', 'properties': {..., 'Result'}}`) but
   the runner read a top-level `Result`, so every successful capture was
   classified `unknown-exit`/FAILED and never reached export readback. The
   runner now consumes the real shape: `success` reaches bounded export
   readback and retention; `exit-code` is an honest `client-exit` failure;
   missing/malformed completion stays `unknown-exit`; a signal/oom/timeout
   result is a genuine process loss that retains the honest receipt and
   raises (campaign stop). `save_session_json` returning False still
   downgrades to `retention-failed`, never `retained`.

Regressions added (real runner/guard methods, external host operations
faked): monitor ticks advancing through the handoff without a false STOP;
tick blocking inside the critical section; coordinator/worker cap and
log-host attribution; genuine demand loss stopping the campaign with full
owned cleanup; finished-demand classification; nested success reaching
export readback; failed/malformed completion never claiming success;
retention failure after successful execution; and one end-to-end
`run_experimental_campaign` with an opt-in demand block (client stop before
demand spawn, no worker stop before capture, durable `demand-export.json`,
`outcomes.demand_capture=EXPORTED`).

Local: issue314 (30), q8_experiment+issue313+issue311 (133),
native_moe_overlap+plan_ci+project_status (174), finalize_repository (73),
issue299_runtime, `finalize_repository.py --check` and
`sync_project_status.py --check` green; `plan_ci.py --mode pr` classifies
every changed path into the existing `issue-99-103` group (no registration
change needed — the module was already registered on all four surfaces).
Still no host contact, native build, model execution, identity promotion or
Final CPU Validation; the composed client remains a candidate receipt.

## Completion lifecycle correction (from head `3ba45811`)

The supervised demand service alone now sets `RemainAfterExit=yes`. Successful
transient services otherwise become eligible for garbage collection before
their completion receipt and later explicit stop can be collected. Ordinary
client/RPC services keep their existing launch and cleanup behavior.

Demand inspection includes loaded/retained state and the main process's exit
code. Monitor ticks and export readback use the same owned-unit check:
`active/exited`, `MainPID=0`, `ExecMainCode=1`, `ExecMainStatus=0` is successful
completion; a normal nonzero exit remains a failed capture. Missing or
mismatched units never prove success, and signals/OOM/timeouts still stop the
campaign. The finished service remains lease-owned until explicit stop and
release; no stop error is suppressed.

Systemd may prune an exited service's empty cgroup while retaining the unit.
Its unavailable live swap counter is retained as unavailable, never rewritten
to zero. That terminal case requires the owned successful completion, the
unchanged coordinator/zero-swap caps, and an empty cgroup; aggregate enforcement
and final empty-slice checks remain in place.

Focused regressions drive the real lifecycle launch/inspect/stop/release and
runner export retention with only system calls and host reads faked, including
the launch-controlled unit lifetime and pruned-cgroup counters. Wrong-unit,
malformed, failed-exit, timeout, retention refusal and default-off controls are
preserved. No real service, native build, model read or hardware operation was
performed. This is a correction to the existing opt-in path, with no change to
capability, accepted identity, frozen limits or execution authority; managed
status declarations remain unchanged.

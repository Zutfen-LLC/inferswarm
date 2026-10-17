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

`tests/test_issue314_demand_integration.py` (13 tests): default-off
inertness; measured-request/prompt binding incl. warmup refusal; bounds,
digest, path and unknown-field refusals; reviewed-manifest digest binding;
exact 41/45 argument propagation (both endpoints, device order, layer/tensor
split 4,4, gpu 8, offload/KV/flash/ctx/batch/ubatch/threads); source-level
unsupported-option refusal; real #312 capture/reducer fixtures for
phase/position mapping and capacity/drop reporting; coordinator-cap spawn
parity with ancillary refusal; and durable export on success plus honest
interrupted-collection incompleteness through the real evidence store.

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

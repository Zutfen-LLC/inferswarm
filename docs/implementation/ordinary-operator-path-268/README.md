# Issue #268 — ordinary operator path (design mapping)

> **Post-acceptance note.** Issue #268 was accepted by the maintainer as
> `R8K_QWEN_CUDA_ORDINARY_OPERATOR_PATH_PASS` on exact PR #269 head
> `438c09ff1f3fb0e161f0bbf6d8389554ab8a1515`
> ([acceptance](https://github.com/Zutfen-LLC/inferswarm/issues/268#issuecomment-5979357776)),
> within the bounded scope stated below and in the living status record. The
> status text that follows, and `product-report.md` and `evidence/`, are the
> retained pre-acceptance record and are deliberately unchanged; where they say
> "not accepted" or "deferred", the acceptance comment controls. The path is a
> fixed-topology path for exactly two participants and one three-range layer
> placement; it is not a planner or a general runtime.

**Status:** Task 1 mapping/context, Task 2 CPU-pure config/plan/strategy seam, and Task 3 ordinary CLI/runtime plus CPU regressions are implemented. Three bounded physical ordinary-path requests have been observed and independently reviewed at measured head `478eb5efc93476dc2be990ac738c7ddd40e11eab`; hosted CI run `37169789383` succeeded on that head. #268 remains unaccepted, current-head CI remains separate, and Final CPU Validation is required/deferred until maintainer exact-head GO. The accepted predecessor is Issue #255 `MVP_DISTRIBUTED_INFERENCE_PASS`, accepted by the maintainer closure at https://github.com/Zutfen-LLC/inferswarm/issues/255#issuecomment-5974171991. Its bounded authority is homogeneous NVIDIA/CUDA, `inferswarm01` RTX 3060 + `inferswarm04` RTX 3090, exact Qwen3.8-Flash-Next-UD-IQ1_S three-part release, llama.cpp `b29c606e28a01b1bc8c1351026a0fa6e616bf6c4`, fixed/manual whole-layer placement, participant-local verified backing, ordinary text generation and repeatability. It does not establish numerical equivalence, mixed-vendor or production readiness, dynamic scheduling, performance superiority, or R8-J/Vulkan authority.

## Current gap and proposed entrypoint

At the accepted #267 merge base there was no ordinary InferSwarm CLI/runtime package; repository scripts were evidence tooling. The implemented entrypoint is:

```sh
python -m inferswarm.operator run --config <path>
```

Operators do not invoke the #255 measurement harness. Operators should not invoke `tools/issue255_mvp/*.py` as the product entrypoint.

Configuration/plan concepts remain model-independent and internal/experimental: opaque model/source identity; client/local and remote participant Node/Compute Unit identities; per-participant backing/source paths; explicit fixed immutable placement; generation/request settings. Proposed seams are config validation → immutable operator-authorized plan → participant source/backing identity verification → bounded runtime adapter for connect/startup/readiness/generation/owned-process cleanup → response and structured plan/source/observed-placement receipt. Do not freeze broad public APIs.

| #255 mechanic | Ordinary product responsibility | Retain as measurement-only evidence |
|---|---|---|
| Select source, participants, manual whole-layer split, backing roots, request settings | Operator config and explicit fixed-plan validation | Exact tested host/model/runtime facts remain attributed to #255 |
| Start/connect client and RPC participant, readiness, request, completion | Bounded adapter and ordinary request surface; own/clean only processes created by that invocation | Benchmark harness request instrumentation is not runtime startup |
| Select and verify participant-local backing | Bind source to each participant and fail closed on missing/wrong identity; report source provenance | `prestage.py` GGUF tensor indexing/cache-key logic is not product behavior unless separately justified |
| Attribute execution and lifecycle | Return selected/observed placement and bounded ownership outcome | GPU sampling, TCP/strace attribution, benchmark/repeatability matrix and evidence reduction remain acceptance ceremony |

Keep distinctions explicit: **source** identifies authorized immutable content; **cache/backing** is where verified bytes can be read; **staging** is movement into a target; **residency** is loaded state; **execution** is where computation occurs. One does not prove another.

Generic planner/fabric logic receives opaque identities and the operator-authorized plan; it must not branch on Qwen/model names, GPU vendor/model, hostname, or issue number. Runtime-native flags, GGUF/cache details belong behind the bounded backend adapter. Do not import or invoke the #255 experiment harness from product code, and do not transplant its measurement ceremony.

## Task 2 internal JSON schema and exported API

`inferswarm.operator.config` exports frozen `ModelIdentity`, `CacheRange`, `Participant`, `Placement`, `BackendOptions`, `RuntimeBinding`, and `OperatorConfig`, plus `parse_config(mapping)`, `parse_config_json(text)`, and `load_config(path)`. Schema `operator-config/2` has exact top-level fields `schema`, `plan_id`, `model`, `participants`, `strategy_id`, `placement`, `backend_options`, `request`. Model members require basename `name`, lowercase SHA-256 and `size_bytes`. Participants have explicit `role` (`client` or `remote`), `node_id`, `compute_id`, `transport`, separate `execution_address` and nullable `rpc_endpoint`, `device`, absolute `source_path`, `runtime_executable`, expected `runtime_sha256`, absolute `cache_path`, bounded `port`, absolute `lifecycle_dir`, source identity triplet, and nonempty `cache_ranges`. Each cache range binds `state_id`, member byte `offset`/`length`, SHA-256, runtime `cache_key`, source identity and opaque `unit_id`; ranges are bounds-checked against required member sizes. Every placement unit declares a `state_ranges` inventory (state ID, source member, offset, length). The adapter requires the remote cache descriptors to cover exactly the assigned state IDs and match each declared source range; actual bytes and runtime cache consumption remain Task 3 checks. Client source-GGUF units do not require RPC cache files. Exactly one client/local and one remote/RPC participant are required; input array order does not define roles.

Placement entries explicitly bind opaque `unit_id` and `state_ids` to a `compute_id`, a `state_ranges` inventory (state ID, source member, byte offset and length), inclusive `first_layer`/`last_layer`, and boolean `output`. `backend_options` is strategy-owned typed data: `hidden_layers`, `offload_tail`, `cpu_experts`, two-element `tensor_split`, `context`, `slots`, `startup_timeout_seconds`, `split_mode`, `verbosity`. Request keys are `prompt`, `max_tokens`, finite `temperature`, and `seed` (the accepted default example is seed 42; context 1024 and one slot are in backend options). Strict unique JSON keys, exact schemas, absolute paths, member basenames, unique IDs/ports/cache keys, integer-not-bool bounds and finite numbers are enforced. Config descriptors and expected hashes do **not** establish file presence or verified bytes.

`inferswarm.operator.plan` exports frozen `OperatorPlan` and `build_plan(config)`; digest is SHA-256 over canonical normalized plan JSON and participant order is semantically irrelevant. `inferswarm.operator.strategy` exports frozen `ExpectedPlacement`, `LaunchSpec`, and `llama_cpp_spec(plan)`. The pure adapter accepts typed options only, rejects range gaps/overlaps/duplicate or misplaced output and unbound assigned cache ranges, and deterministically emits the allowlisted llama.cpp argument vector. Native args cannot be supplied in config. For the accepted adapter descriptor, hidden state IDs 0–47 are CPU 0–40, local 41–44, remote 45–47, with output stage 48 assigned remote; `-ngl 8`, CPU expert setting, device/endpoint and tensor split are explicit operator config. Tensor-split weights are not interpreted as equal layer counts. Pure validation describes expected placement only; Task 3 must verify bytes actually consumed by runtime `LLAMA_CACHE` and observe startup's realized placement.

## Phases and limits

1. Task 1 reconciled accepted #255 living status and supplied this mapping.
2. Task 2 provides pure config/plan/adapter seams and focused CPU tests only.
3. Task 3 implements CLI/lifecycle, actual source/cache byte verification and loader-log observation; local CPU fixtures exercised real child processes and the standalone source subprocess. No physical, network or model execution was performed in Task 3.
4. Local and hosted CI must pass before physical Stage 4; only then can bounded physical acceptance be considered under Issue #268 authority.
5. Final CPU Validation remains after explicit maintainer GO. Living status is informational and grants no execution permission.

#268 is not accepted here. Its eventual acceptance requires ordinary-path implementation, focused tests, hosted CI, and bounded authorized physical criteria (three fresh requests, both GPUs materially participating, verified remote local backing, and bounded process ownership). No equivalence, mixed-vendor, production, dynamic-scheduling, performance-superiority, or Vulkan/R8-J claim is made.

## Ordinary invocation (Task 3 CPU verified; bounded physical observations published below, acceptance pending)

Start from `examples/ordinary-two-host.json`: replace `example-run-CHANGE-ME` lifecycle roots with operator-controlled, writable directories on the **corresponding** hosts; confirm SSH aliases, explicit LAN RPC endpoint/bind port, binary paths/hashes, full three-member model SHA-256/size identities, and remote pre-provisioned read-only `LLAMA_CACHE` (`cache_path/rpc/<native-key>`). The example's 71 remote state descriptors match the retained accepted GGUF metadata index, including ranges below the native cache-read threshold. The client uses its verified full source GGUF, not an invented cache state inventory. Cache availability/verification is not evidence that the runtime read each eligible item; a physical trace is still required. The example records historical expected identities, not a claim that those paths/ports/backing currently exist. Source preparation and provisioning are the operator's responsibility, not a dependency on the #255 harness.

From a provisioned controller with noninteractive SSH to both explicit `execution_address` aliases, Python 3 and C compiler on the remote host, and a local HTTP tunnel-capable SSH client, run:

```sh
python -m inferswarm.operator run --config examples/ordinary-two-host.json
```

One invocation handles exactly one nonstreaming `/v1/chat/completions` request. On success stdout contains one JSON object (`response_id`, `text`, `finish_reason`, completion `tokens`, `plan_id`, `plan_digest`, `verified_backing`, `observed_placement`, `cleanup`); failure emits JSON `error`/`type` to stderr and exits nonzero. Change `request.prompt` for each fresh request; changing the prompt changes the plan digest, while rerunning an identical config uses a fresh random invocation token and distinct durable log/helper directories under each lifecycle root. Logs persist in `<lifecycle_dir>/<token>/`; only `<lifecycle_dir>/active` is released on successful exit. Do not reuse an **active** root concurrently.

The strategy fixes CPU prefix 0–40, client CUDA0 41–44, remote RPC0 45–47 and output stage 48, requires `cpu_experts`, and supplies pinned `--rpc`, `--device`, `--split-mode layer`, `--tensor-split 1,1`, `-ngl 8`, `-cmoe`, `-c 1024`, `-np 1`, `--no-warmup`, `-lv 5`. The RPC server receives separately configured physical `CUDA0`, not an inferred mapping from `RPC0`. Pure config/strategy admission precedes filesystem mutation; source verification reads complete member hashes and GGUF metadata on both hosts and each remote range/cache byte identity before launching processes. The remote RPC process is launched first with `LLAMA_CACHE`; before client launch, a bounded readiness barrier on the remote host matches the configured TCP LISTEN address/port to a socket FD of the exact leased RPC PID/start-time identity, without connecting to the RPC protocol. A delayed or absent listener, or a lost participant, fails and enters owned cleanup rather than racing the client. The client server then starts on its host bound to loopback; an owned SSH tunnel exposes only that loopback endpoint to the controller. Loader layer assignments in the client log must match the explicit plan before requesting. A post-request ownership/liveness check prevents treating a completed HTTP reply alone as participant survival.

The tokenized on-host lease records exact child PID and Linux `/proc` start time, pins PID for TERM where supported, waits for actual exit, and never signals unrelated occupants by name. Occupied configured ports or a foreign active lease are rejected; incomplete cleanup preserves the active marker/records and returns an error. A lost spawn reply with a live recorded child likewise retains the lease rather than declaring cleanup successful. **Limitations:** process acquisition-to-record and transport crash windows cannot be fully recovered by this CLI; it has no crash-resume/reconciliation protocol. Verification-to-open races and tunnel port reservation races are not eliminated. Startup loader logs show assignment, not GPU work or actual cache consumption. No model/vendor/hostname-specific policy was added to generic planner/fabric code. CPU tests and source receipts alone do not substitute for physical proof.

## Physical-stage review handoff (observed, not accepted)

The [bounded product report](product-report.md) and [compact physical observation](evidence/physical-observation.json) publish the three fresh ordinary requests, exact measured source/config/runtime/model identities, placement, positive client SM probes, bounded remote CUDA-backend log inference, nine owned remote cache opens per request, and exact cleanup readbacks. The [twelve-entry raw digest manifest](evidence/RAW-MANIFEST.sha256) binds the retained raw receipts/logs in `/home/zutfen/custody/inferswarm-268-r8k-478eb5ef`; the custody manifest hashes all selected raw, authority, review, config and producer files. Original STOP/inconclusive observer ledgers remain unchanged. Remote in-request pmon SM was zero for all three requests; four untimestamped request-bracketed CUDA graph backend lines per invocation support only the bounded source/ownership-backed compute inference. Cache opens are not full-read proof.

Physical-stage independent spec PASS and quality APPROVED are not overall `R8K_QWEN_CUDA_ORDINARY_OPERATOR_PATH_PASS`, and do not accept Issue #268 or freeze its public surface. Final CPU Validation is REQUIRED/DEFERRED pending maintainer GO on the exact final head; current-head ordinary CI and maintainer review remain separate. Living status grants no execution permission: no fourth or further physical request, push or merge is authorized by this publication.

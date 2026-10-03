# Issue #268 — ordinary operator path (design mapping)

**Status:** Task 1 mapping/context; Task 2 CPU-pure config/plan/strategy seam implemented by the correction below; Task 3 runtime, physical Stage 4 acceptance and Final CPU Validation remain pending. The accepted predecessor is Issue #255 `MVP_DISTRIBUTED_INFERENCE_PASS`, accepted by the maintainer closure at https://github.com/Zutfen-LLC/inferswarm/issues/255#issuecomment-5974171991. Its bounded authority is homogeneous NVIDIA/CUDA, `inferswarm01` RTX 3060 + `inferswarm04` RTX 3090, exact Qwen3.8-Flash-Next-UD-IQ1_S three-part release, llama.cpp `b29c606e28a01b1bc8c1351026a0fa6e616bf6c4`, fixed/manual whole-layer placement, participant-local verified backing, ordinary text generation and repeatability. It does not establish numerical equivalence, mixed-vendor or production readiness, dynamic scheduling, performance superiority, or R8-J/Vulkan authority.

## Current gap and proposed entrypoint

At the accepted #267 merge base there is no ordinary InferSwarm CLI/runtime package; repository scripts are evidence tooling. The proposed entrypoint is `python -m inferswarm.operator run --config <path>`; this is a design proposal, not an existing command. Operators should not invoke `tools/issue255_mvp/*.py` as the product entrypoint.

Configuration/plan concepts remain model-independent and internal/experimental: opaque model/source identity; client/local and remote participant Node/Compute Unit identities; per-participant backing/source paths; explicit fixed immutable placement; generation/request settings. Proposed seams are config validation → immutable operator-authorized plan → participant source/backing identity verification → bounded runtime adapter for connect/startup/readiness/generation/owned-process cleanup → response and structured plan/source/observed-placement receipt. Do not freeze broad public APIs.

## Mapping from #255

| #255 mechanic | Ordinary product responsibility | Retain as measurement-only evidence |
|---|---|---|
| Select source, participants, manual whole-layer split, backing roots, request settings | Operator config and explicit fixed-plan validation | Exact tested host/model/runtime facts remain attributed to #255 |
| Start/connect client and RPC participant, readiness, request, completion | Bounded adapter and ordinary request surface; own/clean only processes created by that invocation | Benchmark harness request instrumentation is not runtime startup |
| Select and verify participant-local backing | Bind source to each participant and fail closed on missing/wrong identity; report source provenance | `prestage.py` GGUF tensor indexing/cache-key logic is not product behavior unless separately justified |
| Attribute execution and lifecycle | Return selected/observed placement and bounded ownership outcome | GPU sampling, TCP/strace attribution, benchmark/repeatability matrix and evidence reduction remain acceptance ceremony |

Keep distinctions explicit: **source** identifies authorized immutable content; **cache/backing** is where verified bytes can be read; **staging** is movement into a target; **residency** is loaded state; **execution** is where computation occurs. One does not prove another.

Generic planner/fabric logic receives opaque identities and the operator-authorized plan; it must not branch on Qwen/model names, GPU vendor/model, hostname, or issue number. Runtime-native flags, GGUF/cache details belong behind the bounded backend adapter. Do not import or invoke the #255 experiment harness from product code, and do not transplant its measurement ceremony.

## Task 2 internal JSON schema and exported API

`inferswarm.operator.config` exports frozen `ModelIdentity`, `CacheRange`, `Participant`, `Placement`, `BackendOptions`, and `OperatorConfig`, plus `parse_config(mapping)`, `parse_config_json(text)`, and `load_config(path)`. Schema `operator-config/2` has exact top-level fields `schema`, `plan_id`, `model`, `participants`, `strategy_id`, `placement`, `backend_options`, `request`. Model members require basename `name`, lowercase SHA-256 and `size_bytes`. Participants have explicit `role` (`client` or `remote`), `node_id`, `compute_id`, `transport`, separate `execution_address` and nullable `rpc_endpoint`, `device`, absolute `source_path`, `runtime_executable`, expected `runtime_sha256`, absolute `cache_path`, bounded `port`, absolute `lifecycle_dir`, source identity triplet, and nonempty `cache_ranges`. Each cache range binds member, byte `offset`/`length`, SHA-256, runtime `cache_key`, source identity and opaque `unit_id`; ranges are bounds-checked against required member sizes. Exactly one client/local and one remote/RPC participant are required; input array order does not define roles.

Placement entries explicitly bind opaque `unit_id` and `state_ids` to a `compute_id`, inclusive `first_layer`/`last_layer`, and boolean `output`. `backend_options` is strategy-owned typed data: `hidden_layers`, `offload_tail`, `cpu_experts`, two-element `tensor_split`, `context`, `slots`, `startup_timeout_seconds`, `split_mode`, `verbosity`. Request keys are `prompt`, `max_tokens`, finite `temperature`, and `seed` (the accepted default example is seed 42; context 1024 and one slot are in backend options). Strict unique JSON keys, exact schemas, absolute paths, member basenames, unique IDs/ports/cache keys, integer-not-bool bounds and finite numbers are enforced. Config descriptors and expected hashes do **not** establish file presence or verified bytes.

`inferswarm.operator.plan` exports frozen `OperatorPlan` and `build_plan(config)`; digest is SHA-256 over canonical normalized plan JSON and participant order is semantically irrelevant. `inferswarm.operator.strategy` exports frozen `ExpectedPlacement`, `LaunchSpec`, and `llama_cpp_spec(plan)`. The pure adapter accepts typed options only, rejects range gaps/overlaps/duplicate or misplaced output and unbound assigned cache ranges, and deterministically emits the allowlisted llama.cpp argument vector. Native args cannot be supplied in config. For the accepted adapter descriptor, hidden state IDs 0–47 are CPU 0–40, local 41–44, remote 45–47, with output stage 48 assigned remote; `-ngl 8`, CPU expert setting, device/endpoint and tensor split are explicit operator config. Tensor-split weights are not interpreted as equal layer counts. Pure validation describes expected placement only; Task 3 must verify bytes actually consumed by runtime `LLAMA_CACHE` and observe startup's realized placement.

## Phases and limits

1. Task 1 reconciled accepted #255 living status and supplied this mapping.
2. Task 2 provides pure config/plan/adapter seams and focused CPU tests only.
3. Task 3 owns CLI/lifecycle, actual source/cache byte verification and runtime observation. No physical, network, subprocess or model execution is permitted in Task 2.
4. Local and hosted CI must pass before physical Stage 4; only then can bounded physical acceptance be considered under Issue #268 authority.
5. Final CPU Validation remains after explicit maintainer GO. Living status is informational and grants no execution permission.

#268 is not accepted here. Its eventual acceptance requires ordinary-path implementation, focused tests, hosted CI, and bounded authorized physical criteria (three fresh requests, both GPUs materially participating, verified remote local backing, and bounded process ownership). No equivalence, mixed-vendor, production, dynamic-scheduling, performance-superiority, or Vulkan/R8-J claim is made.

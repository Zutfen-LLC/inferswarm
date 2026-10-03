# Issue #268 — ordinary operator path (design mapping)

**Status:** design/mapping only; implementation, physical Stage 4 acceptance, and Final CPU Validation remain pending. The accepted predecessor is Issue #255 `MVP_DISTRIBUTED_INFERENCE_PASS`, accepted by the maintainer closure at https://github.com/Zutfen-LLC/inferswarm/issues/255#issuecomment-5974171991. Its bounded authority is homogeneous NVIDIA/CUDA, `inferswarm01` RTX 3060 + `inferswarm04` RTX 3090, exact Qwen3.8-Flash-Next-UD-IQ1_S three-part release, llama.cpp `b29c606e28a01b1bc8c1351026a0fa6e616bf6c4`, fixed/manual whole-layer placement, participant-local verified backing, ordinary text generation and repeatability. It does not establish numerical equivalence, mixed-vendor or production readiness, dynamic scheduling, performance superiority, or R8-J/Vulkan authority.

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

## Phases and limits

1. This task reconciles accepted #255 living status and supplies the architecture mapping.
2. Follow-up implementation tasks establish the narrow config/plan/adapter and focused CPU tests.
3. Local and hosted CI must pass before physical Stage 4; only then can bounded physical acceptance be considered under Issue #268 authority.
4. Final CPU Validation remains after explicit maintainer GO. Living status is informational and grants no execution permission.

#268 is not accepted here. Its eventual acceptance requires the issue's ordinary-path implementation, focused tests, hosted CI, and bounded authorized physical criteria (three fresh requests, both GPUs materially participating, verified remote local backing, and bounded process ownership). No equivalence, mixed-vendor, production, dynamic-scheduling, performance-superiority, or Vulkan/R8-J claim is made.
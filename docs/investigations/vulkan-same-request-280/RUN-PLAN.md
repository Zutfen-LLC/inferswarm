# Issue #280 prospective run plan — PHYSICAL HOLD

Current implementation disposition: NO-GO; see [specific observation gaps](README.md).
The requirements below are prospective and NOT implemented/qualified in full.
No physical run is ready or authorized.

Only one bounded observer/harness implementation and CPU recording validation
are approved by the current user instruction. This plan is prospective, not a
GPU dispatch, model-acquisition permission, acceptance record or tuning permit.
Maintainer exact-head review is required before physical execution or scope
expansion. No tuning until PASS. #239 remains blocked; no holdouts are involved.

## Subject and source

Proposed host: inferswarm05, HP Z440, machine-id
39ac8e342ef845c2a0a90c7c7a407243. Retained dies: 0000:07:00.0 and
0000:0b:00.0, V340L / Vega10, 8,573,157,376 B separate HBM each. These
are historical bindings, not fresh enumeration by this implementation.
They share the PM8533 / root 0000:00:03.0 host uplink; there is no coherent
16-GiB address space or claimed direct peer path. Existing layer-split Vulkan
transport stages cross-device copies through host-visible staging.

Use only llama.cpp b29c606e28a01b1bc8c1351026a0fa6e616bf6c4 plus the
reviewed additive observer transform. Preserve computations, scheduler and
transfer/synchronization semantics. Freeze base commit, source blobs, observer
patch SHA256 and full transformed Git tree, compiler/CMake identities, command
and flags, executable and every resolved runtime/driver library digest before
any approved run. A CPU build/replay is not a Vulkan build or physical proof.
The accepted #243 binary is not this observer build and must not be relabeled.

## Exact proposed artifact and staging source

Qwen/Qwen2.5-3B-Instruct base model; bartowski/Qwen2.5-3B-Instruct-GGUF,
revision f302c64a2269a69fb27b2f9473b362f5bb8e78d8, member
Qwen2.5-3B-Instruct-Q4_K_M.gguf, Q4_K_M, 1,929,903,264 B,
SHA256 9c9f56a391a3abbd5b89d0245bf6106081bcc3173119d4229235dd9d23253f94.
Metadata-only upstream lookup is retained in model-source.json: upstream LFS
size/hash exactly match the retained #163/#210 artifact. No member bytes were
fetched or read. Proposed immutable source is the Hugging Face resolve path
for that exact repository/revision/member; proposed destination on inferswarm05
is /srv/models/issue280/Qwen2.5-3B-Instruct-Q4_K_M.gguf. Neither destination
existence nor available artifact on that host is established. Acquisition,
license/applicability acceptance, byte hash validation and staging require
separate approval. No model was downloaded or staged by this work.

Retained metadata: 36 blocks, embedding 2048, 16 attention heads / 2 KV heads.
The small model fits one die and tests mechanism, not extra-card capacity or
purchase economics. Full repeating/output-layer offload, with CPU input
embedding/tokenizer/sampler, mmap backing, output and staging explicitly
accounted. Equal cumulative split proposes blocks 0–18 on A and 19–35 plus
output on B; actual named tensor allocation bytes must establish the mapping,
not equal-size assumptions. Layer KV follows placement.

## Fixed workload, matrix and budget

A: die A only, split none. B: ordered A,B, layer split 1,1. Same observer
build/model and settings: context 4096, batch 512, microbatch 128, F16 K/V,
flash attention OFF, one slot, 14 CPU threads, no speculative/RPC execution,
fit OFF, automatic warmup OFF, all repeating/output layers offloaded. Reject
silent reduction or extra CPU/backend substitution. Restrict to Radeon ICD
and Vulkan-only build; do not enumerate or invoke it before separate approval.

Raw completion prompts, no implicit chat template:

P1 = "Extract the incident fields as JSON only. Incident: service=payments; severity=high; status=resolved. Required keys: service, severity, status."

P2 = "Reference notes:\n" + 100 exact repetitions of
"Routine maintenance completed without customer impact.\n" +
"Incident: service=search; severity=low; status=open.\nExtract only the incident fields as JSON. Required keys: service, severity, status."

Max output 128 tokens, normal EOS allowed; temperature 0, top_k 1, seed 42,
repetition penalty 1, explicit greedy sampler, cache_prompt false. Freeze
request JSON and UTF-8 prompt hashes before any approved acquisition/run.
Freeze actual token IDs/counts offline with the approved artifact tokenizer
later; 4096 is capacity, not a claimed prompt token count. No context overflow,
truncation, implicit prompt/chat-template changes or prefix/KV reuse.

For EACH prompt: repetition 1 A,B; repetition 2 B,A. Each of eight fresh
process launches sends one process-cold request and one warm request with no
prefix reuse. Sixteen requests total. Process-cold is not disk/page-cache-cold;
no cache dropping. No added calibration, retries, transfer ladders or tuning.
Proposed 60 s/startup and 30 s/request; hard prospective aggregate physical
cap 20 min, $0 incremental cash budget (electricity unmeasured). All startup,
health/preflight and shutdown time in the physical phase consumes that cap.
Abort consumes its launch/request allocation; unsent requests are recorded
NOT_ATTEMPTED, never replaced. A stopped campaign cannot be 16/16 PASS.

## Observation and accounting definitions

An append-only raw stream must correlate launch/process, request and graph ID,
phase (prefill/decode), actual graph token count/positions, named layer/tensor,
shape/type/strides/range and backend device BDF. Every graph in B must show
both dies owning declared state and actual nonempty COMPUTE dispatch submitted
and completed through existing synchronization. Transfer-only submits, queued
commands, utilization, residency deltas or overlapping processes are not proof.
Require causal submit/completion pairing; reject missing/duplicate/cross-request
records, empty submits, wrong BDF, unexplained CPU fallback or lost attribution.

At each scheduler copy boundary record source/destination tensor and BDF,
actual logical payload bytes, actual staged source-device-to-host and
host-to-destination legs, begin/end timestamps on one monotonic clock and
existing wait completion. Device staging may be host-visible mapped memory;
record implementation mechanism, not an invented extra memcpy or direct P2P.
Measure outer synchronized copy elapsed including existing waits. Leg/wait
intervals are diagnostic children and MUST NOT be added again to outer elapsed.
For overlapping intervals use interval unions; never sum nested timers or add
copy time to request wall to create another wall metric. No new synchronization
is permitted solely to make observations convenient. If the current waits cannot
establish completion/elapsed correlation, stop and name the missing seam.

Expected bytes are graph/shape-specific: derive each expected scheduler-copy
range from the graph before its execution (ggml actual logical range/type,
not allocated capacity or a blanket weight-size estimate). Sum exactly one
logical payload per copy; separately reconcile per-leg bytes, counting each
staging leg once, never labeling the leg sum PCIe wire traffic. For an F32
2048-wide activation, 8192 bytes per graph token is an illustrative calculation,
NOT the complete model transfer budget; logits, CPU inputs/outputs, KV and
other scheduler copies must be separately enumerated where they cross devices.
Graph manifests and copy events must agree, including multiplicity and ranges.

Prefill may have multiple microbatch graphs (128 maximum tokens each). The
prefill logits emit the first output; later decode graphs consume prior emitted
tokens. Reconcile graph tokens and transfers to the actual returned token IDs,
EOS/stop status, prompt microbatch count and actual output length, not 128 or
an assumption that N output tokens always imply N decode graphs. Record EOS
sampling and terminal graphs explicitly; extra final decode/stop behavior must
match the pinned server path. Aborted requests retain all completed and pending
submissions/copies, actual partial output length and unfinished intervals;
incomplete intervals are UNKNOWN, not zero elapsed or successful completion.
No complete-request performance or correctness denominator silently drops aborts.

Startup: process spawn to ready. TTFT: accepted request to first output token,
including prefill/waits; request wall: accepted request to terminal response.
Decode: observed intervals/output count after first token, with zero/one-token
cases reported N/A; retain raw token timestamps and actual token count.
Report instrumentation overhead as unquantified unless separately approved and
measured; both arms use identical hooks. These are instrumented timings, not
uninstrumented production performance.

Memory separates named weights, layer KV/mutable state, compute buffers,
optional backing/cache, staging peak and unexplained duplication. Per-BDF
residency supports but cannot replace tensor ownership; process peak RSS and
system MemAvailable/swap are separate metrics. Health windows cover startup
through owned shutdown, not merely requests.

## Correctness, proposals and stop rules

Exact artifact/source/library/request identity, shape/placement and attribution
integrity are mandatory prospective checks. Task-quality proposal: all sixteen
responses parse as JSON only, exactly service/severity/status, exact P1
payments/high/resolved and P2 search/low/open, no extra keys/prose. Baseline
failure stops the workload, not permission to tune or excuse B. Token sequence
equality is diagnostic; no universal bitwise floating-point or NVIDIA reference
requirement. If numerical qualification is required, freeze a separately
approved criterion before execution; do not infer tolerance from results.

The following remain PROPOSALS requiring next maintainer review, not approved
acceptance limits: >=25% of GPU-resident named model bytes on each B die;
>=1,073,741,824 B reserve per die; per-prompt median warm TTFT/request wall
<=1.25x A and decode >=0.80x A; peak RSS <=8 GiB; MemAvailable >=100 GiB;
no incremental system/process swap; synchronized boundary-copy interval union
<=20% request wall; edge stop >=65 C or junction >=75 C. Two repeats do not
support tail/statistical/scaling claims. Existing <=55 C observation was a
bounded historical workload with temporary 140-mm fan, not full-TDP approval.

Prerequisites before ANY later GPU run: separate exact-head maintainer physical
authorization; artifact acquisition/staging approval; fresh operator cooling /
airflow confirmation; approved temperature AND health-stop policy (including
sensor loss); approved proposed thresholds and matrix; fresh subject/runtime/
BDF binding and library identity under that later authorization. A fan sensor
reading zero is not fresh external-fan confirmation. This CPU work does not
satisfy any physical prerequisite.

Stop immediately on any integrity/task failure, unresolved attribution or
copy accounting, OOM, reset, new AER/GPU fault, thermal instability, lost
telemetry, unexpected fallback/reduction, unexpected activity or cap exhaustion.
Retain raw evidence and partial output, mark STOP/UNKNOWN, perform only owned
safe shutdown under the later approved policy. No reset/reboot, recovery tuning,
selective rerun, new host configuration, purchases, multi-card/multi-host,
mixed-vendor, #239 activation, holdout or automatic successor.

## Review and mandatory validation order

Focused CPU recording fixtures and negative controls run early through the real
collector/parser path. A bounded independent advisory review audits observation
semantics and nonclaims. Push an additive DRAFT PR; stop for maintainer exact-head
review. Ordinary exact-head CI is required. Per AGENTS.md and Issues #213/#224/
#226, the mandatory single hosted Final CPU Validation run is REQUIRED/DEFERRED
until maintainer GO on that exact head (unless explicitly declared review-critical).
It is not omitted, self-authorized or replaced by advisory review/focused tests.
Any accepted source correction changes the head and requires fresh exact-head
review/validation. CI green never authorizes physical execution. Final physical
disposition, after a separately approved run, is continue/redesign/stop only
against frozen criteria; no tuning until PASS or automatic scope expansion.

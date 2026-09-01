# R2 correctness-reference methodology — v2

```text
Status: FROZEN BEFORE CORRECTED RETAINED R2 CANDIDATE EVALUATION
Canonical issue: Zutfen-LLC/inferswarm#51
Historical candidate: Zutfen-LLC/FreeToken#17 at 99e3f291ba9603e18a18a7011cdba17dd310ef90
Frozen R2 plan: sha256:6128dd6705d6d692df3d5fc11cc130dba5c010cfff40c0e4c5ec7c19e1b78ff0
Diagnostic implementation: Zutfen-LLC/FreeToken branch poc/r2-local-split-execution
```

This document corrects only the numerical comparator for R2. It changes no R2
candidate plan, split, transport, correctness threshold, workload, logit checkpoint,
performance baseline, or performance measurement. It is frozen before any corrected
retained R2 candidate result is observed under this method.

## Historical result is preserved

The retained FreeToken result at commit
`99e3f291ba9603e18a18a7011cdba17dd310ef90` remains:

`R2_LOCAL_SPLIT_EXECUTION_BLOCKED_CORRECTNESS`

Under the original comparator, W1, W3, and W4 exceeded the unchanged
`rtol=2e-3, atol=2e-3` selected-logit threshold, W2 was byte-exact, maximum
absolute deviation was `1.25`, and NaN/Inf counts were `0/0`. Exact W1-W4
32-token sequences, session isolation, producer/consumer boundary hashes, two
captured block-local decode graphs, zero recaptures, zero host expert fetches,
zero resident-source accesses, zero fallbacks, zero steady-state model-state
movement, zero unexplained persistent host expert mirrors, and clean plan
reconciliation remain historical evidence. They are not rewritten or relabeled.

The measured `PERFORMANCE_NEGATIVE` result also remains historical evidence for
that blocked candidate. It is provisional for roadmap conclusions until numerical
correctness is resolved. This methodology does not change or rerun the performance
baseline.

## Defect in the original comparator

The original R2 harness compared against external artifact
`inferswarm.n1.unsplit-reference/1`, SHA-256
`cc5d7b64323fa2864f3add1193f72f35387780ea9abc8c9f85acc42695864952`.
It identifies the model, revision, workload manifest, prompt token IDs, generation
protocol, and producer FreeToken commit `4c60ff522a95cf147456a4333271ee05b505fc58`.
It does not retain the resolved runtime configuration, prefill chunk size, runtime
capacity, session/reset protocol, graph policy, attention/cache geometry, or
workload state history.

Those omissions are material. The frozen R2 candidate manually prefilled in
64-token chunks with fresh zeroed block-local KV and recurrent state for every
workload. The legacy reference lineage used a much larger default manual prefill
chunk, but the artifact does not self-describe that fact. The comparator therefore
did not prove that it removed only the R2 multi-resource treatment.

This is the same durable lesson established by
`phase1-correctness-reference-methodology-correction-v2.md`: deterministic
serving/cache state can produce logit differences that resemble a distributed
execution failure. A correctness reference must preserve every stateful numerical
property that can affect output while removing the experimental treatment.

## Diagnostic evidence motivating v2

All listed files are labeled `NONCANONICAL_DIAGNOSTIC_EVIDENCE`; none is a corrected
retained R2 candidate evaluation.

| Evidence | SHA-256 | Result |
| --- | --- | --- |
| `chunk-controls.json` | `c5254e57ffb79f1627a629b994474404ac75a011c1b89b9d960224147141a9e5` | reciprocal W2/W4 chunk controls |
| `matched-local-control.json` | `2434b6bd4279969a1bb49dcfc84fcfdcaf4e8554e328fe5a53b2bfc9245911a4` | split and one-GPU local W4 chunk64 are byte-identical |
| `first-divergence.json` | `09b81c3e8c8f9cab338a84016e2f813d5dfff2fffb5d52fb64e14bc81c7e6cab` | first geometry-dependent state is layer-0 recurrent state |

The reciprocal controls show:

- W2 prompt 54, chunk 64, one chunk: every selected logit is byte-exact;
- W2 prompt 54, chunk 32, two chunks: exact 32-token sequence, but every selected
  logit differs; max abs `1.15234375`, NaN/Inf `0/0`;
- W4 prompt 121, chunk 64, two chunks: exact 32-token sequence, but selected logits
  differ; max abs `0.75390625`, NaN/Inf `0/0`;
- W4 prompt 121, chunk 128, one chunk: step-0 and step-1 logits become byte-exact to
  the legacy reference. Later decode diverges, demonstrating that the legacy
  artifact also leaves graph/state protocol unmatched.

The matched local control uses one RTX 3060, a complete ordinary FreeToken model,
FI attention, NVFP4 Triton, page size 1, runtime capacity 17,152, concurrency 1,
64-token manual prefill, zeroed per-workload KV/recurrent state, and one full-model
bs=1 decode graph. Ordinary expert offload is the sole capacity-driven execution
difference. It removes the second Compute Unit, process split, activation transport,
and R2 execution edge.

For W4 chunk64, matched local and R2 split execution have:

- the same complete 32-token sequence;
- byte-identical selected logits at steps 0, 1, 15, and 31;
- byte-identical layer-18 hidden/residual at both prefill chunks;
- byte-identical logical KV and recurrent/linear state for every owned layer after
  each chunk;
- byte-identical Block B output, final norm, and logits after each chunk;
- byte-identical Block A producer and Block B consumer boundary bytes.

There is no split-specific divergent checkpoint, layer, or mutable state in the
captured W4 path. Comparing the matched local computation at chunk64 and chunk128
instead finds the first retained state difference at global decoder layer 0:
convolution state remains exact, while GatedDeltaNet recurrent state differs. The
recurrent-state max absolute/relative deviations are `0.043923377990722656` and
`18153.4453125`, with NaN/Inf `0/0`. The first KV difference appears at global
layer 3. This precedes the layer-19 boundary.

Classification: `REFERENCE_GEOMETRY_MISMATCH`.

## Mechanical v2 reference rule

The R2 correctness reference is:

> the frozen R2 candidate's numerical execution geometry with the multi-resource
> split treatment removed, while preserving stateful properties that can affect
> numerical output.

This rule is mechanical and is not selected from closeness to a candidate result.

### Frozen identity and workload

```text
model repository:       nvidia/Qwen3.6-35B-A3B-NVFP4
model revision:         491c2f1ea524c639598bf8fa787a93fed5a6fbce
FreeToken lineage:      R2 branch from accepted base 6a242a34083c3080aa6d8f92625a6be4a0d124db
reference Compute Unit: frozen-plan gpu-a (exec.block-a / boundary producer)
reference GPU UUID:     GPU-1fc28f83-1d45-926e-54d0-ba1e835ef099
reference GPU model:    NVIDIA GeForce RTX 3060 12 GiB
workload manifest SHA:  10f81e5418a71a68f387632de422c3337cc7ba0518111a8746ad856d0210b24a
workload order:         W1 -> W2 -> W3 -> W4
selected logit steps:   0, 1, 15, 31
```

The Compute Unit selection is mechanically derived from the frozen candidate plan:
remove the consumer/second Compute Unit and retain the Compute Unit assigned to the
boundary-producer execution, `exec.block-a`. For this plan that is `gpu-a`, stable
device UUID `GPU-1fc28f83-1d45-926e-54d0-ba1e835ef099`. If that exact Compute Unit
is unavailable, reference capture stops; it is not substituted after observing any
numerical result. The third-GPU matched-local run on
`GPU-e1f2f90c-49ab-2689-0cf1-e5d9da520176` remains noncanonical diagnostic evidence
and is not the v2 canonical reference source.

The reference records exact prompt token IDs for every workload and fails before
capture if tokenization differs. Generation is greedy with temperature `0.0`,
top-p `1.0`, top-k `-1`, `ignore_eos=true`, and exactly 32 generated tokens.

### Preserved numerical geometry

The reference must resolve and retain:

```text
attention backend:             FI
expert format/backend:         NVFP4 / Triton
MoE execution:                 ordinary one-GPU offload as required by 12 GiB capacity
MoE cache slots:               3,774
prefill overlap:               false
runtime capacity:              17,152 tokens
prefill chunk:                 64 tokens
KV page size:                  1
logical page table:            identity mapping for the fresh session
concurrency:                    1
linear/recurrent state slots:  one live diagnostic session slot
decode graph policy:           exactly one full-model bs=1 graph, no recapture
cross-workload prefix reuse:   none
```

Each workload starts with directly zeroed KV and linear/recurrent state, matching
R2's block-local reset. It does not inherit radix-prefix pages or warmed mutable
state from an earlier workload. Workloads are captured in W1-W4 order for identity
and auditability, but each workload's numerical model state is independent.

The reference must record resolved values, not merely requested flags. A mismatch
between requested and resolved attention backend, NVFP4 backend, MoE cache size
`3,774`, prefill overlap `false`, capacity, chunk, page size, graph policy, or
state-reset protocol stops capture.

### Removed treatment

The reference must not contain:

- the second Compute Unit;
- the two-process block split;
- GPU-A to pinned RAM to GPU-B activation transport;
- the R2 layer-19 execution edge.

The strategy-defined seam after global layer 18 remains observable for diagnostics,
but both sides of the seam execute in the same full-model process.

### Unavoidable capacity difference

The complete model cannot remain resident on one 12 GiB RTX 3060, so the one-GPU
reference uses ordinary expert offload. That is a capacity mechanism, not the R2
treatment. FreeToken #48 and accepted R1 evidence establish that the native expert
representation is preserved across resident and offload materialization. The v2
reference freezes `moe_cache_slots=3774` and `prefill_overlap=false`, matching the
geometry used by the byte-identical diagnostic control. The capture must record those
resolved values, expert source representation, and any expert movement. It fails
closed rather than resizing the cache or enabling overlap.

## Reference artifact provenance gate

Every reference artifact must retain at minimum:

```json
{
  "reference": {
    "artifact_sha256": "...",
    "schema": "...",
    "model": "nvidia/Qwen3.6-35B-A3B-NVFP4",
    "revision": "491c2f1ea524c639598bf8fa787a93fed5a6fbce",
    "producer_commit": "...",
    "runtime_configuration": {
      "attention_backend": "fi",
      "nvfp4_backend": "triton",
      "moe_backend": "offload",
      "moe_cache_slots": 3774,
      "prefill_overlap": false,
      "page_size": 1,
      "concurrency": 1
    },
    "prefill_chunk_tokens": 64,
    "runtime_capacity_tokens": 17152,
    "session_state_protocol": "fresh-zeroed-state-per-workload",
    "graph_policy": "one-full-model-bs1-decode-capture",
    "selected_steps": [0, 1, 15, 31],
    "workload_order": ["W1", "W2", "W3", "W4"]
  }
}
```

The comparator independently hashes the reference bytes. It fails closed on missing
metadata or disagreement in model, revision, workload set/order, exact prompt IDs,
generation length, or selected steps. A legacy reference with incomplete provenance
may be used only by an explicit `NONCANONICAL_DIAGNOSTIC_OVERRIDE` that cannot write
`correctness.json` or `result.json`.

## Reference self-consistency gate

Before a v2 reference can become canonical, capture two independent fresh reference
processes under the identical frozen configuration and protocol. Record for each:

- complete generated token sequences;
- selected full logits and their float32 hashes;
- complete artifact SHA-256;
- resolved configuration and configuration hash;
- layer-18 seam hashes for W2 and W4;
- NaN and Inf counts.

The two captures must have exact token sequences and pass the unchanged full-logit
threshold at every selected checkpoint. Byte-identical artifacts are preferred.
Selection is predeclared: if and only if the pair passes this self-consistency gate,
session A is the canonical v2 reference and session B is its corroborating capture.
Session B can never replace session A based on closeness to the R2 candidate. If the
pair is not self-consistent, neither artifact is selected and candidate evaluation
does not begin.

## Unchanged candidate gate

The corrected R2 comparison retains exactly:

```text
generated tokens: exact, all 32 tokens, W1-W4
selected steps:   0, 1, 15, 31
full logits:      rtol = 0.002, atol = 0.002
NaN/Inf:          zero
```

No tolerance widening, checkpoint removal, workload removal, averaging, or
token-only substitution is allowed. Session isolation, boundary checksum, native
graph execution, ownership, residency, movement, and reconciliation gates remain
unchanged.

## Experiment firewall

At the time this document is committed and opened for review:

- the original R2 evidence files and frozen plan are unchanged;
- `R2_LOCAL_SPLIT_EXECUTION_BLOCKED_CORRECTNESS` remains the only retained verdict;
- no corrected canonical v2 reference has been selected;
- no corrected retained R2 candidate evaluation has been run or observed;
- no R2 performance rerun, placement tuning, split change, or transport change has
  occurred;
- the pinned-host allocator reclamation question remains out of scope.

After this methodology is reviewed and merged, a later change may capture the two
fresh self-consistent references and only then evaluate the retained R2 candidate.
Until that sequence completes, R2 must not be declared pass.

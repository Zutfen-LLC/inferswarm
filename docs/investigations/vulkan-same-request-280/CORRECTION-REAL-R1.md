# Real R1 producer/collector/model correction — Issue #280

Scope: one bounded repository correction after the corrected physical verification
terminated STOP at R1-cold. It changes no physical result and grants no execution
authority. The predecessor correction remains #284 / merged PR #285; no new
prerequisite issue is introduced.

## Retained observation, not new execution

Accepted starting main: `832a9f4adcba2bebfa66f0ed5f1e004cba7fb16d`.
The physical verification consumed exactly one launch and one request. Its
semantic check passed; observer admission failed. R1-warm, R2-cold and R2-warm
were not_attempted. The retained terminal remains STOP, irrespective of any
later offline replay result.

The complete R1 observer bytes are the compatibility authority, not a synthetic
replacement. Original raw size: 13,264,272 bytes. SHA256:
`b1fa13966a715d2009efdde4fa602a5a6f0b70d93c3884ceef0d14426bfcc796`.
The full lossless compressed fixture under `compatibility/` preserves every
original byte and row order; no row reconstruction is permitted. Matching
server log SHA256:
`2dc0d51bb11113536b6993123510bf2ddfc088bd58db97ad91a3806d66cb82ff`.

Pre-edit reproduction with the merged collector and PHYSICAL_280 baseline:
`ok=false`, problems `["graph sequence/request mismatch"]`. The real-capture
compatibility test was added and observed RED before production edits.

## Source-derived correction boundaries

D1: llama.cpp's `ubatch.n_seqs` counts sequence-set layout slots, not unique
logical sequence IDs. `n_seqs_unq` and the complete `seq_id_unq` set establish
unique identity. Token membership in the server's slot-filtered arrays alone
does not prove exclusive membership. An old-capture compatibility witness must
therefore be narrowly authenticated; unrelated old-shaped streams cannot gain
admission by reusing a positive layout count or the first unique ID. Direct
sequence evidence must reject multiple/wrong IDs and explicit request mismatch.

The old server log does not literally print `n_seq_max=1`. It prints
`n_slots=1, kv_unified=false`; the pinned server/common/context initialization
path yields a single allowed logical sequence. This is a corroborated,
source-derived legacy inference, not a newly observed graph field.

D2: pinned CPU/Vulkan host buffer names are explicit literals, not prefixes.
`CPU_Mapped` is backed by the CPU host-buffer callback. CPU/host weights belong
in host accounting and never in a GPU placement numerator. Null-buffer
`unassigned` is unknown ownership, not a CPU alias. Unsupported lookalikes and
unresolved accelerator names must fail closed.

D3: pinned Qwen2 loads an optional distinct output weight; if absent, it creates
a duplicated output-role tensor from `token_embd.weight`. The name remains the
embedding name. The physical capture has both a CPU_Mapped input allocation and
a Vulkan output allocation with this name. Logical tied identity, storage
ownership and execution location are separate. `output_norm.weight` is not the
output projection. The logical output role must be proven by its real
`result_output` / `MUL_MAT` operand and completed compute on the frozen output
die, with matching admissible named allocation bytes. Inventory backend-buffer
pointers and runtime Vulkan device-buffer pointers are different identity
spaces and cannot be equated without an emitted mapping.

Implementation and executable compatibility results are retained in the
additive `compatibility/` bundle. Original instrumentation and predecessor
identities remain historical, byte-preserved inputs; any corrected overlay
has a distinct identity and cannot be relabeled as the physical binary used
for the STOP capture.

## Permanent regression and authority

A physical campaign may not be authorized solely because synthetic observer
fixtures pass. The exact producer/model evidence shape requires offline
compatibility proof against the collector first. For #280, the retained real
R1 capture is the required compatibility authority. Fixture-integrity failure,
missing evidence or collector rejection blocks the prelaunch compatibility
gate; a gate PASS remains a prerequisite, never physical authorization.

Frozen BDFs, block split, per-die KV, completed compute, copy manifests,
shape/stride bytes, occurrence multiplicity, cross-die endpoints, staging leg
reconciliation, task semantics, synchronous STOP, 2-launch/4-request maximum,
aborted-slot consumption, no automatic rerun and peak-RSS fail-closed admission
remain binding. This correction does not reinterpret historical STOP as
CONTINUE or infer any hardware performance result.

The user explicitly requires ordinary exact-head hosted CI before the
maintainer re-review handoff. The separate hosted Final CPU Validation remains
subject to the repository's post-maintainer-GO ordering; ordinary selected CI
is not represented as its substitute.

No physical/GPU/model/device execution, hardware modification, #281 execution,
#239/R8-J, sealed holdout, mixed-vendor, purchase or successor work is within
this correction. Any new physical verification requires fresh maintainer
exact-head review and explicit bounded authorization. Do not rerun automatically.

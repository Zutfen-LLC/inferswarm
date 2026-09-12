# V0-B results: matched-evidence reduction and integration-seam selection

All numbers are MEASURED in the accepted V0-A campaign (issue #141, PR
#145 merge `273b9e8e32c779f063903cd75a0c6772d0d1e451`) or CALCULATED
from those retained values by the mechanical reducers in this bundle
(`scripts/v0b_*.py`, hashes in `MANIFEST.sha256`). The one new physical
collection — the supplemental matched CPU baseline — was produced under
`METHODOLOGY.md` as corrected by `METHODOLOGY-CORRECTION-1.md`,
`METHODOLOGY-CORRECTION-2.md`, and (in the maintainer-review correction
round) `METHODOLOGY-CORRECTION-3.md`, on `inferswarm02` (the V0-A host)
on 2026-09-12. Machine-readable authority: `TERMINAL.json`.

## Phase 0 — comparability audit (mechanical)

`results/comparability-matrix.json`, derived by
`scripts/v0b_comparability_audit.py`:

- parent identity pinned: #141 terminal
  `V0A_MATCHED_CHARACTERIZATION_COMPLETE`; PR #145 merge
  `273b9e8e`; V0-A head `2b2d546d`; superseded `2b14fba`
  interpretations NOT consumed.
- evidence integrity: all 88 parent-manifest rows re-hashed and
  verified byte-exact; all 6 corrected correctness runs prove their
  intended physical device (BDF) in their own retained stderr; all 18
  retained bench rows pin the intended device selector with identical
  model/workload parameters.
- classification: NV-A Vulkan/CUDA pairs (prefill, decode, startup,
  VRAM, host RSS, correctness) are MATCHED_WITH_DECLARED_DIFFERENCE
  (same physical GPU/model/workload/link; backend codegen differs by
  construction). AMD Vulkan/native is NOT_COMPARABLE (native
  unavailable, mechanically demonstrated). AMD-vs-NVIDIA throughput is
  DESCRIPTIVE_ONLY. Superseded evidence is quarantined in the matrix.

## Phase 1 — correctness/stability (AMD + NVIDIA)

`results/correctness-stability.json`, derived by
`scripts/v0b_correctness_stability.py`:

- Integrity: PASS for every corrected run — executable/model SHA-256
  match the frozen identities, intended device proven per run (BDF
  line), 37/37 layers offloaded, clean exits, no fallback or corruption
  markers. Integrity is recorded separately from repeatability and
  never upgrades an under-observed pair.
- Backend-local repeatability (corrected taxonomy — repeatability is an
  observation-count-gated property; one run cannot demonstrate it):
  `stable` — AMD-A only (3/3 identical visible greedy generation).
  AMD-B, NV-A/VK, and NV-A/CUDA are each a single clean observation and
  are classified `insufficiently_observed` — NOT stable, regardless of
  their (identical) outputs.
- Cross-backend: a real generated-output difference — NV-A CUDA differs
  from all Vulkan arms at one word choice. Classified honestly as a
  generated-output difference; NOT relabeled as semantic equality, and
  no logits-level equivalence is claimed.
- ADR 0010 mapping: exact-integrity layer satisfied in evidence;
  qualified-numerical and strategy-semantic layers NOT ESTABLISHED —
  no logits are exposed, no numerical threshold is created here, and
  the list of what a future qualification campaign must freeze
  prospectively is recorded in the reduction.

## Phase 2 — workload economics (matched pairs, distributions retained)

`results/economics.json`, derived by `scripts/v0b_economics.py`. Prefill
and decode are kept separate everywhere; no combined average exists.

### NV-A (04:00.0, RTX 3060 Ti): Vulkan vs CUDA — same device

| metric | Vulkan | CUDA | VK/CUDA (CALCULATED) |
|---|---|---|---|
| prefill pp512 t/s (median of 3 process aggregates) | 3579.0 | 3773.1 | **0.9486** |
| decode tg128 t/s (median of 3) | 95.5 | 108.0 | **0.8842** |
| startup-to-ready (s, corrected zero-inference) | 13.023 | 11.364 | CUDA 1.146x faster ready (+1.66 s) |
| VRAM at ready | 3.280 GB | 3.424 GB | Vulkan −143.7 MB |
| host RSS at ready | 1.003 GB | 0.789 GB | Vulkan +213.7 MB |

These ratios are DESCRIPTIVE summaries of retained evidence. The
0.85/0.80 "near-native" similarity figures sometimes quoted against
them are a non-authoritative heuristic: no performance threshold was
preregistered in this bundle's methodology, and none gates the terminal
recommendation.

### AMD-A (02:00.0, Polaris): Vulkan characterization — no native comparator

pp512 median 498.0 t/s; tg128 median 43.7 t/s; ready 26.48 s; 3.25 GB
VRAM at ready; 0.470 GB host RSS at ready. HIP/ROCm is
`NATIVE_BACKEND_UNAVAILABLE` on the frozen stack; no Vulkan/native ratio
is computed or claimed.

### Supplemental matched CPU baseline (new physical collection, bounded)

Method frozen in `METHODOLOGY.md` before collection; three corrections
refine the proof and provenance record (`METHODOLOGY-CORRECTION-1.md`,
`METHODOLOGY-CORRECTION-2.md`, `METHODOLOGY-CORRECTION-3.md`). Runs
collected under superseded rules were discarded at collection time and
their bytes were OVERWRITTEN by the accepted campaign's re-use of the
runner's sequential run IDs; those bring-up bytes are NOT retained — a
declared provenance defect of this bundle, recorded plainly in
correction 3 §1. Accepted canonical arm: `v0b-cpu-01..03`, collected
2026-09-12 on `inferswarm02`, each accepted only after the corrected
proof is re-derived from its raw retained stderr.

Corrected execution proof (correction 3): the model's LAYERS executed on
the host CPU — exactly one `offloaded 0/37 layers to GPU` line, all 37
per-layer assignment lines bound to CPU, CPU-mapped model buffer, CPU KV
buffer, CPU output buffer, clean exit. The retained stderr also shows
`llama_prepare_model_devices: using device Vulkan0 ...` and a nonzero
`Vulkan0 compute buffer` scratch reservation (~565.81 MiB): Vulkan
initialization and GPU scratch allocation WERE present. The proof
therefore claims CPU layer execution only — it does NOT claim "no GPU
participated" or "no GPU device was used".

Accepted arm (3 independent process runs, same host/probe/model/
workload as V0-A, `-ngl 0`, `-t 2`): pp512 median **53.81 t/s**; tg128
median **0.80 t/s**.

Same-host substrate comparison (CALCULATED; MATCHED_WITH_DECLARED_
DIFFERENCE — execution substrate differs, which is the question):

| metric | AMD-A Vulkan | host CPU | ratio VK/CPU |
|---|---|---|---|
| prefill pp512 | 498.0 t/s | 53.81 t/s | **9.26x** |
| decode tg128 | 43.7 t/s | 0.80 t/s | **54.6x** |

Interpretation: the AMD Vulkan path is not merely "slower than a
native backend that this host cannot run" — it is decisively faster
than host-memory execution on this host, at both prefill and decode,
while also freeing the host CPU and holding state in device-local
memory. The "slower than native" and "not useful vs host" conclusions
are therefore different conclusions, and the evidence selects the
former. The 2x figure sometimes used as a "usefulness bar" is a
non-authoritative descriptive heuristic — it was never preregistered
in this bundle's methodology and gates nothing.

Honest scope notes: this is one model, one 2-thread host CPU, one
quantization; the CPU arm proves substrate usefulness for THIS
subject, not a general CPU-performance characterization.

## Phase 3 — portable-capability assessment

`results/capability-assessment.json`, derived by
`scripts/v0b_capability_assessment.py`. Findings are recorded as
backend capabilities/evidence associated with physical Compute Units
(never as vendor ontology). Highlights:

- Deterministic device discovery/selection, explicit device-local
  memory, model materialization on the accelerator, fixture-scale
  execution without silent host fallback, evidence-bindable runtime
  identity, and machine-readable capability discovery: evidence-
  supported on BOTH vendor stacks.
- Representation/quantization: strong on NVIDIA (fp16/int-dot/
  NV_coopmat2 advertised), structurally limited on Polaris (no fp16
  compute, no int-dot, no matrix cores — advertised-capability facts
  only; causal attribution of the throughput level remains OPEN).
- Persistent-host-copy question: NO direct evidence. Observation only:
  at identical device residency the Vulkan arms hold more host RSS
  than CUDA (NV-A +213.7 MB; AMD-A 0.47 GB total), consistent with a
  host-side shadow; RSS cannot establish persistence semantics — a
  runtime-level experiment is required before any residency claim.

## Phase 4 — integration seams

`results/seam-comparison.json` (`scripts/v0b_seam_comparison.py`).
All five classes considered:

1. Existing runtime gains a Vulkan path — ruled inapplicable for a
   first spike: the current research runtime's execution stack is
   CUDA/capture-shaped and Phase1R evidence shows execution-path swaps
   there are disproportionately expensive.
2. Backend-specific execution adapter/participant — strongest: a
   bounded Vulkan-capable executor realizes ONE strategy-defined unit
   on a Compute Unit while the planner stays backend-neutral; matches
   doctrine (fabric-doctrine 2.4/2.8/6.6, ADR 0006) and directly tests
   the portable-backend hypothesis.
3. External whole-model substrate — insufficient as the primary seam:
   cannot expose state/boundary semantics for exact-integrity
   qualification.
4. Custom Vulkan kernels — ruled out: no missing capability in the
   retained evidence justifies that program scale.
5. No integration — not supported: correct, clean, backend-locally
   stable on AMD-A, near-native on NVIDIA (descriptively), and
   decisively faster than host execution on AMD where no native backend
   exists. Rejection merely for losing to the native backend is
   explicitly barred by the issue.

## Phase 5 — terminal

`TERMINAL.json`: **`V0B_PROCEED_TO_INTEGRATION_SPIKE`**, recommended
seam S2 — selected only after the terminal generator mechanically
validates its inputs (schema-corrected CPU-arm proof re-derived per run,
per-pair repeatability consistency, all five seam classes considered,
S2's recorded properties: LOW planner leak, CUDA/HIP coexistence, V0-C
scope that freezes no public API, and the required capability facts with
their evidence). Any missing, malformed, or contradictory input fails
closed to a lower classification. The terminal claims no
logits-level numerical equivalence and creates no threshold; its
non-claims are machine-checked.

The bounded V0-C scope remains: one strategy-defined execution unit via
a Vulkan-capable adapter, planner-selected from capability evidence,
beside a CUDA unit; no public API freeze, no preferred-backend ADR, no
new threshold. Whether V0-C EXECUTES remains a separate authorization
decision; this bundle only establishes that the spike is
evidence-supported and defines its honest scope.

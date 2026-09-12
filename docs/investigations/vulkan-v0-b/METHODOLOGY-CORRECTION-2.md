# V0-B supplemental-arm correction 2 — CPU-execution proof rule, second refinement (frozen before any accepted run)

Authority: `METHODOLOGY.md` + `METHODOLOGY-CORRECTION-1.md` (this bundle).
ADDITIVE; frozen before any run under correction 1's rule was accepted.
The three runs collected under correction 1's rule were DISCARDED at
their collection time — fail-closed worked; none of them was averaged
into any accepted result.

## Defect found by correction-1 bring-up

Correction 1 required every `Vulkan0 compute buffer` line to report
`0.0000 MiB`. At the pinned commit, `-ngl 0` with a Vulkan device present
still allocates NONZERO GPU compute/scheduler-reserve scratch buffers
(~565.81 MiB + ~342.63 MiB observed on the NVIDIA ICD) even though:

- `load_tensors: offloaded 0/37 layers to GPU` is present; and
- `CPU_Mapped model buffer` carries all weights; and
- every op runs on CPU.

The scratch reservations are backend bookkeeping for layers=0, not
evidence of GPU execution. Correction 1's rule is therefore
unsatisfiable, again — and again the failure mode was safe (runs
discarded, not averaged).

## Corrected proof rule (final; identical for every accepted run)

A run is backend-selection-proven (model executed on host CPU) if and
only if ALL of:

1. stderr contains exactly one `offloaded 0/37 layers to GPU` line;
2. stderr contains `CPU_Mapped model buffer` (weights mapped on CPU);
3. stderr contains `CPU KV buffer` and `CPU  output buffer` sizes
   (KV + output state on CPU);
4. stderr contains NO line of the form `offloaded <n>/37` with n > 0,
   and no `CUDA0`/`Vulkan0` device-selection banner binding execution
   to a GPU device (enumeration banners remain permitted and expected);
5. process exit code is 0.

Note recorded honestly: with a Vulkan ICD present, ggml reserves nonzero
GPU scratch buffers even at `-ngl 0`. The rule above also prohibited "no
`CUDA0`/`Vulkan0` device-selection banner binding execution to a GPU
device" — a clause the maintainer-review correction round found BOTH
unsatisfiable (the accepted runs' stderr contains
`llama_prepare_model_devices: using device Vulkan0 ...`) AND unenforced
(the runner's `startswith("using device ")` detector could never match
it). Correction 3 replaces that clause with an explicit disposition and
defines the final proof; this document's rule is superseded by
METHODOLOGY-CORRECTION-3.md §3.

## Addendum — run numbering

The runner numbers its outputs sequentially per invocation
(`v0b-cpu-01..03`), so the canonical retained runs occupy
`results/cpu-supplemental/v0b-cpu-01..03/` (collected 2026-09-12) while
correction 2 was the declared rule. They were mistakenly accepted by the
defective detector despite the prohibited retained Vulkan0 banner. They
are factually revalidated only under the retrospective correction-3
layer-execution proof, not proven or accepted under this rule. The earlier
discarded runs under the superseded rules used the same IDs; per correction
1's disposition, their bytes were overwritten by the later collections,
and the corrections themselves are the retained record of the bring-up.

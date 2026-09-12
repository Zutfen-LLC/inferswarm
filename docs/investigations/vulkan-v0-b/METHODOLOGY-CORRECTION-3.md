# V0-B supplemental-arm correction 3 — provenance statement and final CPU-execution proof semantics (maintainer-review correction round)

Authority: `METHODOLOGY.md` + `METHODOLOGY-CORRECTION-1.md` +
`METHODOLOGY-CORRECTION-2.md` (this bundle). This correction is issued in
the maintainer-review correction round of PR #146, AFTER the accepted
campaign was collected. It changes NO retained byte, collects NO new
measurement, and rules no run in or out retroactively: all three
accepted runs remain accepted, all superseded runs remain superseded.

## 1. Provenance statement made plain (supersedes the hedged wording)

The superseded bring-up bytes were OVERWRITTEN and are NOT retained.

- The original-rule run discarded at bring-up (before correction 1) was
  overwritten by the accepted campaign's re-use of the sequential run
  ID `v0b-cpu-01`.
- The three correction-1-rule runs discarded at bring-up (before
  correction 2) were overwritten by the accepted campaign's re-use of
  the sequential run IDs `v0b-cpu-01..03`.

No stderr, stdout, or run.json bytes from any superseded run exist in
this repository. The ONLY retained record of the bring-up is these
correction documents. This is a PROVENANCE DEFECT of this bundle (the
runner overwrote discarded bytes instead of archiving them, unlike the
V0-A corrections which preserved superseded bytes in place); it is
declared here, not blurred, and it bounds what can be claimed about the
discarded runs: their measurements and their proof lines cannot be
re-inspected, only their discard and subsequent overwrite can be
asserted from this document.

Consequently, correction 1's reference to `v0b-cpu-01/` "with status
DISCARDED under the original rule" describes a directory that no longer
contains that run's bytes, and both corrections' mentions of
observations "retained in the discarded runs' stderr" are wrong as
written: those observations exist only as the narrative values recorded
in correction 2. The authoritative statement is this section.

## 2. Execution-proof defect found by maintainer review

The correction-2 rule prohibited "no `CUDA0`/`Vulkan0` device-selection
banner binding execution to a GPU device", but the accepted runs'
retained stderr contains:

    llama_prepare_model_devices: using device Vulkan0 (NVIDIA GeForce RTX 3060 Ti) (0000:04:00.0) - 8122 MiB free

The runner's detector (a predicate equivalent to
`line.strip().startswith("using device ")`) never matched this line, so
`gpu_execution_binding_lines` was recorded EMPTY in all three accepted
`run.json` files while the line sat in the retained bytes. The
correction-2 rule as written is therefore simultaneously unsatisfiable
(the banner exists) and unenforced (the detector cannot see it) — the
worst combination: a violation recorded as compliance.

What the retained bytes actually prove: EVERY model layer executed on
the host CPU —
`load_tensors: offloaded 0/37 layers to GPU`; all 37
`layer <i> assigned to device CPU` lines; `CPU_Mapped model buffer`;
`CPU KV buffer`; `CPU output buffer`; clean exit. The `using device
Vulkan0` line is runtime device PREPARATION (ICD enumeration context:
scratch reservation and scheduling), not layer execution. What CANNOT
be claimed: "no GPU participated", "no GPU device was used", or "no GPU
memory was touched" — the same retained stderr shows a nonzero
`Vulkan0 compute buffer` scratch reservation (~565.81 MiB).

## 3. Corrected proof rule (final; layers-executed-on-host-CPU)

A run is backend-selection-proven (model layers executed on the host
CPU) if and only if ALL of:

1. exactly one `offloaded 0/37 layers to GPU` line (exact zero GPU-layer
   offload);
2. all 37 `layer <i> assigned to device CPU` lines present, and NO layer
   assigned to any GPU device;
3. `CPU_Mapped model buffer` present (weights mapped on CPU);
4. `CPU KV buffer` and `CPU output buffer` present;
5. process exit code is 0.

The proof is implemented ONCE, in `scripts/v0b_cpu_proof.py`, and is
enforced both at collection time (`v0b_cpu_supplement_run.py`) and at
reduction time (`v0b_cpu_supplement_derive.py`, `v0b_economics.py`); the
reduction re-derives it from the RAW retained stderr on every run and
never trusts a `backend_selection_proven` boolean. `using device <GPU>`
lines are matched, retained, and reported with the disposition
`icd_device_enumeration_context_not_prohibitive`: they are declared
context, neither proof nor violation. Claim scope: layers-executed-on-
CPU, NOT "no GPU memory touched".

## 4. Disposition of the accepted runs

The three accepted runs (`v0b-cpu-01..03`, collected 2026-09-12) satisfy
the corrected rule on their retained raw bytes — including the
previously undetected `using device Vulkan0` line, now explicitly
dispositioned. They remain ACCEPTED; their collected-time verdicts were
correct, their recorded `gpu_execution_binding_lines` fields were
incomplete, and the summary (`cpu-supplemental/summary.json`) now
carries the re-derived per-run proof.

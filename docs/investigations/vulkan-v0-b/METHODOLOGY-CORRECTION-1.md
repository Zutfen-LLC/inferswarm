# V0-B supplemental-arm correction 1 — CPU-execution proof rule (frozen before any accepted run)

Authority: `METHODOLOGY.md` (this bundle). This correction is ADDITIVE and
freezes a corrected per-run backend-selection proof BEFORE any canonical CPU
run is accepted. It exists because the first physical run exposed a defect in
the METHODOLOGY's proof rule — the run itself is retained as
`results/cpu-supplemental/v0b-cpu-01/` with status DISCARDED under the
original rule, and its bytes are never edited.

## Defect found by first-run bring-up (run v0b-cpu-01)

METHODOLOGY.md required: "each run must record `backends == "CPU"` in its own
CSV row ... and zero Vulkan enumeration lines in retained stderr."

Both requirements are unsatisfiable at the pinned commit with `-ngl 0`:

1. llama-bench labels rows with the AVAILABLE backend registry (here
   `Vulkan` — the build's GPU backend), not the backend that executed the
   layers. A `-ngl 0` run on a machine with a Vulkan ICD still prints
   `Vulkan` in that column while executing every layer on CPU.
2. the binary unconditionally enumerates Vulkan devices on startup
   (`ggml_vulkan: Found 1 Vulkan devices:`), regardless of `-ngl`.

So enumeration lines and the CSV backend column CANNOT prove or disprove
CPU-only execution at this commit. The originally specified rule would have
discarded every physically valid CPU run (fail-closed worked as intended:
v0b-cpu-01 was recorded DISCARDED, not reinterpreted).

## Corrected proof rule (identical for every accepted run)

`-v` (verbose) is added to the argv so ggml buffer accounting is retained in
stderr. A run is backend-selection-proven (CPU-only) if and only if ALL of:

1. stderr contains `offloaded 0/37 layers to GPU`;
2. stderr contains `CPU_Mapped model buffer` (weights mapped on CPU);
3. NO `Vulkan0 compute buffer` line reports a size other than `0.0000 MiB`
   (a zero-size Vulkan compute buffer is the expected no-op allocation when
   no layers are offloaded);
4. process exit code is 0.

(2) alone is necessary but not sufficient (mapped weights can coexist with
GPU compute buffers); (1)+(3) exclude GPU layer execution; together they
bind the run to host execution.

## Addendum — argv identity

Accepted runs use the METHODOLOGY.md invocation PLUS `-v`. `-v` changes only
log output verbosity, not model bytes, workload, threads, backend selection,
or binaries. This deviation is declared here, before the first accepted run,
and is never absorbed silently.

## Disposition of v0b-cpu-01

The v0b-cpu-01 run collected under the original rule was DISCARDED (its
measurements were not consumed by any reduction). Its bytes were later
OVERWRITTEN when the canonical campaign re-used the runner's sequential
run IDs under this corrected rule; the runner records the authoritative
state per run ID at collection time, and `summary.json` lists exactly
the accepted runs. The original defective-rule run is therefore
recorded here by this correction document rather than by retained bytes
— a provenance defect of this bundle, declared rather than blurred:
earlier V0-A corrections preserved superseded bytes in place; this
bundle's runner overwrote them. Accepted runs under this rule:
`results/cpu-supplemental/v0b-cpu-01/` (re-collected),
plus the subsequent sequential IDs.

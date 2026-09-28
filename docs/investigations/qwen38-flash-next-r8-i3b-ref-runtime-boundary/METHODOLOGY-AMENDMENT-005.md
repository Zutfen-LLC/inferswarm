# METHODOLOGY AMENDMENT 005 — Issue #250 V0 adapter placement and preflight boundary

Dated: 2026-09-27. Repository-only documentation amendment on PR #251. This
records the narrow V0 adapter disposition informed by accepted Issue #243
substrate authority and Issue #250 Phase 0 source authority, plus the supplied
binary-only host preflight. It does not authorize or report a model request,
physical selector-to-BDF probe, V0 inference, CPU A, new dispatch, or merge.
Earlier methodology amendments remain unchanged and preserved verbatim.

## Authority and scope

Accepted #243 establishes the inferswarm05 Radeon Pro V340L as a practical
bounded execution substrate, not a row observer. Its accepted placement
mechanism is `VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/radeon_icd.json` with
`GGML_VK_VISIBLE_DEVICES=<idx>` for die selection, with per-BDF
`mem_info_vram_used` deltas used to bind Vulkan index to physical die and
establish selected/excluded-die residency. The accepted canonical Vulkan
binary SHA-256 is
`21707f2568d80fb781b445cd472588e83501e1cc66dcf10885b286e34c02573e`.
That accepted binary is placement substrate authority; it is not a row
observer and does not replace the exact comparator binary below.

Issue #250 Phase 0 source authority on the frozen llama.cpp source pin
`b29c606e28a01b1bc8c1351026a0fa6e616bf6c4` establishes the source law
`i_gpu_start = n_layer + 1 - ngl`: at `ngl=1` the output/full-vocabulary
projection is placed on Vulkan while the input embedding remains CPU-side.
This is source-derived placement semantics, not fresh physical proof that a
runtime selector resolves to a particular BDF.

The comparator observer remains the exact unchanged binary SHA-256
`6f8b56bd44d116cdc691911f8a1131840f5c7a720133c05febe11e467c2636ad`.
It remains the preferred comparator binary on both NVIDIA and AMD: using the
same unchanged executable eliminates a build variable from cross-vendor row
comparison. Do not rebuild or substitute it for this adapter step. The
adapter's authority is not interchangeable with #243's placement substrate
or with #250's source-derived placement law.

## Supplied binary-only preflight facts

The exact comparator binary above was copied unchanged to
`/home/hermes/is250-v0-preflight/observer-bin` on `inferswarm05`. Its dynamic
libraries were provided through the exact `LD_LIBRARY_PATH` libraries from
`inferswarm01`. Running `--help` exited 0 without a model. The observed
platform was RADV ICD 25.0.7, Vulkan 1.4.309, kernel
`6.12.107+deb13-amd64`. Two V340L dies were observed at BDFs `07:00.0` and
`0b:00.0`. These facts establish only binary startup/help and platform
preflight as supplied; they do not attest a model launch, selector mapping,
row-observation behavior on AMD, or residency.

## Unproven physical binding and next-evidence boundary

No physical selector-to-BDF probe is claimed here. In particular, no claim is
made that a `GGML_VK_VISIBLE_DEVICES` value selects either `07:00.0` or
`0b:00.0`, and no selected/excluded per-BDF residency delta has been measured
for this V0 adapter. `--help` success without a model cannot establish either
fact. The exact selection environment, selector value, fresh BDF binding, and
selected/excluded residency proof must be retained together before any future
V0 model request. If that binding cannot be established, fail closed; do not
infer die ordering from Vulkan enumeration or reuse a prior host's ordering.

The two V340L dies observed on September 27 are runtime observations,
not timeless constants. The dormant `run_v0_binding_preflight` path requires
fresh exact-head dispatch, canonical cost and model attestation before its
future load-only probes; it writes two per-index probe records and a canonical
selector-binding digest. Its launch argv is the ordinary pinned `ngl=1`
server argv with no `--device` flag; its process environment includes the
RADV ICD, `GGML_VK_VISIBLE_DEVICES=<validated index>`, `CUDA_VISIBLE_DEVICES=-1`,
and the exact comparator library directory. The V0 unit and reducer both
revalidate the per-index probe digests, DRM card/BDF mapping, retained RADV/
Mesa/Vulkan/kernel identity, selected-die material VRAM delta and excluded-die
nonparticipation. A full 993,280-byte decision-0 row is still the comparison
unit; V0 remains non-terminal and never qualifies either vendor. No new
per-tensor unstructured-log observer is demanded by the pinned source law.

## One frozen screening device (correction, 2026-09-27)

The two-index load-only preflight establishes the two CANDIDATE
selector-to-BDF bindings (index 0 -> one physical V340L BDF, index 1 ->
the other) and nothing more. Before the first V0 inference unit, exactly
ONE of those validated entries is canonically FROZEN for the whole AMD
screening population by an append-only retained record
(`v0-screen-freeze.json`, schema `inferswarm.issue250.v0-screen-freeze/1`)
carrying `v0_screen_vulkan_index`, `v0_screen_selected_bdf`,
`v0_screen_excluded_bdf`, the exact PR head, the live dispatch-authority
digest, and the canonical digest of the validated preflight record it was
derived from. The frozen choice is derived mechanically from the validated
preflight record content via the frozen rule
`lexicographically-smallest-selected-bdf-of-validated-two-index-preflight` —
never from historical enumeration order, host BDF constants, or a
caller-supplied preference — and is re-validated against the live
substrate (enumeration/DRM/runtime identity) when written. The record is
append-only: it cannot be rewritten after the fact, and no device may be
silently re-chosen after a failure.

Every V0 unit — repeats 1, 2, and the conditional repeat 3 — must use the
frozen `GGML_VK_VISIBLE_DEVICES` value, resolve to the same
`selected_bdf`, keep the sibling as `excluded_bdf`, and pass the live
enumeration/runtime/DRM and per-unit residency checks. Only process
freshness varies between AMD screening repeats. The retained-evidence
validator (`_v0_retained_rows`) and the terminal reducer
(`derive_v0_state`) each enforce this invariant INDEPENDENTLY of producer
behavior: a population whose receipts use different Vulkan indices or
selected BDFs — even if every receipt is individually valid — is invalid
V0 evidence, fails closed, and can never influence A reachability or be
interpreted as AMD fresh-process variability, repeat stability,
concordance, or disagreement.

No V0 physical model request or load-only preflight has occurred or is
authorized by this amendment. No CPU A execution is authorized. Existing
exact-head review and dispatch requirements remain independently controlling.

# METHODOLOGY AMENDMENT 007 — Issue #250 V0n current-window NVIDIA Vulkan screen

Dated: 2026-09-28. Repository-only additive correction on PR #251
following the completed V0 AMD screen (maintainer GO review comment
`5868616376`; AMD V0 dispatch comment `5868617068`; executed head
`c5cc132762c51a3352014f36553eff6d0d26b112`; evidence root
`/home/hermes/is250-campaign/evidence-v0-c5cc132/`). This amendment
freezes the prospective current-window NVIDIA RTX 3060 Vulkan
`ngl=1` comparison leg (V0n) BEFORE any NVIDIA execution. It
authorizes no dispatch, no model request, no CPU Arm A/B/C/D, and no
merge. Earlier methodology amendments remain unchanged and preserved
verbatim.

## Motivation and scope

The completed V0 AMD screen established, under the frozen case-3072
subject (comparator binary `6f8b56bd…`, llama.cpp pin `b29c606e…`,
three-member model set, byte-exact request contract, Vulkan backend,
`ngl=1`), that three fresh-process AMD/RADV repeats on one frozen die
are byte-identical (decision-0 row SHA-256
`2187ab8f444e726b9a34d9874499603446a23efdd7943e8330286e223938fb41`,
993280 bytes each) yet differ from BOTH retained #248 NVIDIA Vulkan
`ngl=1` rows (`dff2499b…`, `e369c8cb…`) — reducer state
`CROSS_VENDOR_DISAGREEMENT_STOP_BLOCKED`, maintainer stop, Arm A
ineligible.

That result cannot distinguish (a) historical NVIDIA/Vulkan
fresh-process variability persisting in the current window from (b) a
stable current cross-vendor Vulkan numerical difference, because the
NVIDIA side of the comparison is ~3 days old. (No driver difference is
claimed or assumed: accepted #248 authority freezes NVIDIA driver
`610.57.04`, and the V0n freeze re-observes the live driver through
the same #248 machinery — the current window is bound to whatever the
fresh observation shows, with any drift from the accepted identity
failing closed.) Before spending tens of CPU-hours on
Arm A, one bounded current-window NVIDIA leg answers which hypothesis
the campaign is actually facing. The V0n leg is that leg, and nothing
more: it decides NO vendor's numerical authority, emits NO Issue #250
terminal, grants NO Arm A eligibility, and reaches NO CPU arm.

## Proof the retained #248 comparison rows are NVIDIA Vulkan `ngl=1` rows

The ambiguity this amendment closes permanently: the two retained
comparison rows are NVIDIA **Vulkan** rows, not CUDA rows. The
mechanical proof is in the accepted receipts (consumed read-only by
`verify_v0_historical_rows`, unchanged):

- `server_env.VK_ICD_FILENAMES ==
  /usr/share/vulkan/icd.d/nvidia_icd.json` (NVIDIA's Vulkan ICD);
- `server_env.CUDA_VISIBLE_DEVICES == -1` (every CUDA device removed
  at the process boundary — no CUDA backend could enumerate);
- `server_argv` carries `-ngl 1` with the exact comparator binary
  `6f8b56bd…`, whose dynamic link family contains `libggml-vulkan.so.0`
  and NO CUDA library (`ldd` under the NVIDIA ICD environment);
- both units ran on `inferswarm01` under the #248 placement arm.

Every V0n tooling consumer of those rows (reducer constant
`V0_NVIDIA_ROW0_SHA256`) re-authenticates exactly these fields before
any comparison; a CUDA-produced row cannot satisfy them.

## Frozen V0n condition

Same accepted case-3072 semantic subject as V0:

- host `inferswarm01`; the physical subject is EXACTLY the accepted
  #248 Arm-B reference GPU — GPU UUID
  `GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55`, BDF `00000000:03:00.0`,
  PCI `10de:2504` with the #248-frozen subsystem/revision/link
  identity, NVIDIA driver `610.57.04`, NVIDIA ICD
  `/usr/share/vulkan/icd.d/nvidia_icd.json`, Vulkan device UUID
  `d5c05739-96c1-7e49-89b6-bf54c2121c55` (name `NVIDIA GeForce RTX
  3060`, API `1.4.341`, `NVIDIA proprietary 610.57.04`), selector
  `GGML_VK_VISIBLE_DEVICES=0`, `CUDA_VISIBLE_DEVICES=-1`. Identity
  authority is the accepted #248 machinery
  (`scripts/issue248_identity.py`: `REFERENCE_IDENTITY`,
  `observe_arm_identity("B")`, `identity_problems("B", ...)`,
  `derive_identity_from_raw("B", ...)`) reused verbatim — V0n defines
  NO parallel identity schema and never weakens #248 semantics.
  Vendor/device/driver-ID alone is never accepted as physical
  identity; a same-model RTX 3060 with a different UUID/BDF rejects;
- **Vulkan backend only**: `VK_ICD_FILENAMES=nvidia_icd.json`,
  `GGML_VK_VISIBLE_DEVICES=0`;
- **CUDA exclusion**: `CUDA_VISIBLE_DEVICES=-1` in every server
  environment, plus a mechanical link-family check refusing any
  `libggml-cuda`/`libcuda`/`libcudart` in the comparator's dynamic
  dependencies, plus `cuda_participation is False` required in every
  retained receipt — CUDA-active, CUDA-fallback, or ambiguous-backend
  executions fail closed;
- exact accepted llama.cpp pin `b29c606e…` and comparator binary
  `6f8b56bd…` with the full eight-library observer family digest set;
- same comparator observation seam (`LLAMA_OBSERVE_*` hooks);
- same frozen model release/member (`/srv/models/qwen38-ud-iq1-s/`,
  member 00001-of-00003, accepted SHA-256);
- same prompt bytes and token IDs (accepted fixture ladder case-3072,
  3077 actual tokens);
- same byte-exact request contract;
- fresh process for every repeat (per-receipt distinct PID + full
  process attribution custody);
- `ngl=1` placement: CPU input embedding / Vulkan output projection
  (pinned source law, `placement_source_law` required in every
  receipt);
- full decision-0 vocabulary row, exactly 993280 bytes, compared only
  by complete-row bytes / canonical SHA-256;
- placement/residency evidence: GPU memory delta under the loaded
  model must exceed 64 MiB (the accepted #243 noise bound), measured
  via a TARGETED `nvidia-smi` query that parses every returned GPU
  row and selects exactly one row matching BOTH the accepted GPU UUID
  and the accepted BDF — never an unqualified one-line population,
  never enumeration order; zero matches, duplicate matches, and
  malformed rows all fail closed, and the selected row is retained in
  the receipt as residency evidence.

## V0n screen-identity freeze (NO-GO correction, comment 5874443020)

Before unit 1, an append-only V0n screen freeze
(`v0n-screen-freeze.json` in the V0n evidence root) is retained from
a FRESH `issue248_identity.observe_arm_identity("B")` observation
with `identity_problems("B", ...) == []`, derived through the
accepted machinery, and bound to the exact PR head + live V0n
dispatch authority + pinned comparator/source. The freeze carries the
complete subject identity (every #248 field above plus the
screen-start kernel and Vulkan-instance runtime identity), the
Vulkan selector law, the CUDA-off law, the observer library family,
and a canonical digest; every consumer re-authenticates it against
the ACCEPTED #248 CONSTANTS field-by-field (a re-signed freeze whose
identity no longer equals the accepted authority fails closed even
with internally consistent digests).

Per-unit identity law: EVERY unit re-observes the complete Arm-B
identity live BEFORE launch and again AFTER execution, requiring
exact equality with the same freeze both times; any drift
(driver/runtime/ICD/Vulkan/UUID/BDF/selector) invalidates the unit —
no physical run from a drifted identity may become numerical
evidence. Retained-population law: every `unit.json` binds the
freeze's canonical digest, the full frozen identity, its pre-launch
and post-execution observation digests, the exact UUID/BDF/selector
environment, and all prior binary/model/prompt/request/process/
full-row custody; `_v0n_retained_rows` rejects mixed-identity
populations, mixed freeze digests, PID reuse, and any non-993280
byte row; `derive_v0n_state` fails to `CURRENT_NVIDIA_INVALID_BLOCKED`
before any numerical comparison on any violation.

## Namespace, arm, dispatch, and evidence-root law

- namespace `d250-arm-v0n-nvidia`, arm `V0n-nvidia-vulkan-current`
  (mirrors the V0 AMD naming; distinct in
  `NAMESPACE_ARM_BINDING`-equivalent isolation: the V0n dispatch
  validator refuses every other namespace/arm pair and vice versa);
- a V0n unit runs ONLY under a fresh OWNER/MEMBER exact-head dispatch
  comment for exactly this namespace/arm, revalidated live before and
  after every unit (two-pass law);
- stale dispatch comments `5852485456`, `5862772797`, and the
  completed AMD dispatch `5868617068` are hard-refused by comment ID —
  they can never authorize a V0n unit;
- future evidence root: a NEW sibling root bound to the eventual
  reviewed head, e.g.
  `/home/hermes/is250-campaign/evidence-v0n-nvidia-<HEAD_SHORT>/`;
  the completed AMD root `evidence-v0-c5cc132/` and the historical
  root `evidence/` are read-only comparison inputs and are never
  written by any V0n execution; old/new-head prospective authority is
  never mixed in one reduction;
- the V0n namespace is NOT in the A–D automatic arm ladder and NOT in
  `NAMESPACE_ARM_BINDING`: no CPU Arm A/B/C/D can become
  auto-dispatched from a V0n dispatch or reduction.

## Repeat law (predeclared, before any execution)

Identical bounded screen structure to V0:

1. Run 2 independent fresh-process NVIDIA Vulkan repeats.
2. If the first two full rows differ, classify the current NVIDIA
   screen as variable and STOP the screen (no third repeat).
3. If the first two are byte-identical, run exactly one third
   fresh-process repeat.
4. Three identical rows establish only a repeat-stable current-window
   screening result — not general determinism, not an Issue #250
   terminal, and not Arm A eligibility.

No favorable-repeat selection; no sample-size extension after the
condition is established.

## Prospective interpretation law (reducer states)

- `CURRENT_NVIDIA_VARIABLE_STOP` — fresh-process rows differ. Each row
  is REPORTED as equal-to-AMD-current / equal-to-a-retained-#248-row /
  novel. No root-cause inference.
- `V0N_IDENTICAL_PAIR_THIRD_REQUIRED` — intermediate state after an
  identical first pair; exactly one third repeat required.
- `CURRENT_CROSS_VENDOR_CONCORDANCE_STOP` — three identical rows equal
  to the AMD current-window row `2187ab8f…`: stronger current-window
  Vulkan concordance; #248 remains historical evidence of prior NVIDIA
  variability; maintainer reconciliation of the changed
  runtime/device/driver/build state.
- `CURRENT_CROSS_VENDOR_STABLE_DISAGREEMENT_STOP` — three identical
  rows differing from the AMD row: repeat-stable cross-vendor Vulkan
  disagreement; NO vendor is judged numerically authoritative.
- `CURRENT_NVIDIA_INVALID_BLOCKED` — any identity/backend/placement/
  custody mismatch. No later arm is reachable from an invalid screen.

None of these states is an Issue #250 terminal; every reduction
carries `terminal=None` and `a_eligible=False`.

## Tooling

Additive only; the accepted AMD V0 spine (producer, reducer, freeze,
preflight law) is untouched:

- `scripts/issue250_diagnostic.py`: V0n constants + pure
  `reduce_v0n_screen`;
- `scripts/issue250_physical.py`: V0n dispatch validator, argv/env,
  NVIDIA device observer, binary verifier (CUDA link exclusion),
  `run_v0n_unit`, `_v0n_retained_rows`;
- `scripts/issue250_terminal.py`: `derive_v0n_state` (custody chain →
  full-row comparison);
- `scripts/issue250_timeout.py`: `arm-v0n-nvidia-vulkan` cost condition
  (same planning-rate proxy and ceiling law as V0; disposition
  `authorized_by_v0n_dispatch`);
- `tests/test_issue250_v0n_nvidia.py`: 88 regressions covering the
  directive requirements (Vulkan-not-CUDA identity, CUDA rejection,
  backend/device rejection, wrong-ngl rejection, placement rejection,
  binary/source/model/prompt/request rejection, PID-reuse rejection,
  first-pair-mismatch stop, third-repeat law, concordance stop,
  stable-disagreement stop, variable-stays-variable, full-row not
  winner-only comparison, retained-#248 Vulkan authentication,
  no-terminal law, no-auto-CPU-arm law, stale-dispatch rejection) AND
  the NO-GO correction identity law (exact accepted #248 Arm-B
  identity pass; wrong-UUID/wrong-BDF/UUID-BDF-cross-binding-mismatch/
  different-same-model-RTX-3060/wrong-PCI-subsystem-revision/changed-
  NVIDIA-driver/changed-kernel-driver/changed-ICD/changed-Vulkan-
  UUID-API-driver-name rejection; re-signed/tampered freeze and mixed
  freeze digests rejection; pre-launch drift rejecting before runner
  invocation; post-execution drift preventing row acceptance; units
  with different runtime identities unable to form a screen; targeted
  residency UUID+BDF selection with missing/duplicate/mismatch/mal-
  formed rejection).

This amendment creates no model load, no inference request, and no
physical execution of any kind.

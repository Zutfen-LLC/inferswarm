# R8-H — Matched backend/device parity: Qwen3.8-Flash-Next UD-IQ1_S across CUDA/Vulkan and NVIDIA/AMD

Issue #234 (corrected per maintainer amendment, 2026-09-20;
round-2 correction 2026-09-21).
Campaign: `issue234-r8h-matched-backend-device-parity`.
Status: **COMPLETE — `R8H_QWEN38_MULTI_AXIS_DIVERGENCE_CHARACTERIZED`**
(case-256 rung; ladder escalation correctly stopped at first
deterministic divergence; earliest-divergence position-0 score
characterization mechanically bound).

## 1. Why the original df0cf4 experiment was superseded

The original PR head `df0cf43` ran ONE arm — V340L/Vulkan — and
compared it against the historical R8-D output as the sole correctness
oracle. R8-D was single-host CUDA on two RTX 3060 GPUs plus CPU
spill: a confounded comparator. Its retained observation (V340L
Vulkan case-256, 3 identical repeats, token `34227` at generated
position 5 vs R8-D CUDA `271`, ~1.05 GB selected-die residency,
12,288-byte excluded-die noise, clean platform window) is genuine and
byte-preserved, but it could not establish
`R8H_QWEN38_VULKAN_CORRECTNESS_FAIL` — only that the V340L arm
differed from a historical CUDA-derived stream under unmatched
geometry. That terminal is RETIRED.

The original evidence lives, byte-identical, under
`evidence/superseded-20260920-original-comparator/` (14 files, each
sha256-verified against its df0cf43 git blob by the authority
builder). Three further defects motivated the redo: the physical
producers were edited after the claimed closure commit, and the
assembler registered zero of its advertised controls.

## 2. Corrected experiment — matched A/B/C

Same subject, same minimal placement (`ngl=1`), same pin, same
request, three arms:

| Arm | Host | Device | Backend | binary sha256 (llama-server) |
|---|---|---|---|---|
| A | inferswarm01 | RTX 3060 `GPU-1fc28f83…` @ `00000000:02:00.0` | CUDA (Vulkan OFF) | `9a39749c1ff448fe…` |
| B | inferswarm01 | SAME RTX 3060 (same UUID/BDF) | Vulkan (CUDA OFF) | `21707f2568d80fb7…` |
| C | inferswarm02 | V340L die `00000000:06:00.0` (die `09:00.0` excluded) | Vulkan (CUDA OFF) | `21707f2568d80fb7…` (same bytes as B) |

- llama.cpp pin `b29c606e28a01b1bc8c1351026a0fa6e616bf6c4` for all
  arms. The Vulkan build was produced once on inferswarm01 and the
  identical bin dir deployed to inferswarm02 (ldd-verified), so B and
  C share binary bytes; its CPU component is built with baseline
  intrinsics (`GGML_NATIVE/AVX/AVX2/FMA/F16C/BMI2=OFF`) because 02's
  Celeron G3900 has no AVX — same pin, same source, no runtime
  upgrade.
- Model: exact accepted UD-IQ1_S members, re-hashed on BOTH hosts
  before canonical output (72,546,461,344 bytes, 3/3 sha256 verified
  per host).
- Selector bindings proven mechanically: A by
  `CUDA_VISIBLE_DEVICES=GPU-<uuid>`; B by
  `GGML_VK_VISIBLE_DEVICES=0` under the NVIDIA ICD (residency probe);
  C by `GGML_VK_VISIBLE_DEVICES=0` under the radeon ICD (residency
  probe; RADV UUID encodes the BDF).
- A/B same-GPU proof: both selectors bind `00000000:02:00.0` /
  `GPU-1fc28f83…` (census join + per-repeat selected-device residency
  on that exact GPU, sibling `d5c05739…` flat at 1–2 MiB counter
  noise through every repeat).

## 3. Result — case-256, 3 repeats per arm, all deterministic

| Arm | tokens (identical ×3) |
|---|---|
| A (3060/CUDA) | `328 760 40554 1 271 12188 279 1727` |
| B (3060/Vulkan) | `561 324 55965 51624 29014 271 248068 271` |
| C (V340L/Vulkan) | `561 324 55965 51624 29014 34227 18030 16382` |

Pairwise: **A≠B from generated position 0; B≠C at position 5
(`271` vs `34227`); A≠C from position 0.** Per frozen order, ladder
escalation STOPPED at case-256 (no later rung was executed).

### Position-0 score characterization — the required FIRST-divergence bound (round 2)

Issue #234 requires bounded pre-choice numerical characterization at
the FIRST divergent generated position. The reducer mechanically
derives `required_characterization_position =
min(pairwise first-divergence positions)` from the raw candidate
token streams — for this campaign that derives **0** (A↔B and A↔C
diverge at 0), so the round-1 position-5 characterization could no
longer satisfy the global gate. A bounded observation-only position-0
collection was performed under a prospective pin
(`evidence/candidate/characterization/pos0/pos0-observation-pin.json`)
using the SAME pinned R8-E observation binaries (hashes re-verified
before collection); all three arms reproduced their canonical token
streams exactly (non-perturbation proven per arm), and the new pos-0
hook rows are byte-equal to the retained round-1 run's pos-0 rows.
Every number below is re-derived by the terminal reducer from the
raw float32 row bytes (248,320 floats per arm, all finite; hook
JSONL rows required to agree; authored summary fields are never
authority):

| Arm | winner | runner-up | winner margin | 328-vs-561 |
|---|---|---|---|---|
| A (3060/CUDA) | `328` @ 15.1907425 | `561` @ 15.0724392 | 0.118303 | 0.118303 (328 rank 1, 561 rank 2; 271 rank 3 @ 14.3428001) |
| B (3060/Vulkan) | `561` @ 15.2642355 | `328` @ 15.0300322 | 0.234203 | 0.234203 (561 rank 1, 328 rank 2; 271 rank 4 @ 13.9011326) |
| C (V340L/Vulkan) | `561` @ 15.3407526 | `359` @ 14.9658098 | 0.374943 | 0.599080 (561 rank 1, 271 rank 3, 328 rank 4 @ 14.7416725) |

Observation at position 0: **A/CUDA selects `328` while both Vulkan
arms select `561` from the same prompt on the same (A/B) GPU.** The
margin structure is not a shared near-tie: A's 328-vs-561 margin is
~0.118, B's 561-vs-328 ~0.234, C's 561-vs-328 ~0.599.

### Position-5 characterization — RETAINED as secondary (round 2)

The round-1 position-5 document is retained verbatim under
`evidence/candidate/characterization/pos5-secondary/` and explicitly
reclassified as `secondary_device_axis_characterization`: position 5
is the first B↔C divergence only (B and C share their generated
prefix through positions 0–4), so it can never satisfy the global
first-divergence gate. Its content is unchanged:

| Arm | winner | runner-up | margin | notes |
|---|---|---|---|---|
| A | `12188` @ 17.114 | `760` @ 16.349 | 0.766 | `271` rank 79; `34227` rank 21184 |
| B | `271` @ 16.682 | `34227` @ 15.996 | 0.686 | focal pair occupies ranks 1/2 |
| C | `34227` @ 16.476 | `271` @ 16.206 | 0.269 | focal pair occupies ranks 1/2 |

Raw sidecars (jsonl + float32 rows, 248,320 floats each) retained
under `evidence/candidate/characterization/`; observation runs
reproduced the canonical token streams exactly (non-perturbation
proven per arm). The historical R8-E near-tie (271/34227) is seen on
the VULKAN arms, not on CUDA — and B vs C still picks opposite
winners.

## 4. Terminal

`R8H_QWEN38_MULTI_AXIS_DIVERGENCE_CHARACTERIZED` — the deterministic
A/B/C relation is neither backend-only (A≠B but B≠C) nor device-only
(A≠B). The overall stream is multi-axis across the whole case, while
the observed divergence structure decomposes as:

- an early **CUDA↔Vulkan backend axis at position 0**: same RTX 3060,
  same prompt, A selects 328 (margin 0.118) while B selects 561
  (margin 0.234) — mechanically supported by the raw-bound position-0
  characterization above;
- a later **NVIDIA-Vulkan↔AMD-Vulkan device/backend interaction at
  position 5**: B and C agree through positions 0–4 (both pick 561 at
  position 0) and first diverge at position 5 (271 vs 34227) — see
  the secondary characterization.

These are observed structural facts, not a single causal claim. Exact
pairwise map retained in
`evidence/TERMINAL.json`/`ASSEMBLY.json`.

Non-claims (explicit):
- NOT an AMD/V340L correctness failure;
- NOT a CUDA correctness failure;
- NOT a driver/silicon defect claim;
- no common-root-cause inference from B≠C or token overlap;
- no single-axis reduction of the multi-axis structure (the early
  backend axis and the later device/backend interaction are reported
  separately);
- no Vulkan PASS/FAIL derived from the historical R8-D stream
  (retained as an external anchor only; its two-GPU CUDA geometry is
  not equivalent to Arm A).

## 5. Producer authority (corrected closure doctrine)

- Physical producers frozen at `e7d822a` (host, runtime, placement,
  ladder, health) — byte-identical from that pin through final HEAD,
  and hash-verified as the bytes deployed on BOTH execution hosts
  (`evidence/freeze/deployed-producers.json`). Round 2 makes that
  verification MECHANICALLY AUTHORITATIVE: the assembler requires the
  exact frozen host×producer matrix (inferswarm01/02 × host, runtime,
  placement, ladder, health), compares every retained hash against
  the closure pin, derives `all_hosts_match_pin` itself (the authored
  boolean is never trusted), and fails closed on missing hosts,
  missing producers, hash mismatches, substitutions, and out-of-lineage
  `closure_producer_head` values (the retained `377d2ff` field is a
  real ancestor of the active closure pin — a superseded re-pin in
  the closure lineage, not a contradiction).
- Closure `PRODUCER-CLOSURE.json` pins the final functional producer
  commit (ancestor of final HEAD; reduction-producer amendments
  re-pinned per doctrine), computed from git blobs at the pin; any
  physical-producer modification after execution fails closed
  (`verify_closure`, exercised by the control suite and tests).
  `scripts/issue234_characterize.py` — the terminal-bearing
  characterization assembler — is closure-bound as a reduction
  producer, and the observation-only producer identity (llama.cpp pin
  `b29c606e`, 85-line hook diff `05867441…`, per-arm observation
  binary hashes, selector/ICD binding, prompt digest, focus env) is
  frozen in `issue234_receipt.py` and validated against the
  prospective observation pin before any observation-derived
  characterization is accepted.
- 36/36 numbered controls all_ok on the final evidence
  (`evidence/ASSEMBLY.json`). Control 33 (round-2 strengthened) now
  proves every characterization-failure path blocks: missing corpus,
  wrong generated position, summary/raw digest binding break,
  raw-sidecar tamper, and non-perturbation forgery.

## 6. Validation at final head (round 3)

Round 3 (maintainer finding on `c1ac7237`) closed the last blocker:
the observation-only score-characterization executions were not
mechanically bound to the GPU/backend selectors they claimed to
represent. The retained round-2 pos0 corpus proved token/logit output
only — observation tokens equal to the canonical stream is NOT
identity proof (the quarantined relative-ICD CPU-fallback incident
demonstrated wrong-environment execution is a real failure class).

What round 3 added:

- **Observation execution receipts** (schema
  `inferswarm.r8h.observation-execution-receipt/1`, one per arm under
  `evidence/candidate/characterization/pos0/`): launch host + boot
  id, exact observation binary path/sha256/bin-dir hashes, llama.cpp
  source pin + hook diff digest, exact launch argv (`/proc/PID/
  cmdline`) and environment (`/proc/PID/environ`, captured at exec),
  in-process backend participation (`/proc/PID/maps` libggml
  objects), device identity under the exact launch environment
  (`--list-devices`, `vulkaninfo` GPU UUID→BDF joins via nvidia-smi
  and RADV BDF-encoded UUIDs), pre/during/post accelerator residency
  with excluded-device bounds, live `nvidia-smi` compute-apps binding
  of the server PID to the frozen GPU UUID (arm A), CPU-fallback
  rejection evidence, artifact digests binding the receipt to the
  retained jsonl/f32/resp/server-log bytes, and the generated stream
  (non-perturbation quarantine before any receipt exists).
- **Bounded recollection** under the prospective pin
  `pos0/pos0-observation-pin.json` (schema /2, authored BEFORE
  collection) and the closure-pinned physical collector
  `scripts/issue234_observe.py` (deployed sha `ddbe8d3c…` verified
  byte-identical on BOTH execution hosts before collection). The
  canonical 3×3 ladder was NOT rerun; the recollected pos0 JSONL rows
  and float32 rows are BYTE-IDENTICAL to the round-2 corpus
  (superseded-round2-unbound/), so every score finding is retained
  unchanged.
- **Terminal gate**: `reduce_observation_execution_truth` re-validates
  every identity relation from receipt bytes (arm A CUDA selector to
  the frozen RTX 3060 UUID `GPU-1fc28f83…` at `00000000:02:00.0`;
  arm B absolute NVIDIA ICD + Vulkan selector resolving to the SAME
  frozen 3060 — the A/B same-GPU relation is derived, not assumed;
  arm C absolute Radeon ICD resolving to V340L die `06:00.0` with
  die `09:00.0` excluded and under the frozen bound; no CUDA
  participation in Vulkan arms and vice versa; no CPU fallback;
  observation binary hash equal to the prospectively authorized
  hash). The score characterization gate requires
  `observation_execution_truth.status == OK` for all three arms,
  else `R8H_EVIDENCE_BLOCKED`.
- **Pin hardening**: `_validate_observation_pin` now enforces the
  exact pinned selector/ICD authority (arm A CUDA selector; arms B/C
  Vulkan selector + ABSOLUTE ICD path + ICD file sha256), so a
  mutated pin selector or a diverging execution selector blocks
  independently.
- **Inert identity check removed**: the round-2
  `_arm_identity_map()`/`_derive_arm_characterization()` pairing
  could never fire (the map never supplied the fields the
  characterization looked for). Observation identity is centralized
  in the execution-truth reducer — one fail-closed authority path.
- **Control 33 strengthened** with a receipts-only-absent companion
  mutation; focused suite extended to 65 tests covering 15
  receipt-mutation classes (wrong GPU, B≠A GPU, wrong die, relative/
  missing ICD, wrong ICD vendor, CPU fallback, wrong binary hash,
  wrong host, pin↔receipt selector mismatch, zero selected activity,
  excluded-device active, forged token equality, digest tamper,
  absent receipt, missing backend mapping) — all fail closed.

Validation at the final round-3 head:

- closure verifies (ancestor + blob identity pin→HEAD + worktree;
  observe.py closure-bound as a physical producer);
- deployed producer verification mechanically executes against BOTH
  hosts with the frozen 2×6 matrix (five e7d822a producers +
  the round-3 collector), all hashes live-read and pin-equal;
- deterministic terminal reduction ×2 (byte-identical);
- focused #234 suite (65 tests) green; #184 and #213 preservation
  suites green with the narrow additive #234 allowance;
- `finalize_repository.py --check` and `sync_project_status.py
  --check` pass; CI planner untouched (test module name unchanged);
- `MANIFEST.sha256` regenerated LAST, after every README/evidence
  artifact was final.

## 7. Non-events (confirmed)

No RPC, no mixed simultaneous AMD/NVIDIA execution, no cross-die
V340L use, no runtime upgrade past the pin, no alternate
quantization, no planner policy change, no ordinary serving traffic,
no canonical ladder rerun in round 3.

## 8. Final reduction-only correction — exact retained-prompt binding

Maintainer review of the Round-4 complete-payload state found one
remaining reduction gap: `_receipt_problems()` validated each retained
`A/B/C.request.json` by payload digest, request contract, prompt type,
and prompt length == 256 — but never mechanically proved the payload
carried the accepted frozen `case-256` prompt token sequence. The
receipt's `request.prompt_sha256` is not derived from the retained
payload during reduction, so a forged retained-input mutation (swap
the 256-token list, recompute the payload digest, update
`receipt.request.payload.*` and `receipt.artifacts.request_payload`,
re-digest the receipt, keep all response/jsonl/f32 bytes) satisfied
the reducer. Canonical output equality is not proof of the prompt
actually sent.

The correction (reduction-only; NO physical campaign, ladder,
observation, or collection was rerun; every physical-producer hash
unchanged):

- **Independent prompt authority**: `accepted_case256_prompt_token_ids()`
  derives the accepted prompt from the accepted fixture authority
  (`docs/investigations/qwen38-flash-next-r8-b/evidence/reference/
  fixture-ladder.json`, SHA-256 verified against `R8D_FIXTURE_SHA256`),
  requiring exactly one `case-256` entry, an integer
  `prompt_token_ids` list of the accepted rendered length 256. It
  fails closed on fixture absence, SHA drift, malformed JSON, missing
  or duplicate case, or a malformed prompt field, and never falls
  back to a constant copied from observation evidence.
- **Exact retained-payload binding**: `_receipt_problems()` now
  requires `decoded_payload["prompt"] ==
  accepted_case256_prompt_token_ids()` — exact list equality — in
  addition to every pre-existing check (payload digest, request
  contract, prompt length, receipt prompt SHA, argv, model members,
  package manifest, device/backend identity, non-perturbation).
  Prompt length alone is no longer sufficient. A mismatch at any
  position emits `arm{X}:request_payload_prompt_identity`; a
  fixture-authority failure emits `arm{X}:fixture_prompt_authority`;
  both fail closed to `R8H_EVIDENCE_BLOCKED` through the real
  terminal path.
- **Adversarial coverage**: the focused suite gained
  `TestExactPromptIdentityBinding` — competent same-length forgeries
  that recompute EVERY dependent binding (B position-200 mutation,
  first-token mutation, middle-token mutation, foreign 256-token
  list), a lazy stale-digest forgery, fixture-authority SHA-mismatch
  and absence controls (sandboxed fixture copies under the AREA
  override), and an execution-truth check that the REAL retained
  Round-4 A/B/C payloads carry the fixture prompt verbatim (they do;
  all three payloads are byte-identical at sha256 `16c315a6…`).
  Synthetic harness payloads now build from the fixture authority.

Mechanically re-derived terminal at the corrected head:
`R8H_QWEN38_MULTI_AXIS_DIVERGENCE_CHARACTERIZED` (unchanged; the real
retained evidence was never mutated), 36/36 controls all_ok,
observation execution truth A/B/C all OK with A/B same frozen RTX
3060 and B/C same authorized Vulkan package. Closure re-pinned
through the reduction-amendment commit; `MANIFEST.sha256` regenerated
LAST.

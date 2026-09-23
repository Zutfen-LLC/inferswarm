# R8-I3 Methodology — first practical AMD/Vulkan Qwen comparator pivoted to RX 580 8GB on the matched high-RAM host (issue #241)

Status: **prospective CPU/static freeze — NO PHYSICAL EXECUTION.**

No SSH-driven model execution, no CUDA/Vulkan device initialization, no
model checkpoint execution, no physical calibration observations, no
predictive-corpus execution, no holdout decrypt/secret access (public
ciphertext/certificate/commitment bytes may be read and hashed
normally), and no physical successor created in this issue slice.

This document freezes the R8-I3 deltas BEFORE the campaign's physical
result phases. Physical phases 1-4 are DORMANT until the maintainer
dispatches them on the exact frozen producer head (dispatch phrase
`R8I3 PHYSICAL DISPATCH #241`).

Status marker: `R8I3_QWEN38_RX580_COMPARATOR_V2_METHODOLOGY_FROZEN`

## 0. Authority lineage

- Accepted statistical/semantic predecessor: #237 / PR #238 / merge
  `3aa59aed74df7f00302a6a2eb84640623b7cc14b` (terminal
  `R8I_QWEN38_HETEROGENEOUS_VULKAN_METHODOLOGY_FROZEN`). Its methodology,
  corpora, seals, thresholds, custody, and authorization doctrine govern
  everything not superseded here.
- Superseded correction exploration: #240 (R8-I2) — retained as
  diagnostic history only; no #240 artifact, hash, or output is consumed
  by this campaign.
- Blocked physical campaign: #239 (R8-J) remains blocked pending a
  practical comparator subject.

## 1. Scope

Prospective pivot of the first practical AMD/Vulkan Qwen qualification
subject from the Radeon Pro V340L (inferswarm02) to a consumer Polaris
RX 580 8GB installed in the SAME high-RAM workstation (inferswarm01) as
the NVIDIA reference, plus the prospective continuous
canonical-reference-prefix observer identity
`inferswarm.qwen38-vulkan-comparator/2`.

Strategic basis (issue #241): RX 580/RX 470-class consumer cards are
the intended AMD workhorse family for InferSwarm scale-out; one consumer
GPU = one Compute Unit + one VRAM Memory Resource; sequential same-host
execution eliminates the host/storage/CPU confounds that made
inferswarm02 unsuitable.

## 2. Frozen subjects and arms (fresh post-swap census, 2026-09-23)

Both arms run SEQUENTIALLY on inferswarm01 (never concurrent
mixed-vendor execution):

- Arm B (reference): NVIDIA GeForce RTX 3060 12GiB,
  `GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55` @ `00000000:03:00.0`
  (NVIDIA ICD, proprietary driver 610.57.04), `GGML_VK_VISIBLE_DEVICES=0`,
  `CUDA_VISIBLE_DEVICES=-1`.
- Arm C (candidate): AMD Radeon RX 580 Series (RADV POLARIS10), Ellesmere
  `[1002:67df]` rev e7 @ `00000000:02:00.0` (radeon ICD, RADV Mesa
  25.0.7-2+deb13u1, apiVersion 1.4.305, amdgpu kernel driver, 8192 MiB
  VRAM census), same selectors. RADV Polaris exposes no stable device
  UUID; the candidate is bound by BDF + PCI ID + Vulkan device name.
- Exclusion rule (sequential arms): during arm B the RX 580 must stay at
  idle/noise-floor residency; during arm C the RTX 3060 must (≤ 8 MiB
  over idle baseline in every retained placement record).
- Host: 125 GiB RAM, model bytes at `/srv/models/qwen38-ud-iq1-s`
  (three-member UD-IQ1_S set, per-member sha256 equal to the accepted
  v1 manifest — verified by the Phase 1 census before any execution).
- Model/runtime: EXACTLY the accepted #237 subject — llama.cpp pin
  `b29c606e28a01b1bc8c1351026a0fa6e616bf6c4`, Vulkan-only build flags
  (GGML_CUDA=OFF, baseline CPU intrinsics), the exact frozen request
  contract (greedy, temperature 0, top_k 1, seed 0, n_predict 8,
  cache_prompt false), ctx-size 8192, batch-size 512.

NOTE on reference continuity: the remaining RTX 3060 (GPU-d5c05739) is
a DIFFERENT physical card from R8-H's reference arm (GPU-1fc28f83,
since removed). R8-H arm-B outputs are therefore DIAGNOSTIC-ONLY for
this campaign; comparator/2 reference rows are established prospectively
by this campaign's own reference arm.

## 3. Phase 1 — fresh same-host precheck (physical, dormant)

Read-only census (CPU/RAM/PCIe ancestry and links/BDFs/UUIDs/ICDs/
driver identities/RAM/page-cache/model backing/PSU-power-thermal
sensor availability) validated mechanically against this frozen
methodology by `scripts/issue241_census.py`; fail closed on ANY drift.
Bounded historical-fixture runs then retain thermal/power/driver
health. No predictive corpus execution. CUDA excluded from both arms;
no silent CPU-only or wrong-device fallback (device-side buffer-type
demotion is a rung invalidation; CPU-side Vulkan_Host lines are the
expected host-mapped pipeline).

## 4. Phase 2 — prospective matched placement ladder (physical, dormant)

Reserve policy (frozen BEFORE any rung): candidate census 8192 MiB −
1536 MiB runtime/Vulkan reserve = 6656 MiB model-tensor budget.
Ladder = pure arithmetic on the metadata-derived placement law
(model buffer(ngl) = (ngl−1)·875.04 + 393.43 MiB): rungs (1, 2, 4, 6, 8);
ngl=8 is the mechanical budget maximum. Performance observations and
candidate-vs-reference numerical agreement NEVER enter the derivation
or selection. Both arms run at the SAME ngl (the reference at the
candidate's exact offloaded-layer count despite its 12 GB). Selection =
largest rung valid on BOTH arms (startup, no alloc failure, no
device-side fallback, placement matches requested ngl, excluded device
within noise, no OOM). No silent fallback/OOM-adjusted placement
accepted. Because both arms share the high-RAM host and page cache,
repeated inference must not devolve into page thrash; persistent
physical model reads trigger diagnosis before proceeding.

## 5. Phase 3 — comparator/2 historical-only validation (physical, dormant)

`inferswarm.qwen38-vulkan-comparator/2` — physical semantics of real
stateful generation:

- Reference arm, ONE continuous request per case: consume frozen prompt;
  capture untouched full-vocabulary FP32 consumer row at decision d
  (R8-I3 hook, capture-before-force source order); the sampled greedy
  winner IS the reference winner; append to live state; repeat through
  8 decisions.
- Candidate arm, ONE continuous request per case: identical prompt;
  capture untouched row at decision d; record candidate winner; AFTER
  row capture force/append the REFERENCE token for decision d
  (`LLAMA_OBSERVE_FORCE`); continue live state to d+1; repeat through 8
  decisions. Every acceptance-bearing decision is evaluated on the same
  reference token prefix while recurrent/internal state evolves
  continuously per the candidate implementation.
- Exact source-order proof that row capture precedes reference-token
  forcing: `scripts/issue241_observer_patch.py::validate_capture_force_order`
  + committed patched-source hash.

Historical-only validation on the excluded R8-B fixture ladder (sha256
`419bde66…`, cases case-256/1024/3072/4096) must prove: exactly 8
reference and 8 candidate rows per case; exact reference prefix identity
at every decision (candidate forced sequence == reference winners); no
candidate token can enter a later acceptance-bearing prefix;
deterministic repeat rows per arm; complete full-vocabulary finite FP32
captures; exact device/backend/process attribution; observer inert when
disabled (disabled-hook tokens equal canonical no-hook tokens); no
CUDA/fallback/wrong-device participation. v1-vs-v2 row differences are
retained as DIAGNOSTIC evidence only — byte equality between comparator
versions is NOT required and NOT claimed. comparator/2 supersedes the
v1 independent-prefill physical observation semantics for future R8-J
predictive execution IF the maintainer accepts it.

## 6. Phase 4 — practicality projection (reducer, dormant)

Projection inputs are MEASURED wall times (historical fixtures at the
selected matched placement, comparator/2 one-request semantics), never
nominal arithmetic. Frozen population counts: ~256:338, ~1024:366,
~3072:363, ~4096:349 (1416 draws) + 8 selected-stress. Project
reference total, RX580 candidate total, selected-stress total
(worst-regime bound), sequential total, low/central/high (±25%
projection spread, labeled ESTIMATED). One disposition from the frozen
vocabulary: `R8I3_RX580_COMPARATOR_V2_PRACTICAL` (identities valid,
placement stable, comparator/2 deterministic, projected candidate
Phase A ≤ ~24 h central, no unresolved blocker, predictive/holdout
authority uncontaminated), `R8I3_RX580_INFRASTRUCTURE_BLOCKED`,
`R8I3_RX580_RUNTIME_BLOCKED`, `R8I3_COMPARATOR_V2_BLOCKED`.

## 7. Phase 5 — versioned methodology correction (dormant)

Only after a valid prospective subject exists: additive v2 area; the
accepted #237 v1 area is never edited (byte-preservation mechanically
verified). Superseded: V340L/inferswarm02 candidate applicability for
the FIRST practical workhorse comparator; fixed R8-H-derived ngl=1
geometry; independent-prefill comparator/1 physical semantics;
downstream physical applicability identities. Preserved: statistical
construction (M=3, H=24, alpha=0.05, N=1416), calibration population,
holdout population, acceptance-family definitions (any family-identity
change forced by comparator/2 semantics is maintainer-adjudicated,
never auto-applied), decision-stability theorem structure, exact model
bytes, historical exclusions, sealed holdout bytes subject to the
applicability-binding check. The committed seal
(`contract_id` string and ciphertext sha256 `3786bfcd…`) mechanically
carries NO superseded identity marker; the v1-area applicability
manifests that DO carry them
stay frozen as accepted v1 history and are surfaced ADVISORILY. If any
committed applicability key is found to mechanically include the
superseded V340L identity or comparator/1 such that reuse is invalid,
STOP before resealing/replacing anything and request maintainer
exact-head review; never manufacture a new holdout.

## 8. Evidence discipline

- Historical excluded fixtures only; predictive namespaces (c237-/h237-/
  p237-) are rejected at corpus-load time by every producer.
- Zero selected-stress candidate output use.
- Zero holdout plaintext/decryption/secret access.
- Accepted historical evidence directories are never edited.
- Full-vocab FP32 rows retained on the evidence host; sha256 ledgers
  retained in-repo.
- Candidate-vs-reference numerical agreement is NEVER a placement
  selection criterion.
- Every physical producer requires the exact-head maintainer dispatch
  (`scripts/issue241_dispatch.py`: open PR, open issue #241, current
  OWNER/MEMBER approval naming `R8I3 PHYSICAL DISPATCH #241` and
  `head=<sha>` on the exact clean producer HEAD) and a clean worktree.
  The committed bounded execution path is
  `scripts/issue241_physical.py` (`run_phase1`/`run_phase2`/
  `run_phase3`); each entrypoint invokes the dispatch validation
  BEFORE loading historical fixture content for execution, probing or
  initializing Vulkan/CUDA devices, building or starting the
  qualification server, reading model bytes for model execution, or
  running vulkaninfo, GPU telemetry, placement/model probes, or model
  inference — structurally proven by the dispatch/order tests in
  `tests/test_issue241_r8i3_rx580.py`. Any head movement invalidates
  the authorization.
- If the hardware swap produces unresolved PCI resource, power, cooling,
  or driver conflicts, STOP before model execution and report the exact
  blocker (`R8I3_RX580_INFRASTRUCTURE_BLOCKED`).

## 9. Explicit non-claims

- No physical result of any kind is claimed in this slice.
- No live VRAM headroom, placement, wall-time, or stability claim.
- No comparator/2 acceptance claim — only its prospective frozen
  semantics and validation contract.
- No RX 470 equivalence claim (a later narrowly scoped child issue
  owns portability).
- No dual-GPU concurrent execution claim; arms are strictly sequential.

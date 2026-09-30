# METHODOLOGY AMENDMENT 004 — Issue #250 Arm-C terminal authority

Dated: 2026-09-27. Repository-only correction on PR #251; no new physical
execution, inference, holdout access, dispatch, or merge is authorized here.
This records the Issue #250 maintainer's V0 amendment (comment
5857136762): the amended issue body makes V0 the first physical discriminator.
That issue amendment does not itself review this PR head or dispatch work.
The frozen `METHODOLOGY.md` and amendments 001–003 remain verbatim historical
records. This amendment supersedes the CPU-first sequencing assumption and
**only** AMENDMENT-003's Arm-C claim that five identical C1 `-t 4 -tb 4`
rows suffice for `R8I3B_REFERENCE_RUNTIME_BOUNDARY_LOCALIZED` and its
restriction that C2 is available only after variable C1. A–D remain
fallback methodology. Other prospective cost, timeout, evidence-generation,
and Arm-D rules retain their own authority.

## Reason for correction

Issue #250 §C expressly requires comparison between accepted/default CPU
threading and a *mechanically proven serial/single-thread reference regime
covering prompt prefill and first generation*. Its terminal interpretation
localizes CPU parallel execution/order only when default varies **and serial
is deterministic**; when serial also varies, §D is next. The four-thread C1
regime is materially reduced but is not serial. AMENDMENT-003 §3 incorrectly
allowed a C1-deterministic/default-variable result to terminate as LOCALIZED
while recording `single_thread_tested=False`. That conclusion exceeded the
issue's evidence authority, not merely its label or level of confidence.

## V0-first ordering and fallback boundary

Maintainer Issue #250 comment `5857136762` and the amended issue body add
V0 after pass 6; they supersede only the previous assumption that CPU Arm A
must run first. The exact prospective AMD pair is
`d250-arm-v0-amd` / `V0-amd-vulkan-concordance`. Use the accepted case-3072
model bytes, prompt bytes/token IDs, request semantics and pinned llama.cpp
build family, with a validated full-row observation seam and AMD Vulkan
backend. At `ngl=1`, prove CPU input embedding and Vulkan-resident output
projection; a placement mismatch invalidates V0. Do not change thread, NUMA,
affinity or scheduling controls. Each AMD unit runs in a fresh process.

First compare two *complete* decision-0 full-vocabulary FP32 rows byte-for-byte
(canonical SHA-256); winner/token/text equality has no authority. The first
mismatch ends the AMD population as VARIABLE. If the first pair agrees, run
exactly one third fresh unit: only three identical rows qualify as a
repeat-stable *screen*, never deterministic terminal proof. Consume the two
accepted retained #248 NVIDIA `ngl=1` rows first: bind PR #249 result head
`a2cf9f33d1a056f2eef062b4186c078262e66f63`, accepted terminal
`R8I3_REF_NONDETERMINISM_UNRESOLVED`, adjudication comment `5838156612`,
external 534-row SHA256SUMS self-digest
`af9dfd0f08e9d3c4cbeb8fe164f781bc64b488ad4aba23954f5893ac980ab3bc`,
and the exact placement-rungs units `case-3072-B-ngl1-001` and `-002`.
Their decision-0 rows are each 993,280 bytes, SHA-256 respectively
`dff2499b64045f68d1349a363ee5bc888f3f9640c658252778d106fe80715499`
and `e369c8cb4ec5145f5ff855c0e29a1566795549126a4e135aaff5e94e8ce78ee6`.
Bind each raw row to its accepted unit/manifest/attestation and frozen
model, prompt, request, build and `ngl=1` placement; reject unavailable,
truncated, mutated, foreign or ambiguous records rather than supplying a
hand-authored digest list. Do not rerun NVIDIA to reconfirm historical
variability. An optional current-window NVIDIA leg needs its *own* future
exact-head dispatch if later requested.

V0 is a machine-readable non-terminal gate ahead of A:

- AMD VARIABLE (first two rows differ): A becomes the *next eligible*
  discriminator, not an automatic launch. A needs its own fresh exact-head
  maintainer dispatch and live two-pass validation.
- AMD identical pair: third unit required; neither concordance nor A is
  reachable from the pair alone.
- Three identical AMD rows matching at least one accepted retained NVIDIA
  full row: exact-row cross-vendor concordance; STOP, BLOCKED for maintainer
  review before A. Prefer a narrower NVIDIA driver/device/runtime discriminator.
- Three identical AMD rows matching neither accepted row: disagreement;
  STOP, BLOCKED before A. Do not make either vendor numerically authoritative.
- If a separately dispatched current NVIDIA population and AMD repeatedly
  agree: stronger current-window concordance; STOP before CPU and reconcile
  build/device/driver/runtime drift without overwriting accepted #248 variation.
- Any identity, provenance, placement, request, model, prompt, build or seam
  failure: INVALID/INCOMPLETE, BLOCKED; no concordance inference and no A.

The AMD binary/selector and per-tensor placement observer are not yet
independently attested on the pinned build. The prospective V0 producer
therefore fails closed before process launch even if a dispatch appears;
mock-backed unit tests do not certify a runnable AMD adapter. A further
reviewed exact-head correction must validate and wire that adapter before
physical V0 execution. Do not represent this repository-only screen as an
already-executable measurement.

V0 cannot emit either Issue #250 terminal, qualify either GPU, promote AMD or
NVIDIA to reference authority, alter comparator/2 acceptance, rewrite #248,
or trigger physical work by itself. V0's stop law comes from the amended issue
body and this prospective amendment, not historical `METHODOLOGY.md` (which
predates V0). The existing A–D methods, gates and stop laws remain fallback.
The prior physical dispatch comment `5852485456` is bound to an older head
and cannot authorize V0 or any fallback at a moved head. Separate prospective
cost admission, sequential reachability and dispatch are conjunctive, never
interchangeable.

## Corrected prospective Arm-C sequence (fallback only)

The following Arm-C correction applies only if V0's stop law and a fresh
maintainer decision leave the existing A–D fallback reachable. It does not
authorize that work or bypass the exact-head dispatch requirement.

1. Keep C1 as the frozen bounded intermediate `-t 4 -tb 4` diagnostic:
   retain its full five-identical deterministic proof or first-mismatch
   variable prefix, with the existing CPU-only semantics. Neither completed
   C1 verdict alone can close §C or reach §D. If C1 is incomplete, BLOCKED.
2. With either completed C1 verdict (deterministic **or** variable), absent
   serial C2 evidence means `R8I3B_REDUCER_BLOCKED_INCOMPLETE` and no
   terminal. Retain the C1 verdict and explicit C2 gate/execution status.
   Never issue LOCALIZED for a four-thread-only boundary or UNRESOLVED on
   a missing mandatory serial comparison.
3. C2 remains a separate, expensive, **non-automatic** `-t 1 -tb 1`
   discriminator. It requires a fresh maintainer exact-head dispatch scoped
   precisely to `d250-arm-c2` / `C2-serial` with the literal
   `c2-serial-gate: authorized-for-serial-deep-probe` line and a retained
   `c1-completed-c2-gate.json` record (schema
   `inferswarm.issue250.c1-completed-c2-gate/1`) at the new evidence root.
   The record binds `head_sha`, `c1_completed: true`, `c1_verdict` (exactly
   `deterministic` or `variable`), and the separate C1 and C2 dispatch
   authority digests. Verify the C1 verdict against retained full-row
   receipts and both digests against their *live* exact-head authorities
   before C2 launch/reduction. The older
   `c1-varied-c2-gate.json` shape grants no current C2 authority.
4. Only a completed, separately authorized C2 population may settle §C.
   Default varies + C2 serial deterministic (five identical rows) can
   LOCALIZE the exact default-vs-serial CPU execution boundary, without
   asserting a deeper root cause. If C2 serial also varies (valid
   first-mismatch prefix), §D becomes reachable. A missing/invalid C2
   population remains BLOCKED. No C1 outcome authorizes C2 by itself;
   generic C or C1 namespace dispatch never authorizes serial work.

## Producer cost authority and retained-record binding

The pass-6 prospective planning record is now a producer precondition, not a
report-only calculation. Each fresh-process unit and the Arm-B same-process
lifecycle derives its cost condition from its frozen arm/unit plan, loads
`cost-planning-record.json` from the canonical evidence generation, and
checks the complete record against an independently recomputed frozen
projection before any physical runner/server launch. The producer does not
accept caller-supplied costs or rates. Its canonical SHA-256 binds the entire
record except the digest field itself, including generation, source identity,
all condition entries and dispositions, numeric rates, unit counts and
estimated costs, and campaign ceiling. A matching recomputed digest alone is
not sufficient: even a re-signed mutation must differ from the independent
frozen derivation and fail closed. The HTTP timeout is a distinct safety
bound, never a cost authorization. Conditional B and D admission does not
create sequential reachability or dispatch authority; those gates remain
separate. C2 exceeds the automatic ceiling and may launch only with its
own validated exact-head maintainer authorization and retained C1 proof.

For AMD V0, retain a separate prospective Vulkan cost/timeout condition in
the same generation-bound canonical planning record. A retained NVIDIA
`ngl=1` rate (if used) is a conservative planning *proxy*, not a measured AMD
rate or a conclusion about AMD throughput. Authenticate the complete cost
record before each V0 launch, including the conditional third unit. This
neither waives V0's independent dispatch nor turns cost admission into
sequential reachability.

The signed C2 gate is not a terminal and does not authorize physical work
without independent maintainer dispatch. Exact dispatch is required for every
new physical leg, including V0 and any subsequently selected A–D fallback;
neither this amendment nor the V0 issue-body change dispatches work. Cost
authorization is separate from dispatch, and timeout bounds do not grant
spend authority. AMD repeat stability is only the V0 2-then-3 screen; it does
not replace the five-identical-row deterministic law for terminal conditions.
No AMD-specific inference may generalize beyond the observed device/runtime
population; retain the V0 population and stop law as written, without
post-hoc expansion. Neither accepted #241/#248 evidence nor the failed v1
#250 evidence is reinterpreted.
The four-thread finding remains useful retained context, not the terminal
boundary the issue asked for. No thresholds, comparator methodology,
case-4096, predictive work, or Arm-D predicate is changed.

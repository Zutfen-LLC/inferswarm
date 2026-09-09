# Issue #129 — Arm-C retry methodology remediation — frozen methodology

Status: FROZEN BEFORE ANY FUTURE ARM-C PHYSICAL RETRY.

This document freezes the corrected Arm-C retry methodology required by
issue #129 after the accepted #128 blocker
(`ISSUE117_ARM_C_EVIDENCE_BLOCKER`, merge
`718efbf5770b31c6e44eb3a8c4d0b81fd1dc9c22`). It authorizes and proves
CPU-only methodology readiness. It does NOT authorize any physical
execution, and it produces no ordinary-serving PASS or FAIL.

## 0. Authority and identities

- Accepted InferSwarm main after PR #128: `718efbf5770b31c6e44eb3a8c4d0b81fd1dc9c22`.
- Accepted Arm-B result: `ISSUE117_ARM_B_COLD_REALIZATION_PASS`, merge
  `fed87d1b71a0794374dd58c921e31606a56a242f`.
- Accepted Arm-C blocker: `ISSUE117_ARM_C_EVIDENCE_BLOCKER` (PR #128).
- Frozen FreeToken producer (every control-plane byte this methodology
  imports): `924cd22ea081f6d4ed471016faf01d427fc5b0d2`.
- Checkpoint authority:
  `5a84cb313260ac447237b890387116dfa8682e49a6b44bc585ae8353abbff18d`.
- Accepted qualification subject:
  `sha256:c6b9fe721103fb041be3a5b980e73ee148f2304c8572bc50e971f7f1d7994ffd`.
- Candidate `dense.6171f32b4413`; geometry `01/gpu-0 [0,16)`,
  `01/gpu-1 [16,32)`, `03/gpu-0 [32,48)`; Coordinator `inferswarm00`.
- Public fixture: exactly 24 `c109-*` cases, digest
  `sha256:180185cd5c6a5dcd77b2c65979bd2c9aef4d1c7ea9fb4850a64f4508b2ba36f2`.
  No `h109-*` material exists or may be created.

### 0.1 Additive history (Finding 1 of the #129 review)

The accepted #128 blocker evidence under `evidence/arm-c/` — including
`pre-execution-authority-audit.json` and `blocker-reduction.json` — is
immutable historical authority: it is never modified, re-derived, or
re-classified at later heads. A byte-preservation regression proves
every evidence path that existed under `evidence/arm-c/` at the
accepted merge remains byte-exact in the working tree. The accepted
#128 blocker reducer runs only in its historical-verification mode
(`reduce_all(head=…)` pinned to the accepted merge); the live head is
never re-classified. All #129 authority, integrity pins, and derived
methodology outputs live additively under `evidence/arm-c-retry/`
(`authority.json`, `integrity.json`, `prompt-fixture.json`,
`methodology-run.json`).

## 1. Why: the accepted frozen defect

The accepted #128 blocker established that the frozen Arm-C campaign did
not isolate the control plane:

- frozen direct comparator: one single-shot
  `generate(..., max_new_tokens=8)` per case;
- frozen ordinary path: `EpochServingController.serve_tokens`
  replay-prefix loop — one runtime call per committed position with
  `max_new_tokens=2`, commit step zero only, speculative second token
  discarded.

The arms therefore differed in runtime invocation semantics in addition
to control-plane routing. The retained 18/24 comparison and six
regime-4 divergences remain diagnostic evidence only; nothing in this
methodology is tuned against them.

## 2. Corrected comparator invocation contract (frozen)

The retry direct comparator must mechanically reproduce the ordinary
controller's runtime invocation contract. For each committed position:

1. derive replay input as `prompt_token_ids + committed_generated_token_ids`;
2. invoke the same integrated runtime with `max_new_tokens=2` (and the
   same `on_token` commit-capture contract);
3. commit only generated step/token zero;
4. treat the second generated token as speculative/uncommitted and
   discard it;
5. repeat until 8 tokens are committed;
6. allocate the runtime `session_id` exactly as the frozen controller
   does — through the allocation MECHANICALLY EXTRACTED from the
   sha256-pinned `r5b_epochs.py` bytes
   (`EpochServingController._runtime_session_id`:
   `logical_session_id * 1_000_000 + global call sequence`, one global
   sequence across all cases in ordinary order). The comparator never
   re-codes the formula by hand, and no value passed to `generate()`
   is ever treated as "outside the runtime invocation".

A single-shot `max_new_tokens=8` direct comparator is prohibited (frozen
negative control `single_shot_8`), as is any session-allocation change
with everything else identical (frozen negative control
`session_sequence_shift`).

## 3. CPU-only transcript-equivalence proof (the gate this issue runs)

Both arms run on a recording/fake runtime over all 24 frozen cases, on
CPU, with no model bytes and no GPU:

- ORDINARY arm: starts at the actual frozen ordinary request ingress
  (§3.1) and continues through the REAL frozen control-plane bytes
  retained verbatim under `evidence/arm-c/frozen-freetoken/924cd22e/` —
  `freetoken.research.r3_planner` (generic planner),
  `freetoken.research.r5a_serving` (plan freeze + realization
  reconciliation), `freetoken.research.r5b_epochs`
  (`EpochServingController.serve_tokens`), and the R6 dense strategy
  adapters (`benchmarks.inferswarm_r6.{strategy,xc_strategy}`). The
  controller plans automatically (`AUTOMATIC_PLANNER_SELECTION` over the
  accepted campaign's single context-exact MEASURED ranking record,
  reconstructed verbatim from the retained accepted coordinator-report
  evidence audit), freezes a real execution plan, realizes it through a
  realizer whose observation is reconciled by the REAL frozen
  reconciliation machinery, and serves every case through the real
  `serve_tokens` loop.
- DIRECT arm: an independently coded comparator implementing §2. The
  direct arm may consume the frozen rendered prompt ids directly.

Both arms share one deterministic fake model response function seeded
from the frozen fixture bytes, so equivalence is a property of the two
control-plane paths, not of model outputs.

The recorded per-call transcript (the exact generate() argument set and
values) must be exactly equal across arms for every case: case identity;
logical session mapping; call count and position; the COMPLETE
generate() keyword values — runtime `session_id` (it is part of the
model-execution invocation; the ordinary controller allocates a fresh
runtime session identity for every replay call and the comparator
reproduces exactly that sequence), prompt/replay token ids;
`max_new_tokens`; `on_token` presence (the commit-capture contract);
the exact generate-argument name set; response commit token;
speculative discarded token; stopping semantics (length-only at 8);
sampling inputs (greedy temperature 0.0 / top_k −1 / top_p 1.0);
candidate/plan semantics (same candidate id, same mapping, both plans
compiled by the real frozen machinery).

Genuinely control-plane-only fields — `epoch_id`, `generation`,
`realization_id`, the plan-digest VALUE, `logical_session_id`
numbering, wall-clock stamps — may differ by construction and are
enumerated explicitly; the recording runtime captures the exact
generate() keyword set per call and the reducer requires it to equal
the frozen contract on both arms, proving those fields sit outside
the runtime-invocation argument set. No argument value that reaches
`generate()` is excluded from the comparison; nothing is claimed
"semantically ignorable".

PASS only if all 24 cases have exact runtime-call transcript
equivalence. The reducer never consults stored `equal` flags or terminal
strings (frozen negative control).

### 3.1 Ordinary Coordinator ingress/tokenizer seam (frozen)

The ordinary arm does NOT begin at `serve_tokens`. The frozen R6
ordinary path is `R6CoordinatorRuntime.handle_chat(body)`, which calls
the Coordinator's render/tokenize seam first. The CPU proof:

1. reconstructs the exact ordinary request body per case (single user
   message carrying the frozen `prompt_text`, `max_tokens=8`,
   `temperature=0.0`) and verifies it byte-equal against the retained
   accepted `evidence/arm-c/ordinary-http/ordinary-*.json` records;
2. executes `_render_and_tokenize` and `_sampling_of` VERBATIM —
   AST-extracted (with fail-closed structural verification and line
   citations of the `handle_chat` ingress statements: session
   allocation `len(request_log) + 1`, max-token derivation, sampling
   derivation, and the `serve_tokens(prompt_token_ids=prompt_ids, …)`
   dispatch) from the sha256-pinned `coordinator.py` bytes;
3. runs them against a pinned CPU stand-in tokenizer implementing
   exactly the `AutoTokenizer` surface the frozen seam calls: the
   chat-template wrapper (header/footer token sequences cross-derived
   from BOTH accepted campaign sides for all 24 cases, including the
   one trailing-space boundary-merge case) and the accepted per-case
   content encodings (encode fails closed on any text outside the
   pin). The real tokenizer assets are Source; their identities are
   sha256-pinned (§4) but their bytes are never read CPU-only;
4. requires the derived `prompt_token_ids` equal
   `evidence/arm-c-retry/prompt-fixture.json` exactly, 24/24;
5. feeds the DERIVED ordinary ids into the real controller
   recording-runtime path. The ordinary arm never serves fixture-file
   ids directly.

## 4. Tokenizer / Source seam (frozen, non-ambiguous)

The blocked campaign observed four tokenizer-metadata reads under
`/srv/models/`. The frozen rule for the future physical retry is the
REAL invariant — pinned non-Source tokenizer assets and zero
forbidden-root opens during the observation window — never any
assumption that `transformers` is absent (the Coordinator legitimately
uses a tokenizer):

- BEFORE the observation window: publish the exact immutable
  tokenizer/config assets the Coordinator needs —
  `chat_template.jinja`, `config.json`, `generation_config.json`,
  `tokenizer.json`, `tokenizer_config.json`, with the sha256
  identities pinned from the accepted checkpoint-authority
  provenance — to a dedicated non-Source location
  (e.g. `/srv/inferswarm/tokenizers/gemma-r6-frozen`);
- configure the Coordinator's `tokenizer_path` to that location
  (never at, or under, `/srv/models/`);
- verify the exact tokenizer asset identities before execution;
- begin the correctness-bearing observation only after this
  preparation;
- DURING the observation window: zero file opens under `/srv/models/`
  (audited mechanically by an audit-hook monitor in the CPU run; a
  simulated forbidden open downgrades the terminal to BLOCKED — frozen
  negative control).

The CPU methodology run consumes the frozen rendered ids through the
ingress seam (§3.1); decoded-output reconstruction, if a future retry
needs it, is a separate pinned CPU evidence step outside the
observation window.

## 5. Exact deployed-script identity contract (frozen)

No correctness-bearing execution from mutable/unpinned staged scripts.
Every correctness-bearing harness/driver on every host requires a
retained identity record with: repository SHA; file sha256; expected
path; read-only (or otherwise immutable) deployment identity;
pre-launch verification; post-run verification. Any correctness-bearing
script change after freeze (post-run sha256 differing from the frozen
file sha256) invalidates execution authority and requires a new
reviewed freeze. Mutable deployments, missing pins, and post-freeze
changes are rejected fail-closed (`verify_deployment_identity`).

## 6. Attempt/STOP/physical-authorization state machine (frozen, executable)

Attempt classes are decided mechanically from observed facts — never
from an authored validity label — with five concepts mechanically
separated: methodology readiness accepted
(`methodology_gate_passed`), physical retry authorization
(`physical_retry_authorized`), attempt correctness-bearing state,
deployment identity validity, and the mandatory STOP / terminal state:

- `PRE_OBSERVATION_INFRASTRUCTURE` — no correctness-bearing result or
  commit occurred;
- `CORRECTNESS_BEARING_VALID` — correctness-bearing result/commit with
  verified frozen identity (pre-launch AND post-run), accepted
  methodology readiness, physical-retry authorization, and no prior
  unresolved STOP;
- `CORRECTNESS_BEARING_INVALID` — correctness-bearing result/commit
  without any of those (mandatory STOP:
  `invalid_correctness_bearing_observation`, with the failing reason:
  identity defect / methodology readiness false / physical
  authorization false);
- `DIAGNOSTIC_ONLY_AFTER_STOP` — a disclosed diagnostic observation
  after a STOP or terminal: retained, never verdict authority, clears
  neither the STOP nor the terminal requirement;
- `TERMINAL_CAMPAIGN_ATTEMPT` — a terminal observation that IS
  correctness-bearing and fully authorized: representable,
  authoritative, and the ONLY transition that clears a mandatory STOP;
- `TERMINAL_MARKER_NON_CORRECTNESS_BEARING` — a non-correctness-bearing
  terminal marker: never clears a STOP; while a STOP is active it
  fails closed (`non_correctness_bearing_terminal_cannot_clear_stop`).

The dynamics are frozen in an explicit LEGAL_TRANSITIONS table (per
class: terminal effect, STOP-clearing effect, mandatory-STOP flag,
authoritativeness). A sequence "passes" only with no unauthorized
continuation AND no unresolved mandatory STOP: a correctness-bearing
attempt after a STOP without an intervening authorized terminal
attempt fails closed (`post_stop_continuation_without_terminal`);
authored `stop_occurred` or diagnostic labels never launder authority.
`methodology_gate_passed` is load-bearing: a correctness-bearing
attempt without accepted methodology readiness is INVALID regardless
of deployment identity.

## 7. Preserved Arm-C trust boundaries (future retry requirements)

A future physical retry must still preserve: CPU-only external
Coordinator; zero Coordinator model-weight receipt/materialization; zero
Coordinator CUDA initialization; accepted Arm-B participant state; no
model reacquisition/rematerialization; no silent plan substitution; full
fencing/session/plan/epoch/position attribution; no consumed holdout
material. This issue proves only that the methodology is sufficient to
test those claims correctly; it does not re-observe them physically.

## 8. Mandatory negative controls (all fail closed; retained in CI)

1. direct side uses `max_new_tokens=8` single-shot;
2. either side uses a different replay prefix;
3. either side changes call count;
4. either side commits the speculative second token;
5. the runtime-session ID allocation/sequence differs while replay
   ids, outputs, max tokens, and everything else stay identical;
6. sampling inputs differ;
7. prompt token ids differ;
8. stopping policy differs;
9. a control-plane-only field leaks into model execution inputs;
10. mutable/unpinned deployed driver identity is permitted;
11. a correctness-bearing script changes after freeze;
12. ordinary Coordinator rendering mismatches the frozen prompt-token
    fixture (template-wrapper drift, content-encoding drift, request-
    body drift, or unpinned content at the tokenizer seam);
13. tokenizer asset digest drift;
14. Coordinator `tokenizer_path` pointing at `/srv/models/…`;
15. a forbidden `/srv/models/` open during the (simulated) observation
    window;
16. an invalid correctness-bearing attempt continues without the frozen
    state machine authorizing it (including: correctness-bearing while
    methodology readiness is false; correctness-bearing while physical
    authorization is false; a non-correctness-bearing terminal marker
    attempting to clear a STOP; continuation after STOP without a
    separately authorized terminal campaign attempt);
17. stored `equal: true` or stored terminal strings substitute for
    derivation;
18. frozen-byte pinning degrades silently: mutated frozen sources,
    a missing or broken accepted #128 pins module, a missing inherited
    pin key, or a malformed inherited pin must all fail closed;
19. accepted #128 blocker evidence drift from the accepted merge
    (byte-preservation regression).

## 9. Terminal / acceptance

Successful terminal: `ISSUE117_ARM_C_RETRY_METHODOLOGY_READY` — CPU-only
methodology readiness, NOT physical serving success.

Retained evidence (additive; covered by the retained MANIFEST):
`evidence/arm-c-retry/prompt-fixture.json` (frozen rendered ids +
derivation provenance), `evidence/arm-c-retry/methodology-run.json`
(full reduction: complete runtime-call argument-value equality
including session ids, ordinary-ingress 24/24, tokenizer Source
contract + observation monitor, accepted-blocker byte preservation,
frozen control-plane digests, attempt-state self-checks, CPU-only
attestations), `evidence/arm-c-retry/authority.json` (authority chain,
additive-history policy, byte-preservation proof), and
`evidence/arm-c-retry/integrity.json` (frozen-byte pins, extracted
function citations, template contract, content-encoding pin,
tokenizer asset pins). The accepted `evidence/arm-c/` blocker bytes
are read-only input and are never edited.

After maintainer acceptance, Issue #117 may be updated to authorize a
new, separate Arm-C physical retry. That retry is NOT authorized by
this issue and was not executed.

## 10. Explicit non-claims

This methodology does not establish: Arm-C ordinary-serving PASS or
semantic FAIL; whether the six regime-4 divergences are a real runtime
defect; Arm-D restart/cache reuse; Arm-E locality mutation; any broader
model/vendor result. The accepted #128 blocker remains historical
truth. The CPU stand-in tokenizer's content encodings are pinned to the
accepted fixture pairs; reproducing them from the real tokenizer assets
is a requirement of the future physical retry's §4 preparation, not a
claim of this CPU proof.

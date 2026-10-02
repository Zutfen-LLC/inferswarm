# METHODOLOGY AMENDMENT — 006 (Issue #258)

Date frozen: 2026-10-02
Amends: R8-I3C terminal derivation law (Issue #252 METHODOLOGY.md §5; reducer `scripts/issue252_terminal.py`)
Authority: Issue #258, successor to #254 (PR #256 reviewed head `2dce4e1a51d466308567a3c6afeaede23fd08d4b`) and #257 finding (comment 5945632846)
Status: PROSPECTIVE. Repository-only. No physical execution authorized by this amendment.

## 1. What is amended, verbatim from the frozen text

METHODOLOGY.md §5 states the terminal vocabulary and that only the retained-byte reducer may derive a terminal. The reducer implementation additionally enforced, at PR #256 head `2dce4e1a` (`scripts/issue252_terminal.py`):

- any multi-arm retained tree must contain ALL five named arm namespaces or be refused outright ("mixed arms require independently retained authorities" applied against the complete set);
- a non-localization-family terminal (`R8I3C_VULKAN_MECHANISM_UNRESOLVED`) requires `set(states) == set(A.ARMS)` — the retained execution of every one of A1–A5;
- a deterministic contrast under a non-terminal-capable arm can reach `UNRESOLVED` only via that same complete-five-arm condition.

That complete-named-arm-set law is hereby WITHDRAWN prospectively. It is not a logical theorem: it conditions a logical verdict (non-localization) on the execution of arms that provably cannot change any terminal.

## 2. The observation that falsified it (accepted physical results, immutable)

- A3 (accepted round-7, `/home/hermes/is254-a3-round7/evidence`): physically executed, mechanism-capable, VARIABLE at unit 002 (first-mismatch stop).
- A5 (accepted round-1, `/home/hermes/is254-a5-round1/evidence`): physically executed, observationally capable, NONTERMINAL — accepted classification `A5_OBSERVATIONALLY_CAPABLE_NONTERMINAL` (#257, comment 5945632846): the control is attested live and staging authentic, but no retained observable uniquely discriminates the selected model-buffer memory type / upload path at pin b29c606e.
- A1: non-terminal-capable (no retained submission-serialization observable at the pin).
- A2: dead control on the frozen RTX 3060 / `NV_coopmat2` subject (the KHR-only disable does not remove the subject's selected coopmat2 family).
- A4: non-terminal-capable (no retained observable binds an allocation line to the `prefer_host_memory` branch).

Therefore no assignment of retained states over A1/A2/A4/A5 — executed or not — can alter any terminal: executing them cannot produce localization (incapable of the mechanism law) and their execution is not needed to establish non-localization (they are not terminal-capable discriminators for any frozen hypothesis class). The old law's demand that they run before any non-localization-family terminal is a completion-count requirement, not a coverage requirement.

## 3. Replacement terminal theorem (exact)

Terminal capability is mechanically explicit per arm (`scripts/issue258_theorem.py:TERMINAL_CAPABLE` with `CAPABILITY_REASON`; tests pin both). Let `capable(X)` denote that frozen fact. Terminal T is derived as:

1. **LOCALIZED** — `R8I3C_VULKAN_MECHANISM_LOCALIZED_FIX_NOT_VALIDATED` (and `_FIX_VALIDATED` with a separately dispatched bound fix, unchanged): some arm X with `capable(X)` has a valid deterministic retained population AND X's frozen mechanism contract holds on the retained bytes. Determinism contrast alone, under any arm, never localizes.
2. **NON_LOCALIZED** — `R8I3C_VULKAN_MECHANISM_NON_LOCALIZED` (new string): every frozen hypothesis class whose `discriminator_arm` is not None is covered by at least one terminal-capable arm, every terminal-capable arm has an admissible retained population, and every such population is variable.
3. **UNRESOLVED** — `R8I3C_VULKAN_MECHANISM_UNRESOLVED` (unchanged string): admissible retained evidence exists but clause 2's coverage precondition fails, or no capable arm produced an admissible population, or only nonterminal arms executed.

Old strings `LOCALIZED_FIX_VALIDATED`, `LOCALIZED_FIX_NOT_VALIDATED`, `UNRESOLVED` keep their exact semantics and remain the localization/unresolved vocabulary. `NON_LOCALIZED` is new and carries clause 2's exact meaning. No workflow-progress labels are introduced.

## 4. Required arm set under the new theorem

**Correction (round 2, 2026-10-02):** this section originally stated "the required PHYSICAL arm set for terminal closure is **{A3}**", conflating the per-arm terminal-capability inventory with closure sufficiency. Corrected statement:

At the current frozen pin/subject, terminal closure is **NOT possible**: hypothesis coverage is provably incomplete (H2→A1 nonterminal, H3→A4/A5 nonterminal, H5→A2 dead-control), so NON_LOCALIZED is unreachable regardless of which existing arms execute, and the theorem's machine-readable required-arm API fails closed to the empty set (`issue258_theorem.required_arms() == []`, `terminal_closure()["closure_possible"] is False`). The existing terminal-capable arm inventory is **{A3}** (`terminal_capable_arms() == ["A3"]`) — a per-arm capability fact, NOT a closure set; A3's execution alone cannot close NON_LOCALIZED at this pin. A3's accepted physical result (variable) remains retained and consumable unchanged for both its determinism contrast and its mechanism fact (its mechanism law's retained observables are unchanged by this amendment). The honest current terminal for an admissible all-variable state — including the accepted A3+A5 state — is **UNRESOLVED**.

Arms removed from any terminal requirement: **A1, A2, A4, A5**. A1/A4/A5 are non-terminal-capable at this pin; A2 is a dead control on this subject. Executing them under unchanged instrumentation produces no information capable of changing any terminal. Their physical execution remains permitted only as separately dispatched negative-control/diagnostic facts, never as terminal-closure requirements.

## 5. Evidence reuse / rerun law

- **A3 (`is254-a3-round7`)**: reusable UNCHANGED for its determinism-contrast fact (variable at unit 002) AND for mechanism authority (exact async-disabled line + producer-attested placement per AMENDMENT-005 — those retained observables are exactly this amendment's mechanism law). No rerun required by this amendment. A rerun would be required only if A3's frozen mechanism law itself changed observables (not done here).
- **A5 (`is254-a5-round1`)**: reusable ONLY for its physical-variability fact and its #257-established supporting facts (control-live attestation, authentic staging activity, flag-live). It is NOT promotable to terminal mechanism authority under this amendment: #257 established no retained unique discriminator exists at this pin. A5 requires a fresh physically executed run under NEW instrumentation (see §6) before it may count toward NON_LOCALIZED coverage — that run requires its own exact-head freeze and maintainer dispatch.
- No retrospective reinterpretation of any accepted physical data occurs. Both roots keep their exact original meaning; both reducer-level results (BLOCKED_INCOMPLETE for the single-arm roots under the OLD law) remain historical facts. The new reducer re-derives terminals from the same retained bytes under the new theorem; it does not rewrite them.

## 6. Instrumentation prerequisite (prospective design, not implemented here)

The observation gaps #257 established are recorded in `scripts/issue258_theorem.py` and its committed matrix output (§ capability matrix + gaps). To reopen NON_LOCALIZED coverage for H2/H3/H5-class mechanisms, prospective instrumentation must make at least one currently-nonterminal arm terminal-capable by retaining a unique discriminator, e.g. (design candidates from the pinned source, NONE committed):

- the exact selected memory-property flags / memory-type index for the model buffer, emitted at `ggml_vk_create_buffer`'s selection point;
- an explicit branch/path identifier emitted at the `disable_host_visible_vidmem` / `prefer_host_memory` decision points;
- the staging-buffer owner/lifecycle identifier (device-owned vs context-owned).

Any such instrumentation is a llama.cpp source change: it changes the source identity of any future physical run, must be frozen as a new exact pin with its own dated amendment and adversarial review (why the observable uniquely distinguishes the mechanism, why baseline cannot emit it, mutation/adversarial law, inertness when disabled), and REQUIRES fresh runs — historical A3/A5 results do not transfer mechanism authority to an instrumented build. Implementing it is a separate narrow implementation child issue (STOP condition satisfied here by design: comparator identity, statistical family, and request contract are untouched by this amendment).

## 7. Implementation record

- `scripts/issue258_theorem.py` — frozen capability law + coverage derivation (this amendment's machine-readable form; round-2 correction: the closure API (`terminal_capable_arms()` / `terminal_closure()` / fail-closed `required_arms()`) mechanically separates the terminal-capable inventory ({A3}) from closure sufficiency (not possible at this pin; required-arm set is empty while H2/H3/H5 coverage gaps remain).
- `scripts/issue252_terminal.py` — reducer updated to derive terminals under this theorem (capability-explicit admission; UNRESOLVED on coverage failure; nonterminal arms never required for completion and never granted terminal authority).
- `scripts/issue252_mechanism.py` — `_mechanism_a5` withdrawn from the admissible localization validators (retained verbatim as the falsified prospective law #257 refuted; `mechanism_status` classifies A5 nonterminal via the theorem module). **Correction round 3 (#258 review):** custody/observation validation is now keyed by its own registry, `RETAINED_OBSERVATION_LAWS` (A2/A3/A5 — every arm with a frozen retained-observation law), consumed through the public `retained_observation_status()` boundary. This is mechanically independent of the localization-capability registries (`MECHANISM_VALIDATORS`, `issue258_theorem.TERMINAL_CAPABLE`): A5 remains nonterminal with zero localization authority, but retained A5 evidence in a `derive_terminal()` reduction is still held to its frozen observation law (malformed retained A5 evidence fails closed to BLOCKED; it can never again ride through the reducer unvalidated merely because A5 lost localization capability).
- Tests: `tests/test_issue258_theorem.py` (RED suite at head `2dce4e1a`, GREEN at the corrected head), plus updated pins in `tests/test_issue252_terminal.py` and `tests/test_issue254_round7.py` (old-law anchors superseded by the new theorem; every updated pin documented).

Ancestry: this amendment descends from PR #256 head `2dce4e1a51d466308567a3c6afeaede23fd08d4b` (itself descended from `origin/main` `ac9db62d15f21fdc7dd7a04253589f4b9e9ca489`), precedes any further R8-I3C physical execution, and grants no dispatch authority.

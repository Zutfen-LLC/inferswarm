# Phase-1 campaign-order amendment

```
Status: Binding Phase-1 methodology amendment
Frozen before any canonical Phase-1 candidate performance existed.
Supersedes for §10 ordering only: the repetition-level A/B/A/B interleaving rule
in docs/phase1-poc-success-criteria.md §10 ("Sessions and ordering") and the
contemporaneous-pairing reading of §8.7.
Related issues: #4 and #5
```

## What changes

§10 of the success criteria currently requires the two Phase-1 arms to be
ordered as `A/B/A/B…` at **repetition level** within Session 1. That rule is
superseded, before any candidate performance exists, by an executable
**counterbalanced arm-major crossover**:

- **Session 1** begins from a fresh thermal-reset state and runs
  `CANONICAL_PERFORMANCE_BASELINE` first, then `PHASE1_CANDIDATE`.
- **Session 2** begins from an independent thermal-reset state and reverses the
  arm order: `PHASE1_CANDIDATE` first, then `CANONICAL_PERFORMANCE_BASELINE`.

Within every arm/server process the workload-class order is `W1 → W2 → W3 → W4`
in both sessions, with 2 discarded warmups and 10 measured generations per
class. One fresh server process is started per arm per session; the server is
not restarted between workload classes, and the radix cache is not cleared
between workload classes, so each arm preserves its natural warmed serving
history exactly as §10's warmup rules intend.

The workload-class order is **not** reversed between sessions. Reversal applies
only to the arm order.

## The original rule and what it intended

The original §10 language is preserved verbatim:

> **Sessions and ordering.** Two full sessions. Session 1 interleaves
> `A/B/A/B…`; session 2 runs on a different day and thermal state with the
> order reversed. Interleaving keeps thermal drift symmetric between arms
> rather than assigned to whichever arm ran second.

The intent of that rule is unchanged and remains binding: **thermal and host
load drift must not be assigned to whichever arm runs second.** The amendment
replaces only the mechanism used to pursue that intent.

## Why repetition-level interleaving is not executable on the canonical rig

The two Phase-1 arms cannot be interleaved at repetition level without
changing the experiment being measured:

1. `CANONICAL_PERFORMANCE_BASELINE` (B1) is a single-GPU-0 configuration.
2. `PHASE1_CANDIDATE` requires the **same physical GPU 0** plus the secondary
   GPU 1.
3. Two independently loaded `ft serve` processes cannot simultaneously own the
   same 12-GB GPU 0.
4. The only repetition-level alternatives are concurrent residency (impossible
   per 3) or restarting/reloading a server between individual measured
   repetitions — which destroys the warmed expert-cache/radix-cache serving
   state that §10's warmup rules exist to establish and that M-warm measures.

Arm-major ordering with counterbalanced sessions is therefore the closest
executable protocol to the original intent: neither arm systematically runs
second, and each session's arm starts from a comparable fresh-server,
thermal-reset state.

Silently reinterpreting "interleaved" to mean something else was not an option;
the rule is corrected in writing before candidate performance exists.

## Pre-performance firewall

At the time this amendment was frozen, none of the following existed for a
canonical Phase-1 candidate:

- candidate throughput or tokens/s;
- candidate TTFT;
- a candidate prefill-speed ratio;
- aggregate candidate speedup;
- a candidate/baseline ratio of any kind;
- a GO, ITERATE, or NO-GO performance verdict.

The only inputs to this amendment were the already-recorded Phase-0
hardware/configuration facts (GPU ownership per arm) and the already-merged
Phase-0 thermal/session rules. No Phase-1 candidate observation entered it.

## Sampling consequences

The measured repetition remains the independent sampling unit, in §10 and in
§8.7. Because repetitions of the two arms are no longer contemporaneously
interleaved, the optional within-repetition pairing of §8.7 is **structurally
unavailable** in this campaign. The already-permitted unpaired path applies:

- each arm is aggregated within each repetition;
- the bootstrap resamples repetition blocks, never expert touches;
- `(session, workload class)` boundaries are preserved;
- the report states that direct repetition pairing is unavailable.

Pairing must **not** be manufactured by matching repetition index 0 of one arm
to repetition index 0 of the other. Repetitions with equal indices did not run
under contemporaneous conditions and are not paired observations.

## Thermal and session-boundary controls

The existing Phase-0 thermal/session-reset rules are reused unchanged; no new
temperature threshold is invented for this amendment. In particular:

- Session 2 must satisfy the independent cooled/thermal-reset requirement of
  `phase0-session2-thermal-state-amendment.md`;
- before **each** arm, the campaign records GPU temperatures, GPU clocks, GPU
  power state, host load, and relevant background-process/load observations;
- a session boundary is a validated thermal reset, not an elapsed-wall-time
  assumption.

## Baseline identity

This amendment does not reopen baseline selection. The historical Phase-0
result stands:

```
CANONICAL_PERFORMANCE_BASELINE = B1
```

with the resolved B1 configuration already frozen in §2.3 (offload backend,
auto NVFP4 resolved to Triton, auto expert cache, GPU decode, zero CPU MoE
layers, same physical GPU 0). The Phase-1 campaign **remeasures B1 on the exact
FreeToken campaign build** rather than dividing candidate numbers by historical
Phase-0 numbers collected from another commit/day. This is a current-build
observation of the already-frozen B1 identity, not a new baseline selection.

### Session-1 gate and Session-2 revalidation

Baseline identity is checked at two different points with two different
consequences, because the counterbalanced order is not symmetric with respect
to when B1 resolves:

- **Session 1 B1 runtime resolution is the campaign-build baseline identity
  gate.** Session 1 runs B1 first, and that resolution must pass before the
  **first candidate measurement anywhere in the campaign** — before Session 1's
  own candidate arm runs, and before Session 2 may start at all (Session 2's
  first arm is the candidate). If Session-1 B1 no longer resolves to the
  expected legitimate configuration, the campaign stops with **no candidate
  generation collected**, and the Phase-0 baseline must be refreshed.
- **Session 2 revalidates B1 when its counterbalanced B1 arm runs.** By design
  Session 2 runs the candidate first; no preliminary B1 server is started
  before the Session-2 candidate, because that would perturb the
  candidate-first thermal/cache condition this amendment exists to preserve.
  Session 2 therefore **cannot** stop before candidate performance, and no rule
  in this amendment claims that it can.

If the Session-2 B1 revalidation then materially drifts:

1. Session 2 is `INVALID`.
2. All already-collected Session-2 candidate performance is **retained as
   invalid evidence** but excluded from every `R_c`, from `R_agg`, and from
   every verdict.
3. The baseline must be refreshed and the **complete affected campaign** is
   rerun.
4. No candidate data is reused or spliced into the rerun.

B4, hybrid, CPU, or any other arm may not be silently substituted in either
session.

## Predeclared supplementary KV-matched arm

§3 rule 2 requires a supplementary baseline run pinned to the candidate's KV
capacity whenever the two primary arms resolve different KV capacities. That
arm is **predeclared** in every canonical campaign plan before execution; a
campaign plan is not "fully specified" while a later runtime observation could
reveal that an unplanned arm is mandatory. The operator does not guess or pass
the capacity manually:

- **Arm id:** `baseline_b1_kv_matched` — the B1 identity plus
  `--num-tokens 17075`, nothing else.
- **Pinned capacity:** 17,075 tokens. The canonical candidate requests
  `--num-tokens 17075`, and the candidate's runtime contract requires its
  *resolved* KV capacity to equal 17,075 tokens, so the supplementary arm's
  configuration is fully known before any performance exists.
- **Trigger, fixed before execution:** the arm is required exactly when
  `candidate_resolved_kv_capacity != baseline_resolved_kv_capacity`, evaluated
  once both primary runtime reports exist. No performance number controls this
  branch.
- **Placement and budget:** if required, it runs after both primary arms of the
  same session, with the full 48-generation block (2 discarded warmups + 10
  measured per class, W1→W4), one fresh server process, same as every arm. If
  the capacities are equal, the arm is recorded `NOT_REQUIRED_BY_KV_RULE` and
  its generations are not executed.
- **Accounting:** required primary generations and conditional supplementary
  generations are counted separately, the condition's resolution is recorded
  (required / not required / unresolved), and a canonical session cannot be
  `COMPLETE`/`VALID` when the condition is true and the supplementary block is
  missing.
- **Status:** supplementary and non-gating. It never replaces B1 as a primary
  comparator, never enters `R_c` or `R_agg`, and never affects a verdict.

## What does not change

This amendment changes no performance decision rule and no measured-workload
parameter. The campaign still uses:

- the same pinned model revision;
- the same frozen W1-W4 manifest and output lengths;
- batch size 1;
- 2 discarded warmups and 10 measured generations per class per arm per
  session;
- the same primary statistic, medians, bootstrap rules, CV ≤ 5 % noise-floor
  guard, outlier rules, and no-early-stopping rule;
- the same GO / ITERATE / NO-GO / INVALID thresholds and decision table;
- the same F gates and C gates;
- the same TTFT / prefill constraints;
- the same canonical placement (`phase1-qwen36-placement-v2`,
  SHA-256 `2f62bb84df40d4cc5649e940a39cb53d2975eadecbc320fb97d2b037d4e005f4`);
- the same frozen candidate configuration;
- the same session-agreement rule: both sessions are evaluated independently,
  and the worse verdict stands.

What changes is only what was not executable or not fully specified as written:
the physically impossible repetition-level arm ordering; the baseline-identity
gate semantics for the two counterbalanced sessions (Session-1 gate, Session-2
revalidation); and the predeclaration of the §3-rule-2 supplementary
KV-matched arm, whose trigger and pinned capacity are fixed before execution
instead of being discovered — or guessed — later. No threshold, statistic,
gate, workload, arm flag, or decision rule moves.

## Anti-goalpost statement

No canonical Phase-1 candidate performance existed when this amendment was
frozen, so it cannot favor any observed result. Under the previous rule the
campaign could not have been executed at all without destroying the warmed
serving state it purports to measure; under this rule both arms run under the
same frozen thresholds, workload contract, and statistics. No canonical
Phase-1 performance campaign may begin until this amendment is merged.
